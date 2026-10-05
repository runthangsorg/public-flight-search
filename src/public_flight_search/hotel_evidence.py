"""Hotel-rate evidence boundary for the public engine.

The private engine (on the private compute tiers only) drives a real browser,
reads the rate the hotel or brand actually rendered for the exact stay, and
exports the result to ``data/holiday_hotel_evidence.json``. The workflow seeds
that file alongside price history; it is never committed (``.gitignore``).

This module is the **only** way such a rate may reach a card, and it is an
honest seam rather than a scraper — the same contract as
:mod:`public_flight_search.live_verify`, for the hotel half of the trip:

* every accepted rate is re-validated here for season, exact dates, party size,
  booking shape, board basis and freshness;
* a rate read for ANOTHER pair stays loaded, and ``hotel_rates_near`` hands it
  out nearest-first so a card may be priced from a real nightly rather than a
  catalogue guess (BRIEF-H14 §1). That holds for a pair OUTSIDE the run's own
  departure window too (BRIEF-H15 §1): such a read is marked
  ``pair_is_priceable`` False and can never be an exact-date price, because
  no pair this run prices is that pair; the caller decides whether the board
  and the booking shape are the card's;
* the price is either a GBP ``public`` figure the site displayed, or a
  ``derived_gbp`` conversion that carries its own arithmetic on its face, so a
  converted amount can never be read as a GBP price;
* each rate travels with its terms, its source URL and its observation time;
* a unit check refuses the party only when the EXPORTER said so
  (``refuses_party``, BRIEF-H17 §1), and the wording is read — narrowly, as a
  refusal and its party in one clause within six words — only for records that
  state nothing;
* an aged, mismatched or room-only rate is dropped **with a stated reason**
  rather than quietly;
* a missing or unreadable file changes nothing about today's output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
import re
import sys
from typing import Any, Optional

#: Where the workflow lands the private engine's export. Same path both
#: planner workflows seed (H1, 2026-10-03).
DEFAULT_HOTEL_EVIDENCE_PATH = "data/holiday_hotel_evidence.json"

#: A hotel rate goes stale faster than a flight fare: a room is repriced by
#: the week, not the day. One week (168h) is the ceiling — an older read is
#: not a price for these dates any more, so it is dropped rather than shown.
HOTEL_EVIDENCE_MAX_AGE_HOURS = 168

#: Booking shapes that satisfy the one-booking rule: the whole party is in a
#: single booking, so the total on it is the total for the party. These are
#: the values the engine actually writes — an earlier version of this list
#: guessed ``one_unit`` and dropped every real villa with "not one booking".
ONE_BOOKING_SHAPES: frozenset[str] = frozenset(
    {"single_unit", "two_rooms_one_booking"}
)

#: ``price_basis`` values the engine writes.
TOTAL_STAY_BASES: frozenset[str] = frozenset({"total_stay_rate"})
NIGHTLY_BASES: frozenset[str] = frozenset({"nightly_room_rate"})

#: Boards that count as a holiday deal: meals included, at least breakfast.
#: The owner's breakfast-minimum rule, and this is the engine's vocabulary
#: rather than a guess — ``SC`` (self-catering) was wrongly accepted once
#: already, because it includes no meals, exactly as ``RO`` does not either.
DEAL_BOARDS: frozenset[str] = frozenset({"BB", "HB", "FB", "AI"})

#: Boards that include no meals, with the reason shown when one is dropped.
#: Naming the code alone ("SC") tells an operator nothing about why their rate
#: vanished from the report.
NO_MEAL_BOARDS: dict[str, str] = {
    "RO": "no breakfast (room only)",
    "SC": "no breakfast (self-catering)",
}

#: ``facts.field`` values the card knows how to render. A fact outside this
#: set is not something this card can present, so it is kept out rather than
#: mixed into lines a reader will act on.
HOTEL_FACT_FIELDS: frozenset[str] = frozenset(
    {
        "beach",
        "board_offer",
        "breakfast",
        "breakfast_style",
        "kids_club",
        "nearest_mosque",
        "pools",
        "pools_kids_restaurants",
        "restaurants",
        "restaurants_bars",
        "transfer_distance",
        "transfer_time",
    }
)


def hotel_evidence_max_age_hours() -> int:
    """Freshness ceiling in hours; ``HOTEL_EVIDENCE_MAX_AGE_HOURS`` overrides.

    An unparseable override falls back to the default rather than raising or,
    worse, defaulting to "no limit": the ceiling is a safety limit, so a typo
    in the environment must not silently remove it.
    """
    raw = os.getenv("HOTEL_EVIDENCE_MAX_AGE_HOURS", "").strip()
    if not raw:
        return HOTEL_EVIDENCE_MAX_AGE_HOURS
    try:
        value = int(raw)
    except ValueError:
        return HOTEL_EVIDENCE_MAX_AGE_HOURS
    return value if value > 0 else HOTEL_EVIDENCE_MAX_AGE_HOURS


@dataclass(frozen=True)
class HotelRate:
    """One qualifying rate, with the provenance the card must show."""

    property_name: str
    destination_key: str
    season: str
    vendor: str
    check_in: str
    check_out: str
    nights: int
    rate_name: str
    board: str
    price_gbp: float
    #: ``public`` — a GBP figure the site displayed. ``derived`` — a
    #: conversion, which ``price_label`` says is one.
    price_basis: str
    price_label: str
    currency: str
    #: ``total_stay_rate``, ``nightly_x_nights``, or ``unknown``.
    stay_basis: str
    refundable: bool
    terms: tuple[str, ...]
    source_url: str
    observed_at: str
    booking_shape: str
    party_adults: int = 0
    #: The exporter's own words for how a derived figure was derived.
    price_how: str = ""
    #: The cancellation and payment terms as published, for the card's
    #: booking-terms line. Empty when the page published none — never
    #: inferred from the rate name.
    cancellation: str = ""
    payment: str = ""
    #: Who sells this rate: an online travel agent, or the hotel itself. The
    #: card says so, because an aggregator's price is not the hotel's price.
    provider: str = ""
    #: True when the page stated whether the rate is refundable. False means
    #: "not stated", which is NOT the same as non-refundable.
    refundable_stated: bool = True
    #: The units as the hotel states them ("5 guests", "3 bedrooms"). The
    #: exporter's field names differ by source, so the wording is carried
    #: rather than re-derived from an assumed schema.
    units: tuple[str, ...] = ()
    #: None means the page did not say whether taxes are included.
    taxes_included: Optional[bool] = None


@dataclass(frozen=True)
class UnitCheck:
    property_name: str
    finding: str
    source_url: str
    observed_at: str
    destination_key: str = ""
    #: The dates this check was made for; empty when the engine did not say.
    dates: tuple[str, ...] = ()
    #: The EXPORTER'S OWN answer to the only question this report asks of a
    #: unit check: does this property refuse the party in one booking? BRIEF-H17
    #: §1 (2026-10-06). ``True`` removes the resort, ``False`` never does —
    #: whatever the wording beside it says, which is the whole point: a finding
    #: may quote a page that says "no rooms available" (sold out, not a
    #: refusal) or a note that an estimate "cannot be re-checked" (nothing to do
    #: with the hotel), and a text matcher reads either as a refusal.
    #:
    #: ``None`` means the exporter stated nothing, and only then does
    #: ``unit_check_blocks_party`` fall back to the wording — narrowly, because
    #: a fallback that guesses is what drops a card for a hotel that does take
    #: five adults.
    refuses_party: Optional[bool] = None


@dataclass(frozen=True)
class HotelRating:
    property_name: str
    source: str
    score: float
    scale: float
    review_count: str
    where: str
    source_url: str
    observed_at: str


@dataclass(frozen=True)
class HotelFact:
    property_name: str
    field: str
    stated: str
    where: str
    source_url: str
    observed_at: str


@dataclass(frozen=True)
class BlockedSource:
    what: str
    property_name: str
    reason: str
    source_url: str
    observed_at: str


@dataclass(frozen=True)
class HotelEvidence:
    """What one property may be priced and described with, for one date pair."""

    property_name: str
    destination_key: str
    season: str
    check_in: str
    check_out: str
    booking_shape: str
    #: The cheapest qualifying rate.
    cheapest: HotelRate
    #: The refundable rate when it is a different rate; None when the
    #: cheapest is already refundable. Never a second copy of the cheapest.
    flexible: Optional[HotelRate]
    #: Every qualifying rate, cheapest first. The card needs the whole set: a
    #: refundable "super advance saver" is frequently the CHEAPER rate, and
    #: showing only the cheapest would hide the bookable one.
    rates: tuple[HotelRate, ...] = ()
    unit_checks: tuple[UnitCheck, ...] = ()
    ratings: tuple[HotelRating, ...] = ()
    facts: tuple[HotelFact, ...] = ()
    blocked: tuple[BlockedSource, ...] = ()
    #: False when this read's own pair is not one this run prices (BRIEF-H15
    #: §1, 2026-10-05). The read is still loaded — same property, same board,
    #: same unit, same season, read on a real pair — and may carry a nightly
    #: onto another pair's nights as a labelled estimate. It can never be the
    #: price for the pair it was read for, because this run does not price
    #: that pair at all: ``hotel_rate_for`` refuses it, so "exact" stays exact.
    pair_is_priceable: bool = True


#: Skips from the most recent load, surfaced in the job summary so an
#: operator sees exactly why a property stayed unpriced.
_SKIP_LOG: list[str] = []

#: How this load's unit checks were decided (BRIEF-H17 §3): ``field`` counts the
#: ones the exporter answered for with ``refuses_party``, ``text`` the ones that
#: fell back to the wording. The second number is the fallback's REACH, and it
#: is the one that matters operationally: every check in it is a card whose
#: existence depends on a six-word proximity rule rather than on an answer, so
#: it is where an exporter that stops emitting the field would start costing
#: cards. Belongs to THIS load, like ``_SKIP_LOG``.
_UNIT_CHECK_BASIS: dict[str, int] = {}


def consume_hotel_unit_check_basis() -> dict[str, int]:
    """Return and clear how this load's unit checks were decided.

    Keys: ``total``, ``field``, ``text``.
    """
    basis = dict(_UNIT_CHECK_BASIS)
    _UNIT_CHECK_BASIS.clear()
    return basis


def _tally_unit_check_basis() -> None:
    """Count every unit check this load holds, by the mechanism that decides it.

    Counted over the loaded records rather than over the calls, so the number is
    a property of the evidence file and not of how many resorts and date pairs
    the collector happened to walk.
    """
    total = by_field = 0
    for entry in _SUPPLEMENTAL_BY_PROPERTY.values():
        for check in entry.get("unit_checks", ()) or ():
            total += 1
            if getattr(check, "refuses_party", None) is not None:
                by_field += 1
    _UNIT_CHECK_BASIS.clear()
    _UNIT_CHECK_BASIS.update({"total": total, "field": by_field,
                              "text": total - by_field})


def consume_hotel_skip_log() -> list[str]:
    """Return and clear the skip reasons recorded by the last load."""
    items = list(_SKIP_LOG)
    _SKIP_LOG.clear()
    return items


def _warn_skip(what: str, reason: str) -> None:
    message = f"{what or '?'}: {reason}"
    _SKIP_LOG.append(message)
    print(f"hotel-evidence: skipping {message}", file=sys.stderr)


def _parse_observed_at(raw: str) -> Optional[datetime]:
    try:
        value = datetime.fromisoformat(str(raw).strip().replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def _season_of(date_str: str) -> str:
    from .holidays import SUMMER_TRIP_MONTHS, WINTER_TRIP_MONTHS

    parts = str(date_str).split("-")
    if len(parts) < 2 or not parts[1].isdigit():
        return ""
    month = int(parts[1])
    if month in SUMMER_TRIP_MONTHS:
        return "summer"
    if month in WINTER_TRIP_MONTHS:
        return "winter"
    return ""


def _run_season(config) -> str:
    """The season this run prices, from the pairs it will price."""
    from .holidays import priceable_date_pairs

    for pair in sorted(priceable_date_pairs(config)):
        season = _season_of(pair[0])
        if season:
            return season
    return ""


#: A resort name that spells out the conjunction where the catalogue uses the
#: ampersand, or the other way round: "Melati Beach Resort and Spa" against
#: "Melati Beach Resort & Spa". The word form only counts when it stands alone,
#: so "Banyan Tree" and "Anderson Resort" keep every letter they have.
_CONJUNCTION = re.compile(r"(?<![a-z0-9])and(?![a-z0-9])")


def _normalise_property(name: str) -> str:
    """A hotel name reduced to comparable letters and digits.

    Exporters and resort catalogues punctuate the same hotel differently
    ("Pullman Lombok, Merujani Mandalika Beach Resort" vs the same without the
    comma), so matching must not depend on punctuation or spacing or a card
    misses its own rate over a comma.

    ``&`` and a spelled-out ``and`` are the same character of a name, so both
    are dropped rather than one of them being kept as letters: dropping the
    ampersand alone left "Melati Beach Resort and Spa" unable to find its own
    card, because the catalogue's "&" vanished and the exporter's "and" did not.
    The rule is monotone - it only ever removes MORE from both sides - so it
    cannot un-match a pair that used to match; measured against both shipped
    evidence files it moved nothing (0 gained, 0 lost).
    """
    text = _CONJUNCTION.sub(" ", str(name).lower()).replace("&", " ")
    return "".join(character for character in text if character.isalnum())


def hotel_rate_for(loaded, property_name: str, check_in: str, check_out: str):
    """The evidence for this property and these dates, or None.

    The dates must match exactly: a rate read for other nights is another
    rate, and the loader has already rejected records whose dates were not
    exact. A read for a pair this run does not PRICE is refused here as well
    (BRIEF-H15 §1): it is a real nightly for the same room, but "the rate for
    these dates" can only be a rate read for a pair the report offers, and this
    one is not one. It stays loaded for ``hotel_rates_near``.
    """
    if not loaded:
        return None
    wanted = _normalise_property(property_name)
    for key, entry in loaded.items():
        if not entry.pair_is_priceable:
            continue
        if _normalise_property(entry.property_name) != wanted:
            continue
        if entry.check_in == check_in and entry.check_out == check_out:
            return entry
    return None


def _day_gap(first: Any, second: Any) -> Optional[int]:
    """Days between two ISO dates, or None when either will not parse."""
    try:
        left = datetime.fromisoformat(str(first)[:10])
        right = datetime.fromisoformat(str(second)[:10])
    except (TypeError, ValueError):
        return None
    return abs((left - right).days)


def hotel_rates_near(
    loaded,
    property_name: str,
    check_in: str,
    check_out: str,
    *,
    booking_shape: Optional[str] = None,
):
    """This property's reads for OTHER pairs, nearest first.

    BRIEF-H14 §1 (2026-10-05). A read for a different set of dates is not this
    stay's price, but it is a real nightly for the same room, same party and
    same season — and the card it prices must never fall back to a catalogue
    guess while that read sits in the same evidence file. Since BRIEF-H15 §1
    that includes a read for a pair outside the run's own departure window: the
    loader keeps those (marked ``pair_is_priceable`` False, which stops them
    being an exact-date price) precisely so they can be reached here. The
    caller decides which of these it may use (same board, same unit); this only
    answers "how near, and in what order".

    Nearness is measured on both ends of the stay — a read that starts and ends
    closest to the pair wanted is the nearest — and ties break on the shorter
    difference in nights, then on the earlier check-in, so the order is a
    property of the evidence and never of the dict's iteration order.
    """
    if not loaded:
        return ()
    wanted = _normalise_property(property_name)
    found = []
    for entry in loaded.values():
        if _normalise_property(entry.property_name) != wanted:
            continue
        if entry.check_in == check_in and entry.check_out == check_out:
            continue
        if booking_shape and str(entry.cheapest.booking_shape or "") != booking_shape:
            continue
        rate = entry.cheapest
        if int(getattr(rate, "nights", 0) or 0) < 1:
            continue
        if not float(getattr(rate, "price_gbp", 0.0) or 0.0) > 0:
            continue
        start_gap = _day_gap(entry.check_in, check_in)
        end_gap = _day_gap(entry.check_out, check_out)
        if start_gap is None or end_gap is None:
            continue
        found.append((start_gap + end_gap, abs(int(rate.nights) - _nights_between(
            check_in, check_out)), entry.check_in, entry))
    return tuple(row[3] for row in sorted(found, key=lambda row: row[:3]))


def _nights_between(check_in: str, check_out: str) -> int:
    try:
        left = datetime.fromisoformat(str(check_in)[:10])
        right = datetime.fromisoformat(str(check_out)[:10])
    except (TypeError, ValueError):
        return 0
    return max(0, (right - left).days)


def hotel_rate_provenance(rate: HotelRate) -> str:
    """One sentence a reader can check: when, from whom, and on what basis."""
    observed = _parse_observed_at(rate.observed_at)
    when = (
        f"{observed.day} {observed.strftime('%b %Y')}" if observed else "date unknown"
    )
    parts = [f"rate read {when}"]
    if rate.vendor:
        parts.append(rate.vendor)
    sentence = ", ".join(parts)
    if rate.price_basis == "derived":
        how = rate.price_how or "converted from the displayed price"
        sentence = f"{sentence}; {how}"
    elif rate.price_basis == "public" and rate.stay_basis == "nightly_x_nights":
        sentence = f"{sentence}; {rate.currency} nightly rate x {rate.nights} nights"
    return sentence


def _stated(entry: Any, field_name: str) -> str:
    """A published term value, or "" when the page published none.

    The aggregator rows publish ``null`` for terms they did not read. Reading
    that as ``str(None)`` printed the word "None" on the card as though the
    hotel had said it — a null means not stated, and stays empty.
    """
    if not isinstance(entry, dict):
        return ""
    value = entry.get(field_name)
    if value is None:
        return ""
    return str(value).strip()


def _stated_flag(entry: Any, field_name: str) -> Optional[bool]:
    """A stated yes/no, or ``None`` when the record did not state one.

    Only a real boolean counts. A missing key, a null and a string are all the
    same thing here — the exporter did not answer — and answering them with
    ``False`` would let a text matcher's guess stand in for an answer nobody
    gave (BRIEF-H17 §1).
    """
    if not isinstance(entry, dict):
        return None
    value = entry.get(field_name)
    return value if isinstance(value, bool) else None


def _terms_by_field(rate: dict) -> tuple[str, str]:
    """(cancellation, payment) as published, across the units in the booking.

    A booking of two rooms can publish different terms per room; the card
    shows the union of what was stated rather than picking one room's terms
    for the whole party.
    """
    seen: dict[str, list[str]] = {"cancellation": [], "payment": []}
    for entry in rate.get("terms") or []:
        if not isinstance(entry, dict):
            continue
        for field_name in seen:
            value = _stated(entry, field_name)
            if value and value not in seen[field_name]:
                seen[field_name].append(value)
    return ("; ".join(seen["cancellation"]), " · ".join(seen["payment"]))


def _terms_for(rate: dict, *, refundable: bool) -> tuple[str, ...]:
    """Human-readable terms lines, in the order the card shows them."""
    lines: list[str] = []
    for entry in rate.get("terms") or []:
        if not isinstance(entry, dict):
            continue
        unit = _stated(entry, "unit")
        for field_name, prefix in (
            ("cancellation", "Cancellation"),
            ("payment", "Payment"),
        ):
            value = _stated(entry, field_name)
            if not value:
                continue
            lines.append(f"{unit}: {prefix} — {value}" if unit else f"{prefix} — {value}")
    # No published terms is NOT the same as non-refundable terms, so nothing is
    # invented here: the card reports that no terms were published, and
    # ``refundable`` stays False because flexibility was never established.
    return tuple(lines)


def _published_public_total(rate: dict) -> Optional[float]:
    """The sum of the rates the page displayed, across the units booked.

    Two key names for the same thing: a brand or direct site publishes
    ``public`` (the stay or nightly figure), a Google Hotels aggregator row
    publishes ``nightly`` and names the provider selling it.
    """
    shown = rate.get("prices_shown")
    if not isinstance(shown, list):
        return None
    total = 0.0
    seen = False
    for entry in shown:
        if not isinstance(entry, dict):
            continue
        for key in ("public", "nightly"):
            try:
                value = float(entry.get(key))
            except (TypeError, ValueError):
                continue
            if value > 0:
                total += value
                seen = True
                break
    return total if seen else None


def _provider_of(rate: dict) -> str:
    """The provider that sells this rate, from the priced entry."""
    shown = rate.get("prices_shown")
    if not isinstance(shown, list):
        return ""
    for entry in shown:
        if isinstance(entry, dict):
            name = str(entry.get("provider", "")).strip()
            if name:
                return name
    return ""


def _unit_lines(rate: dict) -> tuple[str, ...]:
    """Units as the hotel states them, in the exporter's own words.

    Brand rows give ``adults``/``max_persons_stated``; aggregator rows give
    ``guests_stated``/``bedrooms_stated``. Whatever was published is carried;
    nothing is inferred from a field that is absent, because "3 bedrooms" is
    the hotel's claim and our arithmetic about occupancy is not.
    """
    units = rate.get("units")
    if not isinstance(units, list):
        return ()
    lines: list[str] = []
    for entry in units:
        if not isinstance(entry, dict):
            continue
        parts = [str(entry.get(key, "")).strip()
                 for key in ("name", "guests_stated", "bedrooms_stated",
                             "adults", "max_persons_stated", "size_m2")]
        text = " — ".join(part for part in parts[:4] if part)
        if entry.get("size_m2") is not None:
            size = str(entry.get("size_m2")).strip()
            if size:
                text = f"{text} — {size} m²" if text else f"{size} m²"
        if text:
            lines.append(text)
    return tuple(lines)


def _float_field(payload: Any) -> Optional[float]:
    if not isinstance(payload, dict):
        return None
    try:
        value = float(payload.get("value"))
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _taxes_words(rate: dict) -> str:
    stated = rate.get("taxes_included")
    if stated is True:
        return "tax included"
    if stated is False:
        return "taxes excluded"
    return "taxes not stated"


def _price_for(rate: dict) -> Optional[tuple[float, str, str, str, str]]:
    """``(gbp, basis, label, stay_basis, how)`` for this rate, or None.

    The card is priced in GBP, so a rate in another currency can only reach it
    through the exporter's own conversion. In order:

    1. a displayed GBP ``total_stay_rate`` - that figure IS the price of the
       stay, so it is the one thing here that is a ``public`` price;
    2. the exporter's ``derived_public_total`` where it is already in GBP -
       derived, because it is a sum rather than a displayed stay total;
    3. a displayed GBP ``nightly_room_rate`` multiplied by the nights - the
       hotel publishes a nightly figure, so the stay total is derived from it;
    4. ``derived_gbp`` for any other currency - always labelled a conversion.

    Anything else prices nothing. A EUR figure with no GBP conversion is not a
    GBP rate, and this module exists to stop arithmetic becoming a price.
    """
    currency = str(rate.get("currency", "")).strip().upper()
    basis_raw = str(rate.get("price_basis", "")).strip()
    public_total = _published_public_total(rate)
    derived_total = _float_field(rate.get("derived_public_total"))
    nights = rate.get("nights")
    try:
        nights = int(nights)
    except (TypeError, ValueError):
        nights = 0

    if basis_raw in NIGHTLY_BASES:
        stay_basis = "nightly_x_nights"
    elif basis_raw in TOTAL_STAY_BASES:
        stay_basis = "total_stay_rate"
    else:
        stay_basis = basis_raw or "unknown"

    if currency == "GBP":
        if public_total and basis_raw in TOTAL_STAY_BASES:
            return (
                float(public_total),
                "public",
                f"£{public_total:,.0f} total price for the stay, "
                f"{_taxes_words(rate)}, as displayed in GBP",
                stay_basis,
                "",
            )
        # The aggregator rows publish the stay total themselves, in
        # ``derived_stay_total``, having done the nightly x nights arithmetic
        # against the listing they read. Their own description of it is shown.
        stay_total = _float_field(rate.get("derived_stay_total"))
        stay_currency = str((rate.get("derived_stay_total") or {}).get(
            "currency", "")).strip().upper()
        if stay_total and stay_currency in ("", currency):
            how = str((rate.get("derived_stay_total") or {}).get(
                "how", "")).strip() or "the stay total the listing published"
            return (
                float(stay_total),
                "derived",
                f"£{stay_total:,.0f} derived: {how}, {_taxes_words(rate)}",
                stay_basis,
                how,
            )
        if public_total and basis_raw in NIGHTLY_BASES and nights > 0:
            # Before ``derived_public_total``: the hotel published a nightly
            # figure, so the stay total is nightly x nights and the card can
            # show that arithmetic. The exporter's own total is the fallback
            # for a nightly rate with no unit prices to multiply.
            total = float(public_total) * nights
            # The brief's wording verbatim, with the figures the reader needs
            # to check the arithmetic themselves.
            how = (f"nightly x {nights} nights "
                   f"(£{public_total:,.0f} per night)")
            return (
                total,
                "derived",
                f"£{total:,.0f} derived: {how}, {_taxes_words(rate)}",
                stay_basis,
                how,
            )
        if derived_total:
            how = _derived_how(rate, "sum of the units published rates")
            return (
                float(derived_total),
                "derived",
                f"£{derived_total:,.0f} derived: {how}, {_taxes_words(rate)}",
                stay_basis,
                how,
            )

    converted = _float_field(rate.get("derived_gbp"))
    if converted is None:
        return None
    how = str((rate.get("derived_gbp") or {}).get("how", "")).strip()
    how = how or "converted from the displayed price"
    # The disclaimer is the point of this branch, so it is stated unless the
    # exporter's own wording already says it (appending it twice reads like
    # two different conversions).
    if "not a gbp price" not in how.lower():
        how = f"{how}; a conversion, not a GBP price"
    return (
        float(converted),
        "derived",
        f"£{converted:,.0f} converted — {how}, {_taxes_words(rate)}",
        stay_basis,
        how,
    )


def _derived_how(rate: dict, fallback: str) -> str:
    return str((rate.get("derived_public_total") or {}).get("how", "")).strip() or fallback


def _refundable(rate: dict) -> bool:
    """True when every published term for this rate is refundable.

    A null ``refundable`` means the page did not say, so this is False — but
    ``_refundable_stated`` records the difference, because "not stated" and
    "stated non-refundable" are not the same fact about a booking.
    """
    entries = [entry for entry in (rate.get("terms") or []) if isinstance(entry, dict)]
    if not entries:
        return False
    return all(bool(entry.get("refundable")) for entry in entries)


def _refundable_stated(rate: dict) -> bool:
    entries = [entry for entry in (rate.get("terms") or []) if isinstance(entry, dict)]
    if not entries:
        return False
    return all(entry.get("refundable") is not None for entry in entries)


def load_hotel_evidence(
    config,
    *,
    path: str = DEFAULT_HOTEL_EVIDENCE_PATH,
    now: Optional[str] = None,
    max_age_hours: Optional[int] = None,
) -> dict[tuple[str, str, str], HotelEvidence]:
    """Load the rates this run may price cards with, keyed by property + dates.

