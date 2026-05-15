"""
R3 — Advanced dynamic itinerary planning with budget management.

This module implements the step-by-step trip simulation where the traveler
can earn money by taking jobs, pay for mandatory lodging and food, and
choose optional activities at each airport.

Key design decisions:
    - Each trip is identified by a session_id stored in api/state.sessions.
    - The state (ItineraryState) is mutated in place as the traveler moves.
    - All monetary and time constraints from config.py are enforced here.
    - Dijkstra is used to suggest the best next move from the current airport.
    - The 20% subsidized distance cap is tracked across the whole trip.

Constraint rules (from project spec):
    - Lodging:  mandatory every DEFAULT_LODGING_INTERVAL_HOURS (20h).
    - Food:     mandatory every DEFAULT_FOOD_INTERVAL_HOURS (8h).
    - Jobs:     only offered when budget < DEFAULT_BUDGET_MIN_PERCENT * initial.
    - Subsidy:  total subsidized km <= MAX_SUBSIDIZED_DISTANCE_PERCENT * total km.
"""

import uuid
from typing import Any, Optional

from config import (
    DEFAULT_AIRCRAFT,
    DEFAULT_BUDGET_MIN_PERCENT,
    DEFAULT_FOOD_INTERVAL_HOURS,
    DEFAULT_LODGING_INTERVAL_HOURS,
    MAX_SUBSIDIZED_DISTANCE_PERCENT,
)
from core.dijkstra import dijkstra
from core.graph import Graph
from core.models import ItineraryState, Route, TripSegment


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------

def start_trip(
    graph: Graph,
    origin: str,
    initial_budget: float,
    time_hours: float,
) -> ItineraryState:
    """
    Create and return a new ItineraryState for a dynamic trip session.

    The session_id is a UUID generated here. The caller (router) is
    responsible for storing it in api.state.sessions.

    Args:
        graph: The loaded Graph instance.
        origin: IATA code of the starting airport.
        initial_budget: Starting budget in USD.
        time_hours: Total available trip time in hours.

    Returns:
        A fresh ItineraryState with the traveler at the origin airport.

    Raises:
        KeyError: If origin does not exist in the graph.
        ValueError: If budget or time are non-positive.
    """
    if not graph.has_node(origin):
        raise KeyError(f"Airport '{origin}' not found in graph.")
    if initial_budget <= 0:
        raise ValueError("initial_budget must be > 0")
    if time_hours <= 0:
        raise ValueError("time_hours must be > 0")

    session_id = str(uuid.uuid4())

    return ItineraryState(
        session_id=session_id,
        current_airport=origin,
        budget_remaining=initial_budget,
        time_remaining_hours=time_hours,
        initial_budget=initial_budget,
        visited=[origin],
    )


def end_trip(state: ItineraryState) -> None:
    """
    Mark a trip session as finished.

    Args:
        state: The active ItineraryState to close.
    """
    state.is_active = False


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

