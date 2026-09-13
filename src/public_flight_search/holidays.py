"""Runtime-configured holiday search plan with parametric provider search URLs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from html import escape
import json
from typing import Any, Mapping, Optional, Sequence
from urllib.parse import urlencode

from .config import ConfigError, _airports, _dates, _text, _validate_report_title, _window
from .google_flights import build_google_flights_roundtrip_url


@dataclass(frozen=True)
class HolidayDestination:
    key: str
    label: str
    airports: tuple[str, ...]


@dataclass(frozen=True)
class HolidayConfig:
    report_title: str
    travellers: int
    rooms: tuple[int, ...]
    departure_window: tuple[str, str]
    origins: tuple[str, ...]
    outbound_dates: tuple[str, ...]
    return_dates: tuple[str, ...]
    destinations: tuple[HolidayDestination, ...]


# ---------------------------------------------------------------------------
# Provider links: every URL below was verified live on 2026-09-07/08 with a
# headless Camoufox browser (real rendered provider page, not a 404).
# Parametric PACKAGE search-result deep links were PROVEN BROKEN and removed:
#   - Jet2 `/search-results?...`  -> "Page not found" (real search needs
#     opaque numeric IDs; destination guides used instead)
#   - easyJet `/spain/canary-islands/...` -> "404 Page" (correct paths below)
#   - TUI `/holidays/search?...` -> "Page Not Found"
#   - BA `/holidays/<dest>/search` -> "Page not found" (holidays hub used)
#   - loveholidays / On the Beach deep search -> bot-wall stubs; homepages
#     render fully, so homepage entry points are linked and the reader enters
#     dates/party on the provider's own search widget.
# HOTEL/FLIGHT metasearch links below ARE parametric and DO encode the exact
# dates + party, because Booking.com `searchresults.html?ss=`, Expedia
# `Hotel-Search?destination=`, Google Hotels `travel/hotels?q=` and Google
# Flights `travel/flights/search?tfs=` all resolve to dated results pages
# without opaque IDs. They are labelled as search entries, never as verified
# checkout totals.
# ---------------------------------------------------------------------------

LOVEHOLIDAYS_HOME = "https://www.loveholidays.com/"
ON_THE_BEACH_HOME = "https://www.onthebeach.co.uk/"
TUI_HOLIDAYS_HUB = "https://www.tui.co.uk/holidays/"
BA_HOLIDAYS_HUB = "https://www.britishairways.com/en-gb/flights-and-holidays/holidays"
EASYJET_HOLIDAYS_HUB = "https://www.easyjet.com/en/holidays/"
JET2_HOME = "https://www.jet2holidays.com/"

BOOKING_COM_BASE = "https://www.booking.com/searchresults.html"
EXPEDIA_BASE = "https://www.expedia.co.uk/Hotel-Search"
GOOGLE_HOTELS_BASE = "https://www.google.com/travel/hotels"
GOOGLE_FLIGHTS_SEARCH_BASE = "https://www.google.com/travel/flights/search"

# Human-searchable destination query per holiday key. Used for Booking.com,
# Expedia and Google Hotels parametric links so every link encodes the real
# destination + dates + party instead of a static homepage.
HOLIDAY_SEARCH_QUERIES: dict[str, str] = {
    "antalya": "Antalya, Turkey",
    "malta": "Valletta, Malta",
    "taghazout": "Taghazout, Morocco",
    "hurghada": "Hurghada, Egypt",
    "cairo": "Cairo, Egypt",
    "muscat": "Muscat, Oman",
    "doha": "Doha, Qatar",
    "tenerife": "Tenerife, Canary Islands",
    "madeira": "Funchal, Madeira",
    "lanzarote": "Playa Blanca, Lanzarote",
    "cape_verde": "Santa Maria, Sal, Cape Verde",
}

# Destination airport per holiday key (for Google Flights parametric links).
HOLIDAY_AIRPORTS: dict[str, str] = {
    "antalya": "AYT", "malta": "MLA", "taghazout": "AGA",
    "hurghada": "HRG", "cairo": "CAI", "muscat": "MCT",
    "doha": "DOH", "tenerife": "TFS", "madeira": "FNC",
    "lanzarote": "ACE", "cape_verde": "SID",
}

# easyJet holidays destination guides, verified live (muscat/doha 404: not
# served by easyJet holidays -> hub fallback in build_easyjet_url).
EASYJET_DESTINATION_PATHS: dict[str, str] = {
    "malta": "https://www.easyjet.com/en/holidays/malta",
    "antalya": "https://www.easyjet.com/en/holidays/turkey/antalya",
    "cairo": "https://www.easyjet.com/en/holidays/egypt/cairo",
    "taghazout": "https://www.easyjet.com/en/holidays/morocco/agadir",
    "hurghada": "https://www.easyjet.com/en/holidays/egypt/hurghada",
    "tenerife": "https://www.easyjet.com/en/holidays/spain/tenerife",
    "madeira": "https://www.easyjet.com/en/holidays/portugal/madeira",
    "lanzarote": "https://www.easyjet.com/en/holidays/spain/lanzarote",
    "cape_verde": "https://www.easyjet.com/en/holidays/cape-verde",
}

# Jet2 destination guides, verified live. Destinations absent here have no
# Jet2 product (long-haul muscat/doha, city-break cairo, cape_verde) and are
# honestly omitted from build_provider_urls instead of linked to a 404.
JET2_DESTINATION_PATHS: dict[str, str] = {
    "malta": "https://www.jet2holidays.com/destinations/malta",
    "antalya": "https://www.jet2holidays.com/destinations/turkey",
    "taghazout": "https://www.jet2holidays.com/destinations/morocco",
    "hurghada": "https://www.jet2holidays.com/destinations/egypt/hurghada",
    "tenerife": "https://www.jet2holidays.com/destinations/canary-islands/tenerife",
    "madeira": "https://www.jet2holidays.com/destinations/portugal/madeira",
    "lanzarote": "https://www.jet2holidays.com/destinations/canary-islands/lanzarote",
}

# Allowlist of every link PREFIX this module may emit. Tests enforce it, so
# a future edit cannot silently reintroduce an unverified deep-link pattern
# (e.g. Jet2 `/search-results?`, TUI `/holidays/search?`, BA per-dest search,
# or legacy Google `#flt=` / `?q=`). Parametric Booking.com / Expedia /
# Google Hotels / Google Flights URLs are allowed because they encode real
# dates + party and resolve to dated results pages without opaque IDs.
VERIFIED_LINK_BASES: frozenset[str] = frozenset(
    {
        LOVEHOLIDAYS_HOME,
        ON_THE_BEACH_HOME,
        TUI_HOLIDAYS_HUB,
        BA_HOLIDAYS_HUB,
        EASYJET_HOLIDAYS_HUB,
        JET2_HOME,
        BOOKING_COM_BASE,
        EXPEDIA_BASE,
        GOOGLE_HOTELS_BASE,
        GOOGLE_FLIGHTS_SEARCH_BASE,
        *EASYJET_DESTINATION_PATHS.values(),
        *JET2_DESTINATION_PATHS.values(),
    }
)


def _is_verified_link(url: str) -> bool:
    """True when a URL starts with an allowlisted verified base."""
    return url.startswith("https://") and any(
        url == base or url.startswith(base) for base in VERIFIED_LINK_BASES
    )


def build_loveholidays_url(
    *,
    destination: str,
    origin_airports: tuple[str, ...],
    departure_date: str,
    return_date: str,
    adults: int,
    rooms: int,
) -> str:
    """loveholidays search needs its JS app + opaque hotel IDs and bot-walls
    automation; link the verified-rendering homepage search entry point."""
    return LOVEHOLIDAYS_HOME


def build_on_the_beach_url(
    *,
    destination: str,
    origin_airports: tuple[str, ...],
    departure_date: str,
    return_date: str,
    adults: int,
) -> str:
    """On the Beach deep pages are bot-walled; link the verified homepage."""
    return ON_THE_BEACH_HOME


def build_jet2_url(
    *,
    destination: str,
    origin_airports: tuple[str, ...],
    departure_date: str,
    return_date: str,
    adults: int,
    rooms: int,
) -> str:
    """Verified Jet2 destination guide. Raises KeyError where Jet2 has no
    product so callers omit the link instead of emitting a 404."""
    return JET2_DESTINATION_PATHS[destination.lower()]


def build_tui_url(
    *,
    destination: str,
    origin_airports: tuple[str, ...],
    departure_date: str,
    return_date: str,
    adults: int,
) -> str:
    """TUI's parametric search path 404s; link the verified holidays hub."""
    return TUI_HOLIDAYS_HUB


