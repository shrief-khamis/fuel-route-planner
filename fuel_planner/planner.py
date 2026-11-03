from collections.abc import Iterable

from routing import Polyline

from .corridor import stations_along
from .errors import NoFeasiblePlan
from .optimizer import cheapest_purchases
from .types import METRES_PER_MILE, FuelPlan, FuelStop, PlanOptions, Station


def plan_fuel_stops(line: Polyline, stations: Iterable[Station], options: PlanOptions) -> FuelPlan:
    """Find the cheapest fuel stops for a route.

    Stations within options.corridor_miles of the route are candidates. Reaching one and
    driving back to the route uses fuel for twice its offset.

    Args:
        line: The route line.
        stations: The stations to consider; those outside the corridor are ignored.
        options: The vehicle and trip settings.

    Returns:
        The plan, with no stops when the start fuel reaches the finish.

    Raises:
        NoFeasiblePlan: No choice of stations reaches the finish without dipping into the
            reserve. Its corridor_stations is set.
    """
    candidates = stations_along(line, stations, options.corridor_miles)
    try:
        purchases = cheapest_purchases(candidates, line.length_m / METRES_PER_MILE, options)
    except NoFeasiblePlan as exc:
        exc.corridor_stations = len(candidates)
        raise

    stops = []
    for purchase in purchases:
        stop = purchase.stop
        gallons = purchase.bought_miles / options.mpg
        stops.append(FuelStop(
            station=stop.station,
            along_miles=stop.along_miles,
            offset_miles=stop.offset_miles,
            fuel_on_arrival_miles=purchase.arrival_miles + options.reserve_miles,
            fuel_added_miles=purchase.bought_miles,
            gallons=gallons,
            cost=round(gallons * stop.station.price, 2),
        ))
    return FuelPlan(
        stops=stops,
        total_gallons=sum(s.gallons for s in stops),
        total_detour_miles=sum(2 * s.offset_miles for s in stops),
        total_cost=round(sum(s.cost for s in stops), 2),
        corridor_stations=len(candidates),
    )
