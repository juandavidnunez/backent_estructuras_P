"""
Tests for features/planner.py — Requirement R2.

Uses network_test.json (8 nodes) for integration tests.
All tests are independent and do not share state.
"""

import pytest

from config import DEFAULT_AIRCRAFT, JSON_TEST_PATH
from features.loader import load_network
from features.planner import (
    find_best_route,
    plan_max_destinations_by_budget,
    plan_max_destinations_by_time,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def test_graph():
    """Load the test network from network_test.json."""
    return load_network(JSON_TEST_PATH)


# ---------------------------------------------------------------------------
# plan_max_destinations_by_budget tests
# ---------------------------------------------------------------------------

class TestPlanByBudget:

    def test_budget_not_exceeded(self, test_graph):
        """
        The itinerary by budget must never exceed the given budget.
        """
        budget = 200.0
        segments = plan_max_destinations_by_budget(
            graph=test_graph,
            origin="BOG",
            budget_usd=budget,
        )

        total_cost = sum(seg.cost_usd for seg in segments)
        assert total_cost <= budget, (
            f"Total cost {total_cost:.2f} exceeds budget {budget}"
        )

    def test_cumulative_cost_is_monotonically_increasing(self, test_graph):
        """
        Each segment's cumulative_cost must be >= the previous one.
        """
        segments = plan_max_destinations_by_budget(
            graph=test_graph,
            origin="BOG",
            budget_usd=500.0,
        )

        for index in range(1, len(segments)):
            assert segments[index].cumulative_cost >= segments[index - 1].cumulative_cost

    def test_zero_budget_returns_empty_or_subsidized_only(self, test_graph):
        """
        With budget=0, only subsidized routes (cost=0) should be traversable.
        The test network has one subsidized route: GYE->UIO.
        Starting from BOG with 0 budget should return empty (no subsidized routes from BOG).
        """
        segments = plan_max_destinations_by_budget(
            graph=test_graph,
            origin="BOG",
            budget_usd=0.0,
        )

        total_cost = sum(seg.cost_usd for seg in segments)
        assert total_cost == pytest.approx(0.0)

    def test_no_repeated_airports(self, test_graph):
        """The traveler must not visit the same airport twice."""
        segments = plan_max_destinations_by_budget(
            graph=test_graph,
            origin="BOG",
            budget_usd=1000.0,
        )

        visited = [seg.dest for seg in segments]
        assert len(visited) == len(set(visited)), "Duplicate airports found in itinerary"

    def test_returns_list_of_trip_segments(self, test_graph):
        """Return type must be a list (possibly empty)."""
        result = plan_max_destinations_by_budget(
            graph=test_graph,
            origin="BOG",
            budget_usd=100.0,
        )
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# plan_max_destinations_by_time tests
# ---------------------------------------------------------------------------

class TestPlanByTime:

    def test_time_not_exceeded(self, test_graph):
        """
        The itinerary by time must never exceed the given time limit.
        """
        time_hours = 5.0
        time_limit_min = time_hours * 60

        segments = plan_max_destinations_by_time(
            graph=test_graph,
            origin="BOG",
            time_hours=time_hours,
        )

        total_time = sum(seg.flight_time_min for seg in segments)
        assert total_time <= time_limit_min, (
            f"Total time {total_time:.1f} min exceeds limit {time_limit_min} min"
        )

    def test_cumulative_time_is_monotonically_increasing(self, test_graph):
        """Each segment's cumulative_time_min must be >= the previous one."""
        segments = plan_max_destinations_by_time(
            graph=test_graph,
            origin="BOG",
            time_hours=20.0,
        )

        for index in range(1, len(segments)):
            assert segments[index].cumulative_time_min >= segments[index - 1].cumulative_time_min

    def test_no_repeated_airports(self, test_graph):
        """The traveler must not visit the same airport twice."""
        segments = plan_max_destinations_by_time(
            graph=test_graph,
            origin="BOG",
            time_hours=50.0,
        )

        visited = [seg.dest for seg in segments]
        assert len(visited) == len(set(visited))


# ---------------------------------------------------------------------------
# find_best_route tests
# ---------------------------------------------------------------------------

class TestFindBestRoute:

    def test_best_route_by_distance(self, test_graph):
        """
        Best route BOG->LIM by distance should return a valid path.
        Direct route is 1900 km; via UIO would be 720+? km — depends on graph.
        """
        results = find_best_route(
            graph=test_graph,
            origin="BOG",
            destination="LIM",
            criteria=["distance"],
        )

        assert "distance" in results
        assert results["distance"]["total"] is not None
        assert results["distance"]["path"][0] == "BOG"
        assert results["distance"]["path"][-1] == "LIM"

    def test_best_route_multiple_criteria(self, test_graph):
        """
        Requesting multiple criteria should return one result per criterion.
        """
        results = find_best_route(
            graph=test_graph,
            origin="BOG",
            destination="LIM",
            criteria=["distance", "time", "cost"],
        )

        assert len(results) == 3
        for criterion in ["distance", "time", "cost"]:
            assert criterion in results
            assert results[criterion]["path"] != [] or results[criterion]["total"] is None

    def test_best_route_invalid_criterion_raises(self, test_graph):
        """Passing an invalid criterion should raise ValueError."""
        with pytest.raises(ValueError):
            find_best_route(
                graph=test_graph,
                origin="BOG",
                destination="LIM",
                criteria=["invalid_criterion"],
            )

    def test_best_route_unreachable_destination(self, test_graph):
        """
        CTG has no outgoing routes in the test network (one-way only).
        BOG->CTG exists but CTG->LIM does not, so LIM is unreachable from CTG.
        """
        results = find_best_route(
            graph=test_graph,
            origin="CTG",
            destination="SCL",
            criteria=["distance"],
        )

        # CTG has no outgoing edges in test network, so SCL is unreachable
        assert results["distance"]["total"] is None
        assert results["distance"]["path"] == []

    def test_best_route_segments_match_path(self, test_graph):
        """
        The number of segments should be len(path) - 1.
        """
        results = find_best_route(
            graph=test_graph,
            origin="BOG",
            destination="MDE",
            criteria=["cost"],
        )

        path = results["cost"]["path"]
        segments = results["cost"]["segments"]

        if path:  # Only check if a path was found
            assert len(segments) == len(path) - 1
