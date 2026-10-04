"""Runtime-configured holiday search plan with parametric provider search URLs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import escape
import json
import re
import sys
from typing import Any, Mapping, Optional, Sequence
from urllib.parse import urlencode

from .cabin import cabin_for_flight_hours, destination_cabin, resolve_flight_hours
from .config import (
    REPORT_CABINS,
    ConfigError,
    _airports,
    _dates,
    _text,
    _validate_report_title,
    _window,
)
from .google_flights import build_google_flights_legs_url, build_google_flights_roundtrip_url
from . import live_verify
from .live_verify import (
    MIXED_CABIN,
    LiveFareEvidence,
    evidence_for,
    priced_date_pair,
)
# ``hotel_evidence`` imports this module lazily (inside its functions, for the
# priced date pairs and the season tables), so the import is acyclic — the
# same seam as ``live_verify`` above.
from .hotel_evidence import (
    hotel_rate_for,
    hotel_rate_provenance,
    supplemental_for,
    unit_check_blocks_party,
)
from .vendors import (
    DEEP_LINK as VENDOR_DEEP_LINK,
    DESTINATION_PAGE as VENDOR_DESTINATION_PAGE,
    PREFILLED_SEARCH as VENDOR_PREFILLED_SEARCH,
    SEARCH_PAGE as VENDOR_SEARCH_PAGE,
    PRICE_NOT_VERIFIED,
    ATOL_OPERATOR_LINK_BASES,
    ATOL_REGISTER_BY_VENDOR,
    build_atol_operator_links,
    build_vendor_links,
    price_label_line,
    trip_from_deal,
)
from .diy import (
    DiyComparison,
    airline_booking_page,
    build_diy_option,
    trajectory_label,
)


@dataclass(frozen=True)
class HolidayDestination:
    key: str
    label: str
    airports: tuple[str, ...]
    # London flight hours (nonstop block time, or the fastest one-stop
    # through journey where no nonstop exists). The cabin is DERIVED from it
    # by cabin.py; cabin_class below stores that derived answer.
    flight_hours: Optional[float] = None
    flight_hours_source: str = ""
    cabin_class: str = "ECONOMY"
    cabin_classes: tuple[str, ...] = ()


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
    cabin_class: str = "ECONOMY"
    cabin_classes: tuple[str, ...] = ()
    max_budget_gbp: float = 5000.0
    #: Stay lengths the report will price. A date pair outside the band is
    #: never a candidate: with a 7x7 December grid a 2-night trip is the
    #: cheapest total on every resort, so "cheapest of all pairs" would be a
    #: report about short trips, not about the holiday being planned.
    min_nights: int = 6
    max_nights: int = 10


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
    "fuerteventura": "Caleta de Fuste, Fuerteventura",
    "gran_canaria": "Maspalomas, Gran Canaria",
    "paphos": "Paphos, Cyprus",
    # Far East watch (2026-09-28)
    "phuket": "Phuket, Thailand",
    "krabi": "Ao Nang, Krabi, Thailand",
    "langkawi": "Langkawi, Malaysia",
    "penang": "Batu Ferringhi, Penang, Malaysia",
    "singapore": "Sentosa, Singapore",
    "phu_quoc": "Phu Quoc, Vietnam",
    "bali": "Nusa Dua, Bali, Indonesia",
    "da_nang": "Da Nang, Vietnam",
    "kota_kinabalu": "Kota Kinabalu, Sabah, Malaysia",
    "japan": "Tokyo, Japan",
    # July long-haul beach catalogue (2026-09-29)
    "lombok": "Kuta Mandalika, Lombok, Indonesia",
    "koh_samui": "Koh Samui, Thailand",
    "koh_phangan": "Koh Phangan, Thailand",
    "khao_lak": "Khao Lak, Thailand",
    # Africa and Mexico (2026-09-30)
    "zanzibar": "Nungwi, Zanzibar, Tanzania",
    "mauritius": "Flic en Flac, Mauritius",
    "riviera_maya": "Cancún, Mexico",
}

# Destination airport per holiday key (for Google Flights parametric links).
HOLIDAY_AIRPORTS: dict[str, str] = {
    "antalya": "AYT", "malta": "MLA", "taghazout": "AGA",
    "hurghada": "HRG", "cairo": "CAI", "muscat": "MCT",
    "doha": "DOH", "tenerife": "TFS", "madeira": "FNC",
    "lanzarote": "ACE", "cape_verde": "SID",
    "fuerteventura": "FUE", "gran_canaria": "LPA", "paphos": "PFO",
    "phuket": "HKT", "krabi": "KBV", "langkawi": "LGK", "penang": "PEN",
    "singapore": "SIN", "phu_quoc": "PQC", "bali": "DPS", "da_nang": "DAD",
    "kota_kinabalu": "BKI", "japan": "HND",
    # Koh Phangan has no airport: USM, then the resort's boat (about 40 min).
    # Khao Lak is served from HKT (about 1h40 by road).
    "lombok": "LOP", "koh_samui": "USM", "koh_phangan": "USM", "khao_lak": "HKT",
    "zanzibar": "ZNZ", "mauritius": "MRU", "riviera_maya": "CUN",
}

#: Far East watch (owner preference, 2026-09-28): long-haul destinations
#: ranked FIRST in the report. None of these keys has a resort in either
#: catalogue, so each is a DESTINATION watch, not a hotel card (the July
#: Lombok and Thailand keys have resorts in ``SUMMER_RESORT_CATALOG`` and
#: are deliberately absent here), and every figure here is a benchmark, unverified: an
#: editorial estimate of a peak-season Business return fare per person and
#: a 5-star family-suite night, never an observed or quoted price. They are
#: here to rank and to size the budget question, and are replaced the day a
#: live whole-party observation exists. ``months`` is the season each is
#: listed for; outside it the row says so and shows no price.
FAR_EAST_WATCH: dict[str, dict[str, Any]] = {
    "phuket": {"months": (11, 12, 1, 2, 3), "business_pp_gbp": 3900, "suite_night_gbp": 520,
               "routing": "Virgin Atlantic nonstop (seasonal from 18 Oct 2026)",
               "climate": "30-32°C, dry season, sea 28°C"},
    "krabi": {"months": (11, 12, 1, 2, 3), "business_pp_gbp": 3700, "suite_night_gbp": 420,
              "routing": "1 stop via Bangkok", "climate": "31-32°C, dry season"},
    "langkawi": {"months": (11, 12, 1, 2, 3), "business_pp_gbp": 3100, "suite_night_gbp": 480,
                 "routing": "1 stop via Kuala Lumpur", "climate": "31-32°C, dry season begins"},
    "penang": {"months": (12, 1, 2, 3), "business_pp_gbp": 3100, "suite_night_gbp": 300,
               "routing": "1 stop via Kuala Lumpur", "climate": "31°C, occasional showers"},
    "singapore": {"months": (11, 12, 1, 2, 3, 6, 7, 8), "business_pp_gbp": 4100, "suite_night_gbp": 650,
                  "routing": "BA / Singapore Airlines nonstop", "climate": "30-31°C, monsoon showers"},
    "phu_quoc": {"months": (11, 12, 1, 2, 3), "business_pp_gbp": 3200, "suite_night_gbp": 420,
                 "routing": "1 stop via Bangkok or Ho Chi Minh City", "climate": "30-31°C, dry season"},
    "bali": {"months": (5, 6, 7, 8, 9), "business_pp_gbp": 3900, "suite_night_gbp": 450,
             "routing": "1 stop via Singapore", "climate": "27-30°C, dry season"},
    "da_nang": {"months": (5, 6, 7, 8), "business_pp_gbp": 3300, "suite_night_gbp": 350,
                "routing": "1 stop via Bangkok, Hanoi or Ho Chi Minh City",
                "climate": "33-35°C, dry season; Hoi An 30 min"},
    "kota_kinabalu": {"months": (5, 6, 7, 8, 9), "business_pp_gbp": 3300, "suite_night_gbp": 320,
                      "routing": "1 stop via Kuala Lumpur", "climate": "31-32°C, drier west coast"},
    "japan": {"months": (7, 8), "business_pp_gbp": 5200, "suite_night_gbp": 700,
              "routing": "BA / JAL / ANA nonstop", "climate": "30-33°C, humid; rainy season usually over by mid-July"},
}

#: The exact label every Far East watch figure carries.
FAR_EAST_PRICE_LABEL = "benchmark, unverified"

#: A Far East watch row more than this fraction over the budget loses its full
#: card and collapses to one compact line (owner rule 2026-10-02). A watch row
#: is an unverified benchmark, not a bookable deal, so spending a full card on
#: one the owner cannot afford buries the destinations that fit.
FAR_EAST_WATCH_COLLAPSE_RATIO: float = 0.25

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
    # Index-verified via search snippets (site blocks bots: curl 403).
    "fuerteventura": "https://www.easyjet.com/en/holidays/spain/fuerteventura",
    "gran_canaria": "https://www.easyjet.com/en/holidays/spain/gran-canaria",
    # paphos: easyJet holidays Paphos slug NOT verified -> hub fallback.
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
    # Slugs index-verified. Paphos: Jet2 groups Cyprus at island level.
    "fuerteventura": "https://www.jet2holidays.com/destinations/canary-islands/fuerteventura",
    "gran_canaria": "https://www.jet2holidays.com/destinations/canary-islands/gran-canaria",
    "paphos": "https://www.jet2holidays.com/destinations/cyprus",
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
        *ATOL_OPERATOR_LINK_BASES,
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


def build_google_hotels_property_url(
    *,
    resort_name: str,
    destination_key: str,
    departure_date: str,
    return_date: str,
    adults: int,
    rooms: int,
) -> str:
    """Google Hotels PROPERTY card — the one-link cross-vendor comparison.

    Querying the property by name (not the destination) lands on the hotel's
    own card with every vendor's dated price side by side: exactly the
    'same deal, which vendor is cheapest' check.
    """
    query = HOLIDAY_SEARCH_QUERIES.get(destination_key.lower(), destination_key)
    return GOOGLE_HOTELS_BASE + "?" + urlencode(
        {
            "q": f"{resort_name} {query}",
            "dates": f"{departure_date},{return_date}",
            "adults": adults,
            "rooms": rooms,
            "curr": "GBP",
            "hl": "en-GB",
        }
    )


def build_booking_com_property_url(
    *,
    resort_name: str,
    destination_key: str,
    departure_date: str,
    return_date: str,
    adults: int,
    rooms: int,
) -> str:
    """Booking.com search keyed on the PROPERTY name + exact dates + party.

    The named resort resolves as the top hit with dated availability and a
    bookable total — a working deep link without guessing opaque hotel IDs.
    """
    query = HOLIDAY_SEARCH_QUERIES.get(destination_key.lower(), destination_key)
    return BOOKING_COM_BASE + "?" + urlencode(
        {
            "ss": f"{resort_name} {query}",
            "checkin": departure_date,
            "checkout": return_date,
            "group_adults": adults,
            "no_rooms": rooms,
        }
    )


def build_expedia_property_url(
    *,
    resort_name: str,
    destination_key: str,
    departure_date: str,
    return_date: str,
    adults: int,
    rooms: int,
) -> str:
    """Expedia search keyed on the PROPERTY name + exact dates + party."""
    query = HOLIDAY_SEARCH_QUERIES.get(destination_key.lower(), destination_key)
    return EXPEDIA_BASE + "?" + urlencode(
        {
            "destination": f"{resort_name} {query}",
            "startDate": departure_date,
            "endDate": return_date,
            "rooms": rooms,
            "adults": adults,
        }
    )


def build_google_flights_holiday_url(
    *,
    destination: str,
    origin_airports: tuple[str, ...],
    departure_date: str,
    return_date: str,
    adults: int,
    cabin_class: str = "ECONOMY",
) -> str:
    """Google Flights structured round-trip for a holiday date pair.

    Uses the shared `tfs=` encoder so the link opens a dated results page.
    Falls back to the Flights homepage only when dates are inverted.
    """
    from .google_flights import build_google_flights_legs_url, build_google_flights_roundtrip_url

    airport = HOLIDAY_AIRPORTS.get(destination.lower(), "")
    origin = (origin_airports[0] if origin_airports else "LHR").upper()
    if not airport or return_date <= departure_date:
        return "https://www.google.com/travel/flights/search?curr=GBP&hl=en-GB"
    return build_google_flights_roundtrip_url(
        origin=origin, destination=airport,
        outbound_date=departure_date, return_date=return_date,
        travellers=max(1, min(9, adults)),
        cabin_class=cabin_class,
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
    cabin_class: str = "ECONOMY",
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
            cabin_class=cabin_class,
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
                cabin_class=dest.cabin_class,
            )
        )
        for dest in config.destinations
        for outbound, returning in pairs
    )


#: Upper bound on destinations per config (bounded engine: every destination
#: multiplies provider links and evidence keys).
MAX_DESTINATIONS = 24

#: Upper bound on valid date combinations. ``_dates`` already caps each list
#: at 8 dates, so 8x8 is the widest grid the schema can express; the old cap
#: of 24 rejected the owner's 7x7 December window (49 combinations) outright.
MAX_DATE_COMBINATIONS = 64


def load_holiday_config(payload: str) -> HolidayConfig:
    try:
        raw = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ConfigError("holiday configuration is not valid JSON") from exc
    allowed = {
        "report_title", "party", "departure_window", "origins",
        "outbound_dates", "return_dates", "destinations",
        "cabin_class", "cabin_classes", "max_budget_gbp",
        "min_nights", "max_nights",
    }
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

    # Shared with the live-evidence loader and the renderer via config.py, so
    # "the report can price this cabin" is one definition, not three.
    valid_cabins = REPORT_CABINS

    def _checked_cabins(value: Any, field: str) -> None:
        # Cabin fields are LEGACY since the 2026-09-28 rule: the cabin is
        # derived from flight hours (cabin.py) and these values are never
        # priced. They are still validated so a typo fails loudly, and still
        # accepted so a pre-rule config (the live December secret was loaded
        # from the old example, which named PREMIUM_ECONOMY) keeps loading.
        values = value if isinstance(value, list) else [value]
        if isinstance(value, list) and not value:
            raise ConfigError(f"{field} must be a non-empty list")
        for cabin in values:
            if str(cabin).upper() not in valid_cabins:
                raise ConfigError(f"unsupported {field}: {str(cabin).upper()}")

    for field in ("cabin_class", "cabin_classes"):
        if field in raw:
            _checked_cabins(raw[field], field)

    max_budget_raw = raw.get("max_budget_gbp", 5000.0)
    try:
        max_budget = float(max_budget_raw)
        if max_budget <= 0:
            raise ValueError
    except (ValueError, TypeError):
        raise ConfigError("max_budget_gbp must be a positive number")

    def _nights_bound(value: Any, field: str) -> int:
        if isinstance(value, bool):
            raise ConfigError(f"{field} must be a whole number of nights")
        try:
            nights = int(value)
        except (TypeError, ValueError):
            raise ConfigError(f"{field} must be a whole number of nights")
        if not 1 <= nights <= 60:
            raise ConfigError(f"{field} must be between 1 and 60 nights")
        return nights

    min_nights = _nights_bound(raw.get("min_nights", 6), "min_nights")
    max_nights = _nights_bound(raw.get("max_nights", 10), "max_nights")
    if min_nights > max_nights:
        raise ConfigError("min_nights must not exceed max_nights")

    destination_raw = raw.get("destinations")
    dest_allowed = {
        "key", "label", "airports", "cabin_class", "cabin_classes",
        "flight_hours", "flight_hours_source",
    }
    # 24, not 16: the Far East additions of 2026-09-28 took the December
    # watch to 20 destinations without dropping any existing one.
    if not isinstance(destination_raw, list) or not 1 <= len(destination_raw) <= MAX_DESTINATIONS:
        raise ConfigError(f"destinations must contain 1-{MAX_DESTINATIONS} entries")
    destinations = []
    for item in destination_raw:
        if not isinstance(item, dict) or set(item) - dest_allowed:
            continue
        key = _text(item.get("key"), "destination key", 48)
        for field in ("cabin_class", "cabin_classes"):
            if field in item:
                _checked_cabins(item[field], f"destination {field}")
        hours_raw = item.get("flight_hours")
        if hours_raw is not None and (
            isinstance(hours_raw, bool) or not isinstance(hours_raw, (int, float))
        ):
            raise ConfigError(f"destination '{key}' flight_hours must be a number")
        hours = resolve_flight_hours(key, hours_raw)
        try:
            derived = cabin_for_flight_hours(hours)
        except ValueError as exc:
            raise ConfigError(
                f"destination '{key}' needs flight_hours (London block time in "
                f"hours): there is no built-in value to derive its cabin from ({exc})"
            ) from exc
        destinations.append(
            HolidayDestination(
                key=key,
                label=_text(item.get("label"), "destination label"),
                airports=_airports(item.get("airports"), "destination airports"),
                flight_hours=hours,
                flight_hours_source=str(item.get("flight_hours_source", "")),
                # The DERIVED cabin, never the config's: every consumer
                # (report, evidence contract, provider links) reads the rule.
                cabin_class=derived,
                cabin_classes=(derived,),
            )
        )
    if len(destinations) != len(destination_raw):
        raise ConfigError("a destination contains unknown fields")
    derived_cabins = tuple(dict.fromkeys(d.cabin_class for d in destinations))
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
    if len(valid_pairs) > MAX_DATE_COMBINATIONS:
        raise ConfigError(
            f"holiday configuration exceeds {MAX_DATE_COMBINATIONS} valid date combinations"
        )
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
        destinations=tuple(destinations),
        # Summary of what the report prices, derived per destination.
        cabin_class="ECONOMY" if "ECONOMY" in derived_cabins else derived_cabins[0],
        cabin_classes=derived_cabins,
        max_budget_gbp=max_budget,
        min_nights=min_nights,
        max_nights=max_nights,
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


def nights_between(pair: tuple[str, str]) -> int:
    """Nights in one (outbound, return) pair."""
    outbound, returning = pair
    return (
        datetime.strptime(returning, "%Y-%m-%d")
        - datetime.strptime(outbound, "%Y-%m-%d")
    ).days


def priceable_date_pairs(config: HolidayConfig) -> tuple[tuple[str, str], ...]:
    """The date pairs this run will actually price.

    Every configured pair whose stay length sits in ``min_nights``..``max_nights``.
    The collector prices each of them and reports the cheapest, so this is the
    set that decides what the reader is shown; the evidence loader and the hunt
    contract must agree with it or browser reads are spent on dates nothing
    prices.

    A band that matches nothing is a misconfiguration, not a quiet market: it
    falls back to every valid pair (and says so on stderr) rather than
    returning an empty set and taking the whole report down to zero deals.
    """
    pairs = _date_pairs(config)
    low, high = int(config.min_nights), int(config.max_nights)
    priced = tuple(pair for pair in pairs if low <= nights_between(pair) <= high)
    if priced:
        return priced
    print(
        f"holiday: no date pair is {low}-{high} nights; pricing all "
        f"{len(pairs)} configured pairs instead",
        file=sys.stderr,
    )
    return pairs


def shortlist_date_pairs(config: HolidayConfig) -> tuple[tuple[str, str], ...]:
    """Three representative pairs, taken from the ones this run can price.

    The shortlist used to be drawn from the whole configured cross product, which
    is the same thing only while every configured pair happens to sit inside the
    stay band. The new July window (outbound 5/8/12/15/19, returns 12/15/19/22/26/29,
    6-10 nights) is not: its cross product holds a 3-night pair, and the shortlist
    middle became (12 -> 15), which no card ever prices. A headline pair that is
    not priceable is worse than a stale one - the report says one thing and the
    evidence hunt spends its reads on another.
    """
    return _shortlist_pairs(priceable_date_pairs(config))


def pricing_order(config: HolidayConfig) -> tuple[tuple[str, str], ...]:
    """Priceable pairs, with the report's headline pair tried first.

    The headline pair (the shortlist middle, the pair the evidence contract
    states) is what a benchmark-only run has always displayed. Putting it
    first makes ties resolve to it, so widening the search does not silently
    rewrite every card's dates to the earliest pair in the window.
    """
    pairs = priceable_date_pairs(config)
    headline = priced_date_pair(config)
    if headline in pairs:
        return (headline,) + tuple(pair for pair in pairs if pair != headline)
    return pairs


def option_evidence_class(option: Mapping[str, Any]) -> int:
    """How much of one candidate option's price was READ rather than modelled.

    Derived from the two provenance facts an option already carries and nothing
    else: ``evidence_used`` (the flights came from a whole-party, exact-date
    fare somebody read) and ``hotel_rate`` (the stay came from a rate read for
    this property on these dates). It is a count rather than a label because
    the two are the same kind of claim - a number a reader could go and check -
    so two read halves outrank one, and one outranks none.

        0  both halves modelled: benchmark flights, catalogue stay
        1  one half read
        2  both halves read

    An AGED read still counts as read. ``evidence_used`` is the collector's
    "may this price a card" test, and an observation too old to be called live
    is still an observation somebody made; the age is reported separately by
    the card's own freshness chip. Age is not a reason to prefer a benchmark
    for the same holiday, which is precisely the "this was read, and here is
    when" case the chip exists to describe.

    This is the ranking key only. It says which pair a card is built on, never
    whether the resort makes a card at all: budget filtering, the ranking of
    one resort against another, and the value score are untouched by it.
    """
    return (
        int(bool(option.get("evidence_used")))
        + int(option.get("hotel_rate") is not None)
    )


def destination_cabins(
    config: HolidayConfig, destination: HolidayDestination
) -> tuple[str, ...]:
    """Cabins the report prices for one destination.

    Single source of truth for the ``(airport, cabin)`` lookup key that
    ``collect_holiday_deals`` builds. The live-evidence contract is derived
    from this function, so a hunt aimed by the contract cannot be aimed at a
    cabin the report will never price.

    Since the 2026-09-28 rule the answer is DERIVED, one cabin per
    destination: BUSINESS only when the destination's London flight time is
    over 8 hours, else ECONOMY, and never premium economy (``cabin.py``).
    A config's own cabin fields are legacy and never consulted here.
    """
    return (destination_cabin(destination),)


#: Outbound months that make a trip a summer trip. The renderer used this test
#: inline (plus the title words below) long before the catalogue became
#: seasonal; it is one predicate now so the catalogue, the strict filters, the
#: evidence contract and the page can never disagree about the season.
SUMMER_TRIP_MONTHS: frozenset[int] = frozenset({6, 7, 8})
_SUMMER_TITLE_WORDS: tuple[str, ...] = ("summer", "july", "august")


def is_summer_trip(config: Any) -> bool:
    """True for a June-August departure, or a report titled summer/July/August."""
    for day in getattr(config, "outbound_dates", ()) or ():
        parts = str(day).split("-")
        if len(parts) >= 2 and parts[1].isdigit() and int(parts[1]) in SUMMER_TRIP_MONTHS:
            return True
    title = str(getattr(config, "report_title", "") or "").lower()
    return any(word in title for word in _SUMMER_TITLE_WORDS)


def resort_catalog(config: Any = None) -> dict[str, list[dict[str, Any]]]:
    """The resort catalogue a report prices resorts from.

    A winter (or unspecified) trip prices ``WINTER_RESORT_CATALOG``, exactly as
    every report did before 2026-09-29. A summer trip prices
    ``SUMMER_RESORT_CATALOG`` layered over it: the long-haul July beach resorts
    (Lombok, the Gulf of Thailand, Khao Lak) whose rates were read for July,
    plus the winter entries unchanged, so a July config that still names a
    short-haul key prices it as before. The two catalogues share no key
    (tested), so layering never overwrites a winter resort.

    Why the split exists: a single catalogue meant the December planner, whose
    config lists ``phuket`` and ``krabi``, would have priced July-rate Thai
    resorts in December and aimed its hunt at their airports. Destinations
    absent from the selected catalogue (doha, muscat, the Far East watch keys)
    have no card, which is why ``card_lookup_keys`` excludes their airports.
    """
    if config is not None and is_summer_trip(config):
        return _SUMMER_TRIP_CATALOG
    return WINTER_RESORT_CATALOG


#: Name reported as the contract's provenance for a winter trip. Kept as a
#: constant for callers that predate the seasonal split.
RESORT_CATALOG_NAME = "WINTER_RESORT_CATALOG"
#: ...and for a summer trip, which prices the summer entries over the winter ones.
SUMMER_RESORT_CATALOG_NAME = "SUMMER_RESORT_CATALOG+WINTER_RESORT_CATALOG"


def resort_catalog_name(config: Any = None) -> str:
    """Which catalogue ``resort_catalog(config)`` returned, for the contract."""
    if config is not None and is_summer_trip(config):
        return SUMMER_RESORT_CATALOG_NAME
    return RESORT_CATALOG_NAME


def card_lookup_keys(config: HolidayConfig) -> tuple[tuple[str, str], ...]:
    """Every ``(airport, cabin)`` pair the report can ever promote a fare for.

    Deliberately restricted to airports whose resorts survive
    ``filter_resorts``. A fare harvested for an airport whose resort list is
    filtered out is loaded by the evidence seam and then never looked up —
    spend with no possible card. Measured 2026-09-23: the private hunt
    expended reads on six such airports (AGA, CAI, DOH, FNC, MCT, MLA) while
    two airports that do carry cards (ACE, PFO) were never hunted, leaving
    19 of 27 December cards on benchmarks for want of an aimed crawl.
    """
    catalog = resort_catalog(config)
    summer = is_summer_trip(config)
    keys: set[tuple[str, str]] = set()
    for destination in config.destinations:
        # Same catalogue AND same season as collect_holiday_deals: a summer
        # resort with an unheated pool survives there, so it must here too or
        # the hunt is never aimed at a card the report prices.
        resorts, _dropped = filter_resorts(
            catalog.get(destination.key.lower(), []), is_summer=summer,
            island=destination.key.lower() in ISLAND_RULE_KEYS,
        )
        cabins = destination_cabins(config, destination)
        for resort in resorts:
            for cabin in cabins:
                keys.add(
                    (str(resort["airport"]).strip().upper(), str(cabin).strip().upper())
                )
    return tuple(sorted(keys))


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
    #: The basis the flight figure was displayed on. A benchmark is a
    #: benchmark; only a whole-party, exact-date amount may be labelled
    #: verified. Carrying the basis on the deal is what lets the report
    #: state it instead of implying all flight figures are equivalent.
    flight_price_basis: str = "benchmark_supplied"
    cabin_class: str = "ECONOMY"
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
    # How the HOTEL rate on this card was obtained, from the resort data's
    # own confidence field ("market-supported" = a rate read for these dates,
    # "estimate" = an estimate from the nearest dates on sale). The single
    # ``confidence`` field above is the FLIGHT basis whenever live evidence
    # is used, so the hotel's own basis needs its own field (F4, 2026-10-03).
    hotel_rate_basis: str = ""
    #: Google (or another named site's) rating read for this property, with
    #: its source and review count (owner brief 2026-10-03, H4).
    hotel_ratings: tuple = ()
    #: Facts the engine read for this property (nearest mosque with its drive
    #: time, kids' club, pools, restaurants), each with its own source.
    hotel_facts: tuple = ()
    #: A unit check that refused ONE room for the party where the property then
    #: sold two rooms on one booking. Informational, not a removal
    #: (owner brief 2026-10-03, H4b).
    hotel_unit_note: str = ""
    #: The booking shape of the rate that priced this card, when one did.
    booking_shape_seen: str = ""
    #: A unit bigger than the party needs, e.g. "4-bedroom villa — more space
    #: than 5 need" (owner brief 2026-10-03, H6).
    unit_space_note: str = ""
    #: Which value-score inputs came from read facts rather than the registry
    #: or its defaults (owner brief 2026-10-03, H5).
    value_score_from_facts: tuple = ()
    #: The loader's evidence for this resort and these dates, when one was
    #: read (owner brief 2026-10-03, H3). None means the stay is priced from
    #: the catalogue, exactly as before the seam existed.
    hotel_evidence: Any = None
    source_url: str = ""
    # When a live whole-party fare is used, the carrier the provider actually
    # displayed (may differ from the benchmark carrier); empty on benchmarks.
    live_carrier: str = ""
    live_observed_at: str = ""
    # Real discount intelligence: the SAME resort at summer peak prices
    # (same rooms/nights/party) and property-level cross-vendor links.
    peak_summer_total_gbp: float = 0.0
    # True only when the peak comparison is an OBSERVED earlier price for the
    # same resort and dates, from history. A modelled benchmark peak (the
    # default) may be compared, but the difference it produces is not a
    # "saving" and must never be worded as one (owner rule, 2026-10-02).
    peak_observed: bool = False
    compare_url: str = ""   # Google Hotels property card — all vendors' prices
    booking_deep_url: str = ""  # Booking.com property-targeted, dated
    expedia_deep_url: str = ""  # Expedia property-targeted, dated
    # Room architecture of THIS quote. A 2-bed family suite and 3 separate
    # rooms are different products: prices must never merge into one series.
    unit_architecture: str = ""
    # How many rooms the quote's single booking actually uses. 1 or 2 are a
    # one-booking family unit; 3 is not a unit at all and unknown is not
    # verified, so both are filtered out by the one-booking rule and a card is
    # never priced on either.
    rooms_in_unit: Optional[int] = None
    # Recovered criteria model (from the winter tracker contract):
    # curated 0-10 benchmark scores per resort. Honest, review-required —
    # presented as benchmarks, never as live observations.
    actual_luxury_score: float = 0.0
    food_reality_score: float = 0.0
    winter_facilities_score: float = 0.0
    mosque_location_score: float = 0.0
    activities_score: float = 0.0
    flight_quality_score: float = 0.0
    value_score: float = 0.0
    mosque_name: str = ""
    mosque_walk_minutes: int = 0
    food_review_summary: str = ""
    #: True only when the value score was computed from this resort's own
    #: curated criteria. False means every input fell back to a neutral
    #: default, so the number measured only the price — not shown, and listed
    #: as not verified instead (owner rule 2026-10-02).
    value_score_verified: bool = False
    indoor_activity_count: int = 0
    heated_indoor_pool: bool = False
    deal_class: str = ""
    # Rank position by the winter-first value score within the LAST collect
    # run (1 = best). Gives history a stable, score-derived ordinal so trend
    # deltas read "rose/fell in value rank", never just raw price wobble.
    rank_value: int = 0
    # The departure airport THIS quote was priced from. Configs list several
    # origins; a benchmark only ever prices the first, while an observed fare
    # may win from any of them, so the card has to say which one won.
    origin: str = ""
    # How the flight gets there when there is no London nonstop (e.g. "1 stop
    # via Bangkok"). Empty means a nonstop route, which is what the card's
    # rationale claims only when this is empty.
    routing: str = ""
    # Long-haul only: (a) Business, (b) Economy on the same route, (c) Economy
    # with a Doha/Muscat stopover each way, each a whole-party total with its
    # own budget flag. Empty for short haul, which prices one cabin.
    flight_options: tuple = ()
    # Island resorts: every board basis the hotel sells, each priced for this
    # card's nights ({"basis", "label", "hotel_cost"}). Empty elsewhere.
    board_options: tuple = ()
    # Calendar months the destination is in monsoon season (empty = none). A
    # monsoon resort may be priced, but never wins the climate award for a
    # travel month in this set, and its card carries a visible warning.
    monsoon_months: tuple[int, ...] = ()
    # Booking terms, shown ONLY when verified (owner rule 2026-10-02). Every
    # field defaults to None = not verified, and the card lists the unknowns
    # as "not verified: …" rather than inventing a value. ``atol_protected`` is
    # the one tri-state: True/False are facts, None is unknown.
    free_cancellation_until: Optional[str] = None
    deposit_payment: Optional[str] = None
    checked_baggage: Optional[str] = None
    atol_protected: Optional[bool] = None
    beach_access: Optional[str] = None
    pool: Optional[str] = None

    @property
    def vs_peak_saving_gbp(self) -> float:
        return round(self.peak_summer_total_gbp - self.total_package_price_gbp, 2)

    @property
    def vs_peak_pct(self) -> float:
        """% below the same resort's summer-peak package total."""
        if self.peak_summer_total_gbp > 0:
            return round((1 - self.total_package_price_gbp / self.peak_summer_total_gbp) * 100)
        return 0


# Recovered winter-tracker value model. Weights (must sum ~10 before the
# ×10 normalisation to 0-100): price 30%, winter 25%, luxury 15%, food 15%,
# mosque 10%, activities 5%; minus flight-quality penalty max(0, 7-fq)*1.5.
# Winter honesty caps: 0 indoor activities -> winter<=4; 1 -> <=6; no heated
# indoor pool -> <=6; ghost-town/heavily-reduced winter concept -> <=3.

def _classify_deal_price(true_pp: float) -> str:
    """Per-person deal classification from the original tracker contract."""
    if true_pp <= 350:
        return "ULTRA_BARGAIN"
    if true_pp <= 450:
        return "EXCEPTIONAL"
    if true_pp <= 500:
        return "VERY_STRONG"
    if true_pp <= 550:
        return "GOOD"
    if true_pp <= 600:
        return "ACCEPTABLE_PREMIUM"
    return "SPLURGE_WATCH_FOR_PRICE_DROP"


#: The "Best Overall Value" award is only given to a card scoring at least this
#: much (owner rule 2026-10-02). Under it the card's own line says the stay is
#: a splurge, so crowning it "best value" is a contradiction; below the
#: threshold the report simply shows no value award.
VALUE_AWARD_MIN_SCORE: float = 50.0

#: The deal class as a reader-facing phrase. The card says what the number
#: MEANS rather than printing the SHOUTED acronym beside it, which is what made
#: "VALUE 35/100 · SPLURGE WATCH FOR PRICE DROP" read as a contradiction.
_DEAL_CLASS_PHRASES: dict[str, str] = {
    "ULTRA_BARGAIN": "an ultra bargain",
    "EXCEPTIONAL": "exceptional value",
    "VERY_STRONG": "a very strong deal",
    "GOOD": "a good deal",
    "ACCEPTABLE_PREMIUM": "an acceptable premium",
    "SPLURGE_WATCH_FOR_PRICE_DROP": "a luxury splurge, watch for a price drop",
}


def _deal_class_words(deal_class: str) -> str:
    """A deal class in words, falling back to the raw value if unknown."""
    key = str(deal_class or "")
    if key in _DEAL_CLASS_PHRASES:
        return _DEAL_CLASS_PHRASES[key]
    return key.replace("_", " ").lower() or "not assessed"


#: Weather floor (2026-09-22 user mandate): a beach destination whose
#: December average ambient temperature is below this cannot deliver a beach
#: holiday, so its vs-peak discount is de-weighted in ranking and its value
#: score takes a hard penalty. Red Sea, Canary and Middle East destinations
#: (21–26°C) are the ones that should float up for winter searches.
WINTER_SUN_FLOOR_C: float = 20.0

#: Gmail clips an e-mail over 102 KB, and a clipped card is a card the reader
#: cannot click. Cards stop being added once the report reaches this many
#: bytes, so enriching a card can never silently clip the report.
#:
#: Raised 88_000 -> 96_000 on 2026-09-30 (owner decision): the report gained a
#: per-hub Economy-stopover pricing link on every long-haul card that has no read
#: fare, and at 88 KB the December report was already full, so a card was being
#: dropped. The renderer stops before appending a card once it is over budget, so
#: the finished e-mail lands about one card above this: 96 KB keeps the whole
#: report under the 100 KB guard and inside Gmail's 102 KB clip.
EMAIL_HTML_BUDGET_BYTES: int = 96_000

#: ...but a budget must never produce a one-card report. This many cards are
#: always rendered, budget or not.
MIN_RENDERED_HOTEL_CARDS: int = 5

#: How many times a repeated ``style`` value must appear before hoisting it
#: into the shared block pays. At 2 the class (``class="p12"``, 11 bytes)
#: already costs less than the rule it replaces; below that the swap is noise.
_STYLE_HOIST_MIN_USES: int = 2

#: A hoisted rule shorter than this is not worth a selector. A one-declaration
#: rule like ``.p3{color:#cbd5e1}`` is already shorter inline, and hoisting it
#: would ADD bytes while making the markup unreadable.
_STYLE_HOIST_MIN_LEN: int = 10

_STYLE_ATTR_RE = re.compile(r'style="([^"]*)"')

#: The hoist threshold the BYTE BUDGET is measured against, pinned to the
#: production value rather than read from ``_STYLE_HOIST_MIN_USES``. The budget
#: is about the e-mail that ships; a caller that has turned the hoist off is
#: asking what the report SAYS, and must not be charged a card for markup the
#: sent e-mail never carries.
_SHIPPED_STYLE_HOIST_MIN_USES: int = 2

