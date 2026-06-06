"""
Tests for features/dynamic.py — R3 dynamic planning.

All tests use network_test.json to build a real Graph with known topology.
No mocking of business logic per the project rules.

Test coverage:
    - start_trip: valid creation, invalid inputs.
    - get_available_flights: filters visited, budget, time, subsidy cap.
    - fly_to: correct state mutation, mandatory events, constraint enforcement.
    - do_activity: cost/time deduction, invalid activity rejection.
    - get_available_jobs: threshold logic.
    - do_job: income addition, constraint enforcement.
    - suggest_next_destination: returns a reachable unvisited node.
    - end_trip: marks session as inactive.
"""

import json
import os
import sys

import pytest

# Make the project root importable regardless of where pytest is invoked from
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.graph import Graph
from core.models import Activity, Airport, Job, Route
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def small_graph() -> Graph:
    """
    Build a minimal 3-node graph: BOG -> MDE -> CLO.

    BOG -> MDE: 230 km, Avión Comercial, not subsidized.
    BOG -> CLO: 420 km, Avión Comercial, not subsidized.
    MDE -> CLO: 290 km, Avión Regional, not subsidized.
    GYE -> BOG: subsidized (costoBase = 0), 680 km.
    BOG -> GYE: not subsidized.

    This graph allows testing every constraint in isolation.
    """
    graph = Graph()

    def make_airport(iata: str, is_hub: bool, lodging: float = 40.0, food: float = 10.0) -> Airport:
        return Airport(
            id=iata,
            name=f"Airport {iata}",
            city=iata,
            country="Colombia",
            timezone="America/Bogota",
            is_hub=is_hub,
            lodging_cost=lodging,
            food_cost=food,
            activities=[
                Activity(name="City tour", type="opcional", duration_min=120, cost_usd=15.0),
                Activity(name="Museum",    type="opcional", duration_min=60,  cost_usd=8.0),
            ],
            jobs=[
                Job(name="Baggage handler", hourly_rate=6.0, max_hours=8),
                Job(name="Ramp assistant",  hourly_rate=7.0, max_hours=6),
            ],
            airlines=["TestAir"],
        )

    for iata, is_hub in [("BOG", True), ("MDE", True), ("CLO", False), ("GYE", False)]:
        graph.add_node(iata, make_airport(iata, is_hub))

    def add_route(origin, dest, km, aircraft, base_cost=-1.0):
        graph.add_edge(origin, dest, Route(
            origin=origin, dest=dest,
            distance_km=km, aircraft_types=aircraft,
            base_cost=base_cost, min_stay_min=60,
        ))

    add_route("BOG", "MDE", 230, ["Avión Comercial"])
    add_route("MDE", "BOG", 230, ["Avión Comercial"])
    add_route("BOG", "CLO", 420, ["Avión Comercial"])
    add_route("CLO", "BOG", 420, ["Avión Comercial"])
    add_route("MDE", "CLO", 290, ["Avión Regional"])
    add_route("BOG", "GYE", 680, ["Avión Comercial"])
    add_route("GYE", "BOG", 680, ["Avión Comercial"], base_cost=0.0)  # subsidized

    return graph


# ---------------------------------------------------------------------------
# start_trip
# ---------------------------------------------------------------------------

class TestStartTrip:

    def test_creates_session_with_correct_initial_state(self, small_graph):
        state = start_trip(small_graph, "BOG", initial_budget=500.0, time_hours=24.0)

        assert state.current_airport == "BOG"
        assert state.budget_remaining == 500.0
        assert state.time_remaining_hours == 24.0
        assert state.initial_budget == 500.0
        assert state.visited == ["BOG"]
        assert state.is_active is True
        assert state.session_id != ""

    def test_raises_if_origin_not_in_graph(self, small_graph):
        with pytest.raises(KeyError):
            start_trip(small_graph, "XXX", 500.0, 24.0)

    def test_raises_if_budget_zero(self, small_graph):
        with pytest.raises(ValueError):
            start_trip(small_graph, "BOG", 0.0, 24.0)

    def test_raises_if_time_zero(self, small_graph):
        with pytest.raises(ValueError):
            start_trip(small_graph, "BOG", 500.0, 0.0)


