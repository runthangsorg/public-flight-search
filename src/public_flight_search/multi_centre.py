"""Two-centre itineraries: the honest seam between "considered" and "priced".

A single-centre report can only ever show one resort per destination. The
owner asked (2026-10-04) for multi-stop holidays to be *considered too*, and
the honest answer for a shape this engine cannot price — no dated multi-city
fare, no rate for a second hotel — is not a card. It is a cost RANGE with its
basis on its face, one line of why it works, one line of what it costs you,
and a multi-city search link that opens the real prices on the reader's screen.

So this module is deliberately not an evidence loader:

* every figure comes from ``data/multi_centre.json`` (schema
  ``multi_centre/1``), compiled 2026-10-04 from public pages and the private
  evidence file;
* each range names its basis, and ``confidence`` is ``dated-rate`` only where
  a dated public rate or fare backs it — most are ``estimate`` because the
  research read no dated multi-city fare;
* **no budget figure is stored here.** Whether a range fits the owner's money
  is decided at render time against ``config.max_budget_gbp``, so the file
  cannot go stale when the budget changes and cannot leak it either;
* a missing or unreadable file returns an empty list. Today's output changes
  nothing; no range is invented to fill the gap.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
import json
from pathlib import Path
from typing import Any, Optional, Sequence

#: Where the compiled itineraries live. It ships with the package (it is
#: committed source data, unlike ``data/`` at the repository root, which holds
#: the runtime private evidence and is gitignored), so the default is resolved
#: from this file rather than from the working directory: a planner run from
#: anywhere must find the same itineraries.
DEFAULT_MULTI_CENTRE_PATH = str(Path(__file__).with_name("data") / "multi_centre.json")

#: The document shape ``multi_centre.json`` declares.
SCHEMA = "multi_centre/1"

#: Seasons, as the catalogue names them: ``summer`` prices for a June-August
#: departure, ``winter`` for everything else (see ``holidays.is_summer_trip``).
SEASONS: frozenset[str] = frozenset({"summer", "winter"})

#: The label a fully-estimated range carries. No figure here was read as a
#: fare.
PRICE_LABEL = "estimate"
#: The label a range whose lines are dated carries. A range is still not a fare,
#: so this never says "price".
PRICE_LABEL_DATED = "dated lines, still a range"

#: Where a trip's shape came from. ``self-build`` is this report's own line-by-line
#: build; ``operator`` is a package an agency actually sells and the row says
#: which (``operator_ref``). A trip with no ``kind`` is a self-build, which is
#: what every Asian trip in the file already was.
KINDS: frozenset[str] = frozenset({"self-build", "operator"})


@dataclass(frozen=True)
class Lodge:
    """One named property inside a stop, with the nights it holds when the source says.

    A stop's ``hotel`` field is free text, and three of the safari stops hold TWO
    properties (a night in town, then three at the lodge). A name is never lifted
    out of that text with a pattern: where a property is known and bookable it is
    written here, and where it is not the stop simply has no lodges and says so.
    """

    name: str
    #: Nights at this property, or ``None`` when the source does not itemise them
    #: ("Naivasha and Amboseli lodges not itemised"). ``None`` is not zero.
    nights: Optional[int] = None
    #: The board words the source states ("full board", "half board"); empty when
    #: it states none, which the e-mail prints as "board not stated".
    board: str = ""
    #: The place to search the property in (``Zanzibar``, ``Serengeti``): the stop's
    #: own ``place`` is often a sentence, and a booking site resolves a name plus a
    #: town far better than a name plus a sentence.
    area: str = ""
    #: A rule that comes from the source about THIS property's room or unit
    #: ("the Presidential Villa is the only unit that sleeps 5").
    note: str = ""
    #: A page we hold for this property (its own page, or the rate page the figure
    #: came from). Empty means we hold none: a link is never built from a guess.
    url: str = ""


@dataclass(frozen=True)
class CostLine:
    """One itemised line of a self-build's price, in whole pounds."""

    label: str
    gbp: float
    basis: str = ""


@dataclass(frozen=True)
class MultiCentreStop:
    """One stop of a two-centre trip: where, how long, and what it costs."""

    place: str
    nights: int
    airport: str
    hotel: str
    basis: str
    lodges: tuple[Lodge, ...] = ()


