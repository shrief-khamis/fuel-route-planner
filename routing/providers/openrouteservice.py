import logging
from collections.abc import Sequence

import httpx

from ..base import check_waypoints
from ..errors import InvalidRouteRequest, RouteNotFound, RoutingUnavailable
from ..types import LatLon, Profile, Route

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = httpx.Timeout(15, connect=5)

# ORS only snaps to roads within ~350 m by default; arbitrary user points often miss that.
# Keep it finite so points in open water still fail.
SNAP_RADIUS_M = 5000

ORS_PROFILES = {
    Profile.TRUCK: 'driving-hgv',
    Profile.CAR: 'driving-car',
}

# https://giscience.github.io/openrouteservice/api-reference/error-codes
ROUTE_NOT_FOUND_CODES = {2009, 2010}
LIMIT_EXCEEDED_CODES = {2004}


class OpenRouteServiceProvider:
    """A routing provider backed by the OpenRouteService (ORS) directions API.

    This is the only place in our code that uses ORS's [lon, lat] coordinate order.

    Attributes:
        api_key: The ORS API key, sent in the Authorization header.
        base_url: The ORS base URL, without a trailing slash.
        timeout: Connect and response timeouts for each request.
        client: An HTTP client to reuse, or None to open one per request.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        client: httpx.Client | None = None,
    ):
        """Create the provider.

        Args:
            api_key: The ORS API key. If empty, every route() call fails without a request.
            base_url: The ORS base URL, e.g. "https://api.heigit.org/openrouteservice".
            timeout: Connect and response timeouts for each request.
            client: An HTTP client to use instead of opening one per request. Tests pass a
                client with an httpx.MockTransport here.
        """
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.client = client

    def route(self, waypoints: Sequence[LatLon], profile: Profile) -> Route:
        """Return a driving route through the waypoints, in order.

        Each waypoint snaps to a road within SNAP_RADIUS_M. The route never crosses a
        border, so it stays in the country of the first waypoint, and a waypoint in another
        country gives RouteNotFound.

        Args:
            waypoints: At least two points to visit, in travel order.
            profile: The vehicle type to route for.

        Returns:
            The route from the first waypoint to the last.

        Raises:
            InvalidRouteRequest: Fewer than two waypoints were given, the profile is not
                supported, or the request exceeds ORS limits (e.g. route distance).
            RouteNotFound: No route connects the waypoints, or a waypoint is not near a road.
            RoutingUnavailable: The API key is missing or rejected, ORS is unreachable, slow,
                rate-limited or failing, or its response is not what we expect.
        """
        check_waypoints(waypoints)
        try:
            ors_profile = ORS_PROFILES[Profile(profile)]
        except (KeyError, ValueError) as exc:
            raise InvalidRouteRequest(f'Unsupported profile: {profile!r}.') from exc
        if not self.api_key:
            logger.error('OpenRouteService API key is not configured; set ORS_API_KEY.')
            raise RoutingUnavailable('Routing provider is not configured.')

        response = self._post(
            f'{self.base_url}/v2/directions/{ors_profile}/geojson',
            {
                'coordinates': [[p.lon, p.lat] for p in waypoints],
                'radiuses': [SNAP_RADIUS_M] * len(waypoints),
                'instructions': False,
                # Keep routes inside the start country: no border crossings at all.
                'options': {'avoid_borders': 'all'},
            },
        )
        if response.status_code != 200:
            self._raise_for_error(response)
        return self._parse_route(response)

    def _post(self, url: str, body: dict) -> httpx.Response:
        """Send a JSON POST request to ORS.

        Args:
            url: The full request URL.
            body: The JSON request body.

        Returns:
            The response, whatever its status code.

        Raises:
            RoutingUnavailable: The request timed out or failed at the network level.
        """
        headers = {
            'Authorization': self.api_key,
            'Content-Type': 'application/json',
            'Accept': 'application/json, application/geo+json',
        }
        try:
            if self.client is not None:
                return self.client.post(url, json=body, headers=headers, timeout=self.timeout)
            with httpx.Client(timeout=self.timeout) as client:
                return client.post(url, json=body, headers=headers)
        except httpx.TimeoutException as exc:
            logger.warning('OpenRouteService request timed out: %s', type(exc).__name__)
            raise RoutingUnavailable('Routing provider timed out.') from exc
        except httpx.HTTPError as exc:
            logger.warning('OpenRouteService request failed: %s', type(exc).__name__)
            raise RoutingUnavailable('Routing provider is unreachable.') from exc

    def _raise_for_error(self, response: httpx.Response) -> None:
        """Raise the routing error that matches an ORS error response.

        Rejected credentials (401/403) and rate limits (429) are logged and mapped to
        RoutingUnavailable. Other 4xx responses are mapped by their ORS error code. Any
        other code is a bug in this adapter, since we validate input before calling ORS.

        Args:
            response: A response whose status code is not 200.

        Raises:
            RouteNotFound: ORS error code 2009 (route not found) or 2010 (point not found).
            InvalidRouteRequest: ORS error code 2004 (request exceeds a server limit).
            RoutingUnavailable: Any other error.
        """
        status = response.status_code
        code, message = _error_details(response)

        if status in (401, 403):
            logger.error(
                'OpenRouteService rejected the API key (HTTP %s: %s); check ORS_API_KEY.',
                status, message,
            )
            raise RoutingUnavailable('Routing provider rejected the credentials.')
        if status == 429:
            logger.warning('OpenRouteService rate limit hit (HTTP 429: %s).', message)
            raise RoutingUnavailable('Routing provider rate limit exceeded.')
        if 400 <= status < 500 and code in ROUTE_NOT_FOUND_CODES:
            raise RouteNotFound('No route found between the waypoints.')
        if 400 <= status < 500 and code in LIMIT_EXCEEDED_CODES:
            raise InvalidRouteRequest('Route request exceeds provider limits.')

        log = logger.warning if status >= 500 else logger.error
        log('OpenRouteService error (HTTP %s, code %s): %s', status, code, message)
        raise RoutingUnavailable('Routing provider returned an error.')

    def _parse_route(self, response: httpx.Response) -> Route:
        """Build a Route from a successful ORS GeoJSON response.

        Args:
            response: A response with status code 200.

        Returns:
            The route, with the coordinates converted from [lon, lat] to LatLon. A missing
            distance or duration counts as 0, since ORS may leave out zero values.

        Raises:
            RoutingUnavailable: The body is not valid JSON, lacks a route feature, or its
                geometry is malformed or has fewer than two points.
        """
        try:
            feature = response.json()['features'][0]
            points = [LatLon(float(lat), float(lon)) for lon, lat, *_ in feature['geometry']['coordinates']]
            summary = feature['properties'].get('summary', {})
            distance_m = float(summary.get('distance', 0))
            duration_s = float(summary.get('duration', 0))
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            logger.error('OpenRouteService returned an unexpected response: %r', exc)
            raise RoutingUnavailable('Routing provider returned an unexpected response.') from exc
        if len(points) < 2:
            logger.error('OpenRouteService returned a route with %d points.', len(points))
            raise RoutingUnavailable('Routing provider returned an unexpected response.')
        return Route(points=points, distance_m=distance_m, duration_s=duration_s)


def _error_details(response: httpx.Response) -> tuple[int | None, str]:
    """Extract the error code and message from an ORS error response.

    ORS routing errors look like {"error": {"code": 2009, "message": "..."}}, while
    gateway errors (e.g. 403, 429) look like {"error": "..."}. This handles both, and
    falls back to the raw text for bodies that are not JSON.

    Args:
        response: An ORS error response.

    Returns:
        A (code, message) tuple. The code is None when the body has no integer code.
    """
    try:
        error = response.json().get('error')
    except (ValueError, AttributeError):
        return None, response.text[:200]
    if isinstance(error, dict):
        code = error.get('code')
        return (code if isinstance(code, int) else None), str(error.get('message', ''))
    return None, str(error)