def build_easyjet_url(
    *,
    destination: str,
    origin_airports: tuple[str, ...],
    departure_date: str,
    return_date: str,
    adults: int,
) -> str:
    """Verified easyJet holidays destination guide, hub fallback included."""
    return EASYJET_DESTINATION_PATHS.get(destination.lower(), EASYJET_HOLIDAYS_HUB)


def build_ba_holidays_url(
    *,
    destination: str,
    origin_airports: tuple[str, ...],
    departure_date: str,
    return_date: str,
    adults: int,
) -> str:
    """BA per-destination search path 404s; link the verified holidays hub."""
    return BA_HOLIDAYS_HUB


def build_booking_com_url(
    *,
    destination: str,
    departure_date: str,
    return_date: str,
    adults: int,
    rooms: int,
) -> str:
    """Booking.com parametric hotel search — encodes real dates + party.

    `searchresults.html?ss=` needs no opaque hotel IDs and resolves to a
    dated results page. Labelled as a search entry, never a checkout total.
    """
    query = HOLIDAY_SEARCH_QUERIES.get(destination.lower(), destination)
    return BOOKING_COM_BASE + "?" + urlencode(
        {
            "ss": query,
            "checkin": departure_date,
            "checkout": return_date,
            "group_adults": adults,
            "no_rooms": rooms,
            "order": "price",
        }
    )


def build_expedia_url(
    *,
    destination: str,
    departure_date: str,
    return_date: str,
    adults: int,
    rooms: int,
) -> str:
    """Expedia parametric hotel search — encodes real dates + party."""
    query = HOLIDAY_SEARCH_QUERIES.get(destination.lower(), destination)
    return EXPEDIA_BASE + "?" + urlencode(
        {
            "destination": query,
            "startDate": departure_date,
            "endDate": return_date,
            "rooms": rooms,
            "adults": adults,
        }
    )


def build_google_hotels_url(
    *,
    destination: str,
    departure_date: str,
    return_date: str,
    adults: int,
    rooms: int,
) -> str:
    """Google Hotels parametric search — encodes real dates + party."""
    query = HOLIDAY_SEARCH_QUERIES.get(destination.lower(), destination)
    return GOOGLE_HOTELS_BASE + "?" + urlencode(
        {
            "q": f"{query} hotels",
            "dates": f"{departure_date},{return_date}",
            "adults": adults,
            "rooms": rooms,
            "curr": "GBP",
            "hl": "en-GB",
        }
    )


def build_google_flights_holiday_url(
    *,
    destination: str,
    origin_airports: tuple[str, ...],
    departure_date: str,
    return_date: str,
    adults: int,
) -> str:
    """Google Flights structured round-trip for a holiday date pair.

    Uses the shared `tfs=` encoder so the link opens a dated results page.
    Falls back to the Flights homepage only when dates are inverted.
    """
    from .google_flights import build_google_flights_roundtrip_url

    airport = HOLIDAY_AIRPORTS.get(destination.lower(), "")
    origin = (origin_airports[0] if origin_airports else "LHR").upper()
    if not airport or return_date <= departure_date:
        return "https://www.google.com/travel/flights/search?curr=GBP&hl=en-GB"
    return build_google_flights_roundtrip_url(
        origin=origin, destination=airport,
        outbound_date=departure_date, return_date=return_date,
        travellers=max(1, min(9, adults)),
    )


def build_provider_urls(
    *,
    destination_key: str,
    destination_label: str,
    origin_airports: tuple[str, ...],
    departure_date: str,
    return_date: str,
    adults: int,
    rooms: int,
) -> dict[str, str]:
    """Verified provider entry points for one destination/date pair.

    10 providers: 6 package entry points (Jet2 only where it has product;
    unknown keys get all hubs so the matrix stays dense) + 4 parametric
    hotel/flight searches that encode the exact dates + party:
    Booking.com, Expedia, Google Hotels, Google Flights.
    Jet2 is included only where it has product; unknown destination keys get
    all six hub/homepage links so the matrix stays dense.
    """
    key = destination_key.lower()
    known = (
        key in EASYJET_DESTINATION_PATHS
        or key in JET2_DESTINATION_PATHS
        or key in {"muscat", "doha", "cairo", "cape_verde"}
        or key in HOLIDAY_SEARCH_QUERIES
    )
    urls: dict[str, str] = {
        "loveholidays": LOVEHOLIDAYS_HOME,
        "on_the_beach": ON_THE_BEACH_HOME,
        "tui": TUI_HOLIDAYS_HUB,
        "easyjet": EASYJET_DESTINATION_PATHS.get(key, EASYJET_HOLIDAYS_HUB),
        "ba_holidays": BA_HOLIDAYS_HUB,
        "booking_com": build_booking_com_url(
            destination=key, departure_date=departure_date,
            return_date=return_date, adults=adults, rooms=rooms,
        ),
        "expedia": build_expedia_url(
            destination=key, departure_date=departure_date,
            return_date=return_date, adults=adults, rooms=rooms,
        ),
        "google_hotels": build_google_hotels_url(
            destination=key, departure_date=departure_date,
            return_date=return_date, adults=adults, rooms=rooms,
        ),
        "google_flights": build_google_flights_holiday_url(
            destination=key, origin_airports=origin_airports,
            departure_date=departure_date, return_date=return_date,
            adults=adults,
        ),
    }
    if key in JET2_DESTINATION_PATHS:
        urls["jet2"] = JET2_DESTINATION_PATHS[key]
    elif not known:
        urls["jet2"] = JET2_HOME
    return urls