@dataclass(frozen=True)
class MultiCentreTrip:
    """One itinerary, with everything a reader needs to judge it."""

    id: str
    title: str
    season: str
    stops: tuple[MultiCentreStop, ...]
    #: ``(origin, destination)`` airport pairs, in order, WITHOUT dates: the
    #: dates are derived from the report's own date pair at render time, so the
    #: search link always matches the trip being priced.
    legs: tuple[tuple[str, str], ...]
    flight_shape: str
    cost_low_gbp: float
    cost_high_gbp: float
    cost_basis: str
    why: str
    catch: str
    confidence: str
    source_urls: tuple[str, ...]
    #: ``self-build`` or ``operator`` (see ``KINDS``). Optional in the file.
    kind: str = "self-build"
    #: For a trip that copies or is an agency's package: whose, and which one.
    operator_ref: str = ""
    #: ``africa``, ``asia`` ...: a label for the reader, never a filter.
    region: str = ""
    #: The id of the trip that is the other half of a vendor-versus-ours pair: an
    #: ``operator`` package names the ``self-build`` of the same shape, and the
    #: other way round. Optional, and checked at load (``_link_counterparts``): an id
    #: that is not in this season's file, or whose kind is the same, is dropped
    #: with a reason, never guessed at.
    compare_with: str = ""
    #: The lines of a self-build's price where the source itemises them. They are
    #: shown only when they add up to the trip's own cost, to the pound.
    cost_lines: tuple[CostLine, ...] = ()

    @property
    def total_nights(self) -> int:
        return sum(stop.nights for stop in self.stops)

    def price_label(self) -> str:
        """The words every range carries, honest about its own confidence.

        A range whose lines are dated still is not a fare, so both cases say
        "cost range"; only the estimate adds the word "estimate", because that
        is the difference a reader acts on.
        """
        if self.confidence == "dated-rate":
            return PRICE_LABEL_DATED
        return PRICE_LABEL

    def fits(self, budget: Any) -> Optional[bool]:
        """Whether the LOW end of the range fits ``budget``.

        The low end is the only number that can fit anything: a range is not a
        price, so the honest question is "could this be affordable", and that
        is the low end's question alone. ``None`` when the budget is unusable,
        so the caller prints no verdict rather than a wrong one.
        """
        try:
            ceiling = float(budget)
        except (TypeError, ValueError):
            return None
        if ceiling <= 0:
            return None
        return self.cost_low_gbp <= ceiling


def season_for(config: Any) -> str:
    """``summer`` or ``winter`` for this config — the catalogue's own test."""
    from .holidays import is_summer_trip

    return "summer" if is_summer_trip(config) else "winter"


#: Skips from the most recent load, surfaced so an operator can see exactly why
#: an itinerary did not make the e-mail. A dropped itinerary is named, never
#: silently missing.
_SKIP_LOG: list[str] = []


def consume_multi_centre_skip_log() -> list[str]:
    """Return and clear the skip reasons recorded by the last load."""
    items = list(_SKIP_LOG)
    _SKIP_LOG.clear()
    return items


def _warn_skip(what: str, reason: str) -> None:
    _SKIP_LOG.append(f"{what or '?'}: {reason}")


def _lodge(item: Any) -> Optional[Lodge]:
    """One property of a stop, or ``None`` when it names nothing or its nights are not a number."""
    if not isinstance(item, dict):
        return None
    name = str(item.get("name", "")).strip()
    if not name:
        return None
    nights: Optional[int] = None
    raw = item.get("nights")
    if raw not in (None, ""):
        try:
            nights = int(raw)
        except (TypeError, ValueError):
            return None
        if nights <= 0:
            return None
    url = str(item.get("url", "") or "").strip()
    if url and not url.startswith(("http://", "https://")):
        url = ""
    return Lodge(
        name=name,
        nights=nights,
        board=str(item.get("board", "") or "").strip(),
        area=str(item.get("area", "") or "").strip(),
        note=str(item.get("note", "") or "").strip(),
        url=url,
    )


def _cost_lines(item: Any, ident: str, low: float, high: float) -> tuple[CostLine, ...]:
    """The itemised lines of a price, but only when they ARE the price.

    A breakdown that does not add up to the trip's own figure is worse than none:
    it reads as an audit and fails it. A range cannot be itemised, so lines are
    accepted only for a trip with one figure (``low == high``), and only when their
    sum is that figure to the pound.
    """
    raw_lines = item.get("cost_lines")
    if not raw_lines:
        return ()
    lines: list[CostLine] = []
    for raw in raw_lines:
        if not isinstance(raw, dict):
            _warn_skip(ident, "a cost line is not an object; the lines are dropped")
            return ()
        label = str(raw.get("label", "")).strip()
        try:
            gbp = float(raw.get("gbp"))
        except (TypeError, ValueError):
            gbp = -1.0
        if not label or gbp < 0:
            _warn_skip(ident, f"cost line {raw!r} has no label or amount; the lines are dropped")
            return ()
        lines.append(CostLine(label=label, gbp=gbp, basis=str(raw.get("basis", "") or "").strip()))
    if low != high or abs(sum(line.gbp for line in lines) - low) > 1.0:
        _warn_skip(ident, "cost lines do not add up to the trip's one figure; the lines are dropped")
        return ()
    return tuple(lines)


