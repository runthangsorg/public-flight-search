"""Small, provider-neutral flight-offer filtering engine."""

from .engine import FlightOffer, SearchCriteria, search_offers
from .amadeus import AmadeusClient, build_google_flights_link

__all__ = [
    "FlightOffer",
    "SearchCriteria",
    "search_offers",
    "AmadeusClient",
    "build_google_flights_link",
]
