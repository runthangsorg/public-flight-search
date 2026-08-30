"""Validate and rank provider flight-offer data without claiming verification."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Mapping, Optional, Tuple
from urllib.parse import urlsplit


_AIRPORT = re.compile(r"^[A-Z]{3}$")


def _clean_text(value: Any, *, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return "".join(char for char in text if char.isprintable())[:limit]


def _airport(value: Any) -> str:
    code = _clean_text(value, limit=3).upper()
    if not _AIRPORT.fullmatch(code):
        raise ValueError("airport codes must contain exactly three ASCII letters")
    return code


def _https_url(value: Any) -> str:
    url = _clean_text(value, limit=2048)
    parts = urlsplit(url)
    if parts.scheme == "https" and parts.netloc:
        return url
    return ""


@dataclass(frozen=True)
class SearchCriteria:
    origins: frozenset[str] = frozenset()
    destinations: frozenset[str] = frozenset()
    max_stops: int = 2
    max_duration_minutes: int = 1440
    max_price: Optional[float] = None
    currency: Optional[str] = None


@dataclass(frozen=True)
class FlightOffer:
    origin: str
    destination: str
    departure: str
    price: float
    currency: str
    stops: int
    duration_minutes: int
    provider: str
    booking_url: str = ""

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "FlightOffer":
        origin = _airport(raw.get("origin"))
        destination = _airport(raw.get("destination"))
        departure = _clean_text(raw.get("departure"), limit=40)
        if not departure:
            raise ValueError("departure is required")
        datetime.fromisoformat(departure.replace("Z", "+00:00"))

        price = float(raw.get("price"))
        if not math.isfinite(price) or price <= 0:
            raise ValueError("price must be positive and finite")

        currency = _clean_text(raw.get("currency"), limit=3).upper()
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise ValueError("currency must be an ISO-style three-letter code")

        stops = int(raw.get("stops"))
        duration = int(raw.get("duration_minutes"))
        if not 0 <= stops <= 4 or not 1 <= duration <= 1440:
            raise ValueError("stops or duration is out of bounds")

        provider = _clean_text(raw.get("provider"), limit=80)
        if not provider:
            raise ValueError("provider is required")

        return cls(
            origin=origin,
            destination=destination,
            departure=departure,
            price=price,
            currency=currency,
            stops=stops,
            duration_minutes=duration,
            provider=provider,
            booking_url=_https_url(raw.get("booking_url")),
        )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "origin": self.origin,
            "destination": self.destination,
            "departure": self.departure,
            "price": round(self.price, 2),
            "currency": self.currency,
            "stops": self.stops,
            "duration_minutes": self.duration_minutes,
            "provider": self.provider,
            "booking_url": self.booking_url,
            "review_status": "unverified_provider_result",
        }


def search_offers(
    raw_offers: Iterable[Mapping[str, Any]], criteria: SearchCriteria
) -> Tuple[FlightOffer, ...]:
    """Return valid provider results matching explicit generic criteria."""
    results = []
    origins = {value.upper() for value in criteria.origins}
    destinations = {value.upper() for value in criteria.destinations}
    wanted_currency = (criteria.currency or "").upper()

    for raw in raw_offers:
        try:
            offer = FlightOffer.from_mapping(raw)
        except (KeyError, TypeError, ValueError):
            continue
        if origins and offer.origin not in origins:
            continue
        if destinations and offer.destination not in destinations:
            continue
        if offer.stops > criteria.max_stops:
            continue
        if offer.duration_minutes > criteria.max_duration_minutes:
            continue
        if criteria.max_price is not None and offer.price > criteria.max_price:
            continue
        if wanted_currency and offer.currency != wanted_currency:
            continue
        results.append(offer)

    return tuple(
        sorted(
            results,
            key=lambda item: (item.price, item.duration_minutes, item.departure),
        )
    )
