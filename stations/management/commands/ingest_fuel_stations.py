from dataclasses import asdict
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from stations.ingest import DataFileError, build_stations
from stations.models import FuelStation


class Command(BaseCommand):
    """Load fuel stations from the data files, replacing all existing stations."""

    help = (
        'Load fuel stations from the fuel price CSV, located with the GeoNames postal codes '
        'and OSM interstate exits. Replaces all existing stations.'
    )

    def add_arguments(self, parser):
        """Add an option for each data file, defaulting to the copy in the project root."""
        parser.add_argument(
            '--fuel-csv',
            type=Path,
            default=settings.BASE_DIR / 'fuel-prices-for-be-assessment.csv',
            help='Fuel price CSV (default: %(default)s).',
        )
        parser.add_argument(
            '--postal-codes',
            type=Path,
            default=settings.BASE_DIR / 'geonames-us-postal-codes.txt',
            help='GeoNames US postal code file (default: %(default)s).',
        )
        parser.add_argument(
            '--exits',
            type=Path,
            default=settings.BASE_DIR / 'osm-interstate-exits.csv',
            help='OSM interstate exits CSV (default: %(default)s).',
        )

    def handle(self, *args, **options):
        """Build the stations, save them in one transaction, then print a summary.

        Raises:
            CommandError: A data file is missing or cannot be read. The database is left
                unchanged.
        """
        paths = [options['fuel_csv'], options['postal_codes'], options['exits']]
        for path in paths:
            if not path.is_file():
                raise CommandError(f'File not found: {path}')

        try:
            stations, report = build_stations(*paths)
        except DataFileError as e:
            raise CommandError(str(e)) from e

        with transaction.atomic():
            FuelStation.objects.all().delete()
            FuelStation.objects.bulk_create(
                [FuelStation(**asdict(station)) for station in stations],
                batch_size=1000,
            )

        self.stdout.write(
            f'Read {report.rows_read} rows from {options["fuel_csv"].name}.\n'
            f'  Skipped as invalid:              {report.rows_invalid}\n'
            f'  Dropped outside contiguous US:   {report.rows_outside_us}\n'
            f'  Dropped as duplicates:           {report.rows_duplicate}\n'
            f'Skipped {report.stations_without_city} stations whose city is not in GeoNames.\n'
            f'Located stations:\n'
            f'  At an interstate exit:           {report.stations_at_exit}\n'
            f'  At their city:                   {report.stations_at_city}'
            f' (incl. {report.exits_too_far} whose exit was too far from the city)'
        )
        self.stdout.write(self.style.SUCCESS(f'Saved {len(stations)} fuel stations.'))
