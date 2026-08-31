"""Flight search provider URL builders and deep-link generators.

Builds parametric search URLs for 6 metasearch engines and 12 airline direct
booking portals.  All URLs are constructed from airport codes and dates only —
no PII, no credentials, no personal preferences are embedded.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# Metasearch URL builders
# ---------------------------------------------------------------------------

def _build_google_flights_url(
    *, out_orig: str, out_dest: str, out_date: str,
    ret_orig: str, ret_dest: str, ret_date: str,
) -> str:
    """Google Flights natural-language query URL."""
    return (
        f"https://www.google.com/travel/flights?q=Flights%20from%20{out_orig}"
        f"%20to%20{out_dest}%20on%20{out_date}%20through%20{ret_date}"
        f"%201%20adult%20currency%20GBP"
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
# Airline direct booking URLs
# ---------------------------------------------------------------------------

def _build_airline_direct_url(
    carrier: str, *, orig: str, dest: str, dep_date: str,
    ret_date: Optional[str] = None,
) -> tuple[str, str]:
    """Build a pre-filled airline booking URL.

    Returns (url, airline_label).
    """
    c = carrier.lower().strip()
    ret_param = f"&returnDate={ret_date}" if ret_date else ""

    if "oman air" in c or c in ("wy", "oman"):
        if ret_date:
            return (
                f"https://www.omanair.com/en/book?origin={orig}&destination={dest}"
                f"&departureDate={dep_date}&returnDate={ret_date}&adults=1",
                "Oman Air",
            )
        return (
            f"https://www.omanair.com/en/book?origin={orig}&destination={dest}"
            f"&departureDate={dep_date}&adults=1",
            "Oman Air",
        )

    if "air arabia" in c or c in ("g9", "airarabia"):
        if ret_date:
            return (
                f"https://www.airarabia.com/en/flight-booking?origin={orig}"
                f"&destination={dest}&departure_date={dep_date}"
                f"&return_date={ret_date}&adults=1",
                "Air Arabia",
            )
        return (
            f"https://www.airarabia.com/en/flight-booking?origin={orig}"
            f"&destination={dest}&departure_date={dep_date}&adults=1",
            "Air Arabia",
        )

    if "etihad" in c or c in ("ey", "etihad"):
        if ret_date:
            return (
                f"https://www.etihad.com/en-gb/book?origin={orig}&destination={dest}"
                f"&departureDate={dep_date}&returnDate={ret_date}&adults=1",
                "Etihad Airways",
            )
        return (
            f"https://www.etihad.com/en-gb/book?origin={orig}&destination={dest}"
            f"&departureDate={dep_date}&adults=1",
            "Etihad Airways",
        )

    if "emirates" in c or c in ("ek", "emirates"):
        if ret_date:
            return (
                f"https://www.emirates.com/uk/english/book/?destination={dest}"
                f"&departureDate={dep_date}&returnDate={ret_date}"
                f"&origin={orig}&adults=1",
                "Emirates",
            )
        return (
            f"https://www.emirates.com/uk/english/book/?destination={dest}"
            f"&departureDate={dep_date}&origin={orig}&adults=1",
            "Emirates",
        )

    if "british airways" in c or c in ("ba", "british"):
        if ret_date:
            return (
                f"https://www.britishairways.com/travel/fx/public/en_gb"
                f"?origin={orig}&destination={dest}&departureDate={dep_date}"
                f"&returnDate={ret_date}&adults=1",
                "British Airways",
            )
        return (
            f"https://www.britishairways.com/travel/fx/public/en_gb"
            f"?origin={orig}&destination={dest}&departureDate={dep_date}"
            f"&adults=1",
            "British Airways",
        )

    if "pegasus" in c or c in ("pc", "pegasus"):
        if ret_date:
            return (
                f"https://www.flypgs.com/en/booking?departureAirport={orig}"
                f"&arrivalAirport={dest}&departureDate={dep_date}"
                f"&returnDate={ret_date}&adultCount=1",
                "Pegasus",
            )
        return (
            f"https://www.flypgs.com/en/booking?departureAirport={orig}"
            f"&arrivalAirport={dest}&departureDate={dep_date}&adultCount=1",
            "Pegasus",
        )

    if "flydubai" in c or c in ("fz", "flydubai"):
        return (
            f"https://www.flydubai.com/en/booking?origin={orig}&destination={dest}"
            f"&departureDate={dep_date}&adults=1",
            "Flydubai",
        )

    if "salam" in c or c in ("ov", "salam"):
        return (
            f"https://www.salamair.com/en/book?origin={orig}&destination={dest}"
            f"&departureDate={dep_date}&adults=1",
            "SalamAir",
        )

    if "ajet" in c or c in ("vf", "ajet"):
        return (
            f"https://www.ajet.com/en/book?origin={orig}&destination={dest}"
            f"&departureDate={dep_date}&adultCount=1",
            "AJet",
        )

    if "turkish" in c or c in ("tk", "turkish"):
        return (
            f"https://www.turkishairlines.com/en-int/flights/booking/"
            f"?origin={orig}&destination={dest}&departureDate={dep_date}"
            f"&adultCount=1",
            "Turkish Airlines",
        )

    if "qatar" in c or c in ("qr", "qatar"):
        return (
            f"https://www.qatarairways.com/en-gb/book?origin={orig}"
            f"&destination={dest}&departureDate={dep_date}&adults=1",
            "Qatar Airways",
        )

    # Fallback to Google Flights
    return (
        f"https://www.google.com/travel/flights?q=Flights%20from%20{orig}"
        f"%20to%20{dest}%20on%20{dep_date}%201%20adult%20currency%20GBP",
        carrier or "Airline Direct",
    )


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
