"""
Anti-bot evasion utilities for Playwright and curl_cffi scrapers.

Covers:
  - Fresh, rotated User-Agent strings (Chrome 134+, Edge, Safari, mobile)
  - Randomised viewport sizes matching real-world distributions
  - Human-like delays (Gaussian, think-time, jitter)
  - Retry with exponential backoff
  - Consistent header sets (Accept, Accept-Language, Referer, Sec-CH-*)
  - Canvas / WebGL fingerprint noise injection via Playwright
  - Session warm-up (homepage visit before target)
  - Realistic scroll and mouse-movement patterns
  - WAF / captcha detection helpers
  - curl_cffi header sets with browser impersonation

Usage:
    from shared.anti_bot import (
        random_user_agent, random_viewport, human_delay,
        get_headers_for_url, check_waf, warm_up_session,
        human_scroll, human_mouse_move, retry_with_backoff,
        curl_headers, STEALTH_CHROMIUM_ARGS,
    )
"""

from __future__ import annotations

import asyncio
import math
import random
import time
from typing import Optional
from urllib.parse import urlparse

# ═══════════════════════════════════════════════════════════════════════
# USER-AGENT ROTATION
# ═══════════════════════════════════════════════════════════════════════
# Chrome 134-136 (current stable ~Aug 2026), Edge 134+, Safari 18+,
# plus mobile variants.  All UAs are real shipping strings.

_DESKTOP_UAS = [
    # Chrome on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    # Chrome on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    # Chrome on Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
    # Edge on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36 Edg/136.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36 Edg/135.0.0.0",
    # Safari on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Safari/605.1.15",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.4 Safari/605.1.15",
]

_MOBILE_UAS = [
    # iPhone Safari
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.4 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.3 Mobile/15E148 Safari/604.1",
    # Android Chrome
    "Mozilla/5.0 (Linux; Android 15; Pixel 9) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Mobile Safari/537.36",
    # iPad Safari
    "Mozilla/5.0 (iPad; CPU OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1",
]

ALL_USER_AGENTS = _DESKTOP_UAS + _MOBILE_UAS

# Platform metadata per UA family (for Sec-CH headers)
_PLATFORM_HINTS = {
    "Windows": "Windows",
    "Macintosh": "macOS",
    "X11": "Linux",
    "iPhone": "iOS",
    "Linux": "Android",
    "iPad": "iOS",
}


def random_user_agent(mobile: bool = False) -> str:
    """Return a random current User-Agent string.

    Args:
        mobile: If True, return only mobile UAs.  If False, prefer desktop
                (70 % desktop, 30 % mobile to match real traffic mix).
    """
    if mobile:
        return random.choice(_MOBILE_UAS)
    if random.random() < 0.70:
        return random.choice(_DESKTOP_UAS)
    return random.choice(_MOBILE_UAS)


def _ua_platform(ua: str) -> str:
    """Infer the Sec-CH-UA-Platform from the UA string."""
    for fragment, platform in _PLATFORM_HINTS.items():
        if fragment in ua:
            return platform
    return "Windows"


def _ua_mobile(ua: str) -> bool:
    """Return True if the UA looks like a mobile device."""
    return any(tok in ua for tok in ("iPhone", "Android", "iPad"))


# ═══════════════════════════════════════════════════════════════════════
# VIEWPORT RANDOMISATION
# ═══════════════════════════════════════════════════════════════════════

_DESKTOP_VIEWPORTS = [
    (1920, 1080), (1536, 864), (1440, 900), (1366, 768),
    (1280, 720), (1600, 900), (1680, 1050), (2560, 1440),
    (1280, 800), (1366, 900), (1536, 960), (1440, 810),
]

_MOBILE_VIEWPORTS = [
    (390, 844),   # iPhone 15 / 16
    (393, 852),   # iPhone 15 Pro
    (430, 932),   # iPhone 15 Pro Max
    (360, 800),   # Samsung Galaxy S24
    (412, 915),   # Pixel 8
    (360, 780),   # Generic Android
    (393, 873),   # iPhone 16 Pro
]


def random_viewport(mobile: bool = False) -> dict:
    """Return a random viewport dict ``{"width": W, "height": H}``."""
    if mobile:
        w, h = random.choice(_MOBILE_VIEWPORTS)
    else:
        w, h = random.choice(_DESKTOP_VIEWPORTS)
    return {"width": w, "height": h}


# ═══════════════════════════════════════════════════════════════════════
# HUMAN-LIKE DELAYS
# ═══════════════════════════════════════════════════════════════════════

