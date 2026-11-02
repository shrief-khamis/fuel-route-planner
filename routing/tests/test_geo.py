import pytest

from routing import LatLon, Polyline, haversine_m

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


def test_polyline_needs_two_points():
    """A line with fewer than two points is rejected."""
    with pytest.raises(ValueError):
        Polyline([NYC])


def test_polyline_length_is_the_sum_of_its_segments():
    """The length and cumulative distances add up the haversine distance of each segment."""
    middle = LatLon(41.0, -80.0)
    line = Polyline([NYC, middle, CHICAGO])

    assert line.cumulative_m == [0.0, haversine_m(NYC, middle), haversine_m(NYC, middle) + haversine_m(middle, CHICAGO)]
    assert line.length_m == line.cumulative_m[-1]


def test_locate_projects_onto_a_segment():
    """A point 1 km north of a segment's middle is 1 km off, halfway along."""
    line = Polyline([LatLon(40.0, -100.0), LatLon(40.0, -99.0)])
    km_north = 1000 / 111_195

    position = line.locate(LatLon(40.0 + km_north, -99.5), max_offset_m=2000)

    assert position.offset_m == pytest.approx(1000, rel=0.01)
    assert position.along_m == pytest.approx(line.length_m / 2, rel=0.001)


def test_locate_outside_max_offset():
    """A point further than max_offset_m from the line is not located."""
    line = Polyline([LatLon(40.0, -100.0), LatLon(40.0, -99.0)])
    assert line.locate(LatLon(40.1, -99.5), max_offset_m=5000) is None


def test_locate_beyond_the_ends():
    """Points past either end are measured to that end."""
    line = Polyline([LatLon(40.0, -100.0), LatLon(40.0, -99.0)])

    before = line.locate(LatLon(40.0, -100.01), max_offset_m=5000)
    after = line.locate(LatLon(40.0, -98.99), max_offset_m=5000)

    assert before.along_m == 0
    assert after.along_m == pytest.approx(line.length_m)
    assert before.offset_m == pytest.approx(haversine_m(LatLon(40.0, -100.01), LatLon(40.0, -100.0)))


def test_locate_picks_the_nearest_part_of_the_line():
    """On a line that doubles back, the nearer leg wins."""
    line = Polyline([LatLon(40.0, -100.0), LatLon(40.0, -99.0), LatLon(40.02, -99.0), LatLon(40.02, -100.0)])

    position = line.locate(LatLon(40.015, -99.5), max_offset_m=5000)

    assert position.along_m > line.cumulative_m[2]
    assert position.offset_m == pytest.approx(haversine_m(LatLon(40.015, -99.5), LatLon(40.02, -99.5)), rel=0.01)


def test_locate_on_a_long_segment():
    """A segment spanning many grid cells is found from any of them."""
    line = Polyline([NYC, CHICAGO])
    middle = LatLon((NYC.lat + CHICAGO.lat) / 2, (NYC.lon + CHICAGO.lon) / 2)

    position = line.locate(middle, max_offset_m=1000)

    assert position.offset_m < 1000
    assert position.along_m == pytest.approx(line.length_m / 2, rel=0.01)


def test_bounding_box_with_margin():
    """The box covers every point, extended by the margin on each side."""
    line = Polyline([NYC, LatLon(41.0, -80.0), CHICAGO])

    south_west, north_east = line.bounding_box(margin_m=10_000)

    assert south_west.lat == pytest.approx(NYC.lat - 10_000 / 111_195, rel=0.001)
    assert north_east.lat == pytest.approx(CHICAGO.lat + 10_000 / 111_195, rel=0.001)
    assert south_west.lon < CHICAGO.lon and north_east.lon > NYC.lon
    assert haversine_m(LatLon(CHICAGO.lat, south_west.lon), CHICAGO) == pytest.approx(10_000, rel=0.001)
