from collections.abc import Sequence

from ..base import check_waypoints
from ..geo import haversine_m
from ..types import LatLon, Profile, Route

SPEED_M_PER_S = {
    Profile.TRUCK: 80 / 3.6,
    Profile.CAR: 100 / 3.6,
}


class FakeRoutingProvider:
    """An offline provider that draws straight lines between consecutive waypoints.

    Deterministic and free of I/O, for local development and tests without an API key.

    Attributes:
        points_per_leg: How many points each leg between two waypoints has, both ends included.
    """

    def __init__(self, points_per_leg: int = 10):
        """Create the provider.

        Args:
            points_per_leg: How many points each leg has, both ends included.

        Raises:
            ValueError: points_per_leg is less than 2.
        """
        if points_per_leg < 2:
            raise ValueError('points_per_leg must be at least 2.')
        self.points_per_leg = points_per_leg

    def route(self, waypoints: Sequence[LatLon], profile: Profile) -> Route:
        """Return a straight-line route through the waypoints, in order.

        Each leg is split into evenly spaced points. A point shared by two legs appears only
        once. The distance is the sum of the haversine distances between the points, and the
        duration assumes a fixed speed per profile.

        Args:
            waypoints: At least two points to visit, in travel order.
            profile: The vehicle type, which sets the assumed speed.

        Returns:
            The route from the first waypoint to the last.

        Raises:
            InvalidRouteRequest: Fewer than two waypoints were given.
        """
        check_waypoints(waypoints)

        points = [LatLon(*waypoints[0])]
        steps = self.points_per_leg - 1
        for a, b in zip(waypoints, waypoints[1:]):
            for i in range(1, steps + 1):
                t = i / steps
                points.append(LatLon(a.lat + (b.lat - a.lat) * t, a.lon + (b.lon - a.lon) * t))

        distance_m = sum(haversine_m(p, q) for p, q in zip(points, points[1:]))
        return Route(
            points=points,
            distance_m=distance_m,
            duration_s=distance_m / SPEED_M_PER_S[Profile(profile)],
        )
