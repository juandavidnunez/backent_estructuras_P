"""FastAPI application — SkyRoute Planner backend."""
from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.models import (
    ActivityRequest,
    ApiResponse,
    BestRouteRequest,
    BlockRouteRequest,
    EndSessionRequest,
    FlyRequest,
    ItineraryRequest,
    JobRequest,
    RecalculateRequest,
    StartSessionRequest,
    UnblockRouteRequest,
)
from app.services import SkyRouteService

NETWORK_PATH = os.environ.get("NETWORK_JSON_PATH")
service = SkyRouteService(NETWORK_PATH)

app = FastAPI(title="SkyRoute Planner API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def ok(data):
    return {"data": data, "error": None}


def fail(msg: str, status: int = 400):
    raise HTTPException(status_code=status, detail={"data": None, "error": msg})


@app.exception_handler(HTTPException)
async def http_exc_handler(request, exc: HTTPException):
    from fastapi.responses import JSONResponse
    if isinstance(exc.detail, dict):
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(status_code=exc.status_code, content={"data": None, "error": str(exc.detail)})


@app.exception_handler(ValueError)
async def value_error_handler(request, exc: ValueError):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=400, content={"data": None, "error": str(exc)})


# ── R1 Graph ────────────────────────────────────────────────────────────────

@app.get("/api/v1/graph/load")
def graph_load():
    return ok(service.summary())


@app.get("/api/v1/graph/status")
def graph_status():
    return ok(service.summary())


@app.get("/api/v1/graph/nodes")
def graph_nodes():
    return ok(list(service.graph.airports.values()))


@app.get("/api/v1/graph/nodes/{node_id}")
def graph_node(node_id: str):
    ap = service.graph.airports.get(node_id)
    if not ap:
        fail(f"Airport {node_id} not found", 404)
    return ok(ap)


@app.get("/api/v1/graph/edges")
def graph_edges():
    return ok(service.graph.to_route_models())


@app.post("/api/v1/graph/reload")
def graph_reload():
    service.reload()
    return ok(service.summary())


# ── R2 Planning ─────────────────────────────────────────────────────────────

@app.post("/api/v1/plan/itinerary")
def plan_itinerary(body: ItineraryRequest):
    return ok(service.plan_itinerary(
        body.origin, body.budget_usd, body.time_hours,
        body.aircraft_types, body.include_secondary,
    ))


@app.post("/api/v1/plan/best-route")
def plan_best_route(body: BestRouteRequest):
    return ok(service.best_route(
        body.origin, body.destination, body.criteria,
        body.aircraft_types, body.include_secondary,
    ))


# ── R3 Dynamic ──────────────────────────────────────────────────────────────

@app.post("/api/v1/dynamic/start")
def dynamic_start(body: StartSessionRequest):
    return ok(service.start_session(body.origin, body.initial_budget, body.time_hours))


@app.get("/api/v1/dynamic/flights")
def dynamic_flights(session_id: str):
    return ok(service.get_flights(session_id))


@app.get("/api/v1/dynamic/activities")
def dynamic_activities(session_id: str):
    return ok(service.get_activities(session_id))


@app.get("/api/v1/dynamic/jobs")
def dynamic_jobs(session_id: str):
    return ok(service.get_jobs(session_id))


@app.get("/api/v1/dynamic/suggest")
def dynamic_suggest(session_id: str):
    return ok(service.get_suggestion(session_id))


@app.post("/api/v1/dynamic/fly")
def dynamic_fly(body: FlyRequest):
    return ok(service.fly(body.session_id, body.dest, body.aircraft_type))


@app.post("/api/v1/dynamic/activity")
def dynamic_activity(body: ActivityRequest):
    return ok(service.do_activity(body.session_id, body.activity_name))


@app.post("/api/v1/dynamic/job")
def dynamic_job(body: JobRequest):
    return ok(service.do_job(body.session_id, body.job_name, body.hours))


@app.post("/api/v1/dynamic/end")
def dynamic_end(body: EndSessionRequest):
    service.end_session(body.session_id)
    return ok({"ended": True})


# ── R4 Events ─────────────────────────────────────────────────────────────────

@app.post("/api/v1/events/block-route")
def events_block(body: BlockRouteRequest):
    result = service.block_route(body.origin, body.dest, body.session_id if hasattr(body, 'session_id') else None)
    return ok(result)


@app.post("/api/v1/events/unblock-route")
def events_unblock(body: UnblockRouteRequest):
    service.unblock_route(body.origin, body.dest)
    return ok({"unblocked": True})


@app.post("/api/v1/events/recalculate")
def events_recalculate(body: RecalculateRequest):
    return ok(service.recalculate(body.current_node, body.final_destination))


@app.get("/api/v1/events/blocked-routes")
def events_blocked():
    return ok(service.blocked_routes())


# ── R5 Report ─────────────────────────────────────────────────────────────────

@app.get("/api/v1/report/{session_id}")
def report_full(session_id: str):
    return ok(service.trip_report(session_id))


@app.get("/api/v1/report/{session_id}/summary")
def report_summary(session_id: str):
    return ok(service.trip_summary(session_id))


@app.get("/health")
def health():
    return {"status": "ok", "nodes": len(service.graph.airports)}
