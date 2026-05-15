"""
R2 — Basic itinerary planning endpoints.

All routes are prefixed with /api/v1/plan (registered in main.py).

Endpoints:
    POST /itinerary   — Two itineraries: max destinations by budget and by time.
    POST /best-route  — Best route between two airports by one or more criteria.
"""

from fastapi import APIRouter

import api.state as state
from api.schemas import (
    ApiResponse,
    BestRouteRequest,
    BestRouteResponse,
    ItineraryResponse,
    PlanRequest,
    TripSegmentResponse,
)
from features.planner import (
    find_best_route,
    plan_max_destinations_by_budget,
    plan_max_destinations_by_time,
)

router = APIRouter()


def _segment_to_response(segment) -> TripSegmentResponse:
    """Convert a TripSegment dataclass to its Pydantic response model."""
    return TripSegmentResponse(
        origin=segment.origin,
        dest=segment.dest,
        aircraft_type=segment.aircraft_type,
        distance_km=segment.distance_km,
        flight_time_min=segment.flight_time_min,
        cost_usd=segment.cost_usd,
        cumulative_cost=segment.cumulative_cost,
        cumulative_time_min=segment.cumulative_time_min,
    )


@router.post(
    "/itinerary",
    response_model=ApiResponse[ItineraryResponse],
    summary="Plan two itineraries: max destinations by budget and by time",
)
def plan_itinerary(request: PlanRequest) -> ApiResponse[ItineraryResponse]:
    """
    Given an origin, budget, and available time, return two itinerary alternatives:
    - by_budget: maximizes destinations without exceeding budget_usd.
    - by_time: maximizes destinations without exceeding time_hours.

    Both itineraries use BFS and respect the include_secondary flag.
    """
    if state.graph is None:
        return ApiResponse(data=None, error="Graph not loaded. Call GET /graph/load first.")

    if not state.graph.has_node(request.origin):
        return ApiResponse(data=None, error=f"Airport '{request.origin}' not found in graph.")

    try:
        budget_segments = plan_max_destinations_by_budget(
            graph=state.graph,
            origin=request.origin,
            budget_usd=request.budget_usd,
            aircraft_types=request.aircraft_types,
            include_secondary=request.include_secondary,
        )

        time_segments = plan_max_destinations_by_time(
            graph=state.graph,
            origin=request.origin,
            time_hours=request.time_hours,
            aircraft_types=request.aircraft_types,
            include_secondary=request.include_secondary,
        )

        return ApiResponse(
            data=ItineraryResponse(
                by_budget=[_segment_to_response(s) for s in budget_segments],
                by_time=[_segment_to_response(s) for s in time_segments],
            ),
            error=None,
        )

    except Exception as exc:
        return ApiResponse(data=None, error=str(exc))


@router.post(
    "/best-route",
    response_model=ApiResponse[BestRouteResponse],
    summary="Find the best route between two airports by one or more criteria",
)
def best_route(request: BestRouteRequest) -> ApiResponse[BestRouteResponse]:
    """
    Calculate the optimal route from origin to destination.

    One Dijkstra run is performed per criterion. Valid criteria:
    'distance', 'time', 'cost'. Multiple criteria return multiple routes.
    """
    if state.graph is None:
        return ApiResponse(data=None, error="Graph not loaded. Call GET /graph/load first.")

    if not state.graph.has_node(request.origin):
        return ApiResponse(data=None, error=f"Airport '{request.origin}' not found.")

    if not state.graph.has_node(request.destination):
        return ApiResponse(data=None, error=f"Airport '{request.destination}' not found.")

    if not request.criteria:
        return ApiResponse(data=None, error="At least one criterion must be provided.")

    valid_criteria = {"distance", "time", "cost"}
    invalid = [c for c in request.criteria if c not in valid_criteria]
    if invalid:
        return ApiResponse(
            data=None,
            error=f"Invalid criteria: {invalid}. Valid options: {list(valid_criteria)}"
        )

    try:
        raw_results = find_best_route(
            graph=state.graph,
            origin=request.origin,
            destination=request.destination,
            criteria=request.criteria,
            include_secondary=request.include_secondary,
        )

        # Serialize segments inside each criterion result
        serialized: dict[str, dict] = {}
        for criterion, result in raw_results.items():
            serialized[criterion] = {
                "total": result["total"],
                "path": result["path"],
                "segments": [_segment_to_response(s).__dict__ for s in result["segments"]],
            }

        return ApiResponse(data=BestRouteResponse(results=serialized), error=None)

    except ValueError as exc:
        return ApiResponse(data=None, error=str(exc))
    except Exception as exc:
        return ApiResponse(data=None, error=str(exc))
