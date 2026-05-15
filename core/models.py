"""
Domain dataclasses for SkyRoute Planner.

These classes represent the core data structures of the system.
They contain NO business logic — only data fields and simple
__post_init__ validations. All business logic lives in features/.
"""

from dataclasses import dataclass, field


@dataclass
class Aircraft:
    """
    Represents a type of aircraft that can operate on a route.

    Attributes:
        name: Human-readable aircraft name (e.g. 'Avión Comercial').
        cost_per_km: Cost in USD per kilometer flown.
        time_per_km: Travel time in minutes per kilometer flown.
        subsidized: True if this aircraft operates subsidized routes.
    """
    name: str
    cost_per_km: float
    time_per_km: float
    subsidized: bool = False

    def __post_init__(self) -> None:
        if self.cost_per_km < 0:
            raise ValueError("cost_per_km must be >= 0")
        if self.time_per_km <= 0:
            raise ValueError("time_per_km must be > 0")


@dataclass
class Activity:
    """
    Represents an activity available at an airport.

    Attributes:
        name: Activity name (e.g. 'City tour', 'Museum visit').
        type: 'obligatoria' or 'opcional'.
        duration_min: Duration of the activity in minutes.
        cost_usd: Cost of the activity in USD.
    """
    name: str
    type: str          # 'obligatoria' | 'opcional'
    duration_min: int
    cost_usd: float

    def __post_init__(self) -> None:
        if self.duration_min < 0:
            raise ValueError("duration_min must be >= 0")
        if self.cost_usd < 0:
            raise ValueError("cost_usd must be >= 0")


@dataclass
class Job:
    """
    Represents a temporary job available at an airport.

    Attributes:
        name: Job title (e.g. 'Baggage handler', 'Ramp assistant').
        hourly_rate: Income in USD per hour worked.
        max_hours: Maximum hours the traveler can work at this job.
    """
    name: str
    hourly_rate: float
    max_hours: int

    def __post_init__(self) -> None:
        if self.hourly_rate <= 0:
            raise ValueError("hourly_rate must be > 0")
        if self.max_hours <= 0:
            raise ValueError("max_hours must be > 0")


@dataclass
class Airport:
    """
    Represents an airport node in the graph.

    Attributes:
        id: IATA code (e.g. 'BOG', 'LIM').
        name: Full airport name.
        city: City where the airport is located.
        country: Country of the airport.
        timezone: Timezone string (e.g. 'America/Bogota').
        is_hub: True if this is a major hub airport.
        lodging_cost: Cost in USD per night of lodging.
        food_cost: Cost in USD per meal.
        activities: List of activities available at this airport.
        jobs: List of temporary jobs available at this airport.
        airlines: List of airline names operating from this airport.
    """
    id: str
    name: str
    city: str
    country: str
    timezone: str
    is_hub: bool
    lodging_cost: float
    food_cost: float
    activities: list[Activity] = field(default_factory=list)
    jobs: list[Job] = field(default_factory=list)
    airlines: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.lodging_cost < 0:
            raise ValueError("lodging_cost must be >= 0")
        if self.food_cost < 0:
            raise ValueError("food_cost must be >= 0")


@dataclass
class Route:
    """
    Represents a directed edge (flight route) between two airports.

    Attributes:
        origin: IATA code of the departure airport.
        dest: IATA code of the arrival airport.
        distance_km: Distance of the route in kilometers.
        aircraft_types: List of aircraft type names that operate this route.
        base_cost: Base cost override. 0 means the route is subsidized.
        min_stay_min: Minimum layover time at destination in minutes.
    """
    origin: str
    dest: str
    distance_km: float
    aircraft_types: list[str] = field(default_factory=list)
    base_cost: float = -1.0   # -1 means "use aircraft cost_per_km * distance"
    min_stay_min: int = 60

    def __post_init__(self) -> None:
        if self.distance_km <= 0:
            raise ValueError("distance_km must be > 0")
        if self.base_cost < -1:
            raise ValueError("base_cost must be >= 0 or -1 (use default)")
        if self.min_stay_min < 0:
            raise ValueError("min_stay_min must be >= 0")

    @property
    def is_subsidized(self) -> bool:
        """Returns True if this route has zero cost (subsidized)."""
        return self.base_cost == 0.0


@dataclass
class TripSegment:
    """
    Represents a single flight leg that was actually flown.
    Used to build the itinerary history and final report.

    Attributes:
        origin: IATA code of departure airport.
        dest: IATA code of arrival airport.
        aircraft_type: Name of the aircraft used.
        distance_km: Distance flown in km.
        flight_time_min: Actual flight time in minutes.
        cost_usd: Actual cost paid for this segment in USD.
        cumulative_cost: Total cost accumulated up to and including this segment.
        cumulative_time_min: Total time accumulated up to and including this segment.
    """
    origin: str
    dest: str
    aircraft_type: str
    distance_km: float
    flight_time_min: float
    cost_usd: float
    cumulative_cost: float = 0.0
    cumulative_time_min: float = 0.0


@dataclass
class ItineraryState:
    """
    Holds the complete mutable state of an in-progress dynamic trip (R3).
    One instance per active session, stored in memory by session_id.

    Attributes:
        session_id: Unique identifier for this trip session.
        current_airport: IATA code of the airport where the traveler currently is.
        budget_remaining: Current available budget in USD.
        time_remaining_hours: Remaining trip time in hours.
        initial_budget: Original budget (used to compute the 35% threshold).
        hours_since_lodging: Hours elapsed since last lodging.
        hours_since_food: Hours elapsed since last meal.
        visited: Ordered list of IATA codes visited (no repeats allowed).
        total_subsidized_km: Accumulated km traveled on subsidized routes.
        total_km: Total km traveled (to enforce 20% subsidized limit).
        segments: Ordered list of flight segments flown.
        is_active: False once end_trip() has been called.
    """
    session_id: str
    current_airport: str
    budget_remaining: float
    time_remaining_hours: float
    initial_budget: float
    hours_since_lodging: float = 0.0
    hours_since_food: float = 0.0
    visited: list[str] = field(default_factory=list)
    total_subsidized_km: float = 0.0
    total_km: float = 0.0
    segments: list[TripSegment] = field(default_factory=list)
    activities_done: list[dict] = field(default_factory=list)
    jobs_done: list[dict] = field(default_factory=list)
    is_active: bool = True
