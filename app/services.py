"""Business logic layer for all SkyRoute requirements."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.algorithms import dijkstra, max_coverage_itinerary, suggest_next_destination
from app.graph import AirRouteGraph
from app.loader import load_graph_from_json
from app.models import (
    ActivityOption,
    ActivityResult,
    ActivitySummary,
    BestRouteResponse,
    BestRouteResult,
    DestinationSummary,
    FlightOption,
    FlyResult,
    GraphSummary,
    ItineraryResponse,
    JobOption,
    JobRecommendation,
    JobResult,
    JobSummary,
    RecalculateResponse,
    SessionState,
    Suggestion,
    TripReport,
    TripSegment,
    TripSummary,
)


@dataclass
class SessionRecord:
    session_id: str
    origin: str
    initial_budget: float
    budget_remaining: float
    time_remaining_hours: float
    current_airport: str
    visited: list[str]
    segments: list[TripSegment] = field(default_factory=list)
    activities_log: list[ActivitySummary] = field(default_factory=list)
    jobs_log: list[JobSummary] = field(default_factory=list)
    hours_since_lodging: float = 0.0
    hours_since_food: float = 0.0
    stay_time_at_airport: dict[str, float] = field(default_factory=dict)
    cost_at_airport: dict[str, float] = field(default_factory=dict)
    subsidized_km: float = 0.0
    total_distance_km: float = 0.0
    ended: bool = False


class SkyRouteService:
    def __init__(self, network_path: str | None = None) -> None:
        self.network_path = network_path
        self.graph: AirRouteGraph = load_graph_from_json(network_path)
        self.sessions: dict[str, SessionRecord] = {}

    def reload(self) -> None:
        self.graph = load_graph_from_json(self.network_path)

    def summary(self) -> GraphSummary:
        return GraphSummary(
            node_count=len(self.graph.airports),
            edge_count=self.graph.edge_count(),
            hub_count=self.graph.hub_count(),
            blocked_edge_count=len(self.graph.blocked),
        )

    # ── R2 ──────────────────────────────────────────────────────────────────

    def plan_itinerary(
        self,
        origin: str,
        budget_usd: float,
        time_hours: float,
        aircraft_types: list[str],
        include_secondary: bool,
    ) -> ItineraryResponse:
        if origin not in self.graph.airports:
            raise ValueError(f"Unknown airport: {origin}")
        if not aircraft_types:
            aircraft_types = list(self.graph.aircraft_config.keys())

        by_budget = max_coverage_itinerary(
            self.graph, origin, budget_usd, time_hours,
            aircraft_filter=aircraft_types,
            include_secondary=include_secondary,
            optimize="cost",
        )
        by_time = max_coverage_itinerary(
            self.graph, origin, budget_usd, time_hours,
            aircraft_filter=aircraft_types,
            include_secondary=include_secondary,
            optimize="time",
        )
        return ItineraryResponse(by_budget=by_budget, by_time=by_time)

    def best_route(
        self,
        origin: str,
        destination: str,
        criteria: list[str],
        aircraft_types: list[str],
        include_secondary: bool,
    ) -> BestRouteResponse:
        if not aircraft_types:
            aircraft_types = list(self.graph.aircraft_config.keys())
        if not criteria:
            criteria = ["cost_usd"]

        results: dict[str, BestRouteResult] = {}
        for crit in criteria:
            key = crit if crit in ("cost_usd", "flight_time_min", "distance_km") else "cost_usd"
            path, segments, total = dijkstra(
                self.graph, origin, destination,
                weight_key=key,
                aircraft_filter=aircraft_types,
                include_secondary=include_secondary,
            )
            results[crit] = BestRouteResult(
                total=total if path else None,
                path=path,
                segments=segments,
            )
        return BestRouteResponse(results=results)

    # ── R3 ──────────────────────────────────────────────────────────────────

    def start_session(self, origin: str, initial_budget: float, time_hours: float) -> SessionState:
        if origin not in self.graph.airports:
            raise ValueError(f"Unknown airport: {origin}")
        sid = str(uuid.uuid4())
        rec = SessionRecord(
            session_id=sid,
            origin=origin,
            initial_budget=initial_budget,
            budget_remaining=initial_budget,
            time_remaining_hours=time_hours,
            current_airport=origin,
            visited=[origin],
            stay_time_at_airport={origin: 0.0},
            cost_at_airport={origin: 0.0},
        )
        self.sessions[sid] = rec
        return self._session_state(rec)

    def _session_state(self, rec: SessionRecord) -> SessionState:
        return SessionState(
            session_id=rec.session_id,
            current_airport=rec.current_airport,
            budget_remaining=round(rec.budget_remaining, 2),
            time_remaining_hours=round(rec.time_remaining_hours, 2),
            visited=list(rec.visited),
        )

    def _get_session(self, session_id: str) -> SessionRecord:
        rec = self.sessions.get(session_id)
        if not rec or rec.ended:
            raise ValueError("Session not found or already ended")
        return rec

    def get_flights(self, session_id: str) -> list[FlightOption]:
        """Get all available flights from current airport, excluding blocked routes and visited airports."""
        rec = self._get_session(session_id)
        options: list[FlightOption] = []
        
        # Get all non-blocked neighbors
        for edge in self.graph.neighbours(rec.current_airport):
            dest = edge.dest
            
            # Skip already-visited airports (no repeated nodes)
            if dest in rec.visited:
                continue
            
            # Build aircraft options for this route
            ac_opts = []
            for ac in self.graph.allowed_aircraft(edge, list(self.graph.aircraft_config.keys())):
                cost = edge.costs_by_aircraft.get(ac, 0.0)
                time_min = edge.times_by_aircraft.get(ac, 0.0)
                
                # Check budget and time constraints
                hours = time_min / 60.0
                if cost <= rec.budget_remaining and hours <= rec.time_remaining_hours:
                    ac_opts.append({"aircraft_type": ac, "cost_usd": cost, "time_min": time_min})
            
            # Skip routes where no aircraft is affordable/feasible
            if not ac_opts:
                continue
            
            # Select cheapest aircraft as recommended
            recommended = min(ac_opts, key=lambda x: (x["cost_usd"], x["time_min"]))
            
            from app.models import AircraftOption
            options.append(FlightOption(
                dest=dest,
                distance_km=edge.distance_km,
                is_subsidized=edge.is_subsidized,
                min_stay_min=edge.min_stay_min,
                aircraft_options=[AircraftOption(**o) for o in ac_opts],
                recommended_aircraft=AircraftOption(**recommended),
            ))
        
        # Log for debugging
        print(f"✓ Vuelos disponibles desde {rec.current_airport}: {len(options)} opciones")
        if len(options) == 0:
            print(f"  ⚠ No hay vuelos disponibles. Aeropuertos visitados: {rec.visited}")
            print(f"  ⚠ Presupuesto: ${rec.budget_remaining:.2f}, Tiempo: {rec.time_remaining_hours:.2f}h")
        
        return options

    def get_activities(self, session_id: str) -> list[ActivityOption]:
        rec = self._get_session(session_id)
        airport = self.graph.airports[rec.current_airport]
        return [
            ActivityOption(
                name=a.name,
                type=a.type,
                duration_min=a.duration_min,
                cost_usd=a.cost_usd,
                can_afford=rec.budget_remaining >= a.cost_usd,
            )
            for a in airport.activities
            if a.type == "opcional"
        ]

    def _living_cost_for_extra_hours(self, rec: SessionRecord, airport, extra_hours: float) -> float:
        """Food and lodging triggered while the traveler stays at the airport (e.g. while working)."""
        if extra_hours <= 0:
            return 0.0
        food_before = int(rec.hours_since_food // self.graph.food_interval_hours)
        food_after = int((rec.hours_since_food + extra_hours) // self.graph.food_interval_hours)
        lodging_before = int(rec.hours_since_lodging // self.graph.lodging_interval_hours)
        lodging_after = int((rec.hours_since_lodging + extra_hours) // self.graph.lodging_interval_hours)
        meals = max(0, food_after - food_before)
        nights = max(0, lodging_after - lodging_before)
        return meals * airport.food_cost + nights * airport.lodging_cost

    def _cheapest_outbound_flight(self, rec: SessionRecord) -> tuple[float, str | None]:
        """Minimum cost among all viable outbound flights from the current airport."""
        best_cost = float("inf")
        best_dest: str | None = None
        for edge in self.graph.neighbours(rec.current_airport):
            if edge.dest in rec.visited:
                continue
            pick = self.graph.best_aircraft_for_cost(edge, list(self.graph.aircraft_config.keys()))
            if not pick:
                continue
            _, cost, time_min = pick
            hours = time_min / 60.0
            if cost <= rec.budget_remaining and hours <= rec.time_remaining_hours and cost < best_cost:
                best_cost = cost
                best_dest = edge.dest
        if best_cost == float("inf"):
            return 0.0, None
        return best_cost, best_dest

    def _recommend_hours_for_job(
        self, rec: SessionRecord, airport, job, target_deficit: float,
    ) -> tuple[int, float, float, float]:
        """Hours needed so income minus living costs while working covers the deficit."""
        best_h, best_net = 1, -float("inf")
        for hours in range(1, job.max_hours + 1):
            if hours > rec.time_remaining_hours:
                break
            income = job.hourly_rate * hours
            living = self._living_cost_for_extra_hours(rec, airport, float(hours))
            net = income - living
            if net > best_net:
                best_h, best_net = hours, net
            if net >= target_deficit:
                return hours, income, living, net
        income = job.hourly_rate * best_h
        living = self._living_cost_for_extra_hours(rec, airport, float(best_h))
        return best_h, income, living, income - living

    def get_jobs(self, session_id: str) -> list[JobOption]:
        rec = self._get_session(session_id)
        airport = self.graph.airports[rec.current_airport]
        cheapest, _ = self._cheapest_outbound_flight(rec)
        threshold = rec.initial_budget * (self.graph.budget_job_threshold_pct / 100.0)
        needs_income = rec.budget_remaining < cheapest if cheapest > 0 else rec.budget_remaining < threshold
        deficit = max(0.0, cheapest - rec.budget_remaining) if cheapest > 0 else max(
            0.0, threshold - rec.budget_remaining,
        )

        options: list[JobOption] = []
        for j in airport.jobs:
            rec_h, income, living, net = self._recommend_hours_for_job(rec, airport, j, deficit if needs_income else 0.0)
            is_rec = needs_income and net > 0
            reason = None
            if needs_income and deficit > 0:
                reason = (
                    f"Con ${rec.budget_remaining:.0f} disponibles y vuelo mínimo ${cheapest:.0f}, "
                    f"trabaja {rec_h}h (hospedaje/comida ~${living:.0f}) para cubrir el déficit."
                )
            elif rec.budget_remaining < threshold:
                reason = f"Presupuesto bajo el {self.graph.budget_job_threshold_pct:.0f}% inicial — trabajo disponible."

            options.append(JobOption(
                name=j.name,
                hourly_rate=j.hourly_rate,
                max_hours=j.max_hours,
                max_earnable_usd=round(j.hourly_rate * j.max_hours, 2),
                recommended_hours=rec_h if is_rec or rec.budget_remaining < threshold else None,
                estimated_living_cost=round(living, 2),
                estimated_net_income=round(net, 2),
                is_recommended=is_rec,
                recommendation_reason=reason,
            ))
        return options

    def get_suggestion(self, session_id: str) -> Suggestion:
        rec = self._get_session(session_id)
        cheapest, cheapest_dest = self._cheapest_outbound_flight(rec)
        deficit = max(0.0, cheapest - rec.budget_remaining) if cheapest > 0 else 0.0
        needs_jobs = deficit > 0 or (
            rec.budget_remaining < rec.initial_budget * (self.graph.budget_job_threshold_pct / 100.0)
            and cheapest > 0
        )

        job_recs: list[JobRecommendation] = []
        if needs_jobs:
            airport = self.graph.airports[rec.current_airport]
            target = deficit if deficit > 0 else max(10.0, cheapest * 0.2)
            for j in airport.jobs:
                h, income, living, net = self._recommend_hours_for_job(rec, airport, j, target)
                if net <= 0:
                    continue
                job_recs.append(JobRecommendation(
                    name=j.name,
                    hourly_rate=j.hourly_rate,
                    recommended_hours=h,
                    estimated_income=round(income, 2),
                    estimated_living_cost=round(living, 2),
                    net_gain=round(net, 2),
                    reason=(
                        f"Trabaja {h}h → ingreso ${income:.0f}, "
                        f"hospedaje/comida ~${living:.0f}, neto +${net:.0f}"
                    ),
                ))
            job_recs.sort(key=lambda x: x.net_gain, reverse=True)

        dest, path, cost, time_min = suggest_next_destination(
            self.graph,
            rec.current_airport,
            rec.budget_remaining,
            visited=set(rec.visited),
        )
        if dest is None and cheapest_dest and rec.budget_remaining >= cheapest:
            dest, cost, time_min = cheapest_dest, cheapest, 0.0
            path, _, _ = dijkstra(
                self.graph, rec.current_airport, cheapest_dest,
                weight_key="cost_usd",
                aircraft_filter=list(self.graph.aircraft_config.keys()),
                include_secondary=True,
            )

        return Suggestion(
            suggested_dest=dest,
            path=path,
            estimated_cost=cost,
            estimated_time_min=time_min,
            needs_jobs=needs_jobs and len(job_recs) > 0,
            budget_deficit=round(deficit, 2),
            cheapest_flight_cost=round(cheapest, 2),
            job_recommendations=job_recs[:3],
        )

    def _apply_mandatory_costs(self, rec: SessionRecord, hours_elapsed: float) -> list[str]:
        """Apply mandatory food and lodging costs based on elapsed time."""
        events: list[str] = []
        airport = self.graph.airports[rec.current_airport]
        rec.hours_since_lodging += hours_elapsed
        rec.hours_since_food += hours_elapsed
        rec.stay_time_at_airport[rec.current_airport] = rec.stay_time_at_airport.get(rec.current_airport, 0) + hours_elapsed * 60

        # Process food charges (every 8 hours)
        while rec.hours_since_food >= self.graph.food_interval_hours:
            rec.budget_remaining -= airport.food_cost
            rec.cost_at_airport[rec.current_airport] = rec.cost_at_airport.get(rec.current_airport, 0) + airport.food_cost
            rec.hours_since_food -= self.graph.food_interval_hours
            events.append(f"🍽 Alimentación obligatoria en {rec.current_airport} (-${airport.food_cost:.2f})")

        # Process lodging charges (every 20 hours)
        while rec.hours_since_lodging >= self.graph.lodging_interval_hours:
            rec.budget_remaining -= airport.lodging_cost
            rec.cost_at_airport[rec.current_airport] = rec.cost_at_airport.get(rec.current_airport, 0) + airport.lodging_cost
            rec.hours_since_lodging -= self.graph.lodging_interval_hours
            events.append(f"🏨 Alojamiento obligatorio en {rec.current_airport} (-${airport.lodging_cost:.2f})")

        # Validation: Log if mandatory costs were applied
        if events:
            print(f"✓ Sistema de recaudo activo - {len(events)} evento(s) aplicado(s)")
            print(f"  Presupuesto restante: ${rec.budget_remaining:.2f}")
            print(f"  Horas desde última comida: {rec.hours_since_food:.1f}h")
            print(f"  Horas desde último alojamiento: {rec.hours_since_lodging:.1f}h")

        return events

    def fly(self, session_id: str, dest: str, aircraft_type: str) -> FlyResult:
        rec = self._get_session(session_id)
        edge = self.graph.get_edge(rec.current_airport, dest)
        
        # Verificar que la ruta existe y no está bloqueada
        if not edge:
            # Verificar si existe la ruta pero está bloqueada
            if self.graph.edge_exists(rec.current_airport, dest) and self.graph.is_blocked(rec.current_airport, dest):
                raise ValueError(f"La ruta de {rec.current_airport} a {dest} está bloqueada")
            raise ValueError(f"No existe ruta de {rec.current_airport} a {dest}")
        
        if aircraft_type not in edge.costs_by_aircraft:
            raise ValueError(f"Aeronave {aircraft_type} no disponible en esta ruta")

        cost = edge.costs_by_aircraft[aircraft_type]
        time_min = edge.times_by_aircraft[aircraft_type]

        # Validar límite de distancia subsidiada (20% del total)
        if edge.is_subsidized:
            max_sub = rec.total_distance_km * 0.20 if rec.total_distance_km > 0 else edge.distance_km
            if rec.subsidized_km + edge.distance_km > max_sub and rec.total_distance_km > 0:
                raise ValueError("La ruta subsidiada excedería el límite del 20% de la distancia total")

        # Validar restricciones presupuestarias
        if cost > rec.budget_remaining:
            raise ValueError(f"Presupuesto insuficiente. Requerido: ${cost:.2f}, Disponible: ${rec.budget_remaining:.2f}")
        
        hours = time_min / 60.0
        if hours > rec.time_remaining_hours:
            raise ValueError(f"Tiempo insuficiente. Requerido: {hours:.2f}h, Disponible: {rec.time_remaining_hours:.2f}h")

        # Construir segmento del viaje
        cum_cost = sum(s.cost_usd for s in rec.segments) + cost
        cum_time = sum(s.flight_time_min for s in rec.segments) + time_min
        segment = self.graph.build_segment(edge, aircraft_type, cum_cost - cost, cum_time - time_min)

        # Actualizar estado de la sesión
        rec.budget_remaining -= cost
        rec.time_remaining_hours -= hours
        rec.total_distance_km += edge.distance_km
        if edge.is_subsidized:
            rec.subsidized_km += edge.distance_km

        # Aplicar costos obligatorios (comida y alojamiento)
        mandatory = self._apply_mandatory_costs(rec, hours)

        # Registrar el segmento y actualizar ubicación
        rec.segments.append(segment)
        rec.current_airport = dest
        if dest not in rec.visited:
            rec.visited.append(dest)
        rec.stay_time_at_airport.setdefault(dest, 0.0)
        rec.cost_at_airport.setdefault(dest, 0.0)
        rec.cost_at_airport[dest] = rec.cost_at_airport.get(dest, 0) + cost

        # Log de verificación
        print(f"✓ Vuelo exitoso: {segment.origin} → {segment.dest}")
        print(f"  Costo: ${cost:.2f} | Tiempo: {hours:.2f}h")
        print(f"  Presupuesto restante: ${rec.budget_remaining:.2f}")
        print(f"  Aeropuertos visitados: {len(rec.visited)}")

        return FlyResult(
            segment=segment,
            mandatory_events=mandatory,
            budget_remaining=round(rec.budget_remaining, 2),
            time_remaining_hours=round(rec.time_remaining_hours, 2),
            current_airport=rec.current_airport,
            visited=list(rec.visited),
        )

    def do_activity(self, session_id: str, activity_name: str) -> ActivityResult:
        rec = self._get_session(session_id)
        airport = self.graph.airports[rec.current_airport]
        act = next((a for a in airport.activities if a.name == activity_name), None)
        if not act:
            raise ValueError(f"Activity '{activity_name}' not found")
        if act.cost_usd > rec.budget_remaining:
            raise ValueError("Insufficient budget")
        hours = act.duration_min / 60.0
        if hours > rec.time_remaining_hours:
            raise ValueError("Insufficient time")

        rec.budget_remaining -= act.cost_usd
        rec.time_remaining_hours -= hours
        rec.stay_time_at_airport[rec.current_airport] = rec.stay_time_at_airport.get(rec.current_airport, 0) + act.duration_min
        rec.cost_at_airport[rec.current_airport] = rec.cost_at_airport.get(rec.current_airport, 0) + act.cost_usd
        rec.activities_log.append(ActivitySummary(
            name=act.name,
            activity_type=act.type,
            duration_min=act.duration_min,
            cost_usd=act.cost_usd,
            airport_iata=rec.current_airport,
        ))
        return ActivityResult(
            cost_usd=act.cost_usd,
            budget_remaining=round(rec.budget_remaining, 2),
            time_remaining_hours=round(rec.time_remaining_hours, 2),
        )

    def do_job(self, session_id: str, job_name: str, hours: float) -> JobResult:
        rec = self._get_session(session_id)
        airport = self.graph.airports[rec.current_airport]
        job = next((j for j in airport.jobs if j.name == job_name), None)
        if not job:
            raise ValueError(f"Job '{job_name}' not found")
        if hours <= 0 or hours > job.max_hours:
            raise ValueError(f"Hours must be between 1 and {job.max_hours}")
        if hours > rec.time_remaining_hours:
            raise ValueError("Insufficient time")

        living_cost = self._living_cost_for_extra_hours(rec, airport, float(hours))
        income = round(job.hourly_rate * hours, 2)
        rec.budget_remaining += income
        rec.budget_remaining -= living_cost
        rec.time_remaining_hours -= hours
        rec.stay_time_at_airport[rec.current_airport] = rec.stay_time_at_airport.get(rec.current_airport, 0) + hours * 60
        rec.cost_at_airport[rec.current_airport] = rec.cost_at_airport.get(rec.current_airport, 0) + living_cost
        rec.hours_since_food += hours
        rec.hours_since_lodging += hours
        rec.jobs_log.append(JobSummary(
            name=job.name,
            hours_worked=hours,
            income_usd=income,
            airport_iata=rec.current_airport,
        ))
        return JobResult(
            income_usd=income,
            budget_remaining=round(rec.budget_remaining, 2),
            time_remaining_hours=round(rec.time_remaining_hours, 2),
        )

    def end_session(self, session_id: str) -> None:
        rec = self._get_session(session_id)
        rec.ended = True

    # ── R4 ──────────────────────────────────────────────────────────────────

    def block_route(self, origin: str, dest: str, session_id: str | None = None) -> dict:
        """
        Block a route and handle in-flight diversions if necessary.
        
        Returns dict with:
            - blocked: bool
            - in_transit_detected: bool
            - diverted_to: str | None (emergency diversion airport)
            - original_dest: str | None
        """
        if not self.graph.edge_exists(origin, dest):
            raise ValueError(f"Route {origin}→{dest} does not exist")
        
        result = {
            "blocked": False,
            "in_transit_detected": False,
            "diverted_to": None,
            "original_dest": None,
        }
        
        # Check if any active session is currently flying this route
        if session_id:
            rec = self.sessions.get(session_id)
            if rec and not rec.ended and len(rec.segments) > 0:
                last_segment = rec.segments[-1]
                # Check if last segment destination hasn't been visited yet (in transit)
                if last_segment.dest not in rec.visited and last_segment.origin == origin and last_segment.dest == dest:
                    result["in_transit_detected"] = True
                    result["original_dest"] = dest
                    
                    # Find emergency diversion - try to find closest available airport
                    diversion_found = False
                    
                    # Try to return to origin first
                    if not self.graph.is_blocked(origin, origin):
                        result["diverted_to"] = origin
                        diversion_found = True
                    
                    # If origin not possible, find another nearby airport
                    if not diversion_found:
                        for edge in self.graph.neighbours(origin):
                            if edge.dest not in rec.visited and not self.graph.is_blocked(origin, edge.dest):
                                result["diverted_to"] = edge.dest
                                diversion_found = True
                                break
                    
                    # If still no diversion, allow return to origin as emergency
                    if not diversion_found:
                        result["diverted_to"] = origin
                    
                    # Update session to reflect emergency diversion
                    if result["diverted_to"] == origin:
                        # Return to origin - cancel last segment
                        rec.segments.pop()
                        rec.current_airport = origin
                    else:
                        # Divert to alternative airport
                        rec.current_airport = result["diverted_to"]
                        if result["diverted_to"] not in rec.visited:
                            rec.visited.append(result["diverted_to"])
                        # Update last segment to reflect diversion
                        rec.segments[-1].dest = result["diverted_to"]
        
        # Block the route
        self.graph.block_edge(origin, dest)
        result["blocked"] = True
        
        return result

    def unblock_route(self, origin: str, dest: str) -> None:
        self.graph.unblock_edge(origin, dest)

    def blocked_routes(self) -> list[dict[str, str]]:
        return [{"origin": o, "dest": d} for o, d in sorted(self.graph.blocked)]

    def recalculate(self, current_node: str, final_destination: str) -> RecalculateResponse:
        path, segments, total = dijkstra(
            self.graph, current_node, final_destination,
            weight_key="cost_usd",
            aircraft_filter=list(self.graph.aircraft_config.keys()),
            include_secondary=True,
        )
        if not path:
            return RecalculateResponse(
                found=False,
                total_cost=None,
                path=[],
                segments=[],
                error="No viable alternative route found",
            )
        return RecalculateResponse(
            found=True,
            total_cost=round(sum(s.cost_usd for s in segments), 2),
            path=path,
            segments=segments,
            error=None,
        )

    # ── R5 ──────────────────────────────────────────────────────────────────

    def trip_report(self, session_id: str) -> TripReport:
        rec = self.sessions.get(session_id)
        if not rec:
            raise ValueError("Session not found")

        destinations = []
        for iata in rec.visited:
            ap = self.graph.airports.get(iata)
            if not ap:
                continue
            destinations.append(DestinationSummary(
                iata_code=iata,
                name=ap.name,
                city=ap.city,
                country=ap.country,
                stay_time_min=rec.stay_time_at_airport.get(iata, 0),
                total_cost_usd=round(rec.cost_at_airport.get(iata, 0), 2),
            ))

        total_earned = round(sum(j.income_usd for j in rec.jobs_log), 2)
        initial = rec.initial_budget
        final_balance = round(rec.budget_remaining, 2)
        total_spent = round(initial - final_balance + total_earned, 2)

        time_used = sum(s.flight_time_min for s in rec.segments)
        time_used += sum(a.duration_min for a in rec.activities_log)
        time_used += sum(j.hours_worked * 60 for j in rec.jobs_log)
        total_time_hours = round(time_used / 60.0, 2)

        return TripReport(
            session_id=session_id,
            destinations=destinations,
            segments=rec.segments,
            activities=rec.activities_log,
            jobs=rec.jobs_log,
            initial_budget=initial,
            total_spent=total_spent,
            total_earned=total_earned,
            final_balance=final_balance,
            total_time_hours=total_time_hours,
            total_distance_km=round(rec.total_distance_km, 1),
        )

    def trip_summary(self, session_id: str) -> TripSummary:
        report = self.trip_report(session_id)
        return TripSummary(
            session_id=session_id,
            initial_budget=report.initial_budget,
            total_spent=report.total_spent,
            total_earned=report.total_earned,
            final_balance=report.final_balance,
            total_time_hours=report.total_time_hours,
            destinations_visited=len(report.destinations),
        )
