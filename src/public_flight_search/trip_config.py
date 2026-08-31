"""Configurable trip definitions — replaces hardcoded PII from private repo.

All personal data (home address, hotel names, family ages, specific dates)
is loaded from runtime JSON config, never hardcoded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple


class CabinClass:
    ECONOMY = "ECONOMY"
    BUSINESS = "BUSINESS"
    MIXED = "MIXED"


class BusinessProductType:
    LIE_FLAT = "LIE_FLAT"
    ANGLED_FLAT = "ANGLED_FLAT"
    RECLINER = "RECLINER"
    EURO_BUSINESS = "EURO_BUSINESS"
    UNKNOWN = "UNKNOWN"


class TicketStructure:
    PROTECTED_SINGLE_PNR = "PROTECTED_SINGLE_PNR"
    TWO_INDEPENDENT_PROTECTED_TICKETS = "TWO_INDEPENDENT_PROTECTED_TICKETS"
    UNBUNDLED_SELF_TRANSFER = "UNBUNDLED_SELF_TRANSFER"
    UNSAFE_SELF_TRANSFER = "UNSAFE_SELF_TRANSFER"


class EvidenceStatus:
    LIVE_VERIFIED = "LIVE_VERIFIED"
    LIVE = "LIVE"
    FRESH_DIRECT = "FRESH_DIRECT"
    FRESH_META = "FRESH_META"
    CACHED_HISTORICAL = "CACHED_HISTORICAL"
    UNVERIFIED = "UNVERIFIED"
    STALE = "STALE"


DEFAULT_SCORING_WEIGHTS = {
    "price_value": 0.30,
    "door_to_door_hassle": 0.20,
    "preferred_dates_timing": 0.15,
    "cabin_quality": 0.15,
    "connections_protection": 0.10,
    "airport_convenience": 0.05,
    "historical_attractiveness": 0.05,
}


@dataclass(frozen=True)
class PassengerParty:
    base_adult_count: int = 1
    additional_ages: Tuple[int, ...] = ()

    @property
    def total_travellers(self) -> int:
        return self.base_adult_count + len(self.additional_ages)

    @property
    def airline_adult_count(self) -> int:
        return self.base_adult_count + sum(1 for age in self.additional_ages if age >= 12)


@dataclass(frozen=True)
class TripDefinition:
    key: str
    label: str
    outbound_origins: Tuple[str, ...]
    outbound_destinations: Tuple[str, ...]
    return_origins: Tuple[str, ...]
    return_destinations: Tuple[str, ...]
    outbound_date_from: str
    outbound_date_to: str
    return_date_from: str
    return_date_to: str
    preferred_outbound_date: str = ""
    preferred_return_date: str = ""
    surface_segments: Tuple[Tuple[str, str], ...] = ()
    hotel_anchors: Tuple[str, ...] = ()
    passenger_party: PassengerParty = PassengerParty()
    preferred_departure_window: Tuple[str, str] = ("00:00", "23:59")
    hard_departure_window: bool = False
    checked_bag_count: int = 1
    checked_bag_target_kg: int = 20
    include_package_search: bool = False


@dataclass(frozen=True)
class SearchRequest:
    bucket: str
    direction: str
    origins: Tuple[str, ...]
    destinations: Tuple[str, ...]
    date_from: str
    date_to: str
    cabin_class: str
    base_adult_count: int = 1
    additional_ages: Tuple[int, ...] = ()
    checked_bag_count: int = 1
    checked_bag_target_kg: int = 20
    preferred_departure_window: Tuple[str, str] = ("00:00", "23:59")
    hard_departure_window: bool = False
    include_package_search: bool = False

    @property
    def airline_adult_count(self) -> int:
        return self.base_adult_count + sum(age >= 12 for age in self.additional_ages)


def build_search_plan(trips: Tuple[TripDefinition, ...]) -> list[SearchRequest]:
    plan: list[SearchRequest] = []
    for trip in trips:
        for cabin in (CabinClass.ECONOMY, CabinClass.BUSINESS):
            plan.append(SearchRequest(
                bucket=trip.key, direction="OUTBOUND",
                origins=trip.outbound_origins, destinations=trip.outbound_destinations,
                date_from=trip.outbound_date_from, date_to=trip.outbound_date_to,
                cabin_class=cabin, base_adult_count=trip.passenger_party.base_adult_count,
                additional_ages=trip.passenger_party.additional_ages,
                checked_bag_count=trip.checked_bag_count,
                checked_bag_target_kg=trip.checked_bag_target_kg,
                preferred_departure_window=trip.preferred_departure_window,
                hard_departure_window=trip.hard_departure_window,
                include_package_search=trip.include_package_search,
            ))
            plan.append(SearchRequest(
                bucket=trip.key, direction="RETURN",
                origins=trip.return_origins, destinations=trip.return_destinations,
                date_from=trip.return_date_from, date_to=trip.return_date_to,
                cabin_class=cabin, base_adult_count=trip.passenger_party.base_adult_count,
                additional_ages=trip.passenger_party.additional_ages,
                checked_bag_count=trip.checked_bag_count,
                checked_bag_target_kg=trip.checked_bag_target_kg,
                preferred_departure_window=trip.preferred_departure_window,
                hard_departure_window=trip.hard_departure_window,
                include_package_search=trip.include_package_search,
            ))
    return plan


def load_trip_definitions_from_config(config: Dict[str, Any]) -> Tuple[TripDefinition, ...]:
    """Build TripDefinition objects from a JSON-compatible config dict.

    Config format:
    {
        "trips": [
            {
                "key": "MUSCAT_OPEN_JAW",
                "label": "Muscat + UAE Open Jaw",
                "outbound_origins": ["LHR", "LGW", "LTN", "STN"],
                "outbound_destinations": ["MCT"],
                "return_origins": ["DXB", "AUH", "SHJ"],
                "return_destinations": ["LHR", "LGW", "LTN", "STN"],
                "outbound_date_from": "2026-09-15",
                "outbound_date_to": "2026-09-16",
                "return_date_from": "2026-09-26",
                "return_date_to": "2026-09-28",
                "preferred_outbound_date": "2026-09-16",
                "preferred_return_date": "2026-09-27",
                "surface_segments": [["MCT", "DXB"]],
                "hotel_anchors": [],
                "passenger_party": {"base_adult_count": 2, "additional_ages": []},
                "preferred_departure_window": ["08:00", "22:00"],
                "hard_departure_window": true,
                "checked_bag_count": 5,
                "checked_bag_target_kg": 20,
                "include_package_search": false
            }
        ]
    }
    """
    trips = []
    for raw in config.get("trips", []):
        party_raw = raw.get("passenger_party", {})
        party = PassengerParty(
            base_adult_count=int(party_raw.get("base_adult_count", 1)),
            additional_ages=tuple(party_raw.get("additional_ages", ())),
        )
        trips.append(TripDefinition(
            key=raw["key"],
            label=raw["label"],
            outbound_origins=tuple(raw["outbound_origins"]),
            outbound_destinations=tuple(raw["outbound_destinations"]),
            return_origins=tuple(raw["return_origins"]),
            return_destinations=tuple(raw["return_destinations"]),
            outbound_date_from=raw["outbound_date_from"],
            outbound_date_to=raw["outbound_date_to"],
            return_date_from=raw["return_date_from"],
            return_date_to=raw["return_date_to"],
            preferred_outbound_date=raw.get("preferred_outbound_date", ""),
            preferred_return_date=raw.get("preferred_return_date", ""),
            surface_segments=tuple(tuple(s) for s in raw.get("surface_segments", [])),
            hotel_anchors=tuple(raw.get("hotel_anchors", [])),
            passenger_party=party,
            preferred_departure_window=tuple(raw.get("preferred_departure_window", ("00:00", "23:59"))),
            hard_departure_window=raw.get("hard_departure_window", False),
            checked_bag_count=int(raw.get("checked_bag_count", party.total_travellers)),
            checked_bag_target_kg=int(raw.get("checked_bag_target_kg", 20)),
            include_package_search=raw.get("include_package_search", False),
        ))
    return tuple(trips)