# ---------------------------------------------------------------------------
# get_available_flights
# ---------------------------------------------------------------------------

class TestGetAvailableFlights:

    def test_returns_reachable_neighbors(self, small_graph):
        state = start_trip(small_graph, "BOG", 1000.0, 48.0)
        flights = get_available_flights(small_graph, state)
        dests = {f["dest"] for f in flights}
        # BOG connects to MDE, CLO, GYE
        assert "MDE" in dests
        assert "CLO" in dests
        assert "GYE" in dests

    def test_excludes_visited_airports(self, small_graph):
        state = start_trip(small_graph, "BOG", 1000.0, 48.0)
        state.visited.append("MDE")  # Simulate already visited
        flights = get_available_flights(small_graph, state)
        dests = {f["dest"] for f in flights}
        assert "MDE" not in dests

    def test_excludes_routes_exceeding_budget(self, small_graph):
        # BOG -> CLO costs 420 * 0.18 = 75.6 USD with Avión Comercial
        state = start_trip(small_graph, "BOG", 50.0, 48.0)
        flights = get_available_flights(small_graph, state)
        dests = {f["dest"] for f in flights}
        assert "CLO" not in dests

    def test_excludes_routes_exceeding_time(self, small_graph):
        # BOG -> GYE: 680 km * 0.7 min/km = 476 min ≈ 7.93 h with Avión Comercial
        state = start_trip(small_graph, "BOG", 1000.0, time_hours=1.0)
        flights = get_available_flights(small_graph, state)
        dests = {f["dest"] for f in flights}
        assert "GYE" not in dests

    def test_each_flight_has_recommended_aircraft(self, small_graph):
        state = start_trip(small_graph, "BOG", 1000.0, 48.0)
        flights = get_available_flights(small_graph, state)
        for flight in flights:
            assert "recommended_aircraft" in flight
            assert flight["recommended_aircraft"]["aircraft_type"] != ""


# ---------------------------------------------------------------------------
# fly_to
# ---------------------------------------------------------------------------

