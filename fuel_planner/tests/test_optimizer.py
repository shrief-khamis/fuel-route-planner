import random
from functools import cache

import pytest

from fuel_planner import NoFeasiblePlan, PlanOptions, Station
from fuel_planner.optimizer import cheapest_purchases
from fuel_planner.types import RouteStation
from routing import LatLon


def options(**overrides):
    """Return PlanOptions with a 100-mile tank, a full start, 10 mpg and no penalty."""
    values = dict(
        max_range_miles=100, start_fuel_miles=100, reserve_miles=0, mpg=10,
        corridor_miles=3, min_stop_saving=0,
    )
    return PlanOptions(**(values | overrides))


def station(along, price, offset=0.0, id=None):
    """Return a RouteStation at along miles, offset miles off the route."""
    return RouteStation(
        station=Station(id=id if id is not None else int(along * 100), location=LatLon(0, 0), price=price),
        along_miles=along,
        offset_miles=offset,
    )


def summary(purchases):
    """Return (along, arrival, bought) for each purchase, rounded for comparison."""
    return [
        (p.stop.along_miles, round(p.arrival_miles, 6), round(p.bought_miles, 6))
        for p in purchases
    ]


def cost(purchases, mpg=10):
    """Return the money spent on the purchases."""
    return sum(p.bought_miles / mpg * p.stop.station.price for p in purchases)


@pytest.mark.parametrize('route_miles', [80, 100])
def test_no_stops_when_start_fuel_reaches_finish(route_miles):
    """The start fuel alone covers a route up to its range, so no stop is made."""
    assert cheapest_purchases([station(50, 3.0)], route_miles, options()) == []


def test_partial_start_fuel():
    """A half tank at the start must stop before 50 miles."""
    purchases = cheapest_purchases([station(40, 3.0)], 120, options(start_fuel_miles=50))
    assert summary(purchases) == [(40, 10, 70)]


def test_no_station_in_reach():
    """The only station is beyond the start fuel."""
    with pytest.raises(NoFeasiblePlan):
        cheapest_purchases([station(120, 3.0)], 150, options())


def test_gap_between_stations_too_wide():
    """Two stations more than a tank apart can't be bridged."""
    with pytest.raises(NoFeasiblePlan):
        cheapest_purchases([station(50, 3.0), station(200, 3.0)], 250, options())


def test_no_stations():
    """A route longer than the start fuel with no stations is infeasible."""
    with pytest.raises(NoFeasiblePlan):
        cheapest_purchases([], 150, options())


def test_last_stop_buys_just_enough():
    """The last stop buys only what reaches the finish."""
    purchases = cheapest_purchases([station(60, 3.0)], 150, options())
    assert summary(purchases) == [(60, 40, 50)]


def test_fills_up_cheap_and_tops_up_expensive():
    """Fill up at cheap stations; buy only enough at an expensive one to reach the next cheap one."""
    stations = [station(50, 3.0), station(120, 5.0), station(160, 3.0)]
    purchases = cheapest_purchases(stations, 250, options())

    assert summary(purchases) == [(50, 50, 50), (120, 30, 10), (160, 0, 90)]
    assert cost(purchases) == pytest.approx(15 + 5 + 27)


def test_skips_stations_that_are_not_needed():
    """An expensive station within reach of a cheaper one is skipped."""
    stations = [station(30, 5.0), station(60, 3.0), station(90, 5.0)]
    purchases = cheapest_purchases(stations, 150, options())
    assert summary(purchases) == [(60, 40, 50)]


def test_reserve_is_never_used():
    """With a 20-mile reserve, only 80 miles of the tank can be driven."""
    opts = options(reserve_miles=20)
    purchases = cheapest_purchases([station(70, 3.0)], 150, opts)
    assert summary(purchases) == [(70, 10, 70)]

    with pytest.raises(NoFeasiblePlan):
        cheapest_purchases([station(90, 3.0)], 150, opts)


