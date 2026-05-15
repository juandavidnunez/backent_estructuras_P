"""
R4 — Route interruption endpoints.

All routes are prefixed with /api/v1/events (registered in main.py).

Endpoints:
    POST /block-route    — Block a route edge.
    POST /unblock-route  — Restore a blocked edge.
    POST /recalculate    — Recalculate itinerary from current position.
    GET  /blocked-routes — List all currently blocked edges.
"""

from fastapi import APIRouter

import api.state as state
from api.schemas import (
    ApiResponse,
    BlockedRouteItem,
    BlockRouteRequest,
    RecalculateRequest,
    RecalculateResponse,
    TripSegmentResponse,
    UnblockRouteRequest,
)
from features.interruptions import (
    block_route,
    get_blocked_routes,
    recalculate_after_block,
    unblock_route,
)

router = APIRouter()


@router.post(
    "/block-route",
    response_model=ApiResponse[dict],
    summary="Block a route edge, simulating an interruption",
)
def block_route_endpoint(request: BlockRouteRequest) -> ApiResponse[dict]:
    """
    Block the directed edge from origin to dest.

    If a session_id is provided, checks whether the traveler is currently
    in transit on this route and returns is_in_transit and redirect_to.
    """
    if state.graph is None:
        return ApiResponse(data=None, error="Graph not loaded.")

    # Retrieve active session if provided
    active_session = None
    if request.session_id:
        active_session = state.sessions.get(request.session_id)

    result = block_route(
        graph=state.graph,
        origin=request.origin,
        dest=request.dest,
        active_state=active_session,
    )

    if result.get("error"):
        return ApiResponse(data=None, error=result["error"])

    return ApiResponse(data=result, error=None)


@router.post(
    "/unblock-route",
    response_model=ApiResponse[dict],
    summary="Restore a previously blocked route",
)
def unblock_route_endpoint(request: UnblockRouteRequest) -> ApiResponse[dict]:
    """Remove the block from a previously blocked edge."""
    if state.graph is None:
        return ApiResponse(data=None, error="Graph not loaded.")

    result = unblock_route(graph=state.graph, origin=request.origin, dest=request.dest)

    if result.get("error"):
        return ApiResponse(data=None, error=result["error"])

    return ApiResponse(data=result, error=None)


@router.post(
    "/recalculate",
    response_model=ApiResponse[RecalculateResponse],
    summary="Recalculate the best available route after a block",
)
def recalculate_endpoint(request: RecalculateRequest) -> ApiResponse[RecalculateResponse]:
    """
    Run Dijkstra from current_node to final_destination on the current
    graph state (blocked edges are automatically excluded).

    Returns the new best route or an error if no path exists.
    """
    if state.graph is None:
        return ApiResponse(data=None, error="Graph not loaded.")

    if not state.graph.has_node(request.current_node):
        return ApiResponse(data=None, error=f"Node '{request.current_node}' not found.")

    if not state.graph.has_node(request.final_destination):
        return ApiResponse(data=None, error=f"Node '{request.final_destination}' not found.")

    result = recalculate_after_block(
        graph=state.graph,
        current_node=request.current_node,
        final_destination=request.final_destination,
    )

    segments_response = [
        TripSegmentResponse(
            origin=seg.origin,
            dest=seg.dest,
            aircraft_type=seg.aircraft_type,
            distance_km=seg.distance_km,
            flight_time_min=seg.flight_time_min,
            cost_usd=seg.cost_usd,
            cumulative_cost=seg.cumulative_cost,
            cumulative_time_min=seg.cumulative_time_min,
        )
        for seg in result["segments"]
    ]

    return ApiResponse(
        data=RecalculateResponse(
            found=result["found"],
            total_cost=result["total_cost"],
            path=result["path"],
            segments=segments_response,
            error=result["error"],
        ),
        error=None,
    )


@router.get(
    "/blocked-routes",
    response_model=ApiResponse[list[BlockedRouteItem]],
    summary="List all currently blocked route edges",
)
def list_blocked_routes() -> ApiResponse[list[BlockedRouteItem]]:
    """Return all edges currently marked as blocked in the graph."""
    if state.graph is None:
        return ApiResponse(data=None, error="Graph not loaded.")

    blocked = get_blocked_routes(state.graph)
    items = [BlockedRouteItem(origin=b["origin"], dest=b["dest"]) for b in blocked]
    return ApiResponse(data=items, error=None)
