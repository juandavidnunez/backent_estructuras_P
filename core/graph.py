"""
Graph data structure for SkyRoute Planner.

Implements a weighted directed graph using an adjacency list.
Nodes represent airports (Airport dataclass).
Edges represent flight routes (Route dataclass).

Adjacency list structure:
    _adj: dict[str, list[tuple[str, Route]]]
        key   -> origin airport IATA code
        value -> list of (dest_iata, Route) tuples

Blocked edges are stored separately in a set of (origin, dest) tuples
so they can be unblocked later without losing route data.
"""

from core.models import Airport, Route


class Graph:
    """
    Weighted directed graph with adjacency list representation.

    Supports node/edge CRUD, edge blocking (for R4 interruptions),
    and all traversal queries needed by Dijkstra and BFS/DFS.
    """

    def __init__(self) -> None:
        """Initialize an empty graph."""
        # Adjacency list: origin_id -> [(dest_id, Route), ...]
        self._adj: dict[str, list[tuple[str, Route]]] = {}

        # Node data store: airport_id -> Airport
        self._nodes: dict[str, Airport] = {}

        # Blocked edges: set of (origin_id, dest_id) tuples
        # Blocked edges are NOT removed from _adj; they are just skipped
        # during traversal. This allows unblocking without data loss.
        self._blocked: set[tuple[str, str]] = set()

    # ------------------------------------------------------------------
    # Node operations
    # ------------------------------------------------------------------

    def add_node(self, airport_id: str, data: Airport) -> None:
        """
        Add an airport node to the graph.

        If the node already exists its data is overwritten.

        Args:
            airport_id: IATA code used as the unique node identifier.
            data: Airport dataclass instance with all airport metadata.
        """
        self._nodes[airport_id] = data
        # Ensure the adjacency list entry exists even for isolated nodes
        if airport_id not in self._adj:
            self._adj[airport_id] = []

    def get_node(self, node_id: str) -> Airport:
        """
        Return the Airport data for a given node.

        Args:
            node_id: IATA code of the airport.

        Returns:
            Airport dataclass instance.

        Raises:
            KeyError: If node_id does not exist in the graph.
        """
        if node_id not in self._nodes:
            raise KeyError(f"Node '{node_id}' not found in graph")
        return self._nodes[node_id]

    def get_all_nodes(self) -> list[str]:
        """
        Return a list of all node IDs (IATA codes) in the graph.

        Returns:
            List of IATA code strings.
        """
        return list(self._nodes.keys())

    def has_node(self, node_id: str) -> bool:
        """
        Check whether a node exists in the graph.

        Args:
            node_id: IATA code to check.

        Returns:
            True if the node exists, False otherwise.
        """
        return node_id in self._nodes

    # ------------------------------------------------------------------
    # Edge operations
    # ------------------------------------------------------------------

    def add_edge(self, origin: str, dest: str, route: Route) -> None:
        """
        Add a directed edge from origin to dest.

        Both nodes must already exist. If an edge between the same
        origin and dest already exists it is replaced.

        Args:
            origin: IATA code of the departure airport.
            dest: IATA code of the arrival airport.
            route: Route dataclass instance describing the edge.

        Raises:
            KeyError: If origin or dest node does not exist.
        """
        if origin not in self._nodes:
            raise KeyError(f"Origin node '{origin}' not found")
        if dest not in self._nodes:
            raise KeyError(f"Destination node '{dest}' not found")

        # Remove existing edge between same pair if present (replace semantics)
        self._adj[origin] = [
            (d, r) for (d, r) in self._adj[origin] if d != dest
        ]
        self._adj[origin].append((dest, route))

    def remove_edge(self, origin: str, dest: str) -> None:
        """
        Permanently remove a directed edge from the graph.

        Also removes it from the blocked set if it was blocked.
        Use block_edge / unblock_edge for temporary interruptions (R4).

        Args:
            origin: IATA code of the departure airport.
            dest: IATA code of the arrival airport.
        """
        if origin in self._adj:
            self._adj[origin] = [
                (d, r) for (d, r) in self._adj[origin] if d != dest
            ]
        # Clean up blocked set as well
        self._blocked.discard((origin, dest))

    def get_neighbors(self, node_id: str) -> list[tuple[str, Route]]:
        """
        Return all reachable neighbors of a node, excluding blocked edges.

        This is the primary method used by Dijkstra and BFS/DFS during
        traversal. Blocked edges are silently skipped.

        Args:
            node_id: IATA code of the node whose neighbors are requested.

        Returns:
            List of (dest_id, Route) tuples for all non-blocked outgoing edges.

        Raises:
            KeyError: If node_id does not exist in the graph.
        """
        if node_id not in self._adj:
            raise KeyError(f"Node '{node_id}' not found in graph")

        # Filter out any edge that is currently blocked
        return [
            (dest, route)
            for (dest, route) in self._adj[node_id]
            if (node_id, dest) not in self._blocked
        ]

    def get_neighbors_all(self, node_id: str) -> list[tuple[str, Route]]:
        """
        Return ALL neighbors including blocked edges.

        Useful for reporting which edges exist regardless of block status.

        Args:
            node_id: IATA code of the node.

        Returns:
            List of (dest_id, Route) tuples including blocked edges.
        """
        if node_id not in self._adj:
            raise KeyError(f"Node '{node_id}' not found in graph")
        return list(self._adj[node_id])

    def has_edge(self, origin: str, dest: str) -> bool:
        """
        Check whether a directed edge exists (regardless of block status).

        Args:
            origin: IATA code of the departure airport.
            dest: IATA code of the arrival airport.

        Returns:
            True if the edge exists in the adjacency list.
        """
        if origin not in self._adj:
            return False
        return any(d == dest for (d, _) in self._adj[origin])

    # ------------------------------------------------------------------
    # Edge blocking (R4 — interruptions)
    # ------------------------------------------------------------------

    def block_edge(self, origin: str, dest: str) -> None:
        """
        Mark a directed edge as blocked without removing it from the graph.

        Blocked edges are invisible to get_neighbors(), so Dijkstra and
        BFS/DFS will not traverse them. The edge data is preserved so
        it can be restored with unblock_edge().

        Args:
            origin: IATA code of the departure airport.
            dest: IATA code of the arrival airport.

        Raises:
            KeyError: If the edge does not exist.
        """
        if not self.has_edge(origin, dest):
            raise KeyError(f"Edge '{origin}' -> '{dest}' does not exist")
        self._blocked.add((origin, dest))

    def unblock_edge(self, origin: str, dest: str) -> None:
        """
        Remove the block from a previously blocked edge.

        Args:
            origin: IATA code of the departure airport.
            dest: IATA code of the arrival airport.
        """
        self._blocked.discard((origin, dest))

    def get_blocked_edges(self) -> list[tuple[str, str]]:
        """
        Return a list of all currently blocked (origin, dest) pairs.

        Returns:
            List of (origin_id, dest_id) tuples.
        """
        return list(self._blocked)

    def is_edge_blocked(self, origin: str, dest: str) -> bool:
        """
        Check whether a specific edge is currently blocked.

        Args:
            origin: IATA code of the departure airport.
            dest: IATA code of the arrival airport.

        Returns:
            True if the edge is blocked.
        """
        return (origin, dest) in self._blocked

    # ------------------------------------------------------------------
    # Graph statistics
    # ------------------------------------------------------------------

    def node_count(self) -> int:
        """Return the total number of nodes in the graph."""
        return len(self._nodes)

    def edge_count(self) -> int:
        """Return the total number of edges (including blocked ones)."""
        return sum(len(neighbors) for neighbors in self._adj.values())

    def hub_count(self) -> int:
        """Return the number of hub airports in the graph."""
        return sum(1 for airport in self._nodes.values() if airport.is_hub)

    def __repr__(self) -> str:
        return (
            f"Graph(nodes={self.node_count()}, "
            f"edges={self.edge_count()}, "
            f"blocked={len(self._blocked)})"
        )
