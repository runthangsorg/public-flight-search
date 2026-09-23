"""Multi-city trip definitions and passenger party models.

Provider-neutral trip shapes that define the search plan; live prices are
injected at runtime via encrypted config. No PII in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
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


# The digest runs twice a day, so its travel window has to roll. Absolute
# literals are correct on the day they are written and expire a fortnight
# later; after that every provider search returns zero cards and the job
# reports a misleading empty-collection failure. That is exactly how the
# digest died on 2026-09-22: green on 2026-09-03 with 13 paired
# itineraries, then zero forever, because the September window it had been
# searching since 2026-09-01 was in the past.
TRIP_LEAD_DAYS = 21        # first outbound date, counted from the run date
TRIP_OUTBOUND_DATES = 2    # consecutive candidate outbound dates
TRIP_NIGHTS = 11           # first return date, counted from the outbound date
TRIP_RETURN_DATES = 3      # consecutive candidate return dates


def rolling_trip_dates(today: date) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """Outbound and return candidate dates derived from ``today``.

    Returns ``(outbound_dates, return_dates)``. The literal window this
    replaced (out 2026-09-15/16, back 2026-09-26/27/28) is exactly what a
    2026-08-25 run date produces, so only the expiry changed, not the trip
    shape.
    """
    outbound_start = today + timedelta(days=TRIP_LEAD_DAYS)
    outbound = tuple(
        (outbound_start + timedelta(days=offset)).isoformat()
        for offset in range(TRIP_OUTBOUND_DATES)
    )
    return_start = outbound_start + timedelta(days=TRIP_NIGHTS)
    returning = tuple(
        (return_start + timedelta(days=offset)).isoformat()
        for offset in range(TRIP_RETURN_DATES)
    )
    return outbound, returning


def default_trip_definitions(
    today: date | None = None,
) -> Tuple[TripDefinition, ...]:
    """The UAE/Muscat digest trip windows, dated from ``today``.

    Job code should call this per run so the window is derived from the
    current date; the module constant below is dated once at import and
    exists for the public API and tests.
    """
    reference = today or datetime.now(timezone.utc).date()
    outbound_dates, return_dates = rolling_trip_dates(reference)
    return (
        TripDefinition(
            key=TripBucket.SEPT_UAE_ROUNDTRIP,
            label="Dubai / Abu Dhabi Round-trip",
            bucket=TripBucket.SEPT_UAE_ROUNDTRIP,
            outbound_origins=("LHR", "LGW", "LTN", "STN"),
            outbound_destinations=("DXB", "AUH"),
            outbound_dates=outbound_dates,
            return_origins=("DXB", "AUH"),
            return_destinations=("LHR", "LGW", "LTN", "STN"),
            return_dates=return_dates,
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
            outbound_dates=outbound_dates,
            return_origins=("DXB", "AUH"),
            return_destinations=("LHR", "LGW", "LTN", "STN"),
            return_dates=return_dates,
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


#: Dated at import time. Job code should prefer ``default_trip_definitions()``
#: so a long-lived process never searches a window that has since expired.
DEFAULT_TRIP_DEFINITIONS = default_trip_definitions()

#: The Christmas window a December holiday plan always describes: out on
#: 20/22/24 December, back on 28/30/31 December of the same year.
DECEMBER_HOLIDAY_OUTBOUND_DAYS = (20, 22, 24)
DECEMBER_HOLIDAY_RETURN_DAYS = (28, 30, 31)


def december_holiday_dates(year: int) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """``(outbound_dates, return_dates)`` for one year's Christmas window."""
    return (
        tuple(f"{year}-12-{day:02d}" for day in DECEMBER_HOLIDAY_OUTBOUND_DAYS),
        tuple(f"{year}-12-{day:02d}" for day in DECEMBER_HOLIDAY_RETURN_DAYS),
    )


def default_holiday_trip_definition(today: date | None = None) -> TripDefinition:
    """The December package trip window, dated from ``today``.

    WHY this is derived and not literal: this definition previously hardcoded
    ``2026-12-20``/``2026-12-22``/``2026-12-24``. That is the exact bug class
    that killed the flight digest on 2026-09-22 — an absolute window is
    correct on the day it is written and returns nothing forever after it
    expires. The Christmas shape is fixed; only the year rolls, and it rolls
    as soon as the first outbound date is no longer in the future, so the
    window this returns is always entirely ahead of the run date.
    """
    reference = today or datetime.now(timezone.utc).date()
    first_outbound = date(reference.year, 12, min(DECEMBER_HOLIDAY_OUTBOUND_DAYS))
    year = reference.year if reference < first_outbound else reference.year + 1
    outbound_dates, return_dates = december_holiday_dates(year)
    return TripDefinition(
        key=TripBucket.DEC_HOLIDAY_PACKAGES,
        label="December Holiday Packages: Turkey, Malta, Egypt",
        bucket=TripBucket.DEC_HOLIDAY_PACKAGES,
        outbound_origins=("LHR", "LGW", "LTN", "STN"),
        outbound_destinations=("AYT", "MLA", "CAI"),
        outbound_dates=outbound_dates,
        return_origins=("AYT", "MLA", "CAI"),
        return_destinations=("LHR", "LGW", "LTN", "STN"),
        return_dates=return_dates,
        passenger_party=PassengerParty(adults=2, children_ages=(23, 16, 20)),
        cabin_classes=("ECONOMY",),
        departure_window=("08:00", "18:00"),
        max_stops=1,
        max_duration_minutes=720,
        max_price_per_traveller_gbp=None,
    )


#: Dated at import time; prefer ``default_holiday_trip_definition()`` in job
#: code so a process that outlives December never searches an expired window.
DEFAULT_HOLIDAY_TRIP_DEFINITION = default_holiday_trip_definition()
