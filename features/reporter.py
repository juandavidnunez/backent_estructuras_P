"""
Final trip report generation — Requirement R5.

Builds a structured TripReport from a completed or active ItineraryState.
The report includes all visited destinations, flight segments, activities,
jobs, and financial/time totals.

This module only reads data — it does NOT modify the ItineraryState.
"""

from dataclasses import dataclass, field
from typing import Optional

from core.graph import Graph
from core.models import ItineraryState, TripSegment


# ---------------------------------------------------------------------------
# Report dataclasses (output structures)
# ---------------------------------------------------------------------------

@dataclass
class DestinationSummary:
    """Summary of a single visited airport."""
    iata_code: str
    name: str
    city: str
    country: str
    stay_time_min: float        # Total time spent at this airport in minutes
    total_cost_usd: float       # Total money spent at this destination


@dataclass
class ActivitySummary:
    """Summary of a single activity performed during the trip."""
    name: str
    activity_type: str          # 'obligatoria' or 'opcional'
    duration_min: int
    cost_usd: float
    airport_iata: str


@dataclass
class JobSummary:
    """Summary of a single job taken during the trip."""
    name: str
    hours_worked: float
    income_usd: float
    airport_iata: str


@dataclass
class TripReport:
    """
    Complete report of a finished (or in-progress) trip.

    Attributes:
        session_id: Unique identifier of the trip session.
        destinations: Ordered list of visited airports with stay details.
        segments: Ordered list of flight legs flown.
        activities: All activities performed (mandatory and optional).
        jobs: All jobs taken during the trip.
        initial_budget: Budget the traveler started with in USD.
        total_spent: Total money spent (flights + activities) in USD.
        total_earned: Total money earned from jobs in USD.
        final_balance: initial_budget - total_spent + total_earned.
        total_time_hours: Total trip duration in hours.
        total_distance_km: Total distance flown in km.
    """
    session_id: str
    destinations: list[DestinationSummary] = field(default_factory=list)
    segments: list[TripSegment] = field(default_factory=list)
    activities: list[ActivitySummary] = field(default_factory=list)
    jobs: list[JobSummary] = field(default_factory=list)
    initial_budget: float = 0.0
    total_spent: float = 0.0
    total_earned: float = 0.0
    final_balance: float = 0.0
    total_time_hours: float = 0.0
    total_distance_km: float = 0.0


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def generate_report(
    state: ItineraryState,
    graph: Optional[Graph] = None,
) -> TripReport:
    """
    Build a TripReport from an ItineraryState.

    Computes all totals from the state's recorded segments, activities,
    and jobs. If a Graph is provided, airport names and cities are
    included in the destination summaries.

    Args:
        state: The ItineraryState to report on (active or finished).
        graph: Optional Graph instance for enriching destination data
               with airport names, cities, and countries.

    Returns:
        A fully populated TripReport dataclass.
    """
    report = TripReport(session_id=state.session_id)
    report.initial_budget = state.initial_budget
    report.segments = list(state.segments)

    # --- Flight totals ---
    total_flight_cost = sum(seg.cost_usd for seg in state.segments)
    total_flight_time_min = sum(seg.flight_time_min for seg in state.segments)
    total_distance_km = sum(seg.distance_km for seg in state.segments)

    report.total_distance_km = total_distance_km

    # --- Activities ---
    total_activity_cost = 0.0
    total_activity_time_min = 0.0

    for activity_record in state.activities_done:
        summary = ActivitySummary(
            name=activity_record.get("name", "Unknown"),
            activity_type=activity_record.get("type", "opcional"),
            duration_min=activity_record.get("duration_min", 0),
            cost_usd=activity_record.get("cost_usd", 0.0),
            airport_iata=activity_record.get("airport_iata", ""),
        )
        report.activities.append(summary)
        total_activity_cost += summary.cost_usd
        total_activity_time_min += summary.duration_min

    # --- Jobs ---
    total_earned = 0.0

    for job_record in state.jobs_done:
        summary = JobSummary(
            name=job_record.get("name", "Unknown"),
            hours_worked=job_record.get("hours_worked", 0.0),
            income_usd=job_record.get("income_usd", 0.0),
            airport_iata=job_record.get("airport_iata", ""),
        )
        report.jobs.append(summary)
        total_earned += summary.income_usd

    report.total_earned = total_earned

    # --- Totals ---
    report.total_spent = total_flight_cost + total_activity_cost
    report.final_balance = state.initial_budget - report.total_spent + total_earned
    report.total_time_hours = (total_flight_time_min + total_activity_time_min) / 60.0

    # --- Destination summaries ---
    # Build a map of airport -> cost spent there (activities + lodging/food)
    airport_costs: dict[str, float] = {}
    airport_times: dict[str, float] = {}

    for activity_record in state.activities_done:
        iata = activity_record.get("airport_iata", "")
        airport_costs[iata] = airport_costs.get(iata, 0.0) + activity_record.get("cost_usd", 0.0)
        airport_times[iata] = airport_times.get(iata, 0.0) + activity_record.get("duration_min", 0)

    for visited_iata in state.visited:
        # Enrich with graph data if available
        name = visited_iata
        city = ""
        country = ""

        if graph is not None and graph.has_node(visited_iata):
            airport = graph.get_node(visited_iata)
            name = airport.name
            city = airport.city
            country = airport.country

        destination = DestinationSummary(
            iata_code=visited_iata,
            name=name,
            city=city,
            country=country,
            stay_time_min=airport_times.get(visited_iata, 0.0),
            total_cost_usd=airport_costs.get(visited_iata, 0.0),
        )
        report.destinations.append(destination)

    return report


def generate_summary(state: ItineraryState) -> dict:
    """
    Generate a lightweight summary with only the financial and time totals.

    Useful for the /report/{session_id}/summary endpoint.

    Args:
        state: The ItineraryState to summarize.

    Returns:
        Dict with keys: session_id, initial_budget, total_spent,
        total_earned, final_balance, total_time_hours, destinations_visited.
    """
    total_flight_cost = sum(seg.cost_usd for seg in state.segments)
    total_activity_cost = sum(
        rec.get("cost_usd", 0.0) for rec in state.activities_done
    )
    total_earned = sum(rec.get("income_usd", 0.0) for rec in state.jobs_done)
    total_time_min = sum(seg.flight_time_min for seg in state.segments) + sum(
        rec.get("duration_min", 0) for rec in state.activities_done
    )
    total_spent = total_flight_cost + total_activity_cost

    return {
        "session_id": state.session_id,
        "initial_budget": state.initial_budget,
        "total_spent": round(total_spent, 2),
        "total_earned": round(total_earned, 2),
        "final_balance": round(state.initial_budget - total_spent + total_earned, 2),
        "total_time_hours": round(total_time_min / 60.0, 2),
        "destinations_visited": len(state.visited),
    }
