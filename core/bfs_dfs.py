"""
BFS and DFS algorithms for maximum destination coverage.

WHY BFS FOR COVERAGE?
    BFS explores the graph level by level (by number of hops). This means
    it finds the maximum number of reachable destinations with the fewest
    intermediate stops first. When we have a budget or time limit, BFS
    naturally explores cheaper/shorter paths before deeper ones, making
    it well-suited for maximizing the number of visited nodes.

    DFS explores as deep as possible before backtracking. It can find
    longer routes but does NOT guarantee visiting the most destinations
    within a constraint — it may exhaust the budget on a single deep path.
    DFS is included for completeness and for cases where depth is preferred.

COMPLEXITY:
    BFS: O(V + E) time, O(V) space for the queue and visited set.
    DFS: O(V + E) time, O(V) space for the stack and visited set.

CONSTRAINT HANDLING:
    Both algorithms carry accumulated cost/time along each path.
    A node is only enqueued if adding it does not violate the constraint.
    The traveler cannot revisit a node (visited set enforced per path).
"""

from collections import deque
from typing import Callable, Optional

from core.graph import Graph
from core.models import Route, TripSegment


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_aircraft_cost_per_km(aircraft_type: str, aircraft_config: dict) -> float:
    """
    Return the cost per km for a given aircraft type.

    Args:
        aircraft_type: Aircraft name string (e.g. 'Avión Comercial').
        aircraft_config: Dict mapping aircraft name -> {'cost_per_km': float, ...}.

    Returns:
        Cost per km as float. Falls back to 0.18 if type not found.
    """
    entry = aircraft_config.get(aircraft_type, {})
    return entry.get("cost_per_km", 0.18)


def _get_aircraft_time_per_km(aircraft_type: str, aircraft_config: dict) -> float:
    """
    Return the time per km (minutes) for a given aircraft type.

    Args:
        aircraft_type: Aircraft name string.
        aircraft_config: Dict mapping aircraft name -> {'time_per_km': float, ...}.

    Returns:
        Time per km in minutes. Falls back to 0.7 if type not found.
    """
    entry = aircraft_config.get(aircraft_type, {})
    return entry.get("time_per_km", 0.7)


def _cheapest_aircraft(route: Route, aircraft_config: dict) -> tuple[str, float]:
    """
    Select the aircraft type with the lowest cost for a given route.

    Only considers aircraft types that actually operate this route.

    Args:
        route: Route dataclass instance.
        aircraft_config: Dict of aircraft configurations.

    Returns:
        Tuple of (aircraft_type_name, cost_usd_for_this_segment).
    """
    best_type = route.aircraft_types[0] if route.aircraft_types else "Avión Comercial"
    best_cost = float("inf")

    for aircraft_type in route.aircraft_types:
        if route.is_subsidized:
            # Subsidized route: cost is 0 regardless of aircraft
            segment_cost = 0.0
        else:
            cost_per_km = _get_aircraft_cost_per_km(aircraft_type, aircraft_config)
            segment_cost = route.distance_km * cost_per_km

        if segment_cost < best_cost:
            best_cost = segment_cost
            best_type = aircraft_type

    return best_type, best_cost


def _fastest_aircraft(route: Route, aircraft_config: dict) -> tuple[str, float]:
    """
    Select the aircraft type with the shortest travel time for a given route.

    Args:
        route: Route dataclass instance.
        aircraft_config: Dict of aircraft configurations.

    Returns:
        Tuple of (aircraft_type_name, time_minutes_for_this_segment).
    """
    best_type = route.aircraft_types[0] if route.aircraft_types else "Avión Comercial"
    best_time = float("inf")

    for aircraft_type in route.aircraft_types:
        time_per_km = _get_aircraft_time_per_km(aircraft_type, aircraft_config)
        segment_time = route.distance_km * time_per_km

        if segment_time < best_time:
            best_time = segment_time
            best_type = aircraft_type

    return best_type, best_time


# ---------------------------------------------------------------------------
# BFS — maximum coverage by budget
# ---------------------------------------------------------------------------

