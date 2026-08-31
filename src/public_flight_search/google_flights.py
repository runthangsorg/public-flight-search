"""Bounded Google Flights results-page adapter using the public web UI."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import re
import sys
import time
from typing import Any, Iterable
from urllib.parse import quote

from .config import FlightSearch
from .stealth import apply_stealth_async

_anti_bot_dir = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
if _anti_bot_dir not in sys.path:
    sys.path.insert(0, _anti_bot_dir)
try:
    from shared.anti_bot import (
        random_user_agent, random_viewport, human_delay,
        inject_canvas_noise, warm_up_session, stealth_browser_args,
        dismiss_cookies, check_waf,
    )
except ImportError:
    import asyncio
    import random as _random

    _USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36 Edg/135.0.0.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.4 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    ]
    _VIEWPORTS = [
        {"width": 1920, "height": 1080}, {"width": 1366, "height": 768},
        {"width": 1536, "height": 864}, {"width": 1440, "height": 900},
        {"width": 1280, "height": 800}, {"width": 1600, "height": 900},
    ]
    _WAF_SIGNALS = [
        "unusual traffic from your computer", "not a robot",
        "our systems have detected unusual traffic",
        "please complete the security check",
        "access to this page has been denied",
        "automated queries are disabled",
        "http/2 429", "rate limit exceeded",
    ]
    _COOKIE_SELECTORS = [
        'button:has-text("Accept all")', 'button:has-text("Reject all")',
        'button:has-text("I agree")', 'button:has-text("Got it")',
        '[aria-label="Accept all"]', '[aria-label="Reject all"]',
    ]

    def random_user_agent(**kw):
        return _random.choice(_USER_AGENTS)

    def random_viewport(**kw):
        return _random.choice(_VIEWPORTS)

    def stealth_browser_args(extra=None):
        args = [
            "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars", "--disable-extensions",
            "--disable-background-networking", "--disable-default-apps",
            "--disable-sync", "--metrics-recording-only", "--no-first-run",
        ]
        if extra:
            args.extend(extra)
        return args

    async def human_delay(min_s=1.0, max_s=3.5, think=False):
        delay = _random.gauss((min_s + max_s) / 2, (max_s - min_s) / 4)
        delay = max(min_s, min(max_s, delay))
        if think:
            delay += _random.uniform(0.5, 2.0)
        await asyncio.sleep(delay)

    async def inject_canvas_noise(page):
        try:
            await page.add_init_script("""
                const _origToDataURL = HTMLCanvasElement.prototype.toDataURL;
                HTMLCanvasElement.prototype.toDataURL = function() {
                    const ctx = this.getContext('2d');
                    if (ctx) {
                        const imgData = ctx.getImageData(0, 0, this.width, this.height);
                        for (let i = 0; i < imgData.data.length; i += 4) {
                            imgData.data[i] ^= 1;
                        }
                        ctx.putImageData(imgData, 0, 0);
                    }
                    return _origToDataURL.apply(this, arguments);
                };
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            """)
        except Exception:
            pass

    async def warm_up_session(page, url):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=15_000)
            await human_delay(1.0, 3.0)
            await page.mouse.move(_random.randint(100, 500), _random.randint(100, 400))
            await human_delay(0.3, 0.8)
        except Exception:
            pass

    async def dismiss_cookies(page):
        for sel in _COOKIE_SELECTORS:
            try:
                btn = page.locator(sel).first
                if await btn.count() and await btn.is_visible():
                    await btn.click()
                    await human_delay(0.5, 1.0)
                    return
            except Exception:
                continue

    async def check_waf(page):
        try:
            html = (await page.content()).lower()
            for signal in _WAF_SIGNALS:
                if signal in html:
                    print(f"[DEBUG] WAF signal matched: '{signal}'")
                    return True
            return False
        except Exception:
            return False
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
    timeout_ms = int(os.getenv("GOOGLE_FLIGHTS_RESULT_TIMEOUT_MS", "15000"))
    deadline = time.monotonic() + int(os.getenv("GOOGLE_FLIGHTS_TOTAL_TIMEOUT_SECONDS", "900"))
    grouped: dict[str, list[FlightOffer]] = {item.key: [] for item in searches}
    screenshots_dir = os.getenv("SCREENSHOTS_DIR", "/tmp/flight-verify")
    async with async_playwright() as playwright:
        ua = random_user_agent()
        vp = random_viewport()
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
            },
        )
        await context.add_cookies([
            {"name": "SOCS", "value": "CAISHAgBEhJnd3NfMjAyNDA4MjAtMF9SQzIaAmVuIAEaBgiA_L20Bg", "domain": ".google.com", "path": "/"},
            {"name": "CONSENT", "value": "PENDING+999", "domain": ".google.com", "path": "/"},
        ])
        page = await context.new_page()
        await apply_stealth_async(page)
        await inject_canvas_noise(page)
        try:
            await warm_up_session(page, "https://www.google.com/travel/flights")
            await human_delay(2.0, 4.0)
            await dismiss_cookies(page)
            print(f"[DEBUG] Starting {len(specs)} searches, deadline in {deadline - time.monotonic():.0f}s")
            for idx, (search, day) in enumerate(specs):
                if time.monotonic() >= deadline:
                    print(f"[DEBUG] Deadline reached at search {idx}")
                    break
                url = build_google_flights_url(
                    origins=search.origins, destinations=search.destinations,
                    date=day, travellers=search.travellers,
                    cabin_class=search.cabin_class,
                )
                print(f"[DEBUG] Search {idx+1}/{len(specs)}: {search.key} {day} -> {url[:80]}...")
                try:
                    await page.goto(url, wait_until="networkidle", timeout=45_000)
                    await human_delay(4.0, 7.0, think=True)
                except Exception as e:
                    print(f"[DEBUG] networkidle failed: {e}")
                    try:
                        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                        await human_delay(5.0, 8.0, think=True)
                    except Exception as e2:
                        print(f"[DEBUG] domcontentloaded also failed: {e2}")
                        continue
                await dismiss_cookies(page)
                page_text = ""
                try:
                    page_text = (await page.content())[:2000].lower()
                except Exception:
                    pass
                if await check_waf(page):
                    print(f"[DEBUG] WAF detected on {search.key} {day}")
                    try:
                        os.makedirs(screenshots_dir, exist_ok=True)
                        await page.screenshot(
                            path=os.path.join(screenshots_dir, f"waf_{search.key}_{day}.png"),
                            full_page=False,
                        )
                    except Exception:
                        pass
                    continue
                form_filled = False
                try:
                    trip_btn = page.locator('button:has-text("Round trip"), button:has-text("One way")').first
                    if await trip_btn.count():
                        current = await trip_btn.inner_text()
                        if "one way" not in current.lower():
                            await trip_btn.click()
                            await human_delay(0.3, 0.6)
                            one_way = page.locator('[role="option"]:has-text("One way")').first
                            if await one_way.count():
                                await one_way.click()
                                await human_delay(0.5, 1.0)
                    from_field = page.locator('input[placeholder*="Where from"]').first
                    if await from_field.count() and await from_field.is_visible():
                        await from_field.click()
                        await human_delay(0.3, 0.8)
                        await from_field.press_sequentially(search.origins[0], delay=80)
                        await human_delay(1.0, 2.0)
                        suggestion = page.locator('[role="option"]').first
                        if await suggestion.count():
                            await suggestion.click()
                            await human_delay(0.5, 1.0)
                        to_field = page.locator('input[placeholder*="Where to"]').first
                        if await to_field.count() and await to_field.is_visible():
                            await to_field.click()
                            await human_delay(0.3, 0.8)
                            await to_field.press_sequentially(search.destinations[0], delay=80)
                            await human_delay(1.0, 2.0)
                            suggestion2 = page.locator('[role="option"]').first
                            if await suggestion2.count():
                                await suggestion2.click()
                                await human_delay(0.5, 1.0)
                            search_btn = page.locator('button[aria-label*="Search"], button:has-text("Search")').first
                            if await search_btn.count():
                                await search_btn.click()
                                await human_delay(5.0, 8.0, think=True)
                                form_filled = True
                except Exception as e:
                    print(f"[DEBUG] Form interaction error: {e}")
                print(f"[DEBUG] form_filled={form_filled}")
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
                    print(f"[DEBUG] No cards found for {search.key} {day}")
                    try:
                        os.makedirs(screenshots_dir, exist_ok=True)
                        await page.screenshot(
                            path=os.path.join(screenshots_dir, f"no_cards_{search.key}_{day}.png"),
                            full_page=False,
                        )
                    except Exception:
                        pass
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
                print(f"[DEBUG] Parsed {len(seen)} offers from cards for {search.key} {day}")
                try:
                    os.makedirs(screenshots_dir, exist_ok=True)
                    await page.screenshot(
                        path=os.path.join(screenshots_dir, f"results_{search.key}_{day}.png"),
                        full_page=False,
                    )
                except Exception:
                    pass
        finally:
            await browser.close()
    return {
        key: tuple(sorted(values, key=lambda item: (item.price, item.duration_minutes))[:10])
        for key, values in grouped.items()
    }
