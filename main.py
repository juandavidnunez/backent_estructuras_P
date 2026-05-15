"""
SkyRoute Planner — FastAPI application entry point.

Registers all routers, configures CORS, and loads the graph at startup.
Run with: uvicorn main:app --reload
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import api.state as state
from api.router_events import router as events_router
from api.router_plan import router as plan_router
from api.router_report import router as report_router
from config import API_PREFIX, CORS_ORIGINS, JSON_NETWORK_PATH


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load the graph from disk when the server starts."""
    try:
        from features.loader import load_network
        state.graph = load_network(JSON_NETWORK_PATH)
        print(f"Graph loaded: {state.graph}")
    except Exception as exc:
        print(f"Warning: Could not load graph at startup: {exc}")
        print("Use GET /api/v1/graph/load to load it manually.")
    yield


app = FastAPI(
    title="SkyRoute Planner API",
    description="Backend for the SkyRoute Planner — Estructuras de Datos, Universidad de Caldas",
    version="1.0.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS — allow Vue.js frontend to connect
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Router registration
# ---------------------------------------------------------------------------

app.include_router(plan_router, prefix=f"{API_PREFIX}/plan", tags=["R2 — Planning"])
app.include_router(events_router, prefix=f"{API_PREFIX}/events", tags=["R4 — Interruptions"])
app.include_router(report_router, prefix=f"{API_PREFIX}/report", tags=["R5 — Reports"])


@app.get("/", tags=["Health"])
def root():
    """Health check endpoint."""
    return {"status": "ok", "message": "SkyRoute Planner API is running"}
