"""Log formatters and filters used by the LOGGING setting.

Both formatters write the same fields: the time, level, source, message, the traceback if
there is one, and the context (the fields passed with `extra=`). The source is always a
place in this project, never in a dependency; see ProjectFormatter.source().
"""

import functools
import json
import logging
import os
import sys
import traceback
from contextvars import ContextVar
from datetime import UTC, datetime

# Attributes every LogRecord has. Anything else on a record was passed with `extra=`.
RECORD_ATTRS = frozenset(vars(logging.makeLogRecord({}))) | {'message', 'asctime'}

# Extras to leave out. Django passes the HttpRequest as `request` with its 5xx errors; the
# path is already in the message.
DROPPED_EXTRAS = frozenset({'request'})

# The ID of the request being handled, set by api.middleware.AccessLogMiddleware. None
# outside a request, e.g. in management commands.
request_id: ContextVar[str | None] = ContextVar('request_id', default=None)

# Installed packages live here, even when the virtualenv is inside the project.
PYTHON_DIRS = tuple({sys.prefix, sys.base_prefix, sys.exec_prefix})


def is_within(path: str, directory: str) -> bool:
    """Return whether the absolute path is inside the directory."""
    return path.startswith(directory.rstrip(os.sep) + os.sep)


@functools.cache
def project_path(filename: str, project_root: str) -> str | None:
    """Return the file's path relative to the project root, if it is a project file.

    Args:
        filename: A source file path, as in a log record or code object.
        project_root: The absolute path of the project root.

    Returns:
        The relative path, or None for files outside the project and installed packages,
        and for names that are not paths, such as "<frozen os>".
    """
    if not os.path.isabs(filename):
        return None
    path = os.path.normpath(filename)
    if not is_within(path, project_root) or any(is_within(path, d) for d in PYTHON_DIRS):
        return None
    if 'site-packages' in path.split(os.sep):
        return None
    return os.path.relpath(path, project_root)


class TracebackOnlyFilter(logging.Filter):
    """Keep only records that carry a traceback."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Return whether the record has exception info."""
        return bool(record.exc_info)


class RequestIdFilter(logging.Filter):
    """Add the current request's ID to each record, as a "request_id" context field.

    Records logged outside a request are left unchanged.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Add the request ID, if there is one, and keep the record."""
        current = request_id.get()
        if current is not None:
            record.request_id = current
        return True


class ProjectFormatter(logging.Formatter):
    """Base class for formatters that report where in this project a record came from.

    Attributes:
        project_root: The absolute path of the project root.
    """

    def __init__(self, project_root: str | os.PathLike):
        """Create the formatter.

        Args:
            project_root: The project root. Files under it, except installed packages,
                count as project files.
        """
        super().__init__()
        self.project_root = os.path.abspath(project_root)

    def source(self, record: logging.LogRecord) -> str:
        """Return the project file and line that the record came from.

        Args:
            record: The record.

        Returns:
            "path/to/file.py:LINE" for the logging call when it is in a project file.
            Otherwise, the innermost project frame of the record's traceback, so a
            dependency's error points at our code. Otherwise, the logger name.
        """
        path = project_path(record.pathname, self.project_root)
        if path is not None:
            return f'{path}:{record.lineno}'
        if record.exc_info and record.exc_info[2] is not None:
            source = None
            for frame, lineno in traceback.walk_tb(record.exc_info[2]):
                path = project_path(frame.f_code.co_filename, self.project_root)
                if path is not None:
                    source = f'{path}:{lineno}'
            if source is not None:
                return source
        return record.name

    def context(self, record: logging.LogRecord) -> dict:
        """Return the fields passed with `extra=`, in the order they were given."""
        return {
            key: value
            for key, value in vars(record).items()
            if key not in RECORD_ATTRS and key not in DROPPED_EXTRAS
        }


class PlainFormatter(ProjectFormatter):
    """Format records as human-readable text.

    Lines look like "2026-11-01 21:36:16,407 INFO api/middleware.py:40: GET /api/
    status=200 duration_ms=12", followed by the traceback if there is one.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Return the record as text.

        Args:
            record: The record to format.

        Returns:
            The text, without a trailing newline.
        """
        text = f'{self.formatTime(record)} {record.levelname} {self.source(record)}: {record.getMessage()}'
        context = self.context(record)
        if context:
            text += ' ' + ' '.join(f'{key}={value}' for key, value in context.items())
        if record.exc_info:
            text += '\n' + self.formatException(record.exc_info)
        if record.stack_info:
            text += '\n' + self.formatStack(record.stack_info)
        return text


class JsonFormatter(ProjectFormatter):
    """Format each record as a single line of JSON.

    Every line has "time" (ISO 8601, UTC), "level", "source" and "message". "exception",
    "stack" and "context" are added only when the record has them. Context values that are
    not JSON types are written as their str().
    """

    def format(self, record: logging.LogRecord) -> str:
        """Return the record as a JSON object on one line.

        Args:
            record: The record to format.

        Returns:
            The JSON text, without a trailing newline.
        """
        entry = {
            'time': datetime.fromtimestamp(record.created, UTC).isoformat(timespec='milliseconds'),
            'level': record.levelname,
            'source': self.source(record),
            'message': record.getMessage(),
        }
        if record.exc_info:
            entry['exception'] = self.formatException(record.exc_info)
        if record.stack_info:
            entry['stack'] = self.formatStack(record.stack_info)
        context = self.context(record)
        if context:
            entry['context'] = context
        return json.dumps(entry, default=str, ensure_ascii=False)
