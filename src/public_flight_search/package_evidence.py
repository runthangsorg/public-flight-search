"""Package-price evidence boundary for the public engine.

The private engine (on the private compute tiers only) reads tour-operator
package prices for the exact stay and exports the result to
``data/holiday_package_evidence.json`` (schema ``holiday_package_evidence/1``).
The workflow seeds that file alongside price history; it is never committed
(``.gitignore``).

This module is the **only** way such a price may reach a card, and it is an
honest seam rather than a scraper — the same contract as
:mod:`public_flight_search.hotel_evidence`, for the package half of the trip:

* every accepted price is re-validated here for season, exact dates, party
  size, room count, board basis, confidence and freshness;
* the price is a GBP figure the operator displayed, or — when the operator
  quotes per person, or per room for a two-room booking — the whole-party
  total the engine derived, carried with its own arithmetic on its face
  (``price_how``), so a per-person or per-room figure can never be read as a
  whole-party price;
* each price travels with its source URL and its observation time;
* a mismatched, room-only, unverified or aged price is dropped **with a stated
  reason** rather than quietly;
* a missing or unreadable file changes nothing about today's output.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
import sys
from typing import Any, Mapping, Optional

from .hotel_evidence import (
    DEAL_BOARDS,
    NO_MEAL_BOARDS,
    _normalise_property,
    _parse_observed_at,
    _run_season,
    _season_of,
)

#: Where the workflow lands the private engine's export. Same path both
#: planner workflows seed.
DEFAULT_PACKAGE_EVIDENCE_PATH = "data/holiday_package_evidence.json"

#: A package price goes stale faster than a flight fare: operators reprice by
#: the week. One week (168h) is the ceiling — an older read is not a price for
#: these dates any more, so it is dropped rather than shown.
PACKAGE_EVIDENCE_MAX_AGE_HOURS = 168

#: The document shape the private engine writes.
SCHEMA = "holiday_package_evidence/1"


def package_evidence_max_age_hours() -> int:
    """Freshness ceiling in hours; ``PACKAGE_EVIDENCE_MAX_AGE_HOURS`` overrides.

    An unparseable override falls back to the default rather than raising or,
    worse, defaulting to "no limit": the ceiling is a safety limit, so a typo
    in the environment must not silently remove it.
    """
    raw = os.getenv("PACKAGE_EVIDENCE_MAX_AGE_HOURS", "").strip()
    if not raw:
        return PACKAGE_EVIDENCE_MAX_AGE_HOURS
    try:
        value = int(raw)
    except ValueError:
        return PACKAGE_EVIDENCE_MAX_AGE_HOURS
    return value if value > 0 else PACKAGE_EVIDENCE_MAX_AGE_HOURS


@dataclass(frozen=True)
class PackagePrice:
    """One qualifying package price, with the provenance the card must show."""

    operator_key: str
    operator: str
    property_name: str
    destination_key: str
    season: str
    departure_airport: str
    outbound_date: str
    return_date: str
    nights: int
    adults: int
    children: int
    rooms: int
    board: str
    total_gbp: float
    #: ``whole_party_total`` — a figure the operator displayed for the party.
    #: ``per_person`` — the whole-party total the engine derived from a
    #: per-person figure; ``price_how`` says how.
    #: ``rooms_sum`` — the whole-party total the engine derived by adding the
    #: operator's per-room prices for a multi-room booking; ``price_how`` says
    #: how. This report's party is five, so a two-room booking is the normal
    #: shape rather than an exception.
    price_basis: str
    #: The exporter's own words for how a displayed figure became the total.
    price_how: str
    read_method: str
    link_kind: str
    source_url: str
    #: The raw observation string as exported; ``package_provenance`` parses it.
    observed_at: str
    flight_summary: str
    includes: tuple[str, ...]
    #: The cabin the PACKAGE's flights were searched in, as the exporter
    #: recorded it, or "" when it recorded none. Since dealsearch ``ff26b7a``
    #: the Destination2 adapter writes both this and ``flight_cabin_basis``;
    #: other adapters carry neither, and a record without this field can never
    #: promote a card's headline (owner brief 2026-10-04, H10 §2).
    flight_cabin: str = ""
    #: The exporter's own words for that choice, e.g. "searched as Class=E
    #: (destination2.py)". Shown on the card so the claim is checkable rather
    #: than taken on trust.
    flight_cabin_basis: str = ""
    #: What the operator put in each room of this booking, in the exporter's
    #: own words: ``"room 1: 2 adults, Melati Beach Resort and Spa - Grand
    #: Deluxe - Bed and Breakfast"``. Carried because a package-priced card has
    #: to describe the PACKAGE's rooms (BRIEF-H14 §3, 2026-10-05): the rooms
    #: the operator sold are the rooms the reader gets, and the catalogue's
    #: unit beside them described a different booking.
    room_descriptions: tuple[str, ...] = ()


#: Skips from the most recent load, surfaced in the job summary so an operator
#: sees exactly why a package stayed unpriced.
_SKIP_LOG: list[str] = []


def consume_package_skip_log() -> list[str]:
    """Return and clear the skip reasons recorded by the last load."""
    items = list(_SKIP_LOG)
    _SKIP_LOG.clear()
    return items


def _warn_skip(what: str, reason: str) -> None:
    message = f"{what or '?'}: {reason}"
    _SKIP_LOG.append(message)
    print(f"package-evidence: skipping {message}", file=sys.stderr)


#: The price bases this loader accepts. ``whole_party_total`` is a figure the
#: operator displayed for the party; ``per_person`` and ``rooms_sum`` are both
#: only usable through the engine's own ``derived_total_gbp``, which carries the
#: arithmetic on its face.
#:
#: ``rooms_sum`` is the shape a two-room booking arrives in: the operator
#: displays a price per room and the engine adds them. Five travellers cannot be
#: one room, so this is not a niche basis for this report's party - as of
#: 2026-10-04 every real record in the export is this basis.
_PRICE_BASES: tuple[str, ...] = ("whole_party_total", "per_person", "rooms_sum")

#: Bases whose total is the engine's sum rather than a figure the operator
#: displayed for the party. Both need ``derived_total_gbp`` to be usable.
_DERIVED_BASES: frozenset[str] = frozenset({"per_person", "rooms_sum"})


def _derived_total(item: dict) -> Optional[tuple[float, str]]:
    """``(value, how)`` from the engine's own derivation, or None.

    The exporter states the arithmetic and this module never repeats it: a total
    computed here would be a figure nobody published and nobody checked.
    """
    derived = item.get("derived_total_gbp")
    if not isinstance(derived, dict):
        return None
    try:
        value = float(derived.get("value"))
    except (TypeError, ValueError):
        return None
    how = str(derived.get("how", "")).strip()
    if value <= 0 or not how:
        return None
    return (value, how)


def _price_for(item: dict) -> Optional[tuple[float, str, str]]:
    """``(total_gbp, price_basis, price_how)`` for this record, or None.

    The card is priced in GBP. A ``whole_party_total`` is a figure the operator
    displayed for the party, so it is the total as shown. A ``per_person`` or
    ``rooms_sum`` figure is only usable through the engine's own
    ``derived_total_gbp``, which carries the arithmetic on its face — this
    module never multiplies a per-person price and never adds two room prices
    itself, because a computed figure must be traceable to the exporter, not
    re-derived here. Anything else prices nothing.
    """
    shown = item.get("price_shown")
    if not isinstance(shown, dict):
        return None
    currency = str(shown.get("currency", "")).strip().upper()
    if currency != "GBP":
        return None
    basis = str(shown.get("basis", "")).strip()
    if basis in _DERIVED_BASES:
        # Judged on the DERIVATION, not on the displayed figure. A rooms_sum
        # displays one room's price and the total is the sum, so requiring the
        # displayed amount to mean "the party" would be the wrong test - and
        # requiring it to be a positive number would reject a record whose
        # exporter left the per-room slot empty while still stating the total.
        derived = _derived_total(item)
        if derived is None:
            return None
        return (derived[0], basis, derived[1])
    try:
        amount = float(shown.get("amount"))
    except (TypeError, ValueError):
        return None
    if amount <= 0:
        return None
    if basis == "whole_party_total":
        return (amount, basis, "")
    return None


def _price_problem(item: dict) -> str:
    """The stated reason ``_price_for`` refused this record's price."""
    shown = item.get("price_shown")
    if not isinstance(shown, dict):
        return "price_shown missing or not an object"
    currency = str(shown.get("currency", "")).strip().upper()
    if currency != "GBP":
        return f"price_shown.currency must be GBP, got {currency or 'nothing'!r}"
    basis = str(shown.get("basis", "")).strip()
    if basis in _DERIVED_BASES:
        noun = "a per-person price" if basis == "per_person" else "a two-room sum"
        if _derived_total(item) is None:
            return f"{noun} needs a derived_total_gbp with a positive value and how"
        return "price could not be read"
    try:
        amount = float(shown.get("amount"))
    except (TypeError, ValueError):
        amount = None
    if amount is None or amount <= 0:
        return "price_shown.amount must be a positive figure as shown"
    if basis == "whole_party_total":
        return "price could not be read"
    return (
        f"price_shown.basis {basis!r} is not one of "
        + ", ".join(repr(name) for name in _PRICE_BASES)
    )