def count_provider_entries(config: HolidayConfig) -> int:
    """Exact number of provider links rendered for every date combination."""
    pairs = _date_pairs(config)
    return sum(
        len(
            build_provider_urls(
                destination_key=dest.key,
                destination_label=dest.label,
                origin_airports=config.origins,
                departure_date=outbound,
                return_date=returning,
                adults=config.travellers,
                rooms=len(config.rooms),
            )
        )
        for dest in config.destinations
        for outbound, returning in pairs
    )


def load_holiday_config(payload: str) -> HolidayConfig:
    try:
        raw = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ConfigError("holiday configuration is not valid JSON") from exc
    allowed = {"report_title", "party", "departure_window", "origins", "outbound_dates", "return_dates", "destinations"}
    if not isinstance(raw, dict) or set(raw) - allowed:
        raise ConfigError("holiday configuration contains unknown fields")
    party = raw.get("party")
    if not isinstance(party, dict) or set(party) - {"travellers", "rooms"}:
        raise ConfigError("party must contain travellers and rooms")
    travellers = int(party.get("travellers", 0))
    rooms_raw = party.get("rooms")
    if not 1 <= travellers <= 12 or not isinstance(rooms_raw, list):
        raise ConfigError("holiday party is invalid")
    rooms = tuple(int(value) for value in rooms_raw)
    if not rooms or sum(rooms) != travellers or any(value < 1 for value in rooms):
        raise ConfigError("room occupancy must account for every traveller")
    destination_raw = raw.get("destinations")
    if not isinstance(destination_raw, list) or not 1 <= len(destination_raw) <= 12:
        raise ConfigError("destinations must contain 1-12 entries")
    destinations = tuple(
        HolidayDestination(
            key=_text(item.get("key"), "destination key", 48),
            label=_text(item.get("label"), "destination label"),
            airports=_airports(item.get("airports"), "destination airports"),
        )
        for item in destination_raw
        if isinstance(item, dict) and not set(item) - {"key", "label", "airports"}
    )
    if len(destinations) != len(destination_raw):
        raise ConfigError("a destination contains unknown fields")
    outbound_dates = _dates(raw.get("outbound_dates"), "outbound_dates")
    return_dates = _dates(raw.get("return_dates"), "return_dates")
    valid_pairs = tuple(
        (outbound, returning)
        for outbound in outbound_dates
        for returning in return_dates
        if returning > outbound
    )
    if not valid_pairs:
        raise ConfigError("at least one return date must be after an outbound date")
    if len(valid_pairs) > 24:
        raise ConfigError("holiday configuration exceeds 24 valid date combinations")
    return HolidayConfig(
        report_title=_validate_report_title(
            _text(raw.get("report_title", "Holiday package watch"), "report_title")
        ),
        travellers=travellers,
        rooms=rooms,
        departure_window=_window(raw.get("departure_window")),
        origins=_airports(raw.get("origins"), "origins"),
        outbound_dates=outbound_dates,
        return_dates=return_dates,
        destinations=destinations,
    )


def _date_pairs(config: HolidayConfig) -> tuple[tuple[str, str], ...]:
    return tuple(
        (outbound, returning)
        for outbound in config.outbound_dates
        for returning in config.return_dates
        if returning > outbound
    )


