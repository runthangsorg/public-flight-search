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
from .engine import FlightOffer



def build_google_flights_url(
    *, origins: tuple[str, ...], destinations: tuple[str, ...], date: str,
    travellers: int, cabin_class: str,
) -> str:
    cabin = "business" if cabin_class == "BUSINESS" else "economy"
    query = (
        f"one way flights from {' or '.join(origins)} to "
        f"{' or '.join(destinations)} on {date} {travellers} adults {cabin} cabin"
    )
    return "https://www.google.com/travel/flights?q=" + quote(query, safe="") + "&curr=GBP&hl=en-GB"


async def search_google_flights(searches: Iterable[FlightSearch]) -> dict[str, tuple[FlightOffer, ...]]:
    """Search all configured date buckets using direct HTTP fetch.

    Google Flights serves different content to headless browsers (Explore page
    instead of search results). We fetch the page HTML directly via HTTP and
    parse the server-rendered flight data from the response.
    """
    import urllib.request
    import urllib.error

    specs = [(search, day) for search in searches for day in search.dates]
    maximum = int(os.getenv("GOOGLE_FLIGHTS_MAX_SEARCHES", "20"))
    specs = specs[: max(1, min(maximum, 40))]
    deadline = time.monotonic() + int(os.getenv("GOOGLE_FLIGHTS_TOTAL_TIMEOUT_SECONDS", "900"))
    grouped: dict[str, list[FlightOffer]] = {item.key: [] for item in searches}

    _dbg(f"Starting {len(specs)} searches (HTTP mode), deadline in {deadline - time.monotonic():.0f}s")

    for idx, (search, day) in enumerate(specs):
        if time.monotonic() >= deadline:
            _dbg(f"Deadline reached at search {idx}")
            break
        url = build_google_flights_url(
            origins=search.origins, destinations=search.destinations,
            date=day, travellers=search.travellers,
            cabin_class=search.cabin_class,
        )
        _dbg(f"Search {idx+1}/{len(specs)}: {search.key} {day} -> {url[:80]}...")

        html = _fetch_page_html(url)
        if html is None:
            _dbg(f"Failed to fetch page for {search.key} {day}")
            continue

        if any(signal in html.lower() for signal in [
            "unusual traffic", "not a robot", "automated queries",
            "rate limit exceeded", "access to this page has been denied",
        ]):
            _dbg(f"WAF detected on {search.key} {day}")
            continue

        dump_dir = os.getenv("SCREENSHOTS_DIR", "/tmp/flight-verify")
        try:
            os.makedirs(dump_dir, exist_ok=True)
            with open(os.path.join(dump_dir, f"html_{search.key}_{day}.txt"), "w") as f:
                f.write(html[:50000])
            _dbg(f"Saved HTML ({len(html)} bytes) for {search.key} {day}")
        except Exception:
            pass

        offers = _parse_flight_cards(html, search=search, day=day, booking_url=url)
        grouped[search.key].extend(offers)
        _dbg(f"Parsed {len(offers)} offers for {search.key} {day}")

    return {
        key: tuple(sorted(values, key=lambda item: (item.price, item.duration_minutes))[:10])
        for key, values in grouped.items()
    }


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


def _parse_flight_cards(html: str, *, search: FlightSearch, day: str, booking_url: str) -> list[FlightOffer]:
    """Parse flight cards from Google Flights HTML response."""
    offers = []

    price_pattern = re.compile(r'£(\d{1,5}(?:,\d{3})*)')
    time_pattern = re.compile(r'(\d{1,2}:\d{2}\s*[AP]M)', re.I)
    duration_pattern = re.compile(r'(\d+)\s*hr\s*(\d+)?\s*min', re.I)
    stops_pattern = re.compile(r'(Nonstop|(\d+)\s*stops?)', re.I)
    airline_pattern = re.compile(
        r'(Aegean|Aer Lingus|Air Arabia|Air France|British Airways|easyJet|'
        r'EgyptAir|Emirates|Etihad|Finnair|Gulf Air|Iberia|KLM|Lufthansa|'
        r'Oman Air|Pegasus|Qatar Airways|Royal Jordanian|Ryanair|Saudia|'
        r'Swiss|Turkish Airlines|Wizz Air)',
        re.I,
    )

    chunks = re.split(r'(?=£\d)', html)
    for chunk in chunks:
        price_match = price_pattern.search(chunk)
        if not price_match:
            continue
        price = float(price_match.group(1).replace(",", ""))
        if not 20 <= price <= 100_000:
            continue

        times = time_pattern.findall(chunk)
        duration_match = duration_pattern.search(chunk)
        stops_match = stops_pattern.search(chunk)
        airline_match = airline_pattern.search(chunk)

        if not duration_match:
            continue

        duration = int(duration_match.group(1)) * 60 + int(duration_match.group(2) or 0)
        if duration <= 0:
            continue

        stops = 0
        if stops_match:
            if stops_match.group(1).lower() == "nonstop":
                stops = 0
            else:
                stops = int(stops_match.group(2) or 0)

        airline = airline_match.group(1) if airline_match else "Unknown airline"

        origin = next((code for code in search.origins if code in chunk), "")
        destination = next((code for code in search.destinations if code in chunk), "")
        if not origin or not destination:
            continue

        departure = f"{day}T{times[0].replace(' ', '').upper()}" if times else f"{day}T00:00:00"
        arrival = ""
        if len(times) > 1:
            arrival = f"{day}T{times[1].replace(' ', '').upper()}"

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
