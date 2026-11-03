# Fuel Route Planner

A Django REST API that returns the driving route between two points in the contiguous
United States, using [openrouteservice](https://openrouteservice.org) (ORS) for routing,
and the cheapest fuel stops along it.

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

Create the database and load the fuel stations (takes about a second, no network):

```bash
python manage.py migrate
python manage.py ingest_fuel_stations
```

Then start the server:

```bash
python manage.py runserver
```

No key yet? Set `ROUTING_PROVIDER=fake` in `.env` to get straight-line routes, fully
offline. Straight lines rarely pass near a station, so trips longer than the tank range
usually return 422 `no_feasible_fuel_plan` in this mode. `.env.example` documents every
other setting (timeouts, logging).

## API

### `GET /api/find-route/`

| Parameter | Required | Format | Allowed values |
|---|---|---|---|
| `start` | yes | `lat,lon` in decimal degrees, e.g. `32.7767,-96.7970` | Inside the contiguous US: latitude 24.396308 to 49.384358, longitude -124.848974 to -66.885444 (inclusive) |
| `finish` | yes | Same as `start` | Same as `start`, and at least 1 km from it in a straight line |
| `profile` | no | `truck` or `car` | Default `truck` |
| `max_range_miles` | no | Number | Miles on a full tank. Over 0, up to 3,000. Default 500 |
| `start_fuel_miles` | no | Number | Miles the fuel at the start lasts. Over `reserve_miles`, up to `max_range_miles`. Default `max_range_miles` (a full tank) |
| `reserve_miles` | no | Number | Fuel to keep in the tank at all times, in miles. 0 to half of `max_range_miles`. Default 0 |
| `mpg` | no | Number | Miles per gallon. Over 0, up to 150. Default 10 |
| `corridor_miles` | no | Number | How far off the route a station may be. Over 0, up to 15. Default 3 |
| `min_stop_saving` | no | Number | Dollars a stop must save to be worth making. 0 or more. Default 5 |

Example request, a 782-mile truck trip from Dallas to Denver with the default settings:

```bash
curl "http://localhost:8000/api/find-route/?start=32.7767,-96.7970&finish=39.7392,-104.9903"
```

Response (trimmed; the full route has 5,449 points):

```json
{
  "profile": "truck",
  "start": {"lat": 32.7767, "lon": -96.797},
  "finish": {"lat": 39.7392, "lon": -104.9903},
  "distance_m": 1259214.4,
  "duration_s": 68176.9,
  "total_cost": 81.53,
  "total_gallons": 28.65,
  "total_detour_miles": 4.07,
  "stops": [
    {
      "station": {
        "opis_id": 72816,
        "name": "QUIKTRIP #7914",
        "address": "I-27 EXIT 117",
        "city": "Amarillo",
        "state": "TX",
        "lat": 35.25345185185185,
        "lon": -101.86565555555555,
        "location_precision": "city"
      },
      "price_per_gallon": 2.8457,
      "distance_from_start_miles": 364.7,
      "offset_miles": 2.03,
      "fuel_on_arrival_miles": 133.2,
      "fuel_added_miles": 286.5,
      "gallons": 28.65,
      "cost": 81.53
    }
  ],
  "points": [
    [32.775944, -96.796753],
    [32.776079, -96.796167],
    ...
    [39.738466, -104.990294]
  ]
}
```

`distance_m` is in metres, `duration_s` in seconds, and `points` is the route line as
`[lat, lon]` pairs, from start to finish. The first and last points are where the route
meets the road, so they can differ slightly from `start` and `finish`.

`stops` lists the fuel stops in travel order, and is empty when the start fuel reaches
the finish. For each stop:

- `distance_from_start_miles` is where the route passes the station, and `offset_miles`
  the straight-line distance from there to the station. Reaching the station and getting
  back to the route uses fuel for twice the offset.
- `fuel_on_arrival_miles` is the range left in the tank on arrival, reserve included.
- `fuel_added_miles` and `gallons` are what to buy, and `cost` what it costs, rounded to
  cents.

`total_cost` adds up the stop costs, `total_gallons` the fuel bought, and
`total_detour_miles` the miles driven off the route. Fuel already in the tank at the
start costs nothing.

### Errors

| Status | `code` | Triggered by |
|---|---|---|
| 400 | — | A missing or malformed coordinate, latitude or longitude out of range, a point outside the contiguous US, an unknown `profile`, `start` and `finish` less than 1 km apart, or a fuel setting outside its allowed values |
| 422 | `route_not_found` | No road route connects the points, a point is more than 5 km from a road (e.g. in water), or the points are in different countries |
| 422 | `invalid_route_request` | The route is over the ORS limit of 6,000 km |
| 422 | `no_feasible_fuel_plan` | No choice of stations reaches the finish: two stations within the corridor, or the start and the first station, are further apart than the usable range (`max_range_miles` minus `reserve_miles`) |
| 503 | `routing_unavailable` | ORS is unreachable, slow (over 15 s), rate-limited or failing, or the API key is missing or rejected |

400 responses use Django REST Framework's standard format, listing errors per field.
The 1 km check is not tied to one field, so its error goes under `non_field_errors`.
Errors from comparing fuel settings go under the field that breaks the rule:

```json
{"start": ["Point must be within the contiguous United States."], "finish": ["This field is required."]}
{"non_field_errors": ["start and finish must be at least 1 km apart."]}
{"reserve_miles": ["Ensure this value is at most half of max_range_miles (250)."]}
```

422 and 503 responses have a generic message and a code. Details about the provider are
only written to the server logs.

```json
{"detail": "No drivable route was found between start and finish.", "code": "route_not_found"}
```

## Logs

Logs go to the console, as plain text or JSON (`LOG_CONSOLE_FORMAT`), and optionally to a
rotating JSON file (`LOG_FILE_ENABLED`). A request logs:

- **One access line**, with the method, path, `status`, `duration_ms` and `query`. Server
  errors (5xx) are logged at ERROR and everything else at INFO, since a 4xx is intentional behavior.
- **The outcome.** `Planned the fuel stops.` with the `stops`, `total_cost`,
  `route_miles`, the stations in the bounding box and in the corridor, `routing_ms` (the
  ORS call) and `planning_ms` (loading stations and planning). Or `Request failed.` with
  the error `code`, and for `no_feasible_fuel_plan` the station counts and usable range.
- **ORS errors**, with the HTTP status and the ORS code and message.

Every line logged during a request has a `request_id`, which is also returned in the
`X-Request-ID` response header. Coordinates are rounded to 2 decimals (about 1 km) in the
query and in ORS messages, so the logs don't record exact addresses. The first request to
use a routing provider logs which one it is, as a warning for the fake one.

```
INFO api/views.py:150: Planned the fuel stops. stops=6 total_cost=710.59 route_miles=2793.7 stations_in_box=3315 stations_in_corridor=323 routing_ms=1863 planning_ms=107 request_id=0e9b7411...
INFO api/middleware.py:65: GET /api/find-route/ status=200 duration_ms=1981 query=start=40.71,-74.01&finish=34.05,-118.24 request_id=0e9b7411...
```

## Fuel station data

`python manage.py ingest_fuel_stations` loads the stations into the `FuelStation` model
from three files in the project root. Each run replaces all stations in one transaction.
Options `--fuel-csv`, `--postal-codes` and `--exits` point it at other copies.

| File | Contents |
|---|---|
| `fuel-prices-for-be-assessment.csv` | Truck stops with their address, city, state and retail price |
| `geonames-us-postal-codes.txt` | US ZIP codes with their place name and coordinates (GeoNames) |
| `osm-interstate-exits.csv` | Interstate exit coordinates by state, interstate and exit number (OpenStreetMap) |

The fuel CSV has no coordinates, so each station is located from its address and city:

1. **Cleaning.** Fields are trimmed and repeated spaces collapsed. Rows with a missing or
   invalid value are skipped and logged with their line number. Rows outside the
   contiguous US (the file also lists Canadian stations) are dropped, and so are duplicate
   rows, ignoring the station name, which only varies in spelling.
2. **One station per OPIS ID.** Some IDs have several rows with different prices and no
   date to say which is current. The station's `retail_price` is their average;
   `price_min`, `price_max` and `price_count` keep the spread.
3. **Location at the exit.** Most addresses name an interstate exit, e.g.
   `I-44, EXIT 283 & US-69`. If that exit is in the OSM file, the station is placed there
   (`location_precision = "exit"`). One exit has a point per ramp, so the points of the
   interchange nearest the city are averaged.
4. **Location at the city, otherwise.** The city's point is the average of its GeoNames
   ZIP codes (`location_precision = "city"`). City names are matched across spellings
   such as "Saint" and "St.". An exit more than 40 km from the city is treated as an error
   in the source data, logged, and the city is used instead. Stations whose city is not
   in GeoNames are skipped and logged.

With the current files, the command drops 620 rows outside the contiguous US and 128
duplicates, and saves 6,626 stations: 3,145 at an interstate exit and 3,481 at their city.

The data exploration behind these rules, and the alternatives that were rejected, are in
[`notebooks/station_data.ipynb`](notebooks/station_data.ipynb).

## How fuel stops are chosen

1. **Stations near the route.** Stations inside the route's bounding box are loaded from
   the database. Each is placed at the nearest point on the route line, and kept if its
   straight-line offset from there is at most `corridor_miles`.
2. **Detours cost fuel.** A stop drives to the station and back, so it uses twice its
   offset on top of the route. A cheap station far off the route can lose to a slightly
   dearer one at the exit.
3. **The cheapest plan, exactly.** For a fixed set of stops, some cheapest plan either
   fills the tank at each stop or buys just enough to reach the next one (Khuller,
   Malekian and Mestre, "To fill or not to fill: the gas station problem", 2011). A dynamic
   program over the stations uses this to find the cheapest plan, not an approximation.
   In practice it fills up at cheap stations and buys just enough at expensive ones to
   reach the next cheap one. The last stop buys only what reaches the finish.
4. **Stops must be worth it.** Each stop counts `min_stop_saving` extra in the search,
   so a stop is made only if it saves more than that. Stops the trip can't do without are
   always made. The extra amount is left out of the reported cost.

Planning takes tens of milliseconds for a coast-to-coast route at the default 3-mile
corridor, which holds a few hundred stations.

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
- **Miles for every fuel setting.** Range, start fuel, reserve, corridor and the stop
  distances are in miles, to match the miles per gallon. The route itself keeps
  `distance_m` in metres.
- **The reserve is never used.** The fuel level stays at or above `reserve_miles`
  everywhere, including on arrival at stations and at the finish, so the usable tank is
  `max_range_miles - reserve_miles`.
- **Start fuel is free.** Only the fuel bought along the way counts towards the cost.
- **One fuel efficiency for every vehicle.** `mpg` is a plain input, the same for both
  profiles. It changes the gallons and the cost, but not which stations are chosen.
- **Fuel can be bought in any amount.** Each stop buys exactly what the plan needs.
- **Planning has its own package.** `fuel_planner/` takes plain route and station data
  and has no Django imports, like `routing/`. The `api` app loads the stations and
  wires them together.
- **Routing sits behind its own interface.** `routing/` has its own types and errors, and
  ORS is one adapter behind it, so the provider can be replaced without changing the API.

## Limitations

- **6,000 km cap.** ORS's public API refuses routes it estimates at over 6,000 km, and this
  API returns 422 `invalid_route_request` for them. A typical coast-to-coast trip
  (about 4,500 km) is well under the cap, but diagonal trips like from Washington to Florida might not fit.
- **The US check is a bounding box.** It also accepts parts of southern Canada, northern
  Mexico and nearby water. Points in water fail with 422, but a trip with both points in
  Canada, such as Toronto to Ottawa, can get a Canadian route.
- **Two points only.** A trip can't pass through waypoints of its own choosing, though
  `routing/` already accepts any number of them.
- **No truck restrictions.** The truck profile ignores vehicle height, weight and hazardous
  goods.
- **Large responses.** Long routes return thousands of points, and the line is not
  simplified.
- **ORS quotas.** A free ORS key has daily and per-minute request limits. Requests over
  them return 503.
- **No authentication, rate limiting or caching** on this API.
- **Stops are not on the route line.** The route is not recalculated through the chosen
  stations, which would cost another ORS request. Detours are estimated from the
  straight-line offset, which is a little shorter than the drive on the road.
- **No time cost.** A stop's only cost is its detour fuel and `min_stop_saving`. Driving
  time and opening hours are ignored, and every station is assumed to have fuel.
- **One price per station.** Stations with several prices in the source data use their
  average.
- **Station locations are approximate.** Exit-located stations are within about a
  kilometre of the interchange. City-located stations can be several kilometres off, and
  in large cities such as Phoenix or El Paso, tens of kilometres.

## Designing for production

This project runs with nothing beyond an ORS key: SQLite, the public ORS API, and a fuel
price CSV loaded once. For production I'd change the following. Each item names the
limitation above that it lifts.

### API

- **POST, or QUERY where supported, instead of GET.** GET suits this scope (see
  [Assumptions and decisions](#assumptions-and-decisions)), but coordinates in a URL end
  up in proxy and server logs, browser history and `Referer` headers, and a trip's start
  is often a home or a depot. A request body keeps them out, and carries credentials and
  larger inputs such as a vehicle profile more naturally. QUERY is the better fit where
  clients and proxies support it: like GET, it is safe to repeat and its responses can be
  cached. POST works everywhere but loses both.
- **Authentication, rate limiting and caching.** A key per customer, quotas per key so no
  single caller uses up the routing capacity, and a cache of recent routes keyed on the
  rounded points and the vehicle. Lifts *No authentication, rate limiting or caching*.
- **Smaller responses.** Simplify the route line to the detail a map needs, and send it
  as an encoded polyline instead of `[lat, lon]` pairs. Lifts *Large responses*.

### Routing

- **A self-hosted routing engine.** ORS can run on our own servers from the same
  OpenStreetMap data. On a coast-to-coast trip the ORS call takes about 1.9 s of a 2 s
  request, so this is where request time goes. It also removes the distance cap and the
  quotas. Lifts *6,000 km cap* and *ORS quotas*.
- **Routing through the chosen stops.** A second request, with the stops as waypoints,
  gives the real route and exact detours instead of estimates from the straight-line
  offset. With a self-hosted engine the extra request is cheap. Lifts *Stops are not on
  the route line*.

### Planning model

- **Cost beyond fuel.** The plan would minimise the whole trip's cost: fuel, tolls, and
  driving time, including the time each stop adds. Fuel use would vary along the route
  instead of being one `mpg`: speed limits set the speed on each stretch, and a loaded
  truck uses far more fuel climbing than on the flat. Required rest breaks under
  hours-of-service rules would be planned too, since they are natural places to refuel.
  Lifts *No time cost*, and the single `mpg` in
  [Assumptions and decisions](#assumptions-and-decisions).
- **Per-vehicle profiles.** Each vehicle would have its own profile: tank size, fuel use
  by speed, load and grade, fuel type, and its height, weight, axles and any hazardous
  goods. The dimensions and weight go to the routing engine, so routes avoid low bridges
  and weight-limited roads; the rest feeds the planner. Lifts *No truck restrictions*.

### Data

- **PostgreSQL with PostGIS.** Postgres handles concurrent reads and writes. SQLite
  allows one writer at a time, while the pipeline below writes all day as requests read.
  PostGIS also moves the spatial work into the database. Stations in the corridor would
  come from one indexed query on the route line, split into short pieces
  (`ST_Subdivide`, `ST_DWithin`), and points would be checked against the real US
  boundary instead of a box. This could speed up planning too: on a coast-to-coast trip,
  loading the stations and keeping those in the corridor takes about 60 ms today, most
  of it in Python. Lifts *The US check is a bounding box*.
- **An ingestion pipeline.** Prices change daily, so they would arrive as scheduled feeds
  instead of a CSV loaded once. Each price keeps its source and time, so the planner uses
  the latest and skips stale ones. Station availability (closures, opening hours, fuel
  outages) would come in the same way, and live traffic would feed the routing engine.
  Station coordinates would come from the data provider or from geocoding the full
  address, instead of from exits and cities. Lifts *One price per station* and *Station
  locations are approximate*.

## Development

`requirements.txt` has only what the API needs. `requirements-dev.txt` adds the test and
notebook tools:

```bash
pip install -r requirements-dev.txt
```

### Testing

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
- **Fuel planner tests** use made-up stations along a line. The search is checked against
  a brute-force search over every possible plan, on small random trips.
- **Station ingestion tests** build small data files in a temporary folder, one rule per
  test, and never read the real data files.

pytest uses `config/settings_test.py`, which turns file logging off.

### Postman collection

[`postman/fuel-route-planner.postman_collection.json`](postman/fuel-route-planner.postman_collection.json)
has three requests against a running server: New York to Los Angeles (several stops),
Dallas to Houston (no stops) and a start outside the US (400). Each has tests and a saved
example response. The long route's tests walk the trip stop by stop, checking the fuel,
gallons and cost at each, and its Visualize tab shows the stops as a table. Set the
`baseUrl` collection variable if the server isn't on `http://localhost:8000`. The
requests call ORS, so they need an API key. To run them from the command line:

```bash
npx newman run postman/fuel-route-planner.postman_collection.json
```

### Notebook

[`notebooks/station_data.ipynb`](notebooks/station_data.ipynb) explores the fuel data and
explains the ingestion rules, including the data sources and geocoding that were
considered and rejected. It is saved with its outputs, so it can be read on GitHub
without running it. It imports the rules from `stations/ingest.py`, so after changing
them, regenerate the outputs with a clean run from top to bottom:

```bash
jupyter execute --inplace notebooks/station_data.ipynb
```

## Project layout

```
api/                     HTTP layer
  views.py               GET /api/find-route/ and error responses
  serializers.py         Query parameter parsing and validation
  validators.py          US bounding box and minimum distance
  services.py            Builds the routing provider, loads stations near a route
  middleware.py          Request IDs and the access log, one line per request
routing/                 Provider-independent routing, no Django imports
  types.py               LatLon, Profile, Route
  errors.py              RouteNotFound, InvalidRouteRequest, RoutingUnavailable
  geo.py                 Haversine distance, Polyline (nearest point on a route)
  providers/
    openrouteservice.py  ORS adapter
    fake.py              Offline straight-line provider
  tests/fixtures/        Recorded ORS responses
fuel_planner/            Fuel stop planning, no Django imports
  types.py               PlanOptions, Station, FuelStop, FuelPlan
  corridor.py            Places the stations near the route on it
  optimizer.py           The cheapest stops and purchases
  planner.py             plan_fuel_stops: corridor, optimizer, gallons and costs
stations/                Fuel stations
  models.py              FuelStation
  ingest.py              Cleaning, merging and locating stations, no Django imports
  management/commands/
    ingest_fuel_stations.py  Loads the stations into the database
config/                  Django project: settings, URLs, logging
notebooks/
  station_data.ipynb     Data exploration behind the station ingestion
fuel-prices-for-be-assessment.csv  Source fuel prices
geonames-us-postal-codes.txt       ZIP code coordinates
osm-interstate-exits.csv           Interstate exit coordinates
```

## Attribution

Routing by [openrouteservice](https://openrouteservice.org) (HeiGIT).
Map data © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors,
available under the Open Database License (ODbL).

Data files in this repo:

- **`geonames-us-postal-codes.txt`** is the US postal code file from
  [GeoNames](https://www.geonames.org), downloaded from
  <https://download.geonames.org/export/zip/> on 2026-11-02 and kept unmodified. It is
  licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
- **`osm-interstate-exits.csv`** contains data © [OpenStreetMap](https://www.openstreetmap.org/copyright)
  contributors. It lists the interstate exits (`highway=motorway_junction` nodes) of the
  48 contiguous states, pulled from the Overpass API on 2026-11-02. It is licensed under
  the [Open Database License (ODbL)](https://opendatacommons.org/licenses/odbl/), and so is
  any database built from it.
