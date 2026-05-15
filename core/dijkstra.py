"""
Dijkstra's shortest path algorithm for SkyRoute Planner.

WHY DIJKSTRA?
    The route network is a weighted directed graph with non-negative edge
    weights (distances, times, costs are always >= 0). Dijkstra is the
    optimal algorithm for single-source shortest paths on such graphs.
    Time complexity: O((V + E) log V) with a binary heap.
    Space complexity: O(V) for the distance and predecessor tables.

    BFS would only work for unweighted graphs (all edges equal weight).
    Bellman-Ford handles negative weights but is O(VE) — too slow here.

WEIGHT FUNCTIONS:
    The algorithm accepts a weight_fn: Callable[[Route], float] so the
    same code can optimize for distance, time, or cost without duplication.
"""

import heapq
from typing import Callable, Optional

from core.graph import Graph
from core.models import Route


def dijkstra(
    graph: Graph,
    origin: str,
    destination: Optional[str],
    weight_fn: Callable[[Route], float],
) -> tuple[Optional[float], list[str]]:
    """
    Run Dijkstra's algorithm from origin, optionally stopping at destination.

    If destination is None, computes shortest paths to ALL reachable nodes
    and returns (total_weight_to_all, []) — useful for coverage problems.
    If destination is provided, returns as soon as it is settled.

    Args:
        graph: The Graph instance to traverse.
        origin: IATA code of the starting airport.
        destination: IATA code of the target airport, or None for full run.
        weight_fn: Function that extracts a float weight from a Route.
                   Examples:
                     lambda r: r.distance_km
                     lambda r: r.distance_km * 0.18  (cost for commercial)

    Returns:
        Tuple of (total_weight, path) where:
            total_weight: Minimum accumulated weight to reach destination,
                          or None if destination is unreachable / not given.
            path: Ordered list of IATA codes from origin to destination
                  (inclusive), or [] if destination is None or unreachable.

    Raises:
        KeyError: If origin does not exist in the graph.

    Complexity:
        Time:  O((V + E) log V)
        Space: O(V)

    Edge cases handled:
        - Disconnected graph: returns (None, []) if destination unreachable.
        - origin == destination: returns (0.0, [origin]).
        - Blocked edges: get_neighbors() already excludes them.
        - Node with no outgoing edges: treated as dead end.
    """

    # --- Early exit: trivial case ---
    if origin == destination:
        return 0.0, [origin]

    # dist[node] = best known cumulative weight from origin to node
    # Initialized to infinity for all nodes; origin starts at 0
    dist: dict[str, float] = {node: float("inf") for node in graph.get_all_nodes()}
    dist[origin] = 0.0

    # prev[node] = the node we came from on the best known path to node
    # Used to reconstruct the path once the destination is settled
    prev: dict[str, Optional[str]] = {node: None for node in graph.get_all_nodes()}

    # Priority queue: min-heap of (cumulative_weight, node_id)
    # heapq in Python is a min-heap, so the node with the smallest
    # cumulative weight is always processed first — this is the greedy
    # choice that makes Dijkstra correct for non-negative weights.
    heap: list[tuple[float, str]] = [(0.0, origin)]

    # visited (settled) set: once a node is popped from the heap with its
    # minimum distance, we never need to process it again.
    settled: set[str] = set()

    while heap:
        # Pop the node with the current smallest known distance
        current_dist, current_node = heapq.heappop(heap)

        # If we already settled this node, skip it.
        # This handles the case where a node appears multiple times in the
        # heap with different distances (lazy deletion pattern).
        if current_node in settled:
            continue

        # Mark this node as settled — its shortest distance is now final
        settled.add(current_node)

        # Early termination: if we just settled the destination, we have
        # the optimal path and there is no need to explore further.
        if destination is not None and current_node == destination:
            break

        # Explore all non-blocked neighbors of the current node
        for neighbor_id, route in graph.get_neighbors(current_node):

            # Compute the weight of this edge using the caller's weight function
            edge_weight = weight_fn(route)

            # Relaxation step: if going through current_node gives a shorter
            # path to neighbor_id than what we knew before, update it.
            candidate_dist = current_dist + edge_weight

            if candidate_dist < dist[neighbor_id]:
                # Found a better path to neighbor_id
                dist[neighbor_id] = candidate_dist
                prev[neighbor_id] = current_node

                # Push the updated distance into the heap.
                # We do NOT remove the old entry (lazy deletion) because
                # heapq does not support decrease-key efficiently.
                heapq.heappush(heap, (candidate_dist, neighbor_id))

    # --- Path reconstruction ---
    if destination is None:
        # Full-graph run: no single path to return
        return None, []

    if dist[destination] == float("inf"):
        # Destination was never reached — graph is disconnected or all
        # paths to destination are blocked
        return None, []

    # Walk backwards from destination to origin using prev pointers
    path: list[str] = []
    node: Optional[str] = destination
    while node is not None:
        path.append(node)
        node = prev[node]

    # Reverse to get origin -> ... -> destination order
    path.reverse()

    return dist[destination], path


def multi_dijkstra(
    graph: Graph,
    origin: str,
    destination: str,
    weight_fns: dict[str, Callable[[Route], float]],
) -> dict[str, dict]:
    """
    Run Dijkstra once per criterion and return all results in a single call.

    Args:
        graph: The Graph instance to traverse.
        origin: IATA code of the starting airport.
        destination: IATA code of the target airport.
        weight_fns: Dict mapping criterion name to its weight function.
                    Example:
                    {
                        "distance": lambda r: r.distance_km,
                        "cost":     lambda r: r.distance_km * 0.18,
                        "time":     lambda r: r.distance_km * 0.7,
                    }

    Returns:
        Dict mapping each criterion name to a result dict:
        {
            "distance": {"total": float, "path": [str, ...]},
            "cost":     {"total": float, "path": [str, ...]},
            ...
        }
        If a criterion yields no path, "total" is None and "path" is [].
    """
    results: dict[str, dict] = {}

    for criterion, weight_fn in weight_fns.items():
        total, path = dijkstra(graph, origin, destination, weight_fn)
        results[criterion] = {"total": total, "path": path}

    return results
