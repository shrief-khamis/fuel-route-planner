import math

from .types import LatLon

EARTH_RADIUS_M = 6_371_008.8


def haversine_m(a: LatLon, b: LatLon) -> float:
    """Return the great-circle distance between two points, in metres.

    Uses the haversine formula on a sphere with the Earth's mean radius. This is within
    about 0.5% of the true distance on the ellipsoid, which is enough for distance checks.

    Args:
        a: The first point.
        b: The second point.

    Returns:
        The distance in metres, 0 when the points are equal.
    """
    lat1, lon1, lat2, lon2 = map(math.radians, (a.lat, a.lon, b.lat, b.lon))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))
