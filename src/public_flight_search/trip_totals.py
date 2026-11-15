"""A trip's stays priced from dated hotel reads, and the list of stays the private reader should read next.

The July body said "flights only, stays not priced" on every trip card (owner, 14 Nov 2026: "massively improve it"),
because a two-centre trip's hotels were never looked up in the hotel evidence: that file priced single-resort cards
only. This module joins the two. Each stop's named property is dated by ``multi_centre.trip_stays_for_dates`` (the
same chain that dates the flights), and a rate is used only when it was read for THAT property and THOSE nights for
the whole party, inside the freshness window (every gate is ``hotel_evidence.load_hotel_evidence``'s own). A
breakfast-or-better read always wins; where there is none, a room-only read for the same nights still prices the night
and says "room only", because a dated room-only figure is a real price for a trip total even though it is not a holiday
deal card (``hotel_evidence.load_room_only_rates``). Nothing is estimated: a stay with no such read is named as
unpriced and the trip stays "partly priced".

``stay_wanted`` is the other half: the exact (property, check-in, check-out) list this run would have used, in the
``stay_wanted/1`` shape the private hotel reader takes, so one command prices next week's cards.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, Mapping, Optional, Sequence

from . import hotel_evidence as hotel_evidence_module
from .multi_centre import trip_stays_for_dates

STAY_WANTED_SCHEMA = "stay_wanted/1"

#: The board as the card says it. ``RO`` is here because a TRIP total may price a
#: night from a room-only read — labelled, never passed off as a holiday deal —
#: while a single-resort deal card still refuses it (``hotel_evidence.DEAL_BOARDS``).
_BOARD_WORDS = {"AI": "all inclusive", "FB": "full board", "HB": "half board", "BB": "breakfast",
                "RO": "room only"}


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
    #: Priced as three rooms (2 + 2 + 1 for five adults), the last resort when no one-unit or two-room
    #: read exists for these nights.
    three_rooms: bool = False
    #: The adults each unit states, from the read itself (``(3, 2)`` for two rooms); empty when the read
    #: states none, and then the card says "2 rooms" and invents nothing.
    unit_guests: tuple[int, ...] = ()
    #: True when the figure is the page's nightly price times the nights rather than a stated stay total.
    derived_total: bool = False
    property_url: str = ""
    #: Why no figure: "no property named", "nights not itemised between these properties",
    #: "the nights at each property are not itemised", "no dated rate read".
    reason: str = ""
    #: The stop's own statement of how its properties share it (``multi_centre``'s
    #: ``lodging``): ``alternatives``, ``sequence``, or empty when it does not say.
    lodging: str = ""
    #: Every property of an ``alternatives`` stop, in catalogue order, when this figure is
    #: one of them: the card then says "Angama Mara (one of: Angama Mara or Mara Serena)".
    one_of: tuple[str, ...] = ()

    @property
    def priced(self) -> bool:
        return self.total_gbp is not None

    @property
    def board_words(self) -> str:
        return _BOARD_WORDS.get(self.board, "")

    @property
    def rooms_words(self) -> str:
        """The booking's shape in a reader's words: "2 rooms (3 + 2 guests)" or "one unit for 5".

        Built from the units the read stated, so the two-room line no longer repeats the exporter's
        display strings ("Booking.com — 3 guests — 3"). With no stated counts it says only what it
        knows: "2 rooms", or nothing for one unit.
        """
        if self.three_rooms:
            if self.unit_guests:
                return f"3 rooms ({' + '.join(str(guests) for guests in self.unit_guests)} guests)"
            return "3 rooms"
        if self.two_rooms:
            if self.unit_guests:
                return f"2 rooms ({' + '.join(str(guests) for guests in self.unit_guests)} guests)"
            return "2 rooms"
        if self.unit_guests:
            return f"one unit for {self.unit_guests[0]}"
        return ""


@dataclass(frozen=True)
class TripTotal:
    """Flights read + stays read for one trip row. ``complete`` only when every planned night has a read."""

    stays: tuple[StayPrice, ...]
    flights_gbp: Optional[float]
    stays_gbp: float
    nights_priced: int
    nights_planned: int
    #: Nights priced from a room-only read: real, dated, and no meals. Named on the card so a reader is never
    #: told a hotel price includes breakfast when the board it was read on was room only.
    room_only_nights: int = 0

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


def _cheapest_read(loaded: Optional[Mapping[Any, Any]], name: str, check_in: str, check_out: str) -> Any:
    """The cheapest entry's rate this mapping holds for exactly this property and these nights."""
    if not loaded or not (name and check_in and check_out):
        return None
    entries = hotel_evidence_module._pair_entries(loaded, name, check_in, check_out, priceable_only=False)
    rates = [entry.cheapest for entry in entries if getattr(entry, "cheapest", None) is not None]
    return min(rates, key=lambda rate: rate.price_gbp) if rates else None


