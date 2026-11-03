import pytest

from fuel_planner import METRES_PER_MILE, NoFeasiblePlan, PlanOptions, Station, plan_fuel_stops
from fuel_planner.corridor import stations_along
from routing import LatLon, Polyline, haversine_m

# A straight east-west line along 40°N, about 106 miles long.
WEST = LatLon(40.0, -100.0)
EAST = LatLon(40.0, -98.0)
LINE = Polyline([WEST, LatLon(40.0, -99.0), EAST])
LINE_MILES = LINE.length_m / METRES_PER_MILE
MILE_DEG = 1 / 69.05  # About one mile of latitude.


def options(**overrides):
    """Return PlanOptions with a 60-mile tank, a full start and a 3-mile corridor."""
    values = dict(
        max_range_miles=60, start_fuel_miles=60, reserve_miles=0, mpg=10,
        corridor_miles=3, min_stop_saving=0,
    )
    return PlanOptions(**(values | overrides))


def test_stations_along_keeps_the_corridor_in_order():
    """Stations within the corridor are placed on the line, nearest the start first."""
    near = Station(1, LatLon(40.0 + 2 * MILE_DEG, -99.0), 3.0)
    far = Station(2, LatLon(40.0 + 4 * MILE_DEG, -99.5), 3.0)
    early = Station(3, LatLon(40.0, -99.5), 3.0)

    placed = stations_along(LINE, [near, far, early], corridor_miles=3)

    assert [p.station.id for p in placed] == [3, 1]
    assert placed[1].along_miles == pytest.approx(LINE_MILES / 2, rel=0.001)
    assert placed[1].offset_miles == pytest.approx(2, rel=0.01)
    assert placed[0].offset_miles == pytest.approx(0, abs=1e-6)


def test_plan_reports_gallons_cost_and_detour():
    """A single stop 1 mile off the route buys enough for its detour and the rest of the trip."""
    stop_station = Station(7, LatLon(40.0 + MILE_DEG, -99.0), 3.459)
    plan = plan_fuel_stops(LINE, [stop_station], options(reserve_miles=5))

    [stop] = plan.stops
    half = LINE_MILES / 2
    offset = haversine_m(stop_station.location, LatLon(40.0, -99.0)) / METRES_PER_MILE
    assert stop.station == stop_station
    assert stop.along_miles == pytest.approx(half, rel=0.001)
    assert stop.offset_miles == pytest.approx(offset, rel=0.001)
    # The tank holds 55 usable miles; reaching the station uses half + offset of them, and
    # the rest of the trip is the offset back plus the other half.
    assert stop.fuel_on_arrival_miles == pytest.approx(60 - half - offset, rel=0.001)
    assert stop.fuel_added_miles == pytest.approx(offset + half - (55 - half - offset), rel=0.001)
    assert stop.gallons == pytest.approx(stop.fuel_added_miles / 10)
    assert stop.cost == round(stop.gallons * 3.459, 2)
    assert plan.total_gallons == pytest.approx(stop.gallons)
    assert plan.total_cost == stop.cost
    assert plan.total_detour_miles == pytest.approx(2 * offset)


def test_no_stops_needed():
    """A full tank of 120 miles covers the line without stopping."""
    plan = plan_fuel_stops(LINE, [], options(max_range_miles=120, start_fuel_miles=120))
    assert plan.stops == []
    assert plan.total_cost == 0
    assert plan.total_gallons == 0
    assert plan.corridor_stations == 0


def test_plan_counts_the_stations_in_the_corridor():
    """corridor_stations counts the candidates, not the stations passed in."""
    stations = [
        Station(1, LatLon(40.0, -99.5), 3.0),
        Station(2, LatLon(40.0, -98.5), 3.0),
        Station(3, LatLon(40.0 + 5 * MILE_DEG, -99.0), 3.0),
    ]
    plan = plan_fuel_stops(LINE, stations, options(max_range_miles=120, start_fuel_miles=120))
    assert plan.corridor_stations == 2


def test_stations_outside_corridor_are_ignored():
    """A station 5 miles off a 3-mile corridor can't save the trip."""
    with pytest.raises(NoFeasiblePlan) as exc_info:
        plan_fuel_stops(LINE, [Station(1, LatLon(40.0 + 5 * MILE_DEG, -99.0), 3.0)], options())
    assert exc_info.value.corridor_stations == 0


def test_total_cost_adds_up_the_rounded_stop_costs():
    """total_cost is the sum of what each stop charges."""
    stations = [Station(1, LatLon(40.0, -99.6), 3.3333), Station(2, LatLon(40.0, -98.8), 3.6667)]
    plan = plan_fuel_stops(LINE, stations, options(max_range_miles=50, start_fuel_miles=50))

    assert len(plan.stops) == 2
    assert plan.total_cost == round(sum(s.cost for s in plan.stops), 2)


@pytest.mark.parametrize('overrides', [
    dict(mpg=0),
    dict(max_range_miles=0),
    dict(corridor_miles=0),
    dict(min_stop_saving=-1),
    dict(start_fuel_miles=70),
    dict(reserve_miles=60),
    dict(reserve_miles=-1),
])
def test_plan_options_reject_inconsistent_settings(overrides):
    """Settings that can't describe a real tank are rejected."""
    with pytest.raises(ValueError):
        options(**overrides)