A rate is kept only when every one of the brief's conditions holds:

    * its season is the season this run prices;
    * ``exact_date_match`` is true, and ``(check_in, check_out)`` is a pair this
      run prices OR a pair outside its window — since BRIEF-H15 §1 (2026-10-05)
      an off-window pair is kept as a DERIVED read only. Every other condition
      below still applies to it; only ``hotel_rate_for`` will not return it;
    * its party is the report's party — a rate quoted for four people is not a
      rate for five;
    * ``booking_shape`` is one booking (``one_unit`` or two rooms in one
      booking), so the total shown covers the party;
    * the board is breakfast or better (``RO`` is never a deal);
    * it is observed within ``max_age_hours`` (default one week);
    * it has a real http(s) source URL and a positive price.

    The returned entry carries the cheapest qualifying rate, the refundable
    rate when it is a *different* rate, and the supplementary records
    (unit checks, ratings, facts, blocked sources) for the property.


    Anything else is skipped with a stated reason on stderr. A missing or
    unreadable file returns an empty mapping — today's output is unchanged,
    never a crash and never a fabricated figure.
    """
    _SKIP_LOG.clear()
    _SUPPLEMENTAL_BY_PROPERTY.clear()
    _UNIT_CHECK_BASIS.clear()

    now_dt = _parse_observed_at(now) or datetime.now(timezone.utc)
    ceiling = max_age_hours if max_age_hours and max_age_hours > 0 else hotel_evidence_max_age_hours()

    from .holidays import priceable_date_pairs

    priced_pairs = set(priceable_date_pairs(config))
    if not priced_pairs:
        return {}
    season = _run_season(config)
    travellers = int(getattr(config, "travellers", 0) or 0)

    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        _SUPPLEMENTAL_BY_PROPERTY.clear()
        return {}
    except (json.JSONDecodeError, OSError) as exc:
        print(f"hotel-evidence: unreadable {path}: {exc}", file=sys.stderr)
        _SUPPLEMENTAL_BY_PROPERTY.clear()
        return {}

    rates = payload.get("rates", []) if isinstance(payload, dict) else payload
    if not isinstance(rates, list):
        print(f"hotel-evidence: {path} has no rates list", file=sys.stderr)
        return {}

    qualifying: dict[tuple[str, str, str], list[HotelRate]] = {}
    #: Keys whose own pair this run prices, so ``pair_is_priceable`` is recorded
    #: from the walk rather than recomputed at the end: one source of truth for
    #: which read may be an exact-date price and which may only be carried.
    priceable_keys: set[tuple[str, str, str]] = set()
    # Indexed BEFORE the rates are walked, and for every property the file
    # mentions rather than only the priced ones: a unit check for a property we
    # found no rate for is still a fact about the property.
    _SUPPLEMENTAL_BY_PROPERTY.update(_index_supplemental(payload))
    _tally_unit_check_basis()
    for index, item in enumerate(rates):
        if not isinstance(item, dict):
            _warn_skip(f"#{index}", "not an object")
            continue
        name = str(item.get("property_name", "")).strip()
        if not name:
            _warn_skip(f"#{index}", "property_name missing")
            continue
        check_in = str(item.get("check_in", "")).strip()
        check_out = str(item.get("check_out", "")).strip()

        record_season = str(item.get("season", "")).strip() or _season_of(check_in)
        # BRIEF-H15 §1 (2026-10-05). "Same season" is decided by the DATES on the
        # read, not only by the label the exporter wrote: this gate used to be
        # the only thing keeping a December read out of a July card, and now that
        # a read for a pair outside the window is kept, a record that declares
        # one season and carries the dates of another has more reach than it had.
        # 0 of the 71 rates in the shipped evidence file disagree; a record that
        # does is refused rather than asked to carry a nightly five months away.
        dates_season = _season_of(check_in)
        if season and dates_season and dates_season != season:
            _warn_skip(
                name,
                f"its own dates {check_in} are {dates_season}, "
                f"and this run prices {season}",
            )
            continue
        if season and record_season and record_season != season:
            _warn_skip(name, f"season {record_season!r} is not the season this run prices ({season})")
            continue
        if not bool(item.get("exact_date_match", False)):
            _warn_skip(name, "exact_date_match is false — nearest dates are not these dates")
            continue
        # BRIEF-H15 §1 (2026-10-05). A read whose pair is NOT one this run
        # prices used to be dropped here, which meant a read for 20–27 Jul could
        # never inform a card on a 28 Jun–12 Jul pair: the card fell back to the
        # catalogue guess while a real nightly for the same property, board,
        # unit and season sat unread in the same file. Every other gate below
        # still has to hold — it is a rate read for a real stay, not a
        # candidate — and the entry is marked so it can never be an exact-date
        # price (see ``HotelEvidence.pair_is_priceable``).
        priceable_pair = (check_in, check_out) in priced_pairs
        party = item.get("party") or {}
        adults = int(party.get("adults", 0) or 0) if isinstance(party, dict) else 0
        children = int(party.get("children", 0) or 0) if isinstance(party, dict) else 0
        if travellers and adults + children != travellers:
            _warn_skip(
                name,
                f"party {adults + children} != report party {travellers}",
            )
            continue
        shape = str(item.get("booking_shape", "")).strip()
        if shape not in ONE_BOOKING_SHAPES:
            _warn_skip(name, f"booking_shape {shape!r} is not one booking")
            continue
        board = str(item.get("board", "")).strip().upper()
        if board not in DEAL_BOARDS:
            _warn_skip(
                name,
                NO_MEAL_BOARDS.get(
                    board, f"board {board!r} is not breakfast or better"
                ),
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
            _warn_skip(
                name,
                f"stale: observed {age_hours:.0f}h ago (max {ceiling}h)",
            )
            continue
        priced = _price_for(item)
        if priced is None:
            _warn_skip(name, "no GBP public price and no derived_gbp figure")
            continue
        value, basis, label, stay_basis, how = priced
        cancellation, payment = _terms_by_field(item)
        refundable = _refundable(item)
        try:
            nights = int(item.get("nights", 0) or 0)
        except (TypeError, ValueError):
            nights = 0
        rate = HotelRate(
            property_name=name,
            destination_key=str(item.get("destination_key", "")).strip(),
            season=record_season,
            vendor=str(item.get("vendor", "")).strip(),
            check_in=check_in,
            check_out=check_out,
            nights=nights,
            rate_name=str(item.get("rate_name", "")).strip(),
            board=board,
            price_gbp=value,
            price_basis=basis,
            price_label=label,
            currency=str(item.get("currency", "")).strip().upper(),
            price_how=how,
            stay_basis=stay_basis,
            refundable=refundable,
            terms=_terms_for(item, refundable=refundable),
            cancellation=cancellation,
            payment=payment,
            provider=_provider_of(item),
            refundable_stated=_refundable_stated(item),
            units=_unit_lines(item),
            taxes_included=(
                item.get("taxes_included")
                if isinstance(item.get("taxes_included"), bool) else None
            ),
            source_url=source_url,
            observed_at=observed_raw,
            booking_shape=shape,
            party_adults=adults,
        )
        qualifying.setdefault((name, check_in, check_out), []).append(rate)
        if priceable_pair:
            priceable_keys.add((name, check_in, check_out))

    entries: dict[tuple[str, str, str], HotelEvidence] = {}
    for key, found in qualifying.items():
        cheapest = min(found, key=lambda rate: rate.price_gbp)
        refundable_rates = [rate for rate in found if rate.refundable]
        flexible = None
        if refundable_rates:
            best_flexible = min(refundable_rates, key=lambda rate: rate.price_gbp)
            if best_flexible.rate_name != cheapest.rate_name or best_flexible.price_gbp != cheapest.price_gbp:
                flexible = best_flexible
        name, check_in, check_out = key
        entries[key] = HotelEvidence(
            property_name=name,
            destination_key=cheapest.destination_key,
            season=cheapest.season,
            check_in=check_in,
            check_out=check_out,
            booking_shape=cheapest.booking_shape,
            cheapest=cheapest,
            flexible=flexible,
            rates=tuple(sorted(found, key=lambda rate: rate.price_gbp)),
            unit_checks=_unit_checks(payload, name, check_in, check_out),
            ratings=_ratings(payload, name),
            facts=_facts(payload, name),
            blocked=_blocked(payload, name),
            pair_is_priceable=(name, check_in, check_out) in priceable_keys,
        )
    return entries


def _supplementary(payload, section: str) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    items = payload.get(section)
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


#: Wording the engine uses when a property has no unit that takes the party in
#: one booking. A unit check that FINDS units is not in here: this list is the
#: refusal vocabulary, and a finding that matches none of it keeps the resort.
#: A wrong removal is worse than a kept card, so the default is to keep. This is
#: the FALLBACK vocabulary only: where the exporter stated ``refuses_party``,
#: that field decides and none of these words is read at all (BRIEF-H17 §1).
UNIT_REFUSAL_WORDS: tuple[str, ...] = (
    "refused",
    "refuse",
    "not available",
    "no unit",
    "no single unit",
    "no rooms",
    "no room",
    "cannot",
    "can't",
    "unavailable",
    "does not take",
    "will not take",
)

#: How close together, in words, a refusal word and the party it refuses must
#: sit for the fallback to read them as one claim (BRIEF-H17 §2). Six words is
#: a clause, not a paragraph: it separates "Rooms cannot accommodate more than
#: 3 adults" from "5 adults in one room refused", and it keeps a refusal in one
#: sentence from pairing with a party named in the next.
UNIT_REFUSAL_PROXIMITY_WORDS = 6

#: A party named in words rather than as a number of people: one room, one
#: unit, one booking. A refusal of any of those is a refusal of the booking the
#: report is selling.
UNIT_PARTY_PHRASES: tuple[str, ...] = (
    "one room",
    "single unit",
    "one booking",
)

#: "5 adults", "5-guest", "12 pers", "5guests": how the exporters write a party,
#: in every shape their pages produced. A stated capacity of any number counts,
#: not only this report's: "Rooms cannot accommodate more than 3 adults" is a
#: refusal of a party of five, and nothing in it says the word five.
_PARTY_NOUNS: tuple[str, ...] = (
    "adult", "guest", "traveller", "traveler", "person", "pers", "pax",
)
_PARTY_WORD = re.compile(r"(\d+)(%s)" % "|".join(_PARTY_NOUNS))
_PARTY_WORD_START = re.compile(r"^(?:%s)" % "|".join(_PARTY_NOUNS))

#: Where one clause ends and the next begins: a semicolon, a question mark, an
#: exclamation mark, a line break, or a full stop that follows a word and is
#: followed by a space. A full stop inside a date ("2027-06-27..2027-07-09")
#: or a decimal is not one, so dates stay in the clause that mentions them.
_CLAUSE_SPLIT = re.compile(r"[;!?\n]+|(?<=[a-z0-9])\.\s")

#: One word of a clause, reduced to its letters, digits and any plus sign:
#: ``refused:`` and ``5-guest`` are the words ``refused`` and ``5guest``, and
#: ``'No`` is the word ``no`` — the exporters quote their pages, so a refusal can
#: arrive inside quotation marks and must still be found there.
_CLAUSE_WORD = re.compile(r"[^a-z0-9+]+")


def _clause_words(text: str) -> tuple[str, ...]:
    return tuple(word for word in _CLAUSE_WORD.split(text.lower()) if word)


def _phrase_positions(words: tuple[str, ...], phrase: str) -> tuple[int, ...]:
    """Every index at which ``phrase``'s words appear, in order and whole."""
    wanted = phrase.lower().split()
    span = len(wanted)
    if not span or span > len(words):
        return ()
    return tuple(
        index for index in range(len(words) - span + 1)
        if words[index:index + span] == tuple(wanted)
    )