async def human_delay(min_s: float = 1.0, max_s: float = 3.5, think: bool = False) -> float:
    """Gaussian-distributed delay that mimics human reaction time.

    When ``think=True`` the delay is longer (3-7 s) and includes a
    secondary micro-pause, simulating a user reading content.
    """
    if think:
        base = random.gauss(5.0, 1.2)
        delay = max(3.0, min(base, 7.0))
    else:
        base = random.gauss((min_s + max_s) / 2, (max_s - min_s) / 4)
        delay = max(min_s, min(base, max_s))
    # Tiny jitter to break periodicity
    delay += random.uniform(-0.15, 0.15)
    delay = max(0.3, delay)
    await asyncio.sleep(delay)
    return delay


def sync_human_delay(min_s: float = 1.0, max_s: float = 3.5) -> float:
    """Synchronous version for curl_cffi / non-async scrapers."""
    base = random.gauss((min_s + max_s) / 2, (max_s - min_s) / 4)
    delay = max(min_s, min(base, max_s))
    delay += random.uniform(-0.15, 0.15)
    delay = max(0.3, delay)
    time.sleep(delay)
    return delay


# ═══════════════════════════════════════════════════════════════════════
# REQUEST HEADERS (for curl_cffi / requests)
# ═══════════════════════════════════════════════════════════════════════

def get_headers_for_url(
    url: str,
    ua: Optional[str] = None,
    extra: Optional[dict] = None,
) -> dict:
    """Build a realistic header set for *url*.

    Includes Referer derived from the URL's own origin, Accept-Language,
    Sec-CH-* client hints, and a matching Accept header.
    """
    ua = ua or random_user_agent()
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    headers = {
        "User-Agent": ua,
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,"
            "application/signed-exchange;v=b3;q=0.7"
        ),
        "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Referer": origin + "/",
        "Sec-CH-UA": f'"Chromium";v="136", "Google Chrome";v="136", "Not-A.Brand";v="99"',
        "Sec-CH-UA-Mobile": "?1" if _ua_mobile(ua) else "?0",
        "Sec-CH-UA-Platform": f'"{_ua_platform(ua)}"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "Cache-Control": "max-age=0",
        "DNT": "1",
    }
    if extra:
        headers.update(extra)
    return headers


def curl_headers(url: str, ua: Optional[str] = None) -> dict:
    """Thin wrapper: headers dict suitable for ``curl_cffi.requests.get``."""
    return get_headers_for_url(url, ua=ua)


# ═══════════════════════════════════════════════════════════════════════
# PLAYWRIGHT STEALTH ARGUMENTS
# ═══════════════════════════════════════════════════════════════════════

STEALTH_CHROMIUM_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
    "--no-sandbox",
    "--disable-infobars",
    "--disable-extensions",
    "--disable-gpu",
    "--disable-background-timer-throttling",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--disable-features=TranslateUI",
    "--lang=en-GB",
]


def stealth_browser_args(extra: Optional[list[str]] = None) -> list[str]:
    """Return Chromium launch args with anti-detection flags."""
    args = list(STEALTH_CHROMIUM_ARGS)
    if extra:
        args.extend(extra)
    return args


# ═══════════════════════════════════════════════════════════════════════
# PLAYWRIGHT CONTEXT FACTORY
# ═══════════════════════════════════════════════════════════════════════

async def create_stealth_context(
    playwright,
    *,
    headless: bool = False,
    user_agent: Optional[str] = None,
    viewport: Optional[dict] = None,
    locale: str = "en-GB",
    timezone: str = "Europe/London",
    proxy: Optional[dict] = None,
    user_data_dir: Optional[str] = None,
    extra_args: Optional[list[str]] = None,
    extra_context_opts: Optional[dict] = None,
):
    """Create a Playwright browser context with full anti-bot settings.

    Returns (browser, context) — caller is responsible for closing.
    If ``user_data_dir`` is given, a persistent context is used.
    """
    from playwright_stealth import Stealth

    ua = user_agent or random_user_agent()
    vp = viewport or random_viewport(mobile=_ua_mobile(ua))

    launch_args = stealth_browser_args(extra_args)

    context_opts = {
        "viewport": vp,
        "user_agent": ua,
        "locale": locale,
        "timezone_id": timezone,
        "color_scheme": "light",
        "java_script_enabled": True,
        "ignore_https_errors": True,
        "accept_downloads": False,
        "extra_http_headers": {
            "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
        },
    }
    if proxy:
        context_opts["proxy"] = proxy
    if extra_context_opts:
        context_opts.update(extra_context_opts)

    if user_data_dir:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=headless,
            args=launch_args,
            **context_opts,
        )
        browser = None
    else:
        browser = await playwright.chromium.launch(
            headless=headless,
            args=launch_args,
        )
        context = await browser.new_context(**context_opts)

    # Apply stealth to all existing and future pages
    stealth = Stealth()
    for page in context.pages:
        await stealth.apply_stealth_async(page)
    context.on("page", lambda p: asyncio.create_task(
        stealth.apply_stealth_async(p)
    ))

    return browser, context


