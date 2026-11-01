import pytest
from django.urls import reverse
from rest_framework import status

from api.validators import US_MAX_LAT, US_MAX_LON, US_MIN_LAT, US_MIN_LON
from routing import InvalidRouteRequest, LatLon, Profile, Route, RouteNotFound, RoutingUnavailable

URL = reverse('find-route')
NYC = '40.7128,-74.0060'
CHICAGO = '41.8781,-87.6298'
US_MESSAGE = 'Point must be within the contiguous United States.'


def test_valid_request_uses_fake_provider(api_client):
    """A valid request returns 200 with the full response shape."""
    response = api_client.get(URL, {'start': NYC, 'finish': CHICAGO})

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert set(data) == {'profile', 'start', 'finish', 'distance_m', 'duration_s', 'points'}
    assert data['profile'] == 'truck'
    assert data['start'] == {'lat': 40.7128, 'lon': -74.006}
    assert data['finish'] == {'lat': 41.8781, 'lon': -87.6298}
    assert data['distance_m'] > 0
    assert data['duration_s'] > 0
    assert data['points'][0] == [40.7128, -74.006]
    assert data['points'][-1] == [41.8781, -87.6298]


def test_route_is_passed_through(api_client, stub_provider):
    """The provider's route appears unchanged in the response."""
    stub_provider(Route(points=[LatLon(40.7, -74.0), LatLon(41.8, -87.6)], distance_m=12.5, duration_s=3.5))

    data = api_client.get(URL, {'start': NYC, 'finish': CHICAGO}).json()

    assert data['points'] == [[40.7, -74.0], [41.8, -87.6]]
    assert data['distance_m'] == 12.5
    assert data['duration_s'] == 3.5


def test_provider_receives_waypoints_and_default_profile(api_client, stub_provider):
    """The provider gets [start, finish] as LatLon and the truck profile by default."""
    stub = stub_provider()
    api_client.get(URL, {'start': NYC, 'finish': CHICAGO})

    [(waypoints, profile)] = stub.calls
    assert waypoints == [LatLon(40.7128, -74.006), LatLon(41.8781, -87.6298)]
    assert all(isinstance(p, LatLon) for p in waypoints)
    assert profile is Profile.TRUCK


def test_car_profile(api_client, stub_provider):
    """profile=car reaches the provider as Profile.CAR."""
    stub = stub_provider()
    response = api_client.get(URL, {'start': NYC, 'finish': CHICAGO, 'profile': 'car'})

    assert response.status_code == status.HTTP_200_OK
    assert response.json()['profile'] == 'car'
    assert stub.calls[0][1] is Profile.CAR


def test_whitespace_around_coordinates_is_allowed(api_client):
    """Spaces around the numbers in a coordinate are accepted."""
    response = api_client.get(URL, {'start': ' 40.7128 , -74.0060 ', 'finish': CHICAGO})
    assert response.status_code == status.HTTP_200_OK


def test_missing_params(api_client):
    """Missing start and finish give a 400 for both fields."""
    response = api_client.get(URL)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert 'start' in response.data
    assert 'finish' in response.data


@pytest.mark.parametrize(
    'value',
    ['abc', '40.7', '40.7,-74,5', '40.7;-74', '', 'nan,1', '40.7,inf', '40.7,', ',-74'],
)
def test_malformed_coordinates(api_client, value):
    """Malformed coordinates give a 400 for that field."""
    response = api_client.get(URL, {'start': value, 'finish': CHICAGO})
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert list(response.data) == ['start']


@pytest.mark.parametrize('value', ['90.1,-74', '-91,-74', '40,180.5', '40,-181'])
def test_out_of_range_coordinates(api_client, value):
    """Out-of-range coordinates give a range error, not the US box error."""
    response = api_client.get(URL, {'start': NYC, 'finish': value})
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert list(response.data) == ['finish']
    assert US_MESSAGE not in response.data['finish']


@pytest.mark.parametrize('value', ['21.3,-157.8', '61.2,-149.9', '51.5,-0.1'])
def test_outside_contiguous_us(api_client, value):
    """Points outside the contiguous US box give a 400."""
    response = api_client.get(URL, {'start': value, 'finish': CHICAGO})
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.data['start'] == [US_MESSAGE]


def test_box_boundary_is_inclusive(api_client):
    """Points on the edge of the US box are accepted."""
    response = api_client.get(URL, {
        'start': f'{US_MIN_LAT},{US_MIN_LON}',
        'finish': f'{US_MAX_LAT},{US_MAX_LON}',
    })
    assert response.status_code == status.HTTP_200_OK


def test_invalid_profile(api_client):
    """An unknown profile gives a 400."""
    response = api_client.get(URL, {'start': NYC, 'finish': CHICAGO, 'profile': 'bike'})
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert list(response.data) == ['profile']


@pytest.mark.parametrize('finish', [NYC, '40.7173,-74.0060'])  # same point, ~500 m north
def test_points_too_close(api_client, finish):
    """start and finish less than 1 km apart give a non-field 400."""
    response = api_client.get(URL, {'start': NYC, 'finish': finish})
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert list(response.data) == ['non_field_errors']


def test_points_2km_apart(api_client):
    """start and finish 2 km apart are accepted."""
    response = api_client.get(URL, {'start': NYC, 'finish': '40.7308,-74.0060'})
    assert response.status_code == status.HTTP_200_OK


def test_field_errors_skip_distance_check(api_client):
    """Field errors are returned without the distance check."""
    response = api_client.get(URL, {'start': '21.3,-157.8', 'finish': '21.3,-157.8'})
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert 'non_field_errors' not in response.data


@pytest.mark.parametrize(
    'error, http_status, code',
    [
        (RouteNotFound('ORS 2010 raw message'), 422, 'route_not_found'),
        (InvalidRouteRequest('ORS 2004 raw message'), 422, 'invalid_route_request'),
        (RoutingUnavailable('ORS 403 raw message'), 503, 'routing_unavailable'),
    ],
)
def test_routing_errors(api_client, stub_provider, error, http_status, code):
    """Routing errors map to 422 or 503 with a generic body."""
    stub_provider(error)
    response = api_client.get(URL, {'start': NYC, 'finish': CHICAGO})

    assert response.status_code == http_status
    data = response.json()
    assert set(data) == {'detail', 'code'}
    assert data['code'] == code
    assert 'ORS' not in data['detail']
    assert 'raw message' not in response.content.decode()


def test_post_not_allowed(api_client):
    """POST gives a 405."""
    response = api_client.post(URL, {}, format='json')
    assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
