"""Build fuel station records from the raw data files.

This module has no Django imports, so it can be tested without a database. The
ingest_fuel_stations command reads the files through build_stations() and saves the result.

The steps, in order:

1. Clean every field: trim it and collapse runs of whitespace to one space.
2. Skip rows with a missing or invalid value, logging each one.
3. Drop rows outside the contiguous US. The source also lists Canadian stations.
4. Drop duplicate rows. The station name is ignored, since it only varies in spelling.
5. Merge the rows of each OPIS ID into one station, priced at the average of its rows.
6. Locate each station at the interstate exit in its address, when that exit is in the
   OSM data and within EXIT_MAX_DISTANCE_M of the city. Otherwise locate it at its city:
   the average of the city's GeoNames ZIP code points. Stations whose city is not in
   GeoNames are skipped and logged.
"""

import csv
import logging
import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from routing import LatLon, haversine_m

logger = logging.getLogger(__name__)

# The 48 contiguous states and DC, the area the route API accepts.
CONTIGUOUS_US_STATES = frozenset({
    'AL', 'AR', 'AZ', 'CA', 'CO', 'CT', 'DC', 'DE', 'FL', 'GA', 'IA', 'ID', 'IL', 'IN',
    'KS', 'KY', 'LA', 'MA', 'MD', 'ME', 'MI', 'MN', 'MO', 'MS', 'MT', 'NC', 'ND', 'NE',
    'NH', 'NJ', 'NM', 'NV', 'NY', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC', 'SD', 'TN', 'TX',
    'UT', 'VA', 'VT', 'WA', 'WI', 'WV', 'WY',
})

# An exit farther than this from the station's city is treated as a data error, and the
# city is used instead. Real stations are rarely more than 25 km from their mailing city;
# mismatched exits are usually more than 40 km away.
EXIT_MAX_DISTANCE_M = 40_000

# OSM has one point per ramp, so one exit has several points, up to about 3 km apart.
# Points farther apart than this are separate places that share an exit number.
EXIT_CLUSTER_RADIUS_M = 3_000

PRICE_PLACES = Decimal('0.0001')

# Column names in the fuel price CSV, by field.
FUEL_COLUMNS = {
    'opis_id': 'OPIS Truckstop ID',
    'name': 'Truckstop Name',
    'address': 'Address',
    'city': 'City',
    'state': 'State',
    'rack_id': 'Rack ID',
    'price': 'Retail Price',
}

EXIT_COLUMNS = ('state', 'interstate', 'exit_ref', 'lat', 'lon')

# Columns of the GeoNames postal code file, which has no header row.
GEONAMES_PLACE, GEONAMES_STATE, GEONAMES_LAT, GEONAMES_LON = 2, 4, 9, 10

# An interstate followed by an exit number, e.g. "I-44, EXIT 283 & US-69" or
# "I-94 & US-12, EXIT 210". The interstate nearest the exit wins: in "I-80 & I-90, EXIT 3"
# it is I-90. The interstate may have a letter, which is either a branch (I-35W) or a
# direction (I-81S).
EXIT_ADDRESS = re.compile(
    r'\bI-?\s?(\d+)([A-Z]?)\b'     # the interstate and its letter
    r'(?:(?!\bI-?\s?\d).)*?'       # anything but another interstate
    r'\bEXIT\s*#?\s*(\d+)',        # the exit number
    re.IGNORECASE,
)


class DataFileError(Exception):
    """A data file cannot be read, e.g. it lacks a required column."""


@dataclass(frozen=True)
class FuelRow:
    """One valid row of the fuel price CSV, with its fields cleaned.

    Attributes:
        line: The row's line number in the file, for log messages.
        opis_id: The station's OPIS Truckstop ID.
        name: The station name.
        address: The address.
        city: The city.
        state: The state code.
        rack_id: The rack ID.
        price: The retail price, in dollars per gallon.
    """

    line: int
    opis_id: int
    name: str
    address: str
    city: str
    state: str
    rack_id: int
    price: Decimal

    def duplicate_key(self) -> tuple:
        """Return the fields that make two rows duplicates: all but the name and line."""
        return (self.opis_id, self.address, self.city, self.state, self.rack_id, self.price)


