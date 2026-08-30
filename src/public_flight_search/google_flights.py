"""Bounded Google Flights results-page adapter using the public web UI."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import re
import time
from typing import Any, Iterable
from urllib.parse import quote

from .config import FlightSearch

_anti_bot_dir = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
if _anti_bot_dir not in sys.path:
    sys.path.insert(0, _anti_bot_dir)
from shared.anti_bot import (
    random_user_agent, random_viewport, human_delay,
    inject_canvas_noise, warm_up_session, stealth_browser_args,
    dismiss_cookies, check_waf, random_headers,
)
from .engine import FlightOffer


CARD_SELECTORS = (
    '[role="main"] li[role="listitem"]',
    '[role="main"] [role="listitem"]',
    "ul.RKOxfe li",
    "li.pIav2d",
    "div.pIav2d",
    "div.yR1fYc",
    "div.mz0pAd",
    "div.Og10v",
)

KNOWN_AIRLINES = (
    "Aegean Airlines", "Aer Lingus", "Air Arabia", "Air France", "British Airways",
    "easyJet", "EgyptAir", "Emirates", "Etihad Airways", "Finnair", "Gulf Air",
    "Iberia", "KLM", "Lufthansa", "Oman Air", "Pegasus Airlines", "Qatar Airways",
    "Royal Jordanian", "Ryanair", "Saudia", "Swiss", "Turkish Airlines", "Wizz Air",
)


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


def _clock_times(text: str, day: str) -> tuple[str, str]:
    matches = re.findall(r"(?<!\d)(\d{1,2}:\d{2})(?:\s*([AP]M))?(?!\d)", text, re.I)
    if not matches:
        return f"{day}T00:00:00", ""
    def parse(value: tuple[str, str]) -> datetime:
        clock, suffix = value
        fmt = "%Y-%m-%d %I:%M %p" if suffix else "%Y-%m-%d %H:%M"
        rendered = f"{day} {clock} {suffix.upper()}" if suffix else f"{day} {clock}"
        return datetime.strptime(rendered, fmt)
    departure = parse(matches[0])
    if len(matches) == 1:
        return departure.isoformat(), ""
    arrival = parse(matches[1])
    if "+1" in text or arrival <= departure:
        arrival += timedelta(days=1)
    return departure.isoformat(), arrival.isoformat()


def parse_google_flight_text(
    text: str, *, origins: tuple[str, ...], destinations: tuple[str, ...],
    date: str, travellers: int, booking_url: str,
) -> FlightOffer | None:
    normalized = " ".join(text.split())
    origin = next((code for code in origins if re.search(rf"\b{code}\b", normalized, re.I)), "")
    destination = next((code for code in destinations if re.search(rf"\b{code}\b", normalized, re.I)), "")
    price_match = re.search(r"(?:£|GBP\s*)([0-9]{1,5}(?:,[0-9]{3})*)", normalized, re.I)
    if not origin or not destination or not price_match:
        return None
    per_person = float(price_match.group(1).replace(",", ""))
    if not 20 <= per_person <= 100_000:
        return None
    if re.search(r"\bnon[ -]?stop\b", normalized, re.I):
        stops = 0
    else:
        stop_match = re.search(r"\b(\d+)\s+stops?\b", normalized, re.I)
        if not stop_match:
            return None
        stops = int(stop_match.group(1))
    duration_match = re.search(r"(\d{1,2})\s*(?:hr|hour)s?(?:\s*(\d{1,2})\s*(?:min|minute)s?)?", normalized, re.I)
    duration = 0 if not duration_match else int(duration_match.group(1)) * 60 + int(duration_match.group(2) or 0)
    if duration <= 0:
        return None
    departure, arrival = _clock_times(normalized, date)
    airline = next(
        (name for name in KNOWN_AIRLINES if re.search(rf"\b{re.escape(name)}\b", normalized, re.I)),
        "Unknown airline",
    )
    return FlightOffer(
        origin=origin,
        destination=destination,
        departure=departure,
        arrival=arrival,
        price=round(per_person * travellers, 2),
        price_per_traveller=per_person,
        currency="GBP",
        stops=stops,
        duration_minutes=duration,
        provider="Google Flights",
        booking_url=booking_url,
        airline=airline,
        observed_at=datetime.now(timezone.utc).isoformat(),
        review_status="results_page_only",
    )


async def search_google_flights(searches: Iterable[FlightSearch]) -> dict[str, tuple[FlightOffer, ...]]:
    """Search all configured date buckets in one bounded browser session."""
    from playwright.async_api import async_playwright

    specs = [(search, day) for search in searches for day in search.dates]
    maximum = int(os.getenv("GOOGLE_FLIGHTS_MAX_SEARCHES", "20"))
    specs = specs[: max(1, min(maximum, 40))]
    timeout_ms = int(os.getenv("GOOGLE_FLIGHTS_RESULT_TIMEOUT_MS", "10000"))
    deadline = time.monotonic() + int(os.getenv("GOOGLE_FLIGHTS_TOTAL_TIMEOUT_SECONDS", "900"))
    grouped: dict[str, list[FlightOffer]] = {item.key: [] for item in searches}
    async with async_playwright() as playwright:
        ua = random_user_agent()
        vp = random_viewport()
        hdrs = random_headers()
        browser = await playwright.chromium.launch(
            headless=True,
            args=stealth_browser_args(),
        )
        context = await browser.new_context(
            locale="en-GB",
            timezone_id="Europe/London",
            user_agent=ua,
            viewport=vp,
            extra_http_headers={
                "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
                "Referer": "https://www.google.com/",
                "Sec-CH-UA": hdrs.get("Sec-CH-UA", ""),
                "Sec-CH-UA-Mobile": hdrs.get("Sec-CH-UA-Mobile", "?0"),
                "Sec-CH-UA-Platform": hdrs.get("Sec-CH-UA-Platform", '"Windows"'),
            },
        )
        await context.add_cookies([
            {"name": "SOCS", "value": "CAISHAgBEhJnd3NfMjAyNDA4MjAtMF9SQzIaAmVuIAEaBgiA_L20Bg", "domain": ".google.com", "path": "/"},
            {"name": "CONSENT", "value": "PENDING+999", "domain": ".google.com", "path": "/"},
        ])
        page = await context.new_page()
        await inject_canvas_noise(page)
        try:
            await warm_up_session(page, "https://www.google.com/travel/flights")
            await human_delay(2.0, 4.0)
            for search, day in specs:
                if time.monotonic() >= deadline:
                    break
                url = build_google_flights_url(
                    origins=search.origins, destinations=search.destinations,
                    date=day, travellers=search.travellers,
                    cabin_class=search.cabin_class,
                )
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                    await human_delay(3.0, 6.0, think=True)
                except Exception:
                    continue
                if await check_waf(page):
                    continue
                cards = None
                for selector in CARD_SELECTORS:
                    try:
                        await page.wait_for_selector(selector, timeout=timeout_ms)
                        candidate = page.locator(selector)
                        if await candidate.count():
                            cards = candidate
                            break
                    except Exception:
                        continue
                if cards is None:
                    continue
                seen: set[tuple[Any, ...]] = set()
                for index in range(min(await cards.count(), 15)):
                    try:
                        text = await cards.nth(index).inner_text(timeout=2_000)
                    except Exception:
                        continue
                    offer = parse_google_flight_text(
                        text, origins=search.origins, destinations=search.destinations,
                        date=day, travellers=search.travellers, booking_url=url,
                    )
                    if offer is None:
                        continue
                    clock = offer.departure[11:16]
                    if not search.departure_window[0] <= clock <= search.departure_window[1]:
                        continue
                    if offer.stops > search.max_stops or offer.duration_minutes > search.max_duration_minutes:
                        continue
                    if search.max_price_per_traveller_gbp is not None and (offer.price_per_traveller or 0) > search.max_price_per_traveller_gbp:
                        continue
                    key = (offer.departure, offer.airline, offer.price, offer.stops)
                    if key not in seen:
                        seen.add(key)
                        grouped[search.key].append(offer)
        finally:
            await browser.close()
    return {
        key: tuple(sorted(values, key=lambda item: (item.price, item.duration_minutes))[:10])
        for key, values in grouped.items()
    }
