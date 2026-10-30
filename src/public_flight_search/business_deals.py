"""Daily business-class deal watch: long-haul fares, cheaper positioning origins, mail only on a real deal.

Fares are read exactly the way the rest of the package reads them (the Google Flights results page through
``google_flights``); walls are recorded and the run stops, never worked around. Each run takes one rotating slice
of the origin x destination x date grid, appends what it saw to an append-only JSONL history, and e-mails ONLY when
at least one fare is a special deal. Silence is the normal outcome and costs one log line.

A fare is a deal when its total (fare + the origin's positioning cost) is

* at least ``median_drop_pct`` below the median of the same origin, destination and departure month over the last
  ``median_window_days`` (needs ``min_observations`` earlier readings; before that the history is cold and only the
  cap can fire), OR
* at or below the absolute cap set for its world region;

and, for a positioning origin (not ``home``), also at least ``away_min_saving_pct`` below the best home-airport total
for the same destination and date. With no home price to compare, a positioning origin can only fire on the cap.
The same deal is not mailed again within ``dedupe_days`` unless it drops by ``redrop_pct`` or more.
"""

from __future__ import annotations

import hashlib
import html as _html
import json
import logging
import math
import os
import random
import re
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

from . import google_flights as _gf
from .business_airlines import excluded_airline
from .cabin import BUSINESS_FLIGHT_HOURS
from .config import FlightSearch
from .engine import FlightOffer

logger = logging.getLogger(__name__)

CABIN = "BUSINESS"
HISTORY_DEFAULT_PATH = Path("data/business_deals_history.jsonl")
MAX_CONFIG_BYTES = 200_000
_AIRPORT = re.compile(r"^[A-Z]{3}$")
_TOP_LEVEL = {
    "report_title", "notes", "origins", "destinations", "dates", "date_windows", "min_days_ahead",
    "min_observations", "median_drop_pct", "median_window_days", "away_min_saving_pct", "dedupe_days",
    "redrop_pct", "max_searches_per_run", "max_stops", "min_fare_gbp", "max_fare_gbp", "stop_after_blocked",
    "absolute_caps_gbp", "exclude_airlines", "exclude_destinations", "travellers", "trip_nights",
}
#: Destinations the watch never prices, whatever the config lists (owner, 30 Oct 2026: "i dont want to go to
#: INDIA"; a Delhi fare was mailed because only one of the two engines had the exclusion). Connecting through one is
#: fine: this filters where the trip goes, not the route a fare takes. ``exclude_destinations`` adds more.
EXCLUDED_DESTINATIONS = frozenset({
    "DEL", "BOM", "BLR", "MAA", "HYD", "CCU", "COK", "AMD", "GOI", "GOX", "JAI", "PNQ", "TRV", "ATQ", "LKO",
    "CCJ", "IXC", "NAG", "VNS", "PAT", "GAU", "BBI", "IXB", "SXR", "IXM", "TRZ", "IXE", "IDR", "VTZ", "CJB",
    "IXA", "IXZ", "BDQ", "RPR", "DED", "STV", "IXJ", "IXR", "IXU", "IXL", "BHO", "UDR", "JDH", "IXG", "HBX",
    "MYQ", "IXD", "GAY", "DIB", "IMF", "AJL", "JRH", "IXS", "BHJ", "RAJ", "KNU", "AGR", "GWL", "JLR", "DHM",
    "KUU", "SAG", "KLH", "TIR", "VGA", "RJA", "NMI", "DXN", "IXY", "DGH",
})


class BusinessDealsConfigError(ValueError):
    """The deal-watch configuration is invalid."""


@dataclass(frozen=True)
class Origin:
    code: str
    label: str
    positioning_gbp: float
    home: bool


@dataclass(frozen=True)
class Destination:
    code: str
    label: str
    region: str
    hours_from_london: float


@dataclass(frozen=True)
class BusinessDealsConfig:
    title: str
    origins: tuple[Origin, ...]
    destinations: tuple[Destination, ...]
    dates: tuple[str, ...]
    min_observations: int = 5
    median_drop_pct: float = 30.0
    median_window_days: int = 90
    away_min_saving_pct: float = 20.0
    dedupe_days: int = 7
    redrop_pct: float = 2.0
    max_searches_per_run: int = 48
    max_stops: int = 1
    min_fare_gbp: float = 150.0
    max_fare_gbp: float = 20000.0
    stop_after_blocked: int = 3
    caps: Mapping[str, float] = field(default_factory=dict)
    #: Airlines added to ``business_airlines.EXCLUDED_FOR_BUSINESS`` (that list always applies).
    exclude_airlines: tuple[str, ...] = ()
    #: Airports added to ``EXCLUDED_DESTINATIONS`` (that list always applies).
    exclude_destinations: tuple[str, ...] = ()
    #: Party size priced on round trips (1-9); one-way reads stay one traveller.
    travellers: int = 1
    #: Round-trip lengths in nights (each 3-30); empty keeps today's one-way behaviour.
    trip_nights: tuple[int, ...] = ()

