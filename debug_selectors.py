"""Temporary debug: capture Google Flights page structure for selector tuning."""
import asyncio, os, sys, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))

from shared.anti_bot import (
    random_user_agent, random_viewport, human_delay,
    inject_canvas_noise, warm_up_session, stealth_browser_args,
    check_waf,
)

async def debug():
    from playwright.async_api import async_playwright
    ua = random_user_agent()
    vp = random_viewport()
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, args=stealth_browser_args())
        context = await browser.new_context(
            locale="en-GB", timezone_id="Europe/London",
            user_agent=ua, viewport=vp,
            extra_http_headers={"Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8"},
        )
        await context.add_cookies([
            {"name": "SOCS", "value": "CAISHAgBEhJnd3NfMjAyNDA4MjAtMF9SQzIaAmVuIAEaBgiA_L20Bg", "domain": ".google.com", "path": "/"},
            {"name": "CONSENT", "value": "PENDING+999", "domain": ".google.com", "path": "/"},
        ])
        page = await context.new_page()
        await inject_canvas_noise(page)
        await warm_up_session(page, "https://www.google.com/travel/flights")
        await human_delay(2.0, 4.0)

        url = "https://www.google.com/travel/flights?q=one+way+flights+from+LTN+to+FNC+on+2026-07-20+5+adults+economy+cabin&curr=GBP&hl=en-GB"
        try:
            await page.goto(url, wait_until="networkidle", timeout=45000)
        except Exception as e:
            print("GOTO:", str(e)[:100])
        await human_delay(5.0, 8.0, think=True)

        is_waf = await check_waf(page)
        print("WAF:", is_waf)
        print("Title:", await page.title())
        print("URL:", page.url)

        # Dump all list items
        for sel in [
            '[role="main"] li[role="listitem"]',
            '[role="main"] [role="listitem"]',
            'ul li',
            'div[role="listitem"]',
            '[data-ved]',
            'li',
        ]:
            try:
                count = await page.locator(sel).count()
                if count > 0:
                    print(f"Selector '{sel}': {count} matches")
                    for i in range(min(count, 3)):
                        try:
                            txt = await page.locator(sel).nth(i).inner_text(timeout=2000)
                            print(f"  [{i}]: {txt[:200]}")
                        except:
                            pass
            except:
                pass

        # Get body text
        try:
            body = await page.inner_text("body")
            import re
            prices = re.findall(r"\u00a3[\d,]+", body)
            print("Prices:", prices[:10] if prices else "none")
            print("Body (500):", body[:500])
        except:
            pass

        # Save screenshot
        os.makedirs("/tmp/flight-verify", exist_ok=True)
        await page.screenshot(path="/tmp/flight-verify/gha_debug.png", full_page=True)
        print("Screenshot saved")

        await browser.close()

asyncio.run(debug())