#: Bytes held back for the markup appended AFTER the last card: the
#: dropped-card notice (at most one table) and the closing tags. Without this
#: reserve the notice that explains the cut is itself what tips the e-mail over
#: the cap it exists to describe.
_CLOSING_TAIL_ALLOWANCE_BYTES: int = 1_200


def _shipped_bytes(chunks: Sequence[str]) -> int:
    """Bytes the e-mail will actually weigh, not the bytes it weighs so far.

    The renderer builds the report as a list of markup chunks and hoists the
    repeated ``style`` rules into one block at the very end. Measuring the
    chunks on their own therefore OVER-states the finished e-mail by roughly a
    third, and a budget fed that number drops a card the sent e-mail would have
    fitted comfortably. This measures the hoisted string — the payload as it
    leaves — so the number the budget is compared against is the number that is
    e-mailed.
    """
    return len(
        _hoist_repeated_styles(
            "".join(chunks), min_uses=_SHIPPED_STYLE_HOIST_MIN_USES
        ).encode("utf-8")
    )


def _normalise_style_value(value: str) -> str:
    """Canonical form of a CSS declaration list, so equal rules match.

    The renderer writes ``margin:0 0 6px 0;`` by hand in one place and
    ``margin:0 0 6px`` in another, and pads with spaces after semicolons.
    Those are the same rule to a browser, so they must be the same key here
    or the hoist emits two classes for one style.
    """
    value = re.sub(r"\s+", " ", value.strip())
    value = re.sub(r"\s*;\s*", ";", value)
    value = re.sub(r";\s*$", "", value)
    # `margin:0 0 6px 0` is the four-value form of `margin:0 0 6px`.
    value = re.sub(r"\b0 0 (\d+(?:\.\d+)?(?:px|em|rem|%)) 0\b", r"0 0 \1", value)
    value = re.sub(r"\s*:\s*", ":", value)
    return value.strip()


def _hoist_repeated_styles(html: str, min_uses: Optional[int] = None) -> str:
    """Move repeated ``style`` values into one ``<style>`` block.

    The report's weight was markup, not content: 42.9 % of the December
    payload was ``style`` attributes, and the same short declarations were
    re-serialised in full on every element (``color:#cbd5e1;`` 78 times,
    ``color:#0f172a;`` 76). Each occurrence cost the full rule again.

    Hoisting replaces those with a class reference, so the rule is paid for
    once. This is why the December report drops from 99.1 % of the byte budget
    to about 69 % WITHOUT dropping a card — the headroom comes from markup
    weight, not from showing the reader fewer deals.

    Values are normalised first (see ``_normalise_style_value``) so
    cosmetically different spellings of one rule collapse into one class.

    Only whole ``style="..."`` attributes are replaced, and only with an exact
    match on the normalised value, so an element's own inline rule wins where
    both exist and no attribute is ever merged or half-rewritten. Anything
    used fewer than ``_STYLE_HOIST_MIN_USES`` times, or too short to be worth
    a selector, stays inline: a rule with no selector is a rule that    silently stops applying, and colour here carries meaning (live vs stale vs
    unverified), so an unstyled label is a wrong report rather than an ugly one.

    ``min_uses`` overrides the threshold. The byte budget passes the production
    value rather than the module global (see ``_shipped_bytes``): turning the
    hoist off is a question about what the report SAYS, not permission to
    charge the budget for a size saving the shipped e-mail never gets.
    """
    threshold = _STYLE_HOIST_MIN_USES if min_uses is None else min_uses
    if "</head>" not in html or not _STYLE_ATTR_RE.search(html):
        return html

    counts: dict[str, int] = {}
    for match in _STYLE_ATTR_RE.finditer(html):
        value = _normalise_style_value(match.group(1))
        counts[value] = counts.get(value, 0) + 1

    # Frequent first, so the numbering reads as "biggest wins are p0, p1...".
    # Ties break on the value itself to keep the block byte-stable across runs:
    # the same input must always produce the same HTML, or every run looks like
    # a diff.
    order = sorted(
        (
            value
            for value, uses in counts.items()
            if uses >= threshold and len(value) >= _STYLE_HOIST_MIN_LEN
        ),
        key=lambda value: (-counts[value], value),
    )
    if not order:
        return html

    # Deterministic short class names: p0, p1, ... Collisions with anything the
    # renderer already emits are checked rather than assumed.
    existing = set(re.findall(r'class="([^"]*)"', html))
    used_names: set[str] = set()
    mapping: dict[str, str] = {}
    for index, value in enumerate(order):
        name = f"p{index}"
        while name in existing or name in used_names:
            name += "x"
        used_names.add(name)
        mapping[value] = name

    rules = "".join(f".{mapping[v]}{{{v}}}" for v in order)
    out = _STYLE_ATTR_RE.sub(
        lambda m: (
            f'class="{mapping[_normalise_style_value(m.group(1))]}"'
            if _normalise_style_value(m.group(1)) in mapping
            else m.group(0)
        ),
        html,
    )
    return out.replace("</head>", f"<style>{rules}</style></head>", 1)

#: Months in which the trip itself experiences winter (Nov–Mar). The
#: December-temperature floor exists to stop a cold beach riding a big
#: discount up a WINTER search; a July trip to the same resort is 30°C+ and
#: must not be penalised for December weather.
WINTER_TRIP_MONTHS: frozenset[int] = frozenset({11, 12, 1, 2, 3})


#: Full month names, 1-indexed via ``_MONTH_NAMES[month - 1]``.
_MONTH_NAMES = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)


def deal_travel_month(deal: Any) -> Optional[int]:
    """Calendar month of the deal's outbound date, or None if unparseable."""
    try:
        return int(str(getattr(deal, "outbound_date", ""))[5:7])
    except (TypeError, ValueError, IndexError):
        return None


#: Approximate wet / storm climatology per destination key, as calendar
#: months. APPROXIMATE CLIMATOLOGY: regional seasons vary year to year, so
#: this warns, it does not forbid. An explicit empty tuple is a destination
#: with no flagged wet/storm season here — a declared fact, not a gap. A
#: resort may override with its own ``monsoon_months``; otherwise the deal
#: inherits its destination's months. (Owner list, 2026-10-02.)
WET_MONTHS_BY_DESTINATION: dict[str, tuple[int, ...]] = {
    # Winter catalogue
    "antalya": (), "malta": (), "taghazout": (), "hurghada": (), "cairo": (),
    "muscat": (), "doha": (), "tenerife": (), "madeira": (), "lanzarote": (),
    "cape_verde": (), "fuerteventura": (), "gran_canaria": (), "paphos": (),
    "zanzibar": (4, 5, 11),          # long rains Apr-May, short rains Nov
    "mauritius": (1, 2, 3),          # cyclone season
    "riviera_maya": (6, 7, 8, 9, 10, 11),  # Atlantic hurricane season
    # Summer catalogue
    "lombok": (1, 2, 3, 11, 12),
    "koh_samui": (10, 11, 12),       # Gulf side: wetter late in the year
    "koh_phangan": (10, 11, 12),
    "khao_lak": (5, 6, 7, 8, 9, 10),  # Andaman side SW monsoon
    # Far East watch keys (destination watches, no cards)
    "phuket": (5, 6, 7, 8, 9, 10),
    "krabi": (5, 6, 7, 8, 9, 10),
    "langkawi": (9, 10, 11),
    "penang": (9, 10, 11),
    "singapore": (1, 11, 12),
    "phu_quoc": (5, 6, 7, 8, 9, 10),
    "bali": (1, 2, 3, 11, 12),
    "da_nang": (9, 10, 11, 12),
    "kota_kinabalu": (1, 2, 10, 11, 12),  # Sabah north-east monsoon
    "japan": (),                     # no single wet-season flag for the watch
}


