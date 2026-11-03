import logging

import pytest
from django.core.exceptions import ImproperlyConfigured

from api.services import get_routing_provider, log_provider_choice
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


@pytest.mark.parametrize(('name', 'level'), [('fake', logging.WARNING), ('openrouteservice', logging.INFO)])
def test_provider_choice_is_logged_once(settings, caplog, name, level):
    """The first build of each provider is logged; the fake one as a warning."""
    settings.ROUTING_PROVIDER = name
    log_provider_choice.cache_clear()
    with caplog.at_level(logging.INFO, logger='api.services'):
        get_routing_provider()
        get_routing_provider()

    [record] = caplog.records
    assert record.levelno == level
