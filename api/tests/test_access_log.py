import logging

from django.urls import reverse

from routing import RoutingUnavailable

URL = reverse('find-route')
NYC = '40.7128,-74.0060'
CHICAGO = '41.8781,-87.6298'


def access_records(caplog):
    """Return the records logged by AccessLogMiddleware."""
    return [r for r in caplog.records if r.name == 'api.middleware']


def test_request_is_logged(api_client, caplog):
    """A request logs its method and path, with the status, duration and query."""
    with caplog.at_level(logging.INFO, logger='api.middleware'):
        api_client.get(URL, {'start': NYC, 'finish': CHICAGO})

    [record] = access_records(caplog)
    assert record.levelno == logging.INFO
    assert record.getMessage() == f'GET {URL}'
    assert record.status == 200
    assert record.duration_ms >= 0
    assert record.query == 'start=40.7128%2C-74.0060&finish=41.8781%2C-87.6298'


def test_client_error_is_a_warning(api_client, caplog):
    """A 4xx response is logged at WARNING."""
    with caplog.at_level(logging.INFO, logger='api.middleware'):
        api_client.get(URL)

    [record] = access_records(caplog)
    assert record.levelno == logging.WARNING
    assert record.status == 400


def test_server_error_is_an_error(api_client, caplog, stub_provider):
    """A 5xx response is logged at ERROR."""
    stub_provider(RoutingUnavailable('down'))
    with caplog.at_level(logging.INFO, logger='api.middleware'):
        api_client.get(URL, {'start': NYC, 'finish': CHICAGO})

    [record] = access_records(caplog)
    assert record.levelno == logging.ERROR
    assert record.status == 503


def test_no_query_means_no_query_field(api_client, caplog):
    """Requests without a query string have no "query" field."""
    with caplog.at_level(logging.INFO, logger='api.middleware'):
        api_client.get(URL)

    [record] = access_records(caplog)
    assert not hasattr(record, 'query')