def _party_positions(words: tuple[str, ...]) -> tuple[int, ...]:
    """Every index at which a party is named — a number of people, or a unit."""
    found: list[int] = []
    for index, word in enumerate(words):
        glued = _PARTY_WORD.match(word)
        if glued and glued.group(0) == word:
            found.append(index)
            continue
        following = words[index + 1] if index + 1 < len(words) else ""
        if word.isdigit() and _PARTY_WORD_START.match(following):
            found.append(index)
    for phrase in UNIT_PARTY_PHRASES:
        found.extend(_phrase_positions(words, phrase))
    return tuple(sorted(set(found)))


def _refusal_positions(words: tuple[str, ...]) -> tuple[int, ...]:
    found: list[int] = []
    for phrase in UNIT_REFUSAL_WORDS:
        found.extend(_phrase_positions(words, phrase))
    return tuple(sorted(set(found)))


def _text_blocks_party(finding: str, travellers: int) -> bool:
    """The fallback: a refusal and the party it refuses, close together.

    BRIEF-H17 §2 (2026-10-06). This used to ask two questions of the WHOLE
    finding — is a refusal word anywhere in it, is a party mentioned anywhere in
    it — and answered True when both were. A finding saying the estimate
    "cannot be re-checked" for a property that "sleeps the party of 5" said
    both, so a card for a hotel that takes five adults was dropped over a
    sentence about our own reading. The two halves must now be in the same
    clause and within six words of each other, which is what a refusal of a
    party actually reads like.

    Anything unrecognised keeps the card: a wrong removal loses a holiday the
    reader could have had, and the exporter's own ``refuses_party`` answers the
    question outright wherever it is stated.
    """
    for clause in _CLAUSE_SPLIT.split(str(finding or "").strip().lower()):
        words = _clause_words(clause)
        if len(words) < 2:
            continue
        refusals = _refusal_positions(words)
        if not refusals:
            continue
        parties = _party_positions(words)
        if not parties:
            continue
        if any(
            abs(refusal - party) <= UNIT_REFUSAL_PROXIMITY_WORDS
            for refusal in refusals for party in parties
        ):
            return True
    return False


