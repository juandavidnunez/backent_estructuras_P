"""
R5 — Trip report endpoints.

All routes are prefixed with /api/v1/report (registered in main.py).

Endpoints:
    GET /report/{session_id}          — Full trip report.
    GET /report/{session_id}/summary  — Totals only (lightweight).
"""

from fastapi import APIRouter

import api.state as state
from api.schemas import (
    ActivitySummaryResponse,
    ApiResponse,
    DestinationSummaryResponse,
    JobSummaryResponse,
    TripReportResponse,
    TripSegmentResponse,
    TripSummaryResponse,
)
from features.reporter import generate_report, generate_summary

router = APIRouter()


@router.get(
    "/{session_id}",
    response_model=ApiResponse[TripReportResponse],
    summary="Generate the full trip report for a session",
)
def get_report(session_id: str) -> ApiResponse[TripReportResponse]:
    """
    Build and return the complete trip report for the given session.

    Includes all destinations, flight segments, activities, jobs, and totals.
    The graph is passed to enrich destination data with airport names.
    """
    trip_state = state.sessions.get(session_id)
    if trip_state is None:
        return ApiResponse(data=None, error=f"Session '{session_id}' not found.")

    report = generate_report(state=trip_state, graph=state.graph)

    destinations = [
        DestinationSummaryResponse(
            iata_code=dest.iata_code,
            name=dest.name,
            city=dest.city,
            country=dest.country,
            stay_time_min=dest.stay_time_min,
            total_cost_usd=dest.total_cost_usd,
        )
        for dest in report.destinations
    ]

    segments = [
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
        for seg in report.segments
    ]

    activities = [
        ActivitySummaryResponse(
            name=act.name,
            activity_type=act.activity_type,
            duration_min=act.duration_min,
            cost_usd=act.cost_usd,
            airport_iata=act.airport_iata,
        )
        for act in report.activities
    ]

    jobs = [
        JobSummaryResponse(
            name=job.name,
            hours_worked=job.hours_worked,
            income_usd=job.income_usd,
            airport_iata=job.airport_iata,
        )
        for job in report.jobs
    ]

    return ApiResponse(
        data=TripReportResponse(
            session_id=report.session_id,
            destinations=destinations,
            segments=segments,
            activities=activities,
            jobs=jobs,
            initial_budget=report.initial_budget,
            total_spent=report.total_spent,
            total_earned=report.total_earned,
            final_balance=report.final_balance,
            total_time_hours=report.total_time_hours,
            total_distance_km=report.total_distance_km,
        ),
        error=None,
    )


@router.get(
    "/{session_id}/summary",
    response_model=ApiResponse[TripSummaryResponse],
    summary="Get a lightweight summary with totals only",
)
def get_summary(session_id: str) -> ApiResponse[TripSummaryResponse]:
    """Return only the financial and time totals for a session."""
    trip_state = state.sessions.get(session_id)
    if trip_state is None:
        return ApiResponse(data=None, error=f"Session '{session_id}' not found.")

    summary = generate_summary(trip_state)

    return ApiResponse(
        data=TripSummaryResponse(**summary),
        error=None,
    )
