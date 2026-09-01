"""Multi-city trip definitions and passenger party models.

Provider-neutral trip shapes that define the search plan; live prices are
injected at runtime via encrypted config. No PII in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Tuple


@dataclass(frozen=True)
class TripBucket:
    """Trip type identifiers for result grouping."""
    SEPT_UAE_ROUNDTRIP = "SEPT_UAE_ROUNDTRIP"
    SEPT_MUSCAT_UAE_OPEN_JAW = "SEPT_MUSCAT_UAE_OPEN_JAW"
    DEC_HOLIDAY_PACKAGES = "DEC_HOLIDAY_PACKAGES"


@dataclass(frozen=True)
class PassengerParty:
    """Passenger party with explicit adult/child split; no invented ages.

    Two adults is the default. Additional children ages are tracked explicitly
    so providers can apply their own child cutoffs at checkout.
    """
    adults: int = 2
    children_ages: Tuple[int, ...] = ()

    @property
    def total_travellers(self) -> int:
        return self.adults + len(self.children_ages)

    @property
    def airline_adult_count(self) -> int:
        """Provider-facing adult count; children >=12 may price as adults."""
        return self.adults + sum(1 for age in self.children_ages if age >= 12)


@dataclass(frozen=True)
class GroundSegment:
    """Surface transport between airports/hotels (not flown)."""
    origin: str
    destination: str
    mode: str  # COACH, TAXI, SHUTTLE, SELF_DRIVE
    cost_gbp: float
    duration_minutes: int


@dataclass(frozen=True)
class TripDefinition:
    """Complete trip definition for a multi-city itinerary.

    Defines the shape of the search (origins, destinations, dates, party)
    without any live pricing. Live prices are injected at runtime.
    """
    key: str
    label: str
    bucket: str  # TripBucket value

    # Outbound leg
    outbound_origins: Tuple[str, ...]
    outbound_destinations: Tuple[str, ...]
    outbound_dates: Tuple[str, ...]

    # Return leg
    return_origins: Tuple[str, ...]
    return_destinations: Tuple[str, ...]
    return_dates: Tuple[str, ...]

    # Party and preferences
    passenger_party: PassengerParty
    cabin_classes: Tuple[str, ...] = ("ECONOMY",)
    departure_window: Tuple[str, str] = ("00:00", "23:59")
    max_stops: int = 2
    max_duration_minutes: int = 1440
    max_price_per_traveller_gbp: float | None = None

    # Surface/ground transport (optional)
    surface_segments: Tuple[GroundSegment, ...] = ()

    # Hotel anchors for display (not used for pricing)
    hotel_anchors: Tuple[str, ...] = ()

    def build_search_plan(self) -> List['SearchRequest']:
        """Generate search requests for this trip definition."""
        from .config import FlightSearch
        plan = []
        for cabin in self.cabin_classes:
            plan.append(FlightSearch(
                key=f"{self.key}_OUTBOUND_{cabin}",
                label=f"{self.label} Outbound ({cabin})",
                origins=self.outbound_origins,
                destinations=self.outbound_destinations,
                dates=self.outbound_dates,
                travellers=self.passenger_party.airline_adult_count,
                cabin_class=cabin,
                departure_window=self.departure_window,
                max_stops=self.max_stops,
                max_duration_minutes=self.max_duration_minutes,
                max_price_per_traveller_gbp=self.max_price_per_traveller_gbp,
            ))
            plan.append(FlightSearch(
                key=f"{self.key}_RETURN_{cabin}",
                label=f"{self.label} Return ({cabin})",
                origins=self.return_origins,
                destinations=self.return_destinations,
                dates=self.return_dates,
                travellers=self.passenger_party.airline_adult_count,
                cabin_class=cabin,
                departure_window=self.departure_window,
                max_stops=self.max_stops,
                max_duration_minutes=self.max_duration_minutes,
                max_price_per_traveller_gbp=self.max_price_per_traveller_gbp,
            ))
        return plan


# Default trip definitions for September 2026 UAE/Muscat
DEFAULT_TRIP_DEFINITIONS = (
    TripDefinition(
        key=TripBucket.SEPT_UAE_ROUNDTRIP,
        label="Dubai / Abu Dhabi Round-trip",
        bucket=TripBucket.SEPT_UAE_ROUNDTRIP,
        outbound_origins=("LHR", "LGW", "LTN", "STN"),
        outbound_destinations=("DXB", "AUH"),
        outbound_dates=("2026-09-15", "2026-09-16"),
        return_origins=("DXB", "AUH"),
        return_destinations=("LHR", "LGW", "LTN", "STN"),
        return_dates=("2026-09-26", "2026-09-27", "2026-09-28"),
        passenger_party=PassengerParty(adults=1),
        cabin_classes=("ECONOMY",),
        departure_window=("06:00", "21:00"),
        max_stops=1,
        max_duration_minutes=720,
        max_price_per_traveller_gbp=500.0,
    ),
    TripDefinition(
        key=TripBucket.SEPT_MUSCAT_UAE_OPEN_JAW,
        label="Muscat + Dubai Open Jaw",
        bucket=TripBucket.SEPT_MUSCAT_UAE_OPEN_JAW,
        outbound_origins=("LHR", "LGW", "LTN", "STN"),
        outbound_destinations=("MCT",),
        outbound_dates=("2026-09-15", "2026-09-16"),
        return_origins=("DXB", "AUH"),
        return_destinations=("LHR", "LGW", "LTN", "STN"),
        return_dates=("2026-09-26", "2026-09-27", "2026-09-28"),
        passenger_party=PassengerParty(adults=1),
        cabin_classes=("ECONOMY",),
        departure_window=("06:00", "21:00"),
        max_stops=1,
        max_duration_minutes=720,
        max_price_per_traveller_gbp=500.0,
        surface_segments=(
            GroundSegment("MCT", "DXB", "COACH", 22.0, 360),
        ),
        hotel_anchors=("The St. Regis Al Mouj Muscat", "Grosvenor House Dubai Marina"),
    ),
)

# Default holiday trip definition for December 2026
DEFAULT_HOLIDAY_TRIP_DEFINITION = TripDefinition(
    key=TripBucket.DEC_HOLIDAY_PACKAGES,
    label="December Holiday Packages: Turkey, Malta, Egypt",
    bucket=TripBucket.DEC_HOLIDAY_PACKAGES,
    outbound_origins=("LHR", "LGW", "LTN", "STN"),
    outbound_destinations=("AYT", "MLA", "CAI"),
    outbound_dates=("2026-12-20", "2026-12-22", "2026-12-24"),
    return_origins=("AYT", "MLA", "CAI"),
    return_destinations=("LHR", "LGW", "LTN", "STN"),
    return_dates=("2026-12-28", "2026-12-30", "2026-12-31"),
    passenger_party=PassengerParty(adults=2, children_ages=(23, 16, 20)),
    cabin_classes=("ECONOMY",),
    departure_window=("08:00", "18:00"),
    max_stops=1,
    max_duration_minutes=720,
    max_price_per_traveller_gbp=None,
)