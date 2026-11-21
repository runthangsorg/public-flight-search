"""Tickets that go beyond a hub and cost less than a ticket to the hub (owner, 21 Nov 2026).

An airline prices a journey by the two cities it sells between, not by the miles flown. London to Tbilisi
through Istanbul competes with every other way to Tbilisi; London to Istanbul nonstop competes with little, so
the longer ticket can be the cheaper one. A traveller who wants Istanbul can buy the Tbilisi ticket and leave
at Istanbul: a "hidden-city" ticket, which is what the apps that sell "secret flights" sell.

This module only measures the gap. For a hub it reads the cheapest nonstop one-way fare to the hub and, for
each onward city in ``data/beyond_cities.json``, the cheapest one-stop one-way fare whose only connection is
that hub, one traveller each, on the same day. It books nothing and prices no card.

What such a ticket costs beyond its fare is in ``CAVEATS``, and every output carries it: the airline's
conditions forbid it, a checked bag goes to the ticketed city, any later flight on the same booking is
cancelled once a leg is missed, and a rerouting by the airline can miss the hub altogether.
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

SCHEMA = "beyond_fares/1"
DATA_PATH = Path(__file__).parent / "data" / "beyond_cities.json"
CONFIDENCE = "results-page, one traveller"
#: A gap is worth a line only when it is this large both in pounds and as a share of the nonstop fare.
MIN_SAVING_GBP = 25.0
MIN_SAVING_PCT = 10.0
MAX_BEYOND_PER_HUB = 8
CAVEATS = (
    "One way only: once a leg is missed the airline cancels every later flight on the booking, so the way "
    "home is a separate ticket.",
    "Hand luggage only: a checked bag is tagged to the ticketed city, not the hub.",
    "The airline's conditions of carriage forbid it; it can cancel the ticket, bill the fare difference or "
    "close a frequent-flyer account, so no loyalty number goes on the booking.",
    "If the airline reroutes the journey, the new route may not pass through the hub at all.",
    "The traveller must be able to enter the ticketed country: check-in can ask for its visa.",
)


@dataclass(frozen=True)
class Hub:
    hub: str
    label: str
    airports: tuple[str, ...]
    beyond: tuple[str, ...]


@dataclass(frozen=True)
class FareRead:
    origin: str
    destination: str
    day: str


def load_hubs(path: Path = DATA_PATH) -> dict[str, Hub]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8")).get("hubs", [])
    except (OSError, ValueError, AttributeError):
        return {}
    hubs: dict[str, Hub] = {}
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        code = str(item.get("hub", "")).strip().upper()
        airports = tuple(str(a).strip().upper() for a in item.get("airports") or [code])
        beyond = tuple(dict.fromkeys(str(b).strip().upper() for b in item.get("beyond") or []))
        if _code(code) and all(_code(a) for a in airports) and all(_code(b) for b in beyond):
            hubs[code] = Hub(code, str(item.get("label") or code), airports,
                             tuple(b for b in beyond if b not in airports)[:MAX_BEYOND_PER_HUB])
    return hubs


def _code(value: str) -> bool:
    return len(value) == 3 and value.isascii() and value.isalpha() and value.isupper()


def plan(origin: str, hub: Hub, day: str) -> list[FareRead]:
    """The hub's own fare first (one read per hub airport), then one read per onward city."""
    return [FareRead(origin, airport, day) for airport in hub.airports] + \
           [FareRead(origin, city, day) for city in hub.beyond]


def _usable(offers: Iterable[Any]) -> list[Any]:
    return [o for o in offers if getattr(o, "currency", "") == "GBP" and float(getattr(o, "price", 0) or 0) > 0]


def cheapest_nonstop(offers: Iterable[Any]) -> Optional[Any]:
    nonstop = [o for o in _usable(offers) if int(o.stops) == 0]
    return min(nonstop, key=lambda o: (o.price, o.duration_minutes)) if nonstop else None