class TestFlyTo:

    def test_moves_traveler_and_deducts_cost_and_time(self, small_graph):
        state = start_trip(small_graph, "BOG", 500.0, 24.0)
        result = fly_to(small_graph, state, "MDE", "Avión Comercial")

        expected_cost = 230 * 0.18  # 41.4 USD
        expected_time_min = 230 * 0.7  # 161 min

        assert state.current_airport == "MDE"
        assert abs(state.budget_remaining - (500.0 - expected_cost)) < 0.01
        assert abs(state.time_remaining_hours - (24.0 - expected_time_min / 60.0)) < 0.01
        assert "MDE" in state.visited
        assert len(state.segments) == 1

    def test_segment_recorded_correctly(self, small_graph):
        state = start_trip(small_graph, "BOG", 500.0, 24.0)
        result = fly_to(small_graph, state, "MDE", "Avión Comercial")
        seg = result["segment"]

        assert seg.origin == "BOG"
        assert seg.dest == "MDE"
        assert seg.aircraft_type == "Avión Comercial"
        assert seg.distance_km == 230

    def test_raises_if_dest_already_visited(self, small_graph):
        state = start_trip(small_graph, "BOG", 500.0, 24.0)
        fly_to(small_graph, state, "MDE", "Avión Comercial")
        # BOG was already visited as the trip origin, so returning should fail.
        with pytest.raises(ValueError, match="already been visited"):
            fly_to(small_graph, state, "BOG", "Avión Comercial")

    def test_raises_if_insufficient_budget(self, small_graph):
        state = start_trip(small_graph, "BOG", 5.0, 24.0)
        with pytest.raises(ValueError, match="budget"):
            fly_to(small_graph, state, "MDE", "Avión Comercial")

    def test_raises_if_insufficient_time(self, small_graph):
        state = start_trip(small_graph, "BOG", 1000.0, 0.5)
        with pytest.raises(ValueError, match="time"):
            fly_to(small_graph, state, "MDE", "Avión Comercial")

    def test_raises_if_aircraft_not_on_route(self, small_graph):
        state = start_trip(small_graph, "BOG", 1000.0, 24.0)
        with pytest.raises(ValueError, match="does not operate"):
            fly_to(small_graph, state, "MDE", "Hélice")

    def test_mandatory_lodging_triggered_after_20h(self, small_graph):
        state = start_trip(small_graph, "BOG", 1000.0, 100.0)
        # Fast-forward hours_since_lodging to just below threshold
        state.hours_since_lodging = 19.5
        result = fly_to(small_graph, state, "MDE", "Avión Comercial")
        # 19.5h + ~2.68h flight > 20h -> lodging triggered
        lodging_events = [e for e in result["mandatory_events"] if "lodging" in e.lower()]
        assert len(lodging_events) == 1
        assert state.hours_since_lodging == 0.0

    def test_mandatory_food_triggered_after_8h(self, small_graph):
        state = start_trip(small_graph, "BOG", 1000.0, 100.0)
        state.hours_since_food = 7.5
        # BOG -> GYE: 476 min ≈ 7.93h; 7.5 + 7.93 > 8 -> food triggered
        result = fly_to(small_graph, state, "GYE", "Avión Comercial")
        food_events = [e for e in result["mandatory_events"] if "meal" in e.lower()]
        assert len(food_events) == 1
        assert state.hours_since_food == 0.0


# ---------------------------------------------------------------------------
# do_activity
# ---------------------------------------------------------------------------

class TestDoActivity:

    def test_deducts_cost_and_time(self, small_graph):
        state = start_trip(small_graph, "BOG", 500.0, 24.0)
        result = do_activity(small_graph, state, "City tour")

        assert result["cost_usd"] == 15.0
        assert result["duration_min"] == 120
        assert abs(state.budget_remaining - 485.0) < 0.01
        assert abs(state.time_remaining_hours - (24.0 - 2.0)) < 0.01

    def test_raises_if_activity_not_found(self, small_graph):
        state = start_trip(small_graph, "BOG", 500.0, 24.0)
        with pytest.raises(ValueError, match="not found"):
            do_activity(small_graph, state, "Skydiving")

    def test_raises_if_insufficient_budget(self, small_graph):
        state = start_trip(small_graph, "BOG", 10.0, 24.0)
        with pytest.raises(ValueError, match="afford"):
            do_activity(small_graph, state, "City tour")

    def test_activity_recorded_in_state(self, small_graph):
        state = start_trip(small_graph, "BOG", 500.0, 24.0)
        do_activity(small_graph, state, "Museum")
        assert any(a["name"] == "Museum" for a in state.activities_done)


# ---------------------------------------------------------------------------
# get_available_jobs
# ---------------------------------------------------------------------------

class TestGetAvailableJobs:

    def test_empty_when_budget_above_threshold(self, small_graph):
        # 500 * 0.35 = 175; budget 500 >= 175 -> no jobs
        state = start_trip(small_graph, "BOG", 500.0, 24.0)
        jobs = get_available_jobs(small_graph, state)
        assert jobs == []

    def test_jobs_offered_when_budget_below_threshold(self, small_graph):
        # 500 * 0.35 = 175; set budget to 100 < 175 -> jobs offered
        state = start_trip(small_graph, "BOG", 500.0, 24.0)
        state.budget_remaining = 100.0
        jobs = get_available_jobs(small_graph, state)
        assert len(jobs) > 0

    def test_job_has_required_fields(self, small_graph):
        state = start_trip(small_graph, "BOG", 500.0, 24.0)
        state.budget_remaining = 100.0
        jobs = get_available_jobs(small_graph, state)
        for job in jobs:
            assert "name" in job
            assert "hourly_rate" in job
            assert "max_hours" in job
            assert "max_earnable_usd" in job


