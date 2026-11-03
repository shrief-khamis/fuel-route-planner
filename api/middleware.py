import logging
import time
import uuid
from urllib.parse import parse_qsl, urlencode

from config.logs import request_id
from routing import round_coordinates

logger = logging.getLogger(__name__)

# Query parameters that hold a location. Their coordinates are rounded in the log.
LOCATION_PARAMS = frozenset({'start', 'finish'})


def loggable_query(query_string):
    """Return the query string with the coordinates of the location parameters rounded.

    Args:
        query_string: The raw query string.

    Returns:
        The query string, re-encoded, with commas left readable.
    """
    params = parse_qsl(query_string, keep_blank_values=True)
    return urlencode(
        [(key, round_coordinates(value) if key in LOCATION_PARAMS else value) for key, value in params],
        safe=',',
    )


class AccessLogMiddleware:
    """Give each request an ID, and log one line per request.

    The line has the method and path, with the status, duration and query. Server errors
    (5xx) are logged at ERROR and everything else at INFO, since a 4xx is intentional
    behavior. Every record logged while the request is handled carries its ID, which is
    also returned in the X-Request-ID header. Put this first in MIDDLEWARE so the duration
    covers the other middleware too.
    """

    def __init__(self, get_response):
        """Store the next handler in the chain."""
        self.get_response = get_response

    def __call__(self, request):
        """Handle the request with a new request ID, then log it.

        Args:
            request: The request.

        Returns:
            The response, with an X-Request-ID header.
        """
        current = uuid.uuid4().hex
        token = request_id.set(current)
        try:
            start = time.perf_counter()
            response = self.get_response(request)
            duration_ms = round((time.perf_counter() - start) * 1000)

            context = {'status': response.status_code, 'duration_ms': duration_ms}
            if request.META.get('QUERY_STRING'):
                context['query'] = loggable_query(request.META['QUERY_STRING'])
            level = logging.ERROR if response.status_code >= 500 else logging.INFO
            logger.log(level, '%s %s', request.method, request.path, extra=context)
        finally:
            request_id.reset(token)
        response['X-Request-ID'] = current
        return response
