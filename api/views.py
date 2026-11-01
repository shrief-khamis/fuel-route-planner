from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from routing import InvalidRouteRequest, RouteNotFound, RoutingError

from .serializers import FindRouteRequestSerializer
from .services import get_routing_provider


def error_response(code, detail, http_status):
    """Build an error response for a routing failure.

    Args:
        code: A short machine-readable error code, e.g. "route_not_found".
        detail: A generic, human-readable message with no provider details.
        http_status: The HTTP status code.

    Returns:
        A response with a {"detail": ..., "code": ...} body.
    """
    return Response({'detail': detail, 'code': code}, status=http_status)


class FindRouteView(APIView):
    """Find a driving route between two points in the contiguous United States."""

    def get(self, request):
        """Return the driving route between the start and finish query parameters.

        Validates the query string, asks the configured routing provider for a route, and
        maps routing errors to 422 (no route, or a request the provider can't serve) or
        503 (provider unavailable).

        Args:
            request: The request, with "start" and "finish" as "lat,lon" strings and an
                optional "profile" ("truck" by default, or "car").

        Returns:
            A 200 response with the profile, start, finish, distance_m, duration_s and the
            route points as [lat, lon] pairs, or a 422 or 503 error response.

        Raises:
            ValidationError: The query parameters are invalid. DRF turns this into a 400.
        """
        serializer = FindRouteRequestSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        start = serializer.validated_data['start']
        finish = serializer.validated_data['finish']
        profile = serializer.validated_data['profile']

        try:
            route = get_routing_provider().route([start, finish], profile)
        except RouteNotFound:
            return error_response(
                'route_not_found',
                'No drivable route was found between start and finish.',
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        except InvalidRouteRequest:
            return error_response(
                'invalid_route_request',
                'The route request exceeds what the routing service supports.',
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        except RoutingError:
            return error_response(
                'routing_unavailable',
                'The routing service is temporarily unavailable. Please try again later.',
                status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(
            {
                'profile': profile.value,
                'start': {'lat': start.lat, 'lon': start.lon},
                'finish': {'lat': finish.lat, 'lon': finish.lon},
                'distance_m': route.distance_m,
                'duration_s': route.duration_s,
                'points': [[p.lat, p.lon] for p in route.points],
            },
            status=status.HTTP_200_OK,
        )
