"""Small, provider-neutral flight-offer filtering engine."""

from .engine import FlightOffer, SearchCriteria, search_offers

__all__ = [
    "FlightOffer",
    "SearchCriteria",
    "search_offers",
]