def bfs_max_coverage_by_budget(
    graph: Graph,
    origin: str,
    budget_usd: float,
    aircraft_config: dict,
    include_secondary: bool = True,
) -> list[TripSegment]:
    """
    BFS that maximizes the number of destinations visited without exceeding budget.

    Explores the graph level by level. At each level, enqueues all neighbors
    reachable without violating the budget constraint. The path that visits
    the most nodes is returned.

    WHY BFS: Level-by-level exploration ensures we find the maximum number
    of destinations reachable with the fewest hops first. This is optimal
    for maximizing coverage because we don't waste budget on deep detours
    before exploring nearby airports.

    Args:
        graph: The Graph instance (blocked edges are automatically excluded).
        origin: IATA code of the starting airport.
        budget_usd: Maximum total cost allowed in USD.
        aircraft_config: Dict mapping aircraft name -> cost/time per km.
        include_secondary: If False, only hub airports are considered as
                           intermediate or destination nodes.

    Returns:
        List of TripSegment instances representing the best path found.
        Empty list if no neighbor is reachable within budget.

    Complexity:
        Time:  O(V + E) — each node/edge visited at most once per path state.
        Space: O(V) — queue holds at most V states simultaneously.

    Edge cases:
        - budget_usd == 0: only subsidized routes are traversable.
        - Isolated origin: returns [].
        - All neighbors blocked: returns [].
    """

    # Each queue entry is a state: (current_node, accumulated_cost, path_segments, visited_set)
    # We use a deque for O(1) popleft (FIFO — essential for BFS level order)
    initial_state = (origin, 0.0, [], {origin})
    queue: deque = deque([initial_state])

    # Track the best result found so far (most segments = most destinations)
    best_segments: list[TripSegment] = []

    while queue:
        # Dequeue the next state to explore (FIFO order = BFS)
        current_node, accumulated_cost, path_segments, visited = queue.popleft()

        # Explore all non-blocked neighbors of the current node
        for neighbor_id, route in graph.get_neighbors(current_node):

            # Skip already-visited nodes (no repeated airports per R1 constraint)
            if neighbor_id in visited:
                continue

            # If secondary airports are excluded, skip non-hub nodes
            if not include_secondary:
                neighbor_airport = graph.get_node(neighbor_id)
                if not neighbor_airport.is_hub:
                    continue

            # Choose the cheapest aircraft for this route
            aircraft_type, segment_cost = _cheapest_aircraft(route, aircraft_config)

            # Compute new accumulated cost after taking this route
            new_cost = accumulated_cost + segment_cost

            # HARD CONSTRAINT: do not exceed budget
            if new_cost > budget_usd:
                continue  # This neighbor is too expensive — skip it

            # Build the TripSegment for this leg
            cost_per_km = _get_aircraft_cost_per_km(aircraft_type, aircraft_config)
            time_per_km = _get_aircraft_time_per_km(aircraft_type, aircraft_config)
            flight_time = route.distance_km * time_per_km

            segment = TripSegment(
                origin=current_node,
                dest=neighbor_id,
                aircraft_type=aircraft_type,
                distance_km=route.distance_km,
                flight_time_min=flight_time,
                cost_usd=segment_cost,
                cumulative_cost=new_cost,
                cumulative_time_min=sum(s.flight_time_min for s in path_segments) + flight_time,
            )

            new_path = path_segments + [segment]
            new_visited = visited | {neighbor_id}

            # Update best result if this path visits more destinations
            if len(new_path) > len(best_segments):
                best_segments = new_path

            # Enqueue this new state for further exploration
            queue.append((neighbor_id, new_cost, new_path, new_visited))

    return best_segments


# ---------------------------------------------------------------------------
# BFS — maximum coverage by time
# ---------------------------------------------------------------------------

