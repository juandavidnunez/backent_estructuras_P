"""
Tests for core/graph.py, core/dijkstra.py, and core/bfs_dfs.py.

Each test is independent: no shared state between tests.
Tests use small graphs with known truth values so results can be
verified manually without ambiguity.
"""

import pytest

from core.bfs_dfs import bfs_max_coverage_by_budget, bfs_max_coverage_by_time
from core.dijkstra import dijkstra, multi_dijkstra
from core.graph import Graph
from core.models import Airport, Route


# ---------------------------------------------------------------------------
# Fixtures — reusable small graphs
# ---------------------------------------------------------------------------

def make_airport(iata: str, is_hub: bool = False) -> Airport:
    """Helper: create a minimal Airport dataclass for testing."""
    return Airport(
        id=iata,
        name=f"Airport {iata}",
        city=f"City {iata}",
        country="TestCountry",
        timezone="UTC",
        is_hub=is_hub,
        lodging_cost=30.0,
        food_cost=8.0,
    )


def make_route(origin: str, dest: str, distance_km: float, base_cost: float = -1.0) -> Route:
    """Helper: create a minimal Route dataclass for testing."""
    return Route(
        origin=origin,
        dest=dest,
        distance_km=distance_km,
        aircraft_types=["Avión Comercial"],
        base_cost=base_cost,
        min_stay_min=60,
    )


@pytest.fixture
def triangle_graph() -> Graph:
    """
    Triangle graph: A -> B -> C, A -> C
    Distances: A-B=100, B-C=100, A-C=250
    Cheapest path A->C: A->B->C (200 km) not A->C (250 km)
    """
    graph = Graph()
    for iata in ["A", "B", "C"]:
        graph.add_node(iata, make_airport(iata))

    graph.add_edge("A", "B", make_route("A", "B", 100.0))
    graph.add_edge("B", "C", make_route("B", "C", 100.0))
    graph.add_edge("A", "C", make_route("A", "C", 250.0))
    return graph


@pytest.fixture
def five_node_graph() -> Graph:
    """
    Five-node graph for coverage tests.
    A(hub) -> B -> C -> D -> E
    A -> C (direct, expensive)
    """
    graph = Graph()
    graph.add_node("A", make_airport("A", is_hub=True))
    graph.add_node("B", make_airport("B"))
    graph.add_node("C", make_airport("C"))
    graph.add_node("D", make_airport("D"))
    graph.add_node("E", make_airport("E"))

    graph.add_edge("A", "B", make_route("A", "B", 100.0))
    graph.add_edge("B", "C", make_route("B", "C", 100.0))
    graph.add_edge("C", "D", make_route("C", "D", 100.0))
    graph.add_edge("D", "E", make_route("D", "E", 100.0))
    graph.add_edge("A", "C", make_route("A", "C", 500.0))
    return graph


@pytest.fixture
def disconnected_graph() -> Graph:
    """Two isolated components: {A, B} and {C, D}."""
    graph = Graph()
    for iata in ["A", "B", "C", "D"]:
        graph.add_node(iata, make_airport(iata))

    graph.add_edge("A", "B", make_route("A", "B", 100.0))
    graph.add_edge("C", "D", make_route("C", "D", 100.0))
    return graph


# ---------------------------------------------------------------------------
# Graph structure tests
# ---------------------------------------------------------------------------

class TestGraphStructure:

    def test_add_nodes_and_get_all(self):
        """Adding 5 nodes should result in 5 nodes retrievable."""
        graph = Graph()
        for iata in ["BOG", "MDE", "CLO", "CTG", "LIM"]:
            graph.add_node(iata, make_airport(iata))

        assert graph.node_count() == 5
        assert set(graph.get_all_nodes()) == {"BOG", "MDE", "CLO", "CTG", "LIM"}

    def test_add_edges_and_get_neighbors(self):
        """Adding 7 edges and verifying get_neighbors returns correct neighbors."""
        graph = Graph()
        nodes = ["A", "B", "C", "D", "E"]
        for node in nodes:
            graph.add_node(node, make_airport(node))

        edges = [
            ("A", "B", 100), ("A", "C", 200), ("B", "C", 150),
            ("B", "D", 300), ("C", "D", 100), ("C", "E", 250), ("D", "E", 50),
        ]
        for origin, dest, dist in edges:
            graph.add_edge(origin, dest, make_route(origin, dest, dist))

        assert graph.edge_count() == 7

        # A should have neighbors B and C
        neighbor_ids = {dest for dest, _ in graph.get_neighbors("A")}
        assert neighbor_ids == {"B", "C"}

        # D should have only E as neighbor
        neighbor_ids = {dest for dest, _ in graph.get_neighbors("D")}
        assert neighbor_ids == {"E"}

    def test_has_node_and_has_edge(self):
        """has_node and has_edge return correct booleans."""
        graph = Graph()
        graph.add_node("X", make_airport("X"))
        graph.add_node("Y", make_airport("Y"))
        graph.add_edge("X", "Y", make_route("X", "Y", 100.0))

        assert graph.has_node("X") is True
        assert graph.has_node("Z") is False
        assert graph.has_edge("X", "Y") is True
        assert graph.has_edge("Y", "X") is False  # Directed graph

    def test_remove_edge(self):
        """Removing an edge should make it disappear from neighbors."""
        graph = Graph()
        graph.add_node("A", make_airport("A"))
        graph.add_node("B", make_airport("B"))
        graph.add_edge("A", "B", make_route("A", "B", 100.0))

        assert graph.has_edge("A", "B") is True
        graph.remove_edge("A", "B")
        assert graph.has_edge("A", "B") is False

    def test_get_node_raises_on_missing(self):
        """get_node should raise KeyError for non-existent nodes."""
        graph = Graph()
        with pytest.raises(KeyError):
            graph.get_node("NONEXISTENT")

    def test_add_node_missing_raises_on_add_edge(self):
        """add_edge should raise KeyError if origin or dest node doesn't exist."""
        graph = Graph()
        graph.add_node("A", make_airport("A"))

        with pytest.raises(KeyError):
            graph.add_edge("A", "MISSING", make_route("A", "MISSING", 100.0))


