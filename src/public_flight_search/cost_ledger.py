"""Itinerary cost ledger for whole-party door-to-door pricing.

All costs in GBP. Estimates require checkout-day revalidation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from datetime import date, datetime, timezone


@dataclass
class ItineraryCostLedger:
    """Complete cost breakdown for a multi-city itinerary.

    All fields default to 0.0 and must be populated before use.
    """
    # Flight costs
    base_airfare: float = 0.0
    fare_family: str = "STANDARD"
    checked_baggage_cost: float = 0.0
    seat_selection_cost: float = 0.0
    payment_fee: float = 0.0

    # Ground transport costs
    london_ground_out_cost: float = 0.0
    london_ground_in_cost: float = 0.0
    uae_ground_transfer_cost: float = 0.0
    oman_to_uae_transfer_cost: float = 0.0
    muscat_taxi_cost: float = 10.0

    # Metadata
    baggage_basis: str = "STD"  # STD, VALUE, BASIC, etc.
    payment_method: str = "CARD"
    computed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def normalized_flight_cost(self) -> float:
        """Airfare + baggage + seat + payment (whole party)."""
        return round(
            self.base_airfare
            + self.checked_baggage_cost
            + self.seat_selection_cost
            + self.payment_fee,
            2,
        )

    @property
    def total_ground_cost(self) -> float:
        """All surface transport (whole party)."""
        return round(
            self.london_ground_out_cost
            + self.london_ground_in_cost
            + self.uae_ground_transfer_cost
            + self.oman_to_uae_transfer_cost
            + self.muscat_taxi_cost,
            2,
        )

    @property
    def total_all_in_door_to_door(self) -> float:
        """Complete door-to-door cost for the entire party."""
        return round(self.normalized_flight_cost + self.total_ground_cost, 2)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "base_airfare": self.base_airfare,
            "fare_family": self.fare_family,
            "checked_baggage_cost": self.checked_baggage_cost,
            "seat_selection_cost": self.seat_selection_cost,
            "payment_fee": self.payment_fee,
            "normalized_flight_cost": self.normalized_flight_cost,
            "london_ground_out_cost": self.london_ground_out_cost,
            "london_ground_in_cost": self.london_ground_in_cost,
            "uae_ground_transfer_cost": self.uae_ground_transfer_cost,
            "oman_to_uae_transfer_cost": self.oman_to_uae_transfer_cost,
            "muscat_taxi_cost": self.muscat_taxi_cost,
            "total_ground_cost": self.total_ground_cost,
            "total_all_in_door_to_door": self.total_all_in_door_to_door,
            "baggage_basis": self.baggage_basis,
            "payment_method": self.payment_method,
            "computed_at": self.computed_at,
        }


@dataclass
class AncillaryQuote:
    """Fare family ancillary details for a specific airline."""
    fare_family: str
    cabin_baggage: str
    included_baggage_kg: int
    baggage_uplift_gbp: float
    in_flight_meal: str
    seat_selection: str
    modification_policy: str
    cancellation_policy: str
    observed_at: str
    provenance: str  # LIVE_VERIFIED, FRESH_DIRECT, CACHED_HISTORICAL, etc.


# Fare family baggage parsers per airline
def parse_fare_family_baggage(airline: str, fare_family: str) -> tuple[int, float, bool]:
    """Returns (included_kg, upgrade_cost_gbp, is_included)."""
    air_clean = airline.strip().lower()
    fam_clean = (fare_family or "").strip().lower()

    if "etihad" in air_clean:
        if "basic" in fam_clean:
            return 0, 45.0, False
        elif "value" in fam_clean:
            return 25, 0.0, True
        elif "comfort" in fam_clean:
            return 30, 0.0, True
        elif "deluxe" in fam_clean:
            return 35, 0.0, True
        return 25, 0.0, True

    elif "oman air" in air_clean:
        if "super saver" in fam_clean:
            return 0, 40.0, False
        elif "lite" in fam_clean or "smart" in fam_clean or "prime" in fam_clean:
            return 30, 0.0, True
        return 30, 0.0, True

    elif "air arabia" in air_clean:
        if "basic" in fam_clean:
            return 0, 27.0, False
        elif "value" in fam_clean:
            return 20, 0.0, True
        elif "ultimate" in fam_clean:
            return 30, 0.0, True
        return 20, 0.0, True

    elif "pegasus" in air_clean:
        if "basic" in fam_clean:
            return 0, 35.0, False
        elif "essentials" in fam_clean or "advantage" in fam_clean:
            return 20, 0.0, True
        return 0, 35.0, False

    elif "wizz" in air_clean:
        if "basic" in fam_clean:
            return 0, 45.0, False
        elif "go" in fam_clean or "plus" in fam_clean:
            return 20, 0.0, True
        return 0, 45.0, False

    elif "emirates" in air_clean:
        if "special" in fam_clean:
            return 20, 0.0, True
        elif "saver" in fam_clean:
            return 25, 0.0, True
        return 30, 0.0, True

    return 20, 0.0, True


def build_cost_ledger(
    airfare: float,
    fare_family: str,
    airline: str,
    traveller_count: int,
    checked_bag_count: int = 1,
    checked_bag_target_kg: int = 20,
    london_ground_out: float = 0.0,
    london_ground_in: float = 0.0,
    uae_ground: float = 0.0,
    oman_uae_transfer: float = 0.0,
    muscat_taxi: float = 10.0,
) -> ItineraryCostLedger:
    """Build a cost ledger from component prices."""
    included_kg, uplift, included = parse_fare_family_baggage(airline, fare_family)
    target_total = traveller_count * checked_bag_count * checked_bag_target_kg
    included_total = included_kg * traveller_count if included else 0
    shortfall = max(0, target_total - included_total)
    baggage_cost = uplift * traveller_count * checked_bag_count if shortfall > 0 else 0.0

    ledger = ItineraryCostLedger(
        base_airfare=airfare,
        fare_family=fare_family,
        checked_baggage_cost=baggage_cost,
        seat_selection_cost=0.0,  # Assume standard seat included
        payment_fee=0.0,
        london_ground_out_cost=london_ground_out,
        london_ground_in_cost=london_ground_in,
        uae_ground_transfer_cost=uae_ground,
        oman_to_uae_transfer_cost=oman_uae_transfer,
        muscat_taxi_cost=10.0,
        baggage_basis="STD",
    )
    return ledger