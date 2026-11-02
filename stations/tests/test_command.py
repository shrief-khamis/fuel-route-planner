from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from stations.models import FuelStation

pytestmark = pytest.mark.django_db

ROWS = [
    ['7', 'WOODSHED OF BIG CABIN', 'I-44, EXIT 283 & US-69', 'Big Cabin', 'OK', '307', '3.00'],
    ['7', 'WOODSHED OF BIG CABIN', 'I-44, EXIT 283 & US-69', 'Big Cabin', 'OK', '307', '3.50'],
    ['9', 'KWIK TRIP', 'SR-183', 'Fort Worth', 'TX', '420', '3.28'],
    ['11', 'ESSO', 'HWY 401', 'Toronto', 'ON', '1', '4.10'],
]


def ingest(fuel, postal, exits):
    """Run the command on the given files and return its output."""
    out = StringIO()
    call_command('ingest_fuel_stations', fuel_csv=fuel, postal_codes=postal, exits=exits, stdout=out)
    return out.getvalue()


def test_saves_stations(data_files):
    """The command saves one row per station, with the averaged price and location."""
    ingest(*data_files(ROWS))

    assert FuelStation.objects.count() == 2
    station = FuelStation.objects.get(opis_id=7)
    assert str(station.retail_price) == '3.2500'
    assert station.price_count == 2
    assert station.location_precision == FuelStation.LocationPrecision.EXIT
    assert FuelStation.objects.get(opis_id=9).location_precision == FuelStation.LocationPrecision.CITY


def test_prints_a_summary(data_files):
    """The output counts dropped rows and how stations were located."""
    output = ingest(*data_files(ROWS))

    assert 'Read 4 rows' in output
    assert 'Dropped outside contiguous US:   1' in output
    assert 'At an interstate exit:           1' in output
    assert 'Saved 2 fuel stations.' in output


def test_rerun_replaces_stations(data_files):
    """Running the command again replaces the stations instead of adding to them."""
    ingest(*data_files(ROWS))
    ingest(*data_files(ROWS[2:]))

    assert list(FuelStation.objects.values_list('opis_id', flat=True)) == [9]


def test_missing_file_leaves_database_unchanged(data_files, tmp_path):
    """A missing file raises CommandError before anything is deleted."""
    fuel, postal, exits = data_files(ROWS)
    ingest(fuel, postal, exits)

    with pytest.raises(CommandError, match='File not found'):
        ingest(tmp_path / 'missing.csv', postal, exits)
    assert FuelStation.objects.count() == 2


def test_unreadable_file_leaves_database_unchanged(data_files):
    """A file without a required column raises CommandError before anything is deleted."""
    ingest(*data_files(ROWS))

    with pytest.raises(CommandError, match='missing columns'):
        ingest(*data_files(ROWS, exits=[['state']]))
    assert FuelStation.objects.count() == 2