def cheapest_through(offers: Iterable[Any], hub: Hub) -> Optional[Any]:
    """The cheapest ticket whose one and only connection is at the hub.

    A read that did not name its connection (``via_airports`` empty) is never counted: a ticket through
    another city is no use to someone going to this one.
    """
    through = [o for o in _usable(offers)
               if int(o.stops) == 1 and len(getattr(o, "via_airports", ())) == 1 and o.via_airports[0] in hub.airports]
    return min(through, key=lambda o: (o.price, o.duration_minutes)) if through else None


def find_beyond_fares(origin: str, hub: Hub, day: str, fetch: Callable[[FareRead], tuple[str, Sequence[Any]]], *,
                      now: Optional[datetime] = None, min_saving_gbp: float = MIN_SAVING_GBP,
                      min_saving_pct: float = MIN_SAVING_PCT) -> dict:
    """Read the hub's nonstop fare and each onward city's through fare; report where the longer ticket is cheaper.

    ``fetch`` returns ``(status, offers)``; any status but "ok" is recorded and the read counts for nothing.
    Without a nonstop fare to the hub there is nothing to compare with, so no onward city is read at all.
    """
    now = now or datetime.now(timezone.utc)
    stamp = now.isoformat(timespec="seconds")
    reads: list[dict] = []
    nonstop: Optional[Any] = None
    for read in plan(origin, hub, day)[:len(hub.airports)]:
        status, offers = fetch(read)
        best = cheapest_nonstop(offers) if status == "ok" else None
        reads.append({"destination": read.destination, "status": "priced" if best else
                      ("no nonstop" if status == "ok" else status)})
        if best is not None and (nonstop is None or best.price < nonstop.price):
            nonstop = best
    result = {"schema": SCHEMA, "generated_at": stamp, "origin": origin, "hub": hub.hub, "hub_label": hub.label,
              "day": day, "confidence_label": CONFIDENCE, "nonstop": None, "leads": [], "reads": reads,
              "caveats": list(CAVEATS)}
    if nonstop is None:
        return result
    result["nonstop"] = {"destination": nonstop.destination, "per_person_gbp": round(float(nonstop.price), 2),
                         "airline": str(nonstop.airline), "departure": nonstop.departure,
                         "source_url": nonstop.booking_url, "observed_at": stamp}
    for read in plan(origin, hub, day)[len(hub.airports):]:
        status, offers = fetch(read)
        best = cheapest_through(offers, hub) if status == "ok" else None
        reads.append({"destination": read.destination, "status": "through fare" if best else
                      ("none through the hub" if status == "ok" else status)})
        if best is None:
            continue
        saving = round(float(nonstop.price) - float(best.price), 2)
        pct = round(saving / float(nonstop.price) * 100, 1)
        if saving < min_saving_gbp or pct < min_saving_pct:
            reads[-1]["status"] = "through fare, no saving"
            continue
        result["leads"].append({
            "ticketed_to": read.destination, "leave_at": best.via_airports[0],
            "per_person_gbp": round(float(best.price), 2), "saving_gbp": saving, "saving_pct": pct,
            "airline": str(best.airline), "departure": best.departure,
            "first_leg_hours": (best.leg_hours[0] if best.leg_hours else None),
            "source_url": best.booking_url, "observed_at": stamp, "confidence_label": CONFIDENCE})
    result["leads"].sort(key=lambda lead: -lead["saving_gbp"])
    return result


def make_google_fetch() -> Callable[[FareRead], tuple[str, Sequence[Any]]]:
    """One traveller, one way, economy, at least ten seconds apart, through the package's Google Flights reader."""
    from . import google_flights as _gf
    from .config import FlightSearch

    delay = max(10.0, float(os.environ.get("GOOGLE_FLIGHTS_DELAY_SECONDS", "12")))
    last = [0.0]

    def fetch(read: FareRead) -> tuple[str, Sequence[Any]]:
        wait = delay * random.uniform(0.9, 1.25) - (time.monotonic() - last[0])
        if last[0] and wait > 0:
            time.sleep(wait)
        url = _gf.build_google_flights_url(origin=read.origin, destination=read.destination, date=read.day,
                                           travellers=1, cabin_class="ECONOMY")
        page = _gf._fetch_page_html(url)
        last[0] = time.monotonic()
        if page is None:
            return "failed", ()
        if _gf._is_waf_response(page):
            return "wall", ()
        spec = FlightSearch(key="beyond-fares", label="beyond fares", origins=(read.origin,),
                            destinations=(read.destination,), dates=(read.day,), travellers=1,
                            cabin_class="ECONOMY", departure_window=("00:00", "23:59"), max_stops=1,
                            max_duration_minutes=1440, max_price_per_traveller_gbp=None)
        tally: dict = {}
        offers = _gf._parse_flight_cards(page, search=spec, origin=read.origin, destination=read.destination,
                                         day=read.day, booking_url=url, tally=tally)
        if not offers and tally.get("payload_refused_error"):
            return "refused", ()
        return "ok", offers

    return fetch


