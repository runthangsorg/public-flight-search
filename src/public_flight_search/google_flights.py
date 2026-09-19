"""Google Flights results-page adapter using direct HTTP fetch.

Google Flights serves different content to headless browsers (Explore page
instead of search results). We fetch the HTML directly and parse the
server-rendered flight cards.
"""

from __future__ import annotations

from base64 import b64encode
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import json
import os
import re
import time
import urllib.request
from typing import Any, Iterable
from urllib.parse import urlencode

from .config import FlightSearch
from .engine import FlightOffer

def _dbg(msg: str) -> None:
    if os.getenv("FLIGHT_DEBUG", "").lower() not in {"1", "true", "yes"}:
        return
    line = f"[DEBUG {time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    path = os.getenv("DEBUG_LOG_PATH", "")
    if path:
        try:
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        except OSError:
            return


def _is_waf_response(html: str) -> bool:
    """Recognise explicit challenge pages without matching dormant CAPTCHA JS."""
    lowered = html.lower()
    return any(
        signal in lowered
        for signal in (
            "unusual traffic",
            "our systems have detected",
            "automated queries",
            "rate limit exceeded",
            "access to this page has been denied",
        )
    )


def _capture_html_if_enabled(
    html: str, *, search_key: str, origin: str, destination: str, day: str
) -> None:
    """Capture bounded diagnostics only after an explicit local opt-in."""
    if os.getenv("FLIGHT_CAPTURE_HTML", "").lower() not in {"1", "true", "yes"}:
        return
    directory = os.getenv("SCREENSHOTS_DIR", "/tmp/flight-verify")
    safe_key = re.sub(r"[^A-Za-z0-9_.-]", "_", search_key)[:48]
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"html_{safe_key}_{origin}_{destination}_{day}.txt")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(html[:80_000])


def _varint(value: int) -> bytes:
    out = bytearray()
    while value > 0x7F:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def _field(number: int, value: str | bytes) -> bytes:
    raw = value.encode() if isinstance(value, str) else value
    return _varint((number << 3) | 2) + _varint(len(raw)) + raw


def _leg(origin: str, destination: str, date: str) -> bytes:
    return (
        _field(2, date)
        + _field(13, _field(2, origin.upper()))
        + _field(14, _field(2, destination.upper()))
    )


#: ``tfs`` field 19 is the trip type. It is not cosmetic: with the
#: one-way value (2) the provider prices ONLY the first leg even when a
#: second leg is present, and renders a form with an empty return field.
#: Verified live 2026-09-18. Emitting two legs without the matching trip
#: type is what previously labelled one-way fares as return totals.
_TRIP_TYPE_FIELD = 19
TRIP_ROUND_TRIP = 1
TRIP_ONE_WAY = 2
TRIP_MULTI_CITY = 3


def _seat_field(travellers: int, cabin_class: str) -> bytes:
    """Encode the cabin selector. Trip type is a separate field."""
    seats = {"ECONOMY": 1, "PREMIUM_ECONOMY": 2, "BUSINESS": 3, "FIRST": 4}
    seat = seats.get(cabin_class.upper())
    if seat is None or not 1 <= travellers <= 9:
        raise ValueError("unsupported travellers or cabin class")
    return _varint((9 << 3) | 0) + _varint(seat)


def _trip_type_field(trip_type: int) -> bytes:
    return _varint((_TRIP_TYPE_FIELD << 3) | 0) + _varint(trip_type)


def build_google_flights_url(
    *, origin: str, destination: str, date: str,
    travellers: int, cabin_class: str,
) -> str:
    """Build Google's current structured one-way search URL."""
    info = (
        _field(3, _leg(origin, destination, date))
        + _field(8, bytes([1]) * travellers)
        + _seat_field(travellers, cabin_class)
        + _trip_type_field(TRIP_ONE_WAY)
    )
    return "https://www.google.com/travel/flights/search?" + urlencode({"tfs": b64encode(info).decode(), "curr": "GBP", "hl": "en-GB"})


