import logging

import pytest
from django.urls import reverse

from config.logs import request_id
from routing import RoutingUnavailable

URL = reverse('find-route')
NYC = '40.7128,-74.0060'
CHICAGO = '41.8781,-87.6298'
PHILADELPHIA = '39.9526,-75.1652'


def access_records(caplog):
    """Return the records logged by AccessLogMiddleware."""
    return [r for r in caplog.records if r.name == 'api.middleware']


@pytest.mark.django_db
def test_request_is_logged(api_client, caplog):
    """A request logs its method and path, with the status, duration and query."""
    with caplog.at_level(logging.INFO, logger='api.middleware'):
        api_client.get(URL, {'start': NYC, 'finish': PHILADELPHIA, 'mpg': '6.5'})

    [record] = access_records(caplog)
    assert record.levelno == logging.INFO
    assert record.getMessage() == f'GET {URL}'
    assert record.status == 200
    assert record.duration_ms >= 0
    assert record.query == 'start=40.71,-74.01&finish=39.95,-75.17&mpg=6.5'


def test_malformed_locations_are_rounded_too(api_client, caplog):
    """Coordinates are rounded in the log even when the value is not valid."""
    with caplog.at_level(logging.INFO, logger='api.middleware'):
        api_client.get(URL, {'start': '(40.7128 -74.0060)', 'finish': ''})

    [record] = access_records(caplog)
    assert record.query == 'start=%2840.71+-74.01%29&finish='


def test_client_error_is_info(api_client, caplog):
    """A 4xx response is intentional behavior, so it is logged at INFO."""
    with caplog.at_level(logging.INFO, logger='api.middleware'):
        api_client.get(URL)

    [record] = access_records(caplog)
    assert record.levelno == logging.INFO
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


@pytest.mark.django_db
def test_request_id_is_set_while_handling_the_request(api_client, stub_provider):
    """The request ID is set during the request, returned in X-Request-ID, then cleared."""
    stub = stub_provider()
    seen = []
    route = stub.route
    stub.route = lambda waypoints, profile: seen.append(request_id.get()) or route(waypoints, profile)

    response = api_client.get(URL, {'start': NYC, 'finish': PHILADELPHIA})

    assert len(response['X-Request-ID']) == 32
    assert seen == [response['X-Request-ID']]
    assert request_id.get() is None


def test_each_request_gets_its_own_id(api_client):
    """Two requests get different IDs."""
    first = api_client.get(URL)['X-Request-ID']
    second = api_client.get(URL)['X-Request-ID']
    assert first != second