def render_text(result: Mapping[str, Any]) -> str:
    head = f"{result['origin']} to {result['hub_label']} ({result['hub']}), {result['day']}, one way, one traveller"
    nonstop = result.get("nonstop")
    if not nonstop:
        return f"{head}\n  no nonstop fare to the hub was read (" + ", ".join(
            f"{r['destination']}: {r['status']}" for r in result.get("reads", [])) + "); nothing to compare with"
    lines = [head, f"  nonstop to {nonstop['destination']}: £{nonstop['per_person_gbp']:,.0f} ({nonstop['airline']})"]
    for lead in result.get("leads", []):
        lines.append(f"  ticket to {lead['ticketed_to']}, leaving at {lead['leave_at']}: £{lead['per_person_gbp']:,.0f} "
                     f"({lead['airline']}), £{lead['saving_gbp']:,.0f} less ({lead['saving_pct']:.0f}%)")
    if not result.get("leads"):
        lines.append("  no onward ticket through the hub was cheaper by enough")
    lines.append("  reads: " + ", ".join(f"{r['destination']} {r['status']}" for r in result.get("reads", [])))
    return "\n".join(lines)


def main(arguments: Sequence[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="beyond-fares", description=__doc__.split("\n\n")[0])
    parser.add_argument("--origin", default="LHR", help="comma-separated origin airports")
    parser.add_argument("--hub", required=True, help="comma-separated hubs from data/beyond_cities.json, or all")
    parser.add_argument("--date", required=True, help="comma-separated departure dates, YYYY-MM-DD")
    parser.add_argument("--beyond", default="", help="onward cities to search instead of the hub's own list")
    parser.add_argument("--out", default="", help="write the results as JSON here")
    args = parser.parse_args(list(arguments))
    hubs = load_hubs()
    wanted = list(hubs) if args.hub.strip().lower() == "all" else [h.strip().upper() for h in args.hub.split(",")]
    unknown = [h for h in wanted if h not in hubs]
    if unknown:
        parser.error(f"unknown hub(s) {', '.join(unknown)}; known: {', '.join(hubs)}")
    origins = [o.strip().upper() for o in args.origin.split(",") if o.strip()]
    days = [d.strip() for d in args.date.split(",") if d.strip()]
    for day in days:
        if date.fromisoformat(day) < datetime.now(timezone.utc).date():
            parser.error(f"{day} has passed")
    if not all(_code(o) for o in origins):
        parser.error("origins are three-letter airport codes")
    override = tuple(b.strip().upper() for b in args.beyond.split(",") if b.strip())
    if not all(_code(b) for b in override):
        parser.error("onward cities are three-letter airport codes")
    fetch = make_google_fetch()
    results = []
    for origin in origins:
        for code in wanted:
            hub = hubs[code]
            if override:
                hub = Hub(hub.hub, hub.label, hub.airports,
                          tuple(b for b in override if b not in hub.airports)[:MAX_BEYOND_PER_HUB])
            for day in days:
                result = find_beyond_fares(origin, hub, day, fetch)
                results.append(result)
                print(render_text(result), flush=True)
    print("\nBefore buying any of these:\n" + "\n".join(f"  - {c}" for c in CAVEATS))
    if args.out:
        from .weekly_fares import write_atomic

        write_atomic(args.out, {"schema": SCHEMA, "results": results})
    print(f"beyond fares: {len(results)} hub-day(s), {sum(len(r['leads']) for r in results)} cheaper onward ticket(s)",
          file=sys.stderr)
    return 0
