"""Cabin policy: BUSINESS only on a NONSTOP London flight over 8 hours.

Two owner rules, the second narrowing the first.

**Rule 1, 2026-09-28:** no premium economy anywhere, and BUSINESS only for a
flight OVER 8 hours from London; everything else is ECONOMY. The boundary
lives here, in code, not in each config: a config can no longer price a
four-hour hop in Business (the July 2027 example did, for six destinations,
and put two more in premium economy).

**Rule 2, 2026-10-04, verbatim:**

> you should only quote business class for direct flights, else always quote
> economy for when its 1 stopover (and we are staying at the stopoever, e.g.
> stop at oman on way out 2d, go thailand, then return 2d oman or maybe doha
> 2d).

**Rule 2 adds a necessary condition to rule 1: the flight must be NONSTOP.**
A one-stop journey is ECONOMY however long it takes, a two-centre trip is
ECONOMY, a hub-stopover itinerary (two nights at the hub each way) is
ECONOMY, and so is any nonstop of 8 hours or less. The owner confirmed the
short end of the band in the same breath: "all under 8 hours is economy" and
"doha and muscat economy is fine" — which is what rule 1 already said, and
which rule 2 leaves standing. The 8.0 hour boundary stays a single constant,
``BUSINESS_FLIGHT_HOURS``.

The cabin is derived from two facts per destination:

* ``nonstop_from_london`` — whether a London nonstop service exists **on the
  trip's dates**. This is a destination-level, SEASONAL fact (a route that
  flies October to April is not nonstop in July), which is why it lives in the
  config rather than only in a table here. ``nonstop_source`` records who said
  so and when it was read, so the claim is auditable.
* ``flight_hours`` — the nonstop block time where one exists, otherwise the
  fastest standard one-stop through journey (both flights plus a minimum
  connection), because that is the time actually spent getting there. Taking
  only the London leg would call Phuket-via-Doha a 6h45 "short haul".

**UNKNOWN MEANS NOT NONSTOP, therefore ECONOMY.** A destination whose config
says nothing about a nonstop is quoted as economy, never as business.
Guessing business is exactly how the old bug priced short hops in Business,
and "we did not check" is not evidence that a nonstop exists.

8.0 exactly is not OVER eight hours, so it is ECONOMY; the pinned boundary
tests are 7.9 -> ECONOMY and 8.1 -> BUSINESS, both with a nonstop stated.
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
    "riviera_maya": 11.02,   # CUN nonstop (Virgin Atlantic 11h01) — that service
                              # ends 11 Apr 2027, so a July config states its own
                              # connected hours rather than inheriting this one
    "okinawa": 16.5,         # OKA via Tokyo: no London nonstop, 2h40 domestic
                              # hop, about 16h30 door to door (read 2026-10-04)
}

#: Destination keys whose London service is a YEAR-ROUND nonstop, for configs
#: that carry no ``nonstop_from_london`` of their own. Deliberately small.
#:
#: This table may hold year-round facts only, because a nonstop that runs for
#: part of the year is not a year-round fact: a legacy config naming Phuket
#: without the field must price ECONOMY (the season is unknown, and unknown
#: means not nonstop), and one naming Cancun — whose Virgin Atlantic service
#: ends 11 Apr 2027 — must too. Every destination that needs business states
#: its own ``nonstop_from_london`` with a ``nonstop_source``.
#:
#: Everything in here is under 8 hours from London and therefore already
#: ECONOMY under the hour rule, so the set never changes an answer today. It
#: exists so a legacy config's nonstop claim stays TRUE rather than
#: accidentally inverted if the hour boundary ever moves.
YEAR_ROUND_NONSTOP_LHR: frozenset[str] = frozenset({
    "malta", "taghazout", "madeira", "lanzarote", "fuerteventura",
    "tenerife", "gran_canaria", "antalya", "paphos", "cairo", "hurghada",
    "cape_verde", "doha", "muscat",
})


def cabin_for_flight_hours(
    flight_hours: Any, nonstop_from_london: Any = None
) -> str:
    """Derive the cabin: BUSINESS only on a NONSTOP flight over 8.0 h.

    ``nonstop_from_london`` is the owner's second condition (2026-10-04). It
    defaults to ``None``, which is UNKNOWN, and unknown means NOT nonstop: a
    one-stop journey is ECONOMY however long it takes. That default is the
    safe direction on purpose — it is the failure this rule exists to stop.
    """
    if flight_hours is None:
        raise ValueError("flight_hours is required to derive a cabin")
    try:
        hours = float(flight_hours)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"flight_hours is not a number: {flight_hours!r}") from exc
    if hours <= 0:
        raise ValueError(f"flight_hours must be positive, got {hours}")
    if not _states_nonstop(nonstop_from_london):
        return SHORT_HAUL_CABIN
    return LONG_HAUL_CABIN if hours > BUSINESS_FLIGHT_HOURS else SHORT_HAUL_CABIN


def _states_nonstop(value: Any) -> bool:
    """True only when the value says YES, in the shapes a config may use.

    ``None`` and every non-boolean spelling are UNKNOWN, and unknown is
    False. ``True``/``"true"`` are the only answers that promote a route to
    business, so a typo reads as economy rather than as a claim nobody made.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return False


def resolve_flight_hours(key: str, explicit: Optional[float]) -> Optional[float]:
    """The destination's own hours, else the built-in table, else None."""
    if explicit is not None:
        return float(explicit)
    return DEFAULT_FLIGHT_HOURS_LHR.get(str(key or "").lower())


def resolve_nonstop_from_london(key: str, explicit: Any) -> bool:
    """Whether a London nonstop exists for this destination. Unknown = False.

    A config's own ``nonstop_from_london`` wins whenever it says anything at
    all. Only when it says nothing does the year-round table apply, and that
    table carries year-round services only — so a seasonal nonstop has to be
    stated by the config that knows its season.
    """
    if explicit is not None:
        return _states_nonstop(explicit)
    return str(key or "").lower() in YEAR_ROUND_NONSTOP_LHR


def is_long_haul_route(hours: Any) -> bool:
    """True when the London journey is over 8 hours, whatever cabin it prices.

    Deliberately separate from the cabin. "Long haul" answers "is this a long
    flight?", and a one-stop Zanzibar at 11h40 is one; "Business" answers "what
    do we quote?", and the owner quotes Economy for it (2026-10-04). The report
    shows its flight-option comparison on long-haul ROUTES — the two-nights-at
    the-hub stopover rows are the point of that comparison, and the owner's own
    rule is to fly one — while the Business row appears only on the routes it
    quotes Business for.
    """
    if hours is None:
        return False
    try:
        return float(hours) > BUSINESS_FLIGHT_HOURS
    except (TypeError, ValueError):
        return False


def is_long_haul_destination(destination: Any) -> bool:
    """``is_long_haul_route`` for a loaded destination, using resolved hours."""
    return is_long_haul_route(
        resolve_flight_hours(
            getattr(destination, "key", ""),
            getattr(destination, "flight_hours", None),
        )
    )


def destination_cabin(destination: Any) -> str:
    """The one cabin the report prices for this destination.

    Raises ``ValueError`` for a destination with no hours of its own and no
    built-in entry: guessing a cabin is how a short hop got priced in
    Business.
    """
    key = getattr(destination, "key", "")
    hours = resolve_flight_hours(key, getattr(destination, "flight_hours", None))
    return cabin_for_flight_hours(
        hours,
        resolve_nonstop_from_london(
            key, getattr(destination, "nonstop_from_london", None)
        ),
    )