@dataclass(frozen=True)
class SearchSpec:
    origin: str
    destination: str
    date: str
    return_date: str = ""


@dataclass(frozen=True)
class FetchOutcome:
    """``status`` is ``ok``, ``wall`` (a challenge page was served) or ``failed`` (no page)."""

    status: str
    offers: Sequence[Any] = ()


@dataclass
class Deal:
    key: str
    origin: str
    origin_label: str
    destination: str
    destination_label: str
    region: str
    departure: str
    fare_gbp: float
    positioning_gbp: float
    total_gbp: float
    stops: int
    duration_minutes: int
    airline: str
    booking_url: str
    trigger: str
    history_n: int
    cold_start: bool
    median_gbp: Optional[float]
    pct_below_median: Optional[float]
    home_total_gbp: Optional[float]
    saving_vs_home_pct: Optional[float]
    last_seen: str
    first_seen: str
    per_person_gbp: float = 0.0
    return_date: str = ""
    travellers: int = 1


@dataclass
class JobResult:
    deals: list = field(default_factory=list)
    mailed: bool = False
    searched: int = 0
    ok: int = 0
    walled: int = 0
    failed: int = 0
    offers_seen: int = 0
    rejected: int = 0
    history_rows_added: int = 0
    stopped_early: bool = False
    log_line: str = ""


# --------------------------------------------------------------------------- config


def _airline_names(value: Any) -> tuple[str, ...]:
    """``exclude_airlines``: a list of up to 50 airline names."""
    if value is None:
        return ()
    if (not isinstance(value, list) or len(value) > 50
            or not all(isinstance(v, str) and 0 < len(v.strip()) <= 60 for v in value)):
        raise BusinessDealsConfigError("exclude_airlines must be a list of up to 50 airline names")
    return tuple(v.strip() for v in value)


def _destination_codes(value: Any) -> tuple[str, ...]:
    """``exclude_destinations``: a list of up to 100 three-letter airport codes."""
    if value is None:
        return ()
    if (not isinstance(value, list) or len(value) > 100
            or not all(isinstance(v, str) and _AIRPORT.fullmatch(v.strip().upper()) for v in value)):
        raise BusinessDealsConfigError("exclude_destinations must be a list of up to 100 three-letter airport codes")
    return tuple(v.strip().upper() for v in value)


def _num(raw: Mapping[str, Any], name: str, default: float, low: float, high: float) -> float:
    try:
        value = float(raw.get(name, default))
    except (TypeError, ValueError):
        raise BusinessDealsConfigError(f"{name} must be a number") from None
    if not math.isfinite(value) or not low <= value <= high:
        raise BusinessDealsConfigError(f"{name} must be between {low} and {high}")
    return value


def _code(value: Any, what: str) -> str:
    code = str(value or "").strip().upper()
    if not _AIRPORT.fullmatch(code):
        raise BusinessDealsConfigError(f"{what}: airport code must be three letters")
    return code


