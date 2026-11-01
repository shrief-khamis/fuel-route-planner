import pytest

from routing import LatLon, haversine_m

NYC = LatLon(40.7128, -74.0060)
CHICAGO = LatLon(41.8781, -87.6298)


def test_same_point_is_zero():
    """The distance from a point to itself is 0."""
    assert haversine_m(NYC, NYC) == 0


def test_nyc_to_chicago():
    """New York to Chicago is about 1,145 km."""
    assert haversine_m(NYC, CHICAGO) == pytest.approx(1_145_000, rel=0.005)


def test_is_symmetric():
    """The distance is the same in both directions."""
    assert haversine_m(NYC, CHICAGO) == pytest.approx(haversine_m(CHICAGO, NYC))


def test_one_degree_of_latitude():
    """One degree of latitude is about 111.2 km."""
    assert haversine_m(LatLon(0, 0), LatLon(1, 0)) == pytest.approx(111_195, abs=1)
