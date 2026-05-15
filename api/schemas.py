"""
Pydantic v2 schemas for all API request and response models.

All endpoints return the ApiResponse[T] wrapper:
    Success: { "data": <T>, "error": null }
    Failure: { "data": null, "error": "message" }
"""

from typing import Generic, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Generic API wrapper
# ---------------------------------------------------------------------------

class ApiResponse(BaseModel, Generic[T]):
    """
    Standard response envelope for all endpoints.

    Attributes:
        data: The response payload on success, None on error.
        error: Error message on failure, None on success.
    """
    data: Optional[T] = None
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# R1 — Graph schemas
# ---------------------------------------------------------------------------

class ActivitySchema(BaseModel):
    name: str
    type: str
    duration_min: int
    cost_usd: float


class JobSchema(BaseModel):
    name: str
    hourly_rate: float
    max_hours: int


class AirportResponse(BaseModel):
    id: str
    name: str
    city: str
    country: str
    timezone: str
    is_hub: bool
    lodging_cost: float
    food_cost: float
    activities: list[ActivitySchema] = []
    jobs: list[JobSchema] = []
    airlines: list[str] = []


class RouteResponse(BaseModel):
    origin: str
    dest: str
    distance_km: float
    aircraft_types: list[str]
    base_cost: float
    min_stay_min: int
    is_subsidized: bool
    # Computed costs per aircraft type
    costs_by_aircraft: dict[str, float] = {}
    times_by_aircraft: dict[str, float] = {}


class GraphSummaryResponse(BaseModel):
    node_count: int
    edge_count: int
    hub_count: int
    blocked_edge_count: int


# ---------------------------------------------------------------------------
# R2 — Planning schemas
# ---------------------------------------------------------------------------

class PlanRequest(BaseModel):
    """Request body for POST /plan/itinerary"""
    origin: str = Field(..., description="IATA code of the starting airport")
    budget_usd: float = Field(..., gt=0, description="Maximum budget in USD")
    time_hours: float = Field(..., gt=0, description="Maximum trip time in hours")
    aircraft_types: list[str] = Field(
        default=["Avión Comercial", "Avión Regional", "Hélice"],
        description="Allowed aircraft types"
    )
    include_secondary: bool = Field(
        default=True,
        description="Whether to include non-hub airports"
    )


class BestRouteRequest(BaseModel):
    """Request body for POST /plan/best-route"""
    origin: str = Field(..., description="IATA code of the starting airport")
    destination: str = Field(..., description="IATA code of the target airport")
    criteria: list[str] = Field(
        ...,
        description="Optimization criteria: 'distance', 'time', 'cost'"
    )
    aircraft_types: list[str] = Field(
        default=["Avión Comercial", "Avión Regional", "Hélice"]
    )
    include_secondary: bool = True


class TripSegmentResponse(BaseModel):
    origin: str
    dest: str
    aircraft_type: str
    distance_km: float
    flight_time_min: float
    cost_usd: float
    cumulative_cost: float
    cumulative_time_min: float


class ItineraryResponse(BaseModel):
    by_budget: list[TripSegmentResponse]
    by_time: list[TripSegmentResponse]


class BestRouteResponse(BaseModel):
    """One entry per criterion requested."""
    results: dict[str, dict]


# ---------------------------------------------------------------------------
# R4 — Events / interruptions schemas
# ---------------------------------------------------------------------------

class BlockRouteRequest(BaseModel):
    origin: str = Field(..., description="IATA code of the route origin")
    dest: str = Field(..., description="IATA code of the route destination")
    session_id: Optional[str] = Field(
        default=None,
        description="Active session ID to check for in-transit traveler"
    )


class UnblockRouteRequest(BaseModel):
    origin: str
    dest: str


class RecalculateRequest(BaseModel):
    current_node: str = Field(..., description="IATA code of traveler's current position")
    final_destination: str = Field(..., description="IATA code of intended destination")


class BlockedRouteItem(BaseModel):
    origin: str
    dest: str


class RecalculateResponse(BaseModel):
    found: bool
    total_cost: Optional[float]
    path: list[str]
    segments: list[TripSegmentResponse]
    error: Optional[str]


# ---------------------------------------------------------------------------
# R5 — Report schemas
# ---------------------------------------------------------------------------

class DestinationSummaryResponse(BaseModel):
    iata_code: str
    name: str
    city: str
    country: str
    stay_time_min: float
    total_cost_usd: float


class ActivitySummaryResponse(BaseModel):
    name: str
    activity_type: str
    duration_min: int
    cost_usd: float
    airport_iata: str


class JobSummaryResponse(BaseModel):
    name: str
    hours_worked: float
    income_usd: float
    airport_iata: str


class TripReportResponse(BaseModel):
    session_id: str
    destinations: list[DestinationSummaryResponse]
    segments: list[TripSegmentResponse]
    activities: list[ActivitySummaryResponse]
    jobs: list[JobSummaryResponse]
    initial_budget: float
    total_spent: float
    total_earned: float
    final_balance: float
    total_time_hours: float
    total_distance_km: float


class TripSummaryResponse(BaseModel):
    session_id: str
    initial_budget: float
    total_spent: float
    total_earned: float
    final_balance: float
    total_time_hours: float
    destinations_visited: int
