import functools
import logging

import httpx
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from fuel_planner import METRES_PER_MILE, Station
from routing import LatLon, Polyline, RoutingProvider
from routing.providers.fake import FakeRoutingProvider
from routing.providers.openrouteservice import OpenRouteServiceProvider
from stations.models import FuelStation

logger = logging.getLogger(__name__)


def get_routing_provider() -> RoutingProvider:
    """Build the routing provider named by the ROUTING_PROVIDER setting.

    This is the only place that reads Django settings for the routing package. The first
    time each provider is built, it is logged.

    Returns:
        A new OpenRouteServiceProvider for "openrouteservice", or a new
        FakeRoutingProvider for "fake".

    Raises:
        ImproperlyConfigured: ROUTING_PROVIDER names an unknown provider.
    """
    name = settings.ROUTING_PROVIDER
    if name == 'openrouteservice':
        log_provider_choice(name)
        return OpenRouteServiceProvider(
            api_key=settings.ORS_API_KEY,
            base_url=settings.ORS_BASE_URL,
            timeout=httpx.Timeout(
                settings.ROUTING_TIMEOUT_SECONDS,
                connect=settings.ROUTING_CONNECT_TIMEOUT_SECONDS,
            ),
        )
    if name == 'fake':
        log_provider_choice(name)
        return FakeRoutingProvider()
    raise ImproperlyConfigured(
        f"Unknown ROUTING_PROVIDER {name!r}; expected 'openrouteservice' or 'fake'."
    )


@functools.cache
def log_provider_choice(name: str) -> None:
    """Log which routing provider is in use, the first time each one is built.

    The fake provider is logged as a warning, since its straight lines are easy to mistake
    for real routes.

    Args:
        name: The ROUTING_PROVIDER setting, "openrouteservice" or "fake".
    """
    if name == 'fake':
        logger.warning('Using the fake routing provider: routes are straight lines, not roads.')
    else:
        logger.info('Using the OpenRouteService routing provider.', extra={'base_url': settings.ORS_BASE_URL})


def stations_near(line: Polyline, margin_miles: float) -> list[Station]:
    """Load the stations inside the line's bounding box, extended by a margin.

    The box is a cheap first filter on the indexed coordinates; the planner then keeps only
    the stations within the corridor.

    Args:
        line: The route line.
        margin_miles: How far to extend the box on every side.

    Returns:
        The stations, with the FuelStation primary key as their ID.
    """
    south_west, north_east = line.bounding_box(margin_miles * METRES_PER_MILE)
    rows = FuelStation.objects.filter(
        lat__range=(south_west.lat, north_east.lat),
        lon__range=(south_west.lon, north_east.lon),
    ).values_list('id', 'lat', 'lon', 'retail_price')
    return [Station(id=pk, location=LatLon(lat, lon), price=float(price)) for pk, lat, lon, price in rows]


def station_details(ids: list[int]) -> dict[int, FuelStation]:
    """Load the full records of the given stations.

    Args:
        ids: FuelStation primary keys.

    Returns:
        The stations by primary key.
    """
    return FuelStation.objects.in_bulk(ids)
