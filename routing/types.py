from dataclasses import dataclass
from enum import Enum
from typing import NamedTuple


class LatLon(NamedTuple):
    """A geographic point, always latitude first.

    Attributes:
        lat: Latitude in decimal degrees.
        lon: Longitude in decimal degrees.
    """

    lat: float
    lon: float


class Profile(str, Enum):
    """The vehicle type to route for.

    Each provider adapter maps these values to its own profile names.

    Attributes:
        TRUCK: A heavy goods vehicle.
        CAR: A passenger car.
    """

    TRUCK = 'truck'
    CAR = 'car'


@dataclass(frozen=True)
class Route:
    """A driving route returned by a routing provider.

    Attributes:
        points: The route line in travel order, from the first waypoint to the last.
        distance_m: Total driving distance in metres.
        duration_s: Estimated driving time in seconds.
    """

    points: list[LatLon]
    distance_m: float
    duration_s: float
