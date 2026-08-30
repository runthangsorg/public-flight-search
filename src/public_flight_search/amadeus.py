"""Amadeus Flight Offers Search API — direct JSON quotes, no scraping or captchas."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from .stealth import stealth_get, stealth_post

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://api.amadeus.com/v1/security/oauth2/token"
_SEARCH_URL = "https://api.amadeus.com/v2/shopping/flight-offers"

_AIRLINE_NAMES: dict[str, str] = {
    "BA": "British Airways",
    "EK": "Emirates",
    "EY": "Etihad Airways",
    "QR": "Qatar Airways",
    "TK": "Turkish Airlines",
    "SV": "Saudia",
    "WY": "Oman Air",
    "GF": "Gulf Air",
    "LH": "Lufthansa",
    "AF": "Air France",
    "KL": "KLM",
    "MS": "EgyptAir",
    "U2": "easyJet",
    "FR": "Ryanair",
    "LX": "Swiss",
    "AY": "Finnair",
    "TP": "TAP Air Portugal",
    "IB": "Iberia",
    "VY": "Vueling",
    "EW": "Eurowings",
    "PC": "Pegasus Airlines",
    "RJ": "Royal Jordanian",
    "W6": "Wizz Air",
    "U8": "Air Arabia",
}


def _parse_iso_duration(iso_duration: str) -> int:
    """Parse ISO 8601 duration to minutes. e.g. PT10H30M -> 630."""
    try:
        duration = iso_duration.replace("PT", "")
        hours = 0
        minutes = 0
        if "H" in duration:
            parts = duration.split("H")
            hours = int(parts[0])
            if len(parts) > 1 and "M" in parts[1]:
                minutes = int(parts[1].replace("M", ""))
        elif "M" in duration:
            minutes = int(duration.replace("M", ""))
        return hours * 60 + minutes
    except (ValueError, IndexError):
        return 0


def _extract_baggage(traveler_pricing: dict) -> tuple[bool, str]:
    """Extract baggage info from fare details. Returns (included, weight_str)."""
    try:
        fare_details = traveler_pricing.get("fareDetailsBySegment", [])
        if fare_details:
            first_segment = fare_details[0]
            included_bags = first_segment.get("includedCheckedBags", {})
            weight = included_bags.get("weight")
            quantity = included_bags.get("quantity", 0)
            if weight:
                return True, f"{weight}kg"
            elif quantity and quantity > 0:
                return True, f"{quantity} bag(s)"
            return False, "Hand only"
    except Exception:
        pass
    return False, "Unknown"


def _build_airline_name(code: str) -> str:
    return _AIRLINE_NAMES.get(code, code)


def build_google_flights_link(
    origin: str,
    destination: str,
    date: str,
    adults: int = 1,
    cabin: str = "economy",
) -> str:
    """Build a pre-filled Google Flights search URL for 1-click booking."""
    query = (
        f"one way flights from {origin} to {destination} on {date} "
        f"{adults} adults {cabin} cabin"
    )
    return "https://www.google.com/travel/flights?q=" + quote(query, safe="") + "&curr=GBP&hl=en-GB"


class AmadeusClient:
    """Amadeus Flight Offers Search API client using stealth HTTP."""

    def __init__(self) -> None:
        self._client_id = os.environ.get("AMADEUS_CLIENT_ID", "")
        self._client_secret = os.environ.get("AMADEUS_CLIENT_SECRET", "")
        self._token: str = ""
        self._token_expires: float = 0.0

    @property
    def is_configured(self) -> bool:
        return bool(self._client_id and self._client_secret)

    def _get_token(self) -> str:
        """Obtain or refresh an Amadeus OAuth2 token."""
        now = datetime.now(timezone.utc).timestamp()
        if self._token and now < self._token_expires:
            return self._token

        response = stealth_post(
            _TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        if response is None or response.status_code != 200:
            logger.error("Amadeus token request failed: %s", getattr(response, "status_code", "no response"))
            return ""

        body = response.json()
        self._token = body.get("access_token", "")
        expires_in = body.get("expires_in", 3000)
        self._token_expires = now + expires_in - 60
        return self._token

    def search_flights(
        self,
        *,
        origin: str,
        destination: str,
        departure_date: str,
        adults: int = 1,
        cabin: str = "ECONOMY",
        max_results: int = 10,
        currency: str = "GBP",
    ) -> list[dict[str, Any]]:
        """Search one-way flights via Amadeus. Returns list of offer dicts."""
        if not self.is_configured:
            logger.info("Amadeus not configured; skipping API search")
            return []

        token = self._get_token()
        if not token:
            return []

        response = stealth_get(
            _SEARCH_URL,
            headers={"Authorization": f"Bearer {token}"},
            params={
                "originLocationCode": origin,
                "destinationLocationCode": destination,
                "departureDate": departure_date,
                "adults": adults,
                "travelClass": cabin,
                "currencyCode": currency,
                "max": str(max_results),
            },
            timeout=20,
        )

        if response is None or response.status_code != 200:
            logger.error("Amadeus search failed: %s", getattr(response, "status_code", "no response"))
            return []

        body = response.json()
        raw_offers = body.get("data", [])
        return [self._parse_offer(offer, origin, destination, departure_date, adults) for offer in raw_offers]

    def _parse_offer(
        self,
        offer_data: dict,
        origin: str,
        destination: str,
        date: str,
        adults: int,
    ) -> dict[str, Any]:
        """Parse an Amadeus offer into a normalized dict."""
        price_info = offer_data.get("price", {})
        total_price = float(price_info.get("grandTotal", 0))
        currency = price_info.get("currency", "GBP")

        itineraries = offer_data.get("itineraries", [])
        first_itin = itineraries[0] if itineraries else {}
        segments = first_itin.get("segments", [])

        first_seg = segments[0] if segments else {}
        last_seg = segments[-1] if segments else first_seg

        airline_code = first_seg.get("carrierCode", "")
        dep_time = first_seg.get("departure", {}).get("at", "")
        arr_time = last_seg.get("arrival", {}).get("at", "")
        dep_time_str = dep_time[11:16] if len(dep_time) > 11 else "00:00"
        arr_time_str = arr_time[11:16] if len(arr_time) > 11 else "00:00"

        duration_mins = _parse_iso_duration(first_itin.get("duration", "PT0H"))
        stops = len(segments) - 1
        stop_airports = [seg.get("arrival", {}).get("iataCode", "") for seg in segments[:-1]]

        traveler_pricings = offer_data.get("travelerPricings", [{}])
        baggage_included, baggage_weight = _extract_baggage(traveler_pricings[0] if traveler_pricings else {})

        cabin = "ECONOMY"
        if traveler_pricings:
            fare_details = traveler_pricings[0].get("fareDetailsBySegment", [{}])
            if fare_details:
                cabin = fare_details[0].get("cabin", "ECONOMY")

        booking_url = build_google_flights_link(
            origin=origin,
            destination=destination,
            date=date,
            adults=adults,
            cabin="business" if cabin == "BUSINESS" else "economy",
        )

        return {
            "id": offer_data.get("id", ""),
            "source": "amadeus",
            "airline": _build_airline_name(airline_code),
            "airline_code": airline_code,
            "origin": origin,
            "destination": destination,
            "departure_date": date,
            "departure_time": dep_time_str,
            "arrival_time": arr_time_str,
            "duration_minutes": duration_mins,
            "stops": stops,
            "stop_airports": stop_airports,
            "price": total_price,
            "price_per_traveller": total_price / adults if adults else total_price,
            "currency": currency,
            "cabin_class": cabin,
            "baggage_included": baggage_included,
            "baggage_weight": baggage_weight,
            "booking_url": booking_url,
            "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "review_status": "amadeus_api_result",
        }


def search_flights_amadeus(
    *,
    origin: str,
    destination: str,
    departure_date: str,
    adults: int = 1,
    cabin: str = "ECONOMY",
    max_results: int = 10,
) -> list[dict[str, Any]]:
    """Convenience wrapper for Amadeus flight search."""
    client = AmadeusClient()
    return client.search_flights(
        origin=origin,
        destination=destination,
        departure_date=departure_date,
        adults=adults,
        cabin=cabin,
        max_results=max_results,
    )
