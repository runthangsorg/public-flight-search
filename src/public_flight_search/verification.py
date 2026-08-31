"""Booking link verification engine.

Verifies that constructed booking URLs resolve correctly, detecting:
- WAF / bot challenge pages
- 404 errors
- Homepage redirects (deep link stripped)
- Route/destination mismatches
- Domain safety violations

Lifted from private muscat_deal_finder.py V5 with all PII removed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlparse, parse_qs


VERIFIED_PREFILLED = "VERIFIED_PREFILLED"
VERIFIED_LANDING_PAGE = "VERIFIED_LANDING_PAGE"
FAILED_404 = "FAILED_404"
FAILED_REDIRECT = "FAILED_REDIRECT"
FAILED_WRONG_ROUTE = "FAILED_WRONG_ROUTE"
FAILED_BOT_CHALLENGE = "FAILED_BOT_CHALLENGE"
PREFILLED_DEEP_LINK = "PREFILLED_DEEP_LINK"
LANDING_PAGE = "LANDING_PAGE"

HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}

BOT_INDICATORS = [
    "access denied", "security check", "challenge-platform",
    "cf-browser-verification", "datadome", "captcha",
    "are you a human", "403 forbidden",
]

ERROR_INDICATORS = [
    "404 not found", "<title>404", "page not found", "page cannot be found",
    "the requested page could not be found", "error 404", "page doesn't exist",
]

LANDING_PATHS = {"", "/", "/en", "/en-gb", "/en-us", "/uk", "/gb", "/home", "/index", "/index.html"}


def provider_domain_matches_label(provider: str, url: str) -> bool:
    """Check that the URL hostname matches the expected provider."""
    try:
        hostname = urlparse(url).hostname or ""
    except Exception:
        return False
    provider_lower = provider.lower().replace(" ", "")
    hostname_lower = hostname.lower()
    return provider_lower in hostname_lower or hostname_lower.endswith(f".{provider_lower}.co.uk")


def verify_booking_link(
    url: str,
    provider: str = "",
    link_type: str = PREFILLED_DEEP_LINK,
    expected_origin: str = "",
    expected_destination: str = "",
    expected_departure_date: str = "",
    expected_return_date: str = "",
) -> Dict[str, Any]:
    """Verify a booking link via HTTP request and semantic checks.

    Returns a dict with verification_status, final_url, and notes.
    Does not require httpx — uses a simple urllib fallback.
    """
    result: Dict[str, Any] = {
        "url": url,
        "provider": provider,
        "link_type": link_type,
        "verification_status": UNVERIFIED,
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "expected_origin": expected_origin,
        "expected_destination": expected_destination,
        "expected_departure_date": expected_departure_date,
        "expected_return_date": expected_return_date,
        "notes": "",
    }

    try:
        import httpx
        client = httpx.Client(follow_redirects=True, timeout=12.0, headers=HTTP_HEADERS)
        try:
            resp = client.get(url)
            status_code = resp.status_code
            final_url = str(resp.url)
            body_text = resp.text
        finally:
            client.close()
    except ImportError:
        import urllib.request
        req = urllib.request.Request(url, headers=HTTP_HEADERS)
        try:
            resp = urllib.request.urlopen(req, timeout=12)
            status_code = resp.status
            final_url = resp.url
            body_text = resp.read().decode("utf-8", errors="ignore")
        except Exception as e:
            result["verification_status"] = FAILED_404
            result["notes"] = f"Connection failed: {e}"
            return result
    except Exception as e:
        result["verification_status"] = FAILED_404
        result["notes"] = f"Connection failed: {e}"
        return result

    if status_code >= 400:
        result["verification_status"] = FAILED_404
        result["notes"] = f"HTTP {status_code} Error"
        return result

    if provider and not provider_domain_matches_label(provider, final_url):
        result["verification_status"] = FAILED_REDIRECT
        result["notes"] = f"Redirected to unauthorized domain: {final_url}"
        return result

    body_lower = body_text.lower()
    if any(ind in body_lower for ind in ERROR_INDICATORS):
        result["verification_status"] = FAILED_404
        result["notes"] = "Page content returned 404 Not Found"
        return result

    if any(b in body_lower for b in BOT_INDICATORS):
        result["verification_status"] = FAILED_BOT_CHALLENGE
        result["notes"] = "Bot verification / WAF challenge intercepted request"
        return result

    if link_type == PREFILLED_DEEP_LINK:
        parsed_final = urlparse(final_url)
        clean_path = parsed_final.path.rstrip("/").lower()
        is_landing = clean_path in LANDING_PATHS and not parsed_final.query
        if is_landing:
            result["verification_status"] = VERIFIED_LANDING_PAGE
            result["link_type"] = LANDING_PAGE
            result["notes"] = "Prefilled parameters redirected to homepage; downgraded to landing page"
            return result

        query = parse_qs(parsed_final.query.lower())
        if expected_origin:
            url_origins = query.get("origin", []) + query.get("orig", []) + query.get("from", []) + query.get("dcity", [])
            if url_origins and not any(expected_origin.lower() in o for o in url_origins):
                result["verification_status"] = FAILED_WRONG_ROUTE
                result["notes"] = f"Route mismatch: expected origin {expected_origin}"
                return result

        if expected_destination:
            url_dests = query.get("destination", []) + query.get("dest", []) + query.get("to", []) + query.get("acity", [])
            if url_dests and not any(expected_destination.lower() in d for d in url_dests):
                result["verification_status"] = FAILED_WRONG_ROUTE
                result["notes"] = f"Route mismatch: expected destination {expected_destination}"
                return result

        result["verification_status"] = VERIFIED_PREFILLED
        result["notes"] = "Prefilled deep link verified"
    else:
        result["verification_status"] = VERIFIED_LANDING_PAGE
        result["notes"] = "Official booking portal verified"

    return result


UNVERIFIED = "UNVERIFIED"
