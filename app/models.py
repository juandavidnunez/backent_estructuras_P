"""Pydantic schemas — mirror the frontend TypeScript types."""
from __future__ import annotations

from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    data: T | None = None
    error: str | None = None


# ── R1 ──────────────────────────────────────────────────────────────────────

class ActivitySchema(BaseModel):
    name: str
    type: Literal["obligatoria", "opcional"]
    duration_min: int
    cost_usd: float


class JobSchema(BaseModel):
    name: str
    hourly_rate: float
    max_hours: int


class Airport(BaseModel):
    id: str
    name: str
    city: str
    country: str
    timezone: str
    is_hub: bool
    lodging_cost: float
    food_cost: float
    activities: list[ActivitySchema]
    jobs: list[JobSchema]
    airlines: list[str]


class Route(BaseModel):
    origin: str
    dest: str
    distance_km: float
    aircraft_types: list[str]
    base_cost: float
    min_stay_min: int
    is_subsidized: bool
    costs_by_aircraft: dict[str, float]
    times_by_aircraft: dict[str, float]


class GraphSummary(BaseModel):
    node_count: int
    edge_count: int
    hub_count: int
    blocked_edge_count: int


# ── R2 ──────────────────────────────────────────────────────────────────────

class TripSegment(BaseModel):
    origin: str
    dest: str
    aircraft_type: str
    distance_km: float
    flight_time_min: float
    cost_usd: float
    cumulative_cost: float
    cumulative_time_min: float


class ItineraryRequest(BaseModel):
    origin: str
    budget_usd: float
    time_hours: float
    aircraft_types: list[str]
    include_secondary: bool = True


class ItineraryResponse(BaseModel):
    by_budget: list[TripSegment]
    by_time: list[TripSegment]


class BestRouteRequest(BaseModel):
    origin: str
    destination: str
    criteria: list[str]
    aircraft_types: list[str]
    include_secondary: bool = True


class BestRouteResult(BaseModel):
    total: float | None
    path: list[str]
    segments: list[TripSegment]


class BestRouteResponse(BaseModel):
    results: dict[str, BestRouteResult]


# ── R3 ──────────────────────────────────────────────────────────────────────

class StartSessionRequest(BaseModel):
    origin: str
    initial_budget: float
    time_hours: float


class SessionState(BaseModel):
    session_id: str
    current_airport: str
    budget_remaining: float
    time_remaining_hours: float
    visited: list[str]


class AircraftOption(BaseModel):
    aircraft_type: str
    cost_usd: float
    time_min: float


class FlightOption(BaseModel):
    dest: str
    distance_km: float
    is_subsidized: bool
    min_stay_min: int
    aircraft_options: list[AircraftOption]
    recommended_aircraft: AircraftOption


class ActivityOption(BaseModel):
    name: str
    type: str
    duration_min: int
    cost_usd: float
    can_afford: bool


class JobOption(BaseModel):
    name: str
    hourly_rate: float
    max_hours: int
    max_earnable_usd: float
    recommended_hours: int | None = None
    estimated_living_cost: float = 0.0
    estimated_net_income: float = 0.0
    is_recommended: bool = False
    recommendation_reason: str | None = None


class JobRecommendation(BaseModel):
    name: str
    hourly_rate: float
    recommended_hours: int
    estimated_income: float
    estimated_living_cost: float
    net_gain: float
    reason: str


class FlyRequest(BaseModel):
    session_id: str
    dest: str
    aircraft_type: str


class FlyResult(BaseModel):
    segment: TripSegment
    mandatory_events: list[str]
    budget_remaining: float
    time_remaining_hours: float
    current_airport: str
    visited: list[str]


class ActivityRequest(BaseModel):
    session_id: str
    activity_name: str


class ActivityResult(BaseModel):
    cost_usd: float
    budget_remaining: float
    time_remaining_hours: float


class JobRequest(BaseModel):
    session_id: str
    job_name: str
    hours: float


class JobResult(BaseModel):
    income_usd: float
    budget_remaining: float
    time_remaining_hours: float


class Suggestion(BaseModel):
    suggested_dest: str | None
    path: list[str]
    estimated_cost: float
    estimated_time_min: float
    needs_jobs: bool = False
    budget_deficit: float = 0.0
    cheapest_flight_cost: float = 0.0
    job_recommendations: list[JobRecommendation] = []


class EndSessionRequest(BaseModel):
    session_id: str


# ── R4 ──────────────────────────────────────────────────────────────────────

class BlockRouteRequest(BaseModel):
    origin: str
    dest: str
    session_id: str | None = None


class UnblockRouteRequest(BaseModel):
    origin: str
    dest: str


class RecalculateRequest(BaseModel):
    current_node: str
    final_destination: str


class BlockedRoute(BaseModel):
    origin: str
    dest: str


class RecalculateResponse(BaseModel):
    found: bool
    total_cost: float | None
    path: list[str]
    segments: list[TripSegment]
    error: str | None = None


# ── R5 ──────────────────────────────────────────────────────────────────────

class DestinationSummary(BaseModel):
    iata_code: str
    name: str
    city: str
    country: str
    stay_time_min: float
    total_cost_usd: float


class ActivitySummary(BaseModel):
    name: str
    activity_type: str
    duration_min: int
    cost_usd: float
    airport_iata: str


class JobSummary(BaseModel):
    name: str
    hours_worked: float
    income_usd: float
    airport_iata: str


class TripReport(BaseModel):
    session_id: str
    destinations: list[DestinationSummary]
    segments: list[TripSegment]
    activities: list[ActivitySummary]
    jobs: list[JobSummary]
    initial_budget: float
    total_spent: float
    total_earned: float
    final_balance: float
    total_time_hours: float
    total_distance_km: float


class TripSummary(BaseModel):
    session_id: str
    initial_budget: float
    total_spent: float
    total_earned: float
    final_balance: float
    total_time_hours: float
    destinations_visited: int