@dataclass(frozen=True)
class StationRecord:
    """A station ready to save. The fields match the FuelStation model."""

    opis_id: int
    name: str
    address: str
    city: str
    state: str
    rack_id: int
    retail_price: Decimal
    price_min: Decimal
    price_max: Decimal
    price_count: int
    lat: float
    lon: float
    location_precision: str


@dataclass
class IngestReport:
    """Counts of what happened to the rows and stations, for the command's summary.

    Attributes:
        rows_read: Data rows in the fuel price CSV.
        rows_invalid: Rows skipped for a missing or invalid value.
        rows_outside_us: Rows dropped for a state outside the contiguous US.
        rows_duplicate: Rows dropped as duplicates of an earlier row.
        stations_without_city: Stations skipped because their city is not in GeoNames.
        stations_at_exit: Stations located at an interstate exit.
        stations_at_city: Stations located at their city.
        exits_too_far: Of stations_at_city, those whose exit was found but was more than
            EXIT_MAX_DISTANCE_M from the city.
    """

    rows_read: int = 0
    rows_invalid: int = 0
    rows_outside_us: int = 0
    rows_duplicate: int = 0
    stations_without_city: int = 0
    stations_at_exit: int = 0
    stations_at_city: int = 0
    exits_too_far: int = 0


def clean_field(value: str) -> str:
    """Return the value trimmed, with each run of whitespace replaced by one space."""
    return ' '.join(value.split())


def normalize_place(name: str) -> str:
    """Return a place name in a form that matches across spellings.

    Lowercases, drops periods and apostrophes, shortens Saint, Fort and Mount, and removes
    spaces and hyphens, so "Saint Louis", "St. Louis" and "St Louis" all match, as do
    "Mc Calla" and "McCalla".

    Args:
        name: A place name.

    Returns:
        The normalized name.
    """
    name = name.lower().replace('.', '').replace("'", '')
    name = re.sub(r'\bsaint\b', 'st', name)
    name = re.sub(r'\bfort\b', 'ft', name)
    name = re.sub(r'\bmount\b', 'mt', name)
    return re.sub(r'[\s-]', '', name)


def parse_exit_address(address: str) -> tuple[list[str], int] | None:
    """Find the interstate exit in an address.

    Args:
        address: A station address, e.g. "I-44, EXIT 283 & US-69".

    Returns:
        The interstate names to look up, in order, and the exit number, e.g.
        (["44"], 283). An interstate with a letter gives two names, e.g. ["35W", "35"],
        since the letter may be a branch with its own exits or just a direction. None if
        the address has no interstate exit.
    """
    match = EXIT_ADDRESS.search(address)
    if match is None:
        return None
    number, letter, exit_number = match.groups()
    names = [number + letter.upper(), number] if letter else [number]
    return names, int(exit_number)


def mean_point(points: list[LatLon]) -> LatLon:
    """Return the average of the points."""
    return LatLon(
        sum(p.lat for p in points) / len(points),
        sum(p.lon for p in points) / len(points),
    )


def locate_exit(points: list[LatLon], city: LatLon) -> LatLon:
    """Pick one location for an exit from its OSM points.

    Takes the point nearest the city and averages it with the points within
    EXIT_CLUSTER_RADIUS_M of it, which are the other ramps of the same interchange. Points
    farther away share the exit number but are elsewhere, and are ignored.

    Args:
        points: The exit's points. Must not be empty.
        city: The station's city.

    Returns:
        The exit's location.
    """
    nearest = min(points, key=lambda p: haversine_m(p, city))
    return mean_point([p for p in points if haversine_m(p, nearest) <= EXIT_CLUSTER_RADIUS_M])


