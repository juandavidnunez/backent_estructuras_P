"""
Route interruption handling — Requirement R4.

Simulates real-world disruptions: airspace closures, weather, airline cancellations.
Provides functions to block/unblock edges and recalculate routes after a disruption.

Key design decisions:
  - Edges are BLOCKED (not deleted) so they can be restored later.
  - The ItineraryState tracks transit progress so we can detect mid-flight disruptions.
  - Recalculation uses Dijkstra on the modified graph (blocked edges excluded).
"""

from typing import Optional

from config import DEFAULT_AIRCRAFT
from core.dijkstra import dijkstra
from core.graph import Graph
from core.models import ItineraryState, Route, TripSegment


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_aircraft_config(override: Optional[dict] = None) -> dict:
    """Merge default aircraft config with optional overrides."""
    config = {k: dict(v) for k, v in DEFAULT_AIRCRAFT.items()}
    if override:
        for name, values in override.items():
            if name in config:
                config[name].update(values)
            else:
                config[name] = values
    return config


def _weight_fn_cost(route: Route, aircraft_config: dict) -> float:
    """Minimum cost weight function for Dijkstra recalculation."""
    if route.is_subsidized:
        return 0.0
    if not route.aircraft_types:
        return route.distance_km * 0.18
    min_cost = float("inf")
    for aircraft_type in route.aircraft_types:
        cost_per_km = aircraft_config.get(aircraft_type, {}).get("cost_per_km", 0.18)
        min_cost = min(min_cost, route.distance_km * cost_per_km)
    return min_cost


def _segments_from_path(
    graph: Graph,
    path: list[str],
    aircraft_config: dict,
) -> list[TripSegment]:
    """Convert a Dijkstra path (list of IATA codes) into TripSegment objects."""
    segments: list[TripSegment] = []
    cumulative_cost = 0.0
    cumulative_time = 0.0

    for index in range(len(path) - 1):
        origin_id = path[index]
        dest_id = path[index + 1]

        route: Optional[Route] = None
        for neighbor_id, candidate_route in graph.get_neighbors(origin_id):
            if neighbor_id == dest_id:
                route = candidate_route
                break

        if route is None:
            continue

        best_aircraft = route.aircraft_types[0] if route.aircraft_types else "Avión Comercial"
        best_cost = float("inf")
        best_time = float("inf")

        for aircraft_type in route.aircraft_types:
            cost_per_km = aircraft_config.get(aircraft_type, {}).get("cost_per_km", 0.18)
            time_per_km = aircraft_config.get(aircraft_type, {}).get("time_per_km", 0.7)
            seg_cost = 0.0 if route.is_subsidized else route.distance_km * cost_per_km
            seg_time = route.distance_km * time_per_km

            if seg_cost < best_cost:
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
# Public interruption functions
# ---------------------------------------------------------------------------

def block_route(
    graph: Graph,
    origin: str,
    dest: str,
    active_state: Optional[ItineraryState] = None,
) -> dict:
    """
    Block a directed edge in the graph, simulating a route interruption.

    The edge is marked as blocked (not deleted), so it can be restored
    later with unblock_route(). Dijkstra and BFS will automatically skip
    blocked edges via graph.get_neighbors().

    If an active ItineraryState is provided, the function checks whether
    the traveler is currently in transit on the blocked route. If so,
    the traveler must be redirected to the origin of that segment.

    Args:
        graph: The Graph instance to modify.
        origin: IATA code of the route's departure airport.
        dest: IATA code of the route's arrival airport.
        active_state: Optional current ItineraryState. If provided, transit
                      detection is performed.

    Returns:
        Dict with:
            "blocked": True if the edge was successfully blocked.
            "is_in_transit": True if the traveler was mid-flight on this route.
            "redirect_to": IATA code the traveler should return to (if in transit).
            "error": Error message string if the edge does not exist, else None.
    """
    result = {
        "blocked": False,
        "is_in_transit": False,
        "redirect_to": None,
        "error": None,
    }

    # Verify the edge exists before attempting to block it
    if not graph.has_edge(origin, dest):
        result["error"] = f"Route '{origin}' -> '{dest}' does not exist in the graph"
        return result

    # Block the edge
    graph.block_edge(origin, dest)
    result["blocked"] = True

    # Check if the traveler is currently flying this exact segment
    if active_state is not None and active_state.is_active:
        # The traveler is "in transit" if their last segment's origin and dest
        # match the blocked route AND they haven't landed yet.
        # We detect this by checking if the last segment in history goes to
        # a node that is NOT yet in the visited list (they're still flying).
        if active_state.segments:
            last_segment = active_state.segments[-1]
            if (
                last_segment.origin == origin
                and last_segment.dest == dest
                and dest not in active_state.visited
            ):
                result["is_in_transit"] = True
                result["redirect_to"] = origin

    return result


def unblock_route(graph: Graph, origin: str, dest: str) -> dict:
    """
    Remove the block from a previously blocked edge.

    Args:
        graph: The Graph instance.
        origin: IATA code of the route's departure airport.
        dest: IATA code of the route's arrival airport.

    Returns:
        Dict with:
            "unblocked": True if the edge was unblocked.
            "error": Error message if the edge does not exist, else None.
    """
    if not graph.has_edge(origin, dest):
        return {"unblocked": False, "error": f"Route '{origin}' -> '{dest}' does not exist"}

    graph.unblock_edge(origin, dest)
    return {"unblocked": True, "error": None}


def recalculate_after_block(
    graph: Graph,
    current_node: str,
    final_destination: str,
    aircraft_override: Optional[dict] = None,
) -> dict:
    """
    Recalculate the best available route after one or more edges have been blocked.

    Runs Dijkstra from current_node to final_destination on the current state
    of the graph (blocked edges are automatically excluded by get_neighbors()).

    Args:
        graph: The Graph instance with blocked edges already applied.
        current_node: IATA code of the traveler's current position.
        final_destination: IATA code of the intended final destination.
        aircraft_override: Optional dict to override default aircraft costs.

    Returns:
        Dict with:
            "found": True if an alternative route was found.
            "total_cost": Total cost of the new route in USD, or None.
            "path": List of IATA codes for the new route, or [].
            "segments": List of TripSegment objects, or [].
            "error": Descriptive error message if no route found, else None.
    """
    aircraft_config = _build_aircraft_config(aircraft_override)

    total_cost, path = dijkstra(
        graph=graph,
        origin=current_node,
        destination=final_destination,
        weight_fn=lambda route: _weight_fn_cost(route, aircraft_config),
    )

    if total_cost is None or not path:
        return {
            "found": False,
            "total_cost": None,
            "path": [],
            "segments": [],
            "error": (
                f"No alternative route found from '{current_node}' "
                f"to '{final_destination}'. All paths are blocked or "
                f"the destination is unreachable."
            ),
        }

    segments = _segments_from_path(graph, path, aircraft_config)

    return {
        "found": True,
        "total_cost": total_cost,
        "path": path,
        "segments": segments,
        "error": None,
    }


def get_blocked_routes(graph: Graph) -> list[dict]:
    """
    Return a list of all currently blocked routes.

    Args:
        graph: The Graph instance.

    Returns:
        List of dicts, each with 'origin' and 'dest' keys.
    """
    return [
        {"origin": origin, "dest": dest}
        for origin, dest in graph.get_blocked_edges()
    ]
