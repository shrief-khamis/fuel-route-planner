import pytest
from rest_framework.test import APIClient

from routing import Route


@pytest.fixture
def api_client():
    """Return a DRF test client."""
    return APIClient()


@pytest.fixture(autouse=True)
def fake_routing(settings):
    """Use the offline fake provider for every API test."""
    settings.ROUTING_PROVIDER = 'fake'


class StubProvider:
    """A routing provider that records its calls and returns or raises a set result."""

    def __init__(self, result):
        """Store the route to return, or the error to raise."""
        self.result = result
        self.calls = []

    def route(self, waypoints, profile):
        """Record the call, then return or raise the set result."""
        self.calls.append((list(waypoints), profile))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def stub_provider(monkeypatch):
    """Return a function that installs a StubProvider in the view."""
    def install(result=None):
        """Install a StubProvider with the given result and return it."""
        if result is None:
            result = Route(points=[], distance_m=0, duration_s=0)
        stub = StubProvider(result)
        monkeypatch.setattr('api.views.get_routing_provider', lambda: stub)
        return stub

    return install