def load_package_evidence(
    config,
    *,
    path: str = DEFAULT_PACKAGE_EVIDENCE_PATH,
    now: Optional[str] = None,
    max_age_hours: Optional[int] = None,
) -> dict[tuple[str, str, str, str], PackagePrice]:
    """Load the package prices this run may price cards with, keyed by property.

    A record is kept only when every one of the brief's conditions holds:

    * its season is the season this run prices;
    * ``exact_date_match`` is true and the dates are a pair this run prices;
    * its party is the report's party and the booking is one or two rooms;
    * the board is breakfast or better (``RO`` is never a deal);
    * the confidence is ``verified-exact-date``;
    * it has a real http(s) source URL and is observed within ``max_age_hours``;
    * its price is a GBP figure: a displayed whole-party total, or a
      per-person or two-room price with the engine's own
      ``derived_total_gbp``.

    Two qualifying records for the same key keep the cheaper total. Anything
    else is skipped with a stated reason on stderr. A missing or unreadable
    file returns an empty mapping — today's output is unchanged, never a crash
    and never a fabricated figure.
    """
    _SKIP_LOG.clear()

    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        # A missing file is the normal case and says nothing: no skip entry, so
        # a non-empty skip log always means something WAS there and was refused.
        return {}
    except (json.JSONDecodeError, OSError) as exc:
        _warn_skip(path, f"unreadable: {type(exc).__name__}: {exc}")
        return {}

    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        found = payload.get("schema") if isinstance(payload, dict) else type(payload).__name__
        _warn_skip(path, f"schema is {found!r}, expected {SCHEMA!r}")
        return {}
    if not isinstance(payload.get("packages"), list):
        _warn_skip(path, "no packages list")
        return {}

    from .holidays import priceable_date_pairs

    priced_pairs = set(priceable_date_pairs(config))
    if not priced_pairs:
        return {}
    season = _run_season(config)
    travellers = int(getattr(config, "travellers", 0) or 0)
    ceiling = (max_age_hours if max_age_hours and max_age_hours > 0
               else package_evidence_max_age_hours())
    now_dt = _parse_observed_at(now) or datetime.now(timezone.utc)

    qualifying: dict[tuple[str, str, str, str], PackagePrice] = {}
    for index, item in enumerate(payload["packages"]):
        if not isinstance(item, dict):
            _warn_skip(f"#{index}", "not an object")
            continue
        name = str(item.get("property_name", "")).strip()
        if not name:
            _warn_skip(f"#{index}", "property_name missing")
            continue
        outbound = str(item.get("outbound_date", "")).strip()
        returning = str(item.get("return_date", "")).strip()

        record_season = str(item.get("season", "")).strip() or _season_of(outbound)
        if season and record_season and record_season != season:
            _warn_skip(name, f"season {record_season!r} is not the season this run prices ({season})")
            continue
        if not bool(item.get("exact_date_match", False)):
            _warn_skip(name, "exact_date_match is false — nearest dates are not these dates")
            continue
        if (outbound, returning) not in priced_pairs:
            _warn_skip(name, f"dates {outbound}..{returning} are not a pair this run prices")
            continue
        party = item.get("party") or {}
        adults = int(party.get("adults", 0) or 0) if isinstance(party, dict) else 0
        children = int(party.get("children", 0) or 0) if isinstance(party, dict) else 0
        if travellers and adults + children != travellers:
            _warn_skip(name, f"party {adults + children} != report party {travellers}")
            continue
        rooms = item.get("rooms")
        if rooms not in (1, 2):
            _warn_skip(name, f"rooms {rooms!r} is not 1 or 2")
            continue
        board = str(item.get("board", "")).strip().upper()
        if board not in DEAL_BOARDS:
            _warn_skip(
                name,
                NO_MEAL_BOARDS.get(board, f"board {board!r} is not breakfast or better"),
            )
            continue
        confidence = str(item.get("confidence", "")).strip()
        if confidence != "verified-exact-date":
            _warn_skip(
                name,
                f"confidence {confidence or 'missing'!r} is not verified-exact-date",
            )
            continue
        source_url = str(item.get("source_url", "")).strip()
        if not source_url.startswith(("http://", "https://")):
            _warn_skip(name, "source_url missing or not http(s)")
            continue
        observed_raw = str(item.get("observed_at", "")).strip()
        observed = _parse_observed_at(observed_raw)
        if observed is None:
            _warn_skip(name, "observed_at missing or unparseable")
            continue
        age_hours = (now_dt - observed).total_seconds() / 3600.0
        if age_hours < 0:
            _warn_skip(name, "observed_at is in the future")
            continue
        if age_hours > ceiling:
            _warn_skip(name, f"stale: observed {age_hours:.0f}h ago (max {ceiling}h)")
            continue
        priced = _price_for(item)
        if priced is None:
            _warn_skip(name, _price_problem(item))
            continue
        total_gbp, price_basis, price_how = priced

        try:
            nights = int(item.get("nights", 0) or 0)
        except (TypeError, ValueError):
            nights = 0
        includes = item.get("includes")
        if not isinstance(includes, list):
            includes = []
        flight_summary = item.get("flight_summary")
        if not isinstance(flight_summary, str):
            flight_summary = ""
        key = (name, outbound, returning, str(item.get("operator_key", "")).strip())
        entry = PackagePrice(
            operator_key=str(item.get("operator_key", "")).strip(),
            operator=str(item.get("operator", "")).strip(),
            property_name=name,
            destination_key=str(item.get("destination_key", "")).strip(),
            season=record_season,
            departure_airport=str(item.get("departure_airport", "")).strip(),
            outbound_date=outbound,
            return_date=returning,
            nights=nights,
            adults=adults,
            children=children,
            rooms=rooms,
            board=board,
            total_gbp=total_gbp,
            price_basis=price_basis,
            price_how=price_how,
            read_method=str(item.get("read_method", "")).strip(),
            link_kind=str(item.get("link_kind", "")).strip(),
            source_url=source_url,
            observed_at=observed_raw,
            flight_summary=flight_summary,
            includes=tuple(str(value) for value in includes),
            flight_cabin=str(item.get("flight_cabin", "") or "").strip().upper(),
            flight_cabin_basis=str(item.get("flight_cabin_basis", "") or "").strip(),
            room_descriptions=_room_descriptions(item),
        )
        previous = qualifying.get(key)
        if previous is None or entry.total_gbp < previous.total_gbp:
            qualifying[key] = entry
    return qualifying