def unit_check_blocks_party(finding: str, travellers: int, *,
                            refuses_party: Optional[bool] = None) -> bool:
    """True when this finding says the property cannot take the party.

    The exporter's own ``refuses_party`` decides it outright (BRIEF-H17 §1,
    2026-10-06): ``True`` blocks the party and ``False`` never blocks, whatever
    the wording beside it says. That is the near miss the dealsearch side caught
    — a finding whose own sentence was about our reading ("...it cannot be
    re-checked and is not replaced by a rate") beside "5 adults", which the text
    matcher read as the hotel refusing five adults, and which would have dropped
    a card for a hotel that does take five.

    Only a check with no stated answer falls back to the wording, and the
    fallback is ``_text_blocks_party`` above: a refusal word and the party it
    refuses in the same clause, no more than six words apart. Both halves must
    be present, so "two units available: 2+2 and 3+2" contains numbers but no
    refusal and the resort stays, while "5 adults in one room refused" and
    "Rooms cannot accommodate more than 3 adults" both go. Anything
    unrecognised keeps the card.
    """
    if refuses_party is not None:
        return bool(refuses_party)
    return _text_blocks_party(finding, travellers)


def _unit_check_from(item: dict, name: str) -> Optional[UnitCheck]:
    finding = _stated(item, "finding")
    if not finding:
        return None
    return UnitCheck(
        property_name=name,
        finding=finding,
        source_url=_stated(item, "source_url"),
        observed_at=_stated(item, "observed_at"),
        destination_key=_stated(item, "destination_key"),
        dates=tuple(str(value) for value in (item.get("dates") or ())),
        refuses_party=_stated_flag(item, "refuses_party"),
    )