def _stop(item: Any) -> Optional[MultiCentreStop]:
    if not isinstance(item, dict):
        return None
    place = str(item.get("place", "")).strip()
    airport = str(item.get("airport", "")).strip().upper()
    if not place or not airport:
        return None
    try:
        nights = int(item.get("nights", 0))
    except (TypeError, ValueError):
        return None
    if nights <= 0:
        return None
    lodges = tuple(l for l in (_lodge(raw) for raw in item.get("lodges", ()) or ()) if l)
    itemised = [l.nights for l in lodges if l.nights is not None]
    if sum(itemised) > nights:
        # Properties that hold more nights than the stop has contradict the stop;
        # the stop stands and the properties are dropped, with the reason.
        _warn_skip(place, "its properties hold more nights than the stop; the properties are dropped")
        lodges = ()
    return MultiCentreStop(
        place=place,
        nights=nights,
        airport=airport,
        hotel=str(item.get("hotel", "")).strip(),
        basis=str(item.get("basis", "")).strip(),
        lodges=lodges,
    )


def _trip(item: Any) -> Optional[MultiCentreTrip]:
    """One validated itinerary, or ``None`` with the reason in the skip log."""
    if not isinstance(item, dict):
        return None
    ident = str(item.get("id", "")).strip()
    title = str(item.get("title", "")).strip()
    season = str(item.get("season", "")).strip().lower()
    if not ident or not title:
        _warn_skip(ident or "?", "no id or title")
        return None
    if season not in SEASONS:
        _warn_skip(ident, f"unknown season {season!r}")
        return None
    stops = tuple(s for s in (_stop(raw) for raw in item.get("stops", ()) or ()) if s)
    if not stops:
        _warn_skip(ident, "no usable stop")
        return None
    legs: list[tuple[str, str]] = []
    for raw in item.get("legs", ()) or ():
        if not isinstance(raw, (list, tuple)) or len(raw) != 2:
            _warn_skip(ident, f"leg {raw!r} is not an airport pair")
            return None
        legs.append((str(raw[0]).strip().upper(), str(raw[1]).strip().upper()))
    if len(legs) < 2:
        _warn_skip(ident, "a two-centre search needs at least two legs")
        return None
    try:
        low = float(item.get("cost_low_gbp"))
        high = float(item.get("cost_high_gbp"))
    except (TypeError, ValueError):
        _warn_skip(ident, "no usable cost range")
        return None
    if low <= 0 or high < low:
        _warn_skip(ident, f"cost range {low}-{high} is not a range")
        return None
    urls = tuple(
        str(u).strip() for u in item.get("source_urls", ()) or () if str(u).strip()
    )
    kind = str(item.get("kind", "") or "self-build").strip().lower()
    if kind not in KINDS:
        _warn_skip(ident, f"unknown kind {kind!r}")
        return None
    operator_ref = str(item.get("operator_ref", "") or "").strip()
    if kind == "operator" and not operator_ref:
        _warn_skip(ident, "an operator trip must name its operator")
        return None
    return MultiCentreTrip(
        id=ident,
        title=title,
        season=season,
        stops=stops,
        legs=tuple(legs),
        flight_shape=str(item.get("flight_shape", "")).strip(),
        cost_low_gbp=low,
        cost_high_gbp=high,
        cost_basis=str(item.get("cost_basis", "")).strip(),
        why=str(item.get("why", "")).strip(),
        catch=str(item.get("catch", "")).strip(),
        confidence=str(item.get("confidence", "")).strip() or "estimate",
        source_urls=urls,
        kind=kind,
        operator_ref=operator_ref,
        region=str(item.get("region", "") or "").strip().lower(),
        compare_with=str(item.get("compare_with", "") or "").strip(),
        cost_lines=_cost_lines(item, ident, low, high),
    )


