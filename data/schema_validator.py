"""
Schema validator for SkyRoute Planner network JSON files.

Usage:
    python data/schema_validator.py data/network.json
    python data/schema_validator.py data/network_test.json

Exit codes:
    0 — JSON is valid.
    1 — JSON is invalid (errors printed to stdout).

Validates:
    - Presence of required top-level keys ('aeropuertos', 'rutas').
    - Required fields on each airport node.
    - Correct data types on numeric and boolean fields.
    - Required fields on each route edge.
    - All route airport references exist as nodes.
    - No duplicate directed edges (same origin + dest pair).
    - At least one aircraft type per route.
    - Activities and jobs have required fields and valid types.
"""

import json
import sys
from typing import Any


# ---------------------------------------------------------------------------
# Required field definitions
# ---------------------------------------------------------------------------

AIRPORT_REQUIRED_FIELDS: dict[str, type] = {
    "id":                str,
    "nombre":            str,
    "ciudad":            str,
    "pais":              str,
    "zonaHoraria":       str,
    "esHub":             bool,
    "costoAlojamiento":  (int, float),
    "costoAlimentacion": (int, float),
}

ROUTE_REQUIRED_FIELDS: dict[str, type] = {
    "origen":       str,
    "destino":      str,
    "distanciaKm":  (int, float),
    "aeronaves":    list,
}

ACTIVITY_REQUIRED_FIELDS: dict[str, type] = {
    "nombre":      str,
    "tipo":        str,
    "duracionMin": int,
    "costoUSD":    (int, float),
}

JOB_REQUIRED_FIELDS: dict[str, type] = {
    "nombre":     str,
    "tarifaHora": (int, float),
    "maxHoras":   int,
}

VALID_ACTIVITY_TYPES = {"obligatoria", "opcional"}


# ---------------------------------------------------------------------------
# Validation functions
# ---------------------------------------------------------------------------

def _check_fields(obj: dict, required: dict, context: str, errors: list[str]) -> None:
    """
    Check that all required fields exist in obj with the correct type.

    Args:
        obj: The dict to validate.
        required: Mapping of field_name -> expected_type (or tuple of types).
        context: Human-readable label for error messages.
        errors: List to append error strings to.
    """
    for field, expected_type in required.items():
        if field not in obj:
            errors.append(f"{context}: missing required field '{field}'.")
            continue

        value = obj[field]
        if not isinstance(value, expected_type):
            errors.append(
                f"{context}: field '{field}' must be {expected_type}, "
                f"got {type(value).__name__} (value: {value!r})."
            )


def validate_airports(airports: list[Any], errors: list[str]) -> set[str]:
    """
    Validate all airport objects and return the set of valid IATA codes.

    Args:
        airports: List of raw airport dicts from the JSON.
        errors: List to append error strings to.

    Returns:
        Set of IATA codes that passed basic validation (used for edge checks).
    """
    valid_ids: set[str] = set()
    seen_ids: set[str] = set()

    for index, airport in enumerate(airports):
        ctx = f"Airport[{index}]"

        if not isinstance(airport, dict):
            errors.append(f"{ctx}: expected object, got {type(airport).__name__}.")
            continue

        _check_fields(airport, AIRPORT_REQUIRED_FIELDS, ctx, errors)

        airport_id = airport.get("id", f"<missing id [{index}]>")
        ctx = f"Airport '{airport_id}'"

        # Duplicate IATA codes
        if airport_id in seen_ids:
            errors.append(f"{ctx}: duplicate IATA code '{airport_id}'.")
        else:
            seen_ids.add(airport_id)
            valid_ids.add(airport_id)

        # Validate activities
        for act_idx, act in enumerate(airport.get("actividades", [])):
            act_ctx = f"{ctx} > Activity[{act_idx}]"
            if not isinstance(act, dict):
                errors.append(f"{act_ctx}: expected object.")
                continue
            _check_fields(act, ACTIVITY_REQUIRED_FIELDS, act_ctx, errors)
            act_type = act.get("tipo", "")
            if act_type not in VALID_ACTIVITY_TYPES:
                errors.append(
                    f"{act_ctx}: 'tipo' must be one of {VALID_ACTIVITY_TYPES}, got '{act_type}'."
                )

        # Validate jobs
        for job_idx, job in enumerate(airport.get("trabajos", [])):
            job_ctx = f"{ctx} > Job[{job_idx}]"
            if not isinstance(job, dict):
                errors.append(f"{job_ctx}: expected object.")
                continue
            _check_fields(job, JOB_REQUIRED_FIELDS, job_ctx, errors)

    return valid_ids