def _room_descriptions(item: Mapping[str, Any]) -> tuple[str, ...]:
    """The exporter's per-room words, or () when it recorded none.

    Anything that is not a list of strings is dropped rather than coerced: this
    is the card's own description of the rooms it is selling, so a malformed
    record must not reach the page as text nobody wrote.
    """
    raw = item.get("room_descriptions")
    if not isinstance(raw, list):
        return ()
    return tuple(str(value).strip() for value in raw if str(value or "").strip())


def package_price_for(
    loaded,
    property_name: str,
    outbound: str,
    returning: str,
    operator_key: Optional[str] = None,
) -> Optional[PackagePrice]:
    """The cheapest qualifying price for this property and these dates, or None.

    The dates must match exactly: a price read for other nights is another
    price, and the loader has already rejected records whose dates were not
    exact. The property name is compared with punctuation and spacing removed,
    so a comma between the resort and the destination does not hide a price.
    """
    if not loaded:
        return None
    wanted = _normalise_property(property_name)
    matches = [
        entry
        for entry in loaded.values()
        if _normalise_property(entry.property_name) == wanted
        and entry.outbound_date == outbound
        and entry.return_date == returning
        and (operator_key is None or entry.operator_key == operator_key)
    ]
    if not matches:
        return None
    return min(matches, key=lambda entry: entry.total_gbp)


