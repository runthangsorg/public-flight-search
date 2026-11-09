"""This week's live fares for every July destination, for the one weekly e-mail (owner, 9 Nov 2026).

The July cards price only whole-party fares from the private engine's evidence, which the laptop hunt refreshes
when it runs. When it has not run, most destinations sat under "Not yet priced". The Sunday run now also reads
one traveller's economy and business fare for every destination through the same Google Flights reader the
business watcher uses on Actions, and the e-mail shows them in their own section: per person, with the party
figure labelled as scaled. They never price a card (cards stay whole-party; see ``live_verify``).
"""

from __future__ import annotations

import html as _html
import json
import math
import os
import random
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

SCHEMA = "july_weekly_fares/1"
DEFAULT_PATH = "data/july_weekly_fares.json"
DEFAULT_BUSINESS_HISTORY = "data/business_deals_history.jsonl"
CABINS = ("ECONOMY", "BUSINESS")
ORIGIN = "LHR"
#: The trip length the section quotes; the cards still price every configured pair.
REFERENCE_NIGHTS = 17
MAX_STOPS = 2
#: Owner destinations the July config does not price as cards yet, so the weekly read still covers them.
EXTRA_AIRPORTS: Mapping[str, str] = {
    "MLE": "Maldives",
    "HND": "Tokyo",
    "ZRH": "Zurich (Swiss lakes)",
    "VCE": "Venice",
}


@dataclass(frozen=True)
class FareSearch:
    airport: str
    label: str
    cabin: str
    outbound: str
    return_date: str


def fare_airports(config: Any) -> list[tuple[str, str]]:
    """Every airport the July config prices, in config order, then the extra owner destinations."""
    seen: dict[str, str] = {}
    for dest in getattr(config, "destinations", ()) or ():
        # "Lombok, Indonesia (Kuta Mandalika beaches; ...)" -> "Lombok, Indonesia": the table has no room for notes.
        label = str(getattr(dest, "label", "") or "").split(" (")[0].strip()
        for code in getattr(dest, "airports", ()) or ():
            code = str(code).strip().upper()
            if code and code not in seen:
                seen[code] = label or code
            elif code in seen and label and label not in seen[code]:
                seen[code] = f"{seen[code]} / {label}"
    for code, label in EXTRA_AIRPORTS.items():
        seen.setdefault(code, label)
    return list(seen.items())


def reference_dates(config: Any) -> tuple[str, str]:
    """The priced date pair nearest REFERENCE_NIGHTS nights, earliest outbound first."""
    from .holidays import priceable_date_pairs

    pairs = list(priceable_date_pairs(config))
    if not pairs:
        raise ValueError("the config prices no date pair")

    def nights(pair: tuple[str, str]) -> int:
        return (datetime.fromisoformat(pair[1]) - datetime.fromisoformat(pair[0])).days

    return min(pairs, key=lambda p: (abs(nights(p) - REFERENCE_NIGHTS), p[0], p[1]))


def plan(config: Any) -> list[FareSearch]:
    outbound, return_date = reference_dates(config)
    return [FareSearch(code, label, cabin, outbound, return_date)
            for code, label in fare_airports(config) for cabin in CABINS]


def _cheapest(offers: Iterable[Any], search: FareSearch) -> Optional[Any]:
    from .business_airlines import excluded_airline
    from .engine import FlightOffer

    good = []
    for item in offers:
        try:
            offer = item if isinstance(item, FlightOffer) else FlightOffer.from_mapping(item)
            price = float(offer.price)
        except (KeyError, TypeError, ValueError):
            continue
        if not math.isfinite(price) or price <= 0 or offer.currency != "GBP":
            continue
        if offer.destination != search.airport or offer.stops > MAX_STOPS:
            continue
        if search.cabin == "BUSINESS" and excluded_airline(str(offer.airline or "")):
            continue
        good.append(offer)
    return min(good, key=lambda o: (o.price, o.duration_minutes)) if good else None