def get_available_flights(
    graph: Graph,
    state: ItineraryState,
) -> list[dict[str, Any]]:
    """
    Return all flights the traveler can take from their current airport.

    For each neighbor reachable from current_airport (non-blocked edges),
    computes the cost and time for every aircraft type on that route.
    Filters out:
        - Already visited airports (no repeated nodes per spec).
        - Routes where all aircraft options exceed remaining budget.
        - Routes where travel time exceeds remaining time.
        - Subsidized routes that would push total subsidized km over 20%.

    Args:
        graph: The loaded Graph instance.
        state: Current ItineraryState of the traveler.

    Returns:
        List of flight option dicts, each containing:
            dest, distance_km, aircraft_options (list of dicts with
            aircraft_type, cost_usd, time_min), min_stay_min,
            is_subsidized, recommended_aircraft (cheapest valid option).
    """
    options: list[dict[str, Any]] = []
    time_remaining_min = state.time_remaining_hours * 60.0

    for neighbor_id, route in graph.get_neighbors(state.current_airport):

        # Skip already-visited airports
        if neighbor_id in state.visited:
            continue

        # Evaluate each aircraft type available on this route
        valid_aircraft: list[dict[str, Any]] = []

        for aircraft_type in route.aircraft_types:
            config = DEFAULT_AIRCRAFT.get(aircraft_type, DEFAULT_AIRCRAFT["Avión Comercial"])

            # Compute cost
            if route.is_subsidized:
                cost = 0.0
            else:
                cost = round(route.distance_km * config["cost_per_km"], 2)

            # Check subsidized distance cap before accepting a free route
            if route.is_subsidized:
                projected_subsidized_km = state.total_subsidized_km + route.distance_km
                projected_total_km = state.total_km + route.distance_km
                if projected_total_km > 0:
                    subsidy_ratio = projected_subsidized_km / projected_total_km
                    if subsidy_ratio > MAX_SUBSIDIZED_DISTANCE_PERCENT:
                        # This subsidized leg would breach the 20% cap — skip
                        continue

            # Compute time
            flight_time_min = round(route.distance_km * config["time_per_km"], 2)

            # Hard constraints: budget and time
            if cost > state.budget_remaining:
                continue
            if flight_time_min > time_remaining_min:
                continue

            valid_aircraft.append({
                "aircraft_type": aircraft_type,
                "cost_usd": cost,
                "time_min": flight_time_min,
            })

        if not valid_aircraft:
            continue

        # Recommend the cheapest valid aircraft
        recommended = min(valid_aircraft, key=lambda a: a["cost_usd"])

        options.append({
            "dest": neighbor_id,
            "distance_km": route.distance_km,
            "is_subsidized": route.is_subsidized,
            "min_stay_min": route.min_stay_min,
            "aircraft_options": valid_aircraft,
            "recommended_aircraft": recommended,
        })

    return options


def fly_to(
    graph: Graph,
    state: ItineraryState,
    dest: str,
    aircraft_type: str,
) -> dict[str, Any]:
    """
    Move the traveler from their current airport to dest using aircraft_type.

    Deducts cost from budget, advances time, updates subsidized km tracking,
    checks if mandatory lodging or food is now due, and records the segment.

    Args:
        graph: The loaded Graph instance.
        state: Current ItineraryState (mutated in place).
        dest: IATA code of the destination airport.
        aircraft_type: Aircraft type to use for this leg.

    Returns:
        Dict with keys:
            segment (TripSegment), mandatory_events (list of str describing
            lodging/food obligations triggered), budget_remaining,
            time_remaining_hours, current_airport.

    Raises:
        KeyError: If the edge or aircraft type does not exist.
        ValueError: If constraints would be violated.
    """
    if not graph.has_edge(state.current_airport, dest):
        raise KeyError(f"No route from '{state.current_airport}' to '{dest}'.")

    if dest in state.visited:
        raise ValueError(f"Airport '{dest}' has already been visited.")

    # Find the route
    route: Optional[Route] = None
    for neighbor_id, r in graph.get_neighbors(state.current_airport):
        if neighbor_id == dest:
            route = r
            break

    if route is None:
        raise KeyError(f"Route '{state.current_airport}' -> '{dest}' is blocked or missing.")

    if aircraft_type not in route.aircraft_types:
        raise ValueError(
            f"Aircraft '{aircraft_type}' does not operate route "
            f"'{state.current_airport}' -> '{dest}'."
        )

    config = DEFAULT_AIRCRAFT.get(aircraft_type, DEFAULT_AIRCRAFT["Avión Comercial"])

    # Compute cost and time
    if route.is_subsidized:
        cost = 0.0
    else:
        cost = round(route.distance_km * config["cost_per_km"], 2)

    flight_time_min = round(route.distance_km * config["time_per_km"], 2)
    flight_time_hours = flight_time_min / 60.0

    # Validate hard constraints
    if cost > state.budget_remaining:
        raise ValueError(
            f"Insufficient budget. Required: ${cost:.2f}, Available: ${state.budget_remaining:.2f}"
        )
    if flight_time_hours > state.time_remaining_hours:
        raise ValueError(
            f"Insufficient time. Required: {flight_time_hours:.2f}h, "
            f"Available: {state.time_remaining_hours:.2f}h"
        )

    # Build segment
    new_cumulative_cost = sum(s.cost_usd for s in state.segments) + cost
    new_cumulative_time = sum(s.flight_time_min for s in state.segments) + flight_time_min

    segment = TripSegment(
        origin=state.current_airport,
        dest=dest,
        aircraft_type=aircraft_type,
        distance_km=route.distance_km,
        flight_time_min=flight_time_min,
        cost_usd=cost,
        cumulative_cost=new_cumulative_cost,
        cumulative_time_min=new_cumulative_time,
    )

    # Mutate state
    state.budget_remaining -= cost
    state.time_remaining_hours -= flight_time_hours
    state.hours_since_lodging += flight_time_hours
    state.hours_since_food += flight_time_hours
    state.total_km += route.distance_km
    if route.is_subsidized:
        state.total_subsidized_km += route.distance_km

    state.current_airport = dest
    state.visited.append(dest)
    state.segments.append(segment)

    # Check mandatory events triggered during or after this flight
    mandatory_events = _check_mandatory_events(graph, state)

    return {
        "segment": segment,
        "mandatory_events": mandatory_events,
        "budget_remaining": state.budget_remaining,
        "time_remaining_hours": state.time_remaining_hours,
        "current_airport": state.current_airport,
    }