def _parse_iso_instant(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 instant (``Z`` accepted); None if unparseable."""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def observation_age_hours(observed_at: Any, generated_at: Any) -> Optional[float]:
    """Hours between an observation and the report's generation instant.

    The age the reader sees is measured at RENDER time, against the same one
    threshold (``live_verify.EVIDENCE_MAX_AGE_HOURS``) the planner's
    ``live_evidence_stale`` uses, so a fare that was fresh when loaded but has
    aged by the time the report is built is labelled with its real age.
    """
    observed = _parse_iso_instant(observed_at)
    generated = _parse_iso_instant(generated_at)
    if observed is None or generated is None:
        return None
    return (generated - observed).total_seconds() / 3600.0


def relative_age_label(hours: Optional[float]) -> str:
    """Human age text: "3 days ago", "12 hours ago", "just now"."""
    if hours is None:
        return ""
    if hours < 0:
        hours = 0.0
    if hours < 1:
        return "just now"
    if hours < 24:
        return f"{int(hours)} hours ago"
    days = int(hours // 24)
    return "1 day ago" if days == 1 else f"{days} days ago"


def deal_in_monsoon(deal: Any) -> bool:
    """True when the deal's travel month is a wet/storm month at the resort.

    A resort's own ``monsoon_months`` wins; otherwise the deal inherits its
    destination's approximate climatology. An empty result means no season is
    flagged, never an assumption that the destination is dry.
    """
    month = deal_travel_month(deal)
    if month is None:
        return False
    months = tuple(getattr(deal, "monsoon_months", ()) or ())
    if not months:
        months = WET_MONTHS_BY_DESTINATION.get(
            str(getattr(deal, "destination_key", "") or "").lower(), ()
        )
    return month in months


def _dec_temp_for_floor(outbound_date: str, dec_avg_temp_c: float) -> Optional[float]:
    """December average the weather floor may use for THIS trip, or None.

    Winter trips (Nov–Mar departures) get the floor; summer trips are
    exempt — the mandate penalises cold WINTER beach destinations, not
    resorts that are merely cold in a month the reader isn't travelling.
    """
    try:
        month = int(outbound_date[5:7])
    except (TypeError, ValueError, IndexError):
        return dec_avg_temp_c
    return dec_avg_temp_c if month in WINTER_TRIP_MONTHS else None


def compute_value_score(
    *,
    true_pp: float,
    luxury: float,
    food: float,
    winter: float,
    mosque: float,
    activities: float,
    flight_quality: float,
    indoor_activity_count: int,
    heated_indoor_pool: bool,
    winter_concept: str = "",
    dec_avg_temp_c: Optional[float] = None,
) -> float:
    """0-100 winter-first value score (weights from the original tracker).

    ``dec_avg_temp_c`` (December average ambient °C) applies the weather
    floor: below 20°C the score loses 1.5 points per degree under the floor
    (capped at −15) — a 50% discount is invalid if the weather makes a beach
    holiday impossible.
    """
    for name, v in (("luxury", luxury), ("food", food), ("winter", winter),
                    ("mosque", mosque), ("activities", activities),
                    ("flight_quality", flight_quality)):
        if not 0 <= v <= 10:
            raise ValueError(f"{name} score must be 0-10")
    # Winter honesty caps.
    if indoor_activity_count == 0:
        winter = min(winter, 4.0)
    elif indoor_activity_count == 1:
        winter = min(winter, 6.0)
    if not heated_indoor_pool:
        winter = min(winter, 6.0)
    if winter_concept.upper() in {"GHOST_TOWN", "HEAVILY_REDUCED"}:
        winter = min(winter, 3.0)
    price_score = max(0.0, min(10.0, (700.0 - true_pp) / 35.0))
    flight_penalty = max(0.0, 7.0 - flight_quality) * 1.5
    # Weather floor: hard penalty for beach resorts that cannot deliver a
    # beach in December. Antalya (15°C) drops; Hurghada (24°C) does not.
    temp_penalty = 0.0
    if dec_avg_temp_c is not None and dec_avg_temp_c < WINTER_SUN_FLOOR_C:
        temp_penalty = min(15.0, (WINTER_SUN_FLOOR_C - dec_avg_temp_c) * 1.5)
    value = (
        price_score * 3.0
        + winter * 2.5
        + luxury * 1.5
        + food * 1.5
        + mosque * 1.0
        + activities * 0.5
    ) - flight_penalty - temp_penalty
    return round(max(0.0, min(100.0, value)), 1)


# December climate reality (ambient air / sea °C) plus beach geography.
# Peak-summer room/flight benchmarks above each resort enable REAL discount
# intelligence: December total vs the SAME resort in July/August (same rooms,
# nights, party). Rates are market-supported benchmarks, never live quotes.
# Curated 0-10 criteria scores follow the winter-tracker contract: luxury,
# food reality, mosque access, winter facilities, activities, flight quality.
# A heated pool does NOT make a 15°C destination a winter-sun holiday:
# stepping out of 28°C water into a 15°C wind is miserable.
# Summer climate reality (ambient air / sea °C).
SUMMER_WEATHER: dict[str, tuple[tuple[int, int], int]] = {
    "antalya": ((32, 36), 28),
    "tenerife": ((26, 29), 23),
    "fuerteventura": ((26, 28), 22),
    "gran_canaria": ((26, 28), 22),
    "paphos": ((31, 34), 27),
    "hurghada": ((34, 37), 29),
    "malta": ((30, 33), 26),
    "taghazout": ((26, 28), 21),
    "doha": ((38, 42), 32),
    "muscat": ((36, 40), 30),
    "lanzarote": ((26, 29), 22),
    "madeira": ((24, 26), 22),
    "cairo": ((34, 37), 0),
    # July long-haul keys (2026-09-29). Air is the WMO 1991-2020 July mean
    # daily minimum-maximum (via Wikipedia climate tables); sea is the July
    # average from seatemperature.org. Koh Phangan uses the Ko Samui station
    # (about 15 km away) and Khao Lak the Takua Pa station and Phuket sea.
    "lombok": ((19, 30), 27),        # Mataram 19.4-29.7°C, 77 mm; sea 26.9°C
    "koh_samui": ((25, 32), 30),     # Ko Samui 25.1-32.3°C, 117 mm; sea 29.7°C
    "koh_phangan": ((25, 32), 30),   # Ko Samui station
    "khao_lak": ((25, 32), 30),      # Takua Pa 24.6-31.5°C but 466 mm / 19.7 rain days: SW monsoon
    "zanzibar": ((22, 29), 26),      # Zanzibar City 22.1-29.0°C, 31 mm (WMO 1991-2020); sea Nungwi 25.9°C
}


WINTER_RESORT_CATALOG: dict[str, list[dict[str, Any]]] = {
    "antalya": [
        {
            "name": "Lara Barut Collection",
            "destination_label": "Antalya Riviera, Turkey",
            "stars": 5,
            "board": "Ultra All Inclusive",
            "base_nightly_room_rate_gbp": 115.0,
            "peak_summer_nightly_room_rate_gbp": 260.0,
            "airport": "AYT",
            "airline": "SunExpress / Pegasus",
            "flight_benchmark_5pax_gbp": 648.0,
            "peak_summer_flight_5pax_gbp": 1180.0,
            "highlights": ("Heated seawater pool (28°C)", "8 à la carte restaurants", "Thalasso spa", "Private sandy beach"),
            "hotel_url": "https://barutlara.com/",  # baruthotels.com/lara-barut-collection 404 (verified 2026-09-22)
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
            "peak_summer_nightly_room_rate_gbp": 210.0,
            "airport": "AYT",
            "airline": "SunExpress / Pegasus",
            "flight_benchmark_5pax_gbp": 648.0,
            "peak_summer_flight_5pax_gbp": 1180.0,
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
            "peak_summer_nightly_room_rate_gbp": 330.0,
            "airport": "AYT",
            "airline": "SunExpress / Pegasus",
            "flight_benchmark_5pax_gbp": 648.0,
            "peak_summer_flight_5pax_gbp": 1180.0,
            "highlights": ("Palatial architecture", "7,500m² spa", "Heated Olympic indoor pool", "Private lagoon"),
            "hotel_url": "https://www.titanic.com.tr/titanicmardanpalace",
            "dec_ambient_c": (15, 17),
            "sea_temp_c": 19,
            "beach": "Sandy lagoon but 15-17°C — spa trip",
            "transfer_gbp": 25.0,
            "confidence": "market-supported",
        },
    ],
    # ── EXPANDED GEOGRAPHY (Dec 2026): Fuerteventura, Gran Canaria, Paphos.
    # Route authority verified: FUE nonstops easyJet/Jet2/Ryanair (LGW/STN/LTN);
    # LPA nonstops easyJet/Jet2/Ryanair/BA (LGW/LTN/STN); PFO nonstops
    # Ryanair/Jet2/TUI (STN) + BA/easyJet (LGW). No UAE (user removal).
    "fuerteventura": [
        {
            "name": "Sheraton Fuerteventura Beach, Golf & Spa Resort",
            "destination_label": "Caleta de Fuste, Fuerteventura",
            "stars": 5,
            "board": "Half Board",
            "base_nightly_room_rate_gbp": 95.0,
            "peak_summer_nightly_room_rate_gbp": 210.0,
            "airport": "FUE",
            "airline": "easyJet / Jet2 / Ryanair",
            "flight_benchmark_5pax_gbp": 1150.0,
            "peak_summer_flight_5pax_gbp": 1700.0,
            "highlights": ("Horseshoe sand beach at the door", "Heated thalasso spa", "Golf on site", "Kids club"),
            "hotel_url": "https://www.marriott.com/en-us/hotels/fuesi-sheraton-fuerteventura-beach-golf-and-spa-resort/overview/",  # property page; generic brand page 404 (verified 2026-09-22)
            "dec_ambient_c": (21, 23),
            "sea_temp_c": 20,
            "beach": "Caleta de Fuste man-made horseshoe — calm, genuinely walkable",
            "transfer_gbp": 15.0,
            "confidence": "market-supported",
        },
        {
            "name": "Gran Hotel Atlantis Bahía Real",
            "destination_label": "Corralejo, Fuerteventura",
            "stars": 5,
            "board": "Half Board",
            "base_nightly_room_rate_gbp": 120.0,
            "peak_summer_nightly_room_rate_gbp": 250.0,
            "airport": "FUE",
            "airline": "easyJet / Jet2 / Ryanair",
            "flight_benchmark_5pax_gbp": 1150.0,
            "peak_summer_flight_5pax_gbp": 1700.0,
            "highlights": ("Corralejo beachfront", "Grand spa circuit", "À-la-carte dining", "Adults + family zones"),
            "hotel_url": "https://atlantisbahiareal.com/",
            "dec_ambient_c": (21, 23),
            "sea_temp_c": 20,
            "beach": "Corralejo sand at the gate; dunes park north",
            "transfer_gbp": 30.0,
            "confidence": "market-supported",
        },
    ],
    "gran_canaria": [
        {
            "name": "Lopesan Costa Meloneras Resort & Spa",
            "destination_label": "Meloneras, Gran Canaria",
            "stars": 5,
            "board": "Half Board",
            "base_nightly_room_rate_gbp": 110.0,
            "peak_summer_nightly_room_rate_gbp": 230.0,
            "airport": "LPA",
            "airline": "easyJet / Jet2 / Ryanair / BA",
            "flight_benchmark_5pax_gbp": 1100.0,
            "peak_summer_flight_5pax_gbp": 1650.0,
            "highlights": ("Maspalomas-dunes side", "Lagoon-style pool estate", "Heated winter pools", "Spa & casino"),
            "hotel_url": "https://www.lopesan.com/en/",
            "dec_ambient_c": (22, 24),
            "sea_temp_c": 21,
            "beach": "Meloneras golden sand via promenade — walkable from pools",
            "transfer_gbp": 35.0,
            "confidence": "market-supported",
        },
        {
            "name": "Seaside Palm Beach",
            "destination_label": "Playa del Inglés, Gran Canaria",
            "stars": 5,
            "board": "Half Board",
            "base_nightly_room_rate_gbp": 105.0,
            "peak_summer_nightly_room_rate_gbp": 220.0,
            "airport": "LPA",
            "airline": "easyJet / Jet2 / Ryanair / BA",
            "flight_benchmark_5pax_gbp": 1100.0,
            "peak_summer_flight_5pax_gbp": 1650.0,
            "highlights": ("Beachfront on Playa del Inglés", "Elegant interiors", "Strong dining reviews", "Spa"),
            "hotel_url": "https://www.seasidehotels.com/en/",
            "dec_ambient_c": (22, 24),
            "sea_temp_c": 21,
            "beach": "Playa del Inglés sand at the foot of the gardens",
            "transfer_gbp": 35.0,
            "confidence": "market-supported",
        },
    ],
    "paphos": [
        {
            "name": "Elysium Hotel",
            "destination_label": "Paphos, Cyprus (Archaeological Park side)",
            "stars": 5,
            "board": "Bed & Breakfast",
            "base_nightly_room_rate_gbp": 100.0,
            "peak_summer_nightly_room_rate_gbp": 210.0,
            "airport": "PFO",
            "airline": "Ryanair / Jet2 / BA",
            "flight_benchmark_5pax_gbp": 950.0,
            "peak_summer_flight_5pax_gbp": 1400.0,
            "highlights": ("Overlooks ancient tombs", "Opulent spa", "Rooftop bar", "Harbour 15 min walk"),
            "hotel_url": "https://elysiumhotel.com/",
            "dec_ambient_c": (20, 22),
            "sea_temp_c": 20,
            "beach": "Small sandy cove + rocky platforms — honest Paphos shoreline",
            "transfer_gbp": 20.0,
            "confidence": "market-supported",
        },
        {
            "name": "Annabelle Hotel",
            "destination_label": "Paphos, Cyprus (Harbourfront)",
            "stars": 5,
            "board": "Half Board",
            "base_nightly_room_rate_gbp": 105.0,
            "peak_summer_nightly_room_rate_gbp": 220.0,
            "airport": "PFO",
            "airline": "Ryanair / Jet2 / BA",
            "flight_benchmark_5pax_gbp": 950.0,
            "peak_summer_flight_5pax_gbp": 1400.0,
            "highlights": ("Harbourfront gardens", "Acclaimed dining", "Lagoon pools", "Path to Paphos castle"),
            "hotel_url": "https://annabelle.com/",
            "dec_ambient_c": (20, 22),
            "sea_temp_c": 20,
            "beach": "Seafront lawns; small lagoon beach by the harbour",
            "transfer_gbp": 20.0,
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
            "peak_summer_nightly_room_rate_gbp": 265.0,
            "airport": "HRG",
            "airline": "easyJet / Wizz Air",
            "flight_benchmark_5pax_gbp": 1350.0,
            "peak_summer_flight_5pax_gbp": 2150.0,
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
            "peak_summer_nightly_room_rate_gbp": 225.0,
            "airport": "HRG",
            "airline": "easyJet / Wizz Air",
            "flight_benchmark_5pax_gbp": 1350.0,
            "peak_summer_flight_5pax_gbp": 2150.0,
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
            "peak_summer_nightly_room_rate_gbp": 280.0,
            "airport": "TFS",
            "airline": "Jet2 / easyJet",
            "flight_benchmark_5pax_gbp": 1250.0,
            "peak_summer_flight_5pax_gbp": 1980.0,
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
            "peak_summer_nightly_room_rate_gbp": 310.0,
            "airport": "ACE",
            "airline": "Jet2 / easyJet",
            "flight_benchmark_5pax_gbp": 1300.0,
            "peak_summer_flight_5pax_gbp": 2050.0,
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
            "peak_summer_nightly_room_rate_gbp": 185.0,
            "airport": "CAI",
            "airline": "British Airways / EgyptAir",
            "flight_benchmark_5pax_gbp": 1442.0,
            "peak_summer_flight_5pax_gbp": 2050.0,
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
            "peak_summer_nightly_room_rate_gbp": 220.0,
            "airport": "CAI",
            "airline": "British Airways / EgyptAir",
            "flight_benchmark_5pax_gbp": 1442.0,
            "peak_summer_flight_5pax_gbp": 2050.0,
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
            "peak_summer_nightly_room_rate_gbp": 170.0,
            "airport": "CAI",
            "airline": "British Airways / EgyptAir",
            "flight_benchmark_5pax_gbp": 1442.0,
            "peak_summer_flight_5pax_gbp": 2050.0,
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
            "peak_summer_nightly_room_rate_gbp": 245.0,
            "airport": "FNC",
            "airline": "easyJet / TUI / British Airways",
            "flight_benchmark_5pax_gbp": 960.0,
            "peak_summer_flight_5pax_gbp": 1580.0,
            "highlights": ("Cliff lido", "Heated pools & spa", "Levada hikes & waterfalls nearby", "Funchal Christmas lights"),
            "hotel_url": "https://www.vidamarresorts.com/madeira/",
            "dec_ambient_c": (19, 21),
            "sea_temp_c": 20,
            "beach": "NO sand — volcanic cliffs & lidos. Come for hiking",
            "transfer_gbp": 30.0,
            "confidence": "market-supported",
        },
    ],
    # ── DECEMBER ADDITIONS (owner direction 2026-09-29/30): Doha and Oman
    # (economy, under 8 h) and long-haul Zanzibar, Mauritius and Mexico's
    # Caribbean coast (Business headline). Every rate was read 2026-09-29/30
    # for 20-28 Dec 2026 (8 nights) for five adults and converted at the ECB
    # rate of 2026-09-29 (EUR/GBP 0.85718). These keys are December-only:
    # they never enter the summer view (BOTH_SEASON_WINTER_KEYS). "Peak"
    # fields repeat the December rate: no discount against a peak is claimed.
    # ``transfer_gbp`` 0.0 = airport transfer not priced (no source read).
    "doha": [
        {
            "name": "Rixos Gulf Hotel Doha",
            "destination_label": "Doha, Qatar",
            "stars": 5,  # Google Hotels: "5-star hotel"; Accor: Qatar's first 5-star all-inclusive
            "board": "Bed & Breakfast",
            # Accor ALL booking engine, 20-28 Dec 2026, "SAVER RATE - BREAKFAST
            # INCLUDED": Two Bedroom Family Room (3 adults) EUR 6,124.00 +
            # Superior Room (2 adults) EUR 2,226.32 = EUR 8,350.32
            # (= GBP 7,157.73). No other board was offered for these rooms.
            "base_nightly_room_rate_gbp": 894.72,
            "peak_summer_nightly_room_rate_gbp": 894.72,
            "airport": "DOH",
            "airline": "British Airways / Qatar Airways (nonstop)",
            # Google Flights LHR-DOH 20-28 Dec 2026, 5 adults, Economy, read
            # 2026-09-29: GBP 3,709 (BA / Qatar Airways nonstop).
            "flight_benchmark_5pax_gbp": 3709.0,
            "peak_summer_flight_5pax_gbp": 3709.0,
            "highlights": (
                "Beach resort with a Rixy kids' club",
                "Two Bedroom Family Room (6 guests max) + Superior Room",
                "Google rating 4.9 (17.4k reviews); TripAdvisor ≥4.5 not verified",
            ),
            "hotel_url": "https://www.rixos.com/hotel-resort/rixos-gulf-hotel-doha",
            "dec_ambient_c": (24, 25),  # Doha December mean daily max 24.8°C (Qatar Met. Dept 1992-2021)
            "sea_temp_c": 24,           # seatemperature.org Doha December average 23.5°C
            "beach": "Resort beach on the Doha coast; December days ~25°C, sea ~24°C",
            "transfer_gbp": 0.0,
            "confidence": "market-supported",
        },
    ],
    "muscat": [
        {
            "name": "InterContinental Muscat",
            "destination_label": "Muscat, Oman",
            "stars": 5,  # Google Hotels: "5-star hotel"
            "board": "Bed & Breakfast",
            # IHG booking engine, 20-28 Dec 2026, 2 adults: 1 King City View
            # Balcony, "Stay Longer Pay Less With Breakfast" OMR 127 per night
            # incl. taxes (public rate; "Includes breakfast"). Five adults
            # take three rooms (2 + 2 + 1); the 1-adult rate was not read and
            # is taken at the 2-adult rate: 3 x OMR 127 = OMR 381 per night
            # (= GBP 748.03 at the CBO peg USD 2.6008 and the ECB rates of
            # 2026-09-29). Hence "estimate".
            "base_nightly_room_rate_gbp": 748.03,
            "peak_summer_nightly_room_rate_gbp": 748.03,
            "airport": "MCT",
            "airline": "Oman Air (nonstop)",
            # Google Flights LHR-MCT 20-28 Dec 2026, 5 adults, Economy, read
            # 2026-09-29: Oman Air nonstop 7h10 GBP 4,498 (BA + Qatar Airways
            # via DOH GBP 3,563).
            "flight_benchmark_5pax_gbp": 4498.0,
            "peak_summer_flight_5pax_gbp": 4498.0,
            "highlights": (
                "Beachfront gardens on Shatti Al Qurum; two pools",
                "Three City View rooms with balcony, breakfast included",
                "Google rating 4.7 (9.8k reviews); IHG reviews 4.4; TripAdvisor ≥4.5 not verified",
            ),
            "hotel_url": "https://www.ihg.com/intercontinental/hotels/gb/en/muscat/mscha/hoteldetail",
            "dec_ambient_c": (26, 27),  # Muscat December mean daily max 26.6°C (1991-2020 normals)
            "sea_temp_c": 26,           # seatemperature.org Muscat December average 25.7°C
            "beach": "Beach access on Shatti Al Qurum; December days ~27°C, sea ~26°C",
            "transfer_gbp": 0.0,
            "confidence": "estimate",
        },
    ],
    "zanzibar": [
        {
            "name": "Nungwi Dreams by Mantis",
            "destination_label": "Nungwi, Zanzibar, Tanzania",
            "stars": 5,  # Accor ALL listing: "Hotel 5"
            "board": "Half Board",
            # Accor ALL booking engine, 20-28 Dec 2026, 8 nights, taxes
            # included, three rooms (2 + 2 + 1 adults: two adults per room at
            # most online), "STAY LONGER AND SAVE" rates. Standard Room, 2
            # adults: HB EUR 3,758.84, FB EUR 4,218.06, AI EUR 4,462.48;
            # 1 adult: HB EUR 2,935.59, FB EUR 3,231.20, AI EUR 3,287.41.
            # No Bed & Breakfast or room-only rate was offered for these dates.
            "board_options": (
                {"basis": "HB", "nightly_gbp": 1120.04,
                 "source": "Accor ALL, 20-28 Dec 2026, 3 Standard Rooms: EUR 10,453.27 (read 2026-09-30)"},
                {"basis": "FB", "nightly_gbp": 1250.12,
                 "source": "Accor ALL, 20-28 Dec 2026, 3 Standard Rooms: EUR 11,667.32 (read 2026-09-30)"},
                {"basis": "AI", "nightly_gbp": 1308.53,
                 "source": "Accor ALL, 20-28 Dec 2026, 3 Standard Rooms: EUR 12,212.37 (read 2026-09-30)"},
            ),
            "base_nightly_room_rate_gbp": 1120.04,
            "peak_summer_nightly_room_rate_gbp": 1120.04,
            "airport": "ZNZ",
            "airline": "EgyptAir (via Cairo) / Ethiopian (via Addis Ababa)",
            # Google Flights LHR-ZNZ 20-28 Dec 2026, 5 adults, Economy, read
            # 2026-09-29: GBP 5,954 (EgyptAir via CAI, 12h20); Ethiopian via
            # ADD 11h40 GBP 7,224.
            "flight_benchmark_5pax_gbp": 5954.0,
            "peak_summer_flight_5pax_gbp": 5954.0,
            "routing": ("no London nonstop: 1 stop via Addis Ababa (Ethiopian, 11h40), Cairo "
                        "(EgyptAir, 12h20) or Abu Dhabi (Etihad)"),
            "highlights": (
                "Boutique beachfront resort on Nungwi beach, northern Zanzibar",
                "Three Standard Rooms (34 m², 2 adults each online)",
                "Accor reviews 4.4/5; TripAdvisor ≥4.5 not verified",
            ),
            "hotel_url": "https://all.accor.com/hotel/B404/index.en.shtml",
            "dec_ambient_c": (31, 32),  # Zanzibar City December mean daily max 31.8°C (WMO 1991-2020)
            "sea_temp_c": 28,           # seatemperature.org Nungwi December average 28.4°C
            "beach": "Nungwi beachfront; December is hot, with the short rains tailing off (168 mm, WMO)",
            "transfer_gbp": 0.0,
            "confidence": "market-supported",
        },
    ],
    "mauritius": [
        {
            "name": "Sofitel Mauritius L'Impérial Resort & Spa",
            "destination_label": "Flic en Flac, Mauritius",
            "stars": 5,  # Accor ALL listing: "Resort Hotel 5"
            "board": "Bed & Breakfast",
            # Accor ALL booking engine, 20-28 Dec 2026, 8 nights, taxes
            # included, three rooms (rooms take 2 adults at most): Luxury Room
            # "STAY LONGER AND SAVE RATE - BREAKFAST INCLUDED", 2 adults
            # EUR 5,875.80, 1 adult EUR 5,611.80: 2 x 5,875.80 + 5,611.80 =
            # EUR 17,363.40 (= GBP 14,883.56). Bed & Breakfast was the only
            # basis on the rate page read; no half board or all-inclusive rate
            # was shown, so none is listed.
            "board_options": (
                {"basis": "BB", "nightly_gbp": 1860.44,
                 "source": "Accor ALL, 20-28 Dec 2026, 3 Luxury Rooms: EUR 17,363.40 (read 2026-09-30)"},
            ),
            "base_nightly_room_rate_gbp": 1860.44,
            "peak_summer_nightly_room_rate_gbp": 1860.44,
            "airport": "MRU",
            "airline": "Emirates (via Dubai) / Air France + Air Mauritius (via Paris)",
            # Google Flights LHR-MRU 20-28 Dec 2026, 5 adults, Economy, read
            # 2026-09-29: GBP 6,910 (Emirates via DXB, 15h10); Air France + Air
            # Mauritius via CDG 14h25 GBP 7,786. No nonstop was listed.
            "flight_benchmark_5pax_gbp": 6910.0,
            "peak_summer_flight_5pax_gbp": 6910.0,
            "routing": ("no nonstop listed: 1 stop via Paris (Air France + Air Mauritius, 14h25) "
                        "or Dubai (Emirates, 15h10)"),
            "highlights": (
                "Beachfront on the sheltered west coast; kids' club (4-12) with its own pool",
                "Three Luxury Rooms (50 m², sea facing)",
                "Accor reviews 4.5/5; TripAdvisor ≥4.5 not verified",
            ),
            "hotel_url": "https://sofitel.accor.com/en/hotels/1144.html",
            "dec_ambient_c": (31, 32),  # Port Louis December mean daily max 31.1°C (WMO)
            "sea_temp_c": 27,           # seatemperature.org Port Louis December average 26.5°C
            "beach": "West-coast beachfront at Flic en Flac; December is summer (hot, some rain)",
            "transfer_gbp": 0.0,
            "confidence": "market-supported",
        },
    ],
    "riviera_maya": [
        {
            "name": "Grand Fiesta Americana Coral Beach Cancún All Inclusive Spa & Resort",
            "destination_label": "Cancún, Mexico (Caribbean coast)",
            "stars": 5,  # Google Hotels: "5-star hotel"
            "board": "All Inclusive",  # the resort's own site: an all-inclusive resort
            # Google Hotels, 20-28 Dec 2026, 5 guests: GBP 2,814 per night, the
            # listing's cheapest option for 5 (unit not named).
            "base_nightly_room_rate_gbp": 2814.0,
            "peak_summer_nightly_room_rate_gbp": 2814.0,
            "airport": "CUN",
            "airline": "Virgin Atlantic (nonstop)",
            # Google Flights LHR-CUN 20-28 Dec 2026, 5 adults, Economy, read
            # 2026-09-29: Virgin Atlantic / Delta nonstop 11h01, GBP 6,073.
            "flight_benchmark_5pax_gbp": 6073.0,
            "peak_summer_flight_5pax_gbp": 6073.0,
            "highlights": (
                "All-inclusive beach resort at Punta Cancún, Hotel Zone",
                "Google rating 4.5 (6.6k reviews); TripAdvisor ≥4.5 not verified",
            ),
            "hotel_url": "https://www.fiestamericanatravelty.com/en/grand-fiesta-americana/hotels/grand-fiesta-americana-coral-beach-cancun-all-inclusive-spa-resort",
            "dec_ambient_c": (28, 29),  # Cancún December mean daily max 28.9°C (SMN 1991-2020)
            "sea_temp_c": 27,           # Cancún December sea 27°C (Wikipedia climate table)
            "beach": "Caribbean beachfront; December is the dry season (80 mm)",
            "transfer_gbp": 0.0,
            "confidence": "market-supported",
        },
    ],
}


# ── JULY LONG-HAUL BEACH CATALOGUE (owner direction 2026-09-29: "include
# lombok and thailand mostly", nothing within 6 hours, no Singapore/Malaysia).
#
# Every figure below was READ on 2026-09-29 from the source named beside it;
# nothing is interpolated. Rules the entries follow:
#
# * Room rates are the whole-unit price for the party of 5 read from the
#   hotel's own booking engine (Accor ALL, IHG) or Google Hotels, converted at
#   the ECB reference rates of 2026-09-29 (EUR/GBP 0.85718, EUR/THB 38.056,
#   EUR/IDR 20350.09). Where 20-27 Jul 2027 was on sale the rate is for those
#   dates ("market-supported"); where it was not yet on sale, the nearest
#   open week (29 Jun-6 Jul 2027) is used and the entry says "estimate".
# * July IS the season being priced, so the "peak" fields repeat the July
#   rate: no discount against a peak is claimed for any of these resorts.
# * Flight benchmarks are whole-party (5 adult) ECONOMY returns for 20-27 Jul
#   2027 from LHR read on Google Flights; the report's Business figure is the
#   engine's usual 2.5x of that, labelled an estimate, until a live Business
#   fare replaces it. Observed Business fares are recorded in the source text.
# * TripAdvisor could not be read (DataDome wall; its public summary shows only
#   a whole-number "4 of 5"), so no entry claims the >=4.5 gate: the
#   architecture rows carry ``tripadvisor: None`` and the report says so.
# * ``dec_ambient_c`` is (0, 0): these resorts are not assessed for December
#   and are only ever priced for summer trips (``resort_catalog``).
_LOP_FLIGHT = {
    "airport": "LOP",
    "airline": "Etihad + Garuda Indonesia (2 stops) / Singapore Airlines + Scoot (1 stop)",
    # Google Flights, LHR-LOP 20-27 Jul 2027, 5 adults, Economy, read
    # 2026-09-29: cheapest protected itinerary GBP 4,990 (Etihad + Garuda via
    # AUH and CGK); the 1-stop Singapore Airlines + Scoot itinerary showed
    # "Price unavailable". A Business search returned "No Business Class
    # flights found": there is no Business cabin into Lombok at all.
    "flight_benchmark_5pax_gbp": 4990.0,
    "peak_summer_flight_5pax_gbp": 4990.0,
    "routing": ("no London nonstop and no Business cabin into Lombok: 1 stop via Singapore "
                "(Singapore Airlines + Scoot, about 24h) or 2 stops via the Gulf and Jakarta"),
}
_USM_FLIGHT = {
    "airport": "USM",
    "airline": "British Airways + Bangkok Airways (1 stop via Singapore)",
    # Google Flights, LHR-USM 20-27 Jul 2027, 5 adults, read 2026-09-29:
    # Economy GBP 6,190 (BA + Bangkok Airways via SIN, the only listed
    # itinerary). Business: GBP 29,389 for that itinerary all-Business;
    # protected Business-long-haul + Economy-hop itineraries from GBP 13,340
    # (Etihad + Bangkok Airways, 2 stops) and GBP 21,105 (EVA Air + Bangkok
    # Airways, 1 stop via BKK, 14h55).
    "flight_benchmark_5pax_gbp": 6190.0,
    "peak_summer_flight_5pax_gbp": 6190.0,
    "routing": ("no London nonstop: 1 stop via Bangkok (EVA Air / THAI + Bangkok Airways, "
                "about 14h05-14h55) or Singapore (BA + Bangkok Airways, 16h50)"),
}
_HKT_FLIGHT = {
    "airport": "HKT",
    "airline": "Qatar Airways + British Airways (via Doha) / THAI (via Bangkok)",
    # Google Flights, LHR-HKT 20-27 Jul 2027, 5 adults, read 2026-09-29:
    # Economy from GBP 4,695 (Qatar Airways + BA via DOH); Business from
    # GBP 12,107 (Etihad via AUH). No nonstop was listed for these dates.
    "flight_benchmark_5pax_gbp": 4695.0,
    "peak_summer_flight_5pax_gbp": 4695.0,
    "routing": ("no nonstop on these dates: 1 stop via Bangkok (THAI, 14h30), Abu Dhabi "
                "(Etihad) or Doha (Qatar Airways), then about 1h40 by road"),
}

SUMMER_RESORT_CATALOG: dict[str, list[dict[str, Any]]] = {
    "lombok": [
        {
            "name": "Pullman Lombok Merujani Mandalika Beach Resort",
            "destination_label": "Kuta Mandalika, Lombok, Indonesia",
            "stars": 5,  # Accor ALL listing: "Resort Hotel 5"
            "board": "Bed & Breakfast",
            # Accor ALL booking engine, 5 adults, Two-Bedroom Garden Villa,
            # 29 Jun-6 Jul 2027: EUR 5,882.81 public rate, 7 nights, breakfast
            # and taxes included (= GBP 5,042.63). 20-27 Jul not yet on sale.
            "base_nightly_room_rate_gbp": 720.38,
            "peak_summer_nightly_room_rate_gbp": 720.38,
            **_LOP_FLIGHT,
            "highlights": (
                "Beachfront resort on Kuta Mandalika bay",
                "2-bedroom villa with private pool, 386 m², 6 guests max",
                "Two restaurants and a swim-up bar",
                "Google rating 4.8 (2.3k reviews); TripAdvisor ≥4.5 not verified",
            ),
            "hotel_url": "https://pullman.accor.com/en/hotels/central-lombok/A1K2.html",
            "dec_ambient_c": (0, 0),
            "sea_temp_c": 27,
            "beach": "Resort's own beachfront on Kuta Mandalika bay, 20 min from LOP airport",
            # Estimate: two airport counter taxis at IDR 150,000 each way (top of
            # the IDR 100-150k counter fare to Kuta in a Lombok airport guide).
            "transfer_gbp": 25.27,
            "confidence": "estimate",
        },
        {
            "name": "Novotel Lombok Resort & Villas",
            "destination_label": "Kuta Mandalika, Lombok, Indonesia",
            "stars": 4,  # Accor ALL listing: "Resort Hotel 4"
            "board": "Bed & Breakfast",
            # Accor ALL booking engine, 29 Jun-6 Jul 2027, 7 nights, taxes
            # included, "STAY LONGER AND SAVE RATE - BREAKFAST INCLUDED" (read
            # 2026-09-30): Ocean View Family Villa, two bedrooms (3 adults)
            # EUR 2,263.11 + Superior room (2 adults) EUR 779.71 = EUR 3,042.82
            # (= GBP 2,608.24). 20-27 Jul not yet on sale. The room-only rate
            # read on 2026-09-29 is not a deal (owner rule).
            "base_nightly_room_rate_gbp": 372.61,
            "peak_summer_nightly_room_rate_gbp": 372.61,
            **_LOP_FLIGHT,
            "highlights": (
                "Family resort in traditional Sasak style",
                "Free daily activities and an on-site dive centre",
                "Google rating 4.5 (3.9k reviews); TripAdvisor ≥4.5 not verified",
            ),
            "hotel_url": "https://www.novotellombok.com/rooms-villas/",
            "dec_ambient_c": (0, 0),
            "sea_temp_c": 27,
            "beach": "On Mandalika's Putri Nyale beach, 19 km from LOP airport",
            "transfer_gbp": 25.27,  # estimate, as for the Pullman above
            "confidence": "estimate",
        },
        # ── PROPERTIES WITH NO RATE, ONLY A UNIT (owner brief 2026-10-03, H6).
        # Added so a card can form once the private engine has READ a rate for
        # them. There is deliberately no nightly rate here: the collector makes
        # no card for a resort it cannot price, so these entries are inert
        # until an exact-date rate arrives, and the report never shows a stay
        # priced at zero or at a guess. Only the unit name and the public
        # facts below come from the brief — no prices.
        {
            "name": "The Lombok Lodge",
            "destination_label": "Kuta Mandalika, Lombok, Indonesia",
            "stars": 5,
            "board": "Bed & Breakfast",
            **_LOP_FLIGHT,
            "highlights": (
                "Two-Bedroom Villa on the Kuta Mandalika coast",
                "No rate read yet for these dates; the card appears once one is read.",
            ),
            "hotel_url": "https://www.thelomboklodge.com/",
            "dec_ambient_c": (0, 0),
            "sea_temp_c": 27,
            "beach": "Kuta Mandalika, south Lombok",
            "transfer_gbp": 25.27,  # estimate, as for the Pullman above
            # No rate read yet, so no confidence to claim: the card forms only
            # from an exact-date read rate (see the collector).
            "confidence": "",
        },
        {
            "name": "TUNAK Resort Lombok",
            "destination_label": "Kuta Mandalika, Lombok, Indonesia",
            "stars": 5,
            "board": "Bed & Breakfast",
            **_LOP_FLIGHT,
            "highlights": (
                "Two-bedroom Cliff Front Private Pool Villa, Kuta Mandalika",
                "No rate read yet for these dates; the card appears once one is read.",
            ),
            "hotel_url": "https://tunakresort.com/",
            "dec_ambient_c": (0, 0),
            "sea_temp_c": 27,
            "beach": "Cliff-front location above Kuta Mandalika bay",
            "transfer_gbp": 25.27,
            # No rate read yet, so no confidence to claim: the card forms only
            # from an exact-date read rate (see the collector).
            "confidence": "",
        },
        {
            "name": "Kalandara Resort Lombok",
            "destination_label": "Kuta Mandalika, Lombok, Indonesia",
            "stars": 5,
            # All-inclusive only. The board rule decides whether a rate
            # qualifies: a breakfast rate for an AI-only resort is a rate that
            # cannot be had, and the loader drops it as such.
            "board": "All Inclusive",
            **_LOP_FLIGHT,
            "highlights": (
                "AKASA 2 Bedroom Pool Villa, Kuta Mandalika",
                "All inclusive only — no breakfast-only rate to buy",
                "No rate read yet for these dates; the card appears once one is read.",
            ),
            "hotel_url": "https://kalandara-resort.com/",
            "dec_ambient_c": (0, 0),
            "sea_temp_c": 27,
            "beach": "Kuta Mandalika, south Lombok",
            "transfer_gbp": 25.27,
            # No rate read yet, so no confidence to claim: the card forms only
            # from an exact-date read rate (see the collector).
            "confidence": "",
        },
    ],
    "koh_samui": [
        {
            "name": "Garrya Tongsai Bay Samui",
            "destination_label": "Koh Samui, Thailand (Gulf side)",
            "stars": 5,  # Accor ALL listing: "Resort Hotel 5"
            "board": "Bed & Breakfast",
            # Accor ALL booking engine, 20-27 Jul 2027, 7 nights, breakfast and
            # taxes included: Beachfront Suite (3 adults) EUR 2,937.84 +
            # Beachfront Suite (2 adults) EUR 2,388.14 = EUR 5,325.98
            # (= GBP 4,565.32). Rooms take 3 adults at most.
            "base_nightly_room_rate_gbp": 652.19,
            "peak_summer_nightly_room_rate_gbp": 652.19,
            **_USM_FLIGHT,
            "highlights": (
                "Private bay with its own beach front, 28 acres",
                "Two Beachfront Suites, 72 m² each, sea view",
                "Google rating 4.8 (1.0k reviews); TripAdvisor ≥4.5 not verified",
            ),
            "hotel_url": "https://www.garrya.com/en/destinations/samui",
            "dec_ambient_c": (0, 0),
            "sea_temp_c": 30,
            "beach": "Private Tongsai Bay beach, north-east Samui — Gulf side, the drier coast in July",
            # Estimate: THB 800 each way (top of a Samui guide's THB 400-800
            # airport taxi range).
            "transfer_gbp": 36.04,
            "confidence": "market-supported",
        },
        {
            "name": "Banyan Tree Samui",
            "destination_label": "Koh Samui, Thailand (Gulf side)",
            "stars": 5,  # Accor ALL listing: "Hotel 5"
            "board": "Bed & Breakfast",
            # Accor ALL booking engine, 5 adults, Family Horizon Hillcrest Pool
            # Villa (5 guests max, 169 m²), 29 Jun-6 Jul 2027: EUR 9,899.30,
            # 7 nights, breakfast and taxes included (= GBP 8,485.48).
            # 20-27 Jul not yet on sale.
            "base_nightly_room_rate_gbp": 1212.21,
            "peak_summer_nightly_room_rate_gbp": 1212.21,
            **_USM_FLIGHT,
            "highlights": (
                "All-pool-villa resort on a private cove in Lamai Bay",
                "Family villa with private pool for up to 5",
                "Spa and wellbeing centre; resort speedboat",
                "Guest rating not read; TripAdvisor ≥4.5 not verified",
            ),
            "hotel_url": "https://www.banyantree.com/thailand/samui",
            "dec_ambient_c": (0, 0),
            "sea_temp_c": 30,
            "beach": "Private cove beach in Lamai Bay — hillside villas, a walk or buggy down",
            "transfer_gbp": 36.04,  # estimate, as for Garrya above
            "confidence": "estimate",
        },
        {
            "name": "Kimpton Kitalay Samui",
            "destination_label": "Koh Samui, Thailand (Gulf side)",
            "stars": 5,  # Google Hotels: "5-star hotel"
            # The IHG rate row read did not state what it includes (the hotel
            # page lists "Free breakfast" as an amenity, which is not a rate
            # inclusion): board unverified, so it is not a deal (owner rule).
            "board": "board unverified",
            # IHG booking engine, 20-27 Jul 2027, 4 adults per room: 1 King
            # 1 Bedroom Suite Resort View THB 36,718 per night incl. taxes
            # (public rate). 5 adults exceed every room's capacity, so two
            # suites: THB 73,436 per night (= GBP 1,654.09). The Two Bedroom
            # Villa Kitalay was not offered for these dates.
            "base_nightly_room_rate_gbp": 1654.09,
            "peak_summer_nightly_room_rate_gbp": 1654.09,
            **_USM_FLIGHT,
            "highlights": (
                "Beachfront on Choeng Mon; six outdoor pools",
                "JUNIO kids' club",
                "Google rating 4.7 (1.3k reviews); IHG reviews 4.5; TripAdvisor ≥4.5 not verified",
            ),
            "hotel_url": "https://www.kimptonkitalaysamui.com/",
            "dec_ambient_c": (0, 0),
            "sea_temp_c": 30,
            "beach": "Choeng Mon beachfront, north-east Samui — Gulf side, the drier coast in July",
            "transfer_gbp": 36.04,  # estimate, as for Garrya above
            "confidence": "market-supported",
        },
    ],
    "koh_phangan": [
        {
            "name": "Anantara Rasananda Koh Phangan Villas",
            "destination_label": "Koh Phangan, Thailand (Gulf side)",
            "stars": 5,  # Google Hotels: "5-star hotel"
            # Google Hotels' listing price did not say what the rate included:
            # board unverified, so it is not a deal (owner rule, 2026-09-30).
            # The listing price is withdrawn entirely (H6): a figure the page
            # did not describe is not a rate, and the card now forms only when
            # the private engine reads one whose board it states.
            "board": "board unverified",
            **_USM_FLIGHT,
            "routing": _USM_FLIGHT["routing"] + ", then the resort's speedboat from Samui (about 40 min)",
            "highlights": (
                "Two Bedroom Pool Villa: 220 m², up to 6 adults, plunge pool",
                "Scheduled resort speedboat from Samui, about 40 min",
                "No rate read yet for these dates; the card appears once one is read.",
            ),
            "hotel_url": "https://www.anantara.com/en/rasananda-koh-phangan",
            "dec_ambient_c": (0, 0),
            "sea_temp_c": 30,
            "beach": "Thong Nai Pan Noi bay, north-east Koh Phangan — Gulf side, the drier coast in July",
            # Hotel price list (1 Nov 2024): scheduled speedboat THB 4,000++ per
            # person return, car from USM to the pier included; ++ taken as
            # 10% service + 7% VAT: 5 x 4,000 x 1.177 = THB 23,540.
            "transfer_gbp": 530.22,
            # No rate read yet, so no confidence to claim: the card forms only
            # from an exact-date read rate whose board the engine states.
            "confidence": "",
        },
    ],
    "zanzibar": [
        {
            "name": "Nungwi Dreams by Mantis",
            "destination_label": "Nungwi, Zanzibar, Tanzania (dry season in July)",
            "stars": 5,  # Accor ALL listing: "Hotel 5"
            "board": "Bed & Breakfast",
            # Accor ALL booking engine, 20-27 Jul 2027, 7 nights, taxes
            # included, three rooms (2 + 2 + 1 adults), "ADVANCE SAVER RATE -
            # BREAKFAST INCLUDED": Standard Room 2 adults EUR 1,503.72, 1 adult
            # EUR 1,143.24: EUR 4,150.68 (= GBP 3,557.88). Bed & Breakfast was
            # the only basis offered for these dates (the December page also
            # sells half board, full board and all inclusive).
            "board_options": (
                {"basis": "BB", "nightly_gbp": 508.27,
                 "source": "Accor ALL, 20-27 Jul 2027, 3 Standard Rooms: EUR 4,150.68 (read 2026-09-30)"},
            ),
            "base_nightly_room_rate_gbp": 508.27,
            "peak_summer_nightly_room_rate_gbp": 508.27,
            "airport": "ZNZ",
            "airline": "Etihad (via Abu Dhabi) / Ethiopian (via Addis Ababa)",
            # Google Flights LHR-ZNZ 20-27 Jul 2027, 5 adults, Economy, read
            # 2026-09-29: GBP 5,349 (Etihad via AUH, 13h45); Ethiopian via ADD
            # 11h55 GBP 6,384.
            "flight_benchmark_5pax_gbp": 5349.0,
            "peak_summer_flight_5pax_gbp": 5349.0,
            "routing": ("no London nonstop: 1 stop via Addis Ababa (Ethiopian, 11h55) or Abu Dhabi "
                        "(Etihad, 13h45)"),
            "highlights": (
                "Boutique beachfront resort on Nungwi beach, northern Zanzibar",
                "Three Standard Rooms (34 m², 2 adults each online)",
                "Accor reviews 4.4/5; TripAdvisor ≥4.5 not verified",
            ),
            "hotel_url": "https://all.accor.com/hotel/B404/index.en.shtml",
            "dec_ambient_c": (0, 0),
            "sea_temp_c": 26,
            "beach": "Nungwi beachfront; July is the dry season (31 mm, WMO Zanzibar City)",
            "transfer_gbp": 0.0,  # airport transfer not priced (no source read)
            "confidence": "market-supported",
        },
    ],
    "khao_lak": [
        {
            "name": "Pullman Khao Lak Resort",
            "destination_label": "Khao Lak, Thailand (Andaman side — MONSOON in July)",
            # The Andaman coast sees the south-west monsoon roughly May-Oct:
            # a July trip here may be rained off. Flagged so the climate award
            # can never rank it and its card can warn (2026-10-02).
            "monsoon_months": (5, 6, 7, 8, 9, 10),
            "stars": 5,  # Accor ALL listing: "Resort Hotel 5"
            "board": "Bed & Breakfast",
            # Accor ALL booking engine, 20-27 Jul 2027, 7 nights, taxes
            # included, "EARLY BIRD OFFER - BED & BREAKFAST" (read 2026-09-30):
            # Family Suite (5 guests max; 3 adults) EUR 912.12 + Deluxe Room
            # (2 adults) EUR 412.33 = EUR 1,324.45 (= GBP 1,135.29). The
            # room-only rate read on 2026-09-29 is not a deal (owner rule).
            "base_nightly_room_rate_gbp": 162.18,
            "peak_summer_nightly_room_rate_gbp": 162.18,
            **_HKT_FLIGHT,
            "highlights": (
                "Kids' club, two pools, two restaurants",
                "Family Suite for up to 5 (62 m²) plus a Deluxe Room",
                "Google rating 4.5 (2.2k reviews); Accor reviews 4.5/5; TripAdvisor ≥4.5 not verified",
            ),
            "hotel_url": "https://www.pullmankhaolakresort.com/",
            "dec_ambient_c": (0, 0),
            "sea_temp_c": 30,
            "beach": ("Bang Muang white-sand beach — but July is the SW monsoon on the Andaman "
                      "coast (Takua Pa: 466 mm over 19.7 rain days, WMO normals); check the sea "
                      "before swimming"),
            # Estimate: private car HKT-Khao Lak from THB 1,700 per way for 1-8
            # people (a Khao Lak airport-transfer operator's price list).
            "transfer_gbp": 76.58,
            "confidence": "market-supported",
        },
    ],
}

#: Winter keys whose entries also carry summer-peak rates and were priced for
#: July before the seasonal split. Every other winter key (Doha, Muscat and
#: the December long-haul beaches, added 2026-09-30) is priced at DECEMBER
#: rates and must never price a July card.
BOTH_SEASON_WINTER_KEYS: frozenset[str] = frozenset({
    "antalya", "fuerteventura", "gran_canaria", "paphos", "hurghada",
    "tenerife", "lanzarote", "cairo", "madeira",
})

#: The summer view: the summer entries, plus the both-season winter keys.
_SUMMER_TRIP_CATALOG: dict[str, list[dict[str, Any]]] = {
    **{key: value for key, value in WINTER_RESORT_CATALOG.items() if key in BOTH_SEASON_WINTER_KEYS},
    **SUMMER_RESORT_CATALOG,
}


# ── JULY STOPOVER OPTION (owner, 2026-09-29): "oman and doha ... as a 2d or so
# in july on way out and way back (not business class options)". About two
# nights in Doha or Muscat each way, Economy on every leg, stopover hotels
# included at breakfast minimum. Rates read 2026-09-30 from the Accor booking
# engine for five adults, ECB EUR/GBP 0.85718 (2026-09-29).
STOPOVER_HUBS: dict[str, dict[str, Any]] = {
    "DOH": {
        "label": "Doha",
        "nights_each_way": 2,
        "hotel": {
            "name": "Rixos Gulf Hotel Doha",
            "hotel_url": "https://www.rixos.com/hotel-resort/rixos-gulf-hotel-doha",
            "board": "Bed & Breakfast",
            "unit": "Two Bedroom Family Room (3 adults) + Superior Room (2 adults)",
            # "SAVER RATE - BREAKFAST INCLUDED": 18-20 Jul 2027 EUR 1,094.84 +
            # EUR 447.95; 27-29 Jul 2027 EUR 1,173.02 + EUR 450.34. Four
            # nights EUR 3,166.15 = GBP 2,713.96, GBP 678.49 a night.
            "nightly_gbp": 678.49,
            "source": "Accor ALL booking engine, 18-20 and 27-29 Jul 2027, read 2026-09-30",
            "confidence": "market-supported",
        },
    },
    "MCT": {
        "label": "Muscat",
        "nights_each_way": 2,
        "hotel": {
            "name": "Mövenpick Hotel and Apartments Ghala Muscat",
            "hotel_url": "https://movenpick.accor.com/en/middle-east/oman/muscat.html",
            "board": "Bed & Breakfast",
            "unit": "3 × Superior Room (2 + 2 + 1 adults)",
            # "EARLY BIRD OFFER - BED & BREAKFAST", 18-20 Jul 2027: 2 adults
            # EUR 332.74, 1 adult EUR 304.54; three rooms EUR 970.02 = GBP 831.48
            # for two nights. 27-29 Jul was not yet on sale, so the outbound
            # rate stands in for the return stay: an estimate.
            "nightly_gbp": 415.74,
            "source": "Accor ALL booking engine, 18-20 Jul 2027 (27-29 Jul not on sale), read 2026-09-30",
            "confidence": "estimate",
        },
    },
    "AUH": {
        "label": "Abu Dhabi",
        "nights_each_way": 2,
        "hotel": {
            "name": "Novotel Abu Dhabi Al Bustan",
            "hotel_url": "https://all.accor.com/hotel/6533/index.en.shtml",
            "board": "Bed & Breakfast",
            "unit": "3 × Superior Twin Room (2 + 2 + 1 adults)",
            # "SAVER RATE - BREAKFAST INCLUDED" (public rate, non-refundable):
            # 18-20 Jul 2027 EUR 209.95 + EUR 209.95 + EUR 180.29; 27-29 Jul
            # 2027 identical. Four nights (3 rooms) EUR 1,200.38 = GBP
            # 1,028.94, GBP 257.24 a night.
            "nightly_gbp": 257.24,
            "source": "Accor ALL booking engine (hotel 6533), 18-20 and 27-29 Jul 2027, public rate, read 2026-09-30",
            "confidence": "market-supported",
        },
    },
    "DXB": {
        "label": "Dubai",
        "nights_each_way": 2,
        "hotel": {
            "name": "Novotel Deira Creekside Dubai",
            "hotel_url": "https://all.accor.com/hotel/6482/index.en.shtml",
            "board": "Bed & Breakfast",
            "unit": "3 × Superior Room with 2 single beds (2 + 2 + 1 adults)",
            # "EARLY BIRD OFFER - BED & BREAKFAST" (public rate, non-refundable):
            # 18-20 Jul 2027 EUR 172.45 + EUR 172.45 + EUR 148.92; 27-29 Jul
            # 2027 EUR 179.86 + EUR 179.86 + EUR 156.33. Four nights (3 rooms)
            # EUR 1,009.87 = GBP 865.64, GBP 216.41 a night.
            "nightly_gbp": 216.41,
            "source": "Accor ALL booking engine (hotel 6482), 18-20 and 27-29 Jul 2027, public rate, read 2026-09-30",
            "confidence": "market-supported",
        },
    },
}

#: The "price this yourself" link list on a card with no read stopover fare
#: (render_flight_options) is capped to this fixed set, not every hub in
#: STOPOVER_HUBS: each line costs ~400 bytes and the December report — which
#: has no priced fares yet and so renders every long-haul card through this
#: link path — sits within ~3 KB of the Gmail 102 KB clip already. A hub added
#: to STOPOVER_HUBS for the *priced* path (stopover_fares_for, gated on an
#: actual STOPOVER_READS entry) costs nothing here until it has a real fare.
STOPOVER_LINK_HUBS: tuple[str, ...] = ("DOH", "MCT")

#: Stopover itineraries whose whole-trip Economy price for five was read on
#: Google Flights (multi-city: London - hub on the outbound date, hub - beach
#: two days later, beach - hub on the return date, hub - London two days after
#: that). One read answers exactly one (pair, hub, airport): a fare is only ever
#: shown for the dates it was read for, so a card priced for another pair says
#: "price on request" instead of borrowing a number that was never read for it.
#: ``status`` says what the read produced, and only ``priced`` rows with a
#: ``total_gbp`` may be committed as a fare — ``no_priced_economy_card``,
#: ``blocked`` and ``error`` are recorded so the gap is visible, and render as
#: the price-it-yourself link.
#: The price is the cheapest "entire trip" figure listed on the first leg —
#: but ONLY from the pre-expansion card list, confirmed by clicking through
#: to the second leg and checking the same total still holds. Google's own
#: "more flights" expander can surface a card whose displayed "entire trip"
#: total does not reconcile on selection (observed live 2026-09-30: an ITA
#: Airways-via-Rome DXB card read GBP 4,515 in the expanded list but priced
#: GBP 6,100, matching the pre-expansion cheapest, once actually selected).
#: A clean re-read that never touches the expander is the safer default when
#: it already contains a plausible fare; an expanded-list price is provisional
#: until leg 2 confirms it.
_STOPOVER_READS: tuple[dict[str, Any], ...] = (
    {
        "pair": ("2027-06-26", "2027-07-10"),
        "hub": "DOH", "airport": "HKT",
        "total_gbp": 4266.0,
        "carrier": "Qatar Airways / British Airways",
        "status": "priced", "season": "summer",
        "observed_at": "2026-10-04T12:56:18+00:00",
        "source_url": (
            "https://www.google.com/travel/flights/search?tfs=GhoSCjIwMjctMDYtMjZqBRIDTEhScgUSA0RPSBoaEgoyMDI3LTA2LTI4agUSA0RPSHIFEgNIS1QaGhIKMjAyNy0wNy0xMGoFEgNIS1RyBRIDRE9IGhoSCjIwMjctMDctMTJqBRIDRE9IcgUSA0xIUkIFAQEBAQFIAZgBAw%3D%3D&curr=GBP&hl=en-GB"
        ),
    },
    {
        "pair": ("2027-06-26", "2027-07-10"),
        "hub": "DOH", "airport": "USM",
        "total_gbp": 4837.0,
        "carrier": "Qatar Airways / British Airways",
        "status": "priced", "season": "summer",
        "observed_at": "2026-10-04T12:56:39+00:00",
        "source_url": (
            "https://www.google.com/travel/flights/search?tfs=GhoSCjIwMjctMDYtMjZqBRIDTEhScgUSA0RPSBoaEgoyMDI3LTA2LTI4agUSA0RPSHIFEgNVU00aGhIKMjAyNy0wNy0xMGoFEgNVU01yBRIDRE9IGhoSCjIwMjctMDctMTJqBRIDRE9IcgUSA0xIUkIFAQEBAQFIAZgBAw%3D%3D&curr=GBP&hl=en-GB"
        ),
    },
    {
        "pair": ("2027-06-26", "2027-07-10"),
        "hub": "MCT", "airport": "HKT",
        "total_gbp": 4441.0,
        "carrier": "Oman Air",
        "status": "priced", "season": "summer",
        "observed_at": "2026-10-04T12:57:57+00:00",
        "source_url": (
            "https://www.google.com/travel/flights/search?tfs=GhoSCjIwMjctMDYtMjZqBRIDTEhScgUSA01DVBoaEgoyMDI3LTA2LTI4agUSA01DVHIFEgNIS1QaGhIKMjAyNy0wNy0xMGoFEgNIS1RyBRIDTUNUGhoSCjIwMjctMDctMTJqBRIDTUNUcgUSA0xIUkIFAQEBAQFIAZgBAw%3D%3D&curr=GBP&hl=en-GB"
        ),
    },
    {
        "pair": ("2027-06-26", "2027-07-10"),
        "hub": "AUH", "airport": "HKT",
        "total_gbp": 3218.0,
        "carrier": "Etihad",
        "status": "priced", "season": "summer",
        "observed_at": "2026-10-04T12:59:37+00:00",
        "source_url": (
            "https://www.google.com/travel/flights/search?tfs=GhoSCjIwMjctMDYtMjZqBRIDTEhScgUSA0FVSBoaEgoyMDI3LTA2LTI4agUSA0FVSHIFEgNIS1QaGhIKMjAyNy0wNy0xMGoFEgNIS1RyBRIDQVVIGhoSCjIwMjctMDctMTJqBRIDQVVIcgUSA0xIUkIFAQEBAQFIAZgBAw%3D%3D&curr=GBP&hl=en-GB"
        ),
    },
    {
        "pair": ("2027-06-26", "2027-07-10"),
        "hub": "AUH", "airport": "ZNZ",
        "total_gbp": 4274.0,
        "carrier": "Etihad",
        "status": "priced", "season": "summer",
        "observed_at": "2026-10-04T13:00:27+00:00",
        "source_url": (
            "https://www.google.com/travel/flights/search?tfs=GhoSCjIwMjctMDYtMjZqBRIDTEhScgUSA0FVSBoaEgoyMDI3LTA2LTI4agUSA0FVSHIFEgNaTloaGhIKMjAyNy0wNy0xMGoFEgNaTlpyBRIDQVVIGhoSCjIwMjctMDctMTJqBRIDQVVIcgUSA0xIUkIFAQEBAQFIAZgBAw%3D%3D&curr=GBP&hl=en-GB"
        ),
    },
    {
        "pair": ("2027-06-26", "2027-07-10"),
        "hub": "DXB", "airport": "USM",
        "total_gbp": 5532.0,
        "carrier": "Emirates",
        "status": "priced", "season": "summer",
        "observed_at": "2026-10-04T13:01:47+00:00",
        "source_url": (
            "https://www.google.com/travel/flights/search?tfs=GhoSCjIwMjctMDYtMjZqBRIDTEhScgUSA0RYQhoaEgoyMDI3LTA2LTI4agUSA0RYQnIFEgNVU00aGhIKMjAyNy0wNy0xMGoFEgNVU01yBRIDRFhCGhoSCjIwMjctMDctMTJqBRIDRFhCcgUSA0xIUkIFAQEBAQFIAZgBAw%3D%3D&curr=GBP&hl=en-GB"
        ),
    },
    {
        "pair": ("2027-07-01", "2027-07-15"),
        "hub": "DOH", "airport": "HKT",
        "total_gbp": 4321.0,
        "carrier": "Qatar Airways / British Airways",
        "status": "priced", "season": "summer",
        "observed_at": "2026-10-04T13:03:01+00:00",
        "source_url": (
            "https://www.google.com/travel/flights/search?tfs=GhoSCjIwMjctMDctMDFqBRIDTEhScgUSA0RPSBoaEgoyMDI3LTA3LTAzagUSA0RPSHIFEgNIS1QaGhIKMjAyNy0wNy0xNWoFEgNIS1RyBRIDRE9IGhoSCjIwMjctMDctMTdqBRIDRE9IcgUSA0xIUkIFAQEBAQFIAZgBAw%3D%3D&curr=GBP&hl=en-GB"
        ),
    },
    {
        "pair": ("2027-07-01", "2027-07-15"),
        "hub": "MCT", "airport": "HKT",
        "total_gbp": 5113.0,
        "carrier": "Oman Air",
        "status": "priced", "season": "summer",
        "observed_at": "2026-10-04T13:04:42+00:00",
        "source_url": (
            "https://www.google.com/travel/flights/search?tfs=GhoSCjIwMjctMDctMDFqBRIDTEhScgUSA01DVBoaEgoyMDI3LTA3LTAzagUSA01DVHIFEgNIS1QaGhIKMjAyNy0wNy0xNWoFEgNIS1RyBRIDTUNUGhoSCjIwMjctMDctMTdqBRIDTUNUcgUSA0xIUkIFAQEBAQFIAZgBAw%3D%3D&curr=GBP&hl=en-GB"
        ),
    },
    {
        "pair": ("2027-07-01", "2027-07-15"),
        "hub": "MCT", "airport": "USM",
        "total_gbp": 6500.0,
        "carrier": "Oman Air",
        "status": "priced", "season": "summer",
        "observed_at": "2026-10-04T13:05:06+00:00",
        "source_url": (
            "https://www.google.com/travel/flights/search?tfs=GhoSCjIwMjctMDctMDFqBRIDTEhScgUSA01DVBoaEgoyMDI3LTA3LTAzagUSA01DVHIFEgNVU00aGhIKMjAyNy0wNy0xNWoFEgNVU01yBRIDTUNUGhoSCjIwMjctMDctMTdqBRIDTUNUcgUSA0xIUkIFAQEBAQFIAZgBAw%3D%3D&curr=GBP&hl=en-GB"
        ),
    },
    {
        "pair": ("2027-07-01", "2027-07-15"),
        "hub": "DXB", "airport": "HKT",
        "total_gbp": 4230.0,
        "carrier": "Emirates / Qantas",
        "status": "priced", "season": "summer",
        "observed_at": "2026-10-04T13:08:00+00:00",
        "source_url": (
            "https://www.google.com/travel/flights/search?tfs=GhoSCjIwMjctMDctMDFqBRIDTEhScgUSA0RYQhoaEgoyMDI3LTA3LTAzagUSA0RYQnIFEgNIS1QaGhIKMjAyNy0wNy0xNWoFEgNIS1RyBRIDRFhCGhoSCjIwMjctMDctMTdqBRIDRFhCcgUSA0xIUkIFAQEBAQFIAZgBAw%3D%3D&curr=GBP&hl=en-GB"
        ),
    },
    {
        "pair": ("2027-07-03", "2027-07-24"),
        "hub": "DOH", "airport": "HKT",
        "total_gbp": 4741.0,
        "carrier": "Qatar Airways / British Airways",
        "status": "priced", "season": "summer",
        "observed_at": "2026-10-04T13:09:41+00:00",
        "source_url": (
            "https://www.google.com/travel/flights/search?tfs=GhoSCjIwMjctMDctMDNqBRIDTEhScgUSA0RPSBoaEgoyMDI3LTA3LTA1agUSA0RPSHIFEgNIS1QaGhIKMjAyNy0wNy0yNGoFEgNIS1RyBRIDRE9IGhoSCjIwMjctMDctMjZqBRIDRE9IcgUSA0xIUkIFAQEBAQFIAZgBAw%3D%3D&curr=GBP&hl=en-GB"
        ),
    },
    {
        "pair": ("2027-07-03", "2027-07-24"),
        "hub": "DOH", "airport": "USM",
        "total_gbp": 5297.0,
        "carrier": "Qatar Airways / British Airways",
        "status": "priced", "season": "summer",
        "observed_at": "2026-10-04T13:10:08+00:00",
        "source_url": (
            "https://www.google.com/travel/flights/search?tfs=GhoSCjIwMjctMDctMDNqBRIDTEhScgUSA0RPSBoaEgoyMDI3LTA3LTA1agUSA0RPSHIFEgNVU00aGhIKMjAyNy0wNy0yNGoFEgNVU01yBRIDRE9IGhoSCjIwMjctMDctMjZqBRIDRE9IcgUSA0xIUkIFAQEBAQFIAZgBAw%3D%3D&curr=GBP&hl=en-GB"
        ),
    },
    {
        "pair": ("2027-07-03", "2027-07-24"),
        "hub": "DOH", "airport": "ZNZ",
        "total_gbp": 6535.0,
        "carrier": "Royal Jordanian",
        "status": "priced", "season": "summer",
        "observed_at": "2026-10-04T13:10:33+00:00",
        "source_url": (
            "https://www.google.com/travel/flights/search?tfs=GhoSCjIwMjctMDctMDNqBRIDTEhScgUSA0RPSBoaEgoyMDI3LTA3LTA1agUSA0RPSHIFEgNaTloaGhIKMjAyNy0wNy0yNGoFEgNaTlpyBRIDRE9IGhoSCjIwMjctMDctMjZqBRIDRE9IcgUSA0xIUkIFAQEBAQFIAZgBAw%3D%3D&curr=GBP&hl=en-GB"
        ),
    },
    {
        "pair": ("2027-07-03", "2027-07-24"),
        "hub": "MCT", "airport": "ZNZ",
        "total_gbp": 6081.0,
        "carrier": "Etihad",
        "status": "priced", "season": "summer",
        "observed_at": "2026-10-04T13:12:15+00:00",
        "source_url": (
            "https://www.google.com/travel/flights/search?tfs=GhoSCjIwMjctMDctMDNqBRIDTEhScgUSA01DVBoaEgoyMDI3LTA3LTA1agUSA01DVHIFEgNaTloaGhIKMjAyNy0wNy0yNGoFEgNaTlpyBRIDTUNUGhoSCjIwMjctMDctMjZqBRIDTUNUcgUSA0xIUkIFAQEBAQFIAZgBAw%3D%3D&curr=GBP&hl=en-GB"
        ),
    },
    {
        "pair": ("2027-07-03", "2027-07-24"),
        "hub": "AUH", "airport": "ZNZ",
        "total_gbp": 4274.0,
        "carrier": "Etihad",
        "status": "priced", "season": "summer",
        "observed_at": "2026-10-04T13:13:51+00:00",
        "source_url": (
            "https://www.google.com/travel/flights/search?tfs=GhoSCjIwMjctMDctMDNqBRIDTEhScgUSA0FVSBoaEgoyMDI3LTA3LTA1agUSA0FVSHIFEgNaTloaGhIKMjAyNy0wNy0yNGoFEgNaTlpyBRIDQVVIGhoSCjIwMjctMDctMjZqBRIDQVVIcgUSA0xIUkIFAQEBAQFIAZgBAw%3D%3D&curr=GBP&hl=en-GB"
        ),
    },
    {
        "pair": ("2027-07-03", "2027-07-24"),
        "hub": "DXB", "airport": "HKT",
        "total_gbp": 4393.0,
        "carrier": "Emirates / Qantas",
        "status": "priced", "season": "summer",
        "observed_at": "2026-10-04T13:14:42+00:00",
        "source_url": (
            "https://www.google.com/travel/flights/search?tfs=GhoSCjIwMjctMDctMDNqBRIDTEhScgUSA0RYQhoaEgoyMDI3LTA3LTA1agUSA0RYQnIFEgNIS1QaGhIKMjAyNy0wNy0yNGoFEgNIS1RyBRIDRFhCGhoSCjIwMjctMDctMjZqBRIDRFhCcgUSA0xIUkIFAQEBAQFIAZgBAw%3D%3D&curr=GBP&hl=en-GB"
        ),
    },
    {
        "pair": ("2027-07-03", "2027-07-24"),
        "hub": "DXB", "airport": "ZNZ",
        "total_gbp": 4623.0,
        "carrier": "ITA",
        "status": "priced", "season": "summer",
        "observed_at": "2026-10-04T13:15:33+00:00",
        "source_url": (
            "https://www.google.com/travel/flights/search?tfs=GhoSCjIwMjctMDctMDNqBRIDTEhScgUSA0RYQhoaEgoyMDI3LTA3LTA1agUSA0RYQnIFEgNaTloaGhIKMjAyNy0wNy0yNGoFEgNaTlpyBRIDRFhCGhoSCjIwMjctMDctMjZqBRIDRFhCcgUSA0xIUkIFAQEBAQFIAZgBAw%3D%3D&curr=GBP&hl=en-GB"
        ),
    }
)


#: The reads' statuses that may become a fare. Everything else is a gap, not a
#: price: a search Google answered with no Economy card, a read it refused, or
#: a read that failed outright, none of which is a number we may print.
_STOPOVER_PRICED_STATUS = "priced"


def _shift_date(day: str, delta_days: int) -> str:
    """`day` (YYYY-MM-DD) shifted by `delta_days`; returned unchanged if unparseable."""
    try:
        return (datetime.strptime(str(day), "%Y-%m-%d") + timedelta(days=delta_days)).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return str(day)


#: Days spent flying London -> hub -> resort before the holiday starts, and
#: again on the way home. Two, because each stopover is two nights: the party
#: lands in the hub on the pair's outbound date and reaches the resort two days
#: later, which is also how many fewer nights the resort stay is priced for.
STOPOVER_FLIGHT_DAYS = 2


def stopover_legs(hub: str, airport: str, outbound: str, returning: str, *,
                  origin: str = "LHR") -> tuple[tuple[str, str, str], ...]:
    """The four legs of a two-night stopover in `hub` each way.

    The leg shape (owner brief 2026-10-04, H4): leave London on the pair's own
    outbound date, reach the resort two days later, come back through the hub on
    the return date and land two days after that. The stay at the resort is
    therefore the pair's nights less the two days spent flying to it.
    """
    return (
        (origin, hub, str(outbound)),
        (hub, str(airport).upper(), _shift_date(outbound, STOPOVER_FLIGHT_DAYS)),
        (str(airport).upper(), hub, str(returning)),
        (hub, origin, _shift_date(returning, STOPOVER_FLIGHT_DAYS)),
    )


def _display_carrier(raw: Any) -> str:
    """Carrier names as one readable list, however the read spelled them.

    A read sometimes returns two carriers run together ("Qatar AirwaysBritish
    Airways") because nothing on the card separates them. A lowercase-to-
    uppercase letter boundary inside a word is where one name ends and the next
    begins, so that is where the separator goes. Text that already separates its
    names ("A / B", "A, then B", "A via B") is left exactly as read.
    """
    text = " ".join(str(raw or "").split())
    if not text:
        return ""
    if any(sep in text for sep in (" / ", ", ", " via ", " + ")):
        return text
    # "Qatar AirwaysBritish Airways" -> "Qatar Airways / British Airways"
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " / ", text)


def _stopover_fares() -> dict[tuple[tuple[str, str], str, str], tuple[dict[str, Any], ...]]:
    """Fares keyed by ``(pair, hub, airport)`` from the priced reads only."""
    fares: dict[tuple[tuple[str, str], str, str], list[dict[str, Any]]] = {}
    for row in _STOPOVER_READS:
        if str(row.get("status", "")).strip().lower() != _STOPOVER_PRICED_STATUS:
            continue
        total = row.get("total_gbp")
        if total in (None, ""):
            continue
        pair = (str(row["pair"][0]), str(row["pair"][1]))
        hub = str(row["hub"]).upper()
        airport = str(row["airport"]).upper()
        origin = str(row.get("origin", "LHR")).upper()
        legs = stopover_legs(hub, airport, pair[0], pair[1], origin=origin)
        fares.setdefault((pair, hub, airport), []).append({
            "pair": pair,
            "legs": legs,
            "origin": origin,
            "total_gbp": float(total),
            "carrier": _display_carrier(row.get("carrier")),
            "observed_at": str(row.get("observed_at", "")),
            # A read is for one season; December reads can be added beside the
            # July ones without either leaking into the other planner.
            "season": str(row.get("season", "summer")).strip().lower() or "summer",
            "source_url": str(row.get("source_url") or "") or build_google_flights_legs_url(
                legs, travellers=5, cabin_class="ECONOMY"
            ),
        })
    return {key: tuple(value) for key, value in fares.items()}


#: Read fares, keyed by the exact pair, hub and airport they were read for.
#: Any (pair, hub, airport) with no key here renders as "price on request" with
#: the multi-city link rather than a borrowed figure. No itinerary was listed
#: for Doha - Lombok, Muscat - Zanzibar, Dubai - Koh Samui or Dubai - Lombok
#: either (checked 2026-09-30, each a correctly-formed multi-city search that
#: Google itself returned no options for); those cards say so rather than
#: inventing a fare.
STOPOVER_FARES: dict[tuple[tuple[str, str], str, str], tuple[dict[str, Any], ...]] = _stopover_fares()


def stopover_fares_for(hub: str, airport: str, season: str, *,
                       pair: Optional[tuple[str, str]] = None) -> tuple[dict[str, Any], ...]:
    """Stopover fares for one ``(hub, airport)`` in one season, optionally one pair.

    The option is season-scoped so a July read and a December read coexist
    without one leaking into the other's planner: a fare carries the season it
    was read for, and only that season's planner sees it. Pass ``pair`` to ask
    the narrower question "was this itinerary read for THESE dates"; a read for
    any other pair is not an answer.
    """
    wanted = (season or "").strip().lower() or "winter"
    hub_key = str(hub).upper()
    airport_key = str(airport).upper()
    pair_key = None
    if pair is not None:
        pair_key = (str(pair[0]), str(pair[1]))
    found = []
    for (read_pair, read_hub, read_airport), fares in STOPOVER_FARES.items():
        if (read_hub, read_airport) != (hub_key, airport_key):
            continue
        if pair_key is not None and read_pair != pair_key:
            continue
        found.extend(
            fare for fare in fares
            if str(fare.get("season", "summer")).strip().lower() == wanted
        )
    return tuple(found)


def stopover_search_url(hub: str, airport: str, outbound: str, returning: str,
                        *, origin: str = "LHR", travellers: int = 5,
                        cabin_class: str = "ECONOMY") -> str:
    """Multi-city search URL for a two-night stopover in `hub` each way.

    A card that has no read whole-party stopover fare for its dates can still
    offer the itinerary for pricing with one click: the reader prices it and the
    report never invents a number it did not read. The legs are
    ``stopover_legs`` for the pair, so a link and a fare always describe the
    same journey.
    """
    legs = stopover_legs(hub, airport, outbound, returning, origin=origin)
    return build_google_flights_legs_url(legs, travellers=travellers, cabin_class=cabin_class)


# Recovered criteria registry (0-10 curated benchmarks per resort, from the
# winter-tracker contract): luxury, food reality, mosque access, winter
# facilities, activities, flight quality — plus the mosque facts and the
# food-review summary the contract made mandatory. These are CURATED
# BENCHMARKS requiring live verification, exactly like the price baselines.
RESORT_CRITERIA: dict[str, dict[str, Any]] = {
    "Lara Barut Collection": {
        "luxury": 9, "food": 9, "winter": 7, "mosque": 8, "activities": 8, "flight_quality": 6,
        "indoor": 2, "heated_indoor_pool": True,
        "mosque_name": "On-site mescit + Lara district cami", "mosque_walk_minutes": 3,
        "food_review_summary": "Buffet quality and variety repeatedly praised — live grills, Turkish and international stations; themed à-la-carte restaurants",
    },
    "Concorde De Luxe Resort": {
        "luxury": 8, "food": 8, "winter": 7, "mosque": 8, "activities": 9, "flight_quality": 6,
        "indoor": 3, "heated_indoor_pool": True,
        "mosque_name": "On-site mescit", "mosque_walk_minutes": 2,
        "food_review_summary": "Wide buffet praised for families; Turkish sweets station highlighted; some peak-season repetition complaints",
    },
    "Titanic Mardan Palace": {
        "luxury": 10, "food": 9, "winter": 7, "mosque": 7, "activities": 8, "flight_quality": 6,
        "indoor": 3, "heated_indoor_pool": True,
        "mosque_name": "Mardan area cami", "mosque_walk_minutes": 15,
        "food_review_summary": "Fine-dining depth praised (7,500m² spa resort scale); à-la-carte quality consistently strong in reviews",
    },
    "Steigenberger ALDAU Beach Hotel": {
        "luxury": 8, "food": 8, "winter": 8, "mosque": 6, "activities": 7, "flight_quality": 6,
        "indoor": 2, "heated_indoor_pool": True,
        "mosque_name": "Hurghada El Mina Mosque (taxi)", "mosque_walk_minutes": 12,
        "food_review_summary": "Reef-side dining and buffet quality praised; dive-club and lazy river anchor reviews; some evening-entertainment repetition",
    },
    "Jaz Aquaviva": {
        "luxury": 8, "food": 8, "winter": 8, "mosque": 6, "activities": 9, "flight_quality": 6,
        "indoor": 2, "heated_indoor_pool": True,
        "mosque_name": "Senzo Mall Mosque (short taxi)", "mosque_walk_minutes": 20,
        "food_review_summary": "Water-park family reviews dominate; buffet variety praised; kids-club and slides keep teens engaged",
    },
    # ── EXPANDED GEOGRAPHY criteria ──
    "Sheraton Fuerteventura Beach, Golf & Spa Resort": {
        "luxury": 7, "food": 7, "winter": 7, "mosque": 0, "activities": 7, "flight_quality": 7,
        "indoor": 2, "heated_indoor_pool": True,
        "mosque_name": "No mosque on Fuerteventura — nearest Masjid Taibah, Las Palmas (Gran Canaria)", "mosque_walk_minutes": 240,
        "food_review_summary": "Beachfront location and breakfast praised; family-pool complex loved; some say rooms need refresh",
    },
    "Gran Hotel Atlantis Bahía Real": {
        "luxury": 8, "food": 8, "winter": 7, "mosque": 0, "activities": 6, "flight_quality": 7,
        "indoor": 2, "heated_indoor_pool": True,
        "mosque_name": "No mosque on Fuerteventura — nearest Masjid Taibah, Las Palmas (Gran Canaria)", "mosque_walk_minutes": 240,
        "food_review_summary": "Buffet quality and spa circuit stand out; service consistently rated; premium bar prices noted",
    },
    "Lopesan Costa Meloneras Resort & Spa": {
        "luxury": 8, "food": 7, "winter": 8, "mosque": 1, "activities": 8, "flight_quality": 7,
        "indoor": 3, "heated_indoor_pool": True,
        "mosque_name": "Masjid Taibah, Las Palmas (35 min drive)", "mosque_walk_minutes": 35,
        "food_review_summary": "Scale and lagoon pools impress; breakfast variety praised; long walks to far rooms divide reviewers",
    },
    "Seaside Palm Beach": {
        "luxury": 8, "food": 8, "winter": 7, "mosque": 1, "activities": 6, "flight_quality": 7,
        "indoor": 2, "heated_indoor_pool": True,
        "mosque_name": "Masjid Taibah, Las Palmas (35 min drive)", "mosque_walk_minutes": 35,
        "food_review_summary": "Dining quality above island norm; elegant interiors; some say the beach strip is compact",
    },
    "Elysium Hotel": {
        "luxury": 8, "food": 7, "winter": 6, "mosque": 5, "activities": 6, "flight_quality": 7,
        "indoor": 2, "heated_indoor_pool": True,
        "mosque_name": "Paphos Grand Mosque, Kato Paphos (10 min walk)", "mosque_walk_minutes": 10,
        "food_review_summary": "Harbour-view dining and service praised; rooftop bar a highlight; beach is small and partly rocky",
    },
    "Annabelle Hotel": {
        "luxury": 8, "food": 8, "winter": 6, "mosque": 4, "activities": 6, "flight_quality": 7,
        "indoor": 2, "heated_indoor_pool": True,
        "mosque_name": "Paphos Grand Mosque, Kato Paphos (15 min walk)", "mosque_walk_minutes": 15,
        "food_review_summary": "Food and staff rated exceptional; gardens and lagoon pools loved; sunbed competition in peak weeks",
    },
    "Hard Rock Hotel Tenerife": {
        "luxury": 8, "food": 7, "winter": 8, "mosque": 1, "activities": 8, "flight_quality": 7,
        "indoor": 2, "heated_indoor_pool": True,
        "mosque_name": "Mezquita de Santa Cruz (75 min drive)", "mosque_walk_minutes": 75,
        "food_review_summary": "Rock-spa and lagoon dominate reviews; dining good but premium-priced; music theme divides reviewers",
    },
    "Princesa Yaiza Suite Hotel Resort": {
        "luxury": 8, "food": 7, "winter": 7, "mosque": 1, "activities": 8, "flight_quality": 7,
        "indoor": 2, "heated_indoor_pool": True,
        "mosque_name": "No mosque on Lanzarote — Arrecife prayer room (30 min)", "mosque_walk_minutes": 30,
        "food_review_summary": "Kikoland kids' park praised heavily; buffet solid; thalasso spa highlighted in winter reviews",
    },
    "Kempinski Nile Hotel Cairo": {
        "luxury": 9, "food": 8, "winter": 7, "mosque": 9, "activities": 6, "flight_quality": 7,
        "indoor": 2, "heated_indoor_pool": True,
        "mosque_name": "Mosque of Omar Makram, Tahrir", "mosque_walk_minutes": 8,
        "food_review_summary": "Nile-view dining and breakfast praised; small-hotel service consistency noted across recent reviews",
    },
    "Marriott Mena House": {
        "luxury": 9, "food": 8, "winter": 7, "mosque": 9, "activities": 7, "flight_quality": 7,
        "indoor": 2, "heated_indoor_pool": True,
        "mosque_name": "Nazlet El-Seman mosque at pyramids gate", "mosque_walk_minutes": 10,
        "food_review_summary": "Pyramid-view breakfast is the review signature; gardens and Indian restaurant consistently praised",
    },
    "JW Marriott Hotel Cairo": {
        "luxury": 8, "food": 8, "winter": 6, "mosque": 8, "activities": 7, "flight_quality": 7,
        "indoor": 3, "heated_indoor_pool": True,
        "mosque_name": "Al-Nour Mosque, Abbasiya (short taxi)", "mosque_walk_minutes": 12,
        "food_review_summary": "Wave-pool resort reviews praise breakfast spread; weekend family crowds noted; golf-view dining solid",
    },
    "Vidamar Resort Madeira": {
        "luxury": 8, "food": 7, "winter": 6, "mosque": 2, "activities": 6, "flight_quality": 7,
        "indoor": 2, "heated_indoor_pool": True,
        "mosque_name": "Funchal Islamic centre prayer room", "mosque_walk_minutes": 25,
        "food_review_summary": "Cliff-lido and Levada-hike base reviews; breakfast praised; island is a hiking rather than beach destination",
    },
}


# --------------------------------------------------------------------------- #
# STRICT SEARCH PARAMETERS (user mandate, Dec 2026):
#   1. ONE family unit — 2-Bedroom Suite / Duplex / Guaranteed Interconnecting
#      rooms sleeping 5 with shared living space. NEVER 3 separate rooms.
#   2. Genuine walkable private beach attached to the hotel (no shuttles).
#   3. Pools officially heated in December to >= 28°C.
#   4. TripAdvisor >= 4.5/5.
#   5. Excluded: Jaz Aquaviva, Jungle Aqua Park, inland waterpark-only resorts.
#   6. Nonstop flights only from LHR/LGW/LTN/STN (route-verified carriers).
# Resorts without a verified 5-in-one-unit architecture are FILTERED OUT and
# reported in a transparency section — never silently dropped.

EXCLUDED_RESORTS: frozenset[str] = frozenset({
    "Jaz Aquaviva",           # user exclusion
    "Jungle Aqua Park",       # inland waterpark-only
})

#: One-unit suite architecture + hard-filter facts per resort. A resort absent
#: here has NO verified 5-in-one-unit room and is filtered with that reason.
SUITE_ARCHITECTURE: dict[str, dict[str, Any]] = {
    "Lara Barut Collection": {
        "suite_type": "2-Bedroom Family Suite (shared lounge)",
        "suite_nightly_gbp": 185.0, "suite_peak_nightly_gbp": 395.0,
        "beach_walkable": True, "pool_heated_c": 28, "tripadvisor": 4.6,
        "nonstop_from": ("LGW", "LHR"),
    },
    "Concorde De Luxe Resort": {
        "suite_type": "Duplex Family Suite (internal stairs, lounge)",
        "suite_nightly_gbp": 150.0, "suite_peak_nightly_gbp": 330.0,
        "beach_walkable": True, "pool_heated_c": 29, "tripadvisor": 4.6,
        "nonstop_from": ("LGW", "LHR"),
    },
    "Titanic Mardan Palace": {
        "suite_type": "2-Bedroom Family Suite (lagoon view)",
        "suite_nightly_gbp": 260.0, "suite_peak_nightly_gbp": 560.0,
        "beach_walkable": True, "pool_heated_c": 28, "tripadvisor": 4.7,
        "nonstop_from": ("LGW", "LHR"),
    },
    "Steigenberger ALDAU Beach Hotel": {
        "suite_type": "2-Bedroom Family Suite (500m private beach)",
        "suite_nightly_gbp": 230.0, "suite_peak_nightly_gbp": 500.0,
        "beach_walkable": True, "pool_heated_c": 28, "tripadvisor": 4.6,
        "nonstop_from": ("LGW", "LTN"),
    },
    "Hard Rock Hotel Tenerife": {
        "suite_type": "2-Bedroom Rock Suite (cove-beach lift access)",
        "suite_nightly_gbp": 300.0, "suite_peak_nightly_gbp": 580.0,
        "beach_walkable": True, "pool_heated_c": 28, "tripadvisor": 4.6,
        "nonstop_from": ("LGW", "LTN", "STN"),
    },
    "Princesa Yaiza Suite Hotel Resort": {
        "suite_type": "2-Bedroom Grand Suite (Playa Dorada front)",
        "suite_nightly_gbp": 320.0, "suite_peak_nightly_gbp": 640.0,
        "beach_walkable": True, "pool_heated_c": 28, "tripadvisor": 4.7,
        "nonstop_from": ("LGW", "STN"),
    },
    # ── EXPANDED GEOGRAPHY: verified 5-in-one-unit suites ──
    "Sheraton Fuerteventura Beach, Golf & Spa Resort": {
        "suite_type": "2-Bedroom Family Suite (Caleta beachfront)",
        "suite_nightly_gbp": 240.0, "suite_peak_nightly_gbp": 520.0,
        "beach_walkable": True, "pool_heated_c": 28, "tripadvisor": 4.5,
        "nonstop_from": ("LGW", "LTN", "STN"),
    },
    "Gran Hotel Atlantis Bahía Real": {
        "suite_type": "2-Bedroom Suite (Corralejo beachfront)",
        "suite_nightly_gbp": 280.0, "suite_peak_nightly_gbp": 580.0,
        "beach_walkable": True, "pool_heated_c": 28, "tripadvisor": 4.5,
        "nonstop_from": ("LGW", "STN"),
    },
    "Lopesan Costa Meloneras Resort & Spa": {
        "suite_type": "2-Bedroom Family Suite (dunes side)",
        "suite_nightly_gbp": 260.0, "suite_peak_nightly_gbp": 540.0,
        "beach_walkable": True, "pool_heated_c": 28, "tripadvisor": 4.5,
        "nonstop_from": ("LGW", "LTN", "STN"),
    },
    "Seaside Palm Beach": {
        "suite_type": "2-Bedroom Family Suite (Playa del Inglés front)",
        "suite_nightly_gbp": 250.0, "suite_peak_nightly_gbp": 520.0,
        "beach_walkable": True, "pool_heated_c": 28, "tripadvisor": 4.5,
        "nonstop_from": ("LGW", "STN"),
    },
    "Elysium Hotel": {
        "suite_type": "2-Bedroom Family Suite (tomb-view side)",
        "suite_nightly_gbp": 230.0, "suite_peak_nightly_gbp": 480.0,
        "beach_walkable": True, "pool_heated_c": 28, "tripadvisor": 4.5,
        "nonstop_from": ("STN", "LGW"),
    },
    "Annabelle Hotel": {
        "suite_type": "2-Bedroom Family Suite (harbourfront gardens)",
        "suite_nightly_gbp": 240.0, "suite_peak_nightly_gbp": 500.0,
        "beach_walkable": True, "pool_heated_c": 28, "tripadvisor": 4.6,
        "nonstop_from": ("STN", "LGW"),
    },
    # ── 2× CONNECTING-ROOMS FALLBACK (user workaround): OTA search APIs
    # cannot guarantee interconnecting rooms, but these hotels confirm the
    # connection as a post-booking request. Quoted as ONE booking of 2
    # rooms; deep links request 2 rooms. Old hard filter removed so these
    # resorts compete again.
    "Vidamar Resort Madeira": {
        "suite_type": "2× Connecting Rooms (request post-booking)",
        "suite_nightly_gbp": 240.0, "suite_peak_nightly_gbp": 500.0,
        "rooms_in_unit": 2,
        "beach_walkable": False,  # volcanic cliffs & lidos, no sand beach
        "pool_heated_c": 28, "tripadvisor": 4.4,
        "nonstop_from": ("LGW", "STN"),
    },
    # ── JULY LONG-HAUL (SUMMER_RESORT_CATALOG), read 2026-09-29. The unit is
    # the one priced in the catalogue entry; where no single unit takes 5
    # adults the unit is two rooms on one booking (``rooms_in_unit: 2``), NOT a
    # guaranteed connecting pair. ``pool_heated_c`` 0 = not assessed: the
    # >=28°C heated-pool rule is a December rule and these resorts are only
    # priced for summer trips. ``tripadvisor`` None = could not be read, and
    # the report says the >=4.5 gate was not applied.
    "Pullman Lombok Merujani Mandalika Beach Resort": {
        "suite_type": "Two-Bedroom Garden Villa, private pool (6 guests max)",
        "suite_nightly_gbp": 720.38, "suite_peak_nightly_gbp": 720.38,
        "beach_walkable": True, "pool_heated_c": 0, "tripadvisor": None,
        "nonstop_from": (),
    },
    "Novotel Lombok Resort & Villas": {
        "suite_type": "Ocean View Family Villa (2 bedrooms, 3 adults) + Superior room (2 adults) — 2 rooms",
        "suite_nightly_gbp": 372.61, "suite_peak_nightly_gbp": 372.61,
        "rooms_in_unit": 2,
        "beach_walkable": True, "pool_heated_c": 0, "tripadvisor": None,
        "nonstop_from": (),
    },
    "Garrya Tongsai Bay Samui": {
        "suite_type": "2× Beachfront Suite (3 + 2 adults) — 2 rooms",
        "suite_nightly_gbp": 652.19, "suite_peak_nightly_gbp": 652.19,
        "rooms_in_unit": 2,
        "beach_walkable": True, "pool_heated_c": 0, "tripadvisor": None,
        "nonstop_from": (),
    },
    "Banyan Tree Samui": {
        "suite_type": "Family Horizon Hillcrest Pool Villa (5 guests max)",
        "suite_nightly_gbp": 1212.21, "suite_peak_nightly_gbp": 1212.21,
        "beach_walkable": True, "pool_heated_c": 0, "tripadvisor": None,
        "nonstop_from": (),
    },
    "Kimpton Kitalay Samui": {
        "suite_type": "2× One-Bedroom Suite, resort view (4 guests max each) — 2 rooms",
        "suite_nightly_gbp": 1654.09, "suite_peak_nightly_gbp": 1654.09,
        "rooms_in_unit": 2,
        "beach_walkable": True, "pool_heated_c": 0, "tripadvisor": None,
        "nonstop_from": (),
    },
    "Anantara Rasananda Koh Phangan Villas": {
        # Unit corrected 2026-10-03 (H6): the Two Bedroom Pool Villa is the
        # one-booking unit for 5, confirmed rather than "likely". The Google
        # Hotels listing price is WITHDRAWN — it said nothing about what the
        # rate included and named no unit — so the nightly rate is 0 and the
        # card forms only once an exact-date rate is read.
        "suite_type": "Two Bedroom Pool Villa (one unit for 5, 220 m², up to 6 adults)",
        "suite_nightly_gbp": 0.0, "suite_peak_nightly_gbp": 0.0,
        "rooms_in_unit": 1,
        "beach_walkable": True, "pool_heated_c": 0, "tripadvisor": None,
        "nonstop_from": (),
    },
    # ── PROPERTIES WITH A UNIT BUT NO RATE (owner brief 2026-10-03, H6).
    # ``suite_nightly_gbp`` 0.0 is the "no price" marker: the collector makes
    # no card for these until the private engine reads an exact-date rate,
    # because a stay priced at zero and a package total that is really just
    # the flights are both worse than no card. ``pool_heated_c`` 0 = not
    # assessed (a December rule; these are summer-only). ``tripadvisor`` None =
    # could not be read, so the >=4.5 gate is not applied and the report says so.
    "The Lombok Lodge": {
        "suite_type": "Two-Bedroom Villa",
        "suite_nightly_gbp": 0.0, "suite_peak_nightly_gbp": 0.0,
        "rooms_in_unit": 1,
        "beach_walkable": True, "pool_heated_c": 0, "tripadvisor": None,
        "nonstop_from": (),
    },
    "TUNAK Resort Lombok": {
        "suite_type": "Two-bedroom Cliff Front Private Pool Villa",
        "suite_nightly_gbp": 0.0, "suite_peak_nightly_gbp": 0.0,
        "rooms_in_unit": 1,
        "beach_walkable": True, "pool_heated_c": 0, "tripadvisor": None,
        "nonstop_from": (),
    },
    "Kalandara Resort Lombok": {
        "suite_type": "AKASA 2 Bedroom Pool Villa",
        "suite_nightly_gbp": 0.0, "suite_peak_nightly_gbp": 0.0,
        "rooms_in_unit": 1,
        "beach_walkable": True, "pool_heated_c": 0, "tripadvisor": None,
        "nonstop_from": (),
    },
    "Pullman Khao Lak Resort": {
        "suite_type": "Family Suite (3 adults, 5 guests max) + Deluxe Room (2 adults) — 2 rooms",
        "suite_nightly_gbp": 162.18, "suite_peak_nightly_gbp": 162.18,
        "rooms_in_unit": 2,
        "beach_walkable": True, "pool_heated_c": 0, "tripadvisor": None,
        "nonstop_from": (),
    },    # ── DECEMBER ADDITIONS (2026-09-30). ``pool_heated_c`` None = not read:
    # the December >=28°C heated-pool gate is then not applied, and the report
    # names the resort in its "rule not applied" block (as with TripAdvisor).
    "Rixos Gulf Hotel Doha": {
        "suite_type": "Two Bedroom Family Room (3 adults, 6 guests max) + Superior Room (2 adults) — 2 rooms",
        "suite_nightly_gbp": 894.72, "suite_peak_nightly_gbp": 894.72,
        "rooms_in_unit": 2,
        "beach_walkable": True, "pool_heated_c": None, "tripadvisor": None,
        "nonstop_from": ("LHR",),
    },
    "InterContinental Muscat": {
        "suite_type": "2 rooms on one booking (3 + 2 adults)",
        "suite_nightly_gbp": 748.03, "suite_peak_nightly_gbp": 748.03,
        "rooms_in_unit": 2,
        "beach_walkable": True, "pool_heated_c": None, "tripadvisor": None,
        "nonstop_from": ("LHR",),
    },
    "Nungwi Dreams by Mantis": {
        # The one-booking unit for 5 is the four-bedroom Presidential Villa
        # (owner brief 2026-10-03, H6), not three Standard Rooms. The nightly
        # rate here is still the December half-board one and the summer entry's
        # own board_options carry its July rate (see _suite_for); the unit
        # change is what the brief corrected, and it is flagged on the card
        # because four bedrooms is more space than five people need.
        "suite_type": "4-Bedroom Presidential Villa (one unit for 5)",
        "suite_nightly_gbp": 1120.04, "suite_peak_nightly_gbp": 1120.04,
        "rooms_in_unit": 1,
        "beach_walkable": True, "pool_heated_c": None, "tripadvisor": None,
        "nonstop_from": (),
    },
    "Sofitel Mauritius L'Impérial Resort & Spa": {
        "suite_type": "3× Luxury Room (2 + 2 + 1 adults; 2 adults per room at most) — 3 rooms",
        "suite_nightly_gbp": 1860.44, "suite_peak_nightly_gbp": 1860.44,
        "rooms_in_unit": 3,
        "beach_walkable": True, "pool_heated_c": None, "tripadvisor": None,
        "nonstop_from": (),
    },
    "Grand Fiesta Americana Coral Beach Cancún All Inclusive Spa & Resort": {
        # December unit corrected 2026-10-03 (H6): the Ocean Front Two Bedroom
        # Family & Friends Suite is ONE booking for 5, so this is no longer a
        # "cheapest option on Google Hotels" of unknown unit.
        "suite_type": "Ocean Front Two Bedroom Family & Friends Suite (one unit for 5)",
        "suite_nightly_gbp": 2814.0, "suite_peak_nightly_gbp": 2814.0,
        "rooms_in_unit": 1,
        "beach_walkable": True, "pool_heated_c": None, "tripadvisor": None,
        "nonstop_from": ("LHR",),
    },
}


# ── BOARD BASIS (owner rules 2026-09-30) ──────────────────────────────────
#: Every hotel deal includes breakfast at minimum. These are the bases that do.
BREAKFAST_BASES: frozenset[str] = frozenset({"BB", "HB", "FB", "AI"})
BOARD_ROOM_ONLY = "RO"
BOARD_UNVERIFIED = "UNVERIFIED"
#: The words the report prints for each basis.
BOARD_LABELS: dict[str, str] = {
    "BB": "Bed & Breakfast",
    "HB": "Half Board",
    "FB": "Full Board",
    "AI": "All Inclusive",
    "RO": "Room only",
    "UNVERIFIED": "board unverified",
}
#: Islands where eating out is not realistic: every basis the hotel sells is
#: shown, each priced separately (half board, full board, all inclusive).
ISLAND_RULE_KEYS: frozenset[str] = frozenset({"maldives", "mauritius", "zanzibar", "seychelles"})


def board_code(board: Any) -> str:
    """Normalise a board description to BB / HB / FB / AI / RO / UNVERIFIED.

    Anything the text does not state plainly is UNVERIFIED: a rate whose page
    did not say what it includes is never assumed to include breakfast.
    """
    text = str(board or "").strip().lower()
    if not text or "unverified" in text:
        return BOARD_UNVERIFIED
    if "inclusive" in text:
        return "AI"
    if "full board" in text:
        return "FB"
    if "half board" in text:
        return "HB"
    if "breakfast" in text:
        return "BB"
    if "room only" in text:
        return BOARD_ROOM_ONLY
    return BOARD_UNVERIFIED


def board_problem(resort: Mapping[str, Any], *, island: bool = False) -> str:
    """Why a resort's board fails the owner's rules, or "" when it passes."""
    code = board_code(resort.get("board"))
    if code == BOARD_ROOM_ONLY:
        return "room only — not a deal: breakfast is the minimum"
    if code == BOARD_UNVERIFIED:
        return "board unverified — the rate read did not state breakfast, so it is not assumed"
    if island:
        options = tuple(resort.get("board_options") or ())
        if not options:
            return "island resort without each sold board basis priced separately"
        seen: set[str] = set()
        for option in options:
            basis = str(option.get("basis", ""))
            if basis not in BREAKFAST_BASES or basis in seen:
                return f"island board option {basis or '?'} is not a breakfast-or-better basis"
            if not float(option.get("nightly_gbp") or 0) > 0 or not str(option.get("source") or "").strip():
                return f"island board option {basis} has no read price and source"
            seen.add(basis)
        if code not in seen:
            return "the resort's headline board is not one of its priced options"
    return ""


def board_totals(resort: Mapping[str, Any], nights: int) -> tuple[dict[str, Any], ...]:
    """Each sold board basis priced for ``nights`` (island resorts), cheapest first."""
    rows = []
    for option in resort.get("board_options") or ():
        basis = str(option["basis"])
        rows.append({
            "basis": basis,
            "label": BOARD_LABELS.get(basis, basis),
            "hotel_cost": round(float(option["nightly_gbp"]) * int(nights), 2),
        })
    return tuple(sorted(rows, key=lambda row: row["hotel_cost"]))


def _unit_rooms(arch: Mapping[str, Any]) -> Optional[int]:
    """Rooms the resort's one-booking unit uses, or ``None`` when unknown.

    The one-booking rule turns on this number, so "unknown" must not silently
    become 1. A verified 2-bedroom suite (or a two-room booking) omits the key
    and is one unit; a resort whose unit was never shown in the source returns
    ``None`` (as does an explicit ``None``), and is filtered rather than
    assumed.
    """
    if "unit not shown" in str(arch.get("suite_type", "")).lower():
        return None
    rooms = arch.get("rooms_in_unit", 1)
    return None if rooms is None else int(rooms)


def filter_resorts(
    resorts: list[dict[str, Any]], *, is_summer: bool = False, island: bool = False
) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
    """Apply the strict filters; return (passing, [(name, reason)] for the rest."""
    kept: list[dict[str, Any]] = []
    dropped: list[tuple[str, str]] = []
    for resort in resorts:
        name = resort["name"]
        if name in EXCLUDED_RESORTS:
            dropped.append((name, "user exclusion / waterpark-only"))
            continue
        arch = SUITE_ARCHITECTURE.get(name)
        if arch is None:
            dropped.append((name, "no verified one-unit room sleeping 5 (2-bed suite / interconnecting)"))
            continue
        # The one-booking rule (owner, 2026-10-02): 5 travellers book ONE unit —
        # a 2-bedroom suite/villa or two rooms on the same booking. A resort
        # whose only verified option is THREE separate rooms is not a deal,
        # however cheap it looks: it must never become a card. An unknown unit
        # ("unit not shown") is not a confirmed one-booking unit either.
        rooms_in_unit = _unit_rooms(arch)
        if rooms_in_unit is None:
            dropped.append((name, "unit not verified - cannot confirm one booking for 5"))
            continue
        if rooms_in_unit >= 3:
            dropped.append((name, "needs 3 rooms — breaks the one-unit rule"))
            continue
        if not arch["beach_walkable"]:
            dropped.append((name, "no genuine walkable private beach attached"))
            continue
        if not is_summer and arch["pool_heated_c"] is not None and arch["pool_heated_c"] < 28:
            dropped.append((name, f"pools not heated to >=28°C in December ({arch['pool_heated_c']}°C)"))
            continue
        # None = the rating could not be read. The gate is then NOT applied
        # (the resort is kept), and the report names every such resort in its
        # transparency block: keeping it silently would claim a check that was
        # never made, dropping it would hide a destination the owner asked for.
        if arch["tripadvisor"] is not None and arch["tripadvisor"] < 4.5:
            dropped.append((name, f"TripAdvisor {arch['tripadvisor']} < 4.5"))
            continue
        problem = board_problem(resort, island=island)
        if problem:
            dropped.append((name, problem))
            continue
        kept.append(resort)
    return kept, dropped


def _suite_for(resort: Mapping[str, Any]) -> dict[str, Any]:
    """The unit's pricing facts for THIS catalogue entry.

    A resort sold in both seasons (Nungwi Dreams: July Bed & Breakfast,
    December half board) has one architecture row but two rates: when the
    entry prices its board options, the headline basis's nightly rate is the
    one this entry's cards are priced at.
    """
    arch = dict(SUITE_ARCHITECTURE[resort["name"]])
    options = resort.get("board_options") or ()
    if options:
        nightly = float(min(options, key=lambda o: float(o["nightly_gbp"]))["nightly_gbp"])
        arch["suite_nightly_gbp"] = nightly
        arch["suite_peak_nightly_gbp"] = nightly
    return arch


def pool_heating_unverified(resort_name: str) -> bool:
    """True when a resort's December pool heating was not read."""
    arch = SUITE_ARCHITECTURE.get(resort_name)
    return arch is not None and arch.get("pool_heated_c") is None


def tripadvisor_unverified(resort_name: str) -> bool:
    """True when a resort's TripAdvisor rating could not be read."""
    arch = SUITE_ARCHITECTURE.get(resort_name)
    return arch is not None and arch.get("tripadvisor") is None


# UK ground transit from Watford Junction (return, whole party share).
# True D2D = package (flights + hotel) + UK ground + destination transfer.
UK_GROUND_RETURN_GBP: dict[str, float] = {
    "LHR": 16.50,  # RailAir RA3 Express Coach, 45 min
    "LGW": 34.00,  # Southern Rail via Clapham Junction, 90 min
    "LTN": 14.50,  # National Rail Thameslink, 55 min
    "STN": 14.50,  # National Rail, approx
    "BHX": 40.00,  # Avanti West Coast direct, 58 min
}

# Carriers with NO business/premium cabin — never label them as luxury.
# SunExpress, Pegasus, Ryanair, easyJet, Jet2, Wizz Air are single-cabin
# (economy-only) operators on these leisure routes. Stamping their names on
# a "Business Class" card (2026-09-19 bug) is a false claim: the benchmark
# multiplier prices a cabin they do not sell.
LCC_NO_PREMIUM_CABIN: frozenset[str] = frozenset({
    "sunexpress", "pegasus", "pegasus airlines", "ryanair", "easyjet",
    "easy jet", "jet2", "wizz air", "wizz air uk",
})

# Real business-capable carriers per destination airport. Used whenever the
# requested cabin is BUSINESS/FIRST/PREMIUM_ECONOMY so the card names an
# airline that actually sells that cabin on the London route — never an LCC.
# Short-haul "business" is Club Europe / Turkish Business (blocked middle
# seat + lounge + priority, not lie-flat); long-haul is true lie-flat.
# Prices remain market-supported BENCHMARKS (multiplier estimate), never live
# verified totals — live cabin-exact verification runs on private browser
# compute only (dealsearch holiday_scraper/live).
BUSINESS_CARRIER_BY_AIRPORT: dict[str, str] = {
    "AYT": "Turkish Airlines Business (via IST)",
    "PFO": "British Airways Club Europe",
    "HRG": "Turkish Airlines Business (via IST)",
    "CAI": "British Airways Club Europe / EgyptAir Business",
    "TFS": "British Airways Club Europe",
    "ACE": "British Airways Club Europe",
    "FUE": "British Airways Club Europe",
    "LPA": "British Airways Club Europe",
    "MLA": "British Airways Club Europe",
    "AGA": "British Airways Club Europe",
    "FNC": "British Airways Club Europe",
    "SID": "TUI / British Airways (best available premium cabin)",
    "MCT": "Oman Air Business / British Airways Club World",
    "DOH": "Qatar Airways Business / British Airways Club World",
    # July long-haul (Google Flights, 20-27 Jul 2027, read 2026-09-29).
    "HKT": "Etihad / Qatar Airways / THAI Business (1 stop)",
    "USM": "British Airways Club World + Bangkok Airways (1 stop via SIN); or EVA Air / Etihad Business with an Economy hop",
    "LOP": ("Business on the long sector only — no Business cabin into Lombok "
            "(Scoot / Garuda Economy on the final leg; unpriced combination)"),
    "ZNZ": "Ethiopian / EgyptAir / Etihad Business (1 stop)",
    "MRU": "Air France + Air Mauritius / Emirates Business (1 stop)",
    "CUN": "Virgin Atlantic Upper Class (nonstop)",
}

PREMIUM_CARRIER_BY_AIRPORT: dict[str, str] = {
    "AYT": "Turkish Airlines Premium (via IST) / BA Euro Traveller Plus",
    "PFO": "British Airways Euro Traveller Plus",
    "HRG": "Turkish Airlines Premium (via IST)",
    "CAI": "EgyptAir Premium / BA World Traveller Plus",
    "TFS": "British Airways Euro Traveller Plus",
    "ACE": "British Airways Euro Traveller Plus",
    "FUE": "British Airways Euro Traveller Plus",
    "LPA": "British Airways Euro Traveller Plus",
    "MLA": "British Airways Euro Traveller Plus",
    "AGA": "British Airways Euro Traveller Plus",
    "FNC": "British Airways Euro Traveller Plus",
    "SID": "TUI Premium / BA Euro Traveller Plus",
    "MCT": "Oman Air Premium / BA World Traveller Plus",
    "DOH": "Qatar Airways Premium / BA World Traveller Plus",
}


def cabin_carrier(*, airport: str, cabin: str, economy_carrier: str) -> str:
    """Return the display carrier for a cabin — never an LCC as luxury."""
    upper = (cabin or "ECONOMY").upper()
    code = (airport or "").upper()
    if upper == "BUSINESS" or upper == "FIRST":
        return BUSINESS_CARRIER_BY_AIRPORT.get(code, "Flag carrier Business (live check required)")
    if upper == "PREMIUM_ECONOMY":
        return PREMIUM_CARRIER_BY_AIRPORT.get(code, "Flag carrier Premium (live check required)")
    return economy_carrier


def _criteria_from_facts(facts: Sequence[Any]) -> dict[str, float]:
    """Criteria inputs this report can state because the engine READ them.

    The registry's curated 0-10 scores are hand-assigned, and a resort with no
    registry entry falls back to neutral defaults — which is why most cards
    say "value score not verified". When the private engine has read a fact
    about this property, the input it covers stops being a default and becomes
    a measurement, and the score may be shown.

    The mapping is deliberately thin and conservative: a fact either covers an
    input or it does not. Pools alone do not establish a heated pool, so they
    do not move the winter score, and nothing here infers a number nobody
    stated.
    """
    overrides: dict[str, float] = {}
    fields = {getattr(fact, "field", ""): getattr(fact, "stated", "")
              for fact in (facts or ())}

    kids = fields.get("kids_club") or fields.get("pools_kids_restaurants")
    if kids:
        # A club with a stated age range is a real, age-appropriate activity.
        overrides["activities"] = 6.0
    restaurants = (fields.get("restaurants") or fields.get("restaurants_bars")
                   or fields.get("pools_kids_restaurants"))
    if restaurants:
        # Stated on-site restaurants are what the food score measures: the
        # number of venues, not whether we think the food is good.
        overrides["food"] = 6.0

    mosque = fields.get("nearest_mosque") or ""
    if mosque:
        match = re.search(r"(\d{1,3})\s*min", mosque, re.IGNORECASE)
        if match:
            minutes = int(match.group(1))
            # Drive time, not walking time: the number the reader will drive.
            if minutes <= 10:
                overrides["mosque"] = 8.0
            elif minutes <= 20:
                overrides["mosque"] = 6.0
            elif minutes <= 45:
                overrides["mosque"] = 4.0
            else:
                overrides["mosque"] = 2.0
    return overrides


def _criteria_fields(
    resort_name: str,
    true_pp: float,
    dec_avg_temp_c: Optional[float] = None,
    facts: Sequence[Any] = (),
) -> dict[str, Any]:
    """Criteria bundle for one resort from the recovered registry (defaults
    keep any un-registered resort renderable with neutral scores).

    ``facts`` are the facts the private engine read for THIS property. They
    override the registry for the inputs they cover, and their presence is
    what makes the score a measurement rather than a set of defaults.
    """
    c = dict(RESORT_CRITERIA.get(resort_name, {}))
    registry_has_criteria = bool(RESORT_CRITERIA.get(resort_name))
    indoor = int(c.get("indoor", 2))
    heated = bool(c.get("heated_indoor_pool", False))
    # Facts read for THIS property by the private engine override the registry
    # for the inputs they cover: they are the fresher, property-specific
    # reading, and they are the difference between a measured score and the
    # neutral defaults.
    fact_inputs = _criteria_from_facts(facts)
    c.update(fact_inputs)
    value = compute_value_score(
        true_pp=true_pp,
        luxury=float(c.get("luxury", 5)),
        food=float(c.get("food", 5)),
        winter=float(c.get("winter", 5)),
        mosque=float(c.get("mosque", 5)),
        activities=float(c.get("activities", 5)),
        flight_quality=float(c.get("flight_quality", 7)),
        indoor_activity_count=indoor,
        heated_indoor_pool=heated,
        dec_avg_temp_c=dec_avg_temp_c,
    )
    return {
        "actual_luxury_score": float(c.get("luxury", 5)),
        "food_reality_score": float(c.get("food", 5)),
        "winter_facilities_score": float(c.get("winter", 5)),
        "mosque_location_score": float(c.get("mosque", 5)),
        "activities_score": float(c.get("activities", 5)),
        "flight_quality_score": float(c.get("flight_quality", 7)),
        "value_score": value,
        # Whether that score came from real inputs: this resort's own criteria
        # in the registry, or facts read for it by the private engine. A
        # default-derived score is not a measurement, so it is named unknown on
        # the card rather than printed as a number (T11b).
        "value_score_verified": bool(registry_has_criteria or fact_inputs),
        "value_score_from_facts": sorted(fact_inputs),
        "mosque_name": c.get("mosque_name", ""),
        "mosque_walk_minutes": int(c.get("mosque_walk_minutes", 0)),
        "food_review_summary": c.get("food_review_summary", ""),
        "indoor_activity_count": indoor,
        "heated_indoor_pool": heated,
        "deal_class": _classify_deal_price(true_pp),
    }


def _highlights_with_blocked_sources(
    highlights: Sequence[str], blocked: Sequence[Any]
) -> tuple[str, ...]:
    """Rewrite "X >=4.5 not verified" as "X blocked (reason)".

    The catalogue says the review gate was not applied because the rating could
    not be read. When the engine has since tried and been refused by a bot
    wall, that is a stronger and more useful fact: it is not a gap in our
    research, it is the source saying no. Saying "not verified" there would
    quietly imply the rating was looked for, found and found wanting.
    """
    out: list[str] = []
    for line in highlights:
        text = str(line)
        for entry in blocked:
            claim = f"{entry.what} ≥4.5 not verified"
            if claim in text:
                text = text.replace(claim, f"{entry.what} blocked ({entry.reason})")
        out.append(text)
    return tuple(out)


def _space_flag(suite_type: str, travellers: int) -> str:
    """A unit that is bigger than the party needs, said plainly.

    A four-bedroom villa for five people is not a better match, it is a
    different one, and the reader is entitled to know before they fall for it
    on the room count. Only stated bedrooms count: the unit name is the
    hotel's, and nothing here infers a size the hotel did not publish.
    """
    text = str(suite_type or "")
    match = re.search(r"(\d+)[-\s]?bedroom", text, re.IGNORECASE)
    if not match:
        return ""
    bedrooms = int(match.group(1))
    if bedrooms >= 4:
        return (f"{bedrooms}-bedroom villa — more space than "
                f"{int(travellers)} need")
    return ""


def _rate_board_matches(resort: Mapping[str, Any], rate: Any) -> bool:
    """True when the read rate's board is one this property can actually be had on.

    An all-inclusive-only resort does not sell a breakfast rate, so a BB rate
    read for it is a rate that cannot be booked and must not price a card. A
    catalogue board of "unverified" is the opposite case: the property's board
    is unknown, so a rate that STATES its board settles the question rather
    than being rejected for the catalogue's silence.
    """
    if rate is None:
        return False
    catalogue = board_code(resort.get("board"))
    read = str(getattr(rate, "board", "") or "").strip().upper()
    if catalogue == BOARD_UNVERIFIED:
        return read in BREAKFAST_BASES
    return bool(read) and read == catalogue


def _board_for_card(resort: Mapping[str, Any], rate: Any) -> str:
    """The board the card shows: the read rate's when there is one.

    A rate the engine read states its own board, and that is a measurement;
    the catalogue's "unverified" is not. Showing the catalogue label beside a
    priced rate would misdescribe what the card is selling.
    """
    read = str(getattr(rate, "board", "") or "").strip().upper()
    if read and read in BOARD_LABELS:
        return BOARD_LABELS[read]
    return str(resort.get("board") or "")


def _unit_check_findings(resort_name: str, config) -> tuple[tuple[str, str], ...]:
    """``(finding, dates)`` for this property's unit checks, per date pair.

    A property that refuses five adults for one week may well take them for

    A property that refuses five adults for one week may well take them for
    another, so a check only speaks for the dates it was made on.
    """
    from .holidays import priceable_date_pairs

    out: list[tuple[str, str]] = []
    for outbound, returning in priceable_date_pairs(config):
        for check in supplemental_for(
            resort_name, "unit_checks", dates=(outbound, returning)
        ):
            out.append((check.finding, f"{outbound}→{returning}"))
    return tuple(out)


def _unit_check_refusal(resort_name: str, config, *, travellers: int,
                        hotel_evidence=None) -> str:
    """Why this property cannot take the party in one booking, else "".

    A unit check removes a resort ONLY when the loader found no qualifying
    one-booking rate for it on those dates. "5 adults in one room refused ...
    sold as 2 rooms in one booking" is a refusal of ONE room, not of the
    party: two rooms on one booking is what the owner's rule asks for, the
    loader had a qualifying rate, and removing the resort on those words cost
    July two good cards.

    Where a qualifying rate exists the finding is still true and still worth
    saying, so it becomes a note on the card (``_unit_check_note``) instead of
    a removal.
    """
    for finding, dates in _unit_check_findings(resort_name, config):
        if not unit_check_blocks_party(finding, travellers):
            continue
        outbound, _, returning = dates.partition("→")
        if hotel_rate_for(hotel_evidence, resort_name, outbound, returning) is not None:
            continue
        return f"{finding} (checked {dates})"
    return ""


def _unit_check_note(resort_name: str, config, *, travellers: int,
                     hotel_evidence=None) -> str:
    """The informational note for a property that was refused and then booked.

    The finding is carried in the engine's own words: "one room for 5 refused;
    sold as 2 rooms in one booking" is exactly the thing a reader wants to
    know before choosing it, and paraphrasing it risks saying something the
    engine did not.
    """
    for finding, dates in _unit_check_findings(resort_name, config):
        if not unit_check_blocks_party(finding, travellers):
            continue
        outbound, _, returning = dates.partition("→")
        if hotel_rate_for(hotel_evidence, resort_name, outbound, returning) is None:
            continue
        return finding
    return ""


def collect_holiday_deals(
    config: HolidayConfig,
    max_budget_gbp: Optional[float] = None,
    live_flight_offers: Optional[Mapping[str, LiveFareEvidence]] = None,
    hotel_evidence: Optional[Mapping[Any, Any]] = None,
) -> tuple[PackageDeal, ...]:
    """Calculate holiday packages, enforcing the budget on BOTH the package
    total (flights + hotel) AND the True D2D total (package + UK ground +
    destination transfer). Anything over budget on either measure is dropped —
    never labelled "under budget" while breaching the ceiling.

    ``hotel_evidence`` is the loader's output (owner brief 2026-10-03, H3). Where
    a card's resort and dates have a qualifying rate, that rate prices the stay
    instead of the catalogue estimate — and the card says so. Absent, or with no
    qualifying rate, nothing changes.
    """
    if max_budget_gbp is None:
        max_budget_gbp = getattr(config, "max_budget_gbp", 5000.0)
    pairs = pricing_order(config)
    priced_pairs_set = set(pairs)
    headline = priced_date_pair(config)
    deals: list[PackageDeal] = []
    filtered_out: list[tuple[str, str]] = []
    rooms_count = len(config.rooms)
    travellers = config.travellers
    # STRICT mode: one family unit (2-bed suite/duplex/interconnecting), NOT
    # 3 separate rooms. One premium unit prices FAR below 3 rooms.
    strict_unit = len(config.rooms) >= 3

    cabin_multipliers = {
        "ECONOMY": 1.0,
        "PREMIUM_ECONOMY": 1.6,
        "BUSINESS": 2.5,
        "FIRST": 4.5,
    }

    def _best_option(resort, cabin, flight_mult, arch, *, enforce_budget: bool = True,
                     prefer_evidence: bool = False,
                     require_evidence: bool = False) -> Optional[dict]:
        """Best (date pair, departure origin) for one resort that clears
        BOTH ceilings, or None when no combination does.

        ``enforce_budget=False`` answers the second question the report asks
        of a resort that failed the first: what would its cheapest option have
        cost? It is used only to state an over-budget resort's price, never to
        make a card.

        This is the whole of the "wider search": every priceable pair and
        every configured origin is evaluated instead of one middle pair from
        ``origins[0]``, and the reader sees the winner with its own dates,
        origin, nights and ground cost. Three rules keep the widening honest:

        * a benchmark may only price a departure from ``origins[0]`` — flight
          benchmarks carry no origin, so claiming a cheaper LGW departure
          from an LHR benchmark would be a fabricated origin;
        * ``require_evidence`` refuses the benchmark altogether. It exists for
          the mixed-cabin row, which describes a fare that was actually READ
          for a party that did not fly in one cabin: there is no benchmark for
          "Premium Economy long-haul + Economy hop", and inventing one would
          be inventing the thing the row is meant to describe.
        * a tie resolves to the first candidate evaluated, and ``pairs`` /
          ``config.origins`` lead with the headline pair and the declared
          origin, so a benchmark-only run still displays the pair the
          evidence contract states.

        ``prefer_evidence`` ranks the candidates by evidence first and price
        second (owner brief 2026-10-04, H5). The reader wants real prices: a
        pair somebody priced for this exact holiday beats a cheaper pair that
        is only modelled, and within one evidence class the cheapest still
        wins. The class is ``option_evidence_class`` — a read fare and a read
        hotel rate are the same kind of claim, and two of them beat one. It
        changes WHICH PAIR the card is built on and nothing else: the budget
        test above still admits and rejects exactly the same candidates, a
        resort that made a card still makes one, and the resorts are still
        ranked against each other afterwards.
        """
        def _rank(option: dict) -> tuple[float, ...]:
            # Strictly less-than below, so a tie keeps the first candidate
            # evaluated — and ``pairs`` leads with the headline pair.
            if not prefer_evidence:
                return (option["total_pkg"], option["true_d2d"])
            return (
                -float(option_evidence_class(option)),
                option["total_pkg"],
                option["true_d2d"],
            )

        best: Optional[dict] = None
        for outbound, returning in pairs:
            nights = nights_between((outbound, returning))
            # A rate read for THIS resort on THESE dates beats the catalogue
            # estimate or nearest-date figure for the same property: it is the
            # price for the stay the card is offering. It is looked up per pair
            # because a rate for one set of nights is not a rate for another.
            hotel_rate = hotel_rate_for(hotel_evidence, resort["name"], outbound, returning)
            if hotel_rate is not None and not _rate_board_matches(resort, hotel_rate.cheapest):
                # A rate for a board this property does not sell (or, when the
                # catalogue does not know, a rate that did not state its
                # board) cannot price this card.
                hotel_rate = None
            if hotel_rate is not None:
                hotel_cost = round(float(hotel_rate.cheapest.price_gbp), 2)
            else:
                hotel_cost = round(arch["suite_nightly_gbp"] * nights, 2)
            peak_hotel = round(arch["suite_peak_nightly_gbp"] * nights, 2)
            if hotel_rate is None and not arch.get("suite_nightly_gbp"):
                # NO PRICE, NO CARD. This entry carries a unit and public facts
                # but no rate: pricing it from nothing would show a stay at
                # zero and a package total that is really just the flights.
                continue
            for origin_index, origin in enumerate(config.origins):
                # Live evidence must be a WHOLE-PARTY, exact-date amount for
                # THIS pair, THIS origin and THIS cabin, or it prices nothing.
                evidence = evidence_for(
                    live_flight_offers,
                    resort["airport"],
                    cabin.upper(),
                    outbound,
                    returning,
                    origin,
                    headline=headline,
                )
                evidence_used = bool(evidence is not None and evidence.usable)
                if require_evidence and not evidence_used:
                    continue
                if origin_index and not evidence_used:
                    continue
                flight_cost = (
                    evidence.total_gbp
                    if evidence_used
                    else round(resort["flight_benchmark_5pax_gbp"] * flight_mult, 2)
                )
                transfer = float(resort.get("transfer_gbp", 30.0))
                uk_ground = UK_GROUND_RETURN_GBP.get(origin, 16.50)
                total_pkg = round(flight_cost + hotel_cost, 2)
                true_d2d = round(total_pkg + uk_ground + transfer, 2)
                # STRICT: both measures must clear the ceiling.
                if enforce_budget and not (
                    total_pkg <= max_budget_gbp and true_d2d <= max_budget_gbp
                ):
                    continue
                option = {
                    "outbound": outbound,
                    "return": returning,
                    "nights": nights,
                    "origin": origin,
                    "uk_ground": uk_ground,
                    "transfer": transfer,
                    "flight_cost": flight_cost,
                    "hotel_cost": hotel_cost,
                    "total_pkg": total_pkg,
                    "true_d2d": true_d2d,
                    "peak_hotel": peak_hotel,
                    "evidence": evidence,
                    "evidence_used": evidence_used,
                    "hotel_rate": hotel_rate,
                }
                if best is None or _rank(option) < _rank(best):
                    best = option
        return best

    def _within(total_pkg: float, true_d2d: float) -> bool:
        return total_pkg <= max_budget_gbp and true_d2d <= max_budget_gbp

    def _option_row(kind: str, cabin: str, picked: dict, basis: str) -> dict:
        return {
            "kind": kind,
            "cabin": cabin,
            "hub": None,
            "outbound": picked["outbound"],
            "return": picked["return"],
            "nights": picked["nights"],
            "origin": picked["origin"],
            "flight_cost": picked["flight_cost"],
            "hotel_cost": picked["hotel_cost"],
            "stopover_hotel_cost": 0.0,
            "stopover_nights": 0,
            "uk_ground": picked["uk_ground"],
            "transfer": picked["transfer"],
            "total_pkg": picked["total_pkg"],
            "true_d2d": picked["true_d2d"],
            "flight_basis": basis,
            "within_budget": _within(picked["total_pkg"], picked["true_d2d"]),
        }

    def _evidence_words(picked: dict, fallback: str) -> str:
        # One provenance per fare, never a mixture (owner rule 2026-10-02): a
        # read fare says when it was read, an aged one says observed-not-live,
        # everything else falls through to a benchmark or an estimate.
        evidence = picked.get("evidence")
        if picked.get("evidence_used") and evidence is not None:
            if evidence.confidence == "verified-exact-date":
                return "live fare read " + str(getattr(evidence, "observed_at", ""))[:10]
            if evidence.confidence == "stale-cache":
                return "observed fare, not live"
            return "observed fare"
        return fallback

    def _flight_options(resort, arch, business: dict) -> tuple[dict, ...]:
        """(a) Business, (b) Economy, (b2) Premium Economy on the same route,
        (c) Economy and (c2) Premium Economy with a Gulf stopover each way,
        plus any mixed-cabin fare: every one a whole-party total."""
        rows = [_option_row("business", "BUSINESS", business,
                            _evidence_words(business, "estimate: economy fare x2.5"))]
        economy = _best_option(resort, "ECONOMY", 1.0, arch, enforce_budget=False,
                               prefer_evidence=True)
        if economy is not None:
            # No evidence read for these dates: exactly "benchmark", never
            # "read" and never a second provenance word (2026-10-02).
            rows.append(_option_row("economy", "ECONOMY", economy,
                                    _evidence_words(economy, "benchmark")))
        # Live evidence is already read for PREMIUM_ECONOMY (evidence_consumption_contract
        # requests it per destination) and was previously discarded as an "unused key" —
        # this is the same _best_option seam Economy uses, just a different cabin/multiplier.
        premium_economy = _best_option(resort, "PREMIUM_ECONOMY", 1.6, arch, enforce_budget=False,
                                       prefer_evidence=True)
        if premium_economy is not None:
            rows.append(_option_row("premium_economy", "PREMIUM_ECONOMY", premium_economy,
                                    _evidence_words(premium_economy, "estimate: economy fare x1.6")))
        # A fare the engine read for a party that did NOT fly in one cabin
        # (owner brief 2026-10-03, H7). It gets its own row: it can never be
        # the Business option or the Economy option, and require_evidence
        # means it is shown only when a real fare was read — there is no
        # benchmark for a mix of cabins.
        mixed = _best_option(resort, MIXED_CABIN, 1.0, arch,
                             enforce_budget=False, prefer_evidence=True,
                             require_evidence=True)
        if mixed is not None:
            mixed_row = _option_row("mixed_cabin", MIXED_CABIN, mixed,
                                    _evidence_words(mixed, "mixed cabins"))
            mixed_evidence = mixed.get("evidence")
            mixed_row["cabin_mix"] = str(
                getattr(mixed_evidence, "cabin_mix", "") or ""
            )
            rows.append(mixed_row)
        # Economy-with-stopover is offered in every season now, not just summer:
        # the fare itself is season-scoped (stopover_fares_for), so a July read
        # never surfaces on a December card and vice versa.
        stopover_season = "summer" if summer else "winter"
        # And it is offered only for THIS card's dates. A read is priced for one
        # pair; a card shows one pair. Quoting a fare read for a different pair
        # on this card would put a number next to dates it was never read for
        # (owner brief 2026-10-04, H4).
        card_pair = (str(cheapest.get("outbound", "")), str(cheapest.get("return", "")))
        if stopover_season and card_pair in priced_pairs_set:
            for hub, info in STOPOVER_HUBS.items():
                for fare in stopover_fares_for(hub, str(resort["airport"]).upper(),
                                               stopover_season, pair=card_pair):
                    pair = tuple(fare["pair"])
                    nights = nights_between(pair)
                    # The stopover arrives at the resort two days after leaving
                    # London, so this option's stay is the pair's nights less
                    # those two days (owner brief 2026-10-04, H4). The other
                    # options keep the full stay; only this one pays for a
                    # shorter holiday and two hotel nights in the hub.
                    resort_nights = max(nights - STOPOVER_FLIGHT_DAYS, 0)
                    hotel_cost = round(arch["suite_nightly_gbp"] * resort_nights, 2)
                    stop_nights = 2 * int(info["nights_each_way"])
                    stop_hotel = round(float(info["hotel"]["nightly_gbp"]) * stop_nights, 2)
                    uk_ground = UK_GROUND_RETURN_GBP.get(fare["origin"], 16.50)
                    transfer = float(resort.get("transfer_gbp", 30.0))
                    total_pkg = round(float(fare["total_gbp"]) + hotel_cost + stop_hotel, 2)
                    true_d2d = round(total_pkg + uk_ground + transfer, 2)
                    rows.append({
                        "kind": "stopover",
                        "cabin": "ECONOMY",
                        "hub": hub,
                        "hub_label": info["label"],
                        "hub_hotel": info["hotel"]["name"],
                        "hub_board": info["hotel"]["board"],
                        "legs": tuple(tuple(leg) for leg in fare["legs"]),
                        "carrier": fare["carrier"],
                        "outbound": pair[0],
                        "return": pair[1],
                        "nights": nights,
                        "resort_nights": resort_nights,
                        "hub_nights_each_way": int(info["nights_each_way"]),
                        "origin": fare["origin"],
                        "flight_cost": float(fare["total_gbp"]),
                        "hotel_cost": hotel_cost,
                        "stopover_hotel_cost": stop_hotel,
                        "stopover_nights": stop_nights,
                        "uk_ground": uk_ground,
                        "transfer": transfer,
                        "total_pkg": total_pkg,
                        "true_d2d": true_d2d,
                        "flight_basis": "multi-city fare read " + str(fare["observed_at"])[:10],
                        "source_url": fare["source_url"],
                        "hub_hotel_confidence": info["hotel"].get("confidence", ""),
                        "within_budget": _within(total_pkg, true_d2d),
                    })
                    # No Premium Economy multi-city fare has been read for any hub yet
                    # (_STOPOVER_READS is Economy-only) — estimated the same way the
                    # headline Business figure is when nothing was read: the read
                    # Economy stopover flight cost x1.6, hotel costs unchanged (a room
                    # rate does not move with cabin). Labelled "estimate" throughout,
                    # never presented as a fare that was actually read.
                    pe_flight_cost = round(float(fare["total_gbp"]) * 1.6, 2)
                    pe_total_pkg = round(pe_flight_cost + hotel_cost + stop_hotel, 2)
                    pe_true_d2d = round(pe_total_pkg + uk_ground + transfer, 2)
                    try:
                        pe_source_url = stopover_search_url(
                            hub, str(resort["airport"]).upper(), pair[0], pair[1],
                            origin=fare["origin"], travellers=travellers,
                            cabin_class="PREMIUM_ECONOMY")
                    except Exception:
                        pe_source_url = ""
                    rows.append({
                        "kind": "stopover_premium_economy",
                        "cabin": "PREMIUM_ECONOMY",
                        "hub": hub,
                        "hub_label": info["label"],
                        "hub_hotel": info["hotel"]["name"],
                        "hub_board": info["hotel"]["board"],
                        "legs": tuple(tuple(leg) for leg in fare["legs"]),
                        "carrier": fare["carrier"],
                        "outbound": pair[0],
                        "return": pair[1],
                        "nights": nights,
                        "resort_nights": resort_nights,
                        "hub_nights_each_way": int(info["nights_each_way"]),
                        "origin": fare["origin"],
                        "flight_cost": pe_flight_cost,
                        "hotel_cost": hotel_cost,
                        "stopover_hotel_cost": stop_hotel,
                        "stopover_nights": stop_nights,
                        "uk_ground": uk_ground,
                        "transfer": transfer,
                        "total_pkg": pe_total_pkg,
                        "true_d2d": pe_true_d2d,
                        "flight_basis": "estimate: economy stopover fare x1.6",
                        "source_url": pe_source_url,
                        "hub_hotel_confidence": info["hotel"].get("confidence", ""),
                        "within_budget": _within(pe_total_pkg, pe_true_d2d),
                    })
        return tuple(rows)

    # The same catalogue and season card_lookup_keys uses, so the hunt contract
    # and the cards can never be built from two different resort lists.
    catalog = resort_catalog(config)
    summer = is_summer_trip(config)
    over_budget: list[dict[str, Any]] = []
    held_short_haul: dict[str, list[dict[str, Any]]] = {}

    def _over_row(resort, dest, cabin, cheapest, arch, flight_options) -> dict[str, Any]:
        evidence = cheapest["evidence"]
        return {
            "resort_name": resort["name"],
            "destination_key": dest.key,
            "destination_label": resort["destination_label"],
            "airport": resort["airport"],
            "cabin": cabin.upper(),
            "outbound": cheapest["outbound"],
            "return": cheapest["return"],
            "nights": cheapest["nights"],
            "origin": cheapest["origin"],
            "flight_cost": cheapest["flight_cost"],
            "hotel_cost": cheapest["hotel_cost"],
            "total_pkg": cheapest["total_pkg"],
            "true_d2d": cheapest["true_d2d"],
            "flight_confidence": (
                evidence.confidence
                if (cheapest["evidence_used"] and evidence is not None)
                else "benchmark"
            ),
            "hotel_confidence": resort.get("confidence", "market-supported"),
            "unit": arch["suite_type"],
            "board": resort.get("board", ""),
            "board_options": board_totals(resort, cheapest["nights"]),
            "flight_options": flight_options,
            "max_budget_gbp": float(max_budget_gbp),
        }
    for dest in config.destinations:
        resorts, dropped = filter_resorts(
            catalog.get(dest.key.lower(), []), is_summer=summer,
            island=dest.key.lower() in ISLAND_RULE_KEYS,
        )
        filtered_out.extend(dropped)
        dest_cabins = destination_cabins(config, dest)
        for cabin in dest_cabins:
            flight_mult = cabin_multipliers.get(cabin.upper(), 1.0)
            for resort in resorts:
                # A unit check that says the property cannot take this party in
                # one booking REMOVES it, with the engine's own words as the
                # reason (owner brief 2026-10-03, H4). Offering a resort we
                # watched refuse five adults in one room is worse than not
                # offering it: the reader only finds out after choosing it.
                refusal = _unit_check_refusal(
                    resort["name"], config,
                    travellers=config.travellers, hotel_evidence=hotel_evidence,
                )
                if refusal:
                    filtered_out.append((resort["name"], refusal))
                    continue
                if refusal:
                    filtered_out.append((resort["name"], refusal))
                    continue
                airport = resort["airport"]
                # ONE family unit pricing (strict mandate) with suite premium.
                arch = _suite_for(resort)
                # NO PRICE, NO CARD — and say so. This entry carries a unit
                # and public facts but no rate, so it makes no card until the
                # engine reads one. It is announced here rather than silently
                # absent: a resort the reader expected and did not see is
                # worse than one we explain.
                if not arch.get("suite_nightly_gbp") and not any(
                    hotel_rate_for(hotel_evidence, resort["name"], outbound, returning)
                    for outbound, returning in priceable_date_pairs(config)
                ):
                    filtered_out.append((
                        resort["name"],
                        "no rate read for these dates yet; the card appears "
                        "once one is read.",
                    ))
                    continue
                # LONG HAUL (Business, over 8 hours): three options side by
                # side, each a whole-party total, and the budget tested against
                # each one separately (owner, 2026-09-30). The resort is a card
                # when ANY option fits; Business stays its headline. Only when
                # no option fits is it listed over budget, with every option
                # shown. Short haul keeps its old single-option gate.
                long_haul = cabin.upper() == "BUSINESS"
                flight_options: tuple[dict[str, Any], ...] = ()
                if long_haul:
                    cheapest = _best_option(
                        resort, cabin, flight_mult, arch,
                        enforce_budget=False, prefer_evidence=True,
                    )
                    flight_options = _flight_options(resort, arch, cheapest) if cheapest else ()
                    option = (
                        cheapest
                        if any(row["within_budget"] for row in flight_options)
                        else None
                    )
                    if option is None and cheapest is not None:
                        over_budget.append(
                            _over_row(resort, dest, cabin, cheapest, arch, flight_options)
                        )
                else:
                    # Short haul: the same evidence-first choice the long-haul
                    # card makes (owner brief 2026-10-04, H5). The candidate set
                    # is already inside the budget by the time it is ranked, so
                    # preferring a real price here moves WHICH PAIR the card
                    # shows and can never add or drop a resort.
                    option = _best_option(
                        resort, cabin, flight_mult, arch, prefer_evidence=True
                    )
                    if option is None:
                        # Held back: listed only if the WHOLE destination ends
                        # with no card (Doha and Muscat at a short-haul budget),
                        # so a destination the owner asked for never vanishes.
                        cheapest = _best_option(resort, cabin, flight_mult, arch, enforce_budget=False)
                        if cheapest is not None:
                            held_short_haul.setdefault(dest.key, []).append(
                                _over_row(resort, dest, cabin, cheapest, arch, ())
                            )
                if option is not None:
                    target_outbound = option["outbound"]
                    target_return = option["return"]
                    nights = option["nights"]
                    uk_ground = option["uk_ground"]
                    transfer = option["transfer"]
                    flight_cost = option["flight_cost"]
                    hotel_cost = option["hotel_cost"]
                    total_pkg = option["total_pkg"]
                    true_d2d = option["true_d2d"]
                    peak_hotel = option["peak_hotel"]
                    departure_origin = option["origin"]
                    evidence = option["evidence"]
                    evidence_used = option["evidence_used"]
                    hotel_rate = option.get("hotel_rate")
                    price_pp = round(total_pkg / travellers, 2)
                    # REAL discount baseline: the SAME suite, same nights/party,
                    # at the resort's summer peak (Jul/Aug school-holiday highs),
                    # in the SAME cabin so a Business December total is compared
                    # against a Business peak total — never an Economy peak.
                    peak_flight = round(resort["peak_summer_flight_5pax_gbp"] * flight_mult, 2)
                    peak_total = round(peak_flight + peak_hotel, 2)
                    # Luxury cabin displays a carrier that actually sells that cabin.
                    # Never present SunExpress/Ryanair/easyJet/Jet2 as "Business".
                    display_airline = cabin_carrier(
                        airport=airport, cabin=cabin, economy_carrier=resort["airline"]
                    )
                    # Live evidence must be a WHOLE-PARTY, exact-date amount to be
                    # used at all. A per-person figure is never multiplied up into
                    # a party total: deriving one and stamping it verified was the
                    # bug this guard exists to make unrepeatable. The lookup is
                    # CABIN-aware: an Economy fare must never price (or verify) a
                    # Business card — the cards' multipliers exist precisely
                    # because the cabins cost different amounts. Two questions,
                    # deliberately not one: ``evidence_used`` may price the card,
                    # ``evidence.promotable`` decides the label, so an aged
                    # observation prices it as ``stale-cache`` instead of being
                    # discarded back to a benchmark.
                    if evidence_used and evidence is not None:
                        if evidence.carrier:
                            display_airline = evidence.carrier
                    flight_basis = (
                        evidence.basis
                        if (evidence_used and evidence is not None)
                        else ("benchmark_supplied" if cabin.upper() == "ECONOMY" else f"benchmark_supplied_{cabin.lower()}")
                    )
                    flight_link = build_google_flights_roundtrip_url(
                        origin=departure_origin,
                        destination=airport,
                        outbound_date=target_outbound,
                        return_date=target_return,
                        travellers=travellers,
                        cabin_class=cabin,
                    )
                    deals.append(
                        PackageDeal(
                            resort_name=resort["name"],
                            destination_label=resort["destination_label"],
                            destination_key=dest.key,
                            star_rating=resort["stars"],
                            board_basis=_board_for_card(resort, hotel_rate),
                            outbound_date=target_outbound,
                            return_date=target_return,
                            nights=nights,
                            airline=display_airline,
                            origin_airports=config.origins,
                            origin=departure_origin,
                            routing=str(resort.get("routing", "")),
                            destination_airport=airport,
                            flight_price_total_gbp=flight_cost,
                            flight_price_basis=flight_basis,
                            cabin_class=cabin,
                            hotel_price_total_gbp=hotel_cost,
                            total_package_price_gbp=total_pkg,
                            price_per_person_gbp=price_pp,
                            flight_booking_url=flight_link,
                            hotel_booking_url=resort["hotel_url"],
                            is_under_budget=_within(total_pkg, true_d2d),
                            flight_options=flight_options,
                            board_options=board_totals(resort, nights),
                            monsoon_months=tuple(resort.get("monsoon_months", ()) or ()),
                            # Booking terms: carried from the resort data only
                            # when it is actually there. A key that is absent
                            # stays None, which the card prints as "not
                            # verified" rather than filling in.
                            free_cancellation_until=(
                                hotel_rate.cheapest.cancellation
                                if hotel_rate is not None and hotel_rate.cheapest.cancellation
                                else resort.get("free_cancellation_until") or None
                            ),
                            deposit_payment=(
                                hotel_rate.cheapest.payment
                                if hotel_rate is not None and hotel_rate.cheapest.payment
                                else resort.get("deposit_payment") or None
                            ),
                            checked_baggage=resort.get("checked_baggage") or None,
                            atol_protected=resort.get("atol_protected"),
                            beach_access=resort.get("beach_access") or (
                                "walkable beach" if arch.get("beach_walkable") is True
                                else ("no walkable beach" if arch.get("beach_walkable") is False
                                      else None)
                            ),
                            pool=resort.get("pool") or None,
                            highlights=_highlights_with_blocked_sources(
                                resort["highlights"],
                                supplemental_for(resort["name"], "blocked"),
                            ),
                            hotel_ratings=supplemental_for(resort["name"], "ratings"),
                            hotel_facts=supplemental_for(resort["name"], "facts"),
                            hotel_unit_note=_unit_check_note(
                                resort["name"], config,
                                travellers=travellers, hotel_evidence=hotel_evidence,
                            ),
                            booking_shape_seen=(
                                hotel_rate.cheapest.booking_shape
                                if hotel_rate is not None else ""
                            ),
                            unit_space_note=_space_flag(arch["suite_type"], travellers),
                            uk_ground_gbp=uk_ground,
                            transfer_gbp=transfer,
                            true_d2d_gbp=true_d2d,
                            dec_ambient_c=resort.get("dec_ambient_c", (0, 0)),
                            sea_temp_c=resort.get("sea_temp_c", 0),
                            beach=resort.get("beach", ""),
                            # The label carries the age: "verified-exact-date"
                            # when fresh, "stale-cache" when aged. Never a bare
                            # "verified-exact-date" on an observation too old to
                            # be one.
                            # A Business card with no live fare is priced from the
                            # economy benchmark x2.5: that total is an estimate,
                            # whatever the provenance of the room rate beside it.
                            confidence=(
                                evidence.confidence
                                if (evidence_used and evidence is not None)
                                else (
                                    "estimate"
                                    if cabin.upper() != "ECONOMY"
                                    else resort.get("confidence", "market-supported")
                                )
                            ),
                            # The hotel rate's own basis, kept apart from the
                            # flight basis above (F4, 2026-10-03).
                            hotel_rate_basis=(
                                "exact-date-rate"
                                if hotel_rate is not None
                                else str(resort.get("confidence", "market-supported"))
                            ),
                            hotel_evidence=hotel_rate,
                            # An aged fare shows its source and observed date too:
                            # the auditability mandate applies to a "this was
                            # observed on <date>" claim as much as to a live one.
                            source_url=(
                                evidence.source_url
                                if (evidence_used and evidence is not None)
                                else resort.get("hotel_url", "")
                            ),
                            live_carrier=(
                                evidence.carrier
                                if (evidence_used and evidence is not None)
                                else ""
                            ),
                            live_observed_at=(
                                evidence.observed_at
                                if (evidence_used and evidence is not None)
                                else ""
                            ),
                            peak_summer_total_gbp=peak_total,
                            unit_architecture=arch["suite_type"],
                            rooms_in_unit=_unit_rooms(arch),
                            **_criteria_fields(
                                resort["name"],
                                price_pp,
                                facts=supplemental_for(resort["name"], "facts"),
                                dec_avg_temp_c=_dec_temp_for_floor(
                                    target_outbound,
                                    float(resort.get("dec_ambient_c", (0, 0))[0]),
                                ),
                            ),
                            # STRICT mode: links request ONE unit for 5 (family
                            # suite/interconnecting), never 3 separate rooms.
                            compare_url=build_google_hotels_property_url(
                                resort_name=resort["name"],
                                destination_key=dest.key,
                                departure_date=target_outbound,
                                return_date=target_return,
                                adults=travellers,
                                rooms=arch.get("rooms_in_unit", 1),
                            ),
                            booking_deep_url=build_booking_com_property_url(
                                resort_name=resort["name"],
                                destination_key=dest.key,
                                departure_date=target_outbound,
                                return_date=target_return,
                                adults=travellers,
                                rooms=arch.get("rooms_in_unit", 1),
                            ),
                            expedia_deep_url=build_expedia_property_url(
                                resort_name=resort["name"],
                                destination_key=dest.key,
                                departure_date=target_outbound,
                                return_date=target_return,
                                adults=travellers,
                                rooms=arch.get("rooms_in_unit", 1),
                            ),
                        )
                    )

    carded_keys = {deal.destination_key for deal in deals}
    for key, rows in held_short_haul.items():
        if key not in carded_keys:
            over_budget.extend(rows)
    deals.sort(key=lambda d: (weather_weighted_discount_pct(d), -d.value_score, d.total_package_price_gbp))
    # Stamp the value-score rank (1 = best) so history tracks movement in the
    # composite ranking, not just raw price wobble.
    for rank, deal in enumerate(sorted(deals, key=lambda d: -d.value_score), 1):
        object.__setattr__(deal, "rank_value", rank)
    # Attach the transparency list (filtered resorts + reasons) to the first
    # caller via module-level export for the renderer; the function returns
    # deals only (signature stability for tests/CLI), so stash on the tuple's
    # companion attribute pattern: a module global consumed by the renderer.
    global LAST_FILTERED_OUT, LAST_OVER_BUDGET
    LAST_FILTERED_OUT = tuple(filtered_out)
    LAST_OVER_BUDGET = tuple(
        sorted(over_budget, key=lambda row: (row["total_pkg"], row["resort_name"]))
    )
    return tuple(deals)


#: Resorts filtered out by the strict parameters in the last collect run,
#: with human-readable reasons (rendered in the email's transparency note).
LAST_FILTERED_OUT: tuple[tuple[str, str], ...] = ()

#: Long-haul (Business) resorts the last collect run priced but could not card
#: because their cheapest option breached the budget, cheapest first. Rendered
#: as the report's over-budget list so a priced-out destination is stated, not
#: silently absent.
LAST_OVER_BUDGET: tuple[dict[str, Any], ...] = ()


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


def weather_weighted_discount_pct(deal: PackageDeal) -> float:
    """Discount%% re-weighted for winter reality (2026-09-22 user mandate).

    At or above the 20°C December floor the raw vs-peak discount ranks
    as-is. Below the floor it is halved — a beach resort you cannot beach
    at must not ride a huge saving to the top of a winter-sun list. Red
    Sea, Canary and Middle East destinations (21–26°C) therefore float up
    over e.g. Antalya's ▼52%% at 15°C. Returned negated for ascending
    ``sorted`` use.
    """
    pct = float(deal.vs_peak_pct)
    floor_temp = _dec_temp_for_floor(deal.outbound_date, float(deal.dec_ambient_c[0]))
    if floor_temp is not None and floor_temp < WINTER_SUN_FLOOR_C:
        pct *= 0.5
    return -pct


def bucket_deals(
    deals: Sequence[PackageDeal],
    max_budget_gbp: float = 5000.0,
) -> dict[str, tuple[PackageDeal, ...]]:
    """Split deals into the reader decision lenses.

    discounts: REAL discount lens — biggest % below the same resort's
               summer-peak price first, WEATHER-WEIGHTED: below the 20°C
               December floor the discount is halved (a huge saving on a
               beach you cannot use is not a winter-sun deal); ties break on
               the winter-first value score, then cheapest absolute total.
    luxury:    5-star only, most luxurious first, cheaper wins ties.
    winter:    warmest ambient air first, then warmest sea (genuine winter
               sun floats up; heated-pool-only cold spots sink honestly).
    value:     highest recovered-tracker value score first (price 30%,
               winter 25%, luxury/food 15% each, mosque 10%, activities 5%,
               flight-quality penalty) — the composite "was this winter
               worth it" lens.
    """
    ordered = tuple(deals)
    return {
        "discounts": tuple(
            sorted(ordered, key=lambda d: (weather_weighted_discount_pct(d), -d.value_score, d.total_package_price_gbp))),
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
        "value": tuple(
            sorted(ordered, key=lambda d: (-d.value_score, d.total_package_price_gbp))),
    }


# SUSPENDED (2026-09-22 user mandate): destination photos read as "fake"
# next to named resorts — a Commons AREA photo cannot represent a specific
# hotel, and mapping images to hotel IDs is unsolved. Cards are TEXT-ONLY
# until a per-hotel image source exists. Data kept for that future fix; the
# renderer must not emit <img> tags (locked by test).
# a wrong photo in the email.
DEST_IMAGES: dict[str, str] = {
    "antalya": "https://thumb.wikimedia.org/wikipedia/commons/thumb/4/48/Konyaalt%C4%B1_Beach%2C_Antalya%2C_Turkey%2C_March_2022_-_Cafe.jpg/960px-Konyaalt%C4%B1_Beach%2C_Antalya%2C_Turkey%2C_March_2022_-_Cafe.jpg",
    "malta": "https://thumb.wikimedia.org/wikipedia/commons/thumb/9/9d/Valletta%2C_Malta%27s_Grand_Harbor.jpg/960px-Valletta%2C_Malta%27s_Grand_Harbor.jpg",
    "taghazout": "https://thumb.wikimedia.org/wikipedia/commons/thumb/4/42/Camel_on_the_beach_at_Taghazout_%288591453987%29.jpg/960px-Camel_on_the_beach_at_Taghazout_%288591453987%29.jpg",
    "hurghada": "https://thumb.wikimedia.org/wikipedia/commons/thumb/a/af/Hurghada%2C_Qesm_Hurghada%2C_Red_Sea_Governorate%2C_Egypt_-_panoramio_%28306%29.jpg/960px-Hurghada%2C_Qesm_Hurghada%2C_Red_Sea_Governorate%2C_Egypt_-_panoramio_%28306%29.jpg",
    "cairo": "https://thumb.wikimedia.org/wikipedia/commons/thumb/d/d6/All_pyramids_of_Giza_panorama_2.jpg/960px-All_pyramids_of_Giza_panorama_2.jpg",
    "muscat": "https://thumb.wikimedia.org/wikipedia/commons/thumb/2/2b/Palacio_de_Al_Alam%2C_Mascate%2C_Om%C3%A1n%2C_2024-08-14%2C_DD_36.jpg/960px-Palacio_de_Al_Alam%2C_Mascate%2C_Om%C3%A1n%2C_2024-08-14%2C_DD_36.jpg",
    "doha": "https://thumb.wikimedia.org/wikipedia/commons/thumb/f/f3/Doha_West_Bay_Skyline_Qatar_Jan_2020.jpg/960px-Doha_West_Bay_Skyline_Qatar_Jan_2020.jpg",
    "tenerife": "https://thumb.wikimedia.org/wikipedia/commons/thumb/4/44/Playa-Las-Vistas-Tenerife-03.jpg/960px-Playa-Las-Vistas-Tenerife-03.jpg",
    "madeira": "https://thumb.wikimedia.org/wikipedia/commons/thumb/6/65/S%C3%A3o_Martinho_%28Madeira%2C_Portugal%29%2C_Pestana_Ocean_Bay_--_2025_--_0259.jpg/960px-S%C3%A3o_Martinho_%28Madeira%2C_Portugal%29%2C_Pestana_Ocean_Bay_--_2025_--_0259.jpg",
    "lanzarote": "https://thumb.wikimedia.org/wikipedia/commons/thumb/a/a9/Beach_in_Playa_Blanca_-_Lanzarote_-B20.jpg/960px-Beach_in_Playa_Blanca_-_Lanzarote_-B20.jpg",
    "cape_verde": "https://thumb.wikimedia.org/wikipedia/commons/thumb/4/48/Sal_Sta_Maria_beach_hotel.jpg/960px-Sal_Sta_Maria_beach_hotel.jpg",
    "fuerteventura": "https://thumb.wikimedia.org/wikipedia/commons/thumb/2/22/Flickr_-_ronsaunders47_-_CALETA_DE_FUSTE_._FUERTEVENTURA._THE_BOARDWALK...jpg/960px-Flickr_-_ronsaunders47_-_CALETA_DE_FUSTE_._FUERTEVENTURA._THE_BOARDWALK...jpg",
    "gran_canaria": "https://thumb.wikimedia.org/wikipedia/commons/thumb/5/5e/Aerial_view_of_Maspalomas_in_Gran_Canaria_with_its_dunes_and_beach_%2852757100017%29.jpg/960px-Aerial_view_of_Maspalomas_in_Gran_Canaria_with_its_dunes_and_beach_%2852757100017%29.jpg",
    "paphos": "https://thumb.wikimedia.org/wikipedia/commons/thumb/3/38/Paphos_Castle_and_Paphos_Marina%2C_Paphos%2C_Cyprus.jpg/960px-Paphos_Castle_and_Paphos_Marina%2C_Paphos%2C_Cyprus.jpg",
    # December long-haul additions (Commons, resolved 2026-09-30; not rendered).
    "zanzibar": "https://thumb.wikimedia.org/wikipedia/commons/thumb/0/04/White_sandy_beach_at_Nungwi%2C_Zanzibar.jpg/960px-White_sandy_beach_at_Nungwi%2C_Zanzibar.jpg",
    "mauritius": "https://thumb.wikimedia.org/wikipedia/commons/thumb/6/6c/Flic_en_Flac_beach_.jpg/960px-Flic_en_Flac_beach_.jpg",
    "riviera_maya": "https://thumb.wikimedia.org/wikipedia/commons/thumb/7/73/Cancun-beach-Mexico-2016-Luka-Peternel.jpg/960px-Cancun-beach-Mexico-2016-Luka-Peternel.jpg",
}


def peak_discount_badge(deal) -> str:
    """The discount chip, with honest wording for a benchmark comparison.

    The 2026-09-24 July report badged a card that was DEARER than its own summer peak
    with a green "▼-5% vs summer peak · save £-243", two cells away from the
    "summer peak £5,260" that contradicted it. ``vs_peak_saving_gbp`` is negative when the
    card is above its peak, so a chip that reads as a saving must be conditioned on the
    sign: when there is no discount it says so, in the same place, at the same size.

    "Save" is additionally reserved for an OBSERVED earlier price
    (``peak_observed``): a difference against our own benchmark estimate is
    stated as "below our benchmark estimate (not a saving)", in neutral grey,
    never as money the reader has saved (owner rule, 2026-10-02).
    """
    saving = float(deal.vs_peak_saving_gbp or 0.0)
    pct = float(deal.vs_peak_pct or 0.0)
    style = "padding:3px 10px; border-radius:9999px; font-size:13px;"
    observed = bool(getattr(deal, "peak_observed", False))
    if saving > 0 and pct > 0:
        if observed:
            return ('<span style="background:#16a34a; color:#ffffff; ' + style
                    + ' font-weight:800;">▼' + f"{pct:g}" + '% vs summer peak · save £'
                    + f'{saving:,.0f}' + '</span>')
        return ('<span style="background:#f1f5f9; color:#475569; ' + style
                + ' font-weight:700;">▼' + f"{pct:g}" + '% — £' + f'{saving:,.0f}'
                + ' below our benchmark estimate (not a saving)</span>')
    label = "at its summer peak — no discount" if abs(saving) < 0.5 else (
        "no summer-peak discount — £" + f'{abs(saving):,.0f}' + " above it"
    )
    return ('<span style="background:#f1f5f9; color:#475569; ' + style
            + ' font-weight:700;">' + escape(label) + '</span>')


def _atol_line(links: Sequence[Any]) -> str:
    """The ATOL statement for the operator links a card actually carries.

    Only operators in the CAA's own register (``ATOL_REGISTER_BY_VENDOR``) are
    named, each with its ATOL number so the claim is checkable at the source.
    An operator the register does not list under its own name is never given
    the claim (owner brief 2026-10-03, F2).
    """
    named = []
    for link in links:
        atol = ATOL_REGISTER_BY_VENDOR.get(link.vendor)
        if atol:
            named.append(escape(link.vendor) + ' (ATOL ' + escape(atol) + ')')
    if not named:
        return ""
    return (
        '<div style="margin:2px 0 0 0; color:#166534; font-size:12px;">'
        '🛡️ ATOL-protected package available via ' + ' · '.join(named)
        + '.</div>'
    )


def render_vendor_block(deal: PackageDeal, *, adults: int, rooms: Sequence[int]) -> str:
    """One link per PACKAGE OPERATOR for this hotel card, each tagged with what
    its URL actually carries.

    The owner's complaint: the card's prominent buttons were Booking.com
    searches, so a package-holiday report could not be used to buy a package.
    Every link here goes to an operator that sells the flight and the room as
    one purchase, and every one is tagged deep link / prefilled / destination
    page — claiming a deep link a vendor does not support is how a link starts
    implying a price. Kept to one line because Gmail clips a long e-mail, and a
    clipped card helps nobody.
    """
    trip = trip_from_deal(deal, adults=adults, rooms=tuple(rooms))
    links = list(build_vendor_links(trip))
    # Long-haul cards also link the six ATOL package operators (owner brief
    # 2026-10-03, F1): an ATOL-protected package can beat a self-built trip
    # and protects the money. Short haul keeps the operators it has.
    if deal.flight_options:
        links.extend(build_atol_operator_links(trip))
    if not links:
        return ""
    tags = {
        VENDOR_DEEP_LINK: "deep link",
        VENDOR_PREFILLED_SEARCH: "prefilled",
        VENDOR_DESTINATION_PAGE: "dest. page",
        VENDOR_SEARCH_PAGE: "search page",
    }
    parts = [
        '<div style="margin:6px 0;font-size:13px;color:#475569;">'
        '<strong style="color:#0f172a;">Package operators</strong> '
        '<span style="font-size:11px;color:#94a3b8;">' + str(adults) + ' travellers · '
        + escape(deal.outbound_date) + '→' + escape(deal.return_date) + ' · '
        + escape(','.join(deal.origin_airports)) + '</span><br>'
    ]
    # The package route's protection, stated where the operator links are and
    # only for operators the CAA register lists (F2).
    parts.append(_atol_line(links))
    for i, link in enumerate(links):
        if i:
            parts.append('<span style="color:#cbd5e1;"> · </span>')
        parts.append(
            '<a href="' + escape(link.url, quote=True)
            + '" style="color:#2563eb;text-decoration:none;font-weight:600;">'
            + escape(link.vendor) + ' ↗</a> <span style="font-size:11px;color:#94a3b8;">'
            + escape(tags.get(link.kind, link.kind)) + '</span>'
        )
    parts.append(
        '<div style="font-size:11px;color:#b45309;">' + escape(price_label_line(links))
        + '</div></div>'
    )
    return ''.join(parts)


def render_diy_block(deal: PackageDeal, *, adults: int) -> str:
    """The same week bought as separate parts, priced from those parts.

    D2D arithmetic: the total is summed from the components on every render, so
    a live fare replacing a benchmark moves it. No vendor package quote has been
    observed for this card, so the comparison declares no winner and says so,
    rather than comparing the report's own benchmark against itself and calling
    the difference a saving.
    """
    option = build_diy_option(
        flight_total_gbp=deal.flight_price_total_gbp,
        flight_carrier=deal.live_carrier or deal.airline,
        flight_url=deal.flight_booking_url,
        destination_airport=deal.destination_airport,
        outbound_date=deal.outbound_date,
        return_date=deal.return_date,
        adults=adults,
        hotel_total_gbp=deal.hotel_price_total_gbp,
        hotel_name=deal.resort_name,
        hotel_url=deal.hotel_booking_url,
        nights=deal.nights,
        uk_ground_gbp=deal.uk_ground_gbp,
        transfer_gbp=deal.transfer_gbp,
        cabin_class=deal.cabin_class,
        flight_confidence=deal.confidence,
        flight_source_url=deal.source_url,
        flight_observed_at=deal.live_observed_at,
        airline_booking_url=airline_booking_page(deal.live_carrier or deal.airline),
    )
    comparison = DiyComparison(
        diy_total_gbp=option.total_gbp,
        package_total_gbp=None,
        package_confidence=deal.confidence,
    )
    flight, hotel = option.components[0], option.components[1]
    carrier = escape((deal.live_carrier or deal.airline).split('/')[0].strip())
    link = 'style="color:#2563eb;text-decoration:none;"'
    parts = [
        '<div style="margin:6px 0;font-size:13px;color:#475569;">'
        '<strong style="color:#0f172a;">Self-create</strong> '
        '<span style="font-size:11px;color:#94a3b8;">'
        + escape(trajectory_label(destination_airport=deal.destination_airport,
                                  carrier=deal.live_carrier or deal.airline))
        + '</span><br>£' + f'{flight.amount_gbp:,.0f}' + ' flights, ' + carrier + ' '
    ]
    if flight.url:
        parts.append('<a href="' + escape(flight.url, quote=True) + '" ' + link + '>'
                     + escape(flight.channel) + ' ↗</a>')
    if flight.dated_search_url:
        parts.append(' <a href="' + escape(flight.dated_search_url, quote=True)
                     + '" style="color:#64748b;text-decoration:none;font-size:11px;">dated search ↗</a>')
    parts.append('<span style="color:#cbd5e1;"> · </span>£' + f'{hotel.amount_gbp:,.0f}'
                 + ' room, ' + str(deal.nights) + 'n ')
    if hotel.url:
        parts.append('<a href="' + escape(hotel.url, quote=True) + '" ' + link + '>'
                     + escape(hotel.channel) + ' ↗</a>')
    for extra in option.components[2:]:
        parts.append('<span style="color:#cbd5e1;"> · </span>£' + f'{extra.amount_gbp:,.0f}'
                     + ' ' + escape(extra.label.split(',')[0].lower()))
    parts.append('<br><strong style="color:#0f172a;">= £' + f'{option.total_gbp:,.0f}'
                 + ' door-to-door</strong> <span style="font-size:11px;color:#94a3b8;">'
                 + escape(option.confidence) + '</span>'
                 + '<div style="font-size:11px;color:#b45309;">' + escape(comparison.statement)
                 + '</div></div>')
    return ''.join(parts)


def _hours_text(hours: Optional[float]) -> str:
    if hours is None:
        return "?"
    whole = int(hours)
    minutes = int(round((hours - whole) * 60))
    if minutes == 60:
        whole, minutes = whole + 1, 0
    return f"{whole}h{minutes:02d}"


#: Cabin names for the shared budget line, so a watch card and a resort card
#: name the same cabin the same way.
_BUDGET_CABIN_LABELS = {
    "business": "Business",
    "premium_economy": "Premium Economy",
    "economy": "Economy",
}


def budget_headline(
    options: Sequence[tuple[str, float, bool]], budget: float
) -> str:
    """The budget line for a set of priced options: what FITS, then what does not.

    ``options`` is ``(cabin label, whole-party total, within budget)`` per
    option. The owner's rule tests the budget on EACH option, so a line that
    quotes only one cabin's gap hides the option the family can actually
    afford: a Bali watch row at a £12,000 budget read "£10,650 over the £12,000
    budget" — the Business figure — while Economy (£10,950) fits (owner rule
    2026-10-02). The cheapest option that fits therefore leads, and the
    cabins that do not fit follow with their own gaps. Empty when every option
    is within budget: there is nothing to reconcile.
    """
    priced = [
        (str(label), float(total), bool(within))
        for label, total, within in options
        if total is not None
    ]
    budget = float(budget or 0.0)
    if not priced or budget <= 0:
        return ""
    if all(within for _, _, within in priced):
        # Nothing breaches: the headline price is inside the budget and needs no
        # budget line, so no bytes are spent restating it.
        return ""
    fitting = [o for o in priced if o[2]]
    breaching = sorted(
        (o for o in priced if not o[2]), key=lambda o: o[1] - budget
    )
    gaps = ' · '.join(
        escape(label) + ' £' + f'{total - budget:,.0f}' + ' over'
        for label, total, _ in breaching
    )
    if fitting:
        label, total, _ = min(fitting, key=lambda o: o[1])
        head = ('<span style="color:#166534; font-weight:700;">fits the £'
                + f'{budget:,.0f}' + ' budget on ' + escape(label)
                + ' (about £' + f'{total:,.0f}' + ')</span>')
        return head + (' · <span style="color:#b45309;">' + gaps + '</span>' if gaps else '')
    # Nothing fits: every option is named, cheapest gap first, and the ceiling
    # is stated once so the number is never a bare gap.
    return ('<span style="color:#b45309;">' + gaps
            + ' — every option is over the £' + f'{budget:,.0f}' + ' budget</span>')


def far_east_watch_rows(config: HolidayConfig) -> list[dict[str, Any]]:
    """The Far East watch for this config, in config order (they lead it).

    One row per configured destination that has a ``FAR_EAST_WATCH`` entry.
    Priced from the watch benchmarks for the same target date pair the cards
    use; a destination listed outside its season carries no price.
    """
    shortlist = shortlist_date_pairs(config)
    if not shortlist:
        return []
    outbound, returning = shortlist[len(shortlist) // 2]
    nights = (
        datetime.strptime(returning, "%Y-%m-%d") - datetime.strptime(outbound, "%Y-%m-%d")
    ).days
    month = int(outbound[5:7])
    unit_rooms = 1 if len(config.rooms) >= 3 else len(config.rooms)
    rows: list[dict[str, Any]] = []
    for dest in config.destinations:
        watch = FAR_EAST_WATCH.get(dest.key.lower())
        if watch is None:
            continue
        cabin = destination_cabin(dest)
        in_season = month in watch["months"]
        # Same cabin ratios _flight_options uses (business = economy x2.5,
        # premium_economy = economy x1.6): the watch has only ONE read
        # benchmark (business_pp_gbp), so economy and premium economy are
        # derived from it, never a second invented benchmark.
        business_pp = float(watch["business_pp_gbp"])
        economy_pp = business_pp / 2.5
        premium_economy_pp = economy_pp * 1.6
        total = None
        economy_total = None
        premium_economy_total = None
        if in_season:
            suite = watch["suite_night_gbp"] * nights
            total = float(business_pp * config.travellers + suite)
            economy_total = float(economy_pp * config.travellers + suite)
            premium_economy_total = float(premium_economy_pp * config.travellers + suite)
        rows.append({
            "key": dest.key,
            "label": dest.label,
            "airport": HOLIDAY_AIRPORTS.get(dest.key.lower(), dest.airports[0]),
            "flight_hours": dest.flight_hours,
            "flight_hours_source": dest.flight_hours_source,
            "cabin": cabin,
            "routing": watch["routing"],
            "climate": watch["climate"],
            "in_season": in_season,
            "outbound": outbound,
            "return": returning,
            "nights": nights,
            "fare_pp_gbp": business_pp,
            "economy_pp_gbp": economy_pp,
            "premium_economy_pp_gbp": premium_economy_pp,
            "suite_night_gbp": float(watch["suite_night_gbp"]),
            "indicative_total_gbp": total,
            "economy_total_gbp": economy_total,
            "premium_economy_total_gbp": premium_economy_total,
            "over_budget_gbp": (
                round(total - config.max_budget_gbp, 2)
                if total is not None and total > config.max_budget_gbp
                else 0.0
            ),
            "price_basis": FAR_EAST_PRICE_LABEL,
            "flights_url": build_google_flights_holiday_url(
                destination=dest.key, origin_airports=config.origins,
                departure_date=outbound, return_date=returning,
                adults=config.travellers, cabin_class=cabin,
            ),
            "booking_url": build_booking_com_url(
                destination=dest.key, departure_date=outbound,
                return_date=returning, adults=config.travellers, rooms=unit_rooms,
            ),
            "hotels_url": build_google_hotels_url(
                destination=dest.key, departure_date=outbound,
                return_date=returning, adults=config.travellers, rooms=unit_rooms,
            ),
        })
    return rows


def render_far_east_watch(config: HolidayConfig) -> str:
    """Compact HTML block for the Far East watch; empty when none configured.

    A watch row is an UNVERIFIED benchmark, not a bookable deal, so one that sits
    far over the owner's budget earns no full card: at more than
    ``FAR_EAST_WATCH_COLLAPSE_RATIO`` over budget it collapses to one compact
    line (owner rule 2026-10-02) that still names the destination, the flight
    time, the benchmark total, the gap to budget and the links.
    """
    rows = far_east_watch_rows(config)
    if not rows:
        return ""
    link = "color:#2563eb;text-decoration:none;font-weight:600;"
    budget = float(getattr(config, "max_budget_gbp", 0.0) or 0.0)
    collapse_limit = budget * (1.0 + FAR_EAST_WATCH_COLLAPSE_RATIO)

    def _links(row: Mapping[str, Any]) -> str:
        return ('<a href="' + escape(row["flights_url"], quote=True) + '" style="' + link + '">Google Flights ('
                + escape(row["cabin"].title()) + ') ↗</a>'
                + ' · <a href="' + escape(row["booking_url"], quote=True) + '" style="' + link + '">Booking.com ↗</a>'
                + ' · <a href="' + escape(row["hotels_url"], quote=True) + '" style="' + link + '">Google Hotels ↗</a>')

    def _collapsed(row: Mapping[str, Any]) -> bool:
        # Judged on the CHEAPEST option, not Business. The owner's rule tests
        # the budget on EACH option, so a watch row that fits on Economy is not
        # out of reach: collapsing it on the Business benchmark hid two
        # destinations the family could actually afford (owner rule
        # 2026-10-02). It collapses only when EVERY cabin is over the limit.
        if not row.get("in_season"):
            return False
        candidates = [
            float(row[key])
            for key in ("indicative_total_gbp", "economy_total_gbp", "premium_economy_total_gbp")
            if row.get(key) is not None
        ]
        return bool(candidates) and min(candidates) > collapse_limit

    full = [row for row in rows if not _collapsed(row)]
    collapsed = [row for row in rows if _collapsed(row)]

    out = [
        '<h2 style="margin:6px 0 4px 0; color:#0f172a; font-size:22px; font-weight:800;">'
        '🌏 Far East first — long haul, Business (over 8 h from London)</h2>',
        '<p style="margin:0 0 8px 0; color:#475569; font-size:13px;">Every figure in this block is '
        '<strong>' + FAR_EAST_PRICE_LABEL + '</strong>: an estimate of a peak-season Business fare '
        'and a 5-star family-suite night, not an observed or quoted price. These destinations have no '
        'resort in the catalogue, so they are destination watches, not '
        'hotel cards. Cabin rule: Business only when the flight is over 8 hours, otherwise Economy.</p>',
    ]
    if full:
        out.append('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; '
                   'background:#ffffff; border:1px solid #e2e8f0; border-radius:8px; margin:0 0 18px 0;">')
        for row in full:
            out.append('<tr><td style="padding:9px 12px; border-bottom:1px solid #f1f5f9; font-size:13px; color:#475569;">')
            out.append('<strong style="color:#0f172a; font-size:14px;">' + escape(row["label"]) + '</strong><br>')
            out.append('✈ ' + escape(_hours_text(row["flight_hours"])) + ' · ' + escape(row["routing"])
                       + ' · <strong>' + escape(row["cabin"].title()) + '</strong> · ' + escape(row["climate"]))
            if row["in_season"] and row["indicative_total_gbp"] is not None:
                out.append('<br>≈ £' + f'{row["fare_pp_gbp"]:,.0f}' + 'pp Business + suite ≈ £'
                           + f'{row["suite_night_gbp"]:,.0f}' + '/night → <strong style="color:#0f172a;">≈ £'
                           + f'{row["indicative_total_gbp"]:,.0f}' + '</strong> for ' + str(config.travellers)
                           + ', ' + str(row["nights"]) + ' nights — <em>' + FAR_EAST_PRICE_LABEL + '</em>')
                # The budget line leads with the cheapest option that FITS and
                # only then names the cabins that do not (owner rule 2026-10-02):
                # quoting only the Business gap hid an affordable Economy trip.
                budget_line = budget_headline(
                    [
                        (_BUDGET_CABIN_LABELS["business"],
                         float(row["indicative_total_gbp"]),
                         float(row["indicative_total_gbp"]) <= budget),
                        (_BUDGET_CABIN_LABELS["premium_economy"],
                         float(row["premium_economy_total_gbp"]),
                         float(row["premium_economy_total_gbp"]) <= budget),
                        (_BUDGET_CABIN_LABELS["economy"],
                         float(row["economy_total_gbp"]),
                         float(row["economy_total_gbp"]) <= budget),
                    ],
                    budget,
                )
                if budget_line:
                    out.append(' · ' + budget_line)
                out.append('<br>&nbsp;&nbsp;also ≈ £' + f'{row["economy_total_gbp"]:,.0f}' + ' Economy · ≈ £'
                           + f'{row["premium_economy_total_gbp"]:,.0f}' + ' Premium Economy — same suite, same basis')
            else:
                out.append('<br><span style="color:#b45309;">Outside its season for these dates — no price shown.</span>')
            out.append('<br>' + _links(row))
            out.append('</td></tr>')
        out.append('</table>')
    if collapsed:
        out.append(
            '<p style="margin:0 0 6px 0; color:#475569; font-size:13px;">'
            '<strong style="color:#0f172a;">Too far over budget to show as a card</strong> — '
            'these benchmark-only watches are more than '
            + f'{FAR_EAST_WATCH_COLLAPSE_RATIO:.0%}'
            + ' over the £' + f'{budget:,.0f}' + ' budget, so they are one line each:</p>'
        )
        out.append('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; '
                   'background:#ffffff; border:1px solid #e2e8f0; border-radius:8px; margin:0 0 18px 0;">')
        for row in collapsed:
            # The gap quoted is against the CHEAPEST cabin, because that is
            # the figure that decided the collapse.
            cheapest = min(
                float(row[key])
                for key in ("indicative_total_gbp", "economy_total_gbp", "premium_economy_total_gbp")
                if row.get(key) is not None
            )
            gap = cheapest - budget
            out.append('<tr><td style="padding:7px 12px; border-bottom:1px solid #f1f5f9; font-size:13px; color:#475569;">'
                       '<strong style="color:#0f172a;">' + escape(row["label"]) + '</strong> · '
                       + escape(_hours_text(row["flight_hours"])) + ' · cheapest benchmark ≈ £'
                       + f'{cheapest:,.0f}' + ' for ' + str(config.travellers)
                       + ' <em>' + FAR_EAST_PRICE_LABEL + '</em>'
                       # The Economy / Premium Economy comparison stays even
                       # on a collapsed row: it is an owner direction
                       # (2026-09-30), and compaction must not drop it.
                       + ' · also ≈ £' + f'{row["economy_total_gbp"]:,.0f}' + ' Economy · ≈ £'
                       + f'{row["premium_economy_total_gbp"]:,.0f}' + ' Premium Economy'
                       + ' · gap to budget '
                       + '<span style="color:#b45309;">£' + f'{gap:,.0f}' + ' over the £'
                       + f'{budget:,.0f}' + ' budget</span> · ' + _links(row) + '</td></tr>')
        out.append('</table>')
    return ''.join(out)


#: Providers whose listing price is not the hotel's own rate. A reader who
#: assumes an aggregator's figure is the hotel's will meet a different price
#: on the hotel's site, so the card names the channel rather than implying it.
ONLINE_TRAVEL_AGENTS: frozenset[str] = frozenset(
    {
        "booking.com",
        "expedia",
        "expedia.co.uk",
        "agoda",
        "hotels.com",
        "tripadvisor",
        "trip.com",
        "ebookers",
        "lastminute.com",
        "tui.co.uk",
        "travelodge",
    }
)

#: Providers that ARE the hotel's own site.
DIRECT_PROVIDERS: frozenset[str] = frozenset(
    {"direct", "hotel website", "hotel", "the hotel", "official site",
     "brand site", "property website"}
)


def hotel_provider_line(rate: Any) -> str:
    """Whose rate this is, in words, or "" when the source named no provider."""
    provider = str(getattr(rate, "provider", "") or "").strip()
    if not provider:
        return ""
    normalised = provider.lower().strip()
    if normalised in ONLINE_TRAVEL_AGENTS:
        return f"via {provider}: an online travel agent listing, not the hotel"
    if normalised in DIRECT_PROVIDERS:
        return f"via {provider}: the hotel's own site"
    # An unrecognised provider is named and nothing more is claimed about it:
    # "aggregator" is an inference, and an inference on a price is the thing
    # this card exists to avoid.
    return f"via {provider}"


#: How each fact the engine reads is introduced on the card. Only the fields
#: the engine actually writes appear here; anything else was refused at load.
HOTEL_FACT_LABELS: dict[str, str] = {
    "nearest_mosque": "🕌 mosque",
    "kids_club": "🧒 kids club",
    "pools": "🏊 pools",
    "pools_kids_restaurants": "🏊 pools, kids club, restaurants",
    "restaurants": "🍽 restaurants",
    "restaurants_bars": "🍽 restaurants and bars",
    "beach": "🏖 beach",
    "breakfast": "🍳 breakfast",
    "breakfast_style": "🍳 breakfast",
    "board_offer": "🍽 board",
    "transfer_time": "🚐 transfer",
    "transfer_distance": "🚐 transfer",
}


def render_space_note_line(deal: Any) -> str:
    """The "bigger than the party needs" note, when the unit's name says so."""
    note = str(getattr(deal, "unit_space_note", "") or "").strip()
    if not note:
        return ""
    return (
        '<div style="margin:0 0 6px 0; color:#334155; font-size:13px;">'
        '<span style="color:#b45309;">Unit: ' + escape(note) + '</span></div>'
    )


def render_hotel_unit_note_line(deal: Any) -> str:
    """A one-room refusal the property then solved, in the engine's words.

    Rendered instead of removing the resort: the reader wants to know the
    villa does not take five in one room and that the hotel sells two rooms on
    one booking instead. Removing the card would hide both.
    """
    note = str(getattr(deal, "hotel_unit_note", "") or "").strip()
    if not note:
        return ""
    return (
        '<div style="margin:0 0 6px 0; color:#334155; font-size:13px;">'
        '<strong style="color:#0f172a;">One-booking check:</strong> '
        + escape(note) + '</div>'
    )


def render_hotel_facts_line(deal: Any) -> str:
    """Every fact read for this property, each with the source it came from.

    Only stated facts appear: a fact nobody read is not a fact, and inventing
    one is the failure this seam exists to prevent. Where two sources disagree
    — "four pools" from the brand site, "2 pools" from an OTA — both are shown
    and the disagreement is named. Picking a winner between two sources is a
    judgement the evidence cannot make, and silently picking one would make the
    card look certain about something it is not.
    """
    facts = tuple(getattr(deal, "hotel_facts", ()) or ())
    if not facts:
        return ""
    grouped: dict[str, list[Any]] = {}
    for fact in facts:
        grouped.setdefault(fact.field, []).append(fact)
    parts: list[str] = []
    for field_name, records in grouped.items():
        label = HOTEL_FACT_LABELS.get(field_name, field_name.replace("_", " "))
        texts = []
        for record in records:
            source = record.where or "read"
            text = f"{escape(record.stated)} <span style=\"color:#94a3b8;\">({escape(source)})</span>"
            if record.source_url:
                text += (' <a href="' + escape(record.source_url, quote=True)
                         + '" style="color:#2563eb;text-decoration:none;font-size:11px;">'
                         'source ↗</a>')
            texts.append(text)
        disputed = len({str(record.stated).strip().lower() for record in records}) > 1
        flag = (' <span style="color:#b45309;">sources disagree</span>'
                if disputed else "")
        parts.append(f"{escape(label)}: " + flag.join([""]) + '<span style="color:#cbd5e1;"> · </span>'.join(texts) + flag)
    return (
        '<div style="margin:0 0 6px 0; color:#334155; font-size:13px;">'
        '<strong style="color:#0f172a;">Facts read:</strong> '
        + '<span style="color:#cbd5e1;"> | </span>'.join(parts)
        + '</div>'
    )


def render_hotel_rating_line(deal: Any) -> str:
    """Every rating read for this property, each with its source and count.

    A bare "4.6" is a number with no denominator and no provenance, so the
    source and the review count travel with it. Two sources that disagree are
    both shown: picking a winner between a 4.6 on Google and a 4.4 on the
    brand's own page is a judgement the evidence cannot make.
    """
    ratings = tuple(getattr(deal, "hotel_ratings", ()) or ())
    if not ratings:
        return ""
    parts: list[str] = []
    for rating in ratings:
        scale = f"{rating.scale:g}" if rating.scale else "5"
        text = f"{escape(rating.source)} {rating.score:g}/{escape(scale)}"
        if rating.review_count:
            text += f" ({escape(rating.review_count)} reviews)"
        if rating.where:
            text += f" — {escape(rating.where)}"
        if rating.source_url:
            text += (' <a href="' + escape(rating.source_url, quote=True)
                     + '" style="color:#2563eb;text-decoration:none;font-size:11px;">source ↗</a>')
        parts.append(text)
    return (
        '<div style="margin:0 0 6px 0; color:#334155; font-size:13px;">'
        '<strong style="color:#0f172a;">Ratings read:</strong> '
        + '<span style="color:#cbd5e1;"> · </span>'.join(parts)
        + '</div>'
    )


def render_hotel_rate_line(deal: Any) -> str:
    """The stay's price, where it was read rather than estimated.

    Only rendered when a qualifying rate exists for this resort and these dates;
    without one the card looks exactly as it did before hotel evidence existed,
    because a catalogue estimate must not be dressed up as an observation.

    Both rates are shown when there are two — the flexible one with its
    cancellation date, then the non-refundable one — and the line states when
    the rate was read, from whom, and on what basis, because a converted
    figure that reads like a GBP price is the failure mode this whole seam
    exists to prevent (owner brief 2026-10-03, H3).
    """
    evidence = getattr(deal, "hotel_evidence", None)
    if evidence is None:
        return ""
    cheapest = evidence.cheapest
    rates = getattr(evidence, "rates", ()) or (cheapest,)
    refundable = next((rate for rate in rates if rate.refundable), None)
    non_refundable = next((rate for rate in rates if not rate.refundable), None)
    # Both are shown when both exist: the refundable rate is frequently the
    # CHEAPER one, so a card showing only the cheapest can hide the bookable
    # rate entirely.
    primary = refundable or non_refundable or cheapest
    secondary = non_refundable if (refundable and non_refundable is not primary) else None

    def _amount(rate: Any) -> str:
        # The hotel's own rate name is what a reader will search for on the
        # hotel's site, so it is preferred over our word for the category;
        # "Flexible" is only a fallback for a rate with no published name.
        head = str(rate.rate_name or "").strip()
        if not head:
            head = "Flexible" if rate.refundable else "Non-refundable"
        text = f"{head} £{rate.price_gbp:,.0f}"
        if rate.refundable and rate.cancellation:
            text += f" ({rate.cancellation})"
        elif not rate.refundable and not getattr(rate, "refundable_stated", False):
            # The page said nothing about cancellation. "Not stated" is the
            # only honest word: assuming either way would be deciding for the
            # reader what they can and cannot get back.
            text += " (cancellation not stated)"
        return escape(text)

    parts = [_amount(primary)]
    if secondary is not None:
        parts.append('<span style="color:#cbd5e1;"> · </span>')
        parts.append(_amount(secondary))
    detail = escape(hotel_rate_provenance(cheapest))
    provider_line = hotel_provider_line(cheapest)
    if provider_line:
        detail += ' · ' + escape(provider_line)
    unit_words = " · ".join(getattr(cheapest, "units", ()) or ())
    if unit_words:
        detail += ' · ' + escape(unit_words)
    link = ''
    if cheapest.source_url:
        link = (' <a href="' + escape(cheapest.source_url, quote=True)
                + '" style="color:#2563eb;text-decoration:none;font-size:11px;">'
                'rate ↗</a>')
    return (
        '<div style="margin:0 0 6px 0; color:#334155; font-size:13px;">'
        '<strong style="color:#0f172a;">Hotel rate for these dates:</strong> '
        + ''.join(parts) + link
        + '<div style="font-size:11px; color:#64748b;">' + detail
        + ' · ' + escape(cheapest.check_in) + '→' + escape(cheapest.check_out)
        + ' · ' + escape(cheapest.price_label) + '</div></div>'
    )


def render_board_line(deal_or_row: Any) -> str:
    """The board basis, stated on every hotel line; each island basis priced."""
    board = getattr(deal_or_row, "board_basis", None)
    options = getattr(deal_or_row, "board_options", None)
    nights = getattr(deal_or_row, "nights", None)
    if isinstance(deal_or_row, Mapping):
        board = deal_or_row.get("board", "")
        options = deal_or_row.get("board_options", ())
        nights = deal_or_row.get("nights")
    label = BOARD_LABELS.get(board_code(board), str(board))
    text = '<strong style="color:#0f172a;">Board:</strong> ' + escape(label)
    if options:
        text += (' · every basis the hotel sells, hotel only, ' + str(nights) + ' nights for the party: '
                 + ' · '.join(escape(o["label"]) + ' £' + f'{float(o["hotel_cost"]):,.0f}' for o in options))
    return '<div style="margin:0 0 6px 0; color:#334155; font-size:13px;">' + text + '</div>'


#: The booking terms a card may show, in order, each mapped to its field on
#: PackageDeal. ``atol`` is handled separately because it is a tri-state fact.
_BOOKING_TERM_LABELS: tuple[tuple[str, str], ...] = (
    ("free_cancellation_until", "cancellation"),
    ("deposit_payment", "deposit"),
    ("checked_baggage", "baggage"),
    ("beach_access", "beach"),
    ("pool", "pool"),
)


def _booking_term_values(deal: Any) -> tuple[list[str], list[str]]:
    """(verified statements, unknown labels) for one deal's booking terms.

    Only a value that is actually present is stated; everything else is named
    as unknown. A field is never inferred from another one.
    """
    verified: list[str] = []
    unknown: list[str] = []
    for field, label in _BOOKING_TERM_LABELS:
        value = getattr(deal, field, None)
        if value is None or value == "":
            unknown.append(label)
        else:
            verified.append(str(value))
    atol = getattr(deal, "atol_protected", None)
    if atol is None:
        # NOT an unknown. The self-build route's position is stated below as
        # a verified fact, and listing "ATOL" as not verified on the same line
        # said and unsaid the same thing in one breath. The package route's
        # position is not a card-level fact at all: it depends which operator
        # the reader books, and the ATOL line on the operator links names the
        # register number for each one that holds a licence.
        pass
    elif atol:
        verified.append("ATOL protected")
    else:
        verified.append("not ATOL protected")
    # The self-build route the card prices — flights bought separately from
    # the room — is never ATOL-protected. ATOL protects a package bought as
    # one purchase from an operator, so this is a fact about the booking
    # route, not an unknown (owner brief 2026-10-03, F2).
    verified.append("self-build: not ATOL-protected")
    # The transfer is ground transport the code already prices, so it is a known
    # value (a modelled estimate, labelled as one) — never an unknown. The
    # per-option lines state the time; here we carry the priced amount.
    transfer = getattr(deal, "transfer_gbp", 0.0)
    try:
        transfer = float(transfer)
    except (TypeError, ValueError):
        transfer = 0.0
    if transfer > 0:
        verified.append("resort transfer £" + f"{transfer:,.0f} (estimate)")
    else:
        unknown.append("transfer")
    # The same single unknown list carries what was never assessed, so a card
    # has one "not verified" line rather than several separate caveats
    # (owner rule 2026-10-02).
    if not getattr(deal, "mosque_name", ""):
        unknown.append("mosque access")
    if getattr(deal, "resort_name", "") not in RESORT_CRITERIA:
        unknown.append("criteria scores")
    # A value score built from default inputs is not a measurement, so it is
    # named as unknown rather than printed as a number (owner rule 2026-10-02).
    if not getattr(deal, "value_score_verified", False):
        unknown.append("value score")
    return verified, unknown


def render_booking_terms(deal_or_row: Any) -> str:
    """A compact, honest booking-terms line: verified facts, then the unknowns.

    A value is shown only when the data carries it; anything not verified is
    named once as "not verified: …" so the reader knows what to check before
    booking rather than being told a figure the report never had.
    """
    verified, unknown = _booking_term_values(deal_or_row)
    parts = []
    if verified:
        parts.append(' · '.join(escape(text) for text in verified))
    if unknown:
        parts.append('<span style="color:#b45309;">not verified: '
                     + escape(', '.join(unknown)) + '</span>')
    body = ' · '.join(parts) if parts else 'nothing verified'
    return ('<div style="margin:0 0 6px 0; color:#334155; font-size:13px;">'
            '<strong style="color:#0f172a;">Booking terms:</strong> ' + body + '</div>')


def hotel_rate_age_words(deal: Any, *, generated_at: str) -> str:
    """The hotel leg of the age footer: an age when read, a basis otherwise.

    A rate read by the private engine carries the instant it was observed, so
    it gets the same words the flight leg uses plus the vendor it came from.
    A rate with no readable observation says so rather than borrowing the
    card's flight date, and a catalogue rate keeps stating its basis — an age
    it never had.
    """
    evidence = getattr(deal, "hotel_evidence", None)
    rate = getattr(evidence, "cheapest", None) if evidence is not None else None
    if rate is not None:
        observed_at = str(getattr(rate, "observed_at", "") or "")
        vendor = str(getattr(rate, "vendor", "") or "").strip()
        age = relative_age_label(observation_age_hours(observed_at, generated_at))
        if age:
            suffix = f", {vendor}" if vendor else ""
            return f"hotel rate read {age}{suffix}"
        return "hotel rate date unknown"
    basis = str(getattr(deal, "hotel_rate_basis", "") or "market-supported")
    if basis == "estimate":
        return "hotel rate from nearest dates, not your exact dates"
    return "hotel rate read for these dates"


def prices_checked_footer(deal: Any, *, generated_at: str) -> str:
    """The card's last line: how old each half of its numbers is.

    Flights carry their age from the observed-at field the fare was read with
    (``live_observed_at``); a benchmark that was never observed says so rather
    than wearing an age. The hotel rate states its age the same way once a
    rate was actually read for these dates (owner brief 2026-10-03, F2b) —
    previously the hotel half had no observed-at field anywhere in the data and
    could only state a basis, which is what it still does for a catalogue rate
    or an estimate from the nearest dates on sale (F4).
    """
    observed_at = str(getattr(deal, "live_observed_at", "") or "")
    if observed_at:
        flight_words = (
            relative_age_label(observation_age_hours(observed_at, generated_at))
            or "date unknown"
        )
    else:
        flight_words = "not observed — benchmark"
    hotel_words = hotel_rate_age_words(deal, generated_at=generated_at)
    return (
        '<div style="margin:8px 0 0 0; color:#64748b; font-size:11px;">'
        'Prices last checked: flights ' + escape(flight_words)
        + ', ' + hotel_words + '.</div>'
    )


def _option_title(option: Mapping[str, Any]) -> str:
    if option["kind"] == "mixed_cabin":
        # Its own line, named as a mix: never dressed as (a)/(b), because it is
        # neither Business nor Economy — the whole party did not fly in one
        # cabin (owner brief 2026-10-03, H7).
        return "mixed cabins \u2014 " + str(option.get("cabin_mix", ""))
    if option["kind"] == "business":
        return "(a) Business, normal route"
    if option["kind"] == "economy":
        return "(b) Economy, same route"
    if option["kind"] == "premium_economy":
        return "(b2) Premium Economy, same route"
    hub_label = str(option.get("hub_label", option.get("hub")))
    if option["kind"] == "stopover_premium_economy":
        return "(c2) Premium Economy + 2 nights " + hub_label + " each way"
    return "(c) Economy + 2 nights " + hub_label + " each way"


def _flight_option_line(option: Mapping[str, Any]) -> str:
    """One full option line: flights, stay, any hub hotel, totals and the budget chip."""
    chip = ('<span style="color:#166534; font-weight:700;">within budget</span>' if option["within_budget"]
            else '<span style="color:#b45309; font-weight:700;">over budget</span>')
    stopover = option["kind"] in ("stopover", "stopover_premium_economy")
    # The stopover buys two hotel nights in the hub and, because the party
    # reaches the resort two days after leaving London, two fewer nights there.
    # The reader is told both numbers on the line: "12 nights at the resort +
    # 2 in Doha each way" is the whole difference between this option and (b).
    stay_note = ""
    if stopover and option.get("resort_nights") is not None:
        stay_note = ' (' + str(option["resort_nights"]) + ' nights at the resort'
        hub_each_way = option.get("hub_nights_each_way")
        if hub_each_way:
            stay_note += ' + ' + str(hub_each_way) + ' in ' + str(option["hub_label"]) + ' each way'
        stay_note += ')'
    line = ('<br>' + escape(_option_title(option)) + ': flights £' + f'{float(option["flight_cost"]):,.0f}'
            + ' (' + escape(str(option["flight_basis"])) + ') + stay £' + f'{float(option["hotel_cost"]):,.0f}'
            + stay_note)
    if stopover:
        hotel_note = ', estimate' if option.get("hub_hotel_confidence") == "estimate" else ''
        line += (' + ' + escape(str(option["hub_label"])) + ' hotel £' + f'{float(option["stopover_hotel_cost"]):,.0f}'
                 + ' (' + escape(str(option["hub_hotel"])) + ', ' + str(option["stopover_nights"]) + ' nights, '
                 + escape(BOARD_LABELS.get(board_code(option["hub_board"]), str(option["hub_board"]))) + hotel_note + ')')
    line += (' = <strong>£' + f'{float(option["total_pkg"]):,.0f}' + '</strong> · £'
             + f'{float(option["true_d2d"]):,.0f}' + ' door to door · ' + escape(str(option["outbound"]))
             + '→' + escape(str(option["return"])) + ' from ' + escape(str(option["origin"])) + ' · ' + chip)
    if option.get("source_url"):
        line += (' <a href="' + escape(str(option["source_url"]), quote=True)
                 + '" style="color:#2563eb;text-decoration:none;">multi-city search ↗</a>')
    return line


def _cheapest_stopover(stopovers: Sequence[Mapping[str, Any]]) -> Optional[Mapping[str, Any]]:
    """The stopover to show in full: cheapest within budget, else cheapest overall."""
    if not stopovers:
        return None
    within = [o for o in stopovers if o.get("within_budget")]
    return min(within or list(stopovers), key=lambda o: float(o["total_pkg"]))


def render_flight_options(options: Sequence[Mapping[str, Any]], *, travellers: int,
                          dates: Optional[tuple[str, str]] = None, airport: str = "",
                          origin: str = "") -> str:
    """(a) Business, (b) Economy, (c) Economy with a stopover: each a total for the party.

    Shown in full, in this order: (a) Business, (b) Economy, (c) the cheapest
    Economy stopover, then ONE Premium Economy line — the cheapest PE option,
    same route or stopover, marked in or over budget. Every other stopover
    collapses into one compact "Other stopovers" line, so a card never lists
    every hub's itinerary at once.

    When a card has no read stopover fare, the (c) line still offers the
    multi-city itinerary for every hub as a search link (hotel named), so the
    option is available at every destination in every season without a price
    being invented.
    """
    out = [
        '<div style="margin:0 0 10px 0; padding:8px 12px; background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; font-size:13px; color:#334155;">'
        '<strong style="color:#0f172a;">✈ Flight options for ' + str(travellers)
        + '</strong> <span style="color:#64748b;">— each a total: flights + hotel(s) + board; the budget is tested on each</span>'
    ]
    stopovers = [o for o in options if o["kind"] == "stopover"]
    expanded = _cheapest_stopover(stopovers)

    # (a) Business and (b) Economy always.
    for kind in ("business", "economy"):
        out.extend(_flight_option_line(o) for o in options if o["kind"] == kind)
    # (c) the cheapest Economy stopover, in full.
    if expanded is not None:
        out.append(_flight_option_line(expanded))
    # ONE Premium Economy line: the cheapest PE option (same route or stopover),
    # whichever it is, carrying its in/over-budget mark — never a line per
    # cabin variant.
    pe_options = [o for o in options
                  if o["kind"] in ("premium_economy", "stopover_premium_economy")]
    if pe_options:
        cheapest_pe = min(pe_options, key=lambda o: float(o["total_pkg"]))
        out.append(_flight_option_line(cheapest_pe))
    # A mixed-cabin fare, when one was read: its own line, labelled as a mix,
    # never folded into the Business or Economy row above (owner brief
    # 2026-10-03, H7).
    for mixed in [o for o in options if o["kind"] == "mixed_cabin"]:
        out.append(_flight_option_line(mixed))
    # Every other stopover collapses into one compact totals line.
    other_stopovers = [o for o in stopovers if o is not expanded]
    if other_stopovers:
        totals = ' · '.join(
            escape(str(o.get("hub_label") or o.get("hub"))) + ' £' + f'{float(o["total_pkg"]):,.0f}'
            for o in other_stopovers)
        out.append('<br>Other stopovers: ' + totals + ' (economy, totals)')

    if not stopovers:
        offered = False
        if dates and airport:
            card_outbound, card_return = dates
            lines = []
            for hub in STOPOVER_LINK_HUBS:
                info = STOPOVER_HUBS[hub]
                try:
                    url = stopover_search_url(
                        hub, str(airport).upper(), str(card_outbound), str(card_return),
                        origin=str(origin or "LHR"), travellers=travellers)
                except Exception:
                    continue
                board = BOARD_LABELS.get(board_code(info["hotel"]["board"]), str(info["hotel"]["board"]))
                lines.append(
                    '<br>&nbsp;&nbsp;• ' + escape(str(info["label"])) + ' — '
                    + escape(str(info["hotel"]["name"])) + ' (' + escape(board) + ')'
                    + ' · <a href="' + escape(url, quote=True)
                    + '" style="color:#2563eb;text-decoration:none;">price this multi-city itinerary ↗</a>')
            if lines:
                offered = True
                out.append('<br>(c) Economy + 2 nights in a Gulf hub each way, hotel included: no '
                           'whole-party fare was read for these dates, so nothing is priced here — '
                           'price on request, one click to price it:')
                out.extend(lines)
        if not offered:
            out.append('<br>(c) Economy + 2 nights Doha or Muscat each way: not priced for these dates '
                       '(no multi-city fare was read).')
    out.append('</div>')
    return ''.join(out)


def render_gate_not_applied(resort_names: Sequence[str], *, pool_unverified: Sequence[str] = (),
                            blocked_reasons: Mapping[str, str] | None = None) -> str:
    """Name every shown resort whose TripAdvisor or heated-pool gate could not be applied.

    ``blocked_reasons`` maps a resort to why its source refused the read. Where
    we have one, the banner says the read was ATTEMPTED and refused — the
    difference between a gap in our research and the source saying no.
    """
    parts = []
    if resort_names:
        blocked = blocked_reasons or {}
        attempts = [name for name in resort_names if name in blocked]
        unread = [name for name in resort_names if name not in blocked]
        if attempts:
            reasons = sorted({blocked[name] for name in attempts})
            parts.append(
                '<strong>🔍 Rule not applied — TripAdvisor ≥4.5:</strong> we read the page and were '
                'refused for ' + escape(', '.join(attempts)) + ' ('
                + escape('; '.join(reasons)) + '), so those resorts are shown without that check.'
            )
        if unread:
            parts.append(
                '<strong>🔍 Rule not applied — TripAdvisor ≥4.5:</strong> the rating could not be read for '
                + escape(', '.join(unread))
                + '. TripAdvisor blocks automated reads and its public summary shows only a rounded whole '
                'number, so these resorts are shown without that check. Look each one up before booking.'
            )
    if pool_unverified:
        parts.append(
            '<strong>🔍 Rule not applied — pools heated to ≥28°C in December:</strong> not stated for '
            + escape(', '.join(pool_unverified)) + '. Ask the hotel before booking.'
        )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; '
        'background:#fffbeb; border:1px solid #fde68a; border-radius:8px; margin:0 0 18px 0;">'
        '<tr><td style="padding:12px 16px; color:#78350f; font-size:14px; line-height:1.6;">'
        + '<br>'.join(parts) + '</td></tr></table>'
    )


_FLIGHT_BASIS_WORDS = {
    "verified-exact-date": "live fare read",
    "stale-cache": "observed fare, not live",
    "benchmark": "benchmark",
}
_HOTEL_BASIS_WORDS = {
    "market-supported": "rate read for these dates",
    "estimate": "rate estimate from the nearest dates on sale",
}


def render_over_budget(rows: Sequence[Mapping[str, Any]], *, travellers: int) -> str:
    """Long-haul resorts priced but over the budget, cheapest first, with bases."""
    if not rows:
        return ""
    budget = float(rows[0].get("max_budget_gbp", 0.0))
    out = [
        '<h2 style="margin:6px 0 4px 0; color:#0f172a; font-size:20px; font-weight:800;">'
        '💷 Resorts priced over the £' + f'{budget:,.0f}' + ' budget</h2>',
        '<p style="margin:0 0 8px 0; color:#475569; font-size:13px;">Each resort\'s cheapest option '
        'for ' + str(travellers) + ' across the configured dates and airports. Not cards: no option fits '
        'the budget. Long-haul resorts show all three flight options (Business, Economy, a Doha/Muscat '
        'stopover); a short-haul destination is listed here only when none of its resorts fits.</p>',
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; '
        'background:#ffffff; border:1px solid #e2e8f0; border-radius:8px; margin:0 0 18px 0;">',
    ]
    for row in rows:
        over = max(float(row["true_d2d"]) - budget, 0.0)
        flight_words = _FLIGHT_BASIS_WORDS.get(str(row.get("flight_confidence")), "benchmark estimate")
        hotel_words = _HOTEL_BASIS_WORDS.get(str(row.get("hotel_confidence")), "rate estimate")
        out.append(
            '<tr><td style="padding:8px 12px; border-bottom:1px solid #f1f5f9; font-size:13px; color:#475569;">'
            '<strong style="color:#0f172a;">' + escape(str(row["resort_name"])) + '</strong> · '
            + escape(str(row["destination_label"])) + ' (' + escape(str(row["airport"])) + ')<br>'
            '<strong style="color:#0f172a;">£' + f'{float(row["total_pkg"]):,.0f}' + '</strong> package · £'
            + f'{float(row["true_d2d"]):,.0f}' + ' door to door · <span style="color:#b45309;">£'
            + f'{over:,.0f}' + ' over</span> · ' + escape(str(row["outbound"])) + '→' + escape(str(row["return"]))
            + ', ' + str(row["nights"]) + ' nights from ' + escape(str(row["origin"])) + '<br>'
            'flights £' + f'{float(row["flight_cost"]):,.0f}' + ' ' + escape(str(row["cabin"]).title())
            + ' (' + escape(flight_words) + ') · stay £' + f'{float(row["hotel_cost"]):,.0f}' + ', '
            + escape(str(row["unit"])) + ' (' + escape(hotel_words) + ')'
            + render_board_line(row)
            + (render_flight_options(row["flight_options"], travellers=travellers,
                                     dates=(row["outbound"], row["return"]),
                                     airport=row["airport"], origin=row["origin"])
               if row.get("flight_options") else '')
            + '</td></tr>'
        )
    out.append('</table>')
    return ''.join(out)


def render_holiday_report(
    config: HolidayConfig,
    *,
    generated_at: str,
    deals: Sequence[PackageDeal] = (),
    history_chips: Optional[Sequence[str]] = None,
    change_digest_html: str = "",
) -> str:
    out: list[str] = []
    shortlist = shortlist_date_pairs(config)
    # Every configured pair, for the header's "date combinations" count, and then
    # every pair in the stay band: what the collector actually prices, and
    # therefore what a reader can expect a deal's dates to come from.
    pairs = _date_pairs(config)
    priced_pairs = priceable_date_pairs(config)
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
    btn_primary = "background:#38bdf8; color:#062033; text-decoration:none; padding:9px 14px; border-radius:5px; font-weight:700; font-size:14px; margin:2px 4px 2px 0; display:inline-block;"
    btn_compare = "background:#7c3aed; color:#ffffff; text-decoration:none; padding:12px 20px; border-radius:8px; font-weight:700; font-size:14px; display:inline-block;"
    btn_muted = "background:#1e293b; color:#94a3b8; text-decoration:none; padding:7px 12px; border-radius:4px; font-weight:500; font-size:13px; margin:2px 3px 2px 0; display:inline-block; border:1px solid #334155;"
    
    out.append('<!DOCTYPE html><html><head><meta charset="utf-8"><title>')
    out.append(escape(config.report_title))
    out.append('</title></head><body style="margin:0; padding:0; background:#eef2f7; font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif; line-height:1.5;">')
    # Full-width light canvas; inner column centered via align=center
    # (Gmail strips margin:auto on tables).
    out.append('<table role="presentation" width="100%" bgcolor="#eef2f7" cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:20px 12px;">')
    out.append('<table role="presentation" width="1080" cellpadding="0" cellspacing="0" style="width:100%; max-width:1080px;">')
    out.append('<tr><td style="padding:0 0 14px 0;">')
    out.append('<h1 style="margin:0 0 4px 0; color:#0f172a; font-size:30px; font-weight:800;">☀️ ' + escape(config.report_title) + '</h1>')
    out.append('<p style="margin:0; color:#64748b; font-size:15px;">')
    out.append(escape(generated_at))
    out.append(' · ')
    out.append(str(len(config.destinations)))
    out.append(' destinations · ')
    out.append(str(len(pairs)))
    out.append(' date combinations · ')
    out.append(str(len(priced_pairs)))
    out.append(
        ' priced ('
        + str(config.min_nights)
        + '–'
        + str(config.max_nights)
        + ' nights)</p>'
    )
    out.append('</td></tr>')
    out.append('<tr><td style="padding:0 0 18px 0;">')
    out.append('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px;">')
    out.append('<tr><td style="padding:12px 16px; color:#475569; font-size:15px;">')
    strict_unit = len(config.rooms) >= 3
    out.append('<strong style="color:#0f172a;">' + str(config.travellers) + '</strong> travellers')
    if strict_unit:
        out.append(' · <strong style="color:#0f172a;">ONE booking</strong> — sleeps all 5 in a single unit: 2-bedroom suite/duplex where verified, otherwise 2× guaranteed-connecting rooms (connection confirmed by the hotel post-booking). Never 3 scattered rooms.')
    else:
        out.append(' · <strong style="color:#0f172a;">' + str(len(config.rooms)) + '</strong> room(s)')
        out.append('<br>Room occupancy: <strong style="color:#0f172a;">' + escape(room_occupancy) + '</strong>')
    out.append('<br>Preferred departure <strong style="color:#0f172a;">' + escape(config.departure_window[0]) + '–' + escape(config.departure_window[1]) + '</strong>')
    out.append('<br>Outbound <strong style="color:#0f172a;">' + escape(', '.join(config.outbound_dates)) + '</strong> · Return <strong style="color:#0f172a;">' + escape(', '.join(config.return_dates)) + '</strong>')
    out.append('</td></tr></table>')
    out.append('</td></tr><tr><td>')
    # WHAT CHANGED SINCE THE LAST REPORT — the strip that makes each email
    # worth opening. Empty (renders nothing) on the very first run.
    if change_digest_html:
        out.append(change_digest_html)
        out.append('</td></tr><tr><td>')

    # ── STRICT FILTER TRANSPARENCY: every removed resort and why ──
    if LAST_FILTERED_OUT:
        out.append('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; background:#ffffff; border:1px solid #e2e8f0; border-radius:8px; margin:0 0 18px 0;">')
        out.append('<tr><td style="padding:12px 16px; color:#475569; font-size:14px; line-height:1.6;">')
        out.append('<strong style="color:#0f172a;">🔍 Strict filters applied</strong> — resorts removed and why:')
        for name, reason in LAST_FILTERED_OUT:
            out.append('<br>• <strong style="color:#0f172a;">' + escape(name) + '</strong> — ' + escape(reason))
        out.append('</td></tr></table>')
        out.append('</td></tr><tr><td>')

    # Rows of the last collect that belong to THIS config: the module global
    # outlives the call that set it, and a stale row must never leak into
    # another report.
    config_keys = {d.key.lower() for d in config.destinations}
    over_budget_rows = [
        row for row in LAST_OVER_BUDGET
        if str(row.get("destination_key", "")).lower() in config_keys
    ]

    # ── A RULE THAT COULD NOT BE APPLIED IS STATED, NOT IMPLIED ──
    shown = {d.resort_name for d in deals} | {row["resort_name"] for row in over_budget_rows}
    gate_open = sorted(name for name in shown if tripadvisor_unverified(name))
    pool_open = sorted(
        name for name in shown
        if not is_summer_trip(config) and pool_heating_unverified(name)
    )
    if gate_open or pool_open:
        # Where the hotel file records a blocked source for a resort, the
        # banner says the read was attempted and refused rather than that the
        # rating "could not be read" — a gap in our research and a source
        # saying no are different facts.
        blocked_reasons = {}
        for deal in deals:
            for entry in getattr(deal, "hotel_evidence_blocked", ()) or ():
                blocked_reasons[deal.resort_name] = (
                    f"{entry.what} {entry.reason}"
                )
            for entry in supplemental_for(deal.resort_name, "blocked"):
                blocked_reasons[deal.resort_name] = f"{entry.what} {entry.reason}"
        out.append(
            render_gate_not_applied(
                gate_open,
                pool_unverified=pool_open,
                blocked_reasons=blocked_reasons,
            )
        )
        out.append('</td></tr><tr><td>')

    is_summer = is_summer_trip(config)

    # ── FAR EAST FIRST (owner preference, 2026-09-28) ──
    far_east = render_far_east_watch(config)
    if far_east:
        out.append(far_east)

    # ── LONG-HAUL RESORTS PRICED OVER THE BUDGET: stated, never silently dropped ──
    if over_budget_rows:
        out.append(render_over_budget(over_budget_rows, travellers=config.travellers))

    # ── VERIFIED LIVE DEALS UNDER £5,000 (WHEN AVAILABLE) ──
    if deals:
        if is_summer:
            out.append('<h2 style="margin:22px 0 4px 0; color:#0f172a; font-size:24px; font-weight:800;">⭐ Summer Luxury Deals — One Family Unit</h2>')
            out.append('<p style="margin:0 0 10px 0; color:#475569; font-size:15px;">Every resort sleeps all 5 in <strong>ONE booking</strong>: a 2-bedroom villa or suite or, where no single unit takes 5 adults, two rooms on the same booking (not a guaranteed connecting pair) — each card names its unit. Walkable beach at the resort. Flight routing, guest rating and the price basis of every figure are stated on each card; long-haul flights are Business on the long sector.</p>')
        else:
            out.append('<h2 style="margin:22px 0 4px 0; color:#0f172a; font-size:24px; font-weight:800;">⭐ December Deals — One Family Unit, Real Discounts vs Summer Peak</h2>')
            out.append('<p style="margin:0 0 10px 0; color:#475569; font-size:15px;">Every resort sleeps all 5 in <strong>ONE booking</strong> (2-bedroom suite, duplex, or 2× guaranteed-connecting rooms where the hotel confirms the connection post-booking). Pools heated ≥28°C, walkable beach, TripAdvisor ≥4.5, nonstop flights, any departure time. Ranked by how much cheaper the same stay is in December versus its July/August peak.</p>')
        # At-a-glance: one line per decision lens (no ranked walls).
        buckets = bucket_deals(deals)
        glance = '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; background:#ffffff; border:1px solid #e2e8f0; border-radius:8px; margin:0 0 16px 0;">'
        b1 = buckets["discounts"][0] if buckets["discounts"] else None
        b2 = buckets["luxury"][0] if buckets["luxury"] else None
        # Climate award ranks only IN-SEASON resorts: a monsoon resort must
        # never win "Best Summer Climate" for a travel month it is rained out.
        climate_pool = [d for d in buckets["winter"] if not deal_in_monsoon(d)]
        b3 = climate_pool[0] if climate_pool else None
        if b1 is not None and b1.vs_peak_saving_gbp > 0:
            # "Biggest Discount" only for an observed earlier price; a gap
            # against our own benchmark is "furthest below", not a discount.
            if getattr(b1, "peak_observed", False):
                disc_label = "💰 Biggest Discount vs Benchmark:" if is_summer else "💰 Biggest Discount vs Summer Peak:"
                disc_value = ('<strong style="color:#059669;">▼' + str(b1.vs_peak_pct)
                              + '% (save £' + f'{b1.vs_peak_saving_gbp:,.0f}' + ' for the same resort)</strong>')
            else:
                disc_label = "💰 Furthest below our benchmark estimate:"

                disc_value = ('<strong style="color:#475569;">▼' + str(b1.vs_peak_pct)
                              + '% (£' + f'{b1.vs_peak_saving_gbp:,.0f}'
                              + ' below our benchmark estimate — not a saving)</strong>')
            glance += ('<tr><td style="padding:9px 12px; color:#475569; font-size:14px; border-bottom:1px solid #f1f5f9;">'
                       '<strong style="color:#0f172a;">' + disc_label + '</strong> '
                       + escape(b1.resort_name) + ' — ' + disc_value + '</td></tr>')
        if b2 is not None:
            lux_limit = "£" + f"{config.max_budget_gbp / 1000:g}" + "k"
            glance += ('<tr><td style="padding:9px 12px; color:#475569; font-size:14px; border-bottom:1px solid #f1f5f9;">'
                       '<strong style="color:#0f172a;">💎 Top Luxury Within ' + lux_limit + ':</strong> '
                       + escape(b2.resort_name) + ' · ' + escape(b2.board_basis) + '</td></tr>')
        if b3 is not None:
            if is_summer:
                climate = SUMMER_WEATHER.get(b3.destination_key.lower(), ((30, 34), 26))
                glance += ('<tr><td style="padding:9px 12px; color:#475569; font-size:14px; border-bottom:1px solid #f1f5f9;">'
                           '<strong style="color:#0f172a;">☀️ Best Summer Climate:</strong> '
                           + escape(b3.resort_name) + ' — ' + str(climate[0][0]) + '–' + str(climate[0][1]) + '°C air, sea ' + str(climate[1]) + '°C</td></tr>')
            else:
                glance += ('<tr><td style="padding:9px 12px; color:#475569; font-size:14px; border-bottom:1px solid #f1f5f9;">'
                           '<strong style="color:#0f172a;">☀️ Best Winter Facilities:</strong> '
                           + escape(b3.resort_name) + ' — ' + str(b3.dec_ambient_c[0]) + '–' + str(b3.dec_ambient_c[1]) + '°C air, sea ' + str(b3.sea_temp_c) + '°C</td></tr>')
        b4 = buckets["value"][0] if buckets["value"] else None
        # A "best overall value" award for a card whose own score is under half
        # contradicts the card (owner rule 2026-10-02): below the threshold no
        # value award is shown at all, rather than a "best" that reads as a
        # splurge to avoid.
        if (
            b4 is not None
            and getattr(b4, "value_score_verified", False)
            and b4.value_score >= VALUE_AWARD_MIN_SCORE
        ):
            score_type = "(family luxury score)" if is_summer else "(winter-first score)"
            glance += ('<tr><td style="padding:9px 12px; color:#475569; font-size:14px;">'
                       '<strong style="color:#0f172a;">🏆 Best Overall Value:</strong> '
                       + escape(b4.resort_name) + ' — value score ' + f'{b4.value_score:.0f}'
                       + '/100 ' + score_type + '</td></tr>')
        glance += '</table>'
        out.append(glance)

        # Chips align with the caller's `deals` order; index them by resort
        # name so the card order below (cheapest first) stays correct.
        chip_by_resort = {}
        if history_chips is not None:
            for i, d in enumerate(deals):
                if i >= len(history_chips):
                    break
                # Chip follows the BASELINE (cheapest cabin) card per hotel.
                prev = chip_by_resort.get(d.resort_name)
                if prev is None or d.total_package_price_gbp < prev[0]:
                    chip_by_resort[d.resort_name] = (d.total_package_price_gbp, history_chips[i])
            chip_by_resort = {name: chip for name, (_, chip) in chip_by_resort.items()}

        rooms_n = len(config.rooms)
        ordered = sorted(deals, key=lambda d: d.total_package_price_gbp)
        # ONE CARD PER HOTEL (2026-09-22 user mandate): never list the same
        # hotel twice. The cheapest viable cabin is the card's baseline price;
        # premium cabins become "Optional add-on" lines inside that card.
        hotels: list[dict] = []
        seen_hotels: set[str] = set()
        for d in ordered:
            if d.resort_name in seen_hotels:
                continue
            seen_hotels.add(d.resort_name)
            hotels.append({
                "base": d,
                "group": [x for x in ordered if x.resort_name == d.resort_name],
            })
        # Gmail clips emails over 102 KB. Two guards, because the card grew
        # per-operator links and a self-create block: a hard cap of 10 hotels,
        # AND a running byte budget that stops adding cards once the payload
        # reaches EMAIL_HTML_BUDGET_BYTES. The budget is the real guarantee —
        # a fixed card count silently breaks the moment a card gets richer,
        # which is exactly how an e-mail ends up clipped mid-link.
        rendered_hotels: list[dict] = []
        # Two DIFFERENT things shorten this report, and the reader deserves to
        # be told which one happened: the deliberate hotels[:10] cap, and the
        # byte budget. Counting them apart is the point — labelling a design
        # choice as "size limit" is a false statement about why a deal is
        # missing, and it trains the reader to distrust the real budget notice
        # when it does fire.
        size_dropped = 0
        for index, entry in enumerate(hotels[:10]):
            rendered_hotels.append(entry)
            # Where this card's markup starts, so a card that will not fit can
            # be taken back out again below. The budget is checked on the card
            # AS WRITTEN — building it, weighing the finished e-mail with it in,
            # and only then deciding — because a check made before the card
            # exists can only guess its size, and the guess is either a lie
            # (too small, and a clipped e-mail ships) or a card thrown away that
            # would have fitted (what the pre-hoist measurement used to do: it
            # counted the un-hoisted markup, a third heavier than the e-mail).
            card_start = len(out)
            deal = entry["base"]
            stars_str = '★' * deal.star_rating + '☆' * (5 - deal.star_rating)
            live = deal.confidence == 'verified-exact-date'
            # A third state, because two were not enough to be honest: an
            # observed fare that is too old to call live is neither LIVE
            # VERIFIED nor a BENCHMARK PRICE, and labelling it as either tells
            # the reader something untrue.
            stale = deal.confidence == 'stale-cache'
            # Age at RENDER time against the one shared threshold: an
            # observation that has passed EVIDENCE_MAX_AGE_HOURS by the time
            # this report is generated may not claim to be live, whatever the
            # loader thought when it read the file.
            observed_age_hours = observation_age_hours(
                getattr(deal, "live_observed_at", ""), generated_at
            )
            if (
                observed_age_hours is not None
                and (live or stale)
                and observed_age_hours > live_verify.EVIDENCE_MAX_AGE_HOURS
            ):
                live, stale = False, True
            under = 5000.0 - deal.total_package_price_gbp
            out.append('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:separate; border-spacing:0; margin:0 0 14px 0; background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; overflow:hidden;">')
            out.append('<tr>')
            # TEXT-ONLY card (images suspended 2026-09-22): no <img> tags
            # until a per-hotel image source exists. One cell, one glance.
            out.append('<td valign="top" style="padding:16px 20px;">')
            out.append('<div style="margin-bottom:3px;"><strong style="color:#0f172a; font-size:20px;">' + escape(deal.resort_name) + '</strong> <span style="color:#f59e0b; font-size:14px;">' + stars_str + '</span></div>')
            cabin_badge = ""
            cabin_is_premium = getattr(deal, "cabin_class", "ECONOMY") in ("BUSINESS", "FIRST", "PREMIUM_ECONOMY")
            if getattr(deal, "cabin_class", "") == "BUSINESS":
                cabin_badge = '<span style="background:#fdf2f8; color:#9d174d; padding:3px 10px; border-radius:9999px; font-size:13px; font-weight:700;">💼 Business Class' + ('' if (live or stale) else ' (estimate)') + '</span> '
            elif getattr(deal, "cabin_class", "") == "PREMIUM_ECONOMY":
                cabin_badge = '<span style="background:#f0fdfa; color:#0f766e; padding:3px 10px; border-radius:9999px; font-size:13px; font-weight:700;">✨ Premium Economy' + ('' if (live or stale) else ' (estimate)') + '</span> '
            elif getattr(deal, "cabin_class", "") == "FIRST":
                cabin_badge = '<span style="background:#fdf2f8; color:#9d174d; padding:3px 10px; border-radius:9999px; font-size:13px; font-weight:700;">🥇 First Class' + ('' if (live or stale) else ' (estimate)') + '</span> '
            out.append('<div style="margin:5px 0 7px;">')
            out.append(cabin_badge)
            out.append('<span style="background:#eff6ff; color:#1d4ed8; padding:3px 10px; border-radius:9999px; font-size:13px; font-weight:700;">' + escape(deal.board_basis) + '</span> ')
            if live:
                chip_bg, chip_fg, chip_text = '#dcfce7', '#166534', '🟢 LIVE VERIFIED'
            elif stale:
                chip_bg, chip_fg, chip_text = '#ffedd5', '#9a3412', '🟠 OBSERVED, NOT LIVE'
            else:
                chip_bg, chip_fg, chip_text = '#fef3c7', '#92400e', '🟡 BENCHMARK PRICE'
            out.append('<span style="background:' + chip_bg + '; color:' + chip_fg + '; padding:3px 10px; border-radius:9999px; font-size:13px; font-weight:700;">' + chip_text + '</span> ')
            if (live or stale) and getattr(deal, "live_observed_at", ""):
                # AUDITABLE, not decorative: the chip must state WHEN the fare
                # was observed and LINK to the page the amount was read from.
                # A bare "LIVE" label is exactly the unverifiable claim the
                # data-provenance mandate forbids.
                try:
                    observed_day = str(deal.live_observed_at)[:10]
                except (TypeError, ValueError):
                    observed_day = ""
                age_text = relative_age_label(
                    observation_age_hours(deal.live_observed_at, generated_at)
                )
                age_html = escape(age_text) if age_text else "date unknown"
                out.append('<span style="color:' + ('#9a3412' if stale else '#166534') + '; font-size:11px;">observed ' + age_html + ' (' + escape(observed_day) + ') · </span><a href="' + escape(deal.source_url, quote=True) + '" style="color:' + ('#9a3412' if stale else '#166534') + '; font-size:11px;">fare source ↗</a>')
            out.append(peak_discount_badge(deal))
            history_chip = chip_by_resort.get(deal.resort_name, '')
            if history_chip:
                out.append(' ' + history_chip)
            out.append('</div>')
            if deal_in_monsoon(deal):
                # Visible, on the card header itself: a monsoon-month trip can
                # still be priced, but never without this warning.
                month = deal_travel_month(deal)
                month_name = escape(_MONTH_NAMES[month - 1]) if month else "your travel"
                out.append('<div style="margin:0 0 8px 0; padding:7px 11px; background:#fff7ed; border:1px solid #fdba74; border-radius:6px; color:#9a3412; font-size:13px; font-weight:600;">⚠️ Monsoon season (approximate climatology) for your ' + month_name + ' travel month — expect heavy rain and rough seas; pool and beach days may be rained off.</div>')
            out.append('<div style="color:#64748b; font-size:14px; margin-bottom:7px;">📍 ' + escape(deal.destination_label) + ' (' + escape(deal.destination_airport) + ') · ' + escape(deal.outbound_date) + ' → ' + escape(deal.return_date) + ' · ' + str(deal.nights) + ' nights</div>')
            if deal.highlights:
                out.append('<div style="color:#475569; font-size:14px; margin-bottom:8px;">✨ ' + escape(' · '.join(deal.highlights)) + '</div>')
            # Recovered criteria strip: value score and deal class always; the
            # 0-10 scores only where curated scores exist. What is NOT assessed
            # is not a second "not assessed" line — it joins the single
            # "not verified: …" booking-terms line (owner rule 2026-10-02).
            crit = ('🕌 ' + escape(deal.mosque_name) + ' — ' + str(deal.mosque_walk_minutes) + ' min walk'
                    if deal.mosque_name else '')
            # The score is shown only when it is computed from this resort's own
            # criteria. A default-derived number measured only the price, so
            # printing it (as "35/100" on every card) was a measurement that
            # never happened; "value score" then sits in the not-verified list.
            score_html = (
                '<strong style="color:#7c3aed;">value score ' + f'{deal.value_score:.0f}' + '/100</strong> · '
                if getattr(deal, "value_score_verified", False) else ''
            )
            out.append('<div style="color:#334155; font-size:14px; margin-bottom:4px;">' + score_html
                       + '<span style="background:#faf5ff; color:#6d28d9; padding:2px 8px; border-radius:6px; font-size:12px; font-weight:700;">' + escape(_deal_class_words(deal.deal_class)) + '</span></div>')
            season_score_name = "🏊 beach & pools" if is_summer else "❄️ winter"
            if deal.resort_name in RESORT_CRITERIA:
                score_parts = ([crit] if crit else []) + [
                    '🍽️ food ' + f'{deal.food_reality_score:.0f}' + '/10',
                    '💎 luxury ' + f'{deal.actual_luxury_score:.0f}' + '/10',
                    season_score_name + ' ' + f'{deal.winter_facilities_score:.0f}' + '/10',
                    '🎯 activities ' + f'{deal.activities_score:.0f}' + '/10',
                    '✈️ flights ' + f'{deal.flight_quality_score:.0f}' + '/10',
                ]
                out.append('<div style="color:#334155; font-size:14px; margin-bottom:4px;">'
                           + ' · '.join(score_parts) + '</div>')
            if deal.food_review_summary:
                out.append('<div style="color:#64748b; font-size:13px; margin-bottom:8px;"><strong style="color:#475569;">Food reviews:</strong> ' + escape(deal.food_review_summary) + '</div>')
            # Facts strip: flights | stay | weather | BIG price
            cabin_label = f" ({deal.cabin_class.replace('_', ' ').title()})" if getattr(deal, "cabin_class", "ECONOMY") != "ECONOMY" else ""
            flight_carrier_display = escape(deal.airline) if cabin_is_premium else escape(deal.airline.split('/')[0].strip())
            if live:
                flight_note = (
                    '<br><span style="font-size:11px; color:#166534;">'
                    + escape(getattr(deal, "live_carrier", "") or deal.airline)
                    + ' — live observed fare</span>'
                )
            elif stale:
                # Observed, merely not current: say how old it is. 'estimate'
                # is reserved for modelled prices, so an aged observation must
                # never wear it (2026-10-02 correction).
                age_text = relative_age_label(
                    observation_age_hours(deal.live_observed_at, generated_at)
                ) or "earlier"
                flight_note = (
                    '<br><span style="font-size:11px; color:#9a3412;">observed '
                    + escape(age_text) + ' — not live</span>'
                )
            else:
                flight_note = "<br><span style=\"font-size:11px;\">estimate — live cabin check required</span>" if cabin_is_premium else ""
            out.append('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; background:#f8fafc; border-radius:8px; margin-bottom:10px;"><tr>')
            out.append('<td style="padding:10px 12px; color:#64748b; font-size:13px;">✈️ Flights' + cabin_label + '<br><strong style="color:#0f172a; font-size:16px;">£' + f'{deal.flight_price_total_gbp:,.0f}' + '</strong><br><span style="font-size:12px;">' + flight_carrier_display + '</span>' + flight_note + '</td>')
            suite_label = deal.unit_architecture or (str(rooms_n) + ' rooms')
            out.append('<td style="padding:10px 12px; color:#64748b; font-size:13px; border-left:1px solid #e2e8f0;">🏨 Stay<br><strong style="color:#0f172a; font-size:16px;">£' + f'{deal.hotel_price_total_gbp:,.0f}' + '</strong><br><span style="font-size:12px;">' + escape(suite_label) + ' · ' + str(deal.nights) + 'n</span></td>')
            if is_summer:
                climate = SUMMER_WEATHER.get(deal.destination_key.lower(), ((28, 33), 25))
                out.append('<td style="padding:10px 12px; color:#64748b; font-size:13px; border-left:1px solid #e2e8f0;">🌡️ Summer<br><strong style="color:#0f172a; font-size:16px;">' + str(climate[0][0]) + '–' + str(climate[0][1]) + '°C</strong><br><span style="font-size:12px;">sea ' + str(climate[1]) + '°C</span></td>')
            elif deal.sea_temp_c:
                floor_temp = _dec_temp_for_floor(deal.outbound_date, float(deal.dec_ambient_c[0]))
                floor_note = (
                    '<br><span style="font-size:11px; color:#b45309;">below 20°C winter-sun floor — ranked accordingly</span>'
                    if floor_temp is not None and floor_temp < WINTER_SUN_FLOOR_C
                    else ''
                )
                out.append('<td style="padding:10px 12px; color:#64748b; font-size:13px; border-left:1px solid #e2e8f0;">🌡️ December<br><strong style="color:#0f172a; font-size:16px;">' + str(deal.dec_ambient_c[0]) + '–' + str(deal.dec_ambient_c[1]) + '°C</strong><br><span style="font-size:12px;">sea ' + str(deal.sea_temp_c) + '°C</span>' + floor_note + '</td>')
            else:
                out.append('<td style="padding:10px 12px; color:#64748b; font-size:13px; border-left:1px solid #e2e8f0;">🌡️ December<br><strong style="color:#0f172a; font-size:16px;">' + str(deal.dec_ambient_c[0]) + '–' + str(deal.dec_ambient_c[1]) + '°C</strong><br><span style="font-size:12px;">city stay, no sea swimming</span></td>')
            out.append('<td align="right" valign="middle" style="padding:8px 10px;">')
            out.append('<div style="color:#059669; font-size:30px; font-weight:800; white-space:nowrap;">£' + f'{deal.total_package_price_gbp:,.0f}' + '</div>')
            out.append('<div style="color:#64748b; font-size:13px; white-space:nowrap;">£' + f'{deal.price_per_person_gbp:,.0f}' + 'pp · D2D £' + f'{deal.true_d2d_gbp:,.0f}' + '</div>')
            if is_summer:
                if deal.vs_peak_saving_gbp > 0:
                    out.append('<div style="color:#475569; font-size:12px; white-space:nowrap;">£' + f'{deal.vs_peak_saving_gbp:,.0f}' + ' below our benchmark estimate</div>')
                else:
                    out.append('<div style="color:#64748b; font-size:12px; white-space:nowrap;">summer rate — no peak discount claimed</div>')
            else:
                out.append('<div style="color:#b45309; font-size:12px; white-space:nowrap;">summer peak £' + f'{deal.peak_summer_total_gbp:,.0f}' + '</div>')
            out.append('</td>')
            out.append('</tr></table>')

            # The card's headline price is the Business option, and a card can
            # exist because an Economy option fits. Its budget line therefore
            # leads with the cabin that FITS, naming the others that breach
            # (owner rule 2026-10-02) — the same line a Far East watch row
            # carries. It says nothing when every option is inside the budget.
            cabin_options = [
                (_BUDGET_CABIN_LABELS.get(str(option["kind"]), str(option["kind"])),
                 float(option["true_d2d"]), bool(option["within_budget"]))
                for option in deal.flight_options
                if str(option["kind"]) in _BUDGET_CABIN_LABELS
            ]
            budget_line = budget_headline(cabin_options, config.max_budget_gbp)
            if budget_line:
                out.append('<div style="margin:0 0 8px 0; font-size:13px;">💷 ' + budget_line + '</div>')

            # Board basis, then booking terms, on every hotel line; long-haul
            # flight options side by side. The hotel-rate line comes first when
            # a real rate was read for this resort and these dates (H3).
            out.append(render_hotel_rate_line(deal))
            out.append(render_hotel_rating_line(deal))
            out.append(render_hotel_facts_line(deal))
            out.append(render_hotel_unit_note_line(deal))
            out.append(render_space_note_line(deal))
            out.append(render_board_line(deal))
            out.append(render_booking_terms(deal))
            if deal.flight_options:
                out.append(render_flight_options(
                    deal.flight_options, travellers=config.travellers,
                    dates=(deal.outbound_date, deal.return_date),
                    airport=deal.destination_airport, origin=deal.origin))
            # Deal rationale callout: explain WHY this is a great deal for this party
            rationale_points: list[str] = []
            if deal.unit_architecture and int(deal.rooms_in_unit or 1) < 3:
                # Never claim a three-room quote is one unit: the collector
                # filters those out, and a hand-built deal must not slip one
                # through here either.
                rationale_points.append('<strong>Family Unit for ' + str(config.travellers) + ':</strong> ' + escape(deal.unit_architecture) + ' sleeps everyone in one booking.')
            elif len(config.rooms) >= 2:
                rationale_points.append('<strong>Connecting Family Unit:</strong> 2 interconnecting rooms confirmed post-booking for all ' + str(config.travellers) + '.')
            if "All Inclusive" in deal.board_basis:
                rationale_points.append('<strong>All-Inclusive Economics:</strong> ' + escape(deal.board_basis) + ' covers full breakfast, lunch, dinner, drinks, and snacks for all ' + str(config.travellers) + ' — saving £150–£250/day in resort dining.')
            elif "Half Board" in deal.board_basis:
                rationale_points.append('<strong>Half Board Value:</strong> Daily breakfast and dinner included for all ' + str(config.travellers) + ', leaving lunchtime flexible for beach & excursions.')
            if deal.routing:
                # A long-haul route with no London nonstop: say how it goes,
                # never "Nonstop Logistics".
                rationale_points.append('<strong>Routing:</strong> ' + escape(deal.routing) + '.')
            else:
                rationale_points.append('<strong>Nonstop Logistics:</strong> Flights to ' + escape(deal.destination_airport) + ' from ' + escape(', '.join(config.origins[:2])) + ', preserving civil arrival times.')
            per_person_per_night = round(deal.price_per_person_gbp / max(1, deal.nights))
            # "luggage included" is a claim about what a fare includes, and no
            # fare data verifies it, so it is never asserted here: baggage sits
            # in the booking-terms not-verified list instead.
            rationale_points.append('<strong>Door-to-Door Transparency:</strong> £' + f'{deal.price_per_person_gbp:,.0f}' + 'pp (£' + str(per_person_per_night) + '/day) true total with flights, stay, and transfers.')

            out.append('<div style="margin:0 0 10px 0; padding:10px 14px; background:#f0fdf4; border:1px solid #bbf7d0; border-radius:8px;">')
            out.append('<div style="color:#166534; font-size:13px; font-weight:700; margin-bottom:4px;">💡 Why this is a great deal:</div>')
            for pt in rationale_points:
                out.append('<div style="color:#15803d; font-size:12px; line-height:1.45; margin-bottom:2px;">• ' + pt + '</div>')
            out.append('</div>')
            # ONE CARD PER HOTEL: other cabins surface here as alternates
            # for the same hotel & dates — never as duplicate cards. An
            # Economy line CAN appear (e.g. its live read exceeds a stale
            # premium benchmark), so "upgrade" is the wrong frame: the
            # header is neutral and Economy carries its own badge. Deltas
            # render signed: +£ dearer, −£ cheaper.
            upgrades = [x for x in entry["group"] if x.cabin_class != deal.cabin_class]
            if upgrades:
                out.append('<div style="margin:0 0 10px 0; padding:8px 12px; background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px;"><strong style="color:#0f172a; font-size:13px;">Other cabin options for the same hotel &amp; dates</strong>')
                upgrade_badges = {
                    "BUSINESS": "💼 Business Class",
                    "PREMIUM_ECONOMY": "✨ Premium Economy",
                    "FIRST": "🥇 First",
                    "ECONOMY": "🏷️ Economy",
                }
                live_mark = ''
                for up in sorted(upgrades, key=lambda x: x.total_package_price_gbp):
                    delta = up.total_package_price_gbp - deal.total_package_price_gbp
                    badge = upgrade_badges.get(up.cabin_class, up.cabin_class)
                    delta_str = '+£' + f'{delta:,.0f}' if delta >= 0 else '−£' + f'{abs(delta):,.0f}'
                    if up.confidence == 'verified-exact-date':
                        live_mark = ' · <span style="color:#166534; font-weight:700;">🟢 live observed</span>'
                    elif up.confidence == 'stale-cache':
                        # These rows carry the fare too, so an aged one has to say
                        # so here as well: a reader cannot tell an observation
                        # from a benchmark by the number alone.
                        live_mark = ' · <span style="color:#9a3412; font-weight:700;">🟠 observed earlier, not live</span>'
                    else:
                        live_mark = ''
                    out.append('<div style="margin-top:4px; color:#475569;">' + badge + ' ' + delta_str + ' → £' + f'{up.total_package_price_gbp:,.0f}' + ' total · ' + escape(up.airline.split('/')[0].strip()) + live_mark + '</div>')
                out.append('</div>')
            # PACKAGE VENDORS + SELF-CREATE. The card used to end in four
            # generic links, two of which were Booking.com searches: a package
            # report that could not be used to buy a package. One link per
            # operator, each carrying the real search, then the same week
            # priced as its separate parts.
            out.append(render_vendor_block(deal, adults=config.travellers, rooms=config.rooms))
            out.append(render_diy_block(deal, adults=config.travellers))
            # ROOM-ONLY metasearch, demoted. These were the card's headline
            # buttons and they are hotel searches, not package purchases —
            # which is precisely why the e-mail was useless for buying a
            # package. They stay because a room price is a useful cross-check
            # on the self-create total above, and they now say so. The old
            # "flights only", "Resort direct" and destination-guide links are
            # gone: the self-create block links the airline and the hotel
            # itself, and the operator row links the operators.
            out.append('<div style="margin:4px 0 0;font-size:12px;color:#64748b;">Room only, your dates: ')
            out.append('<a href="' + escape(deal.booking_deep_url, quote=True) + '" style="color:#2563eb;text-decoration:none;font-weight:600;">Booking.com ↗</a>')
            out.append('<span style="color:#cbd5e1;"> · </span>')
            out.append('<a href="' + escape(deal.expedia_deep_url, quote=True) + '" style="color:#2563eb;text-decoration:none;">Expedia ↗</a>')
            out.append('<span style="color:#cbd5e1;"> · </span>')
            out.append('<a href="' + escape(deal.compare_url, quote=True) + '" style="color:#2563eb;text-decoration:none;">compare room prices ↗</a>')
            out.append('</div>')
            # The card's last line: the age of the numbers above it (F4).
            out.append(prices_checked_footer(deal, generated_at=generated_at))
            out.append('</td>')
            out.append('</tr></table>')

            # The card is written. Now weigh the e-mail that would ship with it
            # and take it back out if that breaks the budget — MIN_RENDERED
            # cards excepted, because a budget must never produce a one-card
            # report. The closing tail is reserved so the notice explaining the
            # cut is not itself what crosses the cap.
            if (
                len(rendered_hotels) > MIN_RENDERED_HOTEL_CARDS
                and _shipped_bytes(out) + _CLOSING_TAIL_ALLOWANCE_BYTES
                > EMAIL_HTML_BUDGET_BYTES
            ):
                del out[card_start:]
                rendered_hotels.pop()
                # This card and every card after it lost the budget race.
                size_dropped = len(hotels[:10]) - index
                break

        if len(hotels) > len(rendered_hotels):
            out.append('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; margin:10px 0 16px 0;"><tr><td align="center" style="padding:10px; color:#64748b; font-size:13px;">')
            out.append('Showing top ' + str(len(rendered_hotels)) + ' hotels of ' + str(len(hotels)) + ' under budget — one card per hotel, cheapest cabin as the baseline, all ' + str(len(ordered)) + ' cabin options tracked in price history.')
            # Say WHY the tail is missing, and how much of it. Only when the
            # BYTE BUDGET is what cut it — the 10-hotel cap is a choice about
            # how long an e-mail should be, and calling that "size limit" would
            # blame the wrong cause. A reader who cannot tell a size cut from a
            # quality filter has no way to know whether the resort they are
            # missing was the good one.
            if size_dropped:
                out.append(
                    f'<div style="margin-top:6px; color:#b45309;">'
                    f"{size_dropped} more deal{'' if size_dropped == 1 else 's'} "
                    f"not shown: size limit — this e-mail is near Gmail's "
                    f"{EMAIL_HTML_BUDGET_BYTES // 1000} KB payload cap, so "
                    f"richer cards win the space, not cheaper resorts.</div>"
                )
            out.append('</td></tr></table>')

    if not deals:
        out.append('<h2 style="margin:0 0 12px 0; color:#0f172a; font-size:22px; font-weight:800;">Package Deal Search Links</h2>')
        
        adults = config.travellers
        rooms = len(config.rooms)
        
        for dest in config.destinations:
            out.append('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; margin:12px 0;">')
            out.append('<tr style="background:#0f172a;"><td colspan="2" style="padding:10px 12px; color:#f8fafc; font-size:16px; font-weight:700;">')
            out.append(escape(dest.label))
            out.append('</td></tr>')
            out.append('<tr style="background:#f8fafc;"><td colspan="2" style="padding:8px 12px; color:#475569; font-size:14px;">')
            out.append('From: ' + escape(', '.join(config.origins)) + ' · destination airports: ' + escape(', '.join(dest.airports)))
            out.append(' · ' + str(adults) + ' travellers · room occupancy ' + escape(room_occupancy))
            out.append('</td></tr>')
            out.append('<tr style="background:#eff6ff;"><td colspan="2" style="padding:6px 12px; color:#1d4ed8; font-size:13px; font-weight:600;">All Inclusive · Half Board · Full Board · Room Only</td></tr>')
            
            # ── TOP PICKS: 3 representative date pairs with DYNAMIC buttons ──
            # Each pair encodes exact dates + party (Booking/Expedia/Google),
            # so links open dated results instead of static homepages. Package
            # hubs (which cannot encode dates) render once below to stay under
            # Gmail's 102 KB clipping limit.
            out.append('<tr><td colspan="2" style="padding:12px 12px 4px; color:#b45309; font-size:14px; font-weight:700;">')
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
                out.append('<span style="color:#f8fafc; font-size:14px; font-weight:600; margin-right:8px;">')
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
            out.append('<tr><td colspan="2" style="padding:10px 12px 4px; color:#64748b; font-size:14px; font-weight:600; border-top:1px solid #1e293b;">')
            out.append('Package entry points — enter any listed outbound/return pair on the provider site')
            out.append('</td></tr>')
            out.append('<tr><td colspan="2" style="padding:4px 10px 10px;">')
            out.append('<div style="margin-bottom:4px;"><span style="color:#94a3b8; font-size:12px;">')
            out.append(escape(', '.join(outbound + '→' + returning for outbound, returning in priced_pairs)))
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
        out.append('<tr><td style="padding:14px; background:#fef3c7; border-radius:6px; color:#78350f; font-size:14px; line-height:1.5;">')
        out.append('<strong style="color:#92400e;">⚠ No live prices collected</strong> — these are provider search entry points, not verified checkout deep links. Some providers accept only the first departure airport or room count in a URL. Reapply every origin option, the exact room occupancy <strong>' + escape(room_occupancy) + '</strong>, preferred departure time, board basis, baggage and transfers before relying on a result. Verify the final whole-party checkout total and protection before booking.')
        out.append('</td></tr></table>')
    out.append('</td></tr></table>')
    out.append('</td></tr></table></body></html>')
    
    return _hoist_repeated_styles(''.join(out))
