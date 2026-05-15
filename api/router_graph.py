"""
R1 — Graph load and query endpoints.

All routes are prefixed with /api/v1/graph (registered in main.py).

Endpoints:
    GET  /load          — Load the JSON network from disk into memory.
    GET  /nodes         — List all airports with full data.
    GET  /nodes/{code}  — Get a single airport by IATA code.
    GET  /edges         — List all routes with computed costs and times.
    GET  /status        — Check if the graph is loaded and its statistics.
    POST /reload        — Force a reload of the JSON from disk.
"""

from fastapi import APIRouter

import api.state as state
from api.schemas import (
    ActivitySchema,
    AirportResponse,
    ApiResponse,
    GraphSummaryResponse,
    JobSchema,
    RouteResponse,
)
from config import DEFAULT_AIRCRAFT, JSON_NETWORK_PATH

router = APIRouter()


def _compute_costs_and_times(
    aircraft_types: list[str],
    distance_km: float,
    is_subsidized: bool,
) -> tuple[dict[str, float], dict[str, float]]:
    """
    Compute cost and time for each aircraft type on a given route.

    Args:
        aircraft_types: List of aircraft type names operating this route.
        distance_km: Route distance in kilometers.
        is_subsidized: True if the route has zero base cost.

    Returns:
        Tuple of (costs_by_aircraft, times_by_aircraft) dicts.
    """
    costs: dict[str, float] = {}
    times: dict[str, float] = {}

    for aircraft_type in aircraft_types:
        config = DEFAULT_AIRCRAFT.get(aircraft_type, DEFAULT_AIRCRAFT["Avión Comercial"])
        times[aircraft_type] = round(distance_km * config["time_per_km"], 2)

        if is_subsidized:
            costs[aircraft_type] = 0.0
        else:
            costs[aircraft_type] = round(distance_km * config["cost_per_km"], 2)

    return costs, times


def _airport_to_response(airport_id: str) -> AirportResponse:
    """
    Convert an Airport dataclass to its Pydantic response model.

    Args:
        airport_id: IATA code of the airport to convert.

    Returns:
        AirportResponse with all fields populated.
    """
    airport = state.graph.get_node(airport_id)

    return AirportResponse(
        id=airport.id,
        name=airport.name,
        city=airport.city,
        country=airport.country,
        timezone=airport.timezone,
        is_hub=airport.is_hub,
        lodging_cost=airport.lodging_cost,
        food_cost=airport.food_cost,
        activities=[
            ActivitySchema(
                name=act.name,
                type=act.type,
                duration_min=act.duration_min,
                cost_usd=act.cost_usd,
            )
            for act in airport.activities
        ],
        jobs=[
            JobSchema(
                name=job.name,
                hourly_rate=job.hourly_rate,
                max_hours=job.max_hours,
            )
            for job in airport.jobs
        ],
        airlines=airport.airlines,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/load",
    response_model=ApiResponse[GraphSummaryResponse],
    summary="Load the flight network from the JSON file into memory",
)
def load_graph() -> ApiResponse[GraphSummaryResponse]:
    """
    Read the JSON network file from disk and build the in-memory graph.

    Idempotent — calling it again replaces the existing graph.
    Returns a summary of the loaded network.
    """
    try:
        from features.loader import load_network
        state.graph = load_network(JSON_NETWORK_PATH)
    except FileNotFoundError:
        return ApiResponse(data=None, error=f"Network file not found: {JSON_NETWORK_PATH}")
    except ValueError as exc:
        return ApiResponse(data=None, error=f"Invalid network JSON: {exc}")
    except Exception as exc:
        return ApiResponse(data=None, error=f"Unexpected error loading graph: {exc}")

    return ApiResponse(
        data=GraphSummaryResponse(
            node_count=state.graph.node_count(),
            edge_count=state.graph.edge_count(),
            hub_count=state.graph.hub_count(),
            blocked_edge_count=len(state.graph.get_blocked_edges()),
        ),
        error=None,
    )


@router.get(
    "/status",
    response_model=ApiResponse[GraphSummaryResponse],
    summary="Check if the graph is loaded and return its statistics",
)
def graph_status() -> ApiResponse[GraphSummaryResponse]:
    """Return graph statistics, or an error if the graph is not loaded."""
    if state.graph is None:
        return ApiResponse(data=None, error="Graph not loaded. Call GET /graph/load first.")

    return ApiResponse(
        data=GraphSummaryResponse(
            node_count=state.graph.node_count(),
            edge_count=state.graph.edge_count(),
            hub_count=state.graph.hub_count(),
            blocked_edge_count=len(state.graph.get_blocked_edges()),
        ),
        error=None,
    )


@router.get(
    "/nodes",
    response_model=ApiResponse[list[AirportResponse]],
    summary="List all airports in the network",
)
def list_nodes() -> ApiResponse[list[AirportResponse]]:
    """Return the complete list of airports with all their metadata."""
    if state.graph is None:
        return ApiResponse(data=None, error="Graph not loaded. Call GET /graph/load first.")

    airports = [_airport_to_response(node_id) for node_id in state.graph.get_all_nodes()]
    return ApiResponse(data=airports, error=None)


@router.get(
    "/nodes/{iata_code}",
    response_model=ApiResponse[AirportResponse],
    summary="Get a single airport by its IATA code",
)
def get_node(iata_code: str) -> ApiResponse[AirportResponse]:
    """
    Return full data for a single airport.

    Returns 404-style error if the IATA code is not found in the graph.
    """
    if state.graph is None:
        return ApiResponse(data=None, error="Graph not loaded. Call GET /graph/load first.")

    if not state.graph.has_node(iata_code):
        return ApiResponse(data=None, error=f"Airport '{iata_code}' not found in graph.")

    return ApiResponse(data=_airport_to_response(iata_code), error=None)


@router.get(
    "/edges",
    response_model=ApiResponse[list[RouteResponse]],
    summary="List all flight routes with computed costs and times",
)
def list_edges() -> ApiResponse[list[RouteResponse]]:
    """
    Return all directed edges in the graph.

    For each route, costs and travel times are pre-computed for every
    aircraft type that operates that route, using the DEFAULT_AIRCRAFT
    configuration (overridable per the project spec).
    """
    if state.graph is None:
        return ApiResponse(data=None, error="Graph not loaded. Call GET /graph/load first.")

    routes: list[RouteResponse] = []

    for node_id in state.graph.get_all_nodes():
        # Use get_neighbors_all to include blocked edges in the listing
        for dest_id, route in state.graph.get_neighbors_all(node_id):
            costs, times = _compute_costs_and_times(
                aircraft_types=route.aircraft_types,
                distance_km=route.distance_km,
                is_subsidized=route.is_subsidized,
            )

            routes.append(
                RouteResponse(
                    origin=route.origin,
                    dest=route.dest,
                    distance_km=route.distance_km,
                    aircraft_types=route.aircraft_types,
                    base_cost=route.base_cost,
                    min_stay_min=route.min_stay_min,
                    is_subsidized=route.is_subsidized,
                    costs_by_aircraft=costs,
                    times_by_aircraft=times,
                )
            )

    return ApiResponse(data=routes, error=None)


@router.post(
    "/reload",
    response_model=ApiResponse[GraphSummaryResponse],
    summary="Force a reload of the network JSON from disk",
)
def reload_graph() -> ApiResponse[GraphSummaryResponse]:
    """
    Drop the current in-memory graph and reload it from the JSON file.

    All active sessions remain in memory but may become inconsistent
    if the network topology changes. Useful during development.
    """
    return load_graph()