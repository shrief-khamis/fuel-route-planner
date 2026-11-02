"""The cheapest choice of stops and purchases along a route.

Fuel is measured in miles of range above the reserve, so the usable tank holds
max_range_miles - reserve_miles. A leg from one stop to the next is the stop's offset back
to the route, the miles along the route, and the next stop's offset.

For a fixed sequence of stops, there is a cheapest plan in which each stop either fills
the tank or buys just enough to reach the next stop (Khuller, Malekian and Mestre, "To
fill or not to fill: the gas station problem", 2011). So the fuel on arrival at a stop is
either 0 or what is left after filling up at the previous stop, and a dynamic program over
the stations finds the cheapest plan exactly. Each stop adds min_stop_saving to the cost
it minimises, so a stop is only made if it saves more than that.
"""

import math
from bisect import bisect_right
from dataclasses import dataclass

from .errors import NoFeasiblePlan
from .types import PlanOptions, RouteStation


@dataclass(frozen=True)
class Purchase:
    """What to buy at a stop, in miles of range.

    Attributes:
        stop: The station.
        arrival_miles: The usable range left on arrival, above the reserve.
        bought_miles: The range bought.
    """

    stop: RouteStation
    arrival_miles: float
    bought_miles: float


def cheapest_purchases(stations: list[RouteStation], route_miles: float, options: PlanOptions) -> list[Purchase]:
    """Choose the stops and purchases that reach the finish for the least money.

    Fuel already in the tank at the start is free. The last stop buys just enough to reach
    the finish with the reserve left.

    Args:
        stations: The candidate stations, sorted by along_miles.
        route_miles: The length of the route.
        options: The vehicle and trip settings.

    Returns:
        The purchases in travel order. Empty when the start fuel reaches the finish.

    Raises:
        NoFeasiblePlan: No choice of stations reaches the finish.
    """
    return _Planner(stations, route_miles, options).solve()


