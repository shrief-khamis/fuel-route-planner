import json
from pathlib import Path

import httpx
import pytest

from routing import InvalidRouteRequest, LatLon, Profile, RouteNotFound, RoutingUnavailable
from routing.providers.openrouteservice import SNAP_RADIUS_M, OpenRouteServiceProvider

FIXTURES = Path(__file__).parent / 'fixtures'
TEST_KEY = 'test-key'
BASE_URL = 'https://ors.test/openrouteservice'
START = LatLon(32.7767, -96.7970)
FINISH = LatLon(32.8998, -96.7300)


def load_fixture(name):
    """Load a recorded ORS response fixture by file name."""
    return json.loads((FIXTURES / name).read_text())


def fixture_response(name):
    """Build an httpx response from a recorded ORS fixture."""
    fixture = load_fixture(name)
    return httpx.Response(fixture['status'], json=fixture['body'])


def make_provider(handler, api_key=TEST_KEY):
    """Build an ORS provider whose requests go to the given mock handler."""
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OpenRouteServiceProvider(api_key=api_key, base_url=BASE_URL, client=client)


class Recorder:
    """A mock transport handler that records requests and returns a set response."""

    def __init__(self, response):
        """Store the response to return."""
        self.response = response
        self.requests = []

    def __call__(self, request):
        """Record the request and return the set response."""
        self.requests.append(request)
        return self.response


@pytest.mark.parametrize(
    'profile, ors_profile',
    [(Profile.TRUCK, 'driving-hgv'), (Profile.CAR, 'driving-car')],
)
def test_request_shape(profile, ors_profile):
    """The request has the right URL, headers and body for each profile."""
    handler = Recorder(fixture_response(f'ors_success_{ors_profile.split("-")[1]}.json'))
    make_provider(handler).route([START, FINISH], profile)

    [request] = handler.requests
    assert request.method == 'POST'
    assert request.url == f'{BASE_URL}/v2/directions/{ors_profile}/geojson'
    assert request.headers['Authorization'] == TEST_KEY
    assert request.headers['Content-Type'] == 'application/json'
    body = json.loads(request.content)
    assert body['coordinates'] == [[START.lon, START.lat], [FINISH.lon, FINISH.lat]]
    assert body['radiuses'] == [SNAP_RADIUS_M, SNAP_RADIUS_M]
    assert body['instructions'] is False
    assert body['options'] == {'avoid_borders': 'all'}


@pytest.mark.parametrize(
    'name, profile',
    [('ors_success_hgv.json', Profile.TRUCK), ('ors_success_car.json', Profile.CAR)],
)
def test_parses_success(name, profile):
    """A recorded success response becomes a Route in (lat, lon) order."""
    feature = load_fixture(name)['body']['features'][0]
    coords = feature['geometry']['coordinates']
    summary = feature['properties']['summary']

    route = make_provider(lambda request: fixture_response(name)).route([START, FINISH], profile)

    assert len(route.points) == len(coords)
    assert route.points[0] == LatLon(coords[0][1], coords[0][0])
    assert route.points[-1] == LatLon(coords[-1][1], coords[-1][0])
    assert all(isinstance(p, LatLon) for p in route.points)
    assert route.distance_m == summary['distance']
    assert route.duration_s == summary['duration']


def test_missing_summary_values_default_to_zero():
    """A missing distance or duration counts as 0."""
    body = {'features': [{
        'geometry': {'coordinates': [[START.lon, START.lat], [FINISH.lon, FINISH.lat]]},
        'properties': {'summary': {}},
    }]}
    route = make_provider(lambda request: httpx.Response(200, json=body)).route([START, FINISH], Profile.CAR)
    assert route.points == [START, FINISH]
    assert route.distance_m == 0
    assert route.duration_s == 0


@pytest.mark.parametrize(
    'name, error',
    [
        ('ors_error_point_not_found.json', RouteNotFound),
        ('ors_error_route_not_found.json', RouteNotFound),
        ('ors_error_limit_exceeded.json', InvalidRouteRequest),
        ('ors_error_bad_request.json', RoutingUnavailable),
        ('ors_error_unauthorized.json', RoutingUnavailable),
        ('ors_error_rate_limited_synthetic.json', RoutingUnavailable),
        ('ors_error_server_synthetic.json', RoutingUnavailable),
    ],
)
def test_error_mapping(name, error):
    """Each recorded ORS error maps to our error, without the ORS message."""
    provider = make_provider(lambda request: fixture_response(name))
    with pytest.raises(error) as exc_info:
        provider.route([START, FINISH], Profile.TRUCK)
    message = load_fixture(name)['body']['error']
    message = message['message'] if isinstance(message, dict) else message
    assert message not in str(exc_info.value)


@pytest.mark.parametrize(
    'response',
    [
        httpx.Response(200, content=b'not json'),
        httpx.Response(200, json={}),
        httpx.Response(200, json={'features': []}),
        httpx.Response(200, json={'features': [{'geometry': {'coordinates': 'bad'}, 'properties': {}}]}),
        httpx.Response(200, json={'features': [{'geometry': {'coordinates': [[1.0, 2.0]]}, 'properties': {}}]}),
        httpx.Response(502, content=b'<html>Bad Gateway</html>'),
        httpx.Response(404, content=b'not json'),
    ],
)
def test_unexpected_responses(response):
    """Malformed or unexpected responses raise RoutingUnavailable."""
    provider = make_provider(lambda request: response)
    with pytest.raises(RoutingUnavailable):
        provider.route([START, FINISH], Profile.TRUCK)


@pytest.mark.parametrize('exc', [httpx.ConnectTimeout('timeout'), httpx.ConnectError('refused')])
def test_transport_errors(exc):
    """Timeouts and network errors raise RoutingUnavailable."""
    def handler(request):
        """Raise the transport error."""
        raise exc

    with pytest.raises(RoutingUnavailable) as exc_info:
        make_provider(handler).route([START, FINISH], Profile.TRUCK)
    assert exc_info.value.__cause__ is exc


def test_empty_api_key_makes_no_request():
    """An empty API key fails without sending a request."""
    handler = Recorder(fixture_response('ors_success_hgv.json'))
    with pytest.raises(RoutingUnavailable):
        make_provider(handler, api_key='').route([START, FINISH], Profile.TRUCK)
    assert handler.requests == []


@pytest.mark.parametrize('waypoints', [[], [START]])
def test_too_few_waypoints(waypoints):
    """Fewer than two waypoints fail without sending a request."""
    handler = Recorder(fixture_response('ors_success_hgv.json'))
    with pytest.raises(InvalidRouteRequest):
        make_provider(handler).route(waypoints, Profile.TRUCK)
    assert handler.requests == []
