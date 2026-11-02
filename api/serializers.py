import math

from rest_framework import serializers
from rest_framework.settings import api_settings

from fuel_planner import PlanOptions
from routing import LatLon, Profile, haversine_m

from .validators import (
    MAX_CORRIDOR_MILES,
    MAX_MPG,
    MAX_RANGE_MILES,
    MAX_RESERVE_FRACTION,
    MIN_ROUTE_DISTANCE_M,
    positive,
    within_contiguous_us,
)

DEFAULT_MAX_RANGE_MILES = 500
DEFAULT_MPG = 10
DEFAULT_CORRIDOR_MILES = 3
DEFAULT_MIN_STOP_SAVING = 5


class LatLonField(serializers.Field):
    """A serializer field for a "lat,lon" string, such as "40.7128,-74.0060"."""

    default_error_messages = {
        'invalid': 'Enter coordinates as "lat,lon", e.g. "40.7128,-74.0060".',
        'lat_range': 'Latitude must be between -90 and 90.',
        'lon_range': 'Longitude must be between -180 and 180.',
    }

    def to_internal_value(self, data):
        """Parse a "lat,lon" string into a LatLon.

        Spaces around each number are allowed. NaN and infinity are rejected.

        Args:
            data: The raw value from the request.

        Returns:
            The parsed point.

        Raises:
            ValidationError: The value is not two comma-separated finite numbers, or the
                latitude or longitude is out of range.
        """
        if not isinstance(data, str):
            self.fail('invalid')
        parts = data.split(',')
        if len(parts) != 2:
            self.fail('invalid')
        try:
            lat, lon = (float(part.strip()) for part in parts)
        except ValueError:
            self.fail('invalid')
        if not (math.isfinite(lat) and math.isfinite(lon)):
            self.fail('invalid')
        if not -90 <= lat <= 90:
            self.fail('lat_range')
        if not -180 <= lon <= 180:
            self.fail('lon_range')
        return LatLon(lat, lon)

    def to_representation(self, value):
        """Convert a LatLon to a {"lat": ..., "lon": ...} dict.

        Args:
            value: The point to convert.

        Returns:
            The point as a dict.
        """
        return {'lat': value.lat, 'lon': value.lon}


class FindRouteRequestSerializer(serializers.Serializer):
    """Validates the query parameters of GET /api/find-route/."""

    start = LatLonField(validators=[within_contiguous_us])
    finish = LatLonField(validators=[within_contiguous_us])
    profile = serializers.ChoiceField(choices=[p.value for p in Profile], default=Profile.TRUCK.value)
    max_range_miles = serializers.FloatField(
        default=DEFAULT_MAX_RANGE_MILES, max_value=MAX_RANGE_MILES, validators=[positive],
    )
    start_fuel_miles = serializers.FloatField(required=False, validators=[positive])
    reserve_miles = serializers.FloatField(default=0, min_value=0)
    mpg = serializers.FloatField(default=DEFAULT_MPG, max_value=MAX_MPG, validators=[positive])
    corridor_miles = serializers.FloatField(
        default=DEFAULT_CORRIDOR_MILES, max_value=MAX_CORRIDOR_MILES, validators=[positive],
    )
    min_stop_saving = serializers.FloatField(default=DEFAULT_MIN_STOP_SAVING, min_value=0)

    def validate_profile(self, value):
        """Convert the profile choice to a Profile.

        Args:
            value: A valid profile choice, "truck" or "car".

        Returns:
            The matching Profile.
        """
        return Profile(value)

    def validate(self, attrs):
        """Check the rules that involve more than one field.

        start and finish must be far enough apart, the reserve at most half the range, and
        the start fuel no more than the range and more than the reserve. The start fuel
        defaults to a full tank. DRF runs this only after every field is valid on its own.

        Args:
            attrs: The validated fields.

        Returns:
            The fields, with start_fuel_miles set.

        Raises:
            ValidationError: One or more rules are broken. The distance error is listed
                under non_field_errors, the others under their field.
        """
        errors = {}
        if haversine_m(attrs['start'], attrs['finish']) < MIN_ROUTE_DISTANCE_M:
            errors[api_settings.NON_FIELD_ERRORS_KEY] = [
                f'start and finish must be at least {MIN_ROUTE_DISTANCE_M / 1000:g} km apart.'
            ]

        max_range = attrs['max_range_miles']
        reserve = attrs['reserve_miles']
        start_fuel = attrs.setdefault('start_fuel_miles', max_range)
        if reserve > max_range * MAX_RESERVE_FRACTION:
            errors['reserve_miles'] = [
                f'Ensure this value is at most half of max_range_miles ({max_range * MAX_RESERVE_FRACTION:g}).'
            ]
        if start_fuel > max_range:
            errors['start_fuel_miles'] = [
                f'Ensure this value is less than or equal to max_range_miles ({max_range:g}).'
            ]
        elif start_fuel <= reserve:
            errors['start_fuel_miles'] = [f'Ensure this value is greater than reserve_miles ({reserve:g}).']

        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    def plan_options(self) -> PlanOptions:
        """Return the fuel settings from the validated data.

        Returns:
            The settings for the fuel planner.
        """
        data = self.validated_data
        return PlanOptions(
            max_range_miles=data['max_range_miles'],
            start_fuel_miles=data['start_fuel_miles'],
            reserve_miles=data['reserve_miles'],
            mpg=data['mpg'],
            corridor_miles=data['corridor_miles'],
            min_stop_saving=data['min_stop_saving'],
        )
