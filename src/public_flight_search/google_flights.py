"""Google Flights results-page adapter using direct HTTP fetch.

Google Flights serves different content to headless browsers (Explore page
instead of search results). We fetch the HTML directly and parse the
server-rendered flight cards.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
import re
import time
import urllib.request
import urllib.error
from typing import Iterable
from urllib.parse import quote

from .config import FlightSearch
from .engine import FlightOffer

_DBG_FILE = os.getenv("DEBUG_LOG_PATH", "/tmp/flight-debug.log")
def _dbg(msg: str) -> None:
    line = f"[DEBUG {time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open(_DBG_FILE, "a") as _f:
            _f.write(line + "\n")
    except Exception:
        pass


def build_google_flights_url(
    *, origin: str, destination: str, date: str,
    travellers: int, cabin_class: str,
) -> str:
    """Build a Google Flights URL for a single origin-destination pair."""
    query = f"flights from {origin} to {destination} on {date} one way"
    return "https://www.google.com/travel/flights?q=" + quote(query, safe="") + "&curr=GBP&hl=en-GB"


def _build_search_pairs(search: FlightSearch) -> list[tuple[str, str, str]]:
    """Build all (origin, destination, date) triples for a search."""
    pairs = []
    for day in search.dates:
        for origin in search.origins:
            for dest in search.destinations:
                pairs.append((origin, dest, day))
    return pairs


async def search_google_flights(searches: Iterable[FlightSearch]) -> dict[str, tuple[FlightOffer, ...]]:
    """Search all configured airport pairs using direct HTTP fetch.

    Iterates through all origin×destination×date combinations with delays
    to avoid rate limiting. Parses server-rendered aria-label flight cards.
    """
    import urllib.request
    import urllib.error

    specs = []
    for search in searches:
        for origin in search.origins:
            for dest in search.destinations:
                for day in search.dates:
                    specs.append((search, origin, dest, day))

    maximum = int(os.getenv("GOOGLE_FLIGHTS_MAX_SEARCHES", "50"))
    specs = specs[: max(1, min(maximum, 60))]
    deadline = time.monotonic() + int(os.getenv("GOOGLE_FLIGHTS_TOTAL_TIMEOUT_SECONDS", "900"))
    grouped: dict[str, list[FlightOffer]] = {item.key: [] for item in searches}

    _dbg(f"Starting {len(specs)} searches (HTTP mode), deadline in {deadline - time.monotonic():.0f}s")

    for idx, (search, origin, dest, day) in enumerate(specs):
        if time.monotonic() >= deadline:
            _dbg(f"Deadline reached at search {idx}")
            break

        url = build_google_flights_url(
            origin=origin, destination=dest,
            date=day, travellers=search.travellers,
            cabin_class=search.cabin_class,
        )
        _dbg(f"Search {idx+1}/{len(specs)}: {origin}→{dest} {day} -> {url[:80]}...")

        html = _fetch_page_html(url)
        if html is None:
            _dbg(f"Failed to fetch page for {origin}→{dest} {day}")
            continue

        if any(signal in html.lower() for signal in [
            "unusual traffic", "not a robot", "automated queries",
            "rate limit exceeded", "access to this page has been denied",
        ]):
            _dbg(f"WAF detected on {origin}→{dest} {day}")
            continue

        dump_dir = os.getenv("SCREENSHOTS_DIR", "/tmp/flight-verify")
        try:
            os.makedirs(dump_dir, exist_ok=True)
            with open(os.path.join(dump_dir, f"html_{search.key}_{origin}_{dest}_{day}.txt"), "w") as f:
                f.write(html[:80000])
            _dbg(f"Saved HTML ({len(html)} bytes) for {origin}→{dest} {day}")
        except Exception:
            pass

        offers = _parse_flight_cards(
            html, search=search, origin=origin, destination=dest,
            day=day, booking_url=url,
        )
        grouped[search.key].extend(offers)
        _dbg(f"Parsed {len(offers)} offers for {origin}→{dest} {day}")

        if idx < len(specs) - 1:
            delay = float(os.getenv("GOOGLE_FLIGHTS_DELAY_SECONDS", "12"))
            _dbg(f"Waiting {delay}s before next request...")
            time.sleep(delay)

    deduped: dict[str, list[FlightOffer]] = {}
    for key, values in grouped.items():
        seen: set[tuple] = set()
        unique: list[FlightOffer] = []
        for offer in values:
            fingerprint = (
                offer.origin, offer.destination,
                offer.departure[11:16], offer.airline,
                offer.stops, offer.duration_minutes,
            )
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            unique.append(offer)
        unique.sort(key=lambda item: (item.price, item.duration_minutes))
        deduped[key] = unique[:10]

    return {key: tuple(vals) for key, vals in deduped.items()}


def _fetch_page_html(url: str) -> str | None:
    """Fetch Google Flights page HTML via urllib with realistic headers."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
        "Accept-Encoding": "identity",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "DNT": "1",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        _dbg(f"HTTP fetch error: {e}")
        return None


def _parse_flight_cards(
    html: str, *, search: FlightSearch, origin: str, destination: str,
    day: str, booking_url: str,
) -> list[FlightOffer]:
    """Parse flight cards from Google Flights HTML via aria-label attributes."""
    offers = []

    aria_pattern = re.compile(
        r'aria-label="From (\d+) British pounds\.\s*'
        r'(Non-stop|(\d+) stop) flight with ([^."]+)\.\s*'
        r'Leaves [^"]+?at (\d{1,2}:\d{2})[^"]+?'
        r'arrives at [^"]+?at (\d{1,2}:\d{2})[^"]+?'
        r'Total duration (\d+) hrs? (\d+)? mins?',
        re.I,
    )

    for m in aria_pattern.finditer(html):
        price = float(m.group(1))
        stops_str = m.group(2)
        stops = 0 if "Non-stop" in stops_str else int(m.group(3) or 0)
        airline = m.group(4).strip()
        dep_time = m.group(5)
        arr_time = m.group(6)
        dur_hrs = int(m.group(7))
        dur_mins = int(m.group(8) or 0)
        duration = dur_hrs * 60 + dur_mins

        if not 20 <= price <= 100_000:
            continue

        departure = f"{day}T{dep_time}:00"
        arrival = f"{day}T{arr_time}:00"

        offer = FlightOffer(
            origin=origin,
            destination=destination,
            departure=departure,
            arrival=arrival,
            price=price * search.travellers,
            price_per_traveller=price,
            currency="GBP",
            stops=stops,
            duration_minutes=duration,
            provider="Google Flights",
            booking_url=booking_url,
            airline=airline,
            observed_at=datetime.now(timezone.utc).isoformat(),
            review_status="results_page_only",
        )

        clock = departure[11:16]
        if not search.departure_window[0] <= clock <= search.departure_window[1]:
            continue
        if offer.stops > search.max_stops or offer.duration_minutes > search.max_duration_minutes:
            continue
        if search.max_price_per_traveller_gbp is not None and price > search.max_price_per_traveller_gbp:
            continue

        offers.append(offer)

    return offers
