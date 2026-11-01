import pytest

from routing import InvalidRouteRequest, LatLon, Profile
from routing.providers.fake import FakeRoutingProvider

A = LatLon(32.7767, -96.7970)
B = LatLon(32.9000, -96.7000)
C = LatLon(33.0000, -96.6000)


def test_two_waypoints():
    """Two waypoints give one leg that starts and ends at them."""
    route = FakeRoutingProvider(points_per_leg=10).route([A, B], Profile.TRUCK)
    assert len(route.points) == 10
    assert route.points[0] == A
    assert route.points[-1] == B
    assert route.distance_m > 0
    assert route.duration_s > 0


def test_three_waypoints_have_no_duplicate_joints():
    """The point shared by two legs appears only once."""
    route = FakeRoutingProvider(points_per_leg=5).route([A, B, C], Profile.TRUCK)
    assert len(route.points) == 9
    assert route.points[0] == A
    assert route.points[4] == B
    assert route.points[-1] == C
    assert all(p != q for p, q in zip(route.points, route.points[1:]))


def test_car_is_faster_than_truck():
    """Car and truck share the distance, but the car is faster."""
    provider = FakeRoutingProvider()
    truck = provider.route([A, B], Profile.TRUCK)
    car = provider.route([A, B], Profile.CAR)
    assert truck.distance_m == car.distance_m
    assert car.duration_s < truck.duration_s


def test_is_deterministic():
    """The same input gives the same route."""
    provider = FakeRoutingProvider()
    assert provider.route([A, B], Profile.CAR) == provider.route([A, B], Profile.CAR)


@pytest.mark.parametrize('waypoints', [[], [A]])
def test_too_few_waypoints(waypoints):
    """Fewer than two waypoints raise InvalidRouteRequest."""
    with pytest.raises(InvalidRouteRequest):
        FakeRoutingProvider().route(waypoints, Profile.TRUCK)
