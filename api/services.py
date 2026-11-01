import httpx
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from routing import RoutingProvider
from routing.providers.fake import FakeRoutingProvider
from routing.providers.openrouteservice import OpenRouteServiceProvider


def get_routing_provider() -> RoutingProvider:
    """Build the routing provider named by the ROUTING_PROVIDER setting.

    This is the only place that reads Django settings for the routing package.

    Returns:
        A new OpenRouteServiceProvider for "openrouteservice", or a new
        FakeRoutingProvider for "fake".

    Raises:
        ImproperlyConfigured: ROUTING_PROVIDER names an unknown provider.
    """
    name = settings.ROUTING_PROVIDER
    if name == 'openrouteservice':
        return OpenRouteServiceProvider(
            api_key=settings.ORS_API_KEY,
            base_url=settings.ORS_BASE_URL,
            timeout=httpx.Timeout(
                settings.ROUTING_TIMEOUT_SECONDS,
                connect=settings.ROUTING_CONNECT_TIMEOUT_SECONDS,
            ),
        )
    if name == 'fake':
        return FakeRoutingProvider()
    raise ImproperlyConfigured(
        f"Unknown ROUTING_PROVIDER {name!r}; expected 'openrouteservice' or 'fake'."
    )
