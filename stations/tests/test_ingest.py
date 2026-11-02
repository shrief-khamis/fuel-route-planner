import logging
from decimal import Decimal

import pytest

from routing import LatLon
from stations.ingest import (
    DataFileError,
    build_stations,
    clean_field,
    locate_exit,
    normalize_place,
    parse_exit_address,
)

BIG_CABIN = LatLon(36.53, -95.22)
EXIT_283 = LatLon((36.5612 + 36.5680) / 2, (-95.2179 + -95.2135) / 2)


def station_row(opis_id='7', name='WOODSHED', address='I-44, EXIT 283 & US-69',
                city='Big Cabin', state='OK', rack_id='307', price='3.009'):
    """Return a fuel CSV row, with defaults for a station at I-44 exit 283."""
    return [opis_id, name, address, city, state, rack_id, price]


def build(data_files, rows, **files):
    """Write the files and build stations from them."""
    return build_stations(*data_files(rows, **files))


@pytest.mark.parametrize('value, expected', [
    ('  PILOT  TRAVEL   CENTER ', 'PILOT TRAVEL CENTER'),
    ('Big\tCabin', 'Big Cabin'),
    ('', ''),
])
def test_clean_field(value, expected):
    """Fields are trimmed and runs of whitespace become one space."""
    assert clean_field(value) == expected


@pytest.mark.parametrize('a, b', [
    ('Saint Louis', 'St. Louis'),
    ('Saint Louis', 'St Louis'),
    ('Mc Calla', 'McCalla'),
    ('De Forest', 'DeForest'),
    ('Winston Salem', 'Winston-Salem'),
    ('Fort Worth', 'Ft. Worth'),
    ('Mount Vernon', 'Mt Vernon'),
    ("Coeur d'Alene", 'Coeur dAlene'),
])
def test_normalize_place_matches_spellings(a, b):
    """Common spelling differences normalize to the same name."""
    assert normalize_place(a) == normalize_place(b)


def test_normalize_place_keeps_different_places_apart():
    """Saint only shortens as a whole word, so Saintville is not Stville."""
    assert normalize_place('Saintville') != normalize_place('Stville')


@pytest.mark.parametrize('address, expected', [
    ('I-44, EXIT 283 & US-69', (['44'], 283)),
    ('I-94 & US-12, EXIT 210', (['94'], 210)),
    ('I-80 & I-90, EXIT 3', (['90'], 3)),
    ('I-35W, EXIT 36 & CR-23', (['35W', '35'], 36)),
    ('I 35W EXIT 8', (['35W', '35'], 8)),
    ('I-81S, EXIT 10', (['81S', '81'], 10)),
    ('I-75, EXIT 283A', (['75'], 283)),
    ('US-51 & US-2', None),
    ('I-78/US-22', None),
    ('1323 E MAIN ST', None),
])
def test_parse_exit_address(address, expected):
    """The interstate nearest the exit is found, with and without its letter."""
    assert parse_exit_address(address) == expected


def test_locate_exit_averages_the_ramps_nearest_the_city():
    """Points of the nearest interchange are averaged; a same-numbered exit far away is ignored."""
    ramps = [LatLon(36.5612, -95.2179), LatLon(36.5680, -95.2135)]
    elsewhere = LatLon(34.1173, -98.5204)
    assert locate_exit([elsewhere, *ramps], BIG_CABIN) == EXIT_283


def test_station_at_exit(data_files):
    """A station whose exit is near its city is located at the exit."""
    stations, report = build(data_files, [station_row()])

    [station] = stations
    assert (station.lat, station.lon) == pytest.approx(EXIT_283)
    assert station.location_precision == 'exit'
    assert report.stations_at_exit == 1


def test_station_without_exit_is_at_its_city(data_files):
    """A station without an exit in its address is located at its city."""
    stations, report = build(data_files, [station_row(address='US-69 & SR-28')])

    [station] = stations
    assert (station.lat, station.lon) == pytest.approx(BIG_CABIN)
    assert station.location_precision == 'city'
    assert report.stations_at_city == 1


def test_exit_missing_from_osm_falls_back_to_city(data_files):
    """An exit that is not in the OSM data leaves the station at its city."""
    [station], _ = build(data_files, [station_row(address='I-44, EXIT 999')])
    assert station.location_precision == 'city'


def test_exit_too_far_from_city_falls_back_to_city(data_files, caplog):
    """An exit more than 40 km from the city is distrusted, counted and logged."""
    with caplog.at_level(logging.INFO, logger='stations.ingest'):
        [station], report = build(data_files, [station_row(address='I-44, EXIT 1')])

    assert (station.lat, station.lon) == pytest.approx(BIG_CABIN)
    assert station.location_precision == 'city'
    assert report.exits_too_far == 1
    assert caplog.records[0].opis_id == 7


def test_city_point_is_the_average_of_its_zip_codes(data_files):
    """A city with several ZIP codes is located at their average."""
    [station], _ = build(data_files, [station_row(address='SR-183', city='Fort Worth', state='TX')])
    assert (station.lat, station.lon) == pytest.approx((32.75, -97.33))


def test_branch_interstate_is_preferred(data_files):
    """I-35W exit 8 matches the I-35W exit, not I-35 exit 8 in another part of the state."""
    [station], _ = build(data_files, [station_row(address='I-35W, EXIT 8', city='Fort Worth', state='TX')])
    assert (station.lat, station.lon) == pytest.approx((32.65, -97.32))
    assert station.location_precision == 'exit'


