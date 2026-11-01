import math

from rest_framework import serializers

from routing import LatLon, Profile, haversine_m

from .validators import MIN_ROUTE_DISTANCE_M, within_contiguous_us


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

    def validate_profile(self, value):
        """Convert the profile choice to a Profile.

        Args:
            value: A valid profile choice, "truck" or "car".

        Returns:
            The matching Profile.
        """
        return Profile(value)

    def validate(self, attrs):
        """Check that start and finish are far enough apart.

        DRF runs this only after every field is valid on its own.

        Args:
            attrs: The validated fields.

        Returns:
            The same fields, unchanged.

        Raises:
            ValidationError: start and finish are less than MIN_ROUTE_DISTANCE_M apart.
        """
        if haversine_m(attrs['start'], attrs['finish']) < MIN_ROUTE_DISTANCE_M:
            raise serializers.ValidationError(
                f'start and finish must be at least {MIN_ROUTE_DISTANCE_M / 1000:g} km apart.'
            )
        return attrs