def load_multi_centre(
    config: Any = None,
    *,
    path: str = DEFAULT_MULTI_CENTRE_PATH,
    season: Optional[str] = None,
) -> list[MultiCentreTrip]:
    """The itineraries for this run's season, in file order.

    ``config`` decides the season when ``season`` is not given; the tests pass
    a season directly so they need no config. A missing, unreadable or
    wrongly-shaped file returns an empty list: the section simply does not
    appear, and no range is invented to fill it.
    """
    _SKIP_LOG.clear()
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        _warn_skip(path, f"unreadable: {exc}")
        return []
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        _warn_skip(path, f"not a {SCHEMA} document")
        return []
    wanted = season or season_for(config)
    trips: list[MultiCentreTrip] = []
    for raw in payload.get("itineraries", ()) or ():
        trip = _trip(raw)
        if trip is not None and trip.season == wanted:
            trips.append(trip)
    return _link_counterparts(trips)


def _link_counterparts(trips: list[MultiCentreTrip]) -> list[MultiCentreTrip]:
    """Drop a ``compare_with`` that points nowhere sensible, saying why.

    A pair is an operator package and a self-build of the SAME shape. An id that is
    not among this season's trips, that is the trip's own, or whose kind is the same
    as the trip's, would print a comparison of two things that are not a pair, so
    the field is cleared (the trip stays) and the skip log names the reason.
    """
    by_id = {trip.id: trip for trip in trips}
    out: list[MultiCentreTrip] = []
    for trip in trips:
        other_id = trip.compare_with
        if not other_id:
            out.append(trip)
            continue
        other = by_id.get(other_id)
        if other is None or other_id == trip.id:
            _warn_skip(trip.id, f"compare_with {other_id!r} is not another trip of this season")
        elif (other.kind == "operator") == (trip.kind == "operator"):
            _warn_skip(trip.id, f"compare_with {other_id!r} is the same kind ({trip.kind}); a pair is one of each")
        else:
            out.append(trip)
            continue
        out.append(replace(trip, compare_with=""))
    return out


def counterparts(trips: Sequence[MultiCentreTrip]) -> dict[str, list[MultiCentreTrip]]:
    """``{trip id: the trips it is paired with}``, from either side's ``compare_with``.

    One side declaring the pair is enough: Kuoni's package does not have to say
    which self-build copies it for the self-build's own ``compare_with`` to put the
    two side by side in both directions. Order is the file's order.
    """
    by_id = {trip.id: trip for trip in trips}
    pairs: dict[str, list[str]] = {trip.id: [] for trip in trips}
    for trip in trips:
        other = by_id.get(trip.compare_with)
        if other is None:
            continue
        if other.id not in pairs[trip.id]:
            pairs[trip.id].append(other.id)
        if trip.id not in pairs[other.id]:
            pairs[other.id].append(trip.id)
    order = {trip.id: index for index, trip in enumerate(trips)}
    return {
        ident: [by_id[o] for o in sorted(others, key=order.__getitem__)]
        for ident, others in pairs.items()
    }


def trip_legs_for_dates(
    trip: MultiCentreTrip,
    outbound: str,
    returning: str,
) -> tuple[tuple[str, str, str], ...]:
    """``trip``'s legs as ``(origin, destination, date)`` triples.

    Dates come from the report's own pair and each leg's stop nights are spent
    in order, so the search link is the itinerary the reader is actually being
    shown. A trip whose stops do not add up to the stay is padded onto its last
    leg rather than silently shifted, and a pair that does not parse raises —
    a wrong date in a search link is worse than no section.
    """
    try:
        start = datetime.strptime(outbound, "%Y-%m-%d")
        end = datetime.strptime(returning, "%Y-%m-%d")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"bad date pair: {outbound!r} -> {returning!r}") from exc
    if end <= start:
        raise ValueError(f"return date is not after the outbound: {outbound!r} -> {returning!r}")
    # One date per leg. A leg moves the date on only when it LEAVES the stay
    # it is ending: its origin is the airport of the next stay not yet spent.
    # Any other leg is a change of plane and flies the same day as the leg
    # before it (live 2026-10-15: MC-02's HKT-BKK-USM was searched with
    # BKK-USM a week later, seven nights in a Bangkok the trip never names).
    dates = []
    current = start
    pending = list(trip.stops)
    for index, (origin, _destination) in enumerate(trip.legs):
        if index and pending and origin == pending[0].airport:
            current = current + timedelta(days=pending.pop(0).nights)
        dates.append(current)
    # The LAST leg is the flight home and leaves on the report's own return
    # date, always; earlier legs are pulled back if they run past it.
    dates = [min(date, end) for date in dates]
    dates[len(trip.legs) - 1] = end
    out: list[tuple[str, str, str]] = []
    for (origin, destination), date in zip(trip.legs, dates):
        out.append((origin, destination, date.strftime("%Y-%m-%d")))
    return tuple(out)


