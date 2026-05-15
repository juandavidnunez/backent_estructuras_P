"""
Shared in-memory application state for SkyRoute Planner.

This module holds the single Graph instance and all active trip sessions.
It is imported (never instantiated) by every router and feature module
that needs access to the live graph or a session.

Design rationale:
    FastAPI does not have a built-in dependency-injection container for
    mutable singletons. Using a module-level variable is the idiomatic
    Python pattern for sharing state across routers without a database.
    The graph is loaded once at startup (see main.py lifespan) and then
    read-only during normal operation, except for R4 edge blocking which
    mutates the graph in place.

Attributes:
    graph: The single Graph instance loaded from the JSON file.
           None until load_network() is called successfully.
    sessions: Dict mapping session_id -> ItineraryState for all active
              dynamic planning sessions (R3). Sessions persist in memory
              for the lifetime of the server process.
"""

from typing import Optional

from core.graph import Graph
from core.models import ItineraryState

# ---------------------------------------------------------------------------
# Singleton graph — loaded at startup, shared across all requests
# ---------------------------------------------------------------------------

graph: Optional[Graph] = None

# ---------------------------------------------------------------------------
# Active dynamic sessions — keyed by session_id (R3)
# ---------------------------------------------------------------------------

sessions: dict[str, ItineraryState] = {}