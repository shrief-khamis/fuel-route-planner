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