def _iso(value: Any, what: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise BusinessDealsConfigError(f"{what}: not an ISO date") from None


def _trip_nights(value: Any) -> tuple[int, ...]:
    """``trip_nights``: a list of 1-6 ints, each 3-30 (empty keeps one-way)."""
    if value is None:
        return ()
    if not isinstance(value, list):
        raise BusinessDealsConfigError("trip_nights must be a list of 1-6 ints")
    if len(value) > 6:
        raise BusinessDealsConfigError("trip_nights must contain at most 6 nights")
    result = []
    for item in value:
        if isinstance(item, bool):
            raise BusinessDealsConfigError("trip_nights must be ints")
        try:
            n = int(item)
        except (TypeError, ValueError):
            raise BusinessDealsConfigError("trip_nights must be ints") from None
        if isinstance(item, float) and not float(item).is_integer():
            raise BusinessDealsConfigError("trip_nights must be ints")
        if not 3 <= n <= 30:
            raise BusinessDealsConfigError("trip_nights values must be between 3 and 30")
        result.append(n)
    return tuple(result)


def load_config(source: Any, *, today: Optional[date] = None) -> BusinessDealsConfig:
    """Parse and validate a config from JSON text or a mapping. Past departure dates are dropped."""
    today = today or datetime.now(timezone.utc).date()
    if isinstance(source, (str, bytes)):
        if len(source) > MAX_CONFIG_BYTES:
            raise BusinessDealsConfigError("config is too large")
        try:
            raw = json.loads(source)
        except json.JSONDecodeError as exc:
            raise BusinessDealsConfigError(f"config is not valid JSON: {exc}") from None
    else:
        raw = dict(source)
    if not isinstance(raw, dict):
        raise BusinessDealsConfigError("config must be a JSON object")
    unknown = set(raw) - _TOP_LEVEL
    if unknown:
        raise BusinessDealsConfigError(f"unknown config fields: {sorted(unknown)}")

    origins = []
    for item in raw.get("origins") or []:
        origins.append(Origin(
            code=_code(item.get("code"), "origin"),
            label=str(item.get("label") or item.get("code"))[:60],
            positioning_gbp=_num(item, "positioning_gbp", 0.0, 0.0, 5000.0),
            home=bool(item.get("home", False)),
        ))
    if len({o.code for o in origins}) != len(origins) or not origins:
        raise BusinessDealsConfigError("origins must be a non-empty list of distinct airports")
    if not any(o.home for o in origins):
        raise BusinessDealsConfigError("at least one origin must be home (the price positioning origins must beat)")

    excluded = _destination_codes(raw.get("exclude_destinations"))
    destinations = []
    for item in raw.get("destinations") or []:
        hours = _num(item, "hours_from_london", 0.0, 0.0, 40.0)
        code = _code(item.get("code"), "destination")
        if code in EXCLUDED_DESTINATIONS or code in excluded:
            continue
        if hours <= BUSINESS_FLIGHT_HOURS:  # strictly over 8 hours, the package's one cabin boundary
            raise BusinessDealsConfigError(
                f"{code}: {hours}h is not over {BUSINESS_FLIGHT_HOURS:g} hours, so it is not a long-haul business route")
        region = str(item.get("region") or "").strip().lower()
        if not region:
            raise BusinessDealsConfigError(f"{code}: region is required")
        destinations.append(Destination(code, str(item.get("label") or code)[:60], region, hours))
    if len({d.code for d in destinations}) != len(destinations) or not destinations:
        raise BusinessDealsConfigError("destinations must be a non-empty list of distinct airports")

    min_ahead = int(_num(raw, "min_days_ahead", 7, 0, 365))
    earliest = today + timedelta(days=min_ahead)
    days: set[date] = {_iso(d, "dates") for d in raw.get("dates") or []}
    for window in raw.get("date_windows") or []:
        start, end = _iso(window.get("start"), "date_windows.start"), _iso(window.get("end"), "date_windows.end")
        step = int(_num(window, "every_days", 14, 1, 120))
        if end < start or (end - start).days > 800:
            raise BusinessDealsConfigError("date_windows: end must follow start within 800 days")
        day = start
        while day <= end:
            days.add(day)
            day += timedelta(days=step)
    future = tuple(sorted(d.isoformat() for d in days if d >= earliest))
    if not future:
        raise BusinessDealsConfigError("no departure dates remain in the future: refresh the config dates")

    regions = {d.region for d in destinations}
    caps = {}
    for region, cap in (raw.get("absolute_caps_gbp") or {}).items():
        if region not in regions:
            raise BusinessDealsConfigError(f"absolute cap for unknown region {region!r}")
        caps[region] = _num({"c": cap}, "c", 0.0, 1.0, 100000.0)

    travellers_raw = _num(raw, "travellers", 1, 1, 9)
    if (isinstance(travellers_raw, float) and not float(travellers_raw).is_integer()) or travellers_raw != int(travellers_raw):
        raise BusinessDealsConfigError("travellers must be an integer")
    travellers = int(travellers_raw)
    return BusinessDealsConfig(
        title=str(raw.get("report_title") or "Business-class deals")[:120],
        origins=tuple(origins), destinations=tuple(destinations), dates=future,
        min_observations=int(_num(raw, "min_observations", 5, 3, 60)),
        median_drop_pct=_num(raw, "median_drop_pct", 30.0, 5.0, 90.0),
        median_window_days=int(_num(raw, "median_window_days", 90, 14, 365)),
        away_min_saving_pct=_num(raw, "away_min_saving_pct", 20.0, 0.0, 90.0),
        dedupe_days=int(_num(raw, "dedupe_days", 7, 1, 60)),
        redrop_pct=_num(raw, "redrop_pct", 2.0, 0.0, 50.0),
        max_searches_per_run=int(_num(raw, "max_searches_per_run", 48, 1, 80)),
        max_stops=int(_num(raw, "max_stops", 1, 0, 2)),
        min_fare_gbp=_num(raw, "min_fare_gbp", 150.0, 1.0, 5000.0),
        max_fare_gbp=_num(raw, "max_fare_gbp", 20000.0, 500.0, 100000.0),
        stop_after_blocked=int(_num(raw, "stop_after_blocked", 3, 1, 10)),
        caps=caps,
        exclude_airlines=_airline_names(raw.get("exclude_airlines")),
        exclude_destinations=excluded,
        travellers=travellers,
        trip_nights=_trip_nights(raw.get("trip_nights")),
    )


# --------------------------------------------------------------------------- planning


def _grid(cfg: BusinessDealsConfig) -> list[SearchSpec]:
    # Same destination and date sit side by side, so a positioning origin is usually priced in the same run as the
    # home airport it has to beat. With trip_nights set, each date expands into one round trip per nights value.
    if not cfg.trip_nights:
        return [SearchSpec(o.code, d.code, day) for day in cfg.dates for d in cfg.destinations for o in cfg.origins]
    from datetime import date as _date, timedelta as _td
    specs: list[SearchSpec] = []
    for day in cfg.dates:
        for nights in cfg.trip_nights:
            return_date = (_date.fromisoformat(day) + _td(days=nights)).isoformat()
            for d in cfg.destinations:
                for o in cfg.origins:
                    specs.append(SearchSpec(o.code, d.code, day, return_date))
    return specs


def cycle_days(cfg: BusinessDealsConfig) -> int:
    return max(1, math.ceil(len(_grid(cfg)) / cfg.max_searches_per_run))


def plan_searches(cfg: BusinessDealsConfig, today: date) -> list[SearchSpec]:
    """Today's rotating slice of the grid; consecutive days cover consecutive slices, wrapping round."""
    grid = _grid(cfg)
    count = min(cfg.max_searches_per_run, len(grid))
    start = (today.toordinal() * cfg.max_searches_per_run) % len(grid)
    return [grid[(start + i) % len(grid)] for i in range(count)]


# --------------------------------------------------------------------------- observations


def _key(origin: str, destination: str, departure: str, return_date: str = "") -> str:
    base = f"{origin}|{destination}|{departure}"
    if return_date:
        base = f"{base}|{return_date}"
    return f"{base}|{CABIN}"


def _accept(offer: Any, spec: SearchSpec, cfg: BusinessDealsConfig) -> Optional[FlightOffer]:
    try:
        if not isinstance(offer, FlightOffer):
            offer = FlightOffer.from_mapping(offer)
        price = float(offer.price)
    except (KeyError, TypeError, ValueError):
        return None
    if not math.isfinite(price) or not cfg.min_fare_gbp <= price <= cfg.max_fare_gbp:
        return None
    if offer.currency != "GBP" or offer.origin != spec.origin or offer.destination != spec.destination:
        return None
    if offer.departure[:10] != spec.date or offer.stops > cfg.max_stops:
        return None
    if offer.duration_minutes <= BUSINESS_FLIGHT_HOURS * 60:
        return None
    if excluded_airline(str(offer.airline or ""), cfg.exclude_airlines):
        return None  # no business class on low-cost carriers or Air India (owner, 27 Oct 2026)
    return offer


def cheapest_observation(offers: Iterable[Any], spec: SearchSpec, cfg: BusinessDealsConfig,
                          now: datetime) -> tuple[Optional[dict], int]:
    """The cheapest acceptable fare for one search as a history row, and how many offers were rejected."""
    origin = next(o for o in cfg.origins if o.code == spec.origin)
    destination = next(d for d in cfg.destinations if d.code == spec.destination)
    good, rejected = [], 0
    for item in offers:
        accepted = _accept(item, spec, cfg)
        if accepted is None:
            rejected += 1
        else:
            good.append(accepted)
    if not good:
        return None, rejected
    best = min(good, key=lambda o: (o.price, o.duration_minutes))
    fare = round(best.price, 2)
    travellers = cfg.travellers if spec.return_date else 1
    positioning = origin.positioning_gbp * travellers
    total = round(fare + positioning, 2)
    per_person = round(total / travellers, 2)
    return {
        "fingerprint": hashlib.sha1(_key(spec.origin, spec.destination, spec.date, spec.return_date).encode()).hexdigest()[:16],
        "key": _key(spec.origin, spec.destination, spec.date, spec.return_date),
        "origin": spec.origin, "destination": spec.destination, "region": destination.region,
        "departure": spec.date, "return_date": spec.return_date, "cabin_class": CABIN,
        "travellers": travellers,
        "fare_gbp": fare, "positioning_gbp": origin.positioning_gbp,
        "total_gbp": total, "per_person_gbp": per_person,
        "stops": best.stops, "duration_minutes": best.duration_minutes, "airline": best.airline,
        "provider": best.provider, "booking_url": best.booking_url,
        "observed_at": now.isoformat(timespec="seconds"), "origin_is_home": origin.home,
    }, rejected


# --------------------------------------------------------------------------- storage


def read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except FileNotFoundError:
        pass
    return rows


def _append_jsonl(path: Path, rows: Sequence[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def append_observations(path: Path, rows: Sequence[dict], existing: Sequence[dict]) -> int:
    """Append rows, at most one per route and UTC day so a re-run never inflates the median."""
    seen = {(r.get("fingerprint") or r.get("key"), str(r.get("observed_at", ""))[:10]) for r in existing}
    fresh = [r for r in rows if (r["fingerprint"], r["observed_at"][:10]) not in seen]
    _append_jsonl(path, fresh)
    return len(fresh)


def _when(row: Mapping[str, Any]) -> Optional[datetime]:
    try:
        stamp = datetime.fromisoformat(str(row.get("observed_at")))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def _total(row: Mapping[str, Any]) -> Optional[float]:
    try:
        value = float(row.get("total_gbp"))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value > 0 else None


def _row_trip_nights(row: Mapping[str, Any]) -> str:
    """"" for a one-way read, else the nights between departure and return: medians compare like with like
    (a 21-night return for the party against one-way history never looked like a deal, 30 Oct 2026)."""
    ret = str(row.get("return_date") or "")
    if not ret:
        return ""
    try:
        return str((date.fromisoformat(ret[:10]) - date.fromisoformat(str(row.get("departure", ""))[:10])).days)
    except ValueError:
        return ret


def _per_person(row: Mapping[str, Any]) -> Optional[float]:
    value = row.get("per_person_gbp", None)
    if value is None:
        value = row.get("total_gbp")
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and result > 0 else None


# --------------------------------------------------------------------------- deal rules


def find_deals(observations: Sequence[dict], history: Sequence[dict], alerts: Sequence[dict],
               cfg: BusinessDealsConfig, now: datetime) -> list[Deal]:
    origin_label = {o.code: o.label for o in cfg.origins}
    dest_label = {d.code: d.label for d in cfg.destinations}
    window_start = now - timedelta(days=cfg.median_window_days)
    pool: dict[tuple, list[float]] = defaultdict(list)
    first_seen: dict[str, datetime] = {}
    for row in history:
        stamp, total = _when(row), _total(row)
        per_person = _per_person(row)
        if stamp is None or total is None or per_person is None:
            continue
        key = str(row.get("key", ""))
        if key and (key not in first_seen or stamp < first_seen[key]):
            first_seen[key] = stamp
        if stamp >= window_start:
            pool[(row.get("origin"), row.get("destination"), row.get("cabin_class"),
                  str(row.get("departure", ""))[:7], _row_trip_nights(row))].append(per_person)

    def home_reference(obs: Mapping[str, Any]) -> Optional[float]:
        totals = [o["total_gbp"] for o in observations if o["origin_is_home"]
                  and o["destination"] == obs["destination"] and o["departure"] == obs["departure"]]
        if not totals:
            recent = now - timedelta(days=7)
            for row in history:
                stamp, total = _when(row), _total(row)
                if (row.get("origin_is_home") and row.get("destination") == obs["destination"]
                        and row.get("departure") == obs["departure"] and stamp and stamp >= recent and total):
                    totals.append(total)
        return min(totals) if totals else None

    by_key: dict[str, dict] = {}
    for row in alerts:
        stamp = _when({"observed_at": row.get("alerted_at")})
        if stamp and stamp >= now - timedelta(days=cfg.dedupe_days) and _per_person(row):
            if row["key"] not in by_key or stamp > _when({"observed_at": by_key[row["key"]]["alerted_at"]}):
                by_key[row["key"]] = row

    deals: list[Deal] = []
    for obs in observations:
        total = obs["total_gbp"]
        per_person = obs["per_person_gbp"]
        prior = pool.get((obs["origin"], obs["destination"], obs["cabin_class"], obs["departure"][:7],
                          _row_trip_nights(obs)), [])
        n = len(prior)
        median = statistics.median(prior) if n else None
        pct = round((1 - per_person / median) * 100, 1) if median else None
        median_hit = n >= cfg.min_observations and pct is not None and pct >= cfg.median_drop_pct
        cap = cfg.caps.get(obs["region"])
        cap_hit = cap is not None and per_person <= cap
        if not (median_hit or cap_hit):
            continue
        home_total = saving = None
        if not obs["origin_is_home"]:
            home_total = home_reference(obs)
            if home_total is None:
                if not cap_hit:
                    continue  # nothing to prove a positioning trip beats flying from home
            else:
                saving = round((1 - total / home_total) * 100, 1)
                if saving < cfg.away_min_saving_pct:
                    continue
        last = by_key.get(obs["key"])
        last_pp = _per_person(last) if last else None
        if last and last_pp is not None and per_person > last_pp * (1 - cfg.redrop_pct / 100):
            continue
        first = first_seen.get(obs["key"])
        deals.append(Deal(
            key=obs["key"], origin=obs["origin"], origin_label=origin_label[obs["origin"]],
            destination=obs["destination"], destination_label=dest_label[obs["destination"]],
            region=obs["region"], departure=obs["departure"], fare_gbp=obs["fare_gbp"],
            positioning_gbp=obs["positioning_gbp"], total_gbp=total, stops=obs["stops"],
            duration_minutes=obs["duration_minutes"], airline=obs["airline"], booking_url=obs["booking_url"],
            trigger="median+cap" if median_hit and cap_hit else ("median" if median_hit else "cap"),
            history_n=n, cold_start=n < cfg.min_observations,
            median_gbp=None if median is None else round(median, 2), pct_below_median=pct,
            home_total_gbp=home_total, saving_vs_home_pct=saving,
            last_seen=obs["observed_at"][:10], first_seen=(first or now).date().isoformat(),
            per_person_gbp=per_person, return_date=obs.get("return_date", ""),
            travellers=obs.get("travellers", 1),
        ))
    deals.sort(key=lambda d: (-(d.pct_below_median if d.pct_below_median is not None else -1), d.total_gbp))
    return deals


# --------------------------------------------------------------------------- email


def _gbp(value: float) -> str:
    return f"£{value:,.0f}"


def _link(deal: Deal) -> str:
    url = deal.booking_url
    if not url.startswith("https://"):
        if deal.return_date:
            url = _gf.build_google_flights_roundtrip_url(origin=deal.origin, destination=deal.destination,
                                                        outbound_date=deal.departure, return_date=deal.return_date,
                                                        travellers=deal.travellers or 1, cabin_class=CABIN)
        else:
            url = _gf.build_google_flights_url(origin=deal.origin, destination=deal.destination,
                                               date=deal.departure, travellers=1, cabin_class=CABIN)
    return url


def _duration(minutes: int) -> str:
    return f"{minutes // 60}h{minutes % 60:02d}"


def render_email(deals: Sequence[Deal], cfg: BusinessDealsConfig, now: datetime) -> tuple[str, str, str]:
    best = deals[0]
    best_n = int(getattr(best, "travellers", 1) or 1)
    best_pp = best.per_person_gbp if getattr(best, "per_person_gbp", None) is not None else best.total_gbp
    subject = (f"Business-class deal{'s' if len(deals) > 1 else ''}: {len(deals)} found, best "
               f"{best.origin} to {best.destination} {_gbp(best.total_gbp)}"
               + (f" for {best_n} ({_gbp(best_pp)} each)" if best_n > 1 else ""))
    esc = _html.escape
    rows, lines = [], []
    for d in deals:
        stops = "non-stop" if d.stops == 0 else f"{d.stops} stop{'s' if d.stops > 1 else ''}"
        cap = cfg.caps.get(d.region)
        travellers = int(getattr(d, "travellers", 1) or 1)
        per_person = d.per_person_gbp if getattr(d, "per_person_gbp", None) is not None else d.total_gbp
        # Caps and medians are per person (30 Oct 2026): a party total beside a per-person cap read as nonsense.
        cap_text = (f"{_gbp(per_person)} per person, under the {d.region.replace('_', ' ')} cap" if travellers > 1
                    else f"under the {d.region.replace('_', ' ')} cap")
        cap_text += (f" {_gbp(cap)}" + (" per person" if travellers > 1 else "")) if cap is not None else ""
        if d.trigger.startswith("median"):
            basis = f"{d.pct_below_median:.0f}% below median {_gbp(d.median_gbp)} (n={d.history_n})"
            if d.trigger == "median+cap":
                basis += f"; also {cap_text}"
        elif d.cold_start or d.median_gbp is None:
            basis = f"{cap_text}; not enough history yet for a median (n={d.history_n})"
        else:  # fired on the cap alone: the median is context, never presented as the reason
            basis = f"{cap_text}; route median {_gbp(d.median_gbp)} (n={d.history_n})"
        home = (f"{d.saving_vs_home_pct:.0f}% under the best home-airport total {_gbp(d.home_total_gbp)}"
                if d.home_total_gbp else ("no home-airport price to compare" if d.positioning_gbp else ""))
        parts = (f"fare {_gbp(d.fare_gbp)} + positioning {_gbp(d.positioning_gbp * travellers)}"
                 + (f" ({travellers} x {_gbp(d.positioning_gbp)})" if travellers > 1 else "")
                 if d.positioning_gbp else "fare only")
        link = _link(d)
        round_trip = bool(d.return_date)
        if round_trip:
            nights = (date.fromisoformat(d.return_date) - date.fromisoformat(d.departure)).days
            dep_fmt = date.fromisoformat(d.departure).strftime("%d %b")
            ret_fmt = date.fromisoformat(d.return_date).strftime("%d %b")
            departs_cell = f"{esc(dep_fmt)} - {esc(ret_fmt)}<br>({nights} nights)"
            total_phrase = f"{_gbp(d.total_gbp)} total for {d.travellers} travellers, return {dep_fmt} - {ret_fmt} ({nights} nights)"
            per_person_phrase = f"{_gbp(d.per_person_gbp)} per person"
            parts = parts + f"; {total_phrase} ({per_person_phrase})"
        else:
            departs_cell = f"{esc(d.departure)}<br>one way"
            total_phrase = f"{_gbp(d.total_gbp)}"
        rows.append(
            "<tr>"
            f"<td><b>{esc(d.origin_label)} to {esc(d.destination_label)}</b><br>{esc(d.origin)}-{esc(d.destination)}"
            f" &middot; {esc(d.region.replace('_', ' '))}</td>"
            f"<td>{departs_cell}</td>"
            f"<td><b>{_gbp(d.total_gbp)}</b><br><span style=\"color:#555\">{esc(parts)}</span></td>"
            f"<td>{esc(basis)}" + (f"<br><span style=\"color:#555\">{esc(home)}</span>" if home else "") + "</td>"
            f"<td>{esc(d.airline)}<br>{stops}, {_duration(d.duration_minutes)}</td>"
            f"<td>last seen {esc(d.last_seen)}<br><span style=\"color:#555\">first seen {esc(d.first_seen)}</span></td>"
            f"<td><a href=\"{esc(link, quote=True)}\">Search this fare</a></td></tr>")
        if round_trip:
            nights = (date.fromisoformat(d.return_date) - date.fromisoformat(d.departure)).days
            dep_fmt = date.fromisoformat(d.departure).strftime("%d %b")
            ret_fmt = date.fromisoformat(d.return_date).strftime("%d %b")
            lines.append(f"{d.origin}-{d.destination} {_gbp(d.total_gbp)} total for {d.travellers} travellers, "
                         f"return {dep_fmt} - {ret_fmt} ({nights} nights) ({_gbp(d.per_person_gbp)} per person); "
                         f"{parts}; {basis}; {home}; {d.airline}, {stops}, {_duration(d.duration_minutes)}; "
                         f"last seen {d.last_seen}; {link}")
        else:
            lines.append(f"{d.origin}-{d.destination} {d.departure} {_gbp(d.total_gbp)} ({parts}); {basis}; {home}; "
                         f"{d.airline}, {stops}, {_duration(d.duration_minutes)}; last seen {d.last_seen}; {link}")
    html = (
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>Business-class deals</title>"
        "<style>body{font-family:Arial,Helvetica,sans-serif;color:#222;background:#fff;font-size:14px;margin:16px}"
        "table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:6px 8px;vertical-align:top;"
        "text-align:left}th{background:#f1f3f5}a{color:#0b57d0}</style></head><body>"
        f"<h2>{esc(cfg.title)}</h2>"
        f"<p>{len(deals)} special fare{'s' if len(deals) > 1 else ''} found on {now.date().isoformat()}. "
        "Fares are the cheapest business-class result read on the Google Flights page, in GBP: a return is the "
        "whole party's fare for the dates shown, a one-way row is per person. A positioning origin's total includes "
        "getting every traveller there. Deals are judged per person. Prices change quickly: check the live page "
        "before relying on one.</p>"
        "<table><tr><th>Route</th><th>Departs</th><th>Total</th><th>Why it is a deal</th><th>Flight</th>"
        "<th>Seen</th><th>Link</th></tr>" + "".join(rows) + "</table></body></html>")
    text = "\n".join([f"{len(deals)} special business-class fare(s) on {now.date().isoformat()} "
                      "(GBP; returns are the party's total, deals judged per person):",
                      *lines])
    return subject, html, text


# --------------------------------------------------------------------------- fetching


def make_google_fetch(cfg: BusinessDealsConfig) -> Callable[[SearchSpec], FetchOutcome]:
    """Read a search through the package's existing Google Flights reader, at least ten seconds apart."""
    delay = max(10.0, float(os.environ.get("GOOGLE_FLIGHTS_DELAY_SECONDS", "12")))
    last = [0.0]

    def fetch(spec: SearchSpec) -> FetchOutcome:
        wait = delay * random.uniform(0.9, 1.25) - (time.monotonic() - last[0])
        if last[0] and wait > 0:
            time.sleep(wait)
        if spec.return_date:
            url = _gf.build_google_flights_roundtrip_url(origin=spec.origin, destination=spec.destination,
                                                        outbound_date=spec.date, return_date=spec.return_date,
                                                        travellers=cfg.travellers, cabin_class=CABIN)
        else:
            url = _gf.build_google_flights_url(origin=spec.origin, destination=spec.destination, date=spec.date,
                                               travellers=1, cabin_class=CABIN)
        page = _gf._fetch_page_html(url)
        last[0] = time.monotonic()
        if page is None:
            return FetchOutcome("failed")
        if _gf._is_waf_response(page):
            return FetchOutcome("wall")
        if spec.return_date:
            search = FlightSearch(
                key="business-deals", label="business deals", origins=(spec.origin,), destinations=(spec.destination,),
                dates=(spec.date,), travellers=cfg.travellers, cabin_class=CABIN, departure_window=("00:00", "23:59"),
                max_stops=cfg.max_stops, max_duration_minutes=1440, max_price_per_traveller_gbp=None)
        else:
            search = FlightSearch(
                key="business-deals", label="business deals", origins=(spec.origin,), destinations=(spec.destination,),
                dates=(spec.date,), travellers=1, cabin_class=CABIN, departure_window=("00:00", "23:59"),
                max_stops=cfg.max_stops, max_duration_minutes=1440, max_price_per_traveller_gbp=None)
        offers = _gf._parse_flight_cards(page, search=search, origin=spec.origin, destination=spec.destination,
                                         day=spec.date, booking_url=url)
        return FetchOutcome("ok", offers)

    return fetch


def offers_file_fetch(path: Path) -> Callable[[SearchSpec], FetchOutcome]:
    """Serve searches from a local JSON list of offers (a dry-run aid; no network)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))

    def fetch(spec: SearchSpec) -> FetchOutcome:
        return FetchOutcome("ok", [o for o in data if isinstance(o, dict) and o.get("origin") == spec.origin
                                   and o.get("destination") == spec.destination
                                   and str(o.get("departure", ""))[:10] == spec.date])

    return fetch


# --------------------------------------------------------------------------- the job


def alerts_path_for(history_path: Path) -> Path:
    return history_path.with_name(history_path.stem + "_alerts.jsonl")


def run_job(cfg: BusinessDealsConfig, *, history_path: Path, alerts_path: Optional[Path] = None,
            now: Optional[datetime] = None, fetch: Optional[Callable[[SearchSpec], FetchOutcome]] = None,
            send: Optional[Callable[..., None]] = None, dry_run: bool = False,
            print_details: bool = True) -> JobResult:
    now = now or datetime.now(timezone.utc)
    history_path = Path(history_path)
    alerts_path = Path(alerts_path) if alerts_path else alerts_path_for(history_path)
    fetch = fetch or make_google_fetch(cfg)
    result = JobResult()

    observations: list[dict] = []
    blocked_run = 0
    plan = plan_searches(cfg, now.date())
    for spec in plan:
        outcome = fetch(spec)
        result.searched += 1
        if outcome.status == "ok":
            blocked_run = 0
            result.ok += 1
            offers = list(outcome.offers)
            result.offers_seen += len(offers)
            observation, rejected = cheapest_observation(offers, spec, cfg, now)
            result.rejected += rejected
            if observation:
                observations.append(observation)
            continue
        blocked_run += 1
        if outcome.status == "wall":
            result.walled += 1
        else:
            result.failed += 1
        if blocked_run >= cfg.stop_after_blocked:
            result.stopped_early = True  # walls are recorded and left alone, never pushed through
            break

    history = read_jsonl(history_path)
    alerts = read_jsonl(alerts_path)
    result.deals = find_deals(observations, history, alerts, cfg, now)
    if not dry_run:
        result.history_rows_added = append_observations(history_path, observations, history)

    if result.deals:
        subject, html, text = render_email(result.deals, cfg, now)
        if dry_run and not print_details:
            # A public Actions log must not carry the owner's routes, dates or fares (they come from a secret).
            print(f"DRY RUN: would mail {len(result.deals)} deal(s); routes, dates and fares are withheld from this "
                  "public log because the config is a private secret (run the dry run locally to see them)")
        elif dry_run:
            print(f"DRY RUN: would mail: {subject}\n{text}\n{html}")
        else:
            try:
                (send or _default_send)(subject, html, text=text)
            except Exception as exc:  # the alert is not recorded, so tomorrow's run tries again
                logger.error("business-deals mail failed: %s", type(exc).__name__)
            else:
                result.mailed = True
                _append_jsonl(alerts_path, [{"key": d.key, "total_gbp": d.total_gbp,
                                              "per_person_gbp": d.per_person_gbp,
                                              "alerted_at": now.isoformat(timespec="seconds")} for d in result.deals])

    result.log_line = (
        f"business-deals {now.date().isoformat()}: searched {result.searched} of {len(_grid(cfg))} "
        f"(ok {result.ok}, walled {result.walled}, failed {result.failed}"
        f"{', stopped early' if result.stopped_early else ''}), offers {result.offers_seen}, "
        f"rejected {result.rejected}, history +{result.history_rows_added}, deals {len(result.deals)}, "
        f"mail {'sent' if result.mailed else 'not sent'}{' (dry run)' if dry_run else ''}, "
        f"full cycle {cycle_days(cfg)}d")
    print(result.log_line)
    return result


def _default_send(subject: str, html: str, *, text: str = "") -> None:
    from .mailer import send_html  # imported late: only a real send needs SMTP settings

    send_html(subject, html, text=text)


def main(arguments: Sequence[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="business-deals")
    parser.add_argument("--config", default="", help="config file (default: BUSINESS_DEALS_CONFIG_JSON, else the example)")
    parser.add_argument("--history", default="", help="history JSONL (default: BUSINESS_DEALS_HISTORY or data/)")
    parser.add_argument("--offers", default="", help="serve fares from this JSON file instead of the network")
    parser.add_argument("--dry-run", action="store_true", help="print the would-be e-mail; send and write nothing")
    args = parser.parse_args(list(arguments))

    secret = ""
    if args.config:
        source = Path(args.config).read_text(encoding="utf-8")
    else:
        secret = os.environ.get("BUSINESS_DEALS_CONFIG_JSON") or ""
        source = secret or Path("examples/business_deals_config.json").read_text(encoding="utf-8")
    cfg = load_config(source)
    history = Path(args.history or os.environ.get("BUSINESS_DEALS_HISTORY") or HISTORY_DEFAULT_PATH)
    fetch = offers_file_fetch(Path(args.offers)) if args.offers else None
    # In Actions any non-example config is private (the secret, or a file written from it); the log is public.
    public_log = os.environ.get("GITHUB_ACTIONS") == "true" and bool(secret or args.config)
    result = run_job(cfg, history_path=history, fetch=fetch, dry_run=args.dry_run, print_details=not public_log)
    return 2 if result.deals and not result.mailed and not args.dry_run else 0
