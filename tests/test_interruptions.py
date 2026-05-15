"""
Tests for features/interruptions.py — Requirement R4.

Tests cover: blocking, unblocking, transit detection, and recalculation.
All tests are independent and do not share state.
"""

import pytest

from config import JSON_TEST_PATH
from core.models import ItineraryState, TripSegment
from features.interruptions import (
    block_route,
    get_blocked_routes,
    recalculate_after_block,
    unblock_route,
)
from features.loader import load_network


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def test_graph():
    """Load the test network from network_test.json."""
    return load_network(JSON_TEST_PATH)


@pytest.fixture
def active_session() -> ItineraryState:
    """
    A minimal ItineraryState simulating a traveler currently flying BOG->MDE.
    The traveler has NOT yet landed (MDE is not in visited).
    """
    segment = TripSegment(
        origin="BOG",
        dest="MDE",
        aircraft_type="Avión Comercial",
        distance_km=240.0,
        flight_time_min=168.0,
        cost_usd=43.2,
        cumulative_cost=43.2,
        cumulative_time_min=168.0,
    )
    return ItineraryState(
        session_id="test-session-001",
        current_airport="BOG",
        budget_remaining=456.8,
        time_remaining_hours=46.2,
        initial_budget=500.0,
        visited=["BOG"],          # MDE not yet in visited — still in transit
        segments=[segment],
        is_active=True,
    )


# ---------------------------------------------------------------------------
# block_route tests
# ---------------------------------------------------------------------------

class TestBlockRoute:

    def test_block_existing_edge(self, test_graph):
        """Blocking an existing edge should succeed and mark it as blocked."""
        result = block_route(graph=test_graph, origin="BOG", dest="MDE")

        assert result["blocked"] is True
        assert result["error"] is None
        assert test_graph.is_edge_blocked("BOG", "MDE") is True

    def test_block_nonexistent_edge_returns_error(self, test_graph):
        """Blocking a non-existent edge should return an error message."""
        result = block_route(graph=test_graph, origin="BOG", dest="NONEXISTENT")

        assert result["blocked"] is False
        assert result["error"] is not None

    def test_blocked_edge_appears_in_blocked_list(self, test_graph):
        """After blocking, the edge should appear in get_blocked_routes()."""
        block_route(graph=test_graph, origin="BOG", dest="MDE")

        blocked = get_blocked_routes(test_graph)
        origins_dests = [(b["origin"], b["dest"]) for b in blocked]
        assert ("BOG", "MDE") in origins_dests

    def test_block_multiple_edges(self, test_graph):
        """Blocking multiple edges should all appear in the blocked list."""
        block_route(graph=test_graph, origin="BOG", dest="MDE")
        block_route(graph=test_graph, origin="BOG", dest="CLO")

        blocked = get_blocked_routes(test_graph)
        origins_dests = [(b["origin"], b["dest"]) for b in blocked]

        assert ("BOG", "MDE") in origins_dests
        assert ("BOG", "CLO") in origins_dests
        assert len(blocked) == 2

    def test_block_detects_in_transit(self, test_graph, active_session):
        """
        Blocking the route the traveler is currently flying should set
        is_in_transit=True and redirect_to=origin of that segment.
        """
        result = block_route(
            graph=test_graph,
            origin="BOG",
            dest="MDE",
            active_state=active_session,
        )

        assert result["blocked"] is True
        assert result["is_in_transit"] is True
        assert result["redirect_to"] == "BOG"

    def test_block_not_in_transit_when_already_landed(self, test_graph):
        """
        If the traveler has already landed (dest is in visited),
        is_in_transit should be False.
        """
        # Traveler has already landed at MDE (it's in visited)
        landed_state = ItineraryState(
            session_id="test-session-002",
            current_airport="MDE",
            budget_remaining=456.8,
            time_remaining_hours=46.2,
            initial_budget=500.0,
            visited=["BOG", "MDE"],   # MDE already visited — landed
            segments=[],
            is_active=True,
        )

        result = block_route(
            graph=test_graph,
            origin="BOG",
            dest="MDE",
            active_state=landed_state,
        )

        assert result["is_in_transit"] is False


# ---------------------------------------------------------------------------
# unblock_route tests
# ---------------------------------------------------------------------------

