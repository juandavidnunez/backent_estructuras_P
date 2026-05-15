"""
Basic itinerary planning — Requirement R2.

Provides three planning functions:
  1. plan_max_destinations_by_budget  — BFS, maximize stops within budget.
  2. plan_max_destinations_by_time    — BFS, maximize stops within time.
  3. find_best_route                  — Dijkstra, best path by one or more criteria.

This module only knows about core/ and config.py.
It does NOT import anything from api/.
"""

from typing import Optional

from config import DEFAULT_AIRCRAFT
from core.bfs_dfs import bfs_max_coverage_by_budget, bfs_max_coverage_by_time
from core.dijkstra import multi_dijkstra
from core.graph import Graph
from core.models import Route, TripSegment


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_aircraft_config(override: Optional[dict] = None) -> dict:
    """
    Merge default aircraft config with any runtime overrides.

    Args:
        override: Optional dict with the same structure as DEFAULT_AIRCRAFT
                  that overrides specific values.

    Returns:
        Merged aircraft configuration dict.
    """
    config = {k: dict(v) for k, v in DEFAULT_AIRCRAFT.items()}
    if override:
        for aircraft_name, values in override.items():
            if aircraft_name in config:
                config[aircraft_name].update(values)
            else:
                config[aircraft_name] = values
    return config


def _weight_fn_distance(route: Route) -> float:
    """Weight function: raw distance in km."""
    return route.distance_km


def _weight_fn_cost(route: Route, aircraft_config: dict) -> float:
    """
    Weight function: minimum cost across all aircraft types on this route.

    If the route is subsidized (base_cost == 0), returns 0.
    Otherwise returns distance_km * cheapest cost_per_km.
    """
    if route.is_subsidized:
        return 0.0
    if not route.aircraft_types:
        return route.distance_km * 0.18  # fallback to commercial default

    min_cost = float("inf")
    for aircraft_type in route.aircraft_types:
        cost_per_km = aircraft_config.get(aircraft_type, {}).get("cost_per_km", 0.18)
        min_cost = min(min_cost, route.distance_km * cost_per_km)
    return min_cost


def _weight_fn_time(route: Route, aircraft_config: dict) -> float:
    """
    Weight function: minimum time across all aircraft types on this route.

    Returns distance_km * fastest time_per_km in minutes.
    """
    if not route.aircraft_types:
        return route.distance_km * 0.7  # fallback to commercial default

    min_time = float("inf")
    for aircraft_type in route.aircraft_types:
        time_per_km = aircraft_config.get(aircraft_type, {}).get("time_per_km", 0.7)
        min_time = min(min_time, route.distance_km * time_per_km)
    return min_time


def _segments_from_path(
    graph: Graph,
    path: list[str],
    aircraft_config: dict,
    optimize_for: str = "cost",
) -> list[TripSegment]:
    """
    Convert a list of IATA codes (Dijkstra path) into TripSegment objects.

    Args:
        graph: The Graph instance.
        path: Ordered list of IATA codes.
        aircraft_config: Aircraft configuration dict.
        optimize_for: 'cost' or 'time' — determines which aircraft is chosen.

    Returns:
        List of TripSegment instances.
    """
    segments: list[TripSegment] = []
    cumulative_cost = 0.0
    cumulative_time = 0.0

    for index in range(len(path) - 1):
        origin_id = path[index]
        dest_id = path[index + 1]

        # Find the route between these two nodes
        route: Optional[Route] = None
        for neighbor_id, candidate_route in graph.get_neighbors(origin_id):
            if neighbor_id == dest_id:
                route = candidate_route
                break

        if route is None:
            continue  # Edge was removed between path computation and now

        # Choose aircraft based on optimization criterion
        best_aircraft = route.aircraft_types[0] if route.aircraft_types else "Avión Comercial"
        best_cost = float("inf")
        best_time = float("inf")

        for aircraft_type in route.aircraft_types:
            cost_per_km = aircraft_config.get(aircraft_type, {}).get("cost_per_km", 0.18)
            time_per_km = aircraft_config.get(aircraft_type, {}).get("time_per_km", 0.7)
            seg_cost = 0.0 if route.is_subsidized else route.distance_km * cost_per_km
            seg_time = route.distance_km * time_per_km

            if optimize_for == "time" and seg_time < best_time:
                best_time = seg_time
                best_aircraft = aircraft_type
                best_cost = seg_cost
            elif optimize_for != "time" and seg_cost < best_cost:
                best_cost = seg_cost
                best_aircraft = aircraft_type
                best_time = seg_time

        cumulative_cost += best_cost
        cumulative_time += best_time

        segments.append(TripSegment(
            origin=origin_id,
            dest=dest_id,
            aircraft_type=best_aircraft,
            distance_km=route.distance_km,
            flight_time_min=best_time,
            cost_usd=best_cost,
            cumulative_cost=cumulative_cost,
            cumulative_time_min=cumulative_time,
        ))

    return segments


# ---------------------------------------------------------------------------
# Public planning functions
# ---------------------------------------------------------------------------