def read_weekly_fares(config: Any, fetch: Callable[[FareSearch], tuple[str, Sequence[Any]]], *,
                      now: Optional[datetime] = None, max_searches: Optional[int] = None) -> dict:
    """Read every planned search; ``fetch`` returns ``(status, offers)`` with status ok, wall or failed."""
    now = now or datetime.now(timezone.utc)
    travellers = int(getattr(config, "travellers", 1) or 1)
    rows = []
    searches = plan(config)
    if max_searches is not None:
        searches = searches[:max_searches]
    for search in searches:
        status, offers = fetch(search)
        row = {"airport": search.airport, "label": search.label, "cabin": search.cabin,
               "outbound": search.outbound, "return": search.return_date, "status": status,
               "observed_at": now.isoformat(timespec="seconds")}
        best = _cheapest(offers, search) if status == "ok" else None
        if best is not None:
            per_person = round(float(best.price), 2)
            row.update(status="priced", per_person_gbp=per_person,
                       party_estimate_gbp=round(per_person * travellers, 2), travellers=travellers,
                       airline=str(best.airline or ""), stops=int(best.stops),
                       duration_minutes=int(best.duration_minutes), booking_url=best.booking_url)
        elif status == "ok":
            row["status"] = "no fares"
        rows.append(row)
    return {"schema": SCHEMA, "generated_at": now.isoformat(timespec="seconds"), "origin": ORIGIN,
            "travellers": travellers, "rows": rows}


def make_google_fetch() -> Callable[[FareSearch], tuple[str, Sequence[Any]]]:
    """One traveller per search, at least ten seconds apart, through the package's Google Flights reader."""
    from . import google_flights as _gf
    from .config import FlightSearch

    delay = max(10.0, float(os.environ.get("GOOGLE_FLIGHTS_DELAY_SECONDS", "12")))
    last = [0.0]

    def fetch(search: FareSearch) -> tuple[str, Sequence[Any]]:
        wait = delay * random.uniform(0.9, 1.25) - (time.monotonic() - last[0])
        if last[0] and wait > 0:
            time.sleep(wait)
        url = _gf.build_google_flights_roundtrip_url(origin=ORIGIN, destination=search.airport,
                                                     outbound_date=search.outbound, return_date=search.return_date,
                                                     travellers=1, cabin_class=search.cabin)
        page = _gf._fetch_page_html(url)
        last[0] = time.monotonic()
        if page is None:
            return "failed", ()
        if _gf._is_waf_response(page):
            return "wall", ()
        spec = FlightSearch(key="weekly-fares", label="weekly fares", origins=(ORIGIN,),
                            destinations=(search.airport,), dates=(search.outbound,), travellers=1,
                            cabin_class=search.cabin, departure_window=("00:00", "23:59"),
                            max_stops=MAX_STOPS, max_duration_minutes=2160, max_price_per_traveller_gbp=None)
        offers = _gf._parse_flight_cards(page, search=spec, origin=ORIGIN, destination=search.airport,
                                         day=search.outbound, booking_url=url, tally={})
        return "ok", offers

    return fetch


def load_weekly_fares(path: str = DEFAULT_PATH) -> Optional[dict]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) and payload.get("schema") == SCHEMA else None


def _stamp(value: Any) -> Optional[datetime]:
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def best_business_this_week(history: Iterable[Mapping[str, Any]], now: datetime, *, days: int = 7,
                            limit: int = 8, window_days: int = 90) -> list[dict]:
    """The cheapest business fare per destination observed in the last ``days``, with its route median."""
    rows = [r for r in history if _stamp(r.get("observed_at")) and r.get("per_person_gbp")]
    medians: dict[str, list[float]] = {}
    for r in rows:
        if _stamp(r["observed_at"]) >= now - timedelta(days=window_days):
            medians.setdefault(str(r.get("destination")), []).append(float(r["per_person_gbp"]))
    best: dict[str, dict] = {}
    for r in rows:
        if _stamp(r["observed_at"]) < now - timedelta(days=days):
            continue
        dest = str(r.get("destination"))
        if dest not in best or float(r["per_person_gbp"]) < float(best[dest]["per_person_gbp"]):
            best[dest] = dict(r)
    out = []
    for dest, r in best.items():
        pool = medians.get(dest, [])
        median = statistics.median(pool) if len(pool) >= 3 else None
        r["median_gbp"] = round(median, 2) if median else None
        r["pct_below_median"] = round((1 - float(r["per_person_gbp"]) / median) * 100, 1) if median else None
        out.append(r)
    out.sort(key=lambda r: float(r["per_person_gbp"]))
    return out[:limit]


