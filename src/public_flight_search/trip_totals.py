"""A trip's stays priced from dated hotel reads, and the list of stays the private reader should read next.

The July body said "flights only, stays not priced" on every trip card (owner, 14 Nov 2026: "massively improve it"),
because a two-centre trip's hotels were never looked up in the hotel evidence: that file priced single-resort cards
only. This module joins the two. Each stop's named property is dated by ``multi_centre.trip_stays_for_dates`` (the
same chain that dates the flights), and a rate is used only when it was read for THAT property and THOSE nights for
the whole party, breakfast or better, inside the freshness window (every gate is ``hotel_evidence.load_hotel_evidence``'s
own). Nothing is estimated: a stay with no such read is named as unpriced and the trip stays "partly priced".

``stay_wanted`` is the other half: the exact (property, check-in, check-out) list this run would have used, in the
``stay_wanted/1`` shape the private hotel reader takes, so one command prices next week's cards.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from . import hotel_evidence as hotel_evidence_module
from .multi_centre import trip_stays_for_dates

STAY_WANTED_SCHEMA = "stay_wanted/1"

_BOARD_WORDS = {"AI": "all inclusive", "FB": "full board", "HB": "half board", "BB": "breakfast"}


@dataclass(frozen=True)
class StayPrice:
    """One dated stay of a trip, with the read that prices it (``total_gbp`` None when no read does)."""

    place: str
    property_name: str
    check_in: str
    check_out: str
    nights: int
    total_gbp: Optional[float] = None
    board: str = ""
    seller: str = ""
    source_url: str = ""
    observed_at: str = ""
    unit: str = ""
    two_rooms: bool = False
    property_url: str = ""
    #: Why no figure: "no property named", "nights not itemised", "no dated rate read".
    reason: str = ""

    @property
    def priced(self) -> bool:
        return self.total_gbp is not None

    @property
    def board_words(self) -> str:
        return _BOARD_WORDS.get(self.board, "")


@dataclass(frozen=True)
class TripTotal:
    """Flights read + stays read for one trip row. ``complete`` only when every planned night has a read."""

    stays: tuple[StayPrice, ...]
    flights_gbp: Optional[float]
    stays_gbp: float
    nights_priced: int
    nights_planned: int

    @property
    def complete(self) -> bool:
        return (self.flights_gbp is not None and self.nights_planned > 0
                and self.nights_priced == self.nights_planned)

    @property
    def total_gbp(self) -> Optional[float]:
        return (self.flights_gbp + self.stays_gbp) if self.complete else None

    @property
    def any_stay_priced(self) -> bool:
        return self.nights_priced > 0


def _place(stop: Any) -> str:
    return str(getattr(stop, "place", "") or "").split("(")[0].strip()


def _seller(rate: Any) -> str:
    provider = str(getattr(rate, "provider", "") or "").strip()
    if provider:
        return provider
    return str(getattr(rate, "vendor", "") or "").split(" as listed")[0].strip()


def _rate_for(hotel_rates: Optional[Mapping[Any, Any]], name: str, check_in: str, check_out: str) -> Any:
    """The cheapest qualifying rate read for exactly this property and these nights, or None."""
    if not hotel_rates or not (name and check_in and check_out):
        return None
    entries = hotel_evidence_module._pair_entries(hotel_rates, name, check_in, check_out, priceable_only=False)
    rates = [entry.cheapest for entry in entries if getattr(entry, "cheapest", None) is not None]
    return min(rates, key=lambda rate: rate.price_gbp) if rates else None


def _priced(place: str, lodge: Any, check_in: str, check_out: str, nights: int, rate: Any) -> StayPrice:
    units = tuple(getattr(rate, "units", ()) or ())
    return StayPrice(
        place=place, property_name=lodge.name, check_in=check_in, check_out=check_out, nights=nights,
        total_gbp=float(rate.price_gbp), board=str(rate.board or ""), seller=_seller(rate),
        source_url=str(rate.source_url or ""), observed_at=str(rate.observed_at or ""),
        unit="; ".join(units[:2]), two_rooms=str(rate.booking_shape or "") == "two_rooms_one_booking",
        property_url=str(getattr(lodge, "url", "") or ""))


def _stop_stays(stay: Any, hotel_rates: Optional[Mapping[Any, Any]]) -> list[StayPrice]:
    place = _place(stay.stop)
    if not stay.lodges:
        return [StayPrice(place=place, property_name="", check_in=stay.check_in, check_out=stay.check_out,
                          nights=stay.nights, reason="no property named")]
    dated = [ls for ls in stay.lodges if ls.check_in and ls.check_out and ls.nights]
    if dated and len(dated) == len(stay.lodges):
        out = []
        for ls in dated:
            rate = _rate_for(hotel_rates, ls.lodge.name, ls.check_in, ls.check_out)
            out.append(_priced(place, ls.lodge, ls.check_in, ls.check_out, ls.nights, rate) if rate is not None else
                       StayPrice(place=place, property_name=ls.lodge.name, check_in=ls.check_in,
                                 check_out=ls.check_out, nights=ls.nights,
                                 property_url=str(ls.lodge.url or ""), reason="no dated rate read"))
        return out
    # The source names properties without itemising their nights: each is an alternative for the whole stop.
    choices = []
    for ls in stay.lodges:
        rate = _rate_for(hotel_rates, ls.lodge.name, stay.check_in, stay.check_out)
        if rate is not None:
            choices.append(_priced(place, ls.lodge, stay.check_in, stay.check_out, stay.nights, rate))
    if choices:
        return [min(choices, key=lambda s: s.total_gbp)]
    names = " or ".join(ls.lodge.name for ls in stay.lodges)
    return [StayPrice(place=place, property_name=names, check_in=stay.check_in, check_out=stay.check_out,
                      nights=stay.nights, property_url=str(stay.lodges[0].lodge.url or ""),
                      reason="no dated rate read")]


def trip_total(row: Mapping[str, Any], hotel_rates: Optional[Mapping[Any, Any]], *,
               flights_gbp: Optional[float]) -> Optional[TripTotal]:
    """The row's stays against the hotel reads. None when the row's dates cannot be planned."""
    try:
        plan = trip_stays_for_dates(row["trip"], str(row["outbound"]), str(row["return"]))
    except (KeyError, ValueError):
        return None
    stays: list[StayPrice] = []
    for stay in plan.stays:
        if stay.nights > 0:
            stays.extend(_stop_stays(stay, hotel_rates))
    priced = [s for s in stays if s.priced]
    return TripTotal(stays=tuple(stays), flights_gbp=flights_gbp,
                     stays_gbp=float(sum(s.total_gbp for s in priced)),
                     nights_priced=sum(s.nights for s in priced),
                     nights_planned=sum(s.nights for s in stays))


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")


def _search_area(area: Any) -> str:
    """The place names of an area, without its descriptions ("Lucerne, lakefront" -> "Lucerne")."""
    parts = [part.strip() for part in str(area or "").split("(")[0].split(",")]
    named = [part for part in parts if part and part[0].isupper() and not any(ch.isdigit() for ch in part)
             and " the " not in f" {part} "]
    return ", ".join(named)


def stay_wanted(config: Any, rows: Sequence[Mapping[str, Any]], *, watch: Sequence[Any] = (),
                reference_pair: Optional[tuple[str, str]] = None) -> dict[str, Any]:
    """Every dated stay this run could price, as a ``stay_wanted/1`` document for the private hotel reader.

    One entry per (property, check-in, check-out): each trip's dated properties, each alternative of a stop whose
    nights are not itemised (for the whole stop), and each watch-list property on ``reference_pair``.
    """
    stays: dict[tuple[str, str, str], dict[str, str]] = {}

    def add(name: str, area: str, check_in: str, check_out: str, why: str) -> None:
        if not (name and check_in and check_out) or check_out <= check_in:
            return
        key = (_key(name), check_in, check_out)
        if key in stays:
            return
        area = _search_area(area)
        query = name if _key(area) in _key(name) or not area else f"{name} {area}"
        stays[key] = {"property_name": name, "destination_key": _key(area) or "unknown", "season": "summer",
                      "check_in": check_in, "check_out": check_out, "query": query, "for": why}

    for row in rows:
        trip = row["trip"]
        try:
            plan = trip_stays_for_dates(trip, str(row["outbound"]), str(row["return"]))
        except (KeyError, ValueError):
            continue
        for stay in plan.stays:
            if stay.nights <= 0:
                continue
            all_dated = all(ls.check_in and ls.check_out and ls.nights for ls in stay.lodges)
            for ls in stay.lodges:
                area = ls.lodge.area or _place(stay.stop)
                if all_dated:
                    add(ls.lodge.name, area, ls.check_in, ls.check_out, trip.id)
                else:
                    add(ls.lodge.name, area, stay.check_in, stay.check_out, trip.id)
    if reference_pair:
        for entry in watch:
            add(str(entry.name), str(entry.area), reference_pair[0], reference_pair[1], "watchlist")
    season = "summer"
    try:
        season = hotel_evidence_module._run_season(config) or "summer"
    except Exception:  # noqa: BLE001 - the season label is a courtesy to the reader, never a reason to fail
        pass
    for item in stays.values():
        item["season"] = season
    return {"schema": STAY_WANTED_SCHEMA, "travellers": int(getattr(config, "travellers", 5) or 5),
            "stays": list(stays.values())}
