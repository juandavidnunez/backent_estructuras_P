"""
R3 — Dynamic itinerary planning endpoints (step-by-step with budget management).

All routes are prefixed with /api/v1/dynamic (registered in main.py).

The R3 flow is session-based:
    1. POST /start          — Begin a new trip session.
    2. GET  /flights        — See available flights from current position.
    3. POST /fly            — Move to a destination airport.
    4. GET  /activities     — See optional activities at current airport.
    5. POST /activity       — Perform an optional activity.
    6. GET  /jobs           — See available jobs (only when budget is low).
    7. POST /job            — Accept a job and earn income.
    8. GET  /suggest        — Get a Dijkstra-powered destination suggestion.
    9. POST /end            — Close the session (report generated via R5).
"""

from fastapi import APIRouter

import api.state as state
from api.schemas import ApiResponse
from features.dynamic import (
    do_activity,
    do_job,
    end_trip,
    fly_to,
    get_available_activities,
    get_available_flights,
    get_available_jobs,
    start_trip,
    suggest_next_destination,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# R3 — Pydantic request models (defined here to keep schemas.py clean for
#       the shared models that all routers use)
# ---------------------------------------------------------------------------

from pydantic import BaseModel, Field
from typing import Optional


class StartTripRequest(BaseModel):
    origin: str = Field(..., description="IATA code of the starting airport")
    initial_budget: float = Field(..., gt=0, description="Starting budget in USD")
    time_hours: float = Field(..., gt=0, description="Total available trip time in hours")


class FlyRequest(BaseModel):
    session_id: str = Field(..., description="Active session ID")
    dest: str = Field(..., description="IATA code of the destination airport")
    aircraft_type: str = Field(..., description="Aircraft type to use for this leg")


class ActivityRequest(BaseModel):
    session_id: str
    activity_name: str = Field(..., description="Name of the optional activity to perform")


class JobRequest(BaseModel):
    session_id: str
    job_name: str = Field(..., description="Name of the job to accept")
    hours: float = Field(..., gt=0, description="Number of hours to work")


class EndTripRequest(BaseModel):
    session_id: str


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _get_session(session_id: str):
    """Return session or None if not found."""
    return state.sessions.get(session_id)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/start",
    response_model=ApiResponse[dict],
    summary="Start a new dynamic trip session",
)
def start_trip_endpoint(request: StartTripRequest) -> ApiResponse[dict]:
    """
    Initialize a new trip session from the given origin airport.

    Returns a session_id that must be included in all subsequent requests.
    The traveler starts at origin with full budget and time available.
    """
    if state.graph is None:
        return ApiResponse(data=None, error="Graph not loaded. Call GET /graph/load first.")

    if not state.graph.has_node(request.origin):
        return ApiResponse(data=None, error=f"Airport '{request.origin}' not found.")

    try:
        trip_state = start_trip(
            graph=state.graph,
            origin=request.origin,
            initial_budget=request.initial_budget,
            time_hours=request.time_hours,
        )
    except (KeyError, ValueError) as exc:
        return ApiResponse(data=None, error=str(exc))

    # Register the session in shared state
    state.sessions[trip_state.session_id] = trip_state

    return ApiResponse(
        data={
            "session_id": trip_state.session_id,
            "current_airport": trip_state.current_airport,
            "budget_remaining": trip_state.budget_remaining,
            "time_remaining_hours": trip_state.time_remaining_hours,
            "visited": trip_state.visited,
        },
        error=None,
    )


@router.get(
    "/flights",
    response_model=ApiResponse[list[dict]],
    summary="Get available flights from current position",
)
def available_flights(session_id: str) -> ApiResponse[list[dict]]:
    """
    Return all flights the traveler can take from their current airport.

    Filters by remaining budget, time, subsidized-km cap, and visited nodes.
    Each option includes all aircraft choices and a recommended (cheapest) one.
    """
    if state.graph is None:
        return ApiResponse(data=None, error="Graph not loaded.")

    trip_state = _get_session(session_id)
    if trip_state is None:
        return ApiResponse(data=None, error=f"Session '{session_id}' not found.")

    if not trip_state.is_active:
        return ApiResponse(data=None, error="This trip session has ended.")

    options = get_available_flights(state.graph, trip_state)
    return ApiResponse(data=options, error=None)


@router.post(
    "/fly",
    response_model=ApiResponse[dict],
    summary="Fly to a destination airport",
)
def fly_endpoint(request: FlyRequest) -> ApiResponse[dict]:
    """
    Move the traveler to the chosen destination using the chosen aircraft.

    Deducts cost and time, records the segment, and auto-applies any
    mandatory lodging or meal charges triggered by the elapsed time.
    """
    if state.graph is None:
        return ApiResponse(data=None, error="Graph not loaded.")

    trip_state = _get_session(request.session_id)
    if trip_state is None:
        return ApiResponse(data=None, error=f"Session '{request.session_id}' not found.")

    if not trip_state.is_active:
        return ApiResponse(data=None, error="This trip session has ended.")

    try:
        result = fly_to(
            graph=state.graph,
            state=trip_state,
            dest=request.dest,
            aircraft_type=request.aircraft_type,
        )
    except (KeyError, ValueError) as exc:
        return ApiResponse(data=None, error=str(exc))

    seg = result["segment"]
    return ApiResponse(
        data={
            "segment": {
                "origin": seg.origin,
                "dest": seg.dest,
                "aircraft_type": seg.aircraft_type,
                "distance_km": seg.distance_km,
                "flight_time_min": seg.flight_time_min,
                "cost_usd": seg.cost_usd,
                "cumulative_cost": seg.cumulative_cost,
                "cumulative_time_min": seg.cumulative_time_min,
            },
            "mandatory_events": result["mandatory_events"],
            "budget_remaining": result["budget_remaining"],
            "time_remaining_hours": result["time_remaining_hours"],
            "current_airport": result["current_airport"],
            "visited": trip_state.visited,
        },
        error=None,
    )