# ═══════════════════════════════════════════════════════════════════════
# CANVAS / WEBGL NOISE INJECTION
# ═══════════════════════════════════════════════════════════════════════

_CANVAS_NOISE_JS = """
(() => {
    // Add subtle noise to canvas fingerprint
    const origToDataURL = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = function(type) {
        if (type === 'image/png' && this.width < 16 && this.height < 16) {
            const ctx = this.getContext('2d');
            if (ctx) {
                const imgData = ctx.getImageData(0, 0, this.width, this.height);
                for (let i = 0; i < imgData.data.length; i += 4) {
                    imgData.data[i] ^= 1;  // flip LSB of red channel
                }
                ctx.putImageData(imgData, 0, 0);
            }
        }
        return origToDataURL.apply(this, arguments);
    };

    // Add noise to WebGL renderer string
    const getParam = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(param) {
        if (param === 37445) return 'Intel Inc.';
        if (param === 37446) return 'Intel Iris OpenGL Engine';
        return getParam.call(this, param);
    };
    const getParam2 = WebGL2RenderingContext.prototype.getParameter;
    WebGL2RenderingContext.prototype.getParameter = function(param) {
        if (param === 37445) return 'Intel Inc.';
        if (param === 37446) return 'Intel Iris OpenGL Engine';
        return getParam2.call(this, param);
    };
})();
"""


async def inject_canvas_noise(page) -> None:
    """Inject canvas / WebGL noise to prevent fingerprinting."""
    try:
        await page.evaluate(_CANVAS_NOISE_JS)
    except Exception:
        pass  # Non-critical


# ═══════════════════════════════════════════════════════════════════════
# SESSION WARM-UP
# ═══════════════════════════════════════════════════════════════════════

async def warm_up_session(page, url: str, visits: int = 1) -> bool:
    """Visit the target origin's homepage before the real URL.

    Many WAFs set cookies on the first visit and verify them on the second.
    This also populates the browser's history for realistic Referer chains.
    """
    from urllib.parse import urlparse
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    try:
        for _ in range(visits):
            await page.goto(origin, wait_until="domcontentloaded", timeout=20000)
            await human_delay(1.5, 3.0)
        return True
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════
# REALISTIC SCROLLING
# ═══════════════════════════════════════════════════════════════════════

async def human_scroll(
    page,
    scrolls: Optional[int] = None,
    min_px: int = 150,
    max_px: int = 800,
    pause_range: tuple[float, float] = (0.4, 1.6),
) -> None:
    """Scroll the page like a real user: variable distance, variable speed,
    occasional pauses, and sometimes scrolling back up slightly.
    """
    if scrolls is None:
        scrolls = random.randint(3, 8)
    for i in range(scrolls):
        dist = random.randint(min_px, max_px)
        # Occasionally overshoot then correct
        if random.random() < 0.15:
            overshoot = random.randint(50, 200)
            await page.evaluate(f"window.scrollBy(0, {dist + overshoot})")
            await asyncio.sleep(random.uniform(0.1, 0.3))
            await page.evaluate(f"window.scrollBy(0, {-overshoot})")
        else:
            await page.evaluate(f"window.scrollBy(0, {dist})")
        await asyncio.sleep(random.uniform(*pause_range))
        # Rarely scroll back up
        if random.random() < 0.1 and i > 1:
            back = random.randint(50, 300)
            await page.evaluate(f"window.scrollBy(0, {-back})")
            await asyncio.sleep(random.uniform(0.3, 0.8))


# ═══════════════════════════════════════════════════════════════════════
# REALISTIC MOUSE MOVEMENT
# ═══════════════════════════════════════════════════════════════════════

