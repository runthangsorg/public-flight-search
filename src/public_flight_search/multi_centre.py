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

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
from pathlib import Path
from typing import Any, Optional

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


@dataclass(frozen=True)
class MultiCentreStop:
    """One stop of a two-centre trip: where, how long, and what it costs."""

    place: str
    nights: int
    airport: str
    hotel: str
    basis: str


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
    return MultiCentreStop(
        place=place,
        nights=nights,
        airport=airport,
        hotel=str(item.get("hotel", "")).strip(),
        basis=str(item.get("basis", "")).strip(),
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
    return trips


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
    dates = [start]
    for stop in trip.stops:
        dates.append(dates[-1] + timedelta(days=stop.nights))
    # One date per leg. More legs than stops is unusual (a route home through a
    # hub) but must not leave a leg undated, so pad with the last date.
    while len(dates) < len(trip.legs):
        dates.append(dates[-1])
    # The LAST leg is the flight home, and it leaves on the report's own return
    # date — always, whether or not the stop nights add up to the stay (13
    # nights inside a 14-night pair, say). A link whose return leg lands before
    # the reader's own return date is a different trip from the one printed, so
    # the RETURN LEG's index is the one that is forced, not the last date the
    # stops happened to generate: a two-leg round trip generates three dates and
    # flies the first two. Intermediate legs follow the stop nights and are
    # pulled back if they run past the return, never past it.
    dates = [min(date, end) for date in dates]
    dates[len(trip.legs) - 1] = end
    out: list[tuple[str, str, str]] = []
    for (origin, destination), date in zip(trip.legs, dates):
        out.append((origin, destination, date.strftime("%Y-%m-%d")))
    return tuple(out)


__all__ = [
    "DEFAULT_MULTI_CENTRE_PATH",
    "MultiCentreStop",
    "MultiCentreTrip",
    "PRICE_LABEL",
    "SCHEMA",
    "consume_multi_centre_skip_log",
    "load_multi_centre",
    "season_for",
    "trip_legs_for_dates",
]