# ---------------------------------------------------------------------------
# Mandatory events (lodging and food)
# ---------------------------------------------------------------------------

def _check_mandatory_events(graph: Graph, state: ItineraryState) -> list[str]:
    """
    Check and apply mandatory lodging and food charges.

    Called automatically after every fly_to(). Charges are deducted from
    the budget and the interval counters are reset.

    Args:
        graph: The Graph instance (needed to read airport costs).
        state: ItineraryState to check and mutate.

    Returns:
        List of human-readable strings describing each event that triggered.
    """
    events: list[str] = []
    airport = graph.get_node(state.current_airport)

    # --- Lodging check ---
    if state.hours_since_lodging >= DEFAULT_LODGING_INTERVAL_HOURS:
        lodging_cost = airport.lodging_cost
        state.budget_remaining -= lodging_cost
        state.hours_since_lodging = 0.0
        state.activities_done.append({
            "name": "Alojamiento",
            "type": "obligatoria",
            "duration_min": 480,       # 8 hours rest assumed
            "cost_usd": lodging_cost,
            "airport_iata": state.current_airport,
        })
        events.append(
            f"Mandatory lodging at {state.current_airport}: -${lodging_cost:.2f}"
        )

    # --- Food check ---
    if state.hours_since_food >= DEFAULT_FOOD_INTERVAL_HOURS:
        food_cost = airport.food_cost
        state.budget_remaining -= food_cost
        state.hours_since_food = 0.0
        state.activities_done.append({
            "name": "Alimentación",
            "type": "obligatoria",
            "duration_min": 45,
            "cost_usd": food_cost,
            "airport_iata": state.current_airport,
        })
        events.append(
            f"Mandatory meal at {state.current_airport}: -${food_cost:.2f}"
        )

    return events


# ---------------------------------------------------------------------------
# Optional activities
# ---------------------------------------------------------------------------

def get_available_activities(graph: Graph, state: ItineraryState) -> list[dict[str, Any]]:
    """
    Return all optional activities available at the current airport.

    Only 'opcional' type activities are returned — mandatory ones (lodging,
    food) are handled automatically by _check_mandatory_events().

    Args:
        graph: The Graph instance.
        state: Current ItineraryState.

    Returns:
        List of activity dicts with name, duration_min, cost_usd, and
        whether the traveler can afford it (can_afford bool).
    """
    airport = graph.get_node(state.current_airport)
    result: list[dict[str, Any]] = []

    for activity in airport.activities:
        if activity.type != "opcional":
            continue

        result.append({
            "name": activity.name,
            "type": activity.type,
            "duration_min": activity.duration_min,
            "cost_usd": activity.cost_usd,
            "can_afford": activity.cost_usd <= state.budget_remaining,
        })

    return result


