import pytest
from django.core.exceptions import ImproperlyConfigured

from api.services import get_routing_provider
from routing.providers.fake import FakeRoutingProvider
from routing.providers.openrouteservice import OpenRouteServiceProvider


def test_fake_provider(settings):
    """ROUTING_PROVIDER=fake builds a FakeRoutingProvider."""
    settings.ROUTING_PROVIDER = 'fake'
    assert isinstance(get_routing_provider(), FakeRoutingProvider)


def test_openrouteservice_provider(settings):
    """ROUTING_PROVIDER=openrouteservice builds an ORS provider from settings."""
    settings.ROUTING_PROVIDER = 'openrouteservice'
    settings.ORS_API_KEY = 'test-key'
    settings.ORS_BASE_URL = 'https://ors.test/openrouteservice/'
    settings.ROUTING_CONNECT_TIMEOUT_SECONDS = 2.0
    settings.ROUTING_TIMEOUT_SECONDS = 7.0

    provider = get_routing_provider()

    assert isinstance(provider, OpenRouteServiceProvider)
    assert provider.api_key == 'test-key'
    assert provider.base_url == 'https://ors.test/openrouteservice'
    assert provider.timeout.connect == 2.0
    assert provider.timeout.read == 7.0


def test_unknown_provider(settings):
    """An unknown ROUTING_PROVIDER raises ImproperlyConfigured."""
    settings.ROUTING_PROVIDER = 'nope'
    with pytest.raises(ImproperlyConfigured):
        get_routing_provider()