async def human_mouse_move(page, steps: Optional[int] = None) -> None:
    """Move the mouse along a curved Bezier-like path to a random point."""
    if steps is None:
        steps = random.randint(8, 20)
    # Start from a random position near centre
    x0 = random.randint(200, 800)
    y0 = random.randint(200, 400)
    x1 = random.randint(100, 1200)
    y1 = random.randint(100, 600)
    # Control point for quadratic Bezier
    cx = random.randint(0, 1400)
    cy = random.randint(0, 800)
    for t_i in range(steps + 1):
        t = t_i / steps
        # Quadratic Bezier: (1-t)^2*P0 + 2*(1-t)*t*C + t^2*P1
        mt = 1 - t
        px = mt * mt * x0 + 2 * mt * t * cx + t * t * x1
        py = mt * mt * y0 + 2 * mt * t * cy + t * t * y1
        await page.mouse.move(px, py)
        await asyncio.sleep(random.uniform(0.01, 0.06))


# ═══════════════════════════════════════════════════════════════════════
# WAF / CAPTCHA DETECTION
# ═══════════════════════════════════════════════════════════════════════

WAF_SIGNALS = [
    "cloudflare", "datadome", "perimeterx", "imperva",
    "just a moment", "verify you are human", "access denied",
    "checking your browser", "security check", "bot detection",
    "please complete the security check", "challenge-platform",
    "cf-browser-verification", "hcaptcha", "recaptcha",
    "g-recaptcha", "captcha-container", "blocked",
    "attention required", "security verify", "distil",
    "akamai", "shape.security", "incapsula", "sucuri",
]


async def check_waf(page) -> bool:
    """Detect WAF / CAPTCHA / access-denied pages."""
    try:
        html = (await page.content()).lower()
        return any(signal in html for signal in WAF_SIGNALS)
    except Exception:
        return False


def check_waf_html(html: str) -> bool:
    """Detect WAF signals in raw HTML string (for curl_cffi responses)."""
    lower = html.lower()
    return any(signal in lower for signal in WAF_SIGNALS)


# ═══════════════════════════════════════════════════════════════════════
# COOKIE CONSENT DISMISSAL
# ═══════════════════════════════════════════════════════════════════════

COOKIE_SELECTORS = [
    '#onetrust-accept-btn-handler',
    'button:has-text("Allow all")',
    'button:has-text("Allow All")',
    'button:has-text("Accept All")',
    'button:has-text("Accept all")',
    'button:has-text("Accept Cookies")',
    'button:has-text("Accept cookies")',
    'button:has-text("Accept")',
    'button:has-text("I Accept")',
    'button:has-text("I agree")',
    'button:has-text("Agree")',
    'button:has-text("OK")',
    'button:has-text("Got it")',
    'button:has-text("Continue")',
    '.cky-btn-accept',
    '[data-testid="accept-cookies"]',
    '[id*="cookie"] button',
    '[class*="cookie"] button',
    '[id*="consent"] button:has-text("Allow")',
    '[id*="consent"] button:has-text("Accept")',
]


async def dismiss_cookies(page) -> bool:
    """Try to dismiss cookie consent banners. Returns True if dismissed."""
    for sel in COOKIE_SELECTORS:
        try:
            btn = page.locator(sel).first
            if await btn.is_visible(timeout=1000):
                await btn.click(timeout=2000)
                await asyncio.sleep(random.uniform(1.0, 2.0))
                return True
        except Exception:
            continue
    return False


# ═══════════════════════════════════════════════════════════════════════
# RETRY WITH EXPONENTIAL BACKOFF
# ═══════════════════════════════════════════════════════════════════════

async def retry_with_backoff(
    coro_func,
    max_retries: int = 3,
    base_delay: float = 2.0,
    max_delay: float = 30.0,
    backoff_factor: float = 2.0,
    retry_on: tuple = (Exception,),
):
    """Retry an async callable with exponential backoff + jitter.

    ``coro_func`` should be a zero-arg callable returning an awaitable.
    """
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return await coro_func()
        except retry_on as exc:
            last_exc = exc
            if attempt == max_retries:
                raise
            delay = min(base_delay * (backoff_factor ** attempt), max_delay)
            delay += random.uniform(0, delay * 0.3)  # jitter
            await asyncio.sleep(delay)
    raise last_exc  # unreachable but satisfies type checkers


# ═══════════════════════════════════════════════════════════════════════
# CONVENIENCE: FULL STEALTH PAGE FACTORY
# ═══════════════════════════════════════════════════════════════════════

async def open_stealth_page(
    context,
    url: str,
    *,
    warm_up: bool = True,
    inject_noise: bool = True,
    do_cookies: bool = True,
):
    """Open a new page, optionally warm up, inject noise, and dismiss cookies.

    Returns the page object.
    """
    page = await context.new_page()
    if inject_noise:
        await inject_canvas_noise(page)
    if warm_up:
        await warm_up_session(page, url)
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=45000)
    except Exception:
        pass
    if do_cookies:
        await dismiss_cookies(page)
    return page
