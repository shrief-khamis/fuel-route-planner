from collections.abc import Iterable

from routing import Polyline

from .types import METRES_PER_MILE, RouteStation, Station


def stations_along(line: Polyline, stations: Iterable[Station], corridor_miles: float) -> list[RouteStation]:
    """Place the stations within the corridor on the route.

    Args:
        line: The route line.
        stations: The stations to consider.
        corridor_miles: How far off the route a station may be.

    Returns:
        The stations within corridor_miles of the route, sorted by distance from the start.
    """
    corridor_m = corridor_miles * METRES_PER_MILE
    placed = []
    for station in stations:
        position = line.locate(station.location, corridor_m)
        if position is not None:
            placed.append(RouteStation(
                station=station,
                along_miles=position.along_m / METRES_PER_MILE,
                offset_miles=position.offset_m / METRES_PER_MILE,
            ))
    placed.sort(key=lambda s: (s.along_miles, s.offset_miles))
    return placed