def cheapest_package_for_property(
    loaded,
    property_name: str,
    date_pairs=None,
    operator_key: Optional[str] = None,
) -> Optional[PackagePrice]:
    """The cheapest qualifying price for this property on ANY priced pair, or None.

    An exact-date lookup (``package_price_for``) is the right question for a
    card: the card has dates and the package must be for those dates. The
    OVER-BUDGET list asks a different question. Its rows are the resorts no
    option fits, so their own pair is by definition the expensive one — and the
    whole point of showing an operator's price there (brief H9, 2026-10-04) is
    to say "this property, on a nearby pair this run also prices, fits the
    budget". Refusing a read because it was for the neighbouring fortnight
    would delete exactly the sentence the owner asked for.

    So this helper matches on the property alone and lets the caller say which
    pairs count (``date_pairs``), defaulting to every pair the loader kept —
    the loader has already rejected records whose dates no run prices. The
    cheapest qualifying read wins, so one property can only ever be quoted once
    and never at its dearest.
    """
    if not loaded:
        return None
    wanted = _normalise_property(property_name)
    pairs = None if date_pairs is None else {tuple(pair) for pair in date_pairs}
    matches = [
        entry
        for entry in loaded.values()
        if _normalise_property(entry.property_name) == wanted
        and (
            pairs is None
            or (entry.outbound_date, entry.return_date) in pairs
        )
        and (operator_key is None or entry.operator_key == operator_key)
    ]
    if not matches:
        return None
    return min(matches, key=lambda entry: entry.total_gbp)


