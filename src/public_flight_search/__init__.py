"""Small, provider-neutral flight-offer filtering engine with multi-city support."""

from .engine import FlightOffer, SearchCriteria, search_offers
from .trip_config import (
    TripDefinition,
    TripBucket,
    PassengerParty,
    GroundSegment,
    DEFAULT_TRIP_DEFINITIONS,
    DEFAULT_HOLIDAY_TRIP_DEFINITION,
)
from .pairing import pair_outbound_return, combine_legs
from .booking_links import BookingLink, build_booking_links
from .cost_ledger import ItineraryCostLedger, build_cost_ledger
from .ground_transport import get_ground_assumptions, watford_to_airport
from .pareto import rank_bucket_sections
from .booking_links import build_booking_links

__all__ = [
    "FlightOffer",
    "SearchCriteria",
    "search_offers",
    "TripDefinition",
    "TripBucket",
    "PassengerParty",
    "GroundSegment",
    "DEFAULT_TRIP_DEFINITIONS",
    "DEFAULT_HOLIDAY_TRIP_DEFINITION",
    "pair_outbound_return",
    "combine_legs",
    "BookingLink",
    "build_booking_links",
    "ItineraryCostLedger",
    "build_cost_ledger",
    "get_ground_assumptions",
    "watford_to_airport",
    "rank_bucket_sections",
]