def do_activity(graph: Graph, state: ItineraryState, activity_name: str) -> dict[str, Any]:
    """
    Perform an optional activity at the current airport.

    Deducts the activity cost from budget and advances time.

    Args:
        graph: The Graph instance.
        state: Current ItineraryState (mutated in place).
        activity_name: Name of the activity to perform.

    Returns:
        Dict with cost_usd, duration_min, budget_remaining, time_remaining_hours.

    Raises:
        ValueError: If the activity is not found or not affordable.
    """
    airport = graph.get_node(state.current_airport)

    activity = next(
        (a for a in airport.activities if a.name == activity_name and a.type == "opcional"),
        None,
    )

    if activity is None:
        raise ValueError(
            f"Optional activity '{activity_name}' not found at {state.current_airport}."
        )

    if activity.cost_usd > state.budget_remaining:
        raise ValueError(
            f"Cannot afford activity '{activity_name}'. "
            f"Cost: ${activity.cost_usd:.2f}, Available: ${state.budget_remaining:.2f}"
        )

    duration_hours = activity.duration_min / 60.0
    if duration_hours > state.time_remaining_hours:
        raise ValueError(
            f"Not enough time for '{activity_name}'. "
            f"Requires: {duration_hours:.2f}h, Available: {state.time_remaining_hours:.2f}h"
        )

    # Mutate state
    state.budget_remaining -= activity.cost_usd
    state.time_remaining_hours -= duration_hours
    state.hours_since_food += duration_hours
    state.hours_since_lodging += duration_hours

    state.activities_done.append({
        "name": activity.name,
        "type": activity.type,
        "duration_min": activity.duration_min,
        "cost_usd": activity.cost_usd,
        "airport_iata": state.current_airport,
    })

    return {
        "cost_usd": activity.cost_usd,
        "duration_min": activity.duration_min,
        "budget_remaining": state.budget_remaining,
        "time_remaining_hours": state.time_remaining_hours,
    }


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

def get_available_jobs(graph: Graph, state: ItineraryState) -> list[dict[str, Any]]:
    """
    Return jobs available at the current airport if budget threshold is met.

    Jobs are only offered when budget_remaining < DEFAULT_BUDGET_MIN_PERCENT
    of the initial_budget (35% by default).

    Args:
        graph: The Graph instance.
        state: Current ItineraryState.

    Returns:
        List of job dicts. Empty list if budget threshold is not met.
        Each dict contains name, hourly_rate, max_hours,
        max_earnable_usd (rate * max_hours).
    """
    # Only offer jobs when budget falls below threshold
    budget_threshold = state.initial_budget * DEFAULT_BUDGET_MIN_PERCENT
    if state.budget_remaining >= budget_threshold:
        return []

    airport = graph.get_node(state.current_airport)
    result: list[dict[str, Any]] = []

    for job in airport.jobs:
        result.append({
            "name": job.name,
            "hourly_rate": job.hourly_rate,
            "max_hours": job.max_hours,
            "max_earnable_usd": round(job.hourly_rate * job.max_hours, 2),
        })

    return result


