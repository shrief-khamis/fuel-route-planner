import logging
import time

logger = logging.getLogger(__name__)


class AccessLogMiddleware:
    """Log one line per request: the method and path, with the status and duration.

    Successful responses are logged at INFO, 4xx at WARNING and 5xx at ERROR. Put this
    first in MIDDLEWARE so the duration covers the other middleware too.
    """

    def __init__(self, get_response):
        """Store the next handler in the chain."""
        self.get_response = get_response

    def __call__(self, request):
        """Handle the request, then log it.

        Args:
            request: The request.

        Returns:
            The response, unchanged.
        """
        start = time.perf_counter()
        response = self.get_response(request)
        duration_ms = round((time.perf_counter() - start) * 1000)

        context = {'status': response.status_code, 'duration_ms': duration_ms}
        if request.META.get('QUERY_STRING'):
            context['query'] = request.META['QUERY_STRING']
        if response.status_code >= 500:
            level = logging.ERROR
        elif response.status_code >= 400:
            level = logging.WARNING
        else:
            level = logging.INFO
        logger.log(level, '%s %s', request.method, request.path, extra=context)
        return response