# ---------------------------------------------------------------------------
# Edge blocking tests (R4)
# ---------------------------------------------------------------------------

class TestEdgeBlocking:

    def test_block_edge_hides_from_neighbors(self):
        """A blocked edge should not appear in get_neighbors()."""
        graph = Graph()
        graph.add_node("A", make_airport("A"))
        graph.add_node("B", make_airport("B"))
        graph.add_edge("A", "B", make_route("A", "B", 100.0))

        graph.block_edge("A", "B")

        # get_neighbors excludes blocked edges
        neighbors = graph.get_neighbors("A")
        assert len(neighbors) == 0

        # get_neighbors_all still shows it
        all_neighbors = graph.get_neighbors_all("A")
        assert len(all_neighbors) == 1

    def test_unblock_edge_restores_neighbor(self):
        """Unblocking an edge should make it visible in get_neighbors() again."""
        graph = Graph()
        graph.add_node("A", make_airport("A"))
        graph.add_node("B", make_airport("B"))
        graph.add_edge("A", "B", make_route("A", "B", 100.0))

        graph.block_edge("A", "B")
        graph.unblock_edge("A", "B")

        neighbors = graph.get_neighbors("A")
        assert len(neighbors) == 1

    def test_get_blocked_edges(self):
        """get_blocked_edges should return all currently blocked pairs."""
        graph = Graph()
        for iata in ["A", "B", "C"]:
            graph.add_node(iata, make_airport(iata))
        graph.add_edge("A", "B", make_route("A", "B", 100.0))
        graph.add_edge("A", "C", make_route("A", "C", 200.0))

        graph.block_edge("A", "B")
        graph.block_edge("A", "C")

        blocked = graph.get_blocked_edges()
        assert ("A", "B") in blocked
        assert ("A", "C") in blocked
        assert len(blocked) == 2

    def test_block_nonexistent_edge_raises(self):
        """Blocking an edge that doesn't exist should raise KeyError."""
        graph = Graph()
        graph.add_node("A", make_airport("A"))
        graph.add_node("B", make_airport("B"))

        with pytest.raises(KeyError):
            graph.block_edge("A", "B")


# ---------------------------------------------------------------------------
# Dijkstra tests
# ---------------------------------------------------------------------------

class TestDijkstra:

    def test_shortest_path_triangle(self, triangle_graph):
        """
        Triangle A-B-C: A->B=100, B->C=100, A->C=250.
        Shortest A->C by distance should be A->B->C (200), not A->C (250).
        """
        total, path = dijkstra(
            graph=triangle_graph,
            origin="A",
            destination="C",
            weight_fn=lambda route: route.distance_km,
        )

        assert total == pytest.approx(200.0)
        assert path == ["A", "B", "C"]

    def test_same_origin_destination(self, triangle_graph):
        """Dijkstra from A to A should return (0.0, ['A'])."""
        total, path = dijkstra(
            graph=triangle_graph,
            origin="A",
            destination="A",
            weight_fn=lambda route: route.distance_km,
        )

        assert total == pytest.approx(0.0)
        assert path == ["A"]

    def test_disconnected_graph_returns_none(self, disconnected_graph):
        """Dijkstra from A to C (different component) should return (None, [])."""
        total, path = dijkstra(
            graph=disconnected_graph,
            origin="A",
            destination="C",
            weight_fn=lambda route: route.distance_km,
        )

        assert total is None
        assert path == []

    def test_dijkstra_respects_blocked_edge(self, triangle_graph):
        """
        Block A->B. The only remaining path A->C is the direct one (250 km).
        """
        triangle_graph.block_edge("A", "B")

        total, path = dijkstra(
            graph=triangle_graph,
            origin="A",
            destination="C",
            weight_fn=lambda route: route.distance_km,
        )

        # With A->B blocked, only A->C direct (250) is available
        assert total == pytest.approx(250.0)
        assert path == ["A", "C"]

    def test_dijkstra_blocked_all_paths_returns_none(self, triangle_graph):
        """Block all paths from A to C. Should return (None, [])."""
        triangle_graph.block_edge("A", "B")
        triangle_graph.block_edge("A", "C")

        total, path = dijkstra(
            graph=triangle_graph,
            origin="A",
            destination="C",
            weight_fn=lambda route: route.distance_km,
        )

        assert total is None
        assert path == []

    def test_multi_dijkstra_returns_all_criteria(self, triangle_graph):
        """multi_dijkstra should return a result for each criterion provided."""
        aircraft_config = {"Avión Comercial": {"cost_per_km": 0.18, "time_per_km": 0.7}}

        results = multi_dijkstra(
            graph=triangle_graph,
            origin="A",
            destination="C",
            weight_fns={
                "distance": lambda r: r.distance_km,
                "cost": lambda r: r.distance_km * 0.18,
                "time": lambda r: r.distance_km * 0.7,
            },
        )

        assert "distance" in results
        assert "cost" in results
        assert "time" in results

        # All three should find the same optimal path (A->B->C)
        for criterion in ["distance", "cost", "time"]:
            assert results[criterion]["path"] == ["A", "B", "C"]


