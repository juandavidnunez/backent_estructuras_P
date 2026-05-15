"""
JSON network loader — Requirement R1 (Programmer B responsibility).

Reads a network JSON file and builds a Graph object using the domain
dataclasses from core/models.py and the Graph class from core/graph.py.

This module only knows about core/ and config.py.
It does NOT import anything from api/.
"""

import json
from typing import Any

from core.graph import Graph
from core.models import Activity, Airport, Job, Route


def load_network(path: str) -> Graph:
    """
    Read a network JSON file and construct a fully populated Graph.

    The JSON must follow the schema defined in the project specification:
    - "aeropuertos": list of airport node objects
    - "rutas": list of directed route edge objects

    Args:
        path: Absolute or relative path to the JSON file.

    Returns:
        A Graph instance with all nodes and edges loaded.

    Raises:
        FileNotFoundError: If the JSON file does not exist.
        ValueError: If the JSON is malformed or missing required fields.
    """
    with open(path, "r", encoding="utf-8") as file_handle:
        raw: dict[str, Any] = json.load(file_handle)

    if "aeropuertos" not in raw:
        raise ValueError("JSON missing required key 'aeropuertos'")
    if "rutas" not in raw:
        raise ValueError("JSON missing required key 'rutas'")

    graph = Graph()

    # --- Load nodes ---
    for node_data in raw["aeropuertos"]:
        activities = [
            Activity(
                name=act["nombre"],
                type=act["tipo"],
                duration_min=act["duracionMin"],
                cost_usd=act["costoUSD"],
            )
            for act in node_data.get("actividades", [])
        ]

        jobs = [
            Job(
                name=job["nombre"],
                hourly_rate=job["tarifaHora"],
                max_hours=job["maxHoras"],
            )
            for job in node_data.get("trabajos", [])
        ]

        airport = Airport(
            id=node_data["id"],
            name=node_data["nombre"],
            city=node_data["ciudad"],
            country=node_data["pais"],
            timezone=node_data["zonaHoraria"],
            is_hub=node_data["esHub"],
            lodging_cost=node_data["costoAlojamiento"],
            food_cost=node_data["costoAlimentacion"],
            activities=activities,
            jobs=jobs,
            airlines=node_data.get("aerolineas", []),
        )

        graph.add_node(airport.id, airport)

    # --- Load edges ---
    for edge_data in raw["rutas"]:
        route = Route(
            origin=edge_data["origen"],
            dest=edge_data["destino"],
            distance_km=edge_data["distanciaKm"],
            aircraft_types=edge_data.get("aeronaves", []),
            base_cost=edge_data.get("costoBase", -1.0),
            min_stay_min=edge_data.get("estanciaMinima", 60),
        )

        graph.add_edge(route.origin, route.dest, route)

    return graph