#: The only cabin a package may be promoted at (owner brief 2026-10-04, H10
#: §2). The owner's rule is business class for a direct flight and economy for
#: a one-stop, and an operator's package is a one-stop by construction — so a
#: package whose flights were searched in Business is NOT the holiday the card
#: now quotes, and promoting it would put a business price on an economy card.
PACKAGE_PROMOTABLE_CABIN = "ECONOMY"

#: A package whose flights are at least this many nights shorter than the row's
#: own trip is a different holiday, so the over-budget note must not say "fits
#: the budget" beside the row's own price: the reader would be comparing a
#: three-week holiday with a fortnight (owner brief, H10 addendum 2 P2-7). It
#: stays quotable, with its own nights named.
PACKAGE_NIGHTS_TOLERANCE = 2


def package_flown_economy(price: PackagePrice) -> bool:
    """True only when the record STATES the package's flights were economy.

    A missing ``flight_cabin`` is UNKNOWN, and unknown does not promote: a
    price whose cabin nobody recorded is not evidence of an economy fare, and
    promoting it is how a business package ends up as an economy headline.
    """
    return str(getattr(price, "flight_cabin", "") or "").strip().upper() == PACKAGE_PROMOTABLE_CABIN


def package_within_budget(price: PackagePrice, max_budget_gbp: Any) -> bool:
    """True when the whole-party total clears the run's ceiling."""
    try:
        return float(price.total_gbp) <= float(max_budget_gbp)
    except (TypeError, ValueError):
        return False


def package_nights(price: Any) -> Optional[int]:
    """How many nights this package is for, or None when it cannot be told.

    The exporter's stated ``nights`` wins, because disagreeing with it is
    exactly the failure this module is guarding: a record whose number and
    whose dates tell different stories is refused rather than believed. The
    dates are the fallback, and they are all a card's ``OperatorPackage``
    carries (it has no ``nights`` field of its own).
    """
    try:
        stated = int(getattr(price, "nights", 0) or 0)
    except (TypeError, ValueError):
        stated = 0
    if stated > 0:
        return stated
    from datetime import datetime as _datetime

    try:
        start = _datetime.strptime(
            str(getattr(price, "outbound_date", "") or ""), "%Y-%m-%d")
        end = _datetime.strptime(
            str(getattr(price, "return_date", "") or ""), "%Y-%m-%d")
        return (end - start).days
    except (TypeError, ValueError):
        return None


def package_covers_nights(price: Any, nights: Any) -> bool:
    """True when the package is for the SAME number of nights as the row.

    The loader already requires the exact date pair, so this is a belt-and-
    braces check: an exporter that disagreed with its own dates must not
    promote a card.
    """
    got = package_nights(price)
    try:
        return got is not None and got == int(nights)
    except (TypeError, ValueError):
        return False


def package_shortfall_nights(price: Any, nights: Any) -> Optional[int]:
    """How many nights SHORTER than the row's trip this package is, or None."""
    got = package_nights(price)
    try:
        if got is None:
            return None
        shortfall = int(nights) - got
    except (TypeError, ValueError):
        return None
    return shortfall if shortfall > 0 else None


def package_provenance(price: PackagePrice) -> str:
    observed = _parse_observed_at(price.observed_at)
    when = (
        f"{observed.day} {observed.strftime('%b %Y')}" if observed else "date unknown"
    )
    if price.price_basis == "per_person":
        basis = f"per-person price x {price.adults + price.children} as shown"
    elif price.price_basis == "rooms_sum":
        # The operator displayed a price per room; the total is the engine's
        # sum of the rooms, so the sentence must say that rather than claim the
        # operator displayed a party total.
        basis = f"{price.rooms} room prices added, as shown"
    else:
        basis = "whole-party total as shown"
    rooms = "room" if price.rooms == 1 else "rooms"
    return (
        f"package read {when} from {price.operator}, {price.board}, "
        f"{price.rooms} {rooms}, {basis}"
    )