# ---------------------------------------------------------------------------
# BFS coverage tests
# ---------------------------------------------------------------------------

class TestBFSCoverage:

    def test_bfs_budget_does_not_exceed_limit(self, five_node_graph):
        """
        BFS with budget=50 USD. At 0.18 USD/km, each 100km hop costs 18 USD.
        Budget 50 allows at most 2 hops (36 USD). Should visit B and C.
        """
        aircraft_config = {"Avión Comercial": {"cost_per_km": 0.18, "time_per_km": 0.7}}

        segments = bfs_max_coverage_by_budget(
            graph=five_node_graph,
            origin="A",
            budget_usd=50.0,
            aircraft_config=aircraft_config,
        )

        total_cost = sum(seg.cost_usd for seg in segments)
        assert total_cost <= 50.0
        assert len(segments) >= 1  # At least one destination reached

    def test_bfs_budget_zero_subsidized_only(self):
        """With budget=0, only subsidized routes (cost=0) should be traversable."""
        graph = Graph()
        for iata in ["A", "B", "C"]:
            graph.add_node(iata, make_airport(iata))

        # B is subsidized (cost=0), C is not
        graph.add_edge("A", "B", make_route("A", "B", 100.0, base_cost=0.0))
        graph.add_edge("A", "C", make_route("A", "C", 100.0, base_cost=-1.0))

        aircraft_config = {"Avión Comercial": {"cost_per_km": 0.18, "time_per_km": 0.7}}

        segments = bfs_max_coverage_by_budget(
            graph=graph,
            origin="A",
            budget_usd=0.0,
            aircraft_config=aircraft_config,
        )

        # Only the subsidized route to B should be taken
        destinations = {seg.dest for seg in segments}
        assert "B" in destinations
        assert "C" not in destinations

    def test_bfs_time_does_not_exceed_limit(self, five_node_graph):
        """
        BFS with time_limit=2 hours (120 min). At 0.7 min/km, each 100km hop = 70 min.
        120 min allows at most 1 hop. Should visit only B.
        """
        aircraft_config = {"Avión Comercial": {"cost_per_km": 0.18, "time_per_km": 0.7}}

        segments = bfs_max_coverage_by_time(
            graph=five_node_graph,
            origin="A",
            time_limit_hours=2.0,
            aircraft_config=aircraft_config,
        )

        total_time = sum(seg.flight_time_min for seg in segments)
        assert total_time <= 120.0  # 2 hours in minutes

    def test_bfs_isolated_origin_returns_empty(self):
        """BFS from an isolated node (no outgoing edges) should return []."""
        graph = Graph()
        graph.add_node("ALONE", make_airport("ALONE"))

        aircraft_config = {"Avión Comercial": {"cost_per_km": 0.18, "time_per_km": 0.7}}

        segments = bfs_max_coverage_by_budget(
            graph=graph,
            origin="ALONE",
            budget_usd=1000.0,
            aircraft_config=aircraft_config,
        )

        assert segments == []

    def test_bfs_exclude_secondary_airports(self, five_node_graph):
        """
        With include_secondary=False, only hub airports should appear in results.
        In five_node_graph, only A is a hub. So no destinations should be reached.
        """
        aircraft_config = {"Avión Comercial": {"cost_per_km": 0.18, "time_per_km": 0.7}}

        segments = bfs_max_coverage_by_budget(
            graph=five_node_graph,
            origin="A",
            budget_usd=1000.0,
            aircraft_config=aircraft_config,
            include_secondary=False,
        )

        # All neighbors of A are non-hubs, so nothing should be reachable
        assert segments == []