def _unit_checks(payload, name: str, check_in: str, check_out: str) -> tuple[UnitCheck, ...]:
    out: list[UnitCheck] = []
    for item in _supplementary(payload, "unit_checks"):
        if str(item.get("property_name", "")).strip() != name:
            continue
        record = _unit_check_from(item, name)
        if record is None:
            continue
        if record.dates and tuple(record.dates) != (check_in, check_out):
            continue
        out.append(record)
    return tuple(out)


def _rating_from(item: dict, name: str) -> Optional[HotelRating]:
    try:
        score = float(item.get("score"))
        scale = float(item.get("scale", 5))
    except (TypeError, ValueError):
        return None
    source = _stated(item, "source")
    if not source:
        # A rating with no source is a number with nothing behind it.
        return None
    return HotelRating(
        property_name=name,
        source=source,
        score=score,
        scale=scale,
        review_count=_stated(item, "review_count"),
        where=_stated(item, "where"),
        source_url=_stated(item, "source_url"),
        observed_at=_stated(item, "observed_at"),
    )


def _ratings(payload, name: str) -> tuple[HotelRating, ...]:
    out: list[HotelRating] = []
    for item in _supplementary(payload, "ratings"):
        if str(item.get("property_name", "")).strip() != name:
            continue
        record = _rating_from(item, name)
        if record is not None:
            out.append(record)
    return tuple(out)


