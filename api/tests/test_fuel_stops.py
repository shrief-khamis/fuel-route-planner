import pytest
from django.urls import reverse
from rest_framework import status

from routing import LatLon

pytestmark = pytest.mark.django_db

URL = reverse('find-route')
NYC = LatLon(40.7128, -74.0060)
CHICAGO = LatLon(41.8781, -87.6298)
TRIP = {'start': f'{NYC.lat},{NYC.lon}', 'finish': f'{CHICAGO.lat},{CHICAGO.lon}'}
MILE_DEG = 1 / 69.05  # About one mile of latitude.


def on_line(t, north_miles=0):
    """Return the point a fraction t of the way along the fake NYC-Chicago line."""
    return NYC.lat + (CHICAGO.lat - NYC.lat) * t + north_miles * MILE_DEG, NYC.lon + (CHICAGO.lon - NYC.lon) * t


def test_stops_at_the_cheapest_station_in_reach(api_client, make_station):
    """Of two stations in reach of the full tank, the trip stops at the cheaper one."""
    make_station(*on_line(0.4), 3.50)
    cheap = make_station(*on_line(0.6), 3.00)

    response = api_client.get(URL, TRIP)

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    [stop] = data['stops']
    assert stop['station'] == {
        'opis_id': cheap.opis_id, 'name': cheap.name, 'address': cheap.address,
        'city': 'Town', 'state': 'PA', 'lat': cheap.lat, 'lon': cheap.lon,
        'location_precision': 'exit',
    }
    assert stop['price_per_gallon'] == 3.0
    # A fraction of the way in degrees is only roughly that fraction of the distance.
    trip_miles = data['distance_m'] / 1609.344
    along = stop['distance_from_start_miles']
    assert along == pytest.approx(0.6 * trip_miles, rel=0.01)
    assert stop['offset_miles'] < 0.1
    assert stop['fuel_on_arrival_miles'] == pytest.approx(500 - along, abs=0.2)
    assert stop['fuel_added_miles'] == pytest.approx(trip_miles - along - stop['fuel_on_arrival_miles'], abs=0.2)
    assert stop['gallons'] == pytest.approx(stop['fuel_added_miles'] / 10, abs=0.01)
    assert stop['cost'] == pytest.approx(stop['gallons'] * 3.0, abs=0.01)
    assert data['total_cost'] == stop['cost']
    assert data['total_gallons'] == stop['gallons']
    assert data['total_detour_miles'] == pytest.approx(2 * stop['offset_miles'], abs=0.01)


def test_no_stops_when_the_tank_covers_the_trip(api_client):
    """An 800-mile tank covers the trip without stopping."""
    data = api_client.get(URL, TRIP | {'max_range_miles': 800}).json()
    assert data['stops'] == []
    assert data['total_cost'] == 0
    assert data['total_gallons'] == 0


def test_no_feasible_plan(api_client, make_station):
    """A trip that no station can complete gives a 422."""
    make_station(*on_line(0.9), 3.0)

    response = api_client.get(URL, TRIP)

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert response.json()['code'] == 'no_feasible_fuel_plan'


def test_start_fuel_and_reserve(api_client, make_station):
    """A half tank and a reserve force an earlier stop, and the reserve is kept on arrival."""
    make_station(*on_line(0.3), 3.0)
    make_station(*on_line(0.6), 3.0)

    data = api_client.get(URL, TRIP | {'start_fuel_miles': 250, 'reserve_miles': 20}).json()

    first = data['stops'][0]
    assert first['distance_from_start_miles'] < 230
    assert first['fuel_on_arrival_miles'] >= 20


def test_corridor_width(api_client, make_station):
    """A station 5 miles off the route is used only with a wider corridor."""
    make_station(*on_line(0.5, north_miles=5), 3.0)

    assert api_client.get(URL, TRIP).status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    data = api_client.get(URL, TRIP | {'corridor_miles': 6}).json()
    [stop] = data['stops']
    assert stop['offset_miles'] == pytest.approx(5, rel=0.05)
    assert data['total_detour_miles'] == pytest.approx(10, rel=0.05)


def test_mpg_scales_the_gallons(api_client, make_station):
    """At 5 mpg the same stop buys twice the gallons it does at 10 mpg."""
    make_station(*on_line(0.5), 3.0)

    at_10 = api_client.get(URL, TRIP).json()['stops'][0]
    at_5 = api_client.get(URL, TRIP | {'mpg': 5}).json()['stops'][0]

    assert at_5['fuel_added_miles'] == at_10['fuel_added_miles']
    assert at_5['gallons'] == pytest.approx(2 * at_10['gallons'], abs=0.01)


@pytest.mark.parametrize('min_stop_saving, stops', [(0, 2), (5, 1)])
def test_min_stop_saving(api_client, make_station, min_stop_saving, stops):
    """An extra stop that saves less than min_stop_saving is skipped.

    The trip can't finish from the station at 20%, so the one at 60% is needed. Filling up
    at 20% first saves about 14 cents.
    """
    make_station(*on_line(0.2), 3.00)
    make_station(*on_line(0.6), 3.01)

    data = api_client.get(URL, TRIP | {'min_stop_saving': min_stop_saving}).json()
    assert len(data['stops']) == stops


@pytest.mark.parametrize('params, field', [
    ({'max_range_miles': 0}, 'max_range_miles'),
    ({'max_range_miles': -5}, 'max_range_miles'),
    ({'max_range_miles': 3001}, 'max_range_miles'),
    ({'max_range_miles': 'abc'}, 'max_range_miles'),
    ({'max_range_miles': 'nan'}, 'max_range_miles'),
    ({'start_fuel_miles': 0}, 'start_fuel_miles'),
    ({'start_fuel_miles': 501}, 'start_fuel_miles'),
    ({'start_fuel_miles': 50, 'reserve_miles': 50}, 'start_fuel_miles'),
    ({'reserve_miles': -1}, 'reserve_miles'),
    ({'reserve_miles': 251}, 'reserve_miles'),
    ({'max_range_miles': 100, 'reserve_miles': 51}, 'reserve_miles'),
    ({'mpg': 0}, 'mpg'),
    ({'mpg': 151}, 'mpg'),
    ({'corridor_miles': 0}, 'corridor_miles'),
    ({'corridor_miles': 15.1}, 'corridor_miles'),
    ({'min_stop_saving': -1}, 'min_stop_saving'),
    ({'min_stop_saving': 'inf'}, 'min_stop_saving'),
])
def test_invalid_fuel_settings(api_client, params, field):
    """Fuel settings out of range give a 400 for that field."""
    response = api_client.get(URL, TRIP | params)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert list(response.data) == [field]


def test_fuel_errors_are_listed_together(api_client):
    """Cross-field errors are reported together with the distance check."""
    response = api_client.get(URL, {
        'start': TRIP['start'], 'finish': TRIP['start'],
        'reserve_miles': 300, 'start_fuel_miles': 600,
    })
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert set(response.data) == {'non_field_errors', 'reserve_miles', 'start_fuel_miles'}


@pytest.mark.parametrize('params', [
    {'max_range_miles': 3000},
    {'reserve_miles': 250},
    {'start_fuel_miles': 500},
    {'mpg': 150},
    {'corridor_miles': 15},
    {'min_stop_saving': 0},
])
def test_limits_are_inclusive(api_client, stub_provider, params):
    """The largest allowed values are accepted."""
    stub_provider()
    assert api_client.get(URL, TRIP | params).status_code == status.HTTP_200_OK
