"""
Graph search algorithms required by SkyRoute (Dijkstra + coverage DFS).

All algorithms operate on the custom adjacency-list graph — no external
graph libraries are used, as required by the course project.
"""
from __future__ import annotations

import heapq
from typing import Callable

from app.graph import AirRouteGraph, Edge
from app.models import TripSegment


WeightFn = Callable[[Edge, str, float, float], float | None]


def _pick_aircraft(
    graph: AirRouteGraph,
    edge: Edge,
    aircraft_filter: list[str] | None,
    optimize: str,
) -> tuple[str, float, float] | None:
    if optimize == "time":
        return graph.best_aircraft_for_time(edge, aircraft_filter)
    return graph.best_aircraft_for_cost(edge, aircraft_filter)


# ── Dijkstra ────────────────────────────────────────────────────────────────

def dijkstra(
    graph: AirRouteGraph,
    origin: str,
    destination: str,
    *,
    weight_key: str = "cost_usd",
    aircraft_filter: list[str] | None = None,
    include_secondary: bool = True,
) -> tuple[list[str], list[TripSegment], float]:
    """
    Single-source shortest path (Dijkstra).

    Applicability: finding the minimum-cost / minimum-time / minimum-distance
    route between two airports on a graph with non-negative edge weights.
    """
    if origin not in graph.airports or destination not in graph.airports:
        return [], [], float("inf")

    dist: dict[str, float] = {origin: 0.0}
    prev: dict[str, tuple[str, Edge, str] | None] = {origin: None}
    pq: list[tuple[float, str]] = [(0.0, origin)]

    while pq:
        d, u = heapq.heappop(pq)
        if d > dist.get(u, float("inf")):
            continue
        if u == destination:
            break

        for edge in graph.neighbours(u):
            if not graph.node_allowed(edge.dest, include_secondary):
                continue
            pick = _pick_aircraft(graph, edge, aircraft_filter, "cost" if weight_key == "cost_usd" else "time")
            if not pick:
                continue
            ac_type, cost, time_min = pick

            if weight_key == "cost_usd":
                w = cost
            elif weight_key == "flight_time_min":
                w = time_min
            else:
                w = edge.distance_km

            nd = d + w
            if nd < dist.get(edge.dest, float("inf")):
                dist[edge.dest] = nd
                prev[edge.dest] = (u, edge, ac_type)
                heapq.heappush(pq, (nd, edge.dest))

    if destination not in prev:
        return [], [], float("inf")

    # Reconstruct path
    path: list[str] = []
    segments: list[TripSegment] = []
    node = destination
    chain: list[tuple[str, Edge, str]] = []
    while node != origin:
        entry = prev.get(node)
        if entry is None:
            return [], [], float("inf")
        parent, edge, ac = entry
        chain.append((parent, edge, ac))
        node = parent
    chain.reverse()

    cum_cost = 0.0
    cum_time = 0.0
    path = [origin]
    for parent, edge, ac in chain:
        seg = graph.build_segment(edge, ac, cum_cost, cum_time)
        cum_cost = seg.cumulative_cost
        cum_time = seg.cumulative_time_min
        segments.append(seg)
        path.append(edge.dest)

    return path, segments, dist[destination]


# ── Maximum destination coverage (DFS + pruning) ────────────────────────────

def max_coverage_itinerary(
    graph: AirRouteGraph,
    origin: str,
    budget_usd: float,
    time_hours: float,
    *,
    aircraft_filter: list[str] | None,
    include_secondary: bool,
    optimize: str = "cost",
) -> list[TripSegment]:
    """
    Find a route that visits the maximum number of distinct airports without
    exceeding budget and time limits (no airport visited twice).

    Applicability: exponential search with pruning is feasible because the
    course network has ~32 nodes; DFS explores extensions until limits bind.
    """
    time_limit_min = time_hours * 60.0
    best_segments: list[TripSegment] = []
    best_dest_count = 0

    def dest_count(segs: list[TripSegment]) -> int:
        return len({origin} | {s.dest for s in segs})

    def dfs(
        current: str,
        visited: set[str],
        segments: list[TripSegment],
        spent: float,
        elapsed_min: float,
    ) -> None:
        nonlocal best_segments, best_dest_count
        count = dest_count(segments)
        if count > best_dest_count or (count == best_dest_count and len(segments) > len(best_segments)):
            best_dest_count = count
            best_segments = list(segments)

        for edge in graph.neighbours(current):
            dest = edge.dest
            if dest in visited:
                continue
            if not graph.node_allowed(dest, include_secondary):
                continue

            pick_fn = graph.best_aircraft_for_time if optimize == "time" else graph.best_aircraft_for_cost
            pick = pick_fn(edge, aircraft_filter)
            if not pick:
                continue
            ac_type, cost, time_min = pick

            if spent + cost > budget_usd:
                continue
            if elapsed_min + time_min > time_limit_min:
                continue

            seg = graph.build_segment(edge, ac_type, spent, elapsed_min)
            dfs(dest, visited | {dest}, segments + [seg], seg.cumulative_cost, seg.cumulative_time_min)

    dfs(origin, {origin}, [], 0.0, 0.0)

    # Ensure at least one aircraft type per available category when possible
    if best_segments:
        return best_segments

    # Fallback: try a single-hop greedy extension
    for edge in graph.neighbours(origin):
        if not graph.node_allowed(edge.dest, include_secondary):
            continue
        pick = _pick_aircraft(graph, edge, aircraft_filter, optimize)
        if not pick:
            continue
        ac_type, cost, time_min = pick
        if cost <= budget_usd and time_min <= time_limit_min:
            return [graph.build_segment(edge, ac_type, 0.0, 0.0)]

    return []


def suggest_next_destination(
    graph: AirRouteGraph,
    current: str,
    budget: float,
    *,
    aircraft_filter: list[str] | None = None,
    include_secondary: bool = True,
    visited: set[str] | None = None,
) -> tuple[str | None, list[str], float, float]:
    """Greedy suggestion: unvisited neighbour with lowest cost."""
    visited = visited or set()
    best: tuple[str, float, float, list[str]] | None = None

    for edge in graph.neighbours(current):
        dest = edge.dest
        if dest in visited:
            continue
        if not graph.node_allowed(dest, include_secondary):
            continue
        pick = graph.best_aircraft_for_cost(edge, aircraft_filter)
        if not pick:
            continue
        ac_type, cost, time_min = pick
        if cost > budget:
            continue
        path, _, _ = dijkstra(graph, current, dest, aircraft_filter=aircraft_filter, include_secondary=include_secondary)
        if not path:
            continue
        if best is None or cost < best[1]:
            best = (dest, cost, time_min, path)

    if best is None:
        return None, [], 0.0, 0.0
    return best[0], best[3], best[1], best[2]
