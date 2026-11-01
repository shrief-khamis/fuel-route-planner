class RoutingError(Exception):
    """Base class for all routing errors.

    Adapters raise only subclasses of this; provider exceptions, status codes and messages
    never leave the adapter.
    """


class RouteNotFound(RoutingError):
    """No route connects the waypoints, or a waypoint is not near any road."""


class InvalidRouteRequest(RoutingError):
    """The request breaks provider limits (too long, too many waypoints, ...)."""


class RoutingUnavailable(RoutingError):
    """The provider could not be reached or answered unexpectedly."""
