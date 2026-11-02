from dataclasses import dataclass

from routing import LatLon

METRES_PER_MILE = 1609.344


@dataclass(frozen=True)
class PlanOptions:
    """The vehicle and trip settings a fuel plan is made for. All distances are in miles.

    The tank is measured in miles of range. The fuel level may never drop below
    reserve_miles, including at the stations and the finish.

    Attributes:
        max_range_miles: How far a full tank goes.
        start_fuel_miles: How far the fuel in the tank at the start goes.
        reserve_miles: The fuel to keep in the tank at all times.
        mpg: Miles per gallon, to convert range to gallons.
        corridor_miles: How far off the route a station may be.
        min_stop_saving: The least a stop must save, in dollars, to be worth making.
    """

    max_range_miles: float
    start_fuel_miles: float
    reserve_miles: float
    mpg: float
    corridor_miles: float
    min_stop_saving: float

    def __post_init__(self):
        """Check that the settings are consistent.

        Raises:
            ValueError: A setting is out of range, or the start fuel is above the tank
                size or not above the reserve.
        """
        if not (self.max_range_miles > 0 and self.mpg > 0 and self.corridor_miles > 0):
            raise ValueError('max_range_miles, mpg and corridor_miles must be positive.')
        if not 0 <= self.reserve_miles < self.start_fuel_miles <= self.max_range_miles:
            raise ValueError('Expected 0 <= reserve_miles < start_fuel_miles <= max_range_miles.')
        if self.min_stop_saving < 0:
            raise ValueError('min_stop_saving must not be negative.')


@dataclass(frozen=True)
class Station:
    """A fuel station that the planner can choose.

    Attributes:
        id: The caller's ID for the station, returned unchanged in the plan.
        location: Where the station is.
        price: The fuel price, in dollars per gallon.
    """

    id: int
    location: LatLon
    price: float


@dataclass(frozen=True)
class RouteStation:
    """A station within the corridor, placed on the route.

    Attributes:
        station: The station.
        along_miles: Distance from the start to the nearest point on the route.
        offset_miles: Straight-line distance from that point to the station. A stop
            drives it twice, there and back.
    """

    station: Station
    along_miles: float
    offset_miles: float


@dataclass(frozen=True)
class FuelStop:
    """A planned stop and what to buy there.

    Attributes:
        station: The station.
        along_miles: Distance from the start to where the route passes the station.
        offset_miles: Straight-line distance from the route to the station.
        fuel_on_arrival_miles: The range left in the tank on arrival, reserve included.
        fuel_added_miles: The range bought.
        gallons: The fuel bought.
        cost: What the fuel costs, rounded to cents as it would be paid.
    """

    station: Station
    along_miles: float
    offset_miles: float
    fuel_on_arrival_miles: float
    fuel_added_miles: float
    gallons: float
    cost: float


@dataclass(frozen=True)
class FuelPlan:
    """The cheapest way to buy fuel for a trip.

    Attributes:
        stops: The stops, in travel order. Empty when the start fuel is enough.
        total_gallons: The fuel bought over the trip.
        total_detour_miles: The miles driven off the route to reach the stops.
        total_cost: The sum of the stop costs, in dollars.
    """

    stops: list[FuelStop]
    total_gallons: float
    total_detour_miles: float
    total_cost: float