def do_job(
    graph: Graph,
    state: ItineraryState,
    job_name: str,
    hours: float,
) -> dict[str, Any]:
    """
    Accept a temporary job at the current airport and earn income.

    Income = hourly_rate * hours_worked.
    Time is deducted from the remaining trip time.
    Budget is increased by the earned income.

    Args:
        graph: The Graph instance.
        state: Current ItineraryState (mutated in place).
        job_name: Name of the job to perform.
        hours: Number of hours to work (must be <= job.max_hours).

    Returns:
        Dict with income_usd, hours_worked, budget_remaining, time_remaining_hours.

    Raises:
        ValueError: If job not found, hours exceed max, or time is insufficient.
    """
    airport = graph.get_node(state.current_airport)

    job = next((j for j in airport.jobs if j.name == job_name), None)

    if job is None:
        raise ValueError(f"Job '{job_name}' not found at {state.current_airport}.")

    if hours <= 0:
        raise ValueError("hours must be > 0")

    if hours > job.max_hours:
        raise ValueError(
            f"Cannot work more than {job.max_hours}h at '{job_name}'. Requested: {hours}h"
        )

    if hours > state.time_remaining_hours:
        raise ValueError(
            f"Not enough trip time to work {hours}h. Available: {state.time_remaining_hours:.2f}h"
        )

    income = round(job.hourly_rate * hours, 2)

    # Mutate state
    state.budget_remaining += income
    state.time_remaining_hours -= hours
    state.hours_since_food += hours
    state.hours_since_lodging += hours

    state.jobs_done.append({
        "name": job.name,
        "hours_worked": hours,
        "income_usd": income,
        "airport_iata": state.current_airport,
    })

    # Re-check mandatory events after time passes
    _check_mandatory_events(graph, state)

    return {
        "income_usd": income,
        "hours_worked": hours,
        "budget_remaining": state.budget_remaining,
        "time_remaining_hours": state.time_remaining_hours,
    }


# ---------------------------------------------------------------------------
# Suggestion helper (Dijkstra-powered next hop)
# ---------------------------------------------------------------------------

def suggest_next_destination(graph: Graph, state: ItineraryState) -> dict[str, Any]:
    """
    Use Dijkstra to suggest the cheapest unvisited reachable airport.

    Runs Dijkstra from the current airport minimizing cost (USD).
    Returns the first unvisited reachable node, along with the full
    cheapest path from current position to that suggestion.

    Args:
        graph: The Graph instance.
        state: Current ItineraryState.

    Returns:
        Dict with suggested_dest, path, estimated_cost, estimated_time_min.
        Returns {"suggested_dest": None} if no unvisited node is reachable.
    """
    unvisited = [n for n in graph.get_all_nodes() if n not in state.visited]

    if not unvisited:
        return {"suggested_dest": None, "path": [], "estimated_cost": 0, "estimated_time_min": 0}

    best_dest: Optional[str] = None
    best_cost: float = float("inf")
    best_path: list[str] = []

    def cost_weight(route: Route) -> float:
        """Weight function: cheapest aircraft cost for this route."""
        if route.is_subsidized:
            return 0.0
        min_cost = float("inf")
        for aircraft_type in route.aircraft_types:
            config = DEFAULT_AIRCRAFT.get(aircraft_type, DEFAULT_AIRCRAFT["Avión Comercial"])
            candidate = route.distance_km * config["cost_per_km"]
            if candidate < min_cost:
                min_cost = candidate
        return min_cost

    for dest in unvisited:
        total, path = dijkstra(graph, state.current_airport, dest, cost_weight)
        if total is not None and total < best_cost and total <= state.budget_remaining:
            best_cost = total
            best_dest = dest
            best_path = path

    if best_dest is None:
        return {"suggested_dest": None, "path": [], "estimated_cost": 0, "estimated_time_min": 0}

    # Estimate time for the suggested path using fastest available aircraft
    estimated_time_min = 0.0
    for i in range(len(best_path) - 1):
        for neighbor_id, route in graph.get_neighbors(best_path[i]):
            if neighbor_id == best_path[i + 1]:
                min_time = float("inf")
                for aircraft_type in route.aircraft_types:
                    config = DEFAULT_AIRCRAFT.get(aircraft_type, DEFAULT_AIRCRAFT["Avión Comercial"])
                    t = route.distance_km * config["time_per_km"]
                    if t < min_time:
                        min_time = t
                estimated_time_min += min_time
                break

    return {
        "suggested_dest": best_dest,
        "path": best_path,
        "estimated_cost": round(best_cost, 2),
        "estimated_time_min": round(estimated_time_min, 2),
    }