class _Planner:
    """The dynamic program behind cheapest_purchases.

    The cost of a stop u reached with g miles of fuel is the cheapest way from u to the
    finish, penalties included. It is the better of two choices:

    - fill up, for (capacity - g) * price(u), then continue from the best next stop v
      with capacity - leg(u, v) miles;
    - buy just enough to reach a next stop v (or the finish) with an empty tank, for
      (leg(u, v) - g) * price(u). This needs leg(u, v) > g, since a stop that buys nothing
      is never worth its detour.

    The best "fill up" continuation does not depend on g, and the "just enough" choices are
    kept sorted by leg with suffix minima, so the cost of any (u, g) takes a binary search.
    Stops are prepared from the last to the first, since each depends only on later ones.
    """

    def __init__(self, stations, route_miles, options):
        """Store the inputs, with fuel measured in usable miles above the reserve."""
        self.stations = stations
        self.finish = len(stations)
        self.route_miles = route_miles
        self.capacity = options.max_range_miles - options.reserve_miles
        self.start_fuel = options.start_fuel_miles - options.reserve_miles
        self.penalty = options.min_stop_saving
        self.price_per_mile = [s.station.price / options.mpg for s in stations]
        self._fill = [None] * self.finish
        self._exact = [None] * self.finish

    def solve(self):
        """Run the dynamic program and return the purchases of the cheapest plan.

        Find the cheapest plan in six steps:

        1. If the fuel at the start, above the reserve, already reaches the finish, buy
           nothing.
        2. Go through the stations from the last to the first. For each one, work out the
           best next stop after filling up there, and the cost of buying just enough to
           reach each later station within a full tank (or the finish), arriving empty.
           Every later station has already been worked out, so these costs are known.
        3. From those, the cheapest way to the finish from any station, with any amount of
           fuel on arrival, is a quick lookup: the better of filling up, or buying just
           enough to reach the cheapest next stop that the fuel on board doesn't already
           reach.
        4. Try each station the start fuel reaches as the first stop, and keep the
           cheapest.
        5. If no first stop leads to the finish, raise NoFeasiblePlan.
        6. Starting at the first stop, take the best choice at each stop again, recording
           what it buys, until the finish.

        Every cost here includes min_stop_saving for each stop. The purchases returned
        leave it out.

        Returns:
            The purchases in travel order. Empty when the start fuel reaches the finish.

        Raises:
            NoFeasiblePlan: No choice of stations reaches the finish.
        """
        if self.route_miles <= self.start_fuel:
            return []
        for u in reversed(range(self.finish)):
            self._prepare(u)

        best_cost, first, arrival = math.inf, None, 0.0
        for v, station in enumerate(self.stations):
            if station.along_miles > self.start_fuel:
                break
            leg = station.along_miles + station.offset_miles
            if leg <= self.start_fuel:
                cost = self._choose(v, self.start_fuel - leg)[0]
                if cost < best_cost:
                    best_cost, first, arrival = cost, v, self.start_fuel - leg
        if first is None or math.isinf(best_cost):
            raise NoFeasiblePlan('No choice of stations reaches the finish.')
        return self._purchases(first, arrival)

    def _leg(self, u, v):
        """Return the miles from stop u to stop v (or the finish), detours included."""
        a = self.stations[u]
        if v == self.finish:
            return a.offset_miles + max(0.0, self.route_miles - a.along_miles)
        b = self.stations[v]
        return a.offset_miles + (b.along_miles - a.along_miles) + b.offset_miles

    def _reachable(self, u):
        """Yield the stations after u that may be within a full tank, then the finish."""
        along = self.stations[u].along_miles
        for v in range(u + 1, self.finish):
            if self.stations[v].along_miles - along > self.capacity:
                break
            yield v
        yield self.finish

    def _prepare(self, u):
        """Precompute both choices at stop u, for every next stop within a full tank."""
        price = self.price_per_mile[u]
        fill_cost, fill_next = math.inf, None
        exact = []
        for v in self._reachable(u):
            leg = self._leg(u, v)
            if leg > self.capacity:
                continue
            if v == self.finish:
                exact.append((leg, leg * price, v))
                continue
            after_fill = self._choose(v, self.capacity - leg)[0]
            if after_fill < fill_cost:
                fill_cost, fill_next = after_fill, v
            exact.append((leg, leg * price + self._choose(v, 0.0)[0], v))

        exact.sort(key=lambda option: option[0])
        suffix = [(math.inf, None)] * (len(exact) + 1)
        for i in reversed(range(len(exact))):
            _, cost, v = exact[i]
            suffix[i] = (cost, v) if cost < suffix[i + 1][0] else suffix[i + 1]
        self._fill[u] = (fill_cost, fill_next)
        self._exact[u] = ([leg for leg, _, _ in exact], suffix)

    def _choose(self, u, g):
        """Return the best choice at stop u when it is reached with g miles of fuel.

        Args:
            u: The station index.
            g: The usable fuel on arrival.

        Returns:
            A (cost, next stop, fills up) tuple. The cost includes this stop's penalty and
            is infinite, with no next stop, when the finish is out of reach.
        """
        price = self.price_per_mile[u]
        legs, suffix = self._exact[u]
        exact_cost, exact_next = suffix[bisect_right(legs, g)]
        best = (exact_cost - g * price, exact_next, False)

        fill_cost, fill_next = self._fill[u]
        if g < self.capacity and fill_next is not None:
            cost = (self.capacity - g) * price + fill_cost
            if cost < best[0]:
                best = (cost, fill_next, True)
        return best[0] + self.penalty, best[1], best[2]

    def _purchases(self, first, arrival):
        """Follow the best choices from the first stop to the finish."""
        purchases = []
        u, g = first, arrival
        while u != self.finish:
            _, v, fills = self._choose(u, g)
            leg = self._leg(u, v)
            bought = self.capacity - g if fills else leg - g
            purchases.append(Purchase(stop=self.stations[u], arrival_miles=g, bought_miles=bought))
            u, g = v, max(0.0, g + bought - leg)
        return purchases
