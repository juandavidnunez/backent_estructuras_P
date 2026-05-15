"""
Global configuration constants for SkyRoute Planner.

ALL numeric constants used in business logic must be defined here.
No magic numbers are allowed in features/, api/, or core/ modules.
"""

import os

# ---------------------------------------------------------------------------
# Data file paths
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

JSON_NETWORK_PATH: str = os.path.join(BASE_DIR, "data", "network.json")
JSON_TEST_PATH: str = os.path.join(BASE_DIR, "data", "network_test.json")

# ---------------------------------------------------------------------------
# Aircraft default values
# Keys match the aircraft type names used in the JSON.
# ---------------------------------------------------------------------------

DEFAULT_AIRCRAFT: dict = {
    "Avión Comercial": {
        "cost_per_km": 0.18,   # USD per km
        "time_per_km": 0.7,    # minutes per km
    },
    "Avión Regional": {
        "cost_per_km": 0.25,
        "time_per_km": 1.1,
    },
    "Hélice": {
        "cost_per_km": 0.12,
        "time_per_km": 2.5,
    },
}

# ---------------------------------------------------------------------------
# Dynamic planning thresholds (R3)
# ---------------------------------------------------------------------------

# Budget percentage below which the system offers jobs to the traveler
DEFAULT_BUDGET_MIN_PERCENT: float = 0.35

# Hours between mandatory lodging events
DEFAULT_LODGING_INTERVAL_HOURS: float = 20.0

# Hours between mandatory meal events
DEFAULT_FOOD_INTERVAL_HOURS: float = 8.0

# Maximum fraction of total distance that can be on subsidized routes
MAX_SUBSIDIZED_DISTANCE_PERCENT: float = 0.20

# ---------------------------------------------------------------------------
# API configuration
# ---------------------------------------------------------------------------

API_PREFIX: str = "/api/v1"

# CORS origins allowed (Vue.js frontend default dev server)
CORS_ORIGINS: list[str] = [
    "http://localhost:5173",
    "http://localhost:3000",
    "http://localhost:8080",
]