def build_google_flights_roundtrip_url(
    *, origin: str, destination: str,
    outbound_date: str, return_date: str,
    travellers: int, cabin_class: str = "ECONOMY",
) -> str:
    """Build Google's current structured RETURN search URL.

    Two legs ride as repeated field-3 segments. Verified live 2026-09-07:
    resolves to a dated results page (the legacy `#flt=` hash format lands
    on the generic homepage and must never be emitted again).
    """
    if return_date <= outbound_date:
        raise ValueError("return_date must be after outbound_date")
    return build_google_flights_multicity_url(
        out_orig=origin, out_dest=destination, out_date=outbound_date,
        ret_orig=destination, ret_dest=origin, ret_date=return_date,
        travellers=travellers, cabin_class=cabin_class,
    )


def build_google_flights_multicity_url(
    *, out_orig: str, out_dest: str, out_date: str,
    ret_orig: str, ret_dest: str, ret_date: str,
    travellers: int, cabin_class: str = "ECONOMY",
) -> str:
    """Build Google's current structured multi-city/open-jaw search URL.

    Both legs ride as repeated field-3 segments, so round-trips
    (LHR-AYT + AYT-LHR) and open-jaws (LHR-MCT + AUH-LHR) share one
    code path. The legacy `?q=Flights+from...` natural-language format
    and the `#flt=` hash format both land on the generic homepage and
    must never be emitted.
    """
    if ret_date <= out_date:
        raise ValueError("ret_date must be after out_date")
    # A true round trip returns to where it started; anything else (an
    # open-jaw, for instance) is a multi-city itinerary to the provider.
    # Both need their own trip type: sending the round-trip value for an
    # open-jaw, or the one-way value for either, silently changes which
    # itinerary the displayed price belongs to.
    plain_round_trip = ret_orig == out_dest and ret_dest == out_orig
    trip_type = TRIP_ROUND_TRIP if plain_round_trip else TRIP_MULTI_CITY
    info = (
        _field(3, _leg(out_orig, out_dest, out_date))
        + _field(3, _leg(ret_orig, ret_dest, ret_date))
        + _field(8, bytes([1]) * travellers)
        + _seat_field(travellers, cabin_class)
        + _trip_type_field(trip_type)
    )
    return "https://www.google.com/travel/flights/search?" + urlencode({"tfs": b64encode(info).decode(), "curr": "GBP", "hl": "en-GB"})


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
    searches = tuple(searches)
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

        if _is_waf_response(html):
            _dbg(f"WAF detected on {origin}→{dest} {day}")
            continue

        try:
            _capture_html_if_enabled(
                html,
                search_key=search.key,
                origin=origin,
                destination=dest,
                day=day,
            )
        except OSError as exc:
            _dbg(f"Local HTML capture failed: {exc}")

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
                offer.departure, offer.airline,
                offer.stops, offer.duration_minutes,
            )
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            unique.append(offer)
        unique.sort(
            key=lambda item: (
                item.departure[:10], item.price, item.duration_minutes
            )
        )
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
        "Cookie": "SOCS=CAISHAgBEhJnd3NfMjAyNDA1MDgtMF9SQzIaAmVuIAEaBgiA_LyuBg; CONSENT=PENDING+999",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        _dbg(f"HTTP fetch error: {type(e).__name__}")
        return None


class _StructuredScriptParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.capture = False
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.casefold() == "script":
            self.capture = "ds:1" in (dict(attrs).get("class") or "").split()

    def handle_endtag(self, tag):
        if tag.casefold() == "script":
            self.capture = False

    def handle_data(self, data):
        if self.capture:
            self.parts.append(data)