def bfs_max_coverage_by_time(
    graph: Graph,
    origin: str,
    time_limit_hours: float,
    aircraft_config: dict,
    include_secondary: bool = True,
) -> list[TripSegment]:
    """
    BFS that maximizes the number of destinations visited without exceeding time.

    Identical structure to bfs_max_coverage_by_budget but the constraint
    is total flight time in hours instead of cost in USD.

    WHY BFS: Same reasoning as the budget version — level-by-level ensures
    we find the most destinations reachable in the fewest hops first.

    Args:
        graph: The Graph instance.
        origin: IATA code of the starting airport.
        time_limit_hours: Maximum total flight time allowed in hours.
        aircraft_config: Dict mapping aircraft name -> cost/time per km.
        include_secondary: If False, only hub airports are considered.

    Returns:
        List of TripSegment instances representing the best path found.

    Complexity:
        Time:  O(V + E)
        Space: O(V)

    Edge cases:
        - time_limit_hours == 0: no routes are traversable.
        - Isolated origin: returns [].
    """
    time_limit_min = time_limit_hours * 60.0  # Convert to minutes for comparison

    # Queue state: (current_node, accumulated_time_min, path_segments, visited_set)
    initial_state = (origin, 0.0, [], {origin})
    queue: deque = deque([initial_state])

    best_segments: list[TripSegment] = []

    while queue:
        current_node, accumulated_time, path_segments, visited = queue.popleft()

        for neighbor_id, route in graph.get_neighbors(current_node):

            if neighbor_id in visited:
                continue

            if not include_secondary:
                neighbor_airport = graph.get_node(neighbor_id)
                if not neighbor_airport.is_hub:
                    continue

            # Choose the fastest aircraft for this route (time optimization)
            aircraft_type, segment_time = _fastest_aircraft(route, aircraft_config)

            new_time = accumulated_time + segment_time

            # HARD CONSTRAINT: do not exceed time limit
            if new_time > time_limit_min:
                continue

            # Compute cost for reporting purposes (use cheapest aircraft cost)
            _, segment_cost = _cheapest_aircraft(route, aircraft_config)

            segment = TripSegment(
                origin=current_node,
                dest=neighbor_id,
                aircraft_type=aircraft_type,
                distance_km=route.distance_km,
                flight_time_min=segment_time,
                cost_usd=segment_cost,
                cumulative_cost=sum(s.cost_usd for s in path_segments) + segment_cost,
                cumulative_time_min=new_time,
            )

            new_path = path_segments + [segment]
            new_visited = visited | {neighbor_id}

            if len(new_path) > len(best_segments):
                best_segments = new_path

            queue.append((neighbor_id, new_time, new_path, new_visited))

    return best_segments


# ---------------------------------------------------------------------------
# DFS — deep path exploration
# ---------------------------------------------------------------------------

def dfs_explore(
    graph: Graph,
    origin: str,
    budget_usd: float,
    aircraft_config: dict,
    include_secondary: bool = True,
) -> list[TripSegment]:
    """
    DFS that explores as deep as possible within a budget constraint.

    WHY DFS HERE: DFS is useful when we want to find a single long path
    rather than the broadest coverage. It may find routes that BFS misses
    because BFS stops exploring a branch once it finds a cheaper neighbor.
    However, DFS does NOT guarantee maximum coverage — it may exhaust the
    budget on a single deep path while missing many nearby destinations.

    Use bfs_max_coverage_by_budget for R2 (maximum destinations).
    Use dfs_explore when a deep single-path exploration is needed.

    Args:
        graph: The Graph instance.
        origin: IATA code of the starting airport.
        budget_usd: Maximum total cost allowed in USD.
        aircraft_config: Dict mapping aircraft name -> cost/time per km.
        include_secondary: If False, only hub airports are considered.

    Returns:
        List of TripSegment instances for the deepest path found within budget.

    Complexity:
        Time:  O(V + E)
        Space: O(V) for the explicit stack.
    """
    # Stack state: (current_node, accumulated_cost, path_segments, visited_set)
    # Using an explicit stack (list) instead of recursion to avoid Python's
    # default recursion limit on large graphs.
    stack: list = [(origin, 0.0, [], {origin})]

    best_segments: list[TripSegment] = []

    while stack:
        # Pop from the top of the stack (LIFO — essential for DFS)
        current_node, accumulated_cost, path_segments, visited = stack.pop()

        for neighbor_id, route in graph.get_neighbors(current_node):

            if neighbor_id in visited:
                continue

            if not include_secondary:
                neighbor_airport = graph.get_node(neighbor_id)
                if not neighbor_airport.is_hub:
                    continue

            aircraft_type, segment_cost = _cheapest_aircraft(route, aircraft_config)
            new_cost = accumulated_cost + segment_cost

            if new_cost > budget_usd:
                continue

            time_per_km = _get_aircraft_time_per_km(aircraft_type, aircraft_config)
            flight_time = route.distance_km * time_per_km

            segment = TripSegment(
                origin=current_node,
                dest=neighbor_id,
                aircraft_type=aircraft_type,
                distance_km=route.distance_km,
                flight_time_min=flight_time,
                cost_usd=segment_cost,
                cumulative_cost=new_cost,
                cumulative_time_min=sum(s.flight_time_min for s in path_segments) + flight_time,
            )

            new_path = path_segments + [segment]
            new_visited = visited | {neighbor_id}

            if len(new_path) > len(best_segments):
                best_segments = new_path

            # Push onto stack for depth-first exploration
            stack.append((neighbor_id, new_cost, new_path, new_visited))

    return best_segments
