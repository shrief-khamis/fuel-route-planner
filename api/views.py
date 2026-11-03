import logging
import time

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from fuel_planner import METRES_PER_MILE, NoFeasiblePlan, plan_fuel_stops
from routing import InvalidRouteRequest, Polyline, RouteNotFound, RoutingError

from .serializers import FindRouteRequestSerializer
from .services import get_routing_provider, station_details, stations_near

logger = logging.getLogger(__name__)


def elapsed_ms(started):
    """Return the whole milliseconds since a time.perf_counter() reading."""
    return round((time.perf_counter() - started) * 1000)


def error_response(code, detail, http_status, **context):
    """Build an error response for a routing or planning failure, and log its code.

    Args:
        code: A short machine-readable error code, e.g. "route_not_found".
        detail: A generic, human-readable message with no provider details.
        http_status: The HTTP status code.
        **context: Fields to log with the code.

    Returns:
        A response with a {"detail": ..., "code": ...} body.
    """
    logger.info('Request failed.', extra={'code': code, **context})
    return Response({'detail': detail, 'code': code}, status=http_status)


def stop_data(stop, station):
    """Convert a planned stop to its response format.

    Args:
        stop: The FuelStop.
        station: The stop's FuelStation record.

    Returns:
        The stop as a dict, with distances rounded for display.
    """
    return {
        'station': {
            'opis_id': station.opis_id,
            'name': station.name,
            'address': station.address,
            'city': station.city,
            'state': station.state,
            'lat': station.lat,
            'lon': station.lon,
            'location_precision': station.location_precision,
        },
        'price_per_gallon': stop.station.price,
        'distance_from_start_miles': round(stop.along_miles, 1),
        'offset_miles': round(stop.offset_miles, 2),
        'fuel_on_arrival_miles': round(stop.fuel_on_arrival_miles, 1),
        'fuel_added_miles': round(stop.fuel_added_miles, 1),
        'gallons': round(stop.gallons, 2),
        'cost': stop.cost,
    }


class FindRouteView(APIView):
    """Find a driving route between two points in the contiguous US, with fuel stops."""

    def get(self, request):
        """Return the route between start and finish, and the cheapest fuel stops along it.

        Validates the query string, asks the configured routing provider for a route, then
        plans the stops from the stations near it. Routing errors map to 422 (no route, or
        a request the provider can't serve) or 503 (provider unavailable). A trip that no
        choice of stations can complete maps to 422. A successful plan, and each of these
        errors, is logged with how long routing and planning took.

        Args:
            request: The request, with "start" and "finish" as "lat,lon" strings, an
                optional "profile" ("truck" by default, or "car"), and the optional fuel
                settings max_range_miles, start_fuel_miles, reserve_miles, mpg,
                corridor_miles and min_stop_saving.

        Returns:
            A 200 response with the profile, start, finish, distance_m, duration_s, the fuel
            totals, the stops and the route points as [lat, lon] pairs, or a 422 or 503
            error response.

        Raises:
            ValidationError: The query parameters are invalid. DRF turns this into a 400.
        """
        serializer = FindRouteRequestSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        start = serializer.validated_data['start']
        finish = serializer.validated_data['finish']
        profile = serializer.validated_data['profile']
        options = serializer.plan_options()

        provider = get_routing_provider()
        started = time.perf_counter()
        try:
            route = provider.route([start, finish], profile)
        except RouteNotFound:
            return error_response(
                'route_not_found',
                'No drivable route was found between start and finish.',
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                routing_ms=elapsed_ms(started),
            )
        except InvalidRouteRequest:
            return error_response(
                'invalid_route_request',
                'The route request exceeds what the routing service supports.',
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                routing_ms=elapsed_ms(started),
            )
        except RoutingError:
            return error_response(
                'routing_unavailable',
                'The routing service is temporarily unavailable. Please try again later.',
                status.HTTP_503_SERVICE_UNAVAILABLE,
                routing_ms=elapsed_ms(started),
            )
        routing_ms = elapsed_ms(started)

        # Planning time covers loading the stations from the database too.
        started = time.perf_counter()
        line = Polyline(route.points)
        stations = stations_near(line, options.corridor_miles)
        context = {
            'route_miles': round(route.distance_m / METRES_PER_MILE, 1),
            'stations_in_box': len(stations),
        }
        try:
            plan = plan_fuel_stops(line, stations, options)
        except NoFeasiblePlan as exc:
            return error_response(
                'no_feasible_fuel_plan',
                'No choice of fuel stations along the route reaches the finish with this range and reserve.',
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                **context,
                stations_in_corridor=exc.corridor_stations,
                usable_range_miles=options.max_range_miles - options.reserve_miles,
                routing_ms=routing_ms,
                planning_ms=elapsed_ms(started),
            )
        logger.info('Planned the fuel stops.', extra={
            'stops': len(plan.stops),
            'total_cost': plan.total_cost,
            **context,
            'stations_in_corridor': plan.corridor_stations,
            'routing_ms': routing_ms,
            'planning_ms': elapsed_ms(started),
        })
        details = station_details([stop.station.id for stop in plan.stops])

        return Response(
            {
                'profile': profile.value,
                'start': {'lat': start.lat, 'lon': start.lon},
                'finish': {'lat': finish.lat, 'lon': finish.lon},
                'distance_m': route.distance_m,
                'duration_s': route.duration_s,
                'total_cost': plan.total_cost,
                'total_gallons': round(plan.total_gallons, 2),
                'total_detour_miles': round(plan.total_detour_miles, 2),
                'stops': [stop_data(stop, details[stop.station.id]) for stop in plan.stops],
                'points': [[p.lat, p.lon] for p in route.points],
            },
            status=status.HTTP_200_OK,
        )