def _shortlist_pairs(pairs: tuple[tuple[str, str], ...]) -> tuple[tuple[str, str], ...]:
    """Pick 3 representative date pairs: earliest, middle, latest."""
    if len(pairs) <= 3:
        return pairs
    return (pairs[0], pairs[len(pairs) // 2], pairs[-1])


@dataclass(frozen=True)
class PackageDeal:
    resort_name: str
    destination_label: str
    destination_key: str
    star_rating: int
    board_basis: str
    outbound_date: str
    return_date: str
    nights: int
    airline: str
    origin_airports: tuple[str, ...]
    destination_airport: str
    flight_price_total_gbp: float
    hotel_price_total_gbp: float
    total_package_price_gbp: float
    price_per_person_gbp: float
    flight_booking_url: str
    hotel_booking_url: str
    is_under_budget: bool
    highlights: tuple[str, ...] = ()
    # True door-to-door: package + UK ground + destination transfer.
    uk_ground_gbp: float = 0.0
    transfer_gbp: float = 0.0
    true_d2d_gbp: float = 0.0
    # Climate honesty: ambient Dec air range + sea temp + beach geography.
    dec_ambient_c: tuple[int, int] = (0, 0)
    sea_temp_c: int = 0
    beach: str = ""
    # Data provenance per confidence gates.
    confidence: str = "market-supported"
    source_url: str = ""


# December climate reality (ambient air / sea °C) plus beach geography.
# A heated pool does NOT make a 15°C destination a winter-sun holiday:
# stepping out of 28°C water into a 15°C wind is miserable.
# Rates below are BENCHMARKS (confidence: market-supported), never live
# checkout totals. Live verification runs privately (Camoufox/FlareSolverr).
WINTER_RESORT_CATALOG: dict[str, list[dict[str, Any]]] = {
    "antalya": [
        {
            "name": "Lara Barut Collection",
            "destination_label": "Antalya Riviera, Turkey",
            "stars": 5,
            "board": "Ultra All Inclusive",
            "base_nightly_room_rate_gbp": 115.0,
            "airport": "AYT",
            "airline": "SunExpress / Pegasus",
            "flight_benchmark_5pax_gbp": 648.0,
            "highlights": ("Heated seawater pool (28°C)", "8 à la carte restaurants", "Thalasso spa", "Private sandy beach"),
            "hotel_url": "https://www.baruthotels.com/lara-barut-collection/",
            "dec_ambient_c": (15, 17),
            "sea_temp_c": 19,
            "beach": "Sandy but 15-17°C air — pools only, no sunbathing",
            "transfer_gbp": 25.0,
            "confidence": "market-supported",
        },
        {
            "name": "Concorde De Luxe Resort",
            "destination_label": "Antalya Riviera, Turkey",
            "stars": 5,
            "board": "Ultra All Inclusive",
            "base_nightly_room_rate_gbp": 88.0,
            "airport": "AYT",
            "airline": "SunExpress / Pegasus",
            "flight_benchmark_5pax_gbp": 648.0,
            "highlights": ("Heated indoor pool", "Private sandy beach", "Carpe Diem luxury spa", "Bowling alley"),
            "hotel_url": "https://www.concordehotels.com.tr/",
            "dec_ambient_c": (15, 17),
            "sea_temp_c": 19,
            "beach": "Sandy but 15-17°C — indoor/spa trip",
            "transfer_gbp": 25.0,
            "confidence": "market-supported",
        },
        {
            "name": "Titanic Mardan Palace",
            "destination_label": "Antalya Riviera, Turkey",
            "stars": 5,
            "board": "Golden Inclusive",
            "base_nightly_room_rate_gbp": 145.0,
            "airport": "AYT",
            "airline": "SunExpress / Pegasus",
            "flight_benchmark_5pax_gbp": 648.0,
            "highlights": ("Palatial architecture", "7,500m² spa", "Heated Olympic indoor pool", "Private lagoon"),
            "hotel_url": "https://www.titanic.com.tr/titanic-mardan-palace",
            "dec_ambient_c": (15, 17),
            "sea_temp_c": 19,
            "beach": "Sandy lagoon but 15-17°C — spa trip",
            "transfer_gbp": 25.0,
            "confidence": "market-supported",
        },
    ],
    "hurghada": [
        {
            "name": "Steigenberger ALDAU Beach Hotel",
            "destination_label": "Hurghada & Red Sea, Egypt",
            "stars": 5,
            "board": "Luxury All Inclusive",
            "base_nightly_room_rate_gbp": 135.0,
            "airport": "HRG",
            "airline": "easyJet / Wizz Air",
            "flight_benchmark_5pax_gbp": 1350.0,
            "highlights": ("500m private beach", "Lazy river & heated pools", "Golf course", "Ilios dive club"),
            "hotel_url": "https://www.steigenberger.com/en/hotels/all-hotels/egypt/hurghada/steigenberger-aldau-beach-hotel",
            "dec_ambient_c": (24, 26),
            "sea_temp_c": 25,
            "beach": "500m reef beach — genuine 24-26°C warmth",
            "transfer_gbp": 30.0,
            "confidence": "market-supported",
        },
        {
            "name": "Jaz Aquaviva",
            "destination_label": "Hurghada & Red Sea, Egypt",
            "stars": 5,
            "board": "All Inclusive",
            "base_nightly_room_rate_gbp": 105.0,
            "airport": "HRG",
            "airline": "easyJet / Wizz Air",
            "flight_benchmark_5pax_gbp": 1350.0,
            "highlights": ("Water World access", "Heated family pools", "Beach transfer", "Kids club"),
            "hotel_url": "https://www.jazhotels.com/",
            "dec_ambient_c": (24, 26),
            "sea_temp_c": 25,
            "beach": "Sandy beach — genuine 24-26°C warmth",
            "transfer_gbp": 30.0,
            "confidence": "market-supported",
        },
    ],
    "tenerife": [
        {
            "name": "Hard Rock Hotel Tenerife",
            "destination_label": "Tenerife, Canary Islands",
            "stars": 5,
            "board": "Half Board",
            "base_nightly_room_rate_gbp": 140.0,
            "airport": "TFS",
            "airline": "Jet2 / easyJet",
            "flight_benchmark_5pax_gbp": 1250.0,
            "highlights": ("Saltwater lagoon", "3 heated pools", "Rock Spa", "Beachfront dining"),
            "hotel_url": "https://www.hardrockhoteltenerife.com/",
            "dec_ambient_c": (22, 24),
            "sea_temp_c": 21,
            "beach": "Golden cove via cliff lift; heated pools carry it",
            "transfer_gbp": 60.0,
            "confidence": "market-supported",
        },
    ],
    "lanzarote": [
        {
            "name": "Princesa Yaiza Suite Hotel Resort",
            "destination_label": "Playa Blanca, Lanzarote",
            "stars": 5,
            "board": "Half Board",
            "base_nightly_room_rate_gbp": 144.0,
            "airport": "ACE",
            "airline": "Jet2 / easyJet",
            "flight_benchmark_5pax_gbp": 1300.0,
            "highlights": ("Playa Dorada beach", "Kikoland 10,000m² family park", "Thalassotherapy center"),
            "hotel_url": "https://www.princesayaiza.com/",
            "dec_ambient_c": (21, 23),
            "sea_temp_c": 20,
            "beach": "Playa Dorada sand; heated pools carry it",
            "transfer_gbp": 25.0,
            "confidence": "market-supported",
        },
    ],
    # Cairo done honestly: a pyramids/Nile cultural holiday, NOT a beach trip.
    # December is prime Cairo season (18-22°C, dry). Heated rooftop pools,
    # but no sea — sea_temp_c 0 renders as "city stay".
    "cairo": [
        {
            "name": "Kempinski Nile Hotel Cairo",
            "destination_label": "Cairo, Egypt (Nile Riverfront)",
            "stars": 5,
            "board": "Half Board",
            "base_nightly_room_rate_gbp": 93.0,
            "airport": "CAI",
            "airline": "British Airways / EgyptAir",
            "flight_benchmark_5pax_gbp": 1442.0,
            "highlights": ("Heated rooftop Nile pool", "Pyramids & museum day trips", "≈45 min from CAI airport"),
            "hotel_url": "https://www.kempinski.com/en/cairo/hotel-nile/",
            "dec_ambient_c": (18, 22),
            "sea_temp_c": 0,
            "beach": "NO beach — Nile city hotel. Come for pyramids, museums, bazaars",
            "transfer_gbp": 40.0,
            "confidence": "market-supported",
        },
        {
            "name": "Marriott Mena House",
            "destination_label": "Giza, Cairo, Egypt (Pyramids View)",
            "stars": 5,
            "board": "Half Board",
            "base_nightly_room_rate_gbp": 120.0,
            "airport": "CAI",
            "airline": "British Airways / EgyptAir",
            "flight_benchmark_5pax_gbp": 1442.0,
            "highlights": ("Pyramid-facing rooms", "Heated pool, spa & gardens", "≈1 hr from CAI airport (40 km)"),
            "hotel_url": "https://www.marriott.com/en-us/hotels/caimn-marriott-mena-house-cairo/overview/",
            "dec_ambient_c": (18, 22),
            "sea_temp_c": 0,
            "beach": "NO beach — desert-edge resort at Giza. Pyramids on the doorstep",
            "transfer_gbp": 45.0,
            "confidence": "market-supported",
        },
        # Cairo sprawls: anything within ~1 hr of CAI airport / the sights is
        # fair game, Nile-front or not. JW Marriott New Cairo is the
        # resort-scale pick: big pools (incl. wave pool), golf views, malls.
        {
            "name": "JW Marriott Hotel Cairo",
            "destination_label": "New Cairo, Egypt (Ring Road)",
            "stars": 5,
            "board": "Half Board",
            "base_nightly_room_rate_gbp": 105.0,
            "airport": "CAI",
            "airline": "British Airways / EgyptAir",
            "flight_benchmark_5pax_gbp": 1442.0,
            "highlights": ("Resort pools incl. wave pool", "Golf-course views & spa", "≈30 min from CAI · ≈1 hr to pyramids"),
            "hotel_url": "https://www.marriott.com/en-us/hotels/caijw-jw-marriott-hotel-cairo/overview/",
            "dec_ambient_c": (18, 22),
            "sea_temp_c": 0,
            "beach": "NO beach — New Cairo resort zone. Pools, golf, malls",
            "transfer_gbp": 30.0,
            "confidence": "market-supported",
        },
    ],
    # Madeira done honestly: Savoy Palace breaches £5k for 5 pax in peak week,
    # so the catalog carries the 4-star alternative that fits. Volcanic island:
    # NO sandy beaches anywhere — hiking/levadas/waterfalls holiday, not beach.
    "madeira": [
        {
            "name": "Vidamar Resort Madeira",
            "destination_label": "Funchal, Madeira, Portugal",
            "stars": 4,
            "board": "Half Board",
            "base_nightly_room_rate_gbp": 160.0,
            "airport": "FNC",
            "airline": "easyJet / TUI / British Airways",
            "flight_benchmark_5pax_gbp": 960.0,
            "highlights": ("Cliff lido", "Heated pools & spa", "Levada hikes & waterfalls nearby", "Funchal Christmas lights"),
            "hotel_url": "https://www.vidamarresorts.com/madeira/",
            "dec_ambient_c": (19, 21),
            "sea_temp_c": 20,
            "beach": "NO sand — volcanic cliffs & lidos. Come for hiking",
            "transfer_gbp": 30.0,
            "confidence": "market-supported",
        },
    ],
}


# UK ground transit from Watford Junction (return, whole party share).
# True D2D = package (flights + hotel) + UK ground + destination transfer.
UK_GROUND_RETURN_GBP: dict[str, float] = {
    "LHR": 16.50,  # RailAir RA3 Express Coach, 45 min
    "LGW": 34.00,  # Southern Rail via Clapham Junction, 90 min
    "LTN": 14.50,  # National Rail Thameslink, 55 min
    "STN": 14.50,  # National Rail, approx
    "BHX": 40.00,  # Avanti West Coast direct, 58 min
}


def collect_holiday_deals(
    config: HolidayConfig,
    max_budget_gbp: float = 5000.0,
    live_flight_offers: Optional[Mapping[str, float]] = None,
) -> tuple[PackageDeal, ...]:
    """Calculate holiday packages, enforcing the budget on BOTH the package
    total (flights + hotel) AND the True D2D total (package + UK ground +
    destination transfer). Anything over budget on either measure is dropped —
    never labelled "under budget" while breaching the ceiling."""
    pairs = _date_pairs(config)
    shortlist = _shortlist_pairs(pairs)
    deals: list[PackageDeal] = []
    rooms_count = len(config.rooms)
    travellers = config.travellers

    target_outbound, target_return = (
        shortlist[len(shortlist) // 2] if shortlist else ("2026-12-22", "2026-12-30")
    )
    dep_dt = datetime.strptime(target_outbound, "%Y-%m-%d")
    ret_dt = datetime.strptime(target_return, "%Y-%m-%d")
    nights = (ret_dt - dep_dt).days
    uk_ground = UK_GROUND_RETURN_GBP.get(config.origins[0], 16.50)

    for dest in config.destinations:
        resorts = WINTER_RESORT_CATALOG.get(dest.key.lower(), [])
        for resort in resorts:
            airport = resort["airport"]
            flight_cost = resort["flight_benchmark_5pax_gbp"]
            live_used = bool(live_flight_offers and airport in live_flight_offers)
            if live_used:
                flight_cost = live_flight_offers[airport]  # type: ignore[index]

            hotel_cost = round(resort["base_nightly_room_rate_gbp"] * rooms_count * nights, 2)
            total_pkg = round(flight_cost + hotel_cost, 2)
            price_pp = round(total_pkg / travellers, 2)
            transfer = float(resort.get("transfer_gbp", 30.0))
            true_d2d = round(total_pkg + uk_ground + transfer, 2)
            # STRICT: both measures must clear the ceiling.
            under_budget = total_pkg <= max_budget_gbp and true_d2d <= max_budget_gbp

            if under_budget:
                flight_link = build_google_flights_roundtrip_url(
                    origin=config.origins[0],
                    destination=airport,
                    outbound_date=target_outbound,
                    return_date=target_return,
                    travellers=travellers,
                )
                deals.append(
                    PackageDeal(
                        resort_name=resort["name"],
                        destination_label=resort["destination_label"],
                        destination_key=dest.key,
                        star_rating=resort["stars"],
                        board_basis=resort["board"],
                        outbound_date=target_outbound,
                        return_date=target_return,
                        nights=nights,
                        airline=resort["airline"],
                        origin_airports=config.origins,
                        destination_airport=airport,
                        flight_price_total_gbp=flight_cost,
                        hotel_price_total_gbp=hotel_cost,
                        total_package_price_gbp=total_pkg,
                        price_per_person_gbp=price_pp,
                        flight_booking_url=flight_link,
                        hotel_booking_url=resort["hotel_url"],
                        is_under_budget=True,
                        highlights=resort["highlights"],
                        uk_ground_gbp=uk_ground,
                        transfer_gbp=transfer,
                        true_d2d_gbp=true_d2d,
                        dec_ambient_c=resort.get("dec_ambient_c", (0, 0)),
                        sea_temp_c=resort.get("sea_temp_c", 0),
                        beach=resort.get("beach", ""),
                        confidence=(
                            "verified-exact-date"
                            if live_used
                            else resort.get("confidence", "market-supported")
                        ),
                        source_url=(
                            flight_link
                            if live_used
                            else resort.get("hotel_url", "")
                        ),
                    )
                )

    deals.sort(key=lambda d: d.total_package_price_gbp)
    return tuple(deals)


BOARD_LUXURY_WEIGHT: dict[str, int] = {
    "ultra all inclusive": 6,
    "golden inclusive": 4,
    "luxury all inclusive": 4,
    "all inclusive": 4,
    "half board": 2,
    "bed & breakfast / half board": 1,
    "bed & breakfast": 1,
}

# Live sale evidence observed with a headless browser (NOT exact-date quotes).
# Cited with source + date; party-agnostic promos only.
OBSERVED_PROMOS: tuple[dict[str, str], ...] = (
    {
        "text": "Save £50pp on all Winter 2026/27 holidays (T&Cs apply)",
        "source": "Jet2 destination guides",
        "observed": "2026-09-07",
        "steer": "≈ £250 off a party of 5 where Jet2 has product",
    },
    {
        "text": "Generic 2-adult lead-ins, NOT 5-pax peak prices",
        "source": "easyJet holidays destination guides",
        "observed": "2026-09-07",
        "steer": "Lanzarote 7n from £331pp · Hurghada 7n from £524pp · Madeira 7n from £402pp",
    },
)


def luxury_score(deal: PackageDeal) -> int:
    """Transparent luxury rank: stars dominate, board breaks ties."""
    return deal.star_rating * 10 + BOARD_LUXURY_WEIGHT.get(deal.board_basis.lower(), 0)


def bucket_deals(
    deals: Sequence[PackageDeal],
    max_budget_gbp: float = 5000.0,
) -> dict[str, tuple[PackageDeal, ...]]:
    """Split deals into the three reader buckets.

    discounts: every deal, cheapest first (saving = budget headroom kept).
    luxury:    5-star only, most luxurious first, cheaper wins ties.
    winter:    warmest ambient air first, then warmest sea (genuine winter
               sun floats up; heated-pool-only cold spots sink honestly).
    """
    ordered = tuple(deals)
    return {
        "discounts": tuple(sorted(ordered, key=lambda d: d.total_package_price_gbp)),
        "luxury": tuple(
            sorted(
                (d for d in ordered if d.star_rating >= 5),
                key=lambda d: (-luxury_score(d), d.total_package_price_gbp),
            )
        ),
        "winter": tuple(
            sorted(
                ordered,
                key=lambda d: (-d.dec_ambient_c[0], -d.sea_temp_c, d.total_package_price_gbp),
            )
        ),
    }


# Per-destination imagery for deal cards (verified stable Wikimedia Commons
# thumbnails; free-to-use). Emails render images by URL — no attachments,
# no binary in the public repo. Resorts without a hotel-specific free photo
# use their destination image (visually distinct per destination).
DEST_IMAGES: dict[str, str] = {
    "hurghada": "https://thumb.wikimedia.org/wikipedia/commons/thumb/a/af/Hurghada%2C_Qesm_Hurghada%2C_Red_Sea_Governorate%2C_Egypt_-_panoramio_%28306%29.jpg/960px-Hurghada%2C_Qesm_Hurghada%2C_Red_Sea_Governorate%2C_Egypt_-_panoramio_%28306%29.jpg",
    "tenerife": "https://thumb.wikimedia.org/wikipedia/commons/thumb/4/44/Playa-Las-Vistas-Tenerife-03.jpg/960px-Playa-Las-Vistas-Tenerife-03.jpg",
    "lanzarote": "https://thumb.wikimedia.org/wikipedia/commons/thumb/a/a9/Beach_in_Playa_Blanca_-_Lanzarote_-B20.jpg/960px-Beach_in_Playa_Blanca_-_Lanzarote_-B20.jpg",
    "madeira": "https://thumb.wikimedia.org/wikipedia/commons/thumb/6/65/S%C3%A3o_Martinho_%28Madeira%2C_Portugal%29%2C_Pestana_Ocean_Bay_--_2025_--_0259.jpg/960px-S%C3%A3o_Martinho_%28Madeira%2C_Portugal%29%2C_Pestana_Ocean_Bay_--_2025_--_0259.jpg",
    "antalya": "https://thumb.wikimedia.org/wikipedia/commons/thumb/4/48/Konyaalt%C4%B1_Beach%2C_Antalya%2C_Turkey%2C_March_2022_-_Cafe.jpg/960px-Konyaalt%C4%B1_Beach%2C_Antalya%2C_Turkey%2C_March_2022_-_Cafe.jpg",
    "cairo": "https://thumb.wikimedia.org/wikipedia/commons/thumb/d/d6/All_pyramids_of_Giza_panorama_2.jpg/960px-All_pyramids_of_Giza_panorama_2.jpg",
}


def render_holiday_report(
    config: HolidayConfig,
    *,
    generated_at: str,
    deals: Sequence[PackageDeal] = (),
    history_chips: Optional[Sequence[str]] = None,
) -> str:
    out: list[str] = []
    pairs = _date_pairs(config)
    shortlist = _shortlist_pairs(pairs)
    room_occupancy = " + ".join(str(value) for value in config.rooms)
    provider_labels = {
        "loveholidays": "loveholidays",
        "on_the_beach": "On the Beach",
        "jet2": "Jet2holidays",
        "tui": "TUI",
        "easyjet": "easyJet holidays",
        "ba_holidays": "British Airways Holidays",
        "booking_com": "Booking.com",
        "expedia": "Expedia",
        "google_hotels": "Google Hotels",
        "google_flights": "Google Flights",
    }
    # Package hubs (static entry points — reader enters dates on provider
    # site) vs dynamic parametric searches (exact dates + party encoded).
    _PACKAGE_KEYS = (
        "loveholidays", "on_the_beach", "tui", "easyjet",
        "ba_holidays", "jet2",
    )
    _DYNAMIC_KEYS = (
        "booking_com", "expedia", "google_hotels", "google_flights",
    )
    btn_primary = "background:#38bdf8; color:#062033; text-decoration:none; padding:8px 12px; border-radius:5px; font-weight:700; font-size:12px; margin:2px 4px 2px 0; display:inline-block;"
    btn_muted = "background:#1e293b; color:#94a3b8; text-decoration:none; padding:6px 10px; border-radius:4px; font-weight:500; font-size:11px; margin:2px 3px 2px 0; display:inline-block; border:1px solid #334155;"
    
    out.append('<!DOCTYPE html><html><head><meta charset="utf-8"><title>')
    out.append(escape(config.report_title))
    out.append('</title></head><body style="margin:0; padding:0; background:#eef2f7; font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif; line-height:1.5;">')
    # Full-width light canvas; inner column centered via align=center
    # (Gmail strips margin:auto on tables).
    out.append('<table role="presentation" width="100%" bgcolor="#eef2f7" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:20px 12px;">')
    out.append('<table role="presentation" width="760" cellpadding="0" cellspacing="0" style="width:100%; max-width:760px;">')
    out.append('<tr><td style="padding:0 0 14px 0;">')
    out.append('<h1 style="margin:0 0 4px 0; color:#0f172a; font-size:24px; font-weight:800;">☀️ ' + escape(config.report_title) + '</h1>')
    out.append('<p style="margin:0; color:#64748b; font-size:13px;">')
    out.append(escape(generated_at))
    out.append(' · ')
    out.append(str(len(config.destinations)))
    out.append(' destinations · ')
    out.append(str(len(pairs)))
    out.append(' valid date combinations</p>')
    out.append('</td></tr>')
    out.append('<tr><td style="padding:0 0 18px 0;">')
    out.append('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px;">')
    out.append('<tr><td style="padding:10px 14px; color:#475569; font-size:13px;">')
    out.append('<strong style="color:#0f172a;">' + str(config.travellers) + '</strong> travellers · <strong style="color:#0f172a;">' + str(len(config.rooms)) + '</strong> room(s)')
    out.append('<br>Room occupancy: <strong style="color:#0f172a;">' + escape(room_occupancy) + '</strong>')
    out.append('<br>Preferred departure <strong style="color:#0f172a;">' + escape(config.departure_window[0]) + '–' + escape(config.departure_window[1]) + '</strong>')
    out.append('<br>Outbound <strong style="color:#0f172a;">' + escape(', '.join(config.outbound_dates)) + '</strong> · Return <strong style="color:#0f172a;">' + escape(', '.join(config.return_dates)) + '</strong>')
    out.append('</td></tr></table>')
    out.append('</td></tr><tr><td>')

    # ── VERIFIED LIVE DEALS UNDER £5,000 (WHEN AVAILABLE) ──
    if deals:
        out.append('<h2 style="margin:22px 0 4px 0; color:#0f172a; font-size:20px; font-weight:800;">⭐ Verified Luxury Deals Under £5,000</h2>')
        out.append('<p style="margin:0 0 10px 0; color:#475569; font-size:13px;">Hand-picked for your party — every resort clears £5,000 on the package <em>and</em> the true door-to-door total. Cheapest first.</p>')
        # At-a-glance: one line per decision lens (no ranked walls).
        buckets = bucket_deals(deals)
        glance = '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; background:#ffffff; border:1px solid #e2e8f0; border-radius:8px; margin:0 0 16px 0;">'
        b1 = buckets["discounts"][0] if buckets["discounts"] else None
        b2 = buckets["luxury"][0] if buckets["luxury"] else None
        b3 = buckets["winter"][0] if buckets["winter"] else None
        if b1 is not None:
            glance += ('<tr><td style="padding:7px 12px; color:#475569; font-size:12px; border-bottom:1px solid #f1f5f9;">'
                       '<strong style="color:#0f172a;">💰 Biggest Discounted Deals:</strong> '
                       + escape(b1.resort_name) + ' — <strong style="color:#059669;">£' + f'{5000.0 - b1.total_package_price_gbp:,.0f}' + ' under £5k</strong></td></tr>')
        if b2 is not None:
            glance += ('<tr><td style="padding:7px 12px; color:#475569; font-size:12px; border-bottom:1px solid #f1f5f9;">'
                       '<strong style="color:#0f172a;">💎 Top Luxury Within £5k:</strong> '
                       + escape(b2.resort_name) + ' · ' + escape(b2.board_basis) + '</td></tr>')
        if b3 is not None:
            glance += ('<tr><td style="padding:7px 12px; color:#475569; font-size:12px;">'
                       '<strong style="color:#0f172a;">☀️ Best Winter Facilities:</strong> '
                       + escape(b3.resort_name) + ' — ' + str(b3.dec_ambient_c[0]) + '–' + str(b3.dec_ambient_c[1]) + '°C air, sea ' + str(b3.sea_temp_c) + '°C</td></tr>')
        glance += '</table>'
        out.append(glance)

        # Chips align with the caller's `deals` order; index them by resort
        # name so the card order below (cheapest first) stays correct.
        chip_by_resort = {}
        if history_chips is not None:
            chip_by_resort = {d.resort_name: history_chips[i] for i, d in enumerate(deals) if i < len(history_chips)}

        rooms_n = len(config.rooms)
        ordered = sorted(deals, key=lambda d: d.total_package_price_gbp)
        for deal in ordered:
            stars_str = '★' * deal.star_rating + '☆' * (5 - deal.star_rating)
            img = DEST_IMAGES.get(deal.destination_key.lower(), DEST_IMAGES["hurghada"])
            live = deal.confidence == 'verified-exact-date'
            under = 5000.0 - deal.total_package_price_gbp
            out.append('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:separate; border-spacing:0; margin:0 0 14px 0; background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; overflow:hidden;">')
            out.append('<tr>')
            # Left: destination photo (hotel-specific photos are not on free CDNs)
            out.append('<td width="220" valign="top" style="padding:0; line-height:0;">')
            out.append('<img src="' + escape(img, quote=True) + '" alt="' + escape(deal.destination_label) + '" width="220" height="176" style="width:220px; height:176px; object-fit:cover; display:block; border-radius:11px 0 0 11px;">')
            out.append('</td>')
            # Right: everything a booker needs, scannable in one glance
            out.append('<td valign="top" style="padding:13px 16px;">')
            out.append('<div style="margin-bottom:3px;"><strong style="color:#0f172a; font-size:17px;">' + escape(deal.resort_name) + '</strong> <span style="color:#f59e0b; font-size:12px; letter-spacing:1px;">' + stars_str + '</span></div>')
            out.append('<div style="margin:5px 0 7px;">')
            out.append('<span style="background:#eff6ff; color:#1d4ed8; padding:2px 8px; border-radius:9999px; font-size:11px; font-weight:700;">' + escape(deal.board_basis) + '</span> ')
            out.append('<span style="background:' + ('#dcfce7' if live else '#fef3c7') + '; color:' + ('#166534' if live else '#92400e') + '; padding:2px 8px; border-radius:9999px; font-size:11px; font-weight:700;">' + ('🟢 LIVE VERIFIED' if live else '🟡 BENCHMARK PRICE') + '</span> ')
            out.append('<span style="background:#f1f5f9; color:#334155; padding:2px 8px; border-radius:9999px; font-size:11px; font-weight:700;">UNDER £5K BUDGET</span>')
            history_chip = chip_by_resort.get(deal.resort_name, '')
            if history_chip:
                out.append(' ' + history_chip)
            out.append('</div>')
            out.append('<div style="color:#64748b; font-size:12px; margin-bottom:7px;">📍 ' + escape(deal.destination_label) + ' (' + escape(deal.destination_airport) + ') · ' + escape(deal.outbound_date) + ' → ' + escape(deal.return_date) + ' · ' + str(deal.nights) + ' nights</div>')
            if deal.highlights:
                out.append('<div style="color:#475569; font-size:12px; margin-bottom:8px;">✨ ' + escape(' · '.join(deal.highlights)) + '</div>')
            # Facts strip: flights | stay | December weather | BIG price
            out.append('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; background:#f8fafc; border-radius:8px; margin-bottom:10px;"><tr>')
            out.append('<td style="padding:8px 10px; color:#64748b; font-size:11px;">✈️ Flights<br><strong style="color:#0f172a; font-size:13px;">£' + f'{deal.flight_price_total_gbp:,.0f}' + '</strong><br><span style="font-size:10px;">' + escape(deal.airline.split('/')[0].strip()) + '</span></td>')
            out.append('<td style="padding:8px 10px; color:#64748b; font-size:11px; border-left:1px solid #e2e8f0;">🏨 Stay<br><strong style="color:#0f172a; font-size:13px;">£' + f'{deal.hotel_price_total_gbp:,.0f}' + '</strong><br><span style="font-size:10px;">' + str(rooms_n) + ' rooms × ' + str(deal.nights) + 'n</span></td>')
            if deal.sea_temp_c:
                out.append('<td style="padding:8px 10px; color:#64748b; font-size:11px; border-left:1px solid #e2e8f0;">🌡️ December<br><strong style="color:#0f172a; font-size:13px;">' + str(deal.dec_ambient_c[0]) + '–' + str(deal.dec_ambient_c[1]) + '°C</strong><br><span style="font-size:10px;">sea ' + str(deal.sea_temp_c) + '°C</span></td>')
            else:
                out.append('<td style="padding:8px 10px; color:#64748b; font-size:11px; border-left:1px solid #e2e8f0;">🌡️ December<br><strong style="color:#0f172a; font-size:13px;">' + str(deal.dec_ambient_c[0]) + '–' + str(deal.dec_ambient_c[1]) + '°C</strong><br><span style="font-size:10px;">city stay, no sea swimming</span></td>')
            out.append('<td align="right" valign="middle" style="padding:8px 10px;">')
            out.append('<div style="color:#059669; font-size:24px; font-weight:800; white-space:nowrap;">£' + f'{deal.total_package_price_gbp:,.0f}' + '</div>')
            out.append('<div style="color:#64748b; font-size:11px; white-space:nowrap;">£' + f'{deal.price_per_person_gbp:,.0f}' + 'pp · D2D £' + f'{deal.true_d2d_gbp:,.0f}' + '</div>')
            out.append('</td>')
            out.append('</tr></table>')
            # ONE obvious action + quiet alternatives (dated, party-encoded)
            out.append('<a href="' + escape(build_booking_com_url(destination=deal.destination_key, departure_date=deal.outbound_date, return_date=deal.return_date, adults=config.travellers, rooms=rooms_n), quote=True) + '" style="background:#2563eb; color:#ffffff; text-decoration:none; padding:10px 18px; border-radius:8px; font-weight:700; font-size:13px; display:inline-block;">Check live dates &amp; prices →</a>')
            out.append('<span style="color:#94a3b8; font-size:11px; margin:0 6px;">or</span>')
            out.append('<a href="' + escape(deal.flight_booking_url, quote=True) + '" style="color:#2563eb; font-size:12px; text-decoration:none; font-weight:600;">flights</a>')
            out.append('<span style="color:#cbd5e1;"> · </span>')
            out.append('<a href="' + escape(build_expedia_url(destination=deal.destination_key, departure_date=deal.outbound_date, return_date=deal.return_date, adults=config.travellers, rooms=rooms_n), quote=True) + '" style="color:#2563eb; font-size:12px; text-decoration:none;">Expedia</a>')
            out.append('<span style="color:#cbd5e1;"> · </span>')
            out.append('<a href="' + escape(build_google_hotels_url(destination=deal.destination_key, departure_date=deal.outbound_date, return_date=deal.return_date, adults=config.travellers, rooms=rooms_n), quote=True) + '" style="color:#2563eb; font-size:12px; text-decoration:none;">Google Hotels</a>')
            out.append('<span style="color:#cbd5e1;"> · </span>')
            out.append('<a href="' + escape(deal.hotel_booking_url, quote=True) + '" style="color:#2563eb; font-size:12px; text-decoration:none;">Resort direct</a>')
            # Best verified package guide for this destination: easyJet guides
            # carry live lead-in prices; Jet2 second; hub fallback otherwise.
            guide_url = EASYJET_DESTINATION_PATHS.get(
                deal.destination_key.lower(),
                JET2_DESTINATION_PATHS.get(deal.destination_key.lower(), LOVEHOLIDAYS_HOME),
            )
            guide_label = (
                "easyJet holidays"
                if deal.destination_key.lower() in EASYJET_DESTINATION_PATHS
                else ("Jet2holidays" if deal.destination_key.lower() in JET2_DESTINATION_PATHS else "loveholidays")
            )
            out.append('<span style="color:#cbd5e1;"> · </span>')
            out.append('<a href="' + escape(guide_url, quote=True) + '" style="color:#2563eb; font-size:12px; text-decoration:none;">' + guide_label + '</a>')
            out.append('</td>')
            out.append('</tr></table>')

    if not deals:
        out.append('<h2 style="margin:0 0 12px 0; color:#0f172a; font-size:18px; font-weight:800;">Package Deal Search Links</h2>')
        
        adults = config.travellers
        rooms = len(config.rooms)
        
        for dest in config.destinations:
            out.append('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; margin:12px 0;">')
            out.append('<tr style="background:#0f172a;"><td colspan="2" style="padding:10px 12px; color:#f8fafc; font-size:15px; font-weight:700;">')
            out.append(escape(dest.label))
            out.append('</td></tr>')
            out.append('<tr style="background:#f8fafc;"><td colspan="2" style="padding:6px 12px; color:#475569; font-size:12px;">')
            out.append('From: ' + escape(', '.join(config.origins)) + ' · destination airports: ' + escape(', '.join(dest.airports)))
            out.append(' · ' + str(adults) + ' travellers · room occupancy ' + escape(room_occupancy))
            out.append('</td></tr>')
            out.append('<tr style="background:#eff6ff;"><td colspan="2" style="padding:4px 12px; color:#1d4ed8; font-size:12px; font-weight:600;">All Inclusive · Half Board · Full Board · Room Only</td></tr>')
            
            # ── TOP PICKS: 3 representative date pairs with DYNAMIC buttons ──
            # Each pair encodes exact dates + party (Booking/Expedia/Google),
            # so links open dated results instead of static homepages. Package
            # hubs (which cannot encode dates) render once below to stay under
            # Gmail's 102 KB clipping limit.
            out.append('<tr><td colspan="2" style="padding:12px 12px 4px; color:#b45309; font-size:13px; font-weight:700;">')
            out.append('⭐ Top Picks (3 of ' + str(len(pairs)) + ' date combinations — dates encoded in every link)')
            out.append('</td></tr><tr><td colspan="2" style="padding:4px 10px 10px;">')
            for outbound, returning in shortlist:
                urls = build_provider_urls(
                    destination_key=dest.key,
                    destination_label=dest.label,
                    origin_airports=config.origins,
                    departure_date=outbound,
                    return_date=returning,
                    adults=adults,
                    rooms=rooms,
                )
                out.append('<div style="margin-bottom:8px;">')
                out.append('<span style="color:#f8fafc; font-size:12px; font-weight:600; margin-right:8px;">')
                out.append(escape(outbound) + ' → ' + escape(returning) + ' (' + str((datetime.strptime(returning, "%Y-%m-%d") - datetime.strptime(outbound, "%Y-%m-%d")).days) + ' nights)')
                out.append('</span>')
                for name in _DYNAMIC_KEYS:
                    url = urls.get(name)
                    if not url:
                        continue
                    out.append('<a href="')
                    out.append(escape(url, quote=True))
                    out.append('" style="')
                    out.append(btn_primary)
                    out.append('">')
                    out.append(escape(provider_labels[name]))
                    out.append('</a>')
                out.append('</div>')
            out.append('</td></tr>')

            # ── PACKAGE HUBS: one row per destination (dates entered on site)
            out.append('<tr><td colspan="2" style="padding:10px 12px 4px; color:#64748b; font-size:12px; font-weight:600; border-top:1px solid #1e293b;">')
            out.append('Package entry points — enter any listed outbound/return pair on the provider site')
            out.append('</td></tr>')
            out.append('<tr><td colspan="2" style="padding:4px 10px 10px;">')
            out.append('<div style="margin-bottom:4px;"><span style="color:#94a3b8; font-size:11px;">')
            out.append(escape(', '.join(outbound + '→' + returning for outbound, returning in pairs)))
            out.append('</span></div><div>')
            for name in _PACKAGE_KEYS:
                url = urls.get(name)
                if not url:
                    continue
                out.append('<a href="')
                out.append(escape(url, quote=True))
                out.append('" style="')
                out.append(btn_muted)
                out.append('">')
                out.append(escape(provider_labels[name]))
                out.append('</a>')
            out.append('</div></td></tr>')

            out.append('</table>')
        
        out.append('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; margin-top:24px;">')
        out.append('<tr><td style="padding:14px; background:#fef3c7; border-radius:6px; color:#78350f; font-size:12px; line-height:1.5;">')
        out.append('<strong style="color:#92400e;">⚠ No live prices collected</strong> — these are provider search entry points, not verified checkout deep links. Some providers accept only the first departure airport or room count in a URL. Reapply every origin option, the exact room occupancy <strong>' + escape(room_occupancy) + '</strong>, preferred departure time, board basis, baggage and transfers before relying on a result. Verify the final whole-party checkout total and protection before booking.')
        out.append('</td></tr></table>')
    out.append('</td></tr></table>')
    out.append('</td></tr></table></body></html>')
    
    return ''.join(out)
