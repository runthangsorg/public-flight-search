"""Live verification boundary for the public engine.

Architecture rule (see travel-deal-engine skill + AUTOMATION_OWNERSHIP):
public GHA runners must stay fast, free and secret-free. Deep stealth
package verification — Camoufox anti-detect browser, FlareSolverr
Cloudflare bypass, human-like cursor cadence — runs in the PRIVATE
`flightdealsearch` engine on local laptop / misc VM compute, never on
public GitHub-hosted runners.

This module is the honest seam between the two:

- On public GHA: `try_live_flight_offers()` performs a BOUNDED Google
  Flights HTTP fetch (no browser, no Cloudflare bypass, 12-search cap,
  60 s budget). When it succeeds, holiday deals are labelled
  `verified-exact-date`; when it fails or is disabled, deals stay
  `market-supported` benchmarks and the report says so.
- Full Camoufox/FlareSolverr package checkout verification is NOT
  attempted here. Use `/home/kc/flightdealsearch` (`holiday_live_verify.py`,
  `patchright_verify.py`, `flare_solverr_client.py`,
  `anti_detect_browser.py`) on local/VM compute for that.

No function here ever invents a price. Empty evidence suppresses the
deal rather than hallucinating one.
"""

from __future__ import annotations

import asyncio
import os
from typing import Mapping


def _live_enabled() -> bool:
    return os.getenv("HOLIDAY_LIVE_FLIGHTS", "").lower() in {"1", "true", "yes"}


def try_live_flight_offers(config, *, max_searches: int = 12) -> Mapping[str, float]:
    """Return {airport: live 5-pax return GBP} or {} when unavailable.

    Bounded for GHA: caps searches, enforces a short deadline, swallows all
    errors. Callers must treat {} as "stay on benchmarks", never as zero.
    """
    if not _live_enabled():
        return {}
    try:
        from .config import FlightSearch
        from .google_flights import search_google_flights
    except Exception:
        return {}

    origins = tuple(config.origins[:2])
    # Representative pair only — full-matrix live pricing is the private
    # engine's job (Camoufox/FlareSolverr on local/VM).
    try:
        pairs = sorted(
            (o, r) for o in config.outbound_dates for r in config.return_dates
            if r > o
        )
    except Exception:
        return {}
    if not pairs:
        return {}
    outbound, returning = pairs[len(pairs) // 2]

    searches: list[FlightSearch] = []
    for dest in config.destinations:
        airports = getattr(dest, "airports", ())
        if not airports:
            continue
        searches.append(
            FlightSearch(
                key=f"holiday_{dest.key}",
                label=getattr(dest, "label", dest.key),
                origins=origins,
                destinations=tuple(a.upper() for a in airports[:1]),
                dates=(outbound,),
                travellers=config.travellers,
                cabin_class="ECONOMY",
                departure_window=config.departure_window,
                max_stops=1,
                max_duration_minutes=720,
                max_price_per_traveller_gbp=None,
            )
        )
    searches = searches[: max(1, min(max_searches, 12))]
    if not searches:
        return {}

    prev_max = os.getenv("GOOGLE_FLIGHTS_MAX_SEARCHES")
    prev_timeout = os.getenv("GOOGLE_FLIGHTS_TOTAL_TIMEOUT_SECONDS")
    prev_delay = os.getenv("GOOGLE_FLIGHTS_DELAY_SECONDS")
    os.environ["GOOGLE_FLIGHTS_MAX_SEARCHES"] = str(len(searches))
    os.environ["GOOGLE_FLIGHTS_TOTAL_TIMEOUT_SECONDS"] = "60"
    os.environ["GOOGLE_FLIGHTS_DELAY_SECONDS"] = "2"
    try:
        grouped = asyncio.run(search_google_flights(tuple(searches)))
    except Exception:
        return {}
    finally:
        if prev_max is None:
            os.environ.pop("GOOGLE_FLIGHTS_MAX_SEARCHES", None)
        else:
            os.environ["GOOGLE_FLIGHTS_MAX_SEARCHES"] = prev_max
        if prev_timeout is None:
            os.environ.pop("GOOGLE_FLIGHTS_TOTAL_TIMEOUT_SECONDS", None)
        else:
            os.environ["GOOGLE_FLIGHTS_TOTAL_TIMEOUT_SECONDS"] = prev_timeout
        if prev_delay is None:
            os.environ.pop("GOOGLE_FLIGHTS_DELAY_SECONDS", None)
        else:
            os.environ["GOOGLE_FLIGHTS_DELAY_SECONDS"] = prev_delay

    offers: dict[str, float] = {}
    for search in searches:
        dest_airport = search.destinations[0] if search.destinations else ""
        best = None
        for offer in grouped.get(search.key, ()):
            # One-way observed fare × travellers ≈ return estimate × 2 legs.
            # Conservative: one-way observed × 2 × travellers, capped sanely.
            try:
                one_way_pp = (
                    offer.price_per_traveller
                    if offer.price_per_traveller
                    else offer.price
                )
                estimate = round(float(one_way_pp) * config.travellers * 2, 2)
            except (TypeError, ValueError):
                continue
            if 100 <= estimate <= 15000 and (best is None or estimate < best):
                best = estimate
        if best is not None and dest_airport:
            offers[dest_airport] = best
    return offers