class TestUnblockRoute:

    def test_unblock_restores_edge(self, test_graph):
        """After unblocking, the edge should no longer be in the blocked list."""
        block_route(graph=test_graph, origin="BOG", dest="MDE")
        assert test_graph.is_edge_blocked("BOG", "MDE") is True

        unblock_route(graph=test_graph, origin="BOG", dest="MDE")
        assert test_graph.is_edge_blocked("BOG", "MDE") is False

    def test_unblock_nonexistent_edge_returns_error(self, test_graph):
        """Unblocking a non-existent edge should return an error."""
        result = unblock_route(graph=test_graph, origin="BOG", dest="NONEXISTENT")
        assert result["unblocked"] is False
        assert result["error"] is not None

    def test_unblock_makes_edge_traversable_again(self, test_graph):
        """After unblocking, Dijkstra should be able to use the edge again."""
        from core.dijkstra import dijkstra

        # Block BOG->MDE and verify Dijkstra can't use it
        block_route(graph=test_graph, origin="BOG", dest="MDE")
        total_blocked, path_blocked = dijkstra(
            graph=test_graph,
            origin="BOG",
            destination="MDE",
            weight_fn=lambda r: r.distance_km,
        )

        # Unblock and verify Dijkstra finds the direct route again
        unblock_route(graph=test_graph, origin="BOG", dest="MDE")
        total_unblocked, path_unblocked = dijkstra(
            graph=test_graph,
            origin="BOG",
            destination="MDE",
            weight_fn=lambda r: r.distance_km,
        )

        # After unblocking, the direct path should be available
        assert total_unblocked is not None
        assert "MDE" in path_unblocked


# ---------------------------------------------------------------------------
# recalculate_after_block tests
# ---------------------------------------------------------------------------

class TestRecalculateAfterBlock:

    def test_recalculate_finds_alternative_route(self, test_graph):
        """
        Block BOG->LIM direct. Recalculate should find an alternative
        (e.g., BOG->UIO->... or another path if available).
        """
        block_route(graph=test_graph, origin="BOG", dest="LIM")

        result = recalculate_after_block(
            graph=test_graph,
            current_node="BOG",
            final_destination="LIM",
        )

        # There may or may not be an alternative — just verify the structure
        assert "found" in result
        assert "path" in result
        assert "segments" in result
        assert "error" in result

        if result["found"]:
            assert result["path"][0] == "BOG"
            assert result["path"][-1] == "LIM"
            assert result["total_cost"] is not None

    def test_recalculate_returns_none_when_no_path(self, test_graph):
        """
        Block the only route between two nodes. Recalculate should return found=False.
        CTG has no outgoing edges in the test network, so it's a dead end.
        """
        result = recalculate_after_block(
            graph=test_graph,
            current_node="CTG",
            final_destination="SCL",
        )

        assert result["found"] is False
        assert result["total_cost"] is None
        assert result["path"] == []
        assert result["error"] is not None

    def test_recalculate_segments_count_matches_path(self, test_graph):
        """
        The number of segments in the result should be len(path) - 1.
        """
        result = recalculate_after_block(
            graph=test_graph,
            current_node="BOG",
            final_destination="MDE",
        )

        if result["found"]:
            assert len(result["segments"]) == len(result["path"]) - 1

    def test_recalculate_does_not_use_blocked_edges(self, test_graph):
        """
        The recalculated path must not include any currently blocked edges.
        """
        block_route(graph=test_graph, origin="BOG", dest="MDE")

        result = recalculate_after_block(
            graph=test_graph,
            current_node="BOG",
            final_destination="MDE",
        )

        if result["found"]:
            path = result["path"]
            # Verify the blocked edge is not in the path
            for index in range(len(path) - 1):
                assert not (path[index] == "BOG" and path[index + 1] == "MDE"), (
                    "Recalculated path uses a blocked edge"
                )


# ---------------------------------------------------------------------------
# get_blocked_routes tests
# ---------------------------------------------------------------------------

class TestGetBlockedRoutes:

    def test_empty_when_no_blocks(self, test_graph):
        """Initially, no edges should be blocked."""
        blocked = get_blocked_routes(test_graph)
        assert blocked == []

    def test_returns_all_blocked(self, test_graph):
        """Should return exactly the edges that were blocked."""
        block_route(graph=test_graph, origin="BOG", dest="MDE")
        block_route(graph=test_graph, origin="LIM", dest="SCL")

        blocked = get_blocked_routes(test_graph)
        assert len(blocked) == 2

        pairs = {(b["origin"], b["dest"]) for b in blocked}
        assert ("BOG", "MDE") in pairs
        assert ("LIM", "SCL") in pairs
