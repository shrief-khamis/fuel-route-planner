# Fuel Route Planner

A Django REST API that returns the driving route between two points in the contiguous
United States, using [openrouteservice](https://openrouteservice.org) (ORS) for routing.
It is the base for a planner that will pick fuel stops along that route.

## Quickstart

Requires Python 3.12 or newer.

```bash
git clone https://github.com/shrief-khamis/fuel-route-planner.git
cd fuel-route-planner
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Get a free ORS API key at <https://account.heigit.org/signup> and set it in `.env`:

```bash
ORS_API_KEY=your-key-here
```

Then start the server:

```bash
python manage.py runserver
```

No key yet? Set `ROUTING_PROVIDER=fake` in `.env` to get straight-line routes, fully
offline. `.env.example` documents every other setting (timeouts, logging).

## API

### `GET /api/find-route/`

| Parameter | Required | Format | Allowed values |
|---|---|---|---|
| `start` | yes | `lat,lon` in decimal degrees, e.g. `32.7767,-96.7970` | Inside the contiguous US: latitude 24.396308 to 49.384358, longitude -124.848974 to -66.885444 (inclusive) |
| `finish` | yes | Same as `start` | Same as `start`, and at least 1 km from it in a straight line |
| `profile` | no | `truck` or `car` | Default `truck` |

Example request, a 20 km truck route across Dallas:

```bash
curl "http://localhost:8000/api/find-route/?start=32.7767,-96.7970&finish=32.8998,-96.7300"
```

Response (trimmed; the full route has 274 points):

```json
{
  "profile": "truck",
  "start": {"lat": 32.7767, "lon": -96.797},
  "finish": {"lat": 32.8998, "lon": -96.73},
  "distance_m": 20355.0,
  "duration_s": 1622.9,
  "points": [
    [32.775944, -96.796753],
    [32.776079, -96.796167],
    ...
    [32.899751, -96.729814]
  ]
}
```

`distance_m` is in metres, `duration_s` in seconds, and `points` is the route line as
`[lat, lon]` pairs, from start to finish. The first and last points are where the route
meets the road, so they can differ slightly from `start` and `finish`.

### Errors

| Status | `code` | Triggered by |
|---|---|---|
| 400 | — | A missing or malformed coordinate, latitude or longitude out of range, a point outside the contiguous US, an unknown `profile`, or `start` and `finish` less than 1 km apart |
| 422 | `route_not_found` | No road route connects the points, a point is more than 5 km from a road (e.g. in water), or the points are in different countries |
| 422 | `invalid_route_request` | The route is over the ORS limit of 6,000 km |
| 503 | `routing_unavailable` | ORS is unreachable, slow (over 15 s), rate-limited or failing, or the API key is missing or rejected |

400 responses use Django REST Framework's standard format, listing errors per field.
The 1 km check is not tied to one field, so its error goes under `non_field_errors`:

```json
{"start": ["Point must be within the contiguous United States."], "finish": ["This field is required."]}
{"non_field_errors": ["start and finish must be at least 1 km apart."]}
```

422 and 503 responses have a generic message and a code. Details about the provider are
only written to the server logs.

```json
{"detail": "No drivable route was found between start and finish.", "code": "route_not_found"}
```

## Assumptions and decisions

- **GET, not POST.** Finding a route only reads data and is safe to repeat, which is what
  GET is for. Two points fit in a query string, and a request works from curl or a browser.
- **Contiguous US only, for points and routes.** Each point is checked against a bounding
  box of the contiguous US, so Alaska and Hawaii are out. ORS is asked to avoid border
  crossings, so a route never leaves the country it starts in.
- **Latitude first, everywhere.** The API takes and returns `lat,lon`. Only the ORS adapter
  converts to the `[lon, lat]` order ORS uses.
- **Truck is the default profile.** It uses ORS's heavy goods vehicle profile
  (`driving-hgv`), since the planner is aimed at trucks.
- **Points snap to a road up to 5 km away.** ORS's default of about 350 m rejects many
  hand-picked points. The radius stays finite so that points in open water still fail.
- **Start and finish must be at least 1 km apart.** Nearly identical points produce an
  empty or meaningless route.
- **Routing sits behind its own interface.** `routing/` has its own types and errors, and
  ORS is one adapter behind it, so the provider can be replaced without changing the API.

## Limitations

- **6,000 km cap.** ORS's public API refuses routes it estimates at over 6,000 km, and this
  API returns 422 `invalid_route_request` for them. A typical coast-to-coast trip
  (about 4,500 km) is well under the cap, but diagonal trips like from Washington to Florida might not fit.
- **The US check is a bounding box.** It also accepts parts of southern Canada, northern
  Mexico and nearby water. Points in water fail with 422, but a trip with both points in
  Canada, such as Toronto to Ottawa, can get a Canadian route.
- **Two points only.** There are no stops in between, though `routing/` already accepts
  any number of waypoints.
- **No truck restrictions.** The truck profile ignores vehicle height, weight and hazardous
  goods.
- **Large responses.** Long routes return thousands of points, and the line is not
  simplified.
- **ORS quotas.** A free ORS key has daily and per-minute request limits. Requests over
  them return 503.
- **No authentication, rate limiting or caching** on this API.

## Testing

```bash
pytest
```

The tests make no network calls and need no API key:

- **Endpoint tests** use the fake routing provider (straight lines), or a stub that
  returns or raises a fixed result.
- **ORS adapter tests** replay real ORS responses recorded in `routing/tests/fixtures/`
  through an `httpx` mock transport. The files marked `_synthetic` (rate limit and server
  error) were written by hand in the same format, since those errors can't be triggered
  safely.

pytest uses `config/settings_test.py`, which turns file logging off.

## Project layout

```
api/                     HTTP layer
  views.py               GET /api/find-route/ and error responses
  serializers.py         Query parameter parsing and validation
  validators.py          US bounding box and minimum distance
  services.py            Builds the routing provider from settings
  middleware.py          Access log, one line per request
routing/                 Provider-independent routing, no Django imports
  types.py               LatLon, Profile, Route
  errors.py              RouteNotFound, InvalidRouteRequest, RoutingUnavailable
  geo.py                 Haversine distance
  providers/
    openrouteservice.py  ORS adapter
    fake.py              Offline straight-line provider
  tests/fixtures/        Recorded ORS responses
config/                  Django project: settings, URLs, logging
```

## Attribution

Routing by [openrouteservice](https://openrouteservice.org) (HeiGIT).
Map data © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors,
available under the Open Database License (ODbL).