def read_jsonl(path: str) -> list[dict]:
    rows = []
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(item, dict):
                        rows.append(item)
    except (FileNotFoundError, OSError):
        return []
    return rows


_H = ("font-size:13px; font-weight:700; text-transform:uppercase; letter-spacing:0.5px; color:#334155; "
      "margin:18px 0 6px 0;")
_TH = "padding:4px 6px; background:#334155; color:#FFFFFF; font-size:11px; text-align:left;"
_TD = "padding:4px 6px; border-top:1px solid #E2E8F0; font-size:12px; color:#0F172A;"


def _gbp(value: float) -> str:
    return f"£{value:,.0f}"


def _day(stamp: Any) -> str:
    when = _stamp(stamp)
    return f"{when.day} {when:%b}" if when else "?"


def render_section_html(weekly: Optional[Mapping[str, Any]], business: Sequence[Mapping[str, Any]]) -> str:
    """The two weekly sections: live fares for every destination, then the week's best business fares."""
    e = _html.escape
    out: list[str] = []
    if weekly and weekly.get("rows"):
        travellers = int(weekly.get("travellers") or 1)
        rows = weekly["rows"]
        first = rows[0]
        out.append(f'<div style="{_H}">Live fares this week, every destination</div>')
        out.append(f'<div style="font-size:12px; color:#475569; margin-bottom:4px;">From {e(str(weekly.get("origin", ORIGIN)))}, '
                   f'{e(_day(first.get("outbound")))} to {e(_day(first.get("return")))}, read {e(_day(weekly.get("generated_at")))} '
                   f'on Google Flights for one traveller; the party figure is that fare × {travellers}, not a quote '
                   f'for {travellers}. Stays are not included.</div>')
        out.append('<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" '
                   'style="border-collapse:collapse; background:#FFFFFF;">')
        out.append(f'<tr><th style="{_TH}">Destination</th><th style="{_TH}">Economy pp</th>'
                   f'<th style="{_TH}">Business pp</th><th style="{_TH}">≈ for {travellers}</th></tr>')
        by_airport: dict[str, dict[str, Mapping[str, Any]]] = {}
        order: list[str] = []
        for r in rows:
            if r["airport"] not in by_airport:
                order.append(r["airport"])
            by_airport.setdefault(r["airport"], {})[r["cabin"]] = r

        def cell(r: Optional[Mapping[str, Any]]) -> str:
            if not r:
                return "not read"
            if r.get("status") != "priced":
                return e(str(r.get("status", "not read")))
            link = r.get("booking_url") or ""
            text = f'{_gbp(float(r["per_person_gbp"]))}<br><span style="color:#475569; font-size:11px;">' \
                   f'{e(str(r.get("airline", "")))}, {int(r.get("stops", 0))} stop(s)</span>'
            return f'<a href="{e(link)}" style="color:#155f8f;">{text}</a>' if link else text

        for code in order:
            cabins = by_airport[code]
            econ, biz = cabins.get("ECONOMY"), cabins.get("BUSINESS")
            label = (econ or biz or {}).get("label", code)
            party = " / ".join(f"{name} {_gbp(float(r['party_estimate_gbp']))}" for name, r in
                               (("E", econ), ("B", biz)) if r and r.get("status") == "priced") or "–"
            out.append(f'<tr><td style="{_TD}"><strong>{e(str(label))}</strong> ({e(code)})</td>'
                       f'<td style="{_TD}">{cell(econ)}</td><td style="{_TD}">{cell(biz)}</td>'
                       f'<td style="{_TD}">{e(party)}</td></tr>')
        out.append("</table>")
    if business:
        out.append(f'<div style="{_H}">Best business fares this week</div>')
        out.append('<div style="font-size:12px; color:#475569; margin-bottom:4px;">The daily business watcher\'s '
                   'cheapest read per destination over the last 7 days, per person. It only e-mails on its own when a '
                   'fare is at least 40% under its usual price.</div>')
        out.append('<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" '
                   'style="border-collapse:collapse; background:#FFFFFF;">')
        out.append(f'<tr><th style="{_TH}">Route</th><th style="{_TH}">Per person</th>'
                   f'<th style="{_TH}">vs usual</th><th style="{_TH}">Read</th></tr>')
        for r in business:
            route = f'{r.get("origin", "")}→{r.get("destination", "")} {str(r.get("departure", ""))[:10]}'
            pct = r.get("pct_below_median")
            vs = (f"{pct:.0f}% under {_gbp(float(r['median_gbp']))}" if pct is not None and pct > 0
                  else (f"usual {_gbp(float(r['median_gbp']))}" if r.get("median_gbp") else "too new to compare"))
            link = r.get("booking_url") or ""
            price = _gbp(float(r["per_person_gbp"])) + f'<br><span style="color:#475569; font-size:11px;">{e(str(r.get("airline", "")))}</span>'
            price = f'<a href="{e(link)}" style="color:#155f8f;">{price}</a>' if link else price
            out.append(f'<tr><td style="{_TD}">{e(route)}</td><td style="{_TD}">{price}</td>'
                       f'<td style="{_TD}">{e(vs)}</td><td style="{_TD}">{e(_day(r.get("observed_at")))}</td></tr>')
        out.append("</table>")
    return "".join(out)