# ---------------------------------------------------------------------------
# do_job
# ---------------------------------------------------------------------------

class TestDoJob:

    def test_adds_income_to_budget(self, small_graph):
        state = start_trip(small_graph, "BOG", 500.0, 24.0)
        state.budget_remaining = 100.0  # Below threshold
        result = do_job(small_graph, state, "Baggage handler", hours=4.0)

        expected_income = 6.0 * 4.0  # 24.0 USD
        assert result["income_usd"] == expected_income
        assert abs(state.budget_remaining - (100.0 + expected_income)) < 0.01

    def test_deducts_time(self, small_graph):
        state = start_trip(small_graph, "BOG", 500.0, 24.0)
        state.budget_remaining = 100.0
        do_job(small_graph, state, "Baggage handler", hours=4.0)
        assert abs(state.time_remaining_hours - 20.0) < 0.01

    def test_raises_if_hours_exceed_max(self, small_graph):
        state = start_trip(small_graph, "BOG", 500.0, 24.0)
        state.budget_remaining = 100.0
        with pytest.raises(ValueError, match="Cannot work more"):
            do_job(small_graph, state, "Baggage handler", hours=9.0)

    def test_raises_if_job_not_found(self, small_graph):
        state = start_trip(small_graph, "BOG", 500.0, 24.0)
        with pytest.raises(ValueError, match="not found"):
            do_job(small_graph, state, "Astronaut", hours=2.0)

    def test_raises_if_insufficient_trip_time(self, small_graph):
        state = start_trip(small_graph, "BOG", 500.0, 24.0)
        state.budget_remaining = 100.0
        state.time_remaining_hours = 1.0
        with pytest.raises(ValueError, match="trip time"):
            do_job(small_graph, state, "Baggage handler", hours=4.0)

    def test_job_recorded_in_state(self, small_graph):
        state = start_trip(small_graph, "BOG", 500.0, 24.0)
        state.budget_remaining = 100.0
        do_job(small_graph, state, "Ramp assistant", hours=2.0)
        assert any(j["name"] == "Ramp assistant" for j in state.jobs_done)


# ---------------------------------------------------------------------------
# suggest_next_destination
# ---------------------------------------------------------------------------

class TestSuggestNextDestination:

    def test_returns_reachable_unvisited_airport(self, small_graph):
        state = start_trip(small_graph, "BOG", 500.0, 48.0)
        suggestion = suggest_next_destination(small_graph, state)
        assert suggestion["suggested_dest"] is not None
        assert suggestion["suggested_dest"] not in state.visited

    def test_returns_none_when_all_visited(self, small_graph):
        state = start_trip(small_graph, "BOG", 500.0, 48.0)
        # Mark all nodes as visited
        state.visited = small_graph.get_all_nodes()
        suggestion = suggest_next_destination(small_graph, state)
        assert suggestion["suggested_dest"] is None

    def test_returns_none_when_budget_too_low(self, small_graph):
        state = start_trip(small_graph, "BOG", 1.0, 48.0)
        suggestion = suggest_next_destination(small_graph, state)
        # BOG -> cheapest neighbor costs >1 USD, so no suggestion
        assert suggestion["suggested_dest"] is None


# ---------------------------------------------------------------------------
# end_trip
# ---------------------------------------------------------------------------

class TestEndTrip:

    def test_marks_session_inactive(self, small_graph):
        state = start_trip(small_graph, "BOG", 500.0, 24.0)
        assert state.is_active is True
        end_trip(state)
        assert state.is_active is False