def load_city_points(path: Path) -> dict[tuple[str, str], LatLon]:
    """Read the GeoNames postal code file into one point per city.

    Args:
        path: The tab-separated GeoNames file, without a header row.

    Returns:
        The average of each city's ZIP code points, keyed by (normalized city name, state
        code).

    Raises:
        DataFileError: A row is too short or has a non-numeric coordinate.
    """
    points: dict[tuple[str, str], list[LatLon]] = {}
    with open(path, newline='', encoding='utf-8') as f:
        for line, row in enumerate(csv.reader(f, delimiter='\t', quoting=csv.QUOTE_NONE), 1):
            try:
                point = LatLon(float(row[GEONAMES_LAT]), float(row[GEONAMES_LON]))
            except (IndexError, ValueError) as e:
                raise DataFileError(f'{path.name} line {line}: not a GeoNames postal code row.') from e
            key = (normalize_place(row[GEONAMES_PLACE]), row[GEONAMES_STATE])
            points.setdefault(key, []).append(point)
    return {key: mean_point(city_points) for key, city_points in points.items()}


def load_exits(path: Path) -> dict[tuple[str, str, int], list[LatLon]]:
    """Read the OSM interstate exits file.

    An exit_ref can name several exits ("21;22") and have a letter ("283A"). Each number
    is indexed separately, without its letter, since addresses rarely give the letter.

    Args:
        path: The exits CSV, with the columns in EXIT_COLUMNS.

    Returns:
        The points of each exit, keyed by (state code, interstate, exit number), e.g.
        ("OK", "44", 283) or ("TX", "35W", 8).

    Raises:
        DataFileError: The file lacks a column or has a non-numeric coordinate.
    """
    exits: dict[tuple[str, str, int], list[LatLon]] = {}
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        missing = [c for c in EXIT_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise DataFileError(f'{path.name} is missing columns: {", ".join(missing)}.')
        for row in reader:
            try:
                point = LatLon(float(row['lat']), float(row['lon']))
            except (TypeError, ValueError) as e:
                raise DataFileError(f'{path.name} line {reader.line_num}: invalid coordinates.') from e
            for part in re.split(r'[;/]', row['exit_ref']):
                number = re.match(r'\s*(\d+)', part)
                if number:
                    key = (row['state'], row['interstate'], int(number.group(1)))
                    exits.setdefault(key, []).append(point)
    return exits


def parse_fuel_row(raw: dict[str, str | None], line: int) -> FuelRow:
    """Clean and validate one row of the fuel price CSV.

    Args:
        raw: The row as read by csv.DictReader.
        line: The row's line number.

    Returns:
        The row.

    Raises:
        ValueError: A value is missing or invalid. The message says which.
    """
    values = {}
    for field, column in FUEL_COLUMNS.items():
        value = raw.get(column)
        if value is None or not clean_field(value):
            raise ValueError(f'{column} is empty')
        values[field] = clean_field(value)

    for field in ('opis_id', 'rack_id'):
        if not values[field].isdigit():
            raise ValueError(f'{FUEL_COLUMNS[field]} is not a whole number: {values[field]!r}')
    try:
        price = Decimal(values['price'])
    except InvalidOperation:
        price = None
    if price is None or not price.is_finite() or price <= 0:
        raise ValueError(f'Retail Price is not a positive number: {values["price"]!r}')

    return FuelRow(
        line=line,
        opis_id=int(values['opis_id']),
        name=values['name'],
        address=values['address'],
        city=values['city'],
        state=values['state'],
        rack_id=int(values['rack_id']),
        price=price,
    )


def read_fuel_rows(path: Path, report: IngestReport) -> list[FuelRow]:
    """Read the fuel price CSV and apply steps 1 to 4 of the module docstring.

    Args:
        path: The fuel price CSV.
        report: Updated with the rows read, skipped and dropped.

    Returns:
        The remaining rows, in file order.

    Raises:
        DataFileError: The file lacks a column.
    """
    rows = []
    seen = set()
    with open(path, newline='', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        missing = [c for c in FUEL_COLUMNS.values() if c not in (reader.fieldnames or [])]
        if missing:
            raise DataFileError(f'{path.name} is missing columns: {", ".join(missing)}.')
        for raw in reader:
            report.rows_read += 1
            try:
                row = parse_fuel_row(raw, reader.line_num)
            except ValueError as e:
                report.rows_invalid += 1
                logger.warning('Skipped invalid fuel price row.', extra={'line': reader.line_num, 'reason': str(e)})
                continue
            if row.state not in CONTIGUOUS_US_STATES:
                report.rows_outside_us += 1
                continue
            if row.duplicate_key() in seen:
                report.rows_duplicate += 1
                continue
            seen.add(row.duplicate_key())
            rows.append(row)
    return rows


def average_price(prices: list[Decimal]) -> Decimal:
    """Return the average of the prices, rounded to PRICE_PLACES."""
    return (sum(prices) / len(prices)).quantize(PRICE_PLACES, rounding=ROUND_HALF_UP)


def build_stations(
    fuel_path: Path,
    postal_codes_path: Path,
    exits_path: Path,
) -> tuple[list[StationRecord], IngestReport]:
    """Read the data files and build one record per station.

    Args:
        fuel_path: The fuel price CSV.
        postal_codes_path: The GeoNames US postal code file.
        exits_path: The OSM interstate exits CSV.

    Returns:
        The stations, in order of their first row in the fuel price CSV, and a report of
        what was skipped or dropped and how stations were located.

    Raises:
        DataFileError: A file lacks a column or has an unreadable row.
    """
    report = IngestReport()
    rows = read_fuel_rows(fuel_path, report)
    city_points = load_city_points(postal_codes_path)
    exits = load_exits(exits_path)

    groups: dict[int, list[FuelRow]] = {}
    for row in rows:
        groups.setdefault(row.opis_id, []).append(row)

    stations = []
    for opis_id, group in groups.items():
        first = group[0]
        if len({(r.address, r.city, r.state, r.rack_id) for r in group}) > 1:
            logger.warning(
                'OPIS ID has rows with different details; using the first row.',
                extra={'opis_id': opis_id, 'lines': [r.line for r in group]},
            )

        city = city_points.get((normalize_place(first.city), first.state))
        if city is None:
            report.stations_without_city += 1
            logger.warning(
                'Skipped station: city not found in GeoNames.',
                extra={'opis_id': opis_id, 'city': first.city, 'state': first.state},
            )
            continue

        location, precision = locate_station(first, city, exits, report)
        prices = [r.price for r in group]
        stations.append(StationRecord(
            opis_id=opis_id,
            name=first.name,
            address=first.address,
            city=first.city,
            state=first.state,
            rack_id=first.rack_id,
            retail_price=average_price(prices),
            price_min=min(prices).quantize(PRICE_PLACES, rounding=ROUND_HALF_UP),
            price_max=max(prices).quantize(PRICE_PLACES, rounding=ROUND_HALF_UP),
            price_count=len(prices),
            lat=location.lat,
            lon=location.lon,
            location_precision=precision,
        ))
    return stations, report


def locate_station(
    row: FuelRow,
    city: LatLon,
    exits: dict[tuple[str, str, int], list[LatLon]],
    report: IngestReport,
) -> tuple[LatLon, str]:
    """Locate a station at the exit in its address, or else at its city.

    Args:
        row: The station's first row.
        city: The station's city point.
        exits: The OSM exits, as returned by load_exits().
        report: Updated with how the station was located.

    Returns:
        The location, and "exit" or "city" for how it was found.
    """
    parsed = parse_exit_address(row.address)
    if parsed is not None:
        interstates, exit_number = parsed
        for interstate in interstates:
            points = exits.get((row.state, interstate, exit_number))
            if not points:
                continue
            location = locate_exit(points, city)
            distance_m = haversine_m(location, city)
            if distance_m <= EXIT_MAX_DISTANCE_M:
                report.stations_at_exit += 1
                return location, 'exit'
            report.exits_too_far += 1
            logger.info(
                'Exit is far from the listed city; located the station at the city.',
                extra={
                    'opis_id': row.opis_id,
                    'address': row.address,
                    'city': row.city,
                    'state': row.state,
                    'distance_km': round(distance_m / 1000),
                },
            )
            break
    report.stations_at_city += 1
    return city, 'city'
