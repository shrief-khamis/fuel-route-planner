import json
import logging
import os
import sys

import pytest
from django.conf import settings

from config.logs import JsonFormatter, PlainFormatter

PROJECT_FILE = str(settings.BASE_DIR / 'routing' / 'geo.py')
DEPENDENCY_FILE = os.path.join(sys.prefix, 'lib', 'site-packages', 'django', 'utils', 'log.py')


def make_record(msg='Route found', args=(), level=logging.INFO, pathname=PROJECT_FILE, lineno=7, **extra):
    """Return a log record from the "routing" logger, with the given extra fields."""
    return logging.makeLogRecord({
        'name': 'routing',
        'levelno': level,
        'levelname': logging.getLevelName(level),
        'pathname': pathname,
        'lineno': lineno,
        'msg': msg,
        'args': args,
        **extra,
    })


def format_json(record):
    """Format the record with JsonFormatter and parse the result."""
    text = JsonFormatter(settings.BASE_DIR).format(record)
    assert '\n' not in text
    return json.loads(text)


def raise_in_project():
    """Raise a ValueError from this test file, which is a project file."""
    raise ValueError('bad route')


def captured_exc_info():
    """Return the exc_info of an error raised by raise_in_project()."""
    try:
        raise_in_project()
    except ValueError:
        return sys.exc_info()


def test_fixed_fields():
    """Each line has exactly the time, level, source and message, in that order."""
    entry = format_json(make_record('Took %d ms', (42,), logging.WARNING))
    assert list(entry) == ['time', 'level', 'source', 'message']
    assert entry['time'].endswith('+00:00')
    assert entry['level'] == 'WARNING'
    assert entry['source'] == os.path.join('routing', 'geo.py') + ':7'
    assert entry['message'] == 'Took 42 ms'


def test_extra_fields_go_in_context():
    """Fields passed with extra= are nested under "context", in the order given."""
    entry = format_json(make_record(status=404, provider='ors'))
    assert entry['context'] == {'status': 404, 'provider': 'ors'}


def test_values_that_are_not_json_are_written_as_str():
    """A context value that json cannot encode is written as its str()."""
    class Thing:
        def __str__(self):
            return 'a thing'

    assert format_json(make_record(thing=Thing()))['context'] == {'thing': 'a thing'}


def test_request_extra_is_dropped():
    """Django's HttpRequest extra is left out."""
    entry = format_json(make_record(request=object(), status_code=500))
    assert entry['context'] == {'status_code': 500}


def test_exception_is_included():
    """A logged exception is written as its formatted traceback."""
    entry = format_json(make_record(exc_info=captured_exc_info()))
    assert entry['exception'].startswith('Traceback')
    assert 'ValueError: bad route' in entry['exception']


def test_dependency_error_points_at_project_code():
    """A dependency's record with a traceback gets the innermost project frame as source."""
    record = make_record(pathname=DEPENDENCY_FILE, exc_info=captured_exc_info())
    source = format_json(record)['source']
    assert source.startswith(os.path.join('config', 'tests', 'test_logging.py') + ':')
    assert int(source.rsplit(':', 1)[1]) == raise_in_project.__code__.co_firstlineno + 2


@pytest.mark.parametrize('pathname', [DEPENDENCY_FILE, '/elsewhere/lib.py', '<frozen os>'])
def test_dependency_record_falls_back_to_logger_name(pathname):
    """A record from outside the project, with no traceback, uses the logger name."""
    assert format_json(make_record(pathname=pathname))['source'] == 'routing'


def test_plain_format():
    """Plain lines have the level, source, message and context as key=value pairs."""
    text = PlainFormatter(settings.BASE_DIR).format(make_record('GET /api/', status=200, duration_ms=12))
    assert text.endswith(f" INFO {os.path.join('routing', 'geo.py')}:7: GET /api/ status=200 duration_ms=12")


def test_tests_do_not_write_log_files():
    """The test settings turn the file handler off, whatever .env says."""
    assert settings.LOG_FILE_ENABLED is False
    assert 'file' not in settings.LOGGING['handlers']


def is_written(name, level, with_traceback=False):
    """Return whether a record at this level from this logger would be written anywhere.

    This follows Logger.handle() and Logger.callHandlers() without emitting anything,
    including Python's last-resort handler, which prints WARNING and above to stderr when a
    record finds no handler at all. pytest's own capture handlers are ignored: pytest adds
    them to loggers that do not propagate.
    """
    logger = logging.getLogger(name)
    exc_info = captured_exc_info() if with_traceback else None
    record = logger.makeRecord(name, level, __file__, 1, 'message', (), exc_info)
    if not logger.isEnabledFor(level) or not logger.filter(record):
        return False
    found = False
    while logger is not None:
        for handler in logger.handlers:
            if type(handler).__module__.startswith('_pytest'):
                continue
            found = True
            if (level >= handler.level and not isinstance(handler, logging.NullHandler)
                    and handler.filter(record)):
                return True
        if not logger.propagate:
            break
        logger = logger.parent
    return not found and level >= logging.lastResort.level


@pytest.mark.parametrize(('name', 'level', 'with_traceback', 'written'), [
    ('routing.providers.openrouteservice', logging.INFO, False, True),
    ('api.middleware', logging.INFO, False, True),
    ('httpx', logging.INFO, False, False),
    ('httpx', logging.WARNING, False, True),
    ('django.utils.autoreload', logging.INFO, False, False),
    ('django.request', logging.WARNING, False, False),
    ('django.request', logging.ERROR, False, False),
    ('django.request', logging.ERROR, True, True),
    ('django.server', logging.WARNING, False, False),
    ('django.server', logging.ERROR, False, False),
])
def test_which_records_are_written(name, level, with_traceback, written):
    """Our code logs at LOG_LEVEL and dependencies at WARNING. Of Django's request logs,
    only errors with a traceback are kept, and runserver's access lines are dropped.
    """
    assert is_written(name, level, with_traceback) is written