def _three_room_read(loaded: Optional[Mapping[Any, Any]], name: str, check_in: str,
                     check_out: str) -> Any:
    """The cheapest three-room rate for these nights, breakfast or better before room only.

    One load holds every board (``hotel_evidence.load_three_room_rates``), so the preference the
    other two loads get from being separate is applied here: a breakfast-or-better three-room
    read wins, and a room-only one is used only when there is none.
    """
    if not loaded or not (name and check_in and check_out):
        return None
    entries = hotel_evidence_module._pair_entries(loaded, name, check_in, check_out, priceable_only=False)
    # every rate of each entry, not only its cheapest: the cheapest of a seller's rates is usually the
    # room-only one, and it hid a breakfast rate read for the same nights (14 Nov 2026)
    rates = [rate for entry in entries
             for rate in (tuple(getattr(entry, "rates", ()) or ()) or (getattr(entry, "cheapest", None),))
             if rate is not None]
    if not rates:
        return None
    with_board = [rate for rate in rates
                  if str(getattr(rate, "board", "")).upper() in hotel_evidence_module.DEAL_BOARDS]
    return min(with_board or rates, key=lambda rate: rate.price_gbp)


def _rate_for(hotel_rates: Optional[Mapping[Any, Any]], name: str, check_in: str, check_out: str,
              room_only_rates: Optional[Mapping[Any, Any]] = None,
              three_room_rates: Optional[Mapping[Any, Any]] = None) -> Any:
    """The rate for exactly this property and these nights, in the brief's order of preference.

    One is: a breakfast-or-better rate in one unit or two rooms; then room only in one unit or two
    rooms; then a three-room rate (breakfast or better before room only, then cheapest).

    A room-only read is used only when NO breakfast-or-better read exists for the
    property and those nights: a trip total then prices the night from a real
    dated figure rather than leaving it open, and the stay carries board ``RO``
    so the card says "room only". The mappings are separate loads of the same
    file (``hotel_evidence.load_room_only_rates``, ``load_three_room_rates``), so
    this is a preference between real reads and never a choice between a read
    and an estimate; a three-room read is the shape of last resort because five
    adults across three rooms is a booking their seller may not hold together.
    """
    rate = _cheapest_read(hotel_rates, name, check_in, check_out)
    if rate is not None:
        return rate
    rate = _cheapest_read(room_only_rates, name, check_in, check_out)
    if rate is not None:
        return rate
    return _three_room_read(three_room_rates, name, check_in, check_out)


def _priced(place: str, lodge: Any, check_in: str, check_out: str, nights: int, rate: Any) -> StayPrice:
    units = tuple(getattr(rate, "units", ()) or ())
    return StayPrice(
        place=place, property_name=lodge.name, check_in=check_in, check_out=check_out, nights=nights,
        total_gbp=float(rate.price_gbp), board=str(rate.board or ""), seller=_seller(rate),
        source_url=str(rate.source_url or ""), observed_at=str(rate.observed_at or ""),
        unit="; ".join(units[:3]), two_rooms=str(rate.booking_shape or "") == "two_rooms_one_booking",
        three_rooms=str(rate.booking_shape or "") == "three_rooms_one_booking",
        unit_guests=tuple(getattr(rate, "unit_guests", ()) or ()),
        derived_total=bool(getattr(rate, "derived_total", False)),
        property_url=str(getattr(lodge, "url", "") or ""))