def test_detour_uses_fuel():
    """The offset counts towards the fuel needed to reach a station and get back."""
    purchases = cheapest_purchases([station(95, 3.0, offset=3)], 150, options())
    assert summary(purchases) == [(95, 2, 56)]

    with pytest.raises(NoFeasiblePlan):
        cheapest_purchases([station(95, 3.0, offset=6)], 150, options())


def test_cheaper_station_loses_to_its_detour():
    """A slightly cheaper station 3 miles off costs more than one on the route."""
    stations = [station(60, 3.00, id=1), station(60, 2.99, offset=3, id=2)]
    [purchase] = cheapest_purchases(stations, 150, options())
    assert purchase.stop.station.id == 1


@pytest.mark.parametrize('min_stop_saving, stops', [(0, [50, 95]), (3.99, [50, 95]), (4.01, [95])])
def test_min_stop_saving(min_stop_saving, stops):
    """An extra stop that saves $4 is made only when the threshold is below that.

    Stopping only at 95 buys 9 gallons at $3.80 ($34.20). Filling 5 gallons at $3.00 at 50
    first leaves 4 gallons to buy at 95 ($30.20).
    """
    stations = [station(50, 3.00), station(95, 3.80)]
    purchases = cheapest_purchases(stations, 190, options(min_stop_saving=min_stop_saving))
    assert [p.stop.along_miles for p in purchases] == stops


def test_threshold_does_not_skip_needed_stops():
    """A stop that the trip can't do without is made whatever the threshold."""
    purchases = cheapest_purchases([station(60, 3.0)], 150, options(min_stop_saving=1000))
    assert summary(purchases) == [(60, 40, 50)]


def brute_force_cost(stations, route_miles, opts):
    """Return the cheapest plan's cost, penalties included, by trying every whole-mile purchase.

    Every distance must be a whole number of miles, so that some cheapest plan only buys
    whole miles.
    """
    capacity = int(opts.max_range_miles - opts.reserve_miles)
    finish = len(stations)

    def leg(u, v):
        a_along, a_offset = (0, 0) if u is None else (stations[u].along_miles, stations[u].offset_miles)
        if v == finish:
            return a_offset + route_miles - a_along
        return a_offset + stations[v].along_miles - a_along + stations[v].offset_miles

    @cache
    def best(u, fuel):
        """The cheapest way to the finish from stop u (None for the start) with fuel miles."""
        price = 0 if u is None else stations[u].station.price / opts.mpg
        top_up = [0] if u is None else range(capacity - fuel + 1)
        result = float('inf')
        for bought in top_up:
            for v in range((-1 if u is None else u) + 1, finish + 1):
                need = leg(u, v)
                if need > fuel + bought:
                    continue
                rest = 0 if v == finish else opts.min_stop_saving + best(v, fuel + bought - need)
                result = min(result, bought * price + rest)
        return result

    return best(None, int(opts.start_fuel_miles - opts.reserve_miles))


@pytest.mark.parametrize('seed', range(60))
def test_matches_brute_force(seed):
    """On small random trips, the plan costs the same as the best of every possible plan."""
    rng = random.Random(seed)
    route_miles = rng.randint(30, 90)
    stations = sorted(
        (station(rng.randint(0, route_miles), round(rng.uniform(2.5, 5.0), 2), offset=rng.randint(0, 3), id=i)
         for i in range(rng.randint(0, 7))),
        key=lambda s: (s.along_miles, s.offset_miles),
    )
    max_range = rng.randint(15, 40)
    reserve = rng.randint(0, max_range // 2)
    opts = options(
        max_range_miles=max_range,
        start_fuel_miles=rng.randint(reserve + 1, max_range),
        reserve_miles=reserve,
        min_stop_saving=rng.choice([0, 0.25, 1]),
    )

    expected = brute_force_cost(stations, route_miles, opts)
    if expected == float('inf'):
        with pytest.raises(NoFeasiblePlan):
            cheapest_purchases(stations, route_miles, opts)
        return
    purchases = cheapest_purchases(stations, route_miles, opts)
    assert cost(purchases) + opts.min_stop_saving * len(purchases) == pytest.approx(expected)
