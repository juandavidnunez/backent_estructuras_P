"""
Weighted directed graph using an adjacency list (from scratch).

Each edge stores distance, per-aircraft cost/time, subsidy flag, and min stay.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from app.models import Airport, Route, TripSegment


@dataclass
class Edge:
    """Directed edge in the air-route network."""
    origin: str
    dest: str
    distance_km: float
    aircraft_types: list[str]
    base_cost: float
    min_stay_min: int
    costs_by_aircraft: dict[str, float]
    times_by_aircraft: dict[str, float]

    @property
    def is_subsidized(self) -> bool:
        return self.base_cost == 0


@dataclass
class AircraftConfig:
    cost_per_km: float
    time_per_km: float


class AirRouteGraph:
    """
    Adjacency-list representation of the Latin-American air network.

    Justification: a directed graph with O(1) neighbour lookup per node is the
    natural structure for one-way flight routes and supports Dijkstra / DFS
    without external graph libraries.
    """

    def __init__(self) -> None:
        self.airports: dict[str, Airport] = {}
        self.adjacency: dict[str, list[Edge]] = {}
        self.blocked: set[tuple[str, str]] = set()
        self.aircraft_config: dict[str, AircraftConfig] = {}
        self.budget_job_threshold_pct: float = 35.0
        self.lodging_interval_hours: float = 20.0
        self.food_interval_hours: float = 8.0

    # ── mutation ────────────────────────────────────────────────────────────

    def add_airport(self, airport: Airport) -> None:
        self.airports[airport.id] = airport
        self.adjacency.setdefault(airport.id, [])

    def add_edge(self, edge: Edge) -> None:
        if edge.origin not in self.airports or edge.dest not in self.airports:
            return
        self.adjacency.setdefault(edge.origin, []).append(edge)

    def block_edge(self, origin: str, dest: str) -> None:
        self.blocked.add((origin, dest))

    def unblock_edge(self, origin: str, dest: str) -> None:
        self.blocked.discard((origin, dest))

    def is_blocked(self, origin: str, dest: str) -> bool:
        return (origin, dest) in self.blocked

    def clear(self) -> None:
        self.airports.clear()
        self.adjacency.clear()
        self.blocked.clear()

    # ── queries ─────────────────────────────────────────────────────────────

    def hub_count(self) -> int:
        return sum(1 for a in self.airports.values() if a.is_hub)

    def edge_count(self) -> int:
        return sum(len(edges) for edges in self.adjacency.values())

    def neighbours(self, node: str) -> list[Edge]:
        return [
            e for e in self.adjacency.get(node, [])
            if not self.is_blocked(e.origin, e.dest)
        ]

    def get_edge(self, origin: str, dest: str) -> Edge | None:
        for e in self.adjacency.get(origin, []):
            if e.dest == dest and not self.is_blocked(origin, dest):
                return e
        return None

    def edge_exists(self, origin: str, dest: str) -> bool:
        return any(e.dest == dest for e in self.adjacency.get(origin, []))

    def allowed_aircraft(
        self,
        edge: Edge,
        aircraft_filter: list[str] | None = None,
    ) -> list[str]:
        types = [t for t in edge.aircraft_types if t in self.aircraft_config]
        if aircraft_filter:
            types = [t for t in types if t in aircraft_filter]
        return types

    def best_aircraft_for_cost(self, edge: Edge, aircraft_filter: list[str] | None) -> tuple[str, float, float] | None:
        """Return (type, cost_usd, time_min) for the cheapest allowed aircraft."""
        best: tuple[str, float, float] | None = None
        for ac in self.allowed_aircraft(edge, aircraft_filter):
            cost = edge.costs_by_aircraft.get(ac, 0.0)
            time_min = edge.times_by_aircraft.get(ac, 0.0)
            if best is None or cost < best[1] or (cost == best[1] and time_min < best[2]):
                best = (ac, cost, time_min)
        return best

    def best_aircraft_for_time(self, edge: Edge, aircraft_filter: list[str] | None) -> tuple[str, float, float] | None:
        """Return (type, cost_usd, time_min) for the fastest allowed aircraft."""
        best: tuple[str, float, float] | None = None
        for ac in self.allowed_aircraft(edge, aircraft_filter):
            cost = edge.costs_by_aircraft.get(ac, 0.0)
            time_min = edge.times_by_aircraft.get(ac, 0.0)
            if best is None or time_min < best[2] or (time_min == best[2] and cost < best[1]):
                best = (ac, cost, time_min)
        return best

    def node_allowed(self, node_id: str, include_secondary: bool) -> bool:
        if node_id not in self.airports:
            return False
        if include_secondary:
            return True
        return self.airports[node_id].is_hub

    def to_route_models(self) -> list[Route]:
        routes: list[Route] = []
        for edges in self.adjacency.values():
            for e in edges:
                routes.append(Route(
                    origin=e.origin,
                    dest=e.dest,
                    distance_km=e.distance_km,
                    aircraft_types=e.aircraft_types,
                    base_cost=e.base_cost,
                    min_stay_min=e.min_stay_min,
                    is_subsidized=e.is_subsidized,
                    costs_by_aircraft=dict(e.costs_by_aircraft),
                    times_by_aircraft=dict(e.times_by_aircraft),
                ))
        return routes

    def build_segment(
        self,
        edge: Edge,
        aircraft_type: str,
        cumulative_cost: float,
        cumulative_time: float,
    ) -> TripSegment:
        cost = edge.costs_by_aircraft.get(aircraft_type, 0.0)
        time_min = edge.times_by_aircraft.get(aircraft_type, 0.0)
        cumulative_cost += cost
        cumulative_time += time_min
        return TripSegment(
            origin=edge.origin,
            dest=edge.dest,
            aircraft_type=aircraft_type,
            distance_km=edge.distance_km,
            flight_time_min=time_min,
            cost_usd=cost,
            cumulative_cost=cumulative_cost,
            cumulative_time_min=cumulative_time,
        )