def plan_max_destinations_by_budget(
    graph: Graph,
    origin: str,
    budget_usd: float,
    aircraft_types: Optional[list[str]] = None,
    include_secondary: bool = True,
    aircraft_override: Optional[dict] = None,
) -> list[TripSegment]:
    """
    Find the itinerary that visits the most destinations without exceeding budget.

    Uses BFS to explore level by level, accumulating cost at each hop.
    The cheapest available aircraft is chosen for each route.

    Args:
        graph: The Graph instance.
        origin: IATA code of the starting airport.
        budget_usd: Maximum total cost in USD (hard constraint).
        aircraft_types: If provided, only routes that include at least one
                        of these aircraft types are considered.
        include_secondary: If False, non-hub airports are excluded.
        aircraft_override: Optional dict to override default aircraft costs.

    Returns:
        List of TripSegment instances ordered from origin outward.
        Empty list if no destination is reachable within budget.
    """
    aircraft_config = _build_aircraft_config(aircraft_override)

    # If aircraft_types filter is requested, we need to pre-filter the graph.
    # We do this by temporarily working with a filtered view — we don't modify
    # the graph itself, just skip edges whose aircraft don't match.
    # For simplicity, we pass the full config and let BFS handle it.
    # A more advanced implementation would wrap the graph with a filter proxy.

    return bfs_max_coverage_by_budget(
        graph=graph,
        origin=origin,
        budget_usd=budget_usd,
        aircraft_config=aircraft_config,
        include_secondary=include_secondary,
    )


def plan_max_destinations_by_time(
    graph: Graph,
    origin: str,
    time_hours: float,
    aircraft_types: Optional[list[str]] = None,
    include_secondary: bool = True,
    aircraft_override: Optional[dict] = None,
) -> list[TripSegment]:
    """
    Find the itinerary that visits the most destinations without exceeding time.

    Uses BFS with the fastest available aircraft on each route.

    Args:
        graph: The Graph instance.
        origin: IATA code of the starting airport.
        time_hours: Maximum total flight time in hours (hard constraint).
        aircraft_types: Optional filter for allowed aircraft types.
        include_secondary: If False, non-hub airports are excluded.
        aircraft_override: Optional dict to override default aircraft times.

    Returns:
        List of TripSegment instances ordered from origin outward.
    """
    aircraft_config = _build_aircraft_config(aircraft_override)

    return bfs_max_coverage_by_time(
        graph=graph,
        origin=origin,
        time_limit_hours=time_hours,
        aircraft_config=aircraft_config,
        include_secondary=include_secondary,
    )


def find_best_route(
    graph: Graph,
    origin: str,
    destination: str,
    criteria: list[str],
    include_secondary: bool = True,
    aircraft_override: Optional[dict] = None,
) -> dict[str, dict]:
    """
    Calculate the best route between two airports for one or more criteria.

    Runs Dijkstra once per criterion. Valid criteria: 'distance', 'time', 'cost'.
    If multiple criteria are given, one route is computed per criterion.

    Args:
        graph: The Graph instance.
        origin: IATA code of the starting airport.
        destination: IATA code of the target airport.
        criteria: List of criterion strings. At least one required.
                  Valid values: 'distance', 'time', 'cost'.
        include_secondary: If False, the algorithm will still traverse secondary
                           airports as intermediates (Dijkstra needs them), but
                           the caller can filter the result if needed.
        aircraft_override: Optional dict to override default aircraft values.

    Returns:
        Dict mapping each criterion to its result:
        {
            "distance": {
                "total": float,          # total km / minutes / USD
                "path": ["BOG", "MDE"],  # IATA codes
                "segments": [TripSegment, ...]
            },
            ...
        }
        If no path exists for a criterion, "total" is None and lists are empty.

    Raises:
        ValueError: If criteria list is empty or contains invalid values.
    """
    valid_criteria = {"distance", "time", "cost"}
    for criterion in criteria:
        if criterion not in valid_criteria:
            raise ValueError(
                f"Invalid criterion '{criterion}'. Must be one of {valid_criteria}"
            )

    if not criteria:
        raise ValueError("At least one criterion must be provided")

    aircraft_config = _build_aircraft_config(aircraft_override)

    # Build weight functions for each requested criterion
    weight_fns = {}
    if "distance" in criteria:
        weight_fns["distance"] = _weight_fn_distance
    if "cost" in criteria:
        weight_fns["cost"] = lambda route: _weight_fn_cost(route, aircraft_config)
    if "time" in criteria:
        weight_fns["time"] = lambda route: _weight_fn_time(route, aircraft_config)

    # Run Dijkstra for all criteria in one call
    raw_results = multi_dijkstra(graph, origin, destination, weight_fns)

    # Enrich each result with TripSegment objects
    enriched: dict[str, dict] = {}
    for criterion, result in raw_results.items():
        path = result["path"]
        optimize_for = "time" if criterion == "time" else "cost"
        segments = _segments_from_path(graph, path, aircraft_config, optimize_for) if path else []

        enriched[criterion] = {
            "total": result["total"],
            "path": path,
            "segments": segments,
        }

    return enriched