def render_section_text(weekly: Optional[Mapping[str, Any]], business: Sequence[Mapping[str, Any]]) -> str:
    lines: list[str] = []
    if weekly and weekly.get("rows"):
        lines.append(f"Live fares this week (one traveller, read {_day(weekly.get('generated_at'))}):")
        for r in weekly["rows"]:
            if r.get("status") == "priced":
                lines.append(f"  {r['label']} ({r['airport']}) {r['cabin'].lower()}: {_gbp(float(r['per_person_gbp']))} pp, "
                             f"{r.get('airline', '')}")
    if business:
        lines.append("Best business fares this week:")
        for r in business:
            lines.append(f"  {r.get('origin')}→{r.get('destination')} {str(r.get('departure', ''))[:10]}: "
                         f"{_gbp(float(r['per_person_gbp']))} pp, {r.get('airline', '')}")
    return "\n".join(lines)


def insert_section(html: str, section: str) -> str:
    """Put the weekly sections before "Not yet priced" when the body has it, else before the body's last </div>."""
    if not section:
        return html
    marker = html.find(">Not yet priced</div>")
    if marker != -1:
        start = html.rfind("<div", 0, marker)
        if start != -1:
            return html[:start] + section + html[start:]
    end = html.rfind("</div>")
    return html[:end] + section + html[end:] if end != -1 else html + section


def weekly_sections(now: Optional[datetime] = None) -> tuple[str, str]:
    """HTML and text for the July body from the files the workflow lands; empty when neither exists."""
    now = now or datetime.now(timezone.utc)
    weekly = load_weekly_fares(os.environ.get("JULY_WEEKLY_FARES_PATH", DEFAULT_PATH))
    history = read_jsonl(os.environ.get("BUSINESS_DEALS_HISTORY", DEFAULT_BUSINESS_HISTORY))
    business = best_business_this_week(history, now)
    return render_section_html(weekly, business), render_section_text(weekly, business)


def main(arguments: Sequence[str]) -> int:
    import argparse

    from .holidays import load_holiday_config

    parser = argparse.ArgumentParser(prog="july-weekly-fares")
    parser.add_argument("--config", default="examples/july_holiday_config.json")
    parser.add_argument("--out", default=DEFAULT_PATH)
    parser.add_argument("--max-searches", type=int, default=None)
    parser.add_argument("--plan-only", action="store_true", help="print the searches; read nothing")
    args = parser.parse_args(list(arguments))
    config = load_holiday_config(Path(args.config).read_text(encoding="utf-8"))
    if args.plan_only:
        for s in plan(config):
            print(f"{s.airport} {s.cabin} {s.outbound}→{s.return_date} ({s.label})")
        return 0
    payload = read_weekly_fares(config, make_google_fetch(), max_searches=args.max_searches)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(payload, indent=1), encoding="utf-8")
    counts: dict[str, int] = {}
    for r in payload["rows"]:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print(f"weekly fares: {len(payload['rows'])} searches; " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())),
          file=sys.stderr)
    return 0