def _stop_stays(stay: Any, hotel_rates: Optional[Mapping[Any, Any]],
                room_only_rates: Optional[Mapping[Any, Any]] = None,
                three_room_rates: Optional[Mapping[Any, Any]] = None) -> list[StayPrice]:
    place = _place(stay.stop)
    if not stay.lodges:
        return [StayPrice(place=place, property_name="", check_in=stay.check_in, check_out=stay.check_out,
                          nights=stay.nights, reason="no property named")]
    dated = [ls for ls in stay.lodges if ls.check_in and ls.check_out and ls.nights]
    if dated and len(dated) == len(stay.lodges):
        out = []
        for ls in dated:
            rate = _rate_for(hotel_rates, ls.lodge.name, ls.check_in, ls.check_out, room_only_rates,
                             three_room_rates)
            out.append(_priced(place, ls.lodge, ls.check_in, ls.check_out, ls.nights, rate) if rate is not None else
                       StayPrice(place=place, property_name=ls.lodge.name, check_in=ls.check_in,
                                 check_out=ls.check_out, nights=ls.nights,
                                 property_url=str(ls.lodge.url or ""), reason="no dated rate read"))
        return out
    if len(stay.lodges) > 1:
        # Several properties and no nights against each. Pricing the whole stop from whichever has a rate put six
        # nights of a safari in a city hotel (14 Nov 2026), so only a stop the CATALOGUE states is priced at all,
        # and nothing is read into the wording: `lodging` says which case it is.
        names = [ls.lodge.name for ls in stay.lodges]
        lodging = str(getattr(stay.stop, "lodging", "") or "")
        if lodging == "alternatives":
            # Each property is the WHOLE stop ("this lodge or that one"): price each for the stop's own nights and
            # keep the cheapest read, which is the pre-14-Nov behaviour restored only under this flag.
            choices = []
            for ls in stay.lodges:
                rate = _rate_for(hotel_rates, ls.lodge.name, stay.check_in, stay.check_out, room_only_rates,
                                 three_room_rates)
                if rate is not None:
                    choices.append(replace(
                        _priced(place, ls.lodge, stay.check_in, stay.check_out, stay.nights, rate),
                        lodging="alternatives", one_of=tuple(names)))
            if choices:
                return [min(choices, key=lambda s: s.total_gbp)]
            return [StayPrice(place=place, property_name=" or ".join(names), check_in=stay.check_in,
                              check_out=stay.check_out, nights=stay.nights,
                              property_url=str(stay.lodges[0].lodge.url or ""),
                              reason="no dated rate read", lodging="alternatives")]
        if lodging == "sequence":
            # The nights run through the properties in order and nobody itemised them: no figure can price this
            # stop, and asking for the whole stop at one property would ask for a read nobody can use.
            return [StayPrice(place=place, property_name=", then ".join(names), check_in=stay.check_in,
                              check_out=stay.check_out, nights=stay.nights,
                              property_url=str(stay.lodges[0].lodge.url or ""),
                              reason="the nights at each property are not itemised", lodging="sequence")]
        return [StayPrice(place=place, property_name=" or ".join(names), check_in=stay.check_in, check_out=stay.check_out,
                          nights=stay.nights, property_url=str(stay.lodges[0].lodge.url or ""),
                          reason="nights not itemised between these properties")]
    # One property named for the whole stop.
    choices = []
    for ls in stay.lodges:
        rate = _rate_for(hotel_rates, ls.lodge.name, stay.check_in, stay.check_out, room_only_rates,
                         three_room_rates)
        if rate is not None:
            choices.append(_priced(place, ls.lodge, stay.check_in, stay.check_out, stay.nights, rate))
    if choices:
        return [min(choices, key=lambda s: s.total_gbp)]
    names = " or ".join(ls.lodge.name for ls in stay.lodges)
    return [StayPrice(place=place, property_name=names, check_in=stay.check_in, check_out=stay.check_out,
                      nights=stay.nights, property_url=str(stay.lodges[0].lodge.url or ""),
                      reason="no dated rate read")]


def trip_total(row: Mapping[str, Any], hotel_rates: Optional[Mapping[Any, Any]], *,
               flights_gbp: Optional[float],
               room_only_rates: Optional[Mapping[Any, Any]] = None,
               three_room_rates: Optional[Mapping[Any, Any]] = None) -> Optional[TripTotal]:
    """The row's stays against the hotel reads. None when the row's dates cannot be planned.

    ``hotel_rates`` is the breakfast-or-better load and ``room_only_rates`` the
    room-only one; a stay takes a breakfast-rate read whenever one exists and only
    then falls back to a room-only read for the same property and nights. Either
    mapping may be empty or None — a run with only room-only evidence still prices
    a trip, and it is labelled room only. ``three_room_rates`` is the three-room load, the last
    shape tried for a night the other two do not price, and the stay then says "3 rooms (2 + 2 + 1
guests)".
    """
    try:
        plan = trip_stays_for_dates(row["trip"], str(row["outbound"]), str(row["return"]))
    except (KeyError, ValueError):
        return None
    stays: list[StayPrice] = []
    for stay in plan.stays:
        if stay.nights > 0:
            stays.extend(_stop_stays(stay, hotel_rates, room_only_rates, three_room_rates))
    priced = [s for s in stays if s.priced]
    return TripTotal(stays=tuple(stays), flights_gbp=flights_gbp,
                     stays_gbp=float(sum(s.total_gbp for s in priced)),
                     nights_priced=sum(s.nights for s in priced),
                     nights_planned=sum(s.nights for s in stays),
                     room_only_nights=sum(s.nights for s in priced if s.board == "RO"))


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
            # A stop whose properties hold no nights is asked for as the whole stop only when they are
            # ALTERNATIVES for it or there is one property. A sequence's nights are not itemised, so a read for
            # the whole stop at one of its properties is a read nobody can use, and it is not asked for.
            whole_stop = bool(getattr(stay.stop, "lodging", "") == "alternatives" or len(stay.lodges) == 1)
            if all_dated or whole_stop:
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