def _fact_from(item: dict, name: str) -> Optional[HotelFact]:
    stated = _stated(item, "stated")
    field_name = _stated(item, "field")
    if not stated or not field_name:
        return None
    if field_name not in HOTEL_FACT_FIELDS:
        # Kept out, not dropped from the file: this card cannot render it, and
        # a fact the reader cannot act on is noise on a card.
        _warn_skip(f"{name} fact {field_name!r}", "field is not one this card can present")
        return None
    return HotelFact(
        property_name=name,
        field=field_name,
        stated=stated,
        where=_stated(item, "where"),
        source_url=_stated(item, "source_url"),
        observed_at=_stated(item, "observed_at"),
    )


def _facts(payload, name: str) -> tuple[HotelFact, ...]:
    """Every fact recorded for this property, including disagreeing sources.

    Two sources saying "four pools" and "2 pools" are both kept: hiding one
    would pick a winner the evidence cannot pick, so the card shows both.
    """
    out: list[HotelFact] = []
    for item in _supplementary(payload, "facts"):
        if str(item.get("property_name", "")).strip() != name:
            continue
        record = _fact_from(item, name)
        if record is not None:
            out.append(record)
    return tuple(out)


def _blocked_from(item: dict, name: str) -> Optional[BlockedSource]:
    reason = _stated(item, "reason")
    if not reason:
        # A block with no reason says nothing a reader can act on, and the card
        # would read as if the rating had been judged and rejected.
        return None
    return BlockedSource(
        what=_stated(item, "what") or "a review site",
        property_name=name,
        reason=reason,
        source_url=_stated(item, "source_url"),
        observed_at=_stated(item, "observed_at"),
    )