def test_direction_letter_falls_back_to_plain_interstate(data_files):
    """A letter that is not a branch in OSM (I-44E) is ignored."""
    [station], _ = build(data_files, [station_row(address='I-44E, EXIT 283')])
    assert station.location_precision == 'exit'


def test_city_names_are_normalized(data_files):
    """St. Louis in the fuel data matches Saint Louis in GeoNames."""
    stations, _ = build(data_files, [station_row(address='I-70', city='St. Louis', state='MO')])
    assert len(stations) == 1


def test_fields_are_cleaned(data_files):
    """Whitespace in the source is trimmed and collapsed before use."""
    [station], _ = build(data_files, [station_row(name='  PILOT  #1243 ', city=' Big  Cabin ')])
    assert station.name == 'PILOT #1243'
    assert station.city == 'Big Cabin'


def test_repeated_ids_are_averaged(data_files):
    """Rows with the same OPIS ID become one station priced at their average."""
    rows = [station_row(price='3.00'), station_row(price='3.50'), station_row(price='3.10')]
    [station], _ = build(data_files, rows)

    assert station.retail_price == Decimal('3.2000')
    assert station.price_min == Decimal('3.0000')
    assert station.price_max == Decimal('3.5000')
    assert station.price_count == 3


def test_average_is_rounded_to_four_places(data_files):
    """The average is rounded half up to 4 decimal places."""
    rows = [station_row(price='3.00733333'), station_row(price='3.00733334')]
    [station], _ = build(data_files, rows)
    assert station.retail_price == Decimal('3.0073')


def test_duplicates_ignore_the_name(data_files):
    """Rows that differ only in the name count once, and the first name is kept."""
    rows = [
        station_row(name='PILOT #1243', price='3.00'),
        station_row(name='PILOT TRAVEL CENTER #1243', price='3.00'),
        station_row(name='PILOT #1243', price='3.50'),
    ]
    [station], report = build(data_files, rows)

    assert station.name == 'PILOT #1243'
    assert station.retail_price == Decimal('3.2500')
    assert station.price_count == 2
    assert report.rows_duplicate == 1


def test_rows_outside_contiguous_us_are_dropped(data_files):
    """Canadian provinces, Alaska and Hawaii are dropped and counted."""
    rows = [
        station_row(opis_id='1', state='ON'),
        station_row(opis_id='2', state='AK'),
        station_row(opis_id='3', state='HI'),
        station_row(opis_id='4'),
    ]
    stations, report = build(data_files, rows)

    assert [s.opis_id for s in stations] == [4]
    assert report.rows_outside_us == 3


@pytest.mark.parametrize('row, reason', [
    (station_row(price='abc'), 'Retail Price is not a positive number'),
    (station_row(price='0'), 'Retail Price is not a positive number'),
    (station_row(price='NaN'), 'Retail Price is not a positive number'),
    (station_row(opis_id='7a'), 'OPIS Truckstop ID is not a whole number'),
    (station_row(rack_id='-1'), 'Rack ID is not a whole number'),
    (station_row(city='  '), 'City is empty'),
    (['7', 'WOODSHED', 'I-44'], 'City is empty'),
])
def test_invalid_rows_are_skipped_and_logged(data_files, caplog, row, reason):
    """A row with a missing or invalid value is skipped, counted and logged with its line."""
    with caplog.at_level(logging.WARNING, logger='stations.ingest'):
        stations, report = build(data_files, [station_row(opis_id='1'), row])

    assert [s.opis_id for s in stations] == [1]
    assert report.rows_invalid == 1
    [record] = caplog.records
    assert record.line == 3
    assert record.reason.startswith(reason)


def test_station_with_unknown_city_is_skipped_and_logged(data_files, caplog):
    """A station whose city is not in GeoNames is skipped, counted and logged."""
    with caplog.at_level(logging.WARNING, logger='stations.ingest'):
        stations, report = build(data_files, [station_row(city='Nowhere')])

    assert stations == []
    assert report.stations_without_city == 1
    assert caplog.records[0].city == 'Nowhere'


def test_report_counts_rows_read(data_files):
    """Every data row is counted as read, whatever happens to it."""
    rows = [station_row(), station_row(), station_row(state='QC'), station_row(price='x')]
    _, report = build(data_files, rows)

    assert report.rows_read == 4
    assert report.rows_duplicate == 1
    assert report.rows_outside_us == 1
    assert report.rows_invalid == 1


def test_missing_fuel_column_raises(data_files):
    """A fuel CSV without a required column raises DataFileError naming it."""
    header = ['OPIS Truckstop ID', 'Truckstop Name', 'Address', 'City', 'State', 'Rack ID']
    with pytest.raises(DataFileError, match='Retail Price'):
        build(data_files, [], fuel_header=header)


def test_missing_exits_column_raises(data_files):
    """An exits CSV without a required column raises DataFileError naming it."""
    with pytest.raises(DataFileError, match='exit_ref'):
        build(data_files, [], exits=[['state', 'interstate', 'lat', 'lon']])


def test_malformed_postal_code_row_raises(data_files):
    """A postal code row without coordinates raises DataFileError."""
    with pytest.raises(DataFileError, match='line 1'):
        build(data_files, [], postal_codes=[['US', '74332', 'Big Cabin']])