def _parse_structured_results(html: str, *, search: FlightSearch, booking_url: str) -> list[FlightOffer]:
    parser = _StructuredScriptParser()
    parser.feed(html[:8_000_000])
    script = "".join(parser.parts)
    if "data:" not in script or "errorHasStatus: true" in script:
        return []
    try:
        payload, _ = json.JSONDecoder().raw_decode(script.split("data:", 1)[1].lstrip())
        rows = payload[3][0]
    except (json.JSONDecodeError, IndexError, TypeError):
        return []
    offers = []
    for row in rows[:50] if isinstance(rows, list) else []:
        try:
            flight = row[0]
            price = float(row[1][0][1])
            segments = flight[2]
            departure = datetime(int(flight[4][0]), int(flight[4][1]), int(flight[4][2]), int(flight[5][0]), int(flight[5][1])).isoformat()
            arrival = datetime(int(flight[7][0]), int(flight[7][1]), int(flight[7][2]), int(flight[8][0]), int(flight[8][1])).isoformat()
            duration = int(flight[9])
            if not 20 <= price <= 1_000_000 or duration <= 0 or not segments:
                continue
            airline = ", ".join(str(value) for value in (flight[1] if isinstance(flight[1], list) else []) if value)[:80] or "Unknown airline"
            offer = FlightOffer(
                origin=str(flight[3]).upper(), destination=str(flight[6]).upper(),
                departure=departure, arrival=arrival, price=round(price, 2),
                price_per_traveller=round(price / search.travellers, 2), currency="GBP",
                stops=len(segments) - 1, duration_minutes=duration,
                provider="Google Flights", booking_url=booking_url, airline=airline,
                observed_at=datetime.now(timezone.utc).isoformat(), review_status="results_page_structured",
            )
            clock = offer.departure[11:16]
            if not search.departure_window[0] <= clock <= search.departure_window[1]:
                continue
            if offer.stops > search.max_stops or offer.duration_minutes > search.max_duration_minutes:
                continue
            if search.max_price_per_traveller_gbp is not None and offer.price_per_traveller > search.max_price_per_traveller_gbp:
                continue
            offers.append(offer)
        except (IndexError, TypeError, ValueError, ZeroDivisionError):
            continue
    return offers


def _parse_flight_cards(
    html: str, *, search: FlightSearch, origin: str, destination: str,
    day: str, booking_url: str,
) -> list[FlightOffer]:
    """Parse current structured data, retaining aria-label compatibility."""
    structured = _parse_structured_results(html, search=search, booking_url=booking_url)
    if structured:
        return structured
    offers = []

    aria_pattern = re.compile(
        r'aria-label="From ([\d,]+) British pounds\.\s*'
        r'(Non-stop|(\d+) stops?) flight with ([^."]+)\.\s*'
        r'Leaves [^"]+?at (\d{1,2}:\d{2})[^"]+?'
        r'arrives at [^"]+?at (\d{1,2}:\d{2})[^"]+?'
        r'Total duration (\d+) hrs?(?:\s+(\d+) mins?)?',
        re.I,
    )

    for m in aria_pattern.finditer(html):
        price = float(m.group(1).replace(",", ""))
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

        departure_dt = datetime.fromisoformat(f"{day}T{dep_time}:00")
        arrival_dt = datetime.fromisoformat(f"{day}T{arr_time}:00")
        if arrival_dt <= departure_dt:
            arrival_dt += timedelta(days=1)
        departure = departure_dt.isoformat()
        arrival = arrival_dt.isoformat()

        offer = FlightOffer(
            origin=origin,
            destination=destination,
            departure=departure,
            arrival=arrival,
            # Google can vary the displayed-fare basis. Preserve the observed
            # amount instead of inventing a multiplied whole-party total.
            price=price,
            price_per_traveller=price if search.travellers == 1 else None,
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
        if (
            search.travellers == 1
            and search.max_price_per_traveller_gbp is not None
            and price > search.max_price_per_traveller_gbp
        ):
            continue

        offers.append(offer)

    return offers
