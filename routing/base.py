from collections.abc import Sequence
from typing import Protocol

from .errors import InvalidRouteRequest
from .types import LatLon, Profile, Route

MIN_WAYPOINTS = 2


class RoutingProvider(Protocol):
    """The interface every routing adapter implements.

    Adapters convert our types to and from the provider's format, and raise only
    RoutingError subclasses.
    """

    def route(self, waypoints: Sequence[LatLon], profile: Profile) -> Route:
        """Return a driving route through the waypoints, in order.

        Args:
            waypoints: At least two points to visit, in travel order.
            profile: The vehicle type to route for.

        Returns:
            The route from the first waypoint to the last.

        Raises:
            InvalidRouteRequest: Fewer than two waypoints were given, or the request exceeds
                provider limits.
            RouteNotFound: No route connects the waypoints, or a waypoint is not near a road.
            RoutingUnavailable: The provider failed or answered unexpectedly.
        """
        ...


def check_waypoints(waypoints: Sequence[LatLon]) -> None:
    """Check that there are enough waypoints to form a route.

    Args:
        waypoints: The waypoints passed to a provider.

    Raises:
        InvalidRouteRequest: Fewer than MIN_WAYPOINTS waypoints were given.
    """
    if len(waypoints) < MIN_WAYPOINTS:
        raise InvalidRouteRequest(f'At least {MIN_WAYPOINTS} waypoints are required.')
