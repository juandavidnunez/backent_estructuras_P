"""Load network.json (Spanish schema) into the in-memory graph."""
from __future__ import annotations

import json
from pathlib import Path

from app.graph import AirRouteGraph, AircraftConfig, Edge
from app.models import ActivitySchema, Airport, JobSchema


DEFAULT_AIRCRAFT = {
    "Avión Comercial": {"costoKm": 0.18, "tiempoKm": 0.7},
    "Avión Regional": {"costoKm": 0.25, "tiempoKm": 1.1},
    "Hélice": {"costoKm": 0.12, "tiempoKm": 2.5},
}


def _resolve_network_path(path: str | None) -> Path:
    if path:
        return Path(path)
    here = Path(__file__).resolve().parent.parent
    candidates = [
        here / "network.json",
        here.parent / "skyroute-frontend" / "public" / "network.json",
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]


def load_graph_from_json(path: str | None = None) -> AirRouteGraph:
    json_path = _resolve_network_path(path)
    with open(json_path, encoding="utf-8") as f:
        raw = json.load(f)

    graph = AirRouteGraph()
    cfg = raw.get("configuracion", {})

    aircraft_cfg = cfg.get("aeronaves", DEFAULT_AIRCRAFT)
    for name, vals in aircraft_cfg.items():
        graph.aircraft_config[name] = AircraftConfig(
            cost_per_km=float(vals["costoKm"]),
            time_per_km=float(vals["tiempoKm"]),
        )

    graph.budget_job_threshold_pct = float(cfg.get("presupuestoMinimoPorc", 35))
    graph.lodging_interval_hours = float(cfg.get("intervaloAlojamiento", 20))
    graph.food_interval_hours = float(cfg.get("intervaloAlimentacion", 8))

    for node in raw.get("aeropuertos", []):
        activities = [
            ActivitySchema(
                name=a["nombre"],
                type=a["tipo"],
                duration_min=int(a["duracionMin"]),
                cost_usd=float(a["costoUSD"]),
            )
            for a in node.get("actividades", [])
        ]
        jobs = [
            JobSchema(
                name=j["nombre"],
                hourly_rate=float(j["tarifaHora"]),
                max_hours=int(j["maxHoras"]),
            )
            for j in node.get("trabajos", [])
        ]
        graph.add_airport(Airport(
            id=node["id"],
            name=node["nombre"],
            city=node["ciudad"],
            country=node["pais"],
            timezone=node["zonaHoraria"],
            is_hub=bool(node.get("esHub", False)),
            lodging_cost=float(node.get("costoAlojamiento", 0)),
            food_cost=float(node.get("costoAlimentacion", 0)),
            activities=activities,
            jobs=jobs,
            airlines=list(node.get("aerolineas", [])),
        ))

    for route in raw.get("rutas", []):
        origin = route["origen"]
        dest = route["destino"]
        distance = float(route["distanciaKm"])
        base_cost = float(route.get("costoBase", 1))
        subsidized = base_cost == 0
        aircraft_types = list(route.get("aeronaves", []))

        costs: dict[str, float] = {}
        times: dict[str, float] = {}
        for ac in aircraft_types:
            ac_cfg = graph.aircraft_config.get(ac)
            if not ac_cfg:
                continue
            if subsidized:
                costs[ac] = 0.0
            else:
                costs[ac] = round(distance * ac_cfg.cost_per_km, 2)
            times[ac] = round(distance * ac_cfg.time_per_km, 1)

        graph.add_edge(Edge(
            origin=origin,
            dest=dest,
            distance_km=distance,
            aircraft_types=aircraft_types,
            base_cost=base_cost,
            min_stay_min=int(route.get("estanciaMinima", 0)),
            costs_by_aircraft=costs,
            times_by_aircraft=times,
        ))

    return graph
