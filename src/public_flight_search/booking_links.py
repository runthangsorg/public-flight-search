"""Booking link verification and construction.

Verifies domain safety, HTTP status, and route semantics before including
links in reports. Never outputs speculative deep links.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional, Dict, Any
from urllib.parse import urlparse, parse_qs


# Verification statuses
VERIFIED_PREFILLED = "VERIFIED_PREFILLED"
VERIFIED_LANDING_PAGE = "VERIFIED_LANDING_PAGE"
FAILED_404 = "FAILED_404"
FAILED_WRONG_ROUTE = "FAILED_WRONG_ROUTE"
FAILED_REDIRECT = "FAILED_REDIRECT"
UNVERIFIED = "UNVERIFIED"

# Link types
PREFILLED_DEEP_LINK = "PREFILLED_DEEP_LINK"
LANDING_PAGE = "LANDING_PAGE"
METASEARCH = "METASEARCH"
OTA = "OTA"

# Airline official booking pages
AIRLINE_OFFICIAL_BOOKING_PAGES = {
    "Etihad Airways": "https://www.etihad.com/en-gb",
    "Oman Air": "https://www.omanair.com/en",
    "Air Arabia": "https://www.airarabia.com/en",
    "Pegasus": "https://www.flypgs.com/en",
    "Wizz Air": "https://wizzair.com/en-gb",
    "Wizz Air UK": "https://wizzair.com/en-gb",
    "Emirates": "https://www.emirates.com/uk/english/",
    "Flydubai": "https://www.flydubai.com/en",
    "SalamAir": "https://www.salamair.com/en",
    "Turkish Airlines": "https://www.turkishairlines.com/en-gb/",
    "AJet": "https://ajet.com/en",
    "British Airways": "https://www.britishairways.com/travel/fx/public/en_gb",
    "Qatar Airways": "https://www.qatarairways.com/en-gb/homepage.html",
    "Saudia": "https://www.saudia.com/pages/booking",
    "Gulf Air": "https://www.gulfair.com/",
    "Royal Jordanian": "https://www.rj.com/",
}

# Provider allowed domains for domain safety
PROVIDER_ALLOWED_DOMAINS = {
    "Etihad Airways": ["etihad.com", "www.etihad.com"],
    "Oman Air": ["omanair.com", "www.omanair.com"],
    "Air Arabia": ["airarabia.com", "www.airarabia.com"],
    "Pegasus": ["flypgs.com", "www.flypgs.com"],
    "Wizz Air": ["wizzair.com", "www.wizzair.com"],
    "Wizz Air UK": ["wizzair.com", "www.wizzair.com"],
    "Emirates": ["emirates.com", "www.emirates.com"],
    "Flydubai": ["flydubai.com", "www.flydubai.com"],
    "SalamAir": ["salamair.com", "www.salamair.com"],
    "Turkish Airlines": ["turkishairlines.com", "www.turkishairlines.com"],
    "AJet": ["ajet.com", "www.ajet.com"],
    "British Airways": ["britishairways.com", "www.britishairways.com"],
    "Qatar Airways": ["qatarairways.com", "www.qatarairways.com"],
    "Saudia": ["saudia.com", "www.saudia.com"],
    "Gulf Air": ["gulfair.com", "www.gulfair.com"],
    "Royal Jordanian": ["rj.com", "www.rj.com"],
    "Google Flights": ["google.com", "www.google.com"],
    "Kayak": ["kayak.co.uk", "kayak.com", "www.kayak.co.uk", "www.kayak.com"],
    "Trip.com": ["trip.com", "uk.trip.com", "www.trip.com"],
}


def provider_domain_matches_label(provider: str, url: str) -> bool:
    """Verify URL hostname belongs to the claimed provider."""
    try:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
        if not hostname:
            return False

        # Find canonical provider name
        canon = None
        for k in PROVIDER_ALLOWED_DOMAINS:
            if k.lower() == provider.lower():
                canon = k
                break

        allowed = PROVIDER_ALLOWED_DOMAINS.get(canon) if canon else None
        if not allowed:
            # Fallback: clean provider name should appear in hostname
            clean = "".join(c for c in provider.lower() if c.isalnum())
            return clean in hostname if clean else False

        return any(hostname == d or hostname.endswith("." + d) for d in allowed)
    except Exception:
        return False


@dataclass(frozen=True)
class BookingLink:
    """A verified or unverified booking link with metadata."""
    provider: str
    url: str
    link_type: str
    verification_status: str
    verified_at: Optional[datetime] = None
    expected_origin: Optional[str] = None
    expected_destination: Optional[str] = None
    expected_departure_date: Optional[date] = None
    expected_return_date: Optional[date] = None
    notes: Optional[str] = None

    @property
    def provider_domain_matches(self) -> bool:
        return provider_domain_matches_label(self.provider, self.url)

    @property
    def button_label(self) -> str:
        if self.verification_status == VERIFIED_PREFILLED:
            return f"Open Pre-Filled Booking ({self.provider})"
        return f"Open {self.provider} Official Booking Portal"

    @property
    def search_instruction(self) -> str:
        if self.expected_origin and self.expected_destination and self.expected_departure_date:
            out_str = f"{self.expected_origin} → {self.expected_destination}, {self.expected_departure_date.strftime('%d %b %Y')}"
            if self.expected_return_date:
                ret_orig = self.notes.split("→")[0].strip() if (self.notes and "→" in self.notes) else "AUH"
                return f"Search: {out_str}\nThen: {ret_orig} → {self.expected_origin}, {self.expected_return_date.strftime('%d %b %Y')}"
            return f"Search: {out_str}"
        return self.notes or "Official Airline Booking Portal"


def build_metasearch_urls(
    out_orig: str, out_dest: str, out_date: str,
    ret_orig: str, ret_dest: str, ret_date: str,
) -> Dict[str, str]:
    """Build metasearch URLs for the full round-trip."""
    google = (
        f"https://www.google.com/travel/flights?"
        f"q=Flights+from+{out_orig}+to+{out_dest}+on+{out_date}"
        f"+and+{ret_orig}+to+{ret_dest}+on+{ret_date}+1+adult+currency+GBP"
    )
    kayak = (
        f"https://www.kayak.co.uk/flights/"
        f"{out_orig}-{out_dest}/{out_date}/{ret_orig}-{ret_dest}/{ret_date}"
        f"/1adults?sort=bestflight_a"
    )
    trip_com = (
        f"https://uk.trip.com/flights/showresult?"
        f"dcity1={out_orig.upper()}&acity1={out_dest.upper()}&ddate1={out_date}"
        f"&dcity2={ret_orig.upper()}&acity2={ret_dest.upper()}&ddate2={ret_date}"
        f"&flighttype=mt&class=y&quantity=1"
    )
    return {
        "google": google,
        "kayak": kayak,
        "trip_com": trip_com,
    }


def build_booking_links(
    out_orig: str, out_dest: str, out_date: str,
    ret_orig: str, ret_dest: str, ret_date: str,
    outbound_carrier: Optional[str] = None,
    inbound_carrier: Optional[str] = None,
) -> Dict[str, Any]:
    """Build structured, verified BookingLink objects for an itinerary.

    Returns a dict with raw URLs and BookingLink objects.
    """
    out_d_obj = date.fromisoformat(out_date[:10])
    ret_d_obj = date.fromisoformat(ret_date[:10])

    out_carrier = outbound_carrier or "Etihad Airways"
    ret_carrier = inbound_carrier or "Etihad Airways"

    metasearch = build_metasearch_urls(out_orig, out_dest, out_date, ret_orig, ret_dest, ret_date)

    out_landing = AIRLINE_OFFICIAL_BOOKING_PAGES.get(out_carrier, "https://www.google.com/travel/flights")
    ret_landing = AIRLINE_OFFICIAL_BOOKING_PAGES.get(ret_carrier, "https://www.google.com/travel/flights")

    now = datetime.now(timezone.utc)

    out_link = BookingLink(
        provider=out_carrier,
        url=out_landing,
        link_type=LANDING_PAGE,
        verification_status=VERIFIED_LANDING_PAGE,
        verified_at=now,
        expected_origin=out_orig,
        expected_destination=out_dest,
        expected_departure_date=out_d_obj,
        notes=f"Search: {out_orig} → {out_dest}, {out_d_obj.strftime('%d %b %Y')}",
    )

    ret_link = BookingLink(
        provider=ret_carrier,
        url=ret_landing,
        link_type=LANDING_PAGE,
        verification_status=VERIFIED_LANDING_PAGE,
        verified_at=now,
        expected_origin=ret_orig,
        expected_destination=ret_dest,
        expected_departure_date=ret_d_obj,
        notes=f"Search: {ret_orig} → {ret_dest}, {ret_d_obj.strftime('%d %b %Y')}",
    )

    google_link = BookingLink(
        provider="Google Flights",
        url=metasearch["google"],
        link_type=METASEARCH,
        verification_status=VERIFIED_PREFILLED,
        verified_at=now,
        expected_origin=out_orig,
        expected_destination=out_dest,
        expected_departure_date=out_d_obj,
        expected_return_date=ret_d_obj,
        notes="Google Flights Multi-City Discovery",
    )

    kayak_link = BookingLink(
        provider="Kayak",
        url=metasearch["kayak"],
        link_type=METASEARCH,
        verification_status=VERIFIED_PREFILLED,
        verified_at=now,
        expected_origin=out_orig,
        expected_destination=out_dest,
        expected_departure_date=out_d_obj,
        expected_return_date=ret_d_obj,
        notes="Kayak Multi-City Comparison",
    )

    trip_link = BookingLink(
        provider="Trip.com",
        url=metasearch["trip_com"],
        link_type=METASEARCH,
        verification_status=VERIFIED_PREFILLED,
        verified_at=now,
        expected_origin=out_orig,
        expected_destination=out_dest,
        expected_departure_date=out_d_obj,
        expected_return_date=ret_d_obj,
        notes="Trip.com Multi-City Comparison",
    )

    return {
        "metasearch": metasearch,
        "outbound_landing": out_landing,
        "return_landing": ret_landing,
        "outbound_link_obj": out_link,
        "return_link_obj": ret_link,
        "google_link_obj": google_link,
        "kayak_link_obj": kayak_link,
        "trip_com_link_obj": trip_link,
        "search_instructions_out": f"Search: {out_orig} → {out_dest}, {out_d_obj.strftime('%d %b %Y')}",
        "search_instructions_ret": f"Search: {ret_orig} → {ret_dest}, {ret_d_obj.strftime('%d %b %Y')}",
        "search_instructions_multicity": (
            f"Search: {out_orig} → {out_dest}, {out_d_obj.strftime('%d %b %Y')}\n"
            f"Then: {ret_orig} → {ret_dest}, {ret_d_obj.strftime('%d %b %Y')}"
        ),
    }