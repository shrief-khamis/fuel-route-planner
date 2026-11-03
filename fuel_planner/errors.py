class NoFeasiblePlan(Exception):
    """No choice of stations gets the vehicle to the finish without dipping into the reserve.

    Attributes:
        corridor_stations: How many stations were within the corridor, or None when the
            error was not raised by plan_fuel_stops.
    """

    corridor_stations: int | None = None
