from decimal import Decimal
from itertools import count

import pytest
from rest_framework.test import APIClient

from routing import LatLon, Route
from stations.models import FuelStation

# A 2 km route, short enough to need no fuel stop.
SHORT_ROUTE = Route(points=[LatLon(40.7128, -74.006), LatLon(40.7308, -74.006)], distance_m=2000, duration_s=120)


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
            result = SHORT_ROUTE
        stub = StubProvider(result)
        monkeypatch.setattr('api.views.get_routing_provider', lambda: stub)
        return stub

    return install


@pytest.fixture
def make_station(db):
    """Return a function that saves a FuelStation at a point with a price."""
    ids = count(1)

    def make(lat, lon, price, location_precision='exit'):
        """Save and return a station with placeholder details."""
        n = next(ids)
        price = Decimal(str(price))
        return FuelStation.objects.create(
            opis_id=n, name=f'STATION {n}', address=f'I-80, EXIT {n}', city='Town', state='PA',
            rack_id=1, retail_price=price, price_min=price, price_max=price, price_count=1,
            lat=lat, lon=lon, location_precision=location_precision,
        )

    return make
