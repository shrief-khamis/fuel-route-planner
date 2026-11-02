from django.db import models


class FuelStation(models.Model):
    """A truck stop with its fuel price and location.

    Loaded by the ingest_fuel_stations command, which replaces every row on each run.

    Attributes:
        opis_id: The station's ID in the source data (OPIS Truckstop ID).
        name: The station name, as first spelled in the source data.
        address: The address as given, usually a highway and exit, e.g. "I-44, EXIT 283".
        city: The city as given.
        state: The two-letter state code.
        rack_id: The ID of the wholesale terminal (rack) the price is tied to.
        retail_price: The average of the station's listed prices, in dollars per gallon.
        price_min: The lowest listed price.
        price_max: The highest listed price.
        price_count: How many rows were averaged, after duplicate rows were dropped.
        lat: Latitude in decimal degrees.
        lon: Longitude in decimal degrees.
        location_precision: Whether lat and lon are the interstate exit in the address or
            the city.
    """

    class LocationPrecision(models.TextChoices):
        """Where a station's coordinates came from."""

        EXIT = 'exit', 'Interstate exit (OpenStreetMap)'
        CITY = 'city', 'City (average of its GeoNames ZIP codes)'

    opis_id = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=2)
    rack_id = models.PositiveIntegerField()

    retail_price = models.DecimalField(max_digits=7, decimal_places=4)
    price_min = models.DecimalField(max_digits=7, decimal_places=4)
    price_max = models.DecimalField(max_digits=7, decimal_places=4)
    price_count = models.PositiveSmallIntegerField()

    lat = models.FloatField()
    lon = models.FloatField()
    location_precision = models.CharField(max_length=4, choices=LocationPrecision.choices)

    class Meta:
        indexes = [models.Index(fields=['lat', 'lon'])]

    def __str__(self):
        """Return the name and city, e.g. "PILOT #1243 (Gila Bend, AZ)"."""
        return f'{self.name} ({self.city}, {self.state})'
