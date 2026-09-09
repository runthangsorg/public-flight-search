"""Flight search provider URL builders and deep-link generators.

Builds parametric search URLs for metasearch engines and verified airline
direct booking portals. Google Flights links use the structured `tfs=`
format (the legacy `?q=` natural-language and `#flt=` hash formats land on
the generic homepage and are never emitted). Airline links are verified
official landing pages with a search brief — never speculative prefilled
`?origin=` deep links, which 404 or strip parameters. All URLs embed only
airport codes and dates — no PII, no credentials.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# Verified airline official booking portals (landing pages, not speculative
# prefilled deep links). Mirrors booking_links.AIRLINE_OFFICIAL_BOOKING_PAGES.
AIRLINE_OFFICIAL_PORTALS: dict[str, str] = {
    "etihad airways": "https://www.etihad.com/en-gb",
    "oman air": "https://www.omanair.com/en",
    "air arabia": "https://www.airarabia.com/en",
    "pegasus": "https://www.flypgs.com/en",
    "wizz air": "https://wizzair.com/en-gb",
    "wizz air uk": "https://wizzair.com/en-gb",
    "emirates": "https://www.emirates.com/uk/english/",
    "flydubai": "https://www.flydubai.com/en",
    "salamair": "https://www.salamair.com/en",
    "turkish airlines": "https://www.turkishairlines.com/en-gb/",
    "ajet": "https://ajet.com/en",
    "british airways": "https://www.britishairways.com/travel/fx/public/en_gb",
    "qatar airways": "https://www.qatarairways.com/en-gb/homepage.html",
    "saudia": "https://www.saudia.com/pages/booking",
    "gulf air": "https://www.gulfair.com/",
    "royal jordanian": "https://www.rj.com/",
    "easyjet": "https://www.easyjet.com/en/",
    "jet2": "https://www.jet2.com/",
    "ryanair": "https://www.ryanair.com/gb/en",
    "tui airways": "https://www.tui.co.uk/flights/",
}

# IATA code -> portal key, so "EK"/"EY"/"BA" resolve without guessing URLs.
_CARRIER_CODE_TO_PORTAL: dict[str, str] = {
    "EY": "etihad airways", "WY": "oman air", "G9": "air arabia",
    "PC": "pegasus", "W6": "wizz air", "W9": "wizz air uk",
    "EK": "emirates", "FZ": "flydubai", "OV": "salamair",
    "TK": "turkish airlines", "VF": "ajet", "BA": "british airways",
    "QR": "qatar airways", "SV": "saudia", "GF": "gulf air",
    "RJ": "royal jordanian", "U2": "easyjet", "LS": "jet2",
    "FR": "ryanair", "BY": "tui airways",
}


# ---------------------------------------------------------------------------
# Metasearch URL builders
# ---------------------------------------------------------------------------

def _build_google_flights_url(
    *, out_orig: str, out_dest: str, out_date: str,
    ret_orig: str, ret_dest: str, ret_date: str,
    travellers: int = 1,
) -> str:
    """Google Flights structured multi-city search URL (`tfs=`).

    Delegates to google_flights.build_google_flights_multicity_url so every
    Google link in every report shares one verified encoder.
    """
    from .google_flights import build_google_flights_multicity_url

    return build_google_flights_multicity_url(
        out_orig=out_orig, out_dest=out_dest, out_date=out_date,
        ret_orig=ret_orig, ret_dest=ret_dest, ret_date=ret_date,
        travellers=travellers,
    )


def _build_kayak_url(
    *, out_orig: str, out_dest: str, out_date: str,
    ret_orig: str, ret_dest: str, ret_date: str,
) -> str:
    """Kayak roundtrip or multi-city URL."""
    if out_orig == ret_dest and out_dest == ret_orig:
        return f"https://www.kayak.co.uk/flights/{out_orig}-{out_dest}/{out_date}/{ret_date}/1adults?sort=bestflight_a"
    return (
        f"https://www.kayak.co.uk/flights/{out_orig}-{out_dest}/{out_date}"
        f"/{ret_orig}-{ret_dest}/{ret_date}/1adults?sort=bestflight_a"
    )


def _build_skyscanner_url(
    *, out_orig: str, out_dest: str, out_date: str,
    ret_orig: str, ret_dest: str, ret_date: str,
) -> str:
    """Skyscanner URL with YYMMDD date format."""
    out_yymmdd = out_date.replace("-", "")[2:]
    ret_yymmdd = ret_date.replace("-", "")[2:]
    if out_orig == ret_dest and out_dest == ret_orig:
        return (
            f"https://www.skyscanner.net/transport/flights/{out_orig.lower()}"
            f"/{out_dest.lower()}/{out_yymmdd}/{ret_yymmdd}/"
            f"?adultsv2=1&cabinclass=economy&rtn=1"
        )
    return (
        f"https://www.skyscanner.net/transport/flights/{out_orig.lower()}"
        f"/{out_dest.lower()}/{out_yymmdd}/{ret_orig.lower()}"
        f"/{ret_dest.lower()}/{ret_yymmdd}/"
        f"?adultsv2=1&cabinclass=economy&rtn=1"
    )


def _build_trip_com_url(
    *, out_orig: str, out_dest: str, out_date: str,
    ret_orig: str, ret_dest: str, ret_date: str,
) -> str:
    """Trip.com roundtrip or multi-city URL."""
    if out_orig == ret_dest and out_dest == ret_orig:
        return (
            f"https://uk.trip.com/flights/showresult?dcity={out_orig}"
            f"&acity={out_dest}&ddate={out_date}&rdate={ret_date}"
            f"&flighttype=rt&class=y&quantity=1"
        )
    return (
        f"https://uk.trip.com/flights/showresult?flighttype=mt"
        f"&dcity1={out_orig}&acity1={out_dest}&ddate1={out_date}"
        f"&dcity2={ret_orig}&acity2={ret_dest}&ddate2={ret_date}"
        f"&class=y&quantity=1"
    )


def _build_momondo_url(
    *, out_orig: str, out_dest: str, out_date: str,
    ret_orig: str, ret_dest: str, ret_date: str,
) -> str:
    """Momondo roundtrip or multi-city URL."""
    if out_orig == ret_dest and out_dest == ret_orig:
        return (
            f"https://www.momondo.co.uk/flight-search/{out_orig}-{out_dest}"
            f"/{out_date}/{ret_date}?sort=bestflight_a"
        )
    return (
        f"https://www.momondo.co.uk/flight-search/{out_orig}-{out_dest}"
        f"/{out_date}/{ret_orig}-{ret_dest}/{ret_date}?sort=bestflight_a"
    )


def _build_gotogate_url(
    *, out_orig: str, out_dest: str, out_date: str,
    ret_orig: str, ret_dest: str, ret_date: str,
) -> str:
    """GoToGate roundtrip URL."""
    return (
        f"https://www.gotogate.co.uk/flights/{out_orig.upper()}-{out_dest.upper()}"
        f"/{out_date}/{ret_orig.upper()}-{ret_dest.upper()}/{ret_date}"
        f"?adults=1&cabin=ECONOMY"
    )


# ---------------------------------------------------------------------------
# Airline direct booking URLs (verified landing pages only)
# ---------------------------------------------------------------------------

def _resolve_airline_portal(carrier: str) -> tuple[str, str]:
    """Resolve a carrier name/code to (portal_url, airline_label).

    Speculative prefilled `?origin=` deep links 404 or strip parameters on
    every major airline booking engine (verified live 2026-09-07/08), so we
    link the verified official portal and let the reader enter the exact
    route/dates shown beside the button. Never emits a guessed query string.
    """
    raw = (carrier or "").strip()
    c = raw.lower()
    if not c:
        return "", ""
    # Direct IATA code match first.
    portal_key = _CARRIER_CODE_TO_PORTAL.get(raw.upper().strip())
    label = ""
    if portal_key:
        label = portal_key.title() if portal_key not in (
            "etihad airways", "oman air", "air arabia", "turkish airlines",
            "british airways", "qatar airways", "royal jordanian",
        ) else {
            "etihad airways": "Etihad Airways", "oman air": "Oman Air",
            "air arabia": "Air Arabia", "turkish airlines": "Turkish Airlines",
            "british airways": "British Airways",
            "qatar airways": "Qatar Airways",
            "royal jordanian": "Royal Jordanian",
        }[portal_key]
        return AIRLINE_OFFICIAL_PORTALS[portal_key], label
    # Substring match on full names.
    for key, url in AIRLINE_OFFICIAL_PORTALS.items():
        if key in c or c in key:
            pretty = {
                "etihad airways": "Etihad Airways", "oman air": "Oman Air",
                "air arabia": "Air Arabia", "pegasus": "Pegasus",
                "wizz air": "Wizz Air", "wizz air uk": "Wizz Air UK",
                "emirates": "Emirates", "flydubai": "Flydubai",
                "salamair": "SalamAir",
                "turkish airlines": "Turkish Airlines", "ajet": "AJet",
                "british airways": "British Airways",
                "qatar airways": "Qatar Airways", "saudia": "Saudia",
                "gulf air": "Gulf Air",
                "royal jordanian": "Royal Jordanian",
                "easyjet": "easyJet", "jet2": "Jet2",
                "ryanair": "Ryanair", "tui airways": "TUI Airways",
            }.get(key, key.title())
            return url, pretty
    return "", ""


def _build_airline_direct_url(
    carrier: str, *, orig: str, dest: str, dep_date: str,
    ret_date: Optional[str] = None,
) -> tuple[str, str]:
    """Return the verified official portal for a carrier.

    Returns (url, airline_label). Falls back to a structured Google Flights
    search when the carrier is unknown, so every emitted link resolves.
    The orig/dest/dep_date/ret_date args are kept for call-site
    compatibility and are rendered as a search brief beside the button —
    never embedded as guessed query parameters.
    """
    url, label = _resolve_airline_portal(carrier)
    if url:
        return url, label
    # Fallback to Google Flights structured search (one-way leg).
    from .google_flights import build_google_flights_url

    try:
        fallback = build_google_flights_url(
            origin=orig, destination=dest, date=dep_date,
            travellers=1, cabin_class="ECONOMY",
        )
    except ValueError:
        fallback = "https://www.google.com/travel/flights/search?curr=GBP&hl=en-GB"
    return fallback, carrier.strip() or "Airline Direct"


# ---------------------------------------------------------------------------
# Aggregated provider URL builder
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProviderURLs:
    """All provider URLs for a single itinerary."""
    google: str
    kayak: str
    skyscanner: str
    trip_com: str
    momondo: str
    gotogate: str
    airline_outbound: str
    airline_return: str
    airline_name: str
    airline_return_name: str
    is_roundtrip: bool


def build_all_provider_urls(
    *,
    out_orig: str,
    out_dest: str,
    out_date: str,
    ret_orig: str,
    ret_dest: str,
    ret_date: str,
    carrier: str = "",
    outbound_carrier: str = "",
    inbound_carrier: str = "",
) -> ProviderURLs:
    """Build search URLs for all supported providers.

    No PII is embedded — only airport codes, dates, and optional carrier.
    """
    out_o = out_orig.upper().strip()
    out_d = out_dest.upper().strip()
    ret_o = ret_orig.upper().strip()
    ret_d = ret_dest.upper().strip()

    is_roundtrip = (out_o == ret_d and out_d == ret_o)

    google = _build_google_flights_url(
        out_orig=out_o, out_dest=out_d, out_date=out_date,
        ret_orig=ret_o, ret_dest=ret_d, ret_date=ret_date,
    )
    kayak = _build_kayak_url(
        out_orig=out_o, out_dest=out_d, out_date=out_date,
        ret_orig=ret_o, ret_dest=ret_d, ret_date=ret_date,
    )
    skyscanner = _build_skyscanner_url(
        out_orig=out_o, out_dest=out_d, out_date=out_date,
        ret_orig=ret_o, ret_dest=ret_d, ret_date=ret_date,
    )
    trip_com = _build_trip_com_url(
        out_orig=out_o, out_dest=out_d, out_date=out_date,
        ret_orig=ret_o, ret_dest=ret_d, ret_date=ret_date,
    )
    momondo = _build_momondo_url(
        out_orig=out_o, out_dest=out_d, out_date=out_date,
        ret_orig=ret_o, ret_dest=ret_d, ret_date=ret_date,
    )
    gotogate = _build_gotogate_url(
        out_orig=out_o, out_dest=out_d, out_date=out_date,
        ret_orig=ret_o, ret_dest=ret_d, ret_date=ret_date,
    )

    out_carrier = (outbound_carrier or carrier or "").strip()
    ret_carrier = (inbound_carrier or carrier or "").strip()

    out_direct, out_name = _build_airline_direct_url(
        out_carrier, orig=out_o, dest=out_d, dep_date=out_date,
        ret_date=ret_date if is_roundtrip else None,
    )
    ret_direct, ret_name = _build_airline_direct_url(
        ret_carrier, orig=ret_o, dest=ret_d, dep_date=ret_date,
    )

    return ProviderURLs(
        google=google,
        kayak=kayak,
        skyscanner=skyscanner,
        trip_com=trip_com,
        momondo=momondo,
        gotogate=gotogate,
        airline_outbound=out_direct,
        airline_return=ret_direct,
        airline_name=out_name,
        airline_return_name=ret_name,
        is_roundtrip=is_roundtrip,
    )


# ---------------------------------------------------------------------------
# Provider coverage model
# ---------------------------------------------------------------------------

ACTIVE_PROVIDER_COVERAGE = {
    "live_priced_results": ("Google Flights",),
    "manual_discovery_links": (
        "Kayak",
        "Skyscanner",
        "Trip.com",
        "Momondo",
        "GoToGate",
        "direct-airline portals",
    ),
    "not_live": (
        "Opodo",
        "lastminute.com",
        "Expedia",
    ),
}


def render_provider_coverage_notice() -> str:
    """HTML notice distinguishing live prices from manual discovery links."""
    manual = ", ".join(ACTIVE_PROVIDER_COVERAGE["manual_discovery_links"])
    inactive = ", ".join(ACTIVE_PROVIDER_COVERAGE["not_live"])
    return (
        '<section data-provider-coverage="active" '
        'style="margin:16px 0;padding:12px;border:1px solid #475569;'
        'border-radius:8px;background:#0f172a;color:#cbd5e1;font-size:12px;'
        'line-height:1.5">'
        '<strong style="color:#f8fafc">Provider coverage:</strong> '
        "Only Google Flights supplies live priced results. "
        f"{manual} are manual discovery links only; "
        "they are not checked/current prices. "
        f"{inactive} are not queried live.</section>"
    )