def validate_routes(routes: list[Any], valid_ids: set[str], errors: list[str]) -> None:
    """
    Validate all route objects.

    Args:
        routes: List of raw route dicts from the JSON.
        valid_ids: Set of IATA codes from validate_airports().
        errors: List to append error strings to.
    """
    seen_edges: set[tuple[str, str]] = set()

    for index, route in enumerate(routes):
        ctx = f"Route[{index}]"

        if not isinstance(route, dict):
            errors.append(f"{ctx}: expected object, got {type(route).__name__}.")
            continue

        _check_fields(route, ROUTE_REQUIRED_FIELDS, ctx, errors)

        origin = route.get("origen", "")
        dest   = route.get("destino", "")
        ctx    = f"Route '{origin}' -> '{dest}'"

        # Reference integrity: airports must exist as nodes
        if origin and origin not in valid_ids:
            errors.append(f"{ctx}: origin airport '{origin}' not found in 'aeropuertos'.")
        if dest and dest not in valid_ids:
            errors.append(f"{ctx}: dest airport '{dest}' not found in 'aeropuertos'.")

        # Duplicate directed edges
        edge_key = (origin, dest)
        if edge_key in seen_edges:
            errors.append(f"{ctx}: duplicate directed edge '{origin}' -> '{dest}'.")
        else:
            seen_edges.add(edge_key)

        # Must have at least one aircraft
        aircraft_list = route.get("aeronaves", [])
        if isinstance(aircraft_list, list) and len(aircraft_list) == 0:
            errors.append(f"{ctx}: 'aeronaves' must contain at least one aircraft type.")

        # Distance must be positive
        dist = route.get("distanciaKm", 0)
        if isinstance(dist, (int, float)) and dist <= 0:
            errors.append(f"{ctx}: 'distanciaKm' must be > 0, got {dist}.")

        # costoBase: -1 (default) or >= 0 (override / subsidized)
        cost_base = route.get("costoBase", -1)
        if isinstance(cost_base, (int, float)) and cost_base < -1:
            errors.append(f"{ctx}: 'costoBase' must be -1 or >= 0, got {cost_base}.")


def validate(path: str) -> list[str]:
    """
    Run the full validation pipeline on a JSON network file.

    Args:
        path: Path to the JSON file.

    Returns:
        List of error strings. Empty list means the file is valid.
    """
    errors: list[str] = []

    # --- Load file ---
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return [f"File not found: '{path}'"]
    except json.JSONDecodeError as exc:
        return [f"JSON parse error: {exc}"]

    if not isinstance(data, dict):
        return ["Root element must be a JSON object."]

    # --- Top-level keys ---
    if "aeropuertos" not in data:
        errors.append("Missing required top-level key 'aeropuertos'.")
    if "rutas" not in data:
        errors.append("Missing required top-level key 'rutas'.")

    if errors:
        return errors  # Cannot continue without the top-level lists

    airports = data["aeropuertos"]
    routes   = data["rutas"]

    if not isinstance(airports, list):
        errors.append("'aeropuertos' must be a list.")
        airports = []

    if not isinstance(routes, list):
        errors.append("'rutas' must be a list.")
        routes = []

    if len(airports) == 0:
        errors.append("'aeropuertos' must contain at least one airport.")

    # --- Validate nodes ---
    valid_ids = validate_airports(airports, errors)

    # --- Validate edges ---
    validate_routes(routes, valid_ids, errors)

    return errors


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the validator from the command line."""
    if len(sys.argv) < 2:
        print("Usage: python data/schema_validator.py <path-to-json>")
        sys.exit(1)

    path = sys.argv[1]
    errors = validate(path)

    if not errors:
        print(f"✓ '{path}' is valid. No errors found.")
        sys.exit(0)
    else:
        print(f"✗ '{path}' has {len(errors)} error(s):\n")
        for i, error in enumerate(errors, start=1):
            print(f"  {i}. {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()