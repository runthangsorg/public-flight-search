"""Cabin policy: BUSINESS only when the flight is over 8 hours from London.

Owner rule (2026-09-28): no premium economy anywhere, and BUSINESS only for a
flight OVER 8 hours from London; everything else is ECONOMY. The boundary
lives here, in code, not in each config: a config can no longer price a
four-hour hop in Business (the July 2027 example did, for six destinations,
and put two more in premium economy).

The cabin is derived from a per-destination ``flight_hours``:

* where a nonstop London service exists, its scheduled block time;
* where none exists, the fastest standard one-stop through journey (both
  flights plus a minimum connection), because that is the time actually spent
  getting there. Taking only the London leg would call Phuket-via-Doha a
  6h45 "short haul".

8.0 exactly is not OVER eight hours, so it is ECONOMY; the pinned boundary
tests are 7.9 -> ECONOMY and 8.1 -> BUSINESS.
"""

from __future__ import annotations

from typing import Any, Optional

BUSINESS_FLIGHT_HOURS = 8.0  # strictly greater-than
LONG_HAUL_CABIN = "BUSINESS"
SHORT_HAUL_CABIN = "ECONOMY"
#: Banned outright by the same rule AS A DESTINATION'S HEADLINE/DERIVED CABIN.
#: Legacy configs that still name it load (the live December secret predates
#: the rule) but it is never priced as the headline. Owner direction
#: 2026-09-30 added a Premium Economy row to the per-card "Flight options"
#: comparison (holidays.py's _flight_options) alongside Business and Economy —
#: that is a reader-visible comparison line, never a destination's own
#: cabin_class/watch cabin, so it does not reopen the bug this rule fixed.
BANNED_CABINS = frozenset({"PREMIUM_ECONOMY"})

#: Built-in London flight hours per destination key, used when a config
#: destination carries no ``flight_hours`` of its own (legacy configs, such as
#: the live December secret until it is reloaded). Every committed example
#: carries its own hours and a ``flight_hours_source``; this table mirrors
#: them. Approximate scheduled times, rounded to the nearest few minutes.
DEFAULT_FLIGHT_HOURS_LHR: dict[str, float] = {
    # Nonstop short/medium haul from London
    "malta": 3.25,
    "taghazout": 3.75,       # AGA
    "madeira": 3.75,         # FNC
    "lanzarote": 4.0,        # ACE
    "fuerteventura": 4.25,   # FUE
    "tenerife": 4.5,         # TFS
    "gran_canaria": 4.5,     # LPA
    "antalya": 4.5,          # AYT
    "paphos": 4.75,          # PFO
    "cairo": 5.0,            # CAI
    "hurghada": 5.25,        # HRG
    "cape_verde": 6.0,       # SID
    "doha": 6.75,            # DOH
    "muscat": 7.33,          # MCT, the one near the line: 7h10-7h20 typical
    # Far East, nonstop from London
    "phuket": 12.17,         # Virgin Atlantic seasonal nonstop from 2026-10-18
    "singapore": 13.0,
    "japan": 14.25,          # Tokyo HND/NRT, routed around Russian airspace
    # Far East, no nonstop: fastest standard one-stop through journey
    "krabi": 14.5,           # via BKK
    "phu_quoc": 15.0,        # via BKK or SGN
    "da_nang": 15.0,         # via BKK/HAN/SGN; serves Hoi An
    "langkawi": 15.5,        # via KUL
    "penang": 15.5,          # via KUL
    "kota_kinabalu": 17.0,   # via KUL
    "bali": 17.25,           # via SIN
    # July long-haul beach keys: fastest protected one-stop journey Google
    # Flights listed for LHR 20 Jul 2027 (read 2026-09-29).
    "khao_lak": 14.5,        # HKT via BKK (THAI 14h30); then ~1h40 by road
    "koh_samui": 14.92,      # USM via BKK (EVA Air + Bangkok Airways 14h55)
    "koh_phangan": 14.92,    # USM as above, then the resort boat (~40 min)
    "lombok": 24.0,          # LOP via SIN (Singapore Airlines + Scoot, 24h)
    # Africa and Mexico (Google Flights, LHR, read 2026-09-29).
    "zanzibar": 11.67,       # ZNZ via ADD (Ethiopian 11h40 Dec; 11h55 Jul)
    "mauritius": 14.42,      # MRU via CDG (Air France + Air Mauritius 14h25); no nonstop listed
    "riviera_maya": 11.02,   # CUN nonstop (Virgin Atlantic 11h01)
}


def cabin_for_flight_hours(flight_hours: Any) -> str:
    """Derive the cabin from flight hours: BUSINESS only if over 8.0 h."""
    if flight_hours is None:
        raise ValueError("flight_hours is required to derive a cabin")
    try:
        hours = float(flight_hours)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"flight_hours is not a number: {flight_hours!r}") from exc
    if hours <= 0:
        raise ValueError(f"flight_hours must be positive, got {hours}")
    return LONG_HAUL_CABIN if hours > BUSINESS_FLIGHT_HOURS else SHORT_HAUL_CABIN


def resolve_flight_hours(key: str, explicit: Optional[float]) -> Optional[float]:
    """The destination's own hours, else the built-in table, else None."""
    if explicit is not None:
        return float(explicit)
    return DEFAULT_FLIGHT_HOURS_LHR.get(str(key or "").lower())


def destination_cabin(destination: Any) -> str:
    """The one cabin the report prices for this destination.

    Raises ``ValueError`` for a destination with no hours of its own and no
    built-in entry: guessing a cabin is how a short hop got priced in Business.
    """
    hours = resolve_flight_hours(
        getattr(destination, "key", ""), getattr(destination, "flight_hours", None)
    )
    return cabin_for_flight_hours(hours)
