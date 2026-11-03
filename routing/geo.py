import math
import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise

from .types import LatLon

EARTH_RADIUS_M = 6_371_008.8

# Size of the grid cells that index a Polyline's segments, in degrees (about 11 km of
# latitude).
GRID_CELL_DEG = 0.1

# Decimal places kept when coordinates are written to logs. Two places are about 1 km:
# close enough to debug a request, without recording an exact address.
LOGGED_COORDINATE_PLACES = 2

DECIMAL_NUMBER = re.compile(r'\d+\.\d+')


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


def round_coordinates(text: str, places: int = LOGGED_COORDINATE_PLACES) -> str:
    """Round every decimal number in the text, to keep exact locations out of logs.

    Works on any text, so it also covers malformed coordinates and provider messages
    that quote them. Numbers without a decimal point are left alone.

    Args:
        text: The text, e.g. "40.7128,-74.0060".
        places: The decimal places to keep.

    Returns:
        The text with each decimal number rounded, e.g. "40.71,-74.01".
    """
    return DECIMAL_NUMBER.sub(lambda m: str(round(float(m.group()), places)), text)


@dataclass(frozen=True)
class LinePosition:
    """Where a point lies relative to a Polyline.

    Attributes:
        along_m: Distance along the line, from its first point to the nearest point.
        offset_m: Straight-line distance from the point to the nearest point on the line.
    """

    along_m: float
    offset_m: float


class Polyline:
    """A line through points, with fast queries for the nearest point on it.

    Segments are indexed in a grid of GRID_CELL_DEG cells, so a query only looks at the
    segments near the point. Each segment is treated as straight in a local flat
    projection, which is accurate for the short segments of a road route. The line is not
    expected to cross the antimeridian.

    Attributes:
        points: The points of the line, in order.
        cumulative_m: The distance along the line to each point; the first is 0.
        length_m: The length of the line, in metres.
    """

    def __init__(self, points: Sequence[LatLon]):
        """Build the line and its segment index.

        Args:
            points: At least two points, in order.

        Raises:
            ValueError: Fewer than two points were given.
        """
        if len(points) < 2:
            raise ValueError('A polyline needs at least two points.')
        self.points = list(points)
        self.cumulative_m = [0.0]
        for a, b in pairwise(self.points):
            self.cumulative_m.append(self.cumulative_m[-1] + haversine_m(a, b))
        self.length_m = self.cumulative_m[-1]

        self._grid = defaultdict(list)
        for i, (a, b) in enumerate(pairwise(self.points)):
            for cell in _cells(min(a.lat, b.lat), min(a.lon, b.lon), max(a.lat, b.lat), max(a.lon, b.lon)):
                self._grid[cell].append(i)

    def bounding_box(self, margin_m: float = 0) -> tuple[LatLon, LatLon]:
        """Return the south-west and north-east corners of a box around the line.

        Args:
            margin_m: How far to extend the box on every side, in metres.

        Returns:
            The (south_west, north_east) corners.
        """
        lats = [p.lat for p in self.points]
        lons = [p.lon for p in self.points]
        dlat, dlon = _margin_deg(margin_m, max(abs(min(lats)), abs(max(lats))))
        return (
            LatLon(min(lats) - dlat, min(lons) - dlon),
            LatLon(max(lats) + dlat, max(lons) + dlon),
        )

    def locate(self, point: LatLon, max_offset_m: float) -> LinePosition | None:
        """Find the nearest point on the line, if it is within max_offset_m.

        Points beyond either end of the line are measured to that end. When two parts of
        the line are equally near, the one closer to the start wins.

        Args:
            point: The point to locate.
            max_offset_m: The largest offset to accept, in metres.

        Returns:
            The position of the nearest point on the line, or None if the line is further
            than max_offset_m away.
        """
        dlat, dlon = _margin_deg(max_offset_m, abs(point.lat))
        candidates = set()
        for cell in _cells(point.lat - dlat, point.lon - dlon, point.lat + dlat, point.lon + dlon):
            candidates.update(self._grid.get(cell, ()))

        best = None
        for i in sorted(candidates):
            position = self._project(i, point)
            if position.offset_m <= max_offset_m and (best is None or position.offset_m < best.offset_m):
                best = position
        return best

    def _project(self, i: int, point: LatLon) -> LinePosition:
        """Return the position of the nearest point to point on segment i.

        Args:
            i: The segment index; segment i runs from points[i] to points[i + 1].
            point: The point to project.

        Returns:
            The position of the nearest point on the segment.
        """
        a, b = self.points[i], self.points[i + 1]
        scale = math.cos(math.radians(point.lat))
        ax, ay = (a.lon - point.lon) * scale, a.lat - point.lat
        dx, dy = (b.lon - a.lon) * scale, b.lat - a.lat
        length2 = dx * dx + dy * dy
        t = 0.0 if length2 == 0 else min(1.0, max(0.0, -(ax * dx + ay * dy) / length2))
        foot = LatLon(a.lat + (b.lat - a.lat) * t, a.lon + (b.lon - a.lon) * t)
        along = self.cumulative_m[i] + t * (self.cumulative_m[i + 1] - self.cumulative_m[i])
        return LinePosition(along_m=along, offset_m=haversine_m(point, foot))


def _margin_deg(margin_m: float, abs_lat: float) -> tuple[float, float]:
    """Convert a distance to degrees of latitude and longitude.

    Args:
        margin_m: The distance in metres.
        abs_lat: The absolute latitude to convert at. The longitude margin grows towards
            the poles, so pass the latitude furthest from the equator.

    Returns:
        The (latitude, longitude) margins in degrees.
    """
    dlat = math.degrees(margin_m / EARTH_RADIUS_M)
    return dlat, dlat / max(math.cos(math.radians(abs_lat)), 1e-6)


def _cells(min_lat: float, min_lon: float, max_lat: float, max_lon: float):
    """Yield the grid cells that a box overlaps.

    Args:
        min_lat: The south edge of the box.
        min_lon: The west edge of the box.
        max_lat: The north edge of the box.
        max_lon: The east edge of the box.

    Yields:
        (row, column) cell keys.
    """
    for row in range(math.floor(min_lat / GRID_CELL_DEG), math.floor(max_lat / GRID_CELL_DEG) + 1):
        for col in range(math.floor(min_lon / GRID_CELL_DEG), math.floor(max_lon / GRID_CELL_DEG) + 1):
            yield row, col