@dataclass(frozen=True)
class LodgeStay:
    """One property's own dated window inside a stop; empty dates when its nights are not itemised."""

    lodge: Lodge
    check_in: str
    check_out: str
    nights: Optional[int]


@dataclass(frozen=True)
class Stay:
    """One stop with its check-in and check-out, and its properties dated inside it."""

    stop: MultiCentreStop
    check_in: str
    check_out: str
    nights: int
    lodges: tuple[LodgeStay, ...]


@dataclass(frozen=True)
class StayPlan:
    """The whole trip dated against one date pair, and what that pair leaves over.

    ``unplanned_nights`` is the stay between where the plan ends and the flight
    home: the trip's stops add up to their own nights (9 for a nine-night package),
    the report's date pair is a fortnight or more, and the difference is real
    nights nobody has planned or priced. ``cut_nights`` is the opposite: a plan
    longer than the pair, cut at the flight home.
    """

    stays: tuple[Stay, ...]
    plan_end: str
    return_date: str
    unplanned_nights: int
    cut_nights: int


def trip_stays_for_dates(trip: MultiCentreTrip, outbound: str, returning: str) -> StayPlan:
    """Each stop's (and each property's) check-in and check-out for the report's date pair.

    The first stay starts on the outbound date and each stay starts where the last
    one ended, by the stops' OWN nights: the same chain ``trip_legs_for_dates``
    uses to date the flights between stops, so the day a flight leaves is the day
    the stay it leaves ends. Nothing is stretched to reach the return date. Where
    the stops add up to fewer nights than the pair, the gap is reported in
    ``unplanned_nights`` and the last stay still ends on the day the plan does;
    where they add up to more, the last stays are cut at the flight home and the
    nights cut are reported in ``cut_nights``.

    A property's window is given only when its nights are known: its own
    ``nights``, or the whole stop when it is the stop's only property. A property
    whose nights the source does not itemise gets empty dates, never a guess.
    """
    try:
        start = datetime.strptime(outbound, "%Y-%m-%d")
        end = datetime.strptime(returning, "%Y-%m-%d")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"bad date pair: {outbound!r} -> {returning!r}") from exc
    if end <= start:
        raise ValueError(f"return date is not after the outbound: {outbound!r} -> {returning!r}")
    fmt = "%Y-%m-%d"
    cursor = start
    cut = 0
    stays: list[Stay] = []
    for stop in trip.stops:
        available = (end - cursor).days
        nights = max(0, min(stop.nights, available))
        cut += stop.nights - nights
        check_in = cursor
        check_out = cursor + timedelta(days=nights)
        lodge_cursor = check_in
        lodge_stays: list[LodgeStay] = []
        for lodge in stop.lodges:
            held = lodge.nights
            if held is None and len(stop.lodges) == 1:
                held = stop.nights
            if held is None:
                lodge_stays.append(LodgeStay(lodge, "", "", None))
                continue
            span = max(0, min(held, (check_out - lodge_cursor).days))
            lodge_stays.append(LodgeStay(
                lodge,
                lodge_cursor.strftime(fmt),
                (lodge_cursor + timedelta(days=span)).strftime(fmt),
                span,
            ))
            lodge_cursor += timedelta(days=span)
        stays.append(Stay(stop, check_in.strftime(fmt), check_out.strftime(fmt), nights, tuple(lodge_stays)))
        cursor = check_out
    return StayPlan(
        stays=tuple(stays),
        plan_end=cursor.strftime(fmt),
        return_date=end.strftime(fmt),
        unplanned_nights=max(0, (end - cursor).days),
        cut_nights=cut,
    )


__all__ = [
    "DEFAULT_MULTI_CENTRE_PATH",
    "MultiCentreStop",
    "MultiCentreTrip",
    "CostLine",
    "KINDS",
    "Lodge",
    "LodgeStay",
    "PRICE_LABEL",
    "SCHEMA",
    "Stay",
    "StayPlan",
    "consume_multi_centre_skip_log",
    "counterparts",
    "load_multi_centre",
    "season_for",
    "trip_legs_for_dates",
    "trip_stays_for_dates",
]