def _blocked(payload, name: str) -> tuple[BlockedSource, ...]:
    out: list[BlockedSource] = []
    for item in _supplementary(payload, "blocked"):
        if str(item.get("property_name", "")).strip() != name:
            continue
        record = _blocked_from(item, name)
        if record is not None:
            out.append(record)
    return tuple(out)


#: Supplementary records from the most recent load, keyed by the NORMALISED
#: property name, for EVERY property the file mentions — including properties
#: with no qualifying rate. That last part is the whole reason this index
#: exists: a property we watched refuse five adults in one booking may have no
#: rate for us, and dropping that resort is exactly the case which must not
#: depend on having found a price for it. Same pattern as ``_SKIP_LOG``: it
#: belongs to THIS load, and every load rebuilds it.
_SUPPLEMENTAL_BY_PROPERTY: dict[str, dict[str, tuple]] = {}


def _index_supplemental(payload) -> dict[str, dict[str, tuple]]:
    """Group every supplementary record by normalised property name."""
    index: dict[str, dict[str, tuple]] = {}
    builders = (
        ("unit_checks", _unit_check_from),
        ("ratings", _rating_from),
        ("facts", _fact_from),
        ("blocked", _blocked_from),
    )
    for section, builder in builders:
        for item in _supplementary(payload, section):
            name = str(item.get("property_name", "")).strip()
            if not name:
                continue
            record = builder(item, name)
            if record is None:
                continue
            key = _normalise_property(name)
            entry = index.setdefault(
                key,
                {"unit_checks": (), "ratings": (), "facts": (), "blocked": ()},
            )
            entry[section] = tuple(entry[section]) + (record,)
    return index


def supplemental_for(
    property_name: str, section: str, *, dates: tuple[str, ...] = ()
) -> tuple:
    """The records of one section for one property, from the last load.

    ``section`` is one of ``unit_checks``, ``ratings``, ``facts``, ``blocked``.
    With ``dates`` given, unit checks for other date pairs are excluded: a
    check of last month's nights is not a check of these.
    """
    entry = _SUPPLEMENTAL_BY_PROPERTY.get(_normalise_property(property_name))
    if not entry:
        return ()
    records = tuple(entry.get(section, ()))
    if not dates:
        return records
    return tuple(
        record for record in records
        if not getattr(record, "dates", ()) or tuple(record.dates) == tuple(dates)
    )