"""
Shared in-memory state for the SkyRoute API.

The Graph is loaded once at startup and reused across all requests.
Dynamic trip sessions are stored in a dict keyed by session_id.

This module is the single source of truth for mutable server state.
"""

from typing import Optional

from core.graph import Graph
from core.models import ItineraryState

# Singleton graph instance — loaded by /graph/load or at startup
graph: Optional[Graph] = None

# Active dynamic trip sessions: session_id -> ItineraryState
sessions: dict[str, ItineraryState] = {}
