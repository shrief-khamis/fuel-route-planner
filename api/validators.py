from rest_framework import serializers

from routing import LatLon

# Contiguous US extreme points with a small margin (inclusive).
US_MIN_LAT = 24.396308
US_MAX_LAT = 49.384358
US_MIN_LON = -124.848974
US_MAX_LON = -66.885444

MIN_ROUTE_DISTANCE_M = 1000


def within_contiguous_us(value: LatLon) -> None:
    """Check that a point is inside the contiguous US bounding box.

    The box is a rough check, with inclusive bounds. It also accepts parts of southern
    Canada, northern Mexico and nearby water.

    Args:
        value: The point to check.

    Raises:
        ValidationError: The point is outside the box.
    """
    if not (US_MIN_LAT <= value.lat <= US_MAX_LAT and US_MIN_LON <= value.lon <= US_MAX_LON):
        raise serializers.ValidationError('Point must be within the contiguous United States.')

# Upper limits for the fuel inputs, all in miles except mpg.
MAX_RANGE_MILES = 3000
MAX_MPG = 150
MAX_CORRIDOR_MILES = 15
MAX_RESERVE_FRACTION = 0.5


def positive(value: float) -> None:
    """Check that a number is greater than zero.

    Args:
        value: The number to check.

    Raises:
        ValidationError: The number is zero or negative.
    """
    if value <= 0:
        raise serializers.ValidationError('Ensure this value is greater than 0.')