@router.get(
    "/activities",
    response_model=ApiResponse[list[dict]],
    summary="Get optional activities available at current airport",
)
def available_activities(session_id: str) -> ApiResponse[list[dict]]:
    """
    Return all optional activities at the traveler's current airport.

    Mandatory activities (lodging, food) are applied automatically and
    are not listed here.
    """
    if state.graph is None:
        return ApiResponse(data=None, error="Graph not loaded.")

    trip_state = _get_session(session_id)
    if trip_state is None:
        return ApiResponse(data=None, error=f"Session '{session_id}' not found.")

    if not trip_state.is_active:
        return ApiResponse(data=None, error="This trip session has ended.")

    activities = get_available_activities(state.graph, trip_state)
    return ApiResponse(data=activities, error=None)


@router.post(
    "/activity",
    response_model=ApiResponse[dict],
    summary="Perform an optional activity at the current airport",
)
def do_activity_endpoint(request: ActivityRequest) -> ApiResponse[dict]:
    """
    Perform the named optional activity, deducting cost and time.

    Returns updated budget and time after the activity.
    """
    if state.graph is None:
        return ApiResponse(data=None, error="Graph not loaded.")

    trip_state = _get_session(request.session_id)
    if trip_state is None:
        return ApiResponse(data=None, error=f"Session '{request.session_id}' not found.")

    if not trip_state.is_active:
        return ApiResponse(data=None, error="This trip session has ended.")

    try:
        result = do_activity(state.graph, trip_state, request.activity_name)
    except ValueError as exc:
        return ApiResponse(data=None, error=str(exc))

    return ApiResponse(data=result, error=None)


@router.get(
    "/jobs",
    response_model=ApiResponse[list[dict]],
    summary="Get available jobs (only offered when budget is low)",
)
def available_jobs(session_id: str) -> ApiResponse[list[dict]]:
    """
    Return temporary jobs available at the current airport.

    Jobs are only offered when the traveler's remaining budget falls below
    35% of the initial budget. Returns an empty list otherwise.
    """
    if state.graph is None:
        return ApiResponse(data=None, error="Graph not loaded.")

    trip_state = _get_session(session_id)
    if trip_state is None:
        return ApiResponse(data=None, error=f"Session '{session_id}' not found.")

    if not trip_state.is_active:
        return ApiResponse(data=None, error="This trip session has ended.")

    jobs = get_available_jobs(state.graph, trip_state)
    return ApiResponse(data=jobs, error=None)


@router.post(
    "/job",
    response_model=ApiResponse[dict],
    summary="Accept a temporary job and earn income",
)
def do_job_endpoint(request: JobRequest) -> ApiResponse[dict]:
    """
    Work the specified number of hours at the chosen job.

    Income is added to budget; time is deducted from trip time.
    Mandatory events (food/lodging) are auto-applied after work hours pass.
    """
    if state.graph is None:
        return ApiResponse(data=None, error="Graph not loaded.")

    trip_state = _get_session(request.session_id)
    if trip_state is None:
        return ApiResponse(data=None, error=f"Session '{request.session_id}' not found.")

    if not trip_state.is_active:
        return ApiResponse(data=None, error="This trip session has ended.")

    try:
        result = do_job(state.graph, trip_state, request.job_name, request.hours)
    except ValueError as exc:
        return ApiResponse(data=None, error=str(exc))

    return ApiResponse(data=result, error=None)


@router.get(
    "/suggest",
    response_model=ApiResponse[dict],
    summary="Get a Dijkstra-powered suggestion for the next destination",
)
def suggest_endpoint(session_id: str) -> ApiResponse[dict]:
    """
    Run Dijkstra from the current position to find the cheapest unvisited
    reachable airport, and return it as a suggestion with the full path.
    """
    if state.graph is None:
        return ApiResponse(data=None, error="Graph not loaded.")

    trip_state = _get_session(session_id)
    if trip_state is None:
        return ApiResponse(data=None, error=f"Session '{session_id}' not found.")

    if not trip_state.is_active:
        return ApiResponse(data=None, error="This trip session has ended.")

    suggestion = suggest_next_destination(state.graph, trip_state)
    return ApiResponse(data=suggestion, error=None)


@router.post(
    "/end",
    response_model=ApiResponse[dict],
    summary="End the current trip session",
)
def end_trip_endpoint(request: EndTripRequest) -> ApiResponse[dict]:
    """
    Close a trip session. After this call, the session is read-only.

    The full trip report can still be retrieved via GET /report/{session_id}.
    """
    trip_state = _get_session(request.session_id)
    if trip_state is None:
        return ApiResponse(data=None, error=f"Session '{request.session_id}' not found.")

    if not trip_state.is_active:
        return ApiResponse(data=None, error="Session is already ended.")

    end_trip(trip_state)

    return ApiResponse(
        data={
            "session_id": trip_state.session_id,
            "message": "Trip ended. Use GET /report/{session_id} for the full report.",
            "destinations_visited": len(trip_state.visited),
            "total_km": trip_state.total_km,
        },
        error=None,
    )