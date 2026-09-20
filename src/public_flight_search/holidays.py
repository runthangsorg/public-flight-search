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
from .live_verify import LiveFareEvidence


@dataclass(frozen=True)
class HolidayDestination:
    key: str
    label: str
    airports: tuple[str, ...]
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
}

# Destination airport per holiday key (for Google Flights parametric links).
HOLIDAY_AIRPORTS: dict[str, str] = {
    "antalya": "AYT", "malta": "MLA", "taghazout": "AGA",
    "hurghada": "HRG", "cairo": "CAI", "muscat": "MCT",
    "doha": "DOH", "tenerife": "TFS", "madeira": "FNC",
    "lanzarote": "ACE", "cape_verde": "SID",
    "fuerteventura": "FUE", "gran_canaria": "LPA", "paphos": "PFO",
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
    from .google_flights import build_google_flights_roundtrip_url

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


def load_holiday_config(payload: str) -> HolidayConfig:
    try:
        raw = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ConfigError("holiday configuration is not valid JSON") from exc
    allowed = {
        "report_title", "party", "departure_window", "origins",
        "outbound_dates", "return_dates", "destinations",
        "cabin_class", "cabin_classes", "max_budget_gbp",
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

    valid_cabins = {"ECONOMY", "PREMIUM_ECONOMY", "BUSINESS", "FIRST"}
    root_cabin = str(raw.get("cabin_class", "ECONOMY")).upper()
    if root_cabin not in valid_cabins:
        raise ConfigError(f"unsupported cabin_class: {root_cabin}")

    root_cabins_raw = raw.get("cabin_classes")
    if root_cabins_raw is not None:
        if not isinstance(root_cabins_raw, list) or not root_cabins_raw:
            raise ConfigError("cabin_classes must be a non-empty list")
        root_cabins = tuple(str(c).upper() for c in root_cabins_raw)
        for c in root_cabins:
            if c not in valid_cabins:
                raise ConfigError(f"unsupported cabin_class in cabin_classes: {c}")
    else:
        root_cabins = (root_cabin,)

    max_budget_raw = raw.get("max_budget_gbp", 5000.0)
    try:
        max_budget = float(max_budget_raw)
        if max_budget <= 0:
            raise ValueError
    except (ValueError, TypeError):
        raise ConfigError("max_budget_gbp must be a positive number")

    destination_raw = raw.get("destinations")
    dest_allowed = {"key", "label", "airports", "cabin_class", "cabin_classes"}
    if not isinstance(destination_raw, list) or not 1 <= len(destination_raw) <= 16:
        raise ConfigError("destinations must contain 1-16 entries")
    destinations = []
    for item in destination_raw:
        if not isinstance(item, dict) or set(item) - dest_allowed:
            continue
        dest_cabins_raw = item.get("cabin_classes")
        if dest_cabins_raw is not None:
            if not isinstance(dest_cabins_raw, list) or not dest_cabins_raw:
                raise ConfigError("destination cabin_classes must be a non-empty list")
            dest_cabins = tuple(str(c).upper() for c in dest_cabins_raw)
            for c in dest_cabins:
                if c not in valid_cabins:
                    raise ConfigError(f"unsupported destination cabin_class in cabin_classes: {c}")
            effective_dest_cabin = dest_cabins[0]
        else:
            dest_cabin = str(item.get("cabin_class", root_cabin)).upper()
            if dest_cabin not in valid_cabins:
                raise ConfigError(f"unsupported destination cabin_class: {dest_cabin}")
            dest_cabins = (dest_cabin,) if "cabin_class" in item else root_cabins
            effective_dest_cabin = dest_cabin

        destinations.append(
            HolidayDestination(
                key=_text(item.get("key"), "destination key", 48),
                label=_text(item.get("label"), "destination label"),
                airports=_airports(item.get("airports"), "destination airports"),
                cabin_class=effective_dest_cabin,
                cabin_classes=dest_cabins,
            )
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
        destinations=tuple(destinations),
        cabin_class=root_cabin,
        cabin_classes=root_cabins,
        max_budget_gbp=max_budget,
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
    source_url: str = ""
    # Real discount intelligence: the SAME resort at summer peak prices
    # (same rooms/nights/party) and property-level cross-vendor links.
    peak_summer_total_gbp: float = 0.0
    compare_url: str = ""   # Google Hotels property card — all vendors' prices
    booking_deep_url: str = ""  # Booking.com property-targeted, dated
    expedia_deep_url: str = ""  # Expedia property-targeted, dated
    # Room architecture of THIS quote. A 2-bed family suite and 3 separate
    # rooms are different products: prices must never merge into one series.
    unit_architecture: str = ""
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
    indoor_activity_count: int = 0
    heated_indoor_pool: bool = False
    deal_class: str = ""
    # Rank position by the winter-first value score within the LAST collect
    # run (1 = best). Gives history a stable, score-derived ordinal so trend
    # deltas read "rose/fell in value rank", never just raw price wobble.
    rank_value: int = 0

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
) -> float:
    """0-100 winter-first value score (weights from the original tracker)."""
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
    value = (
        price_score * 3.0
        + winter * 2.5
        + luxury * 1.5
        + food * 1.5
        + mosque * 1.0
        + activities * 0.5
    ) - flight_penalty
    return round(max(0.0, min(100.0, value)), 1)


# December climate reality (ambient air / sea °C) plus beach geography.
# Peak-summer room/flight benchmarks above each resort enable REAL discount
# intelligence: December total vs the SAME resort in July/August (same rooms,
# nights, party). Rates are market-supported benchmarks, never live quotes.
# Curated 0-10 criteria scores follow the winter-tracker contract: luxury,
# food reality, mosque access, winter facilities, activities, flight quality.
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
            "peak_summer_nightly_room_rate_gbp": 260.0,
            "airport": "AYT",
            "airline": "SunExpress / Pegasus",
            "flight_benchmark_5pax_gbp": 648.0,
            "peak_summer_flight_5pax_gbp": 1180.0,
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
            "hotel_url": "https://www.titanic.com.tr/titanic-mardan-palace",
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
            "hotel_url": "https://www.marriott.com/en-us/brands/sheraton-hotels/",
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
            "hotel_url": "https://www.elysiumhotel.com/",
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
}


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
}


def filter_resorts(resorts: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[tuple[str, str]]]:
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
        if not arch["beach_walkable"]:
            dropped.append((name, "no genuine walkable private beach attached"))
            continue
        if arch["pool_heated_c"] < 28:
            dropped.append((name, f"pools not heated to >=28°C in December ({arch['pool_heated_c']}°C)"))
            continue
        if arch["tripadvisor"] < 4.5:
            dropped.append((name, f"TripAdvisor {arch['tripadvisor']} < 4.5"))
            continue
        kept.append(resort)
    return kept, dropped


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


def _criteria_fields(resort_name: str, true_pp: float) -> dict[str, Any]:
    """Criteria bundle for one resort from the recovered registry (defaults
    keep any un-registered resort renderable with neutral scores)."""
    c = RESORT_CRITERIA.get(resort_name, {})
    indoor = int(c.get("indoor", 2))
    heated = bool(c.get("heated_indoor_pool", False))
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
    )
    return {
        "actual_luxury_score": float(c.get("luxury", 5)),
        "food_reality_score": float(c.get("food", 5)),
        "winter_facilities_score": float(c.get("winter", 5)),
        "mosque_location_score": float(c.get("mosque", 5)),
        "activities_score": float(c.get("activities", 5)),
        "flight_quality_score": float(c.get("flight_quality", 7)),
        "value_score": value,
        "mosque_name": c.get("mosque_name", ""),
        "mosque_walk_minutes": int(c.get("mosque_walk_minutes", 0)),
        "food_review_summary": c.get("food_review_summary", ""),
        "indoor_activity_count": indoor,
        "heated_indoor_pool": heated,
        "deal_class": _classify_deal_price(true_pp),
    }


def collect_holiday_deals(
    config: HolidayConfig,
    max_budget_gbp: Optional[float] = None,
    live_flight_offers: Optional[Mapping[str, LiveFareEvidence]] = None,
) -> tuple[PackageDeal, ...]:
    """Calculate holiday packages, enforcing the budget on BOTH the package
    total (flights + hotel) AND the True D2D total (package + UK ground +
    destination transfer). Anything over budget on either measure is dropped —
    never labelled "under budget" while breaching the ceiling."""
    if max_budget_gbp is None:
        max_budget_gbp = getattr(config, "max_budget_gbp", 5000.0)
    pairs = _date_pairs(config)
    shortlist = _shortlist_pairs(pairs)
    deals: list[PackageDeal] = []
    filtered_out: list[tuple[str, str]] = []
    rooms_count = len(config.rooms)
    travellers = config.travellers
    # STRICT mode: one family unit (2-bed suite/duplex/interconnecting), NOT
    # 3 separate rooms. One premium unit prices FAR below 3 rooms.
    strict_unit = len(config.rooms) >= 3

    target_outbound, target_return = (
        shortlist[len(shortlist) // 2] if shortlist else ("2026-12-22", "2026-12-30")
    )
    dep_dt = datetime.strptime(target_outbound, "%Y-%m-%d")
    ret_dt = datetime.strptime(target_return, "%Y-%m-%d")
    nights = (ret_dt - dep_dt).days
    uk_ground = UK_GROUND_RETURN_GBP.get(config.origins[0], 16.50)

    cabin_multipliers = {
        "ECONOMY": 1.0,
        "PREMIUM_ECONOMY": 1.6,
        "BUSINESS": 2.5,
        "FIRST": 4.5,
    }

    for dest in config.destinations:
        resorts, dropped = filter_resorts(WINTER_RESORT_CATALOG.get(dest.key.lower(), []))
        filtered_out.extend(dropped)
        dest_cabins = getattr(dest, "cabin_classes", ()) or (getattr(dest, "cabin_class", "") or getattr(config, "cabin_class", "ECONOMY"),)
        for cabin in dest_cabins:
            flight_mult = cabin_multipliers.get(cabin.upper(), 1.0)
            for resort in resorts:
                airport = resort["airport"]
                flight_cost = round(resort["flight_benchmark_5pax_gbp"] * flight_mult, 2)
                # Luxury cabin displays a carrier that actually sells that cabin.
                # Never present SunExpress/Ryanair/easyJet/Jet2 as "Business".
                display_airline = cabin_carrier(
                    airport=airport, cabin=cabin, economy_carrier=resort["airline"]
                )
                # Live evidence must be a WHOLE-PARTY, exact-date amount to be
                # used at all. A per-person figure is never multiplied up into
                # a party total: deriving one and stamping it verified was the
                # bug this guard exists to make unrepeatable.
                evidence = live_flight_offers.get(airport) if live_flight_offers else None
                live_used = bool(evidence is not None and evidence.promotable)
                if live_used and evidence is not None:
                    flight_cost = evidence.total_gbp
                flight_basis = (
                    evidence.basis
                    if (live_used and evidence is not None)
                    else ("benchmark_supplied" if cabin.upper() == "ECONOMY" else f"benchmark_supplied_{cabin.lower()}")
                )

                # ONE family unit pricing (strict mandate) with suite premium.
                arch = SUITE_ARCHITECTURE[resort["name"]]
                hotel_cost = round(arch["suite_nightly_gbp"] * nights, 2)
                total_pkg = round(flight_cost + hotel_cost, 2)
                price_pp = round(total_pkg / travellers, 2)
                transfer = float(resort.get("transfer_gbp", 30.0))
                true_d2d = round(total_pkg + uk_ground + transfer, 2)
                # REAL discount baseline: the SAME suite, same nights/party, at
                # the resort's summer peak (Jul/Aug school-holiday highs), in the
                # SAME cabin so a Business December total is compared against a
                # Business peak total — never against an Economy peak.
                peak_hotel = round(arch["suite_peak_nightly_gbp"] * nights, 2)
                peak_flight = round(resort["peak_summer_flight_5pax_gbp"] * flight_mult, 2)
                peak_total = round(peak_flight + peak_hotel, 2)
                # STRICT: both measures must clear the ceiling.
                under_budget = total_pkg <= max_budget_gbp and true_d2d <= max_budget_gbp

                if under_budget:
                    flight_link = build_google_flights_roundtrip_url(
                        origin=config.origins[0],
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
                            board_basis=resort["board"],
                            outbound_date=target_outbound,
                            return_date=target_return,
                            nights=nights,
                            airline=display_airline,
                            origin_airports=config.origins,
                            destination_airport=airport,
                            flight_price_total_gbp=flight_cost,
                            flight_price_basis=flight_basis,
                            cabin_class=cabin,
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
                                evidence.source_url
                                if (live_used and evidence is not None)
                                else resort.get("hotel_url", "")
                            ),
                            peak_summer_total_gbp=peak_total,
                            unit_architecture=arch["suite_type"],
                            **_criteria_fields(resort["name"], price_pp),
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

    deals.sort(key=lambda d: (-d.vs_peak_pct, -d.value_score, d.total_package_price_gbp))
    # Stamp the value-score rank (1 = best) so history tracks movement in the
    # composite ranking, not just raw price wobble.
    for rank, deal in enumerate(sorted(deals, key=lambda d: -d.value_score), 1):
        object.__setattr__(deal, "rank_value", rank)
    # Attach the transparency list (filtered resorts + reasons) to the first
    # caller via module-level export for the renderer; the function returns
    # deals only (signature stability for tests/CLI), so stash on the tuple's
    # companion attribute pattern: a module global consumed by the renderer.
    global LAST_FILTERED_OUT
    LAST_FILTERED_OUT = tuple(filtered_out)
    return tuple(deals)


#: Resorts filtered out by the strict parameters in the last collect run,
#: with human-readable reasons (rendered in the email's transparency note).
LAST_FILTERED_OUT: tuple[tuple[str, str], ...] = ()


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
    """Split deals into the reader decision lenses.

    discounts: REAL discount lens — biggest % below the same resort's
               summer-peak price first; ties break on the winter-first value
               score (a bigger % off a miserable-winter property is not the
               better deal), then cheapest absolute total.
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
            sorted(ordered, key=lambda d: (-d.vs_peak_pct, -d.value_score, d.total_package_price_gbp))),
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
    change_digest_html: str = "",
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
    out.append(' valid date combinations</p>')
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

    # ── VERIFIED LIVE DEALS UNDER £5,000 (WHEN AVAILABLE) ──
    if deals:
        out.append('<h2 style="margin:22px 0 4px 0; color:#0f172a; font-size:24px; font-weight:800;">⭐ December Deals — One Family Unit, Real Discounts vs Summer Peak</h2>')
        out.append('<p style="margin:0 0 10px 0; color:#475569; font-size:15px;">Every resort sleeps all 5 in <strong>ONE booking</strong> (2-bedroom suite, duplex, or 2× guaranteed-connecting rooms where the hotel confirms the connection post-booking). Pools heated ≥28°C, walkable beach, TripAdvisor ≥4.5, nonstop flights, any departure time. Ranked by how much cheaper the same stay is in December versus its July/August peak.</p>')
        # At-a-glance: one line per decision lens (no ranked walls).
        buckets = bucket_deals(deals)
        glance = '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; background:#ffffff; border:1px solid #e2e8f0; border-radius:8px; margin:0 0 16px 0;">'
        b1 = buckets["discounts"][0] if buckets["discounts"] else None
        b2 = buckets["luxury"][0] if buckets["luxury"] else None
        b3 = buckets["winter"][0] if buckets["winter"] else None
        if b1 is not None:
            glance += ('<tr><td style="padding:9px 12px; color:#475569; font-size:14px; border-bottom:1px solid #f1f5f9;">'
                       '<strong style="color:#0f172a;">💰 Biggest Discount vs Summer Peak:</strong> '
                       + escape(b1.resort_name) + ' — <strong style="color:#059669;">▼' + str(b1.vs_peak_pct) + '% (save £' + f'{b1.vs_peak_saving_gbp:,.0f}' + ' for the same resort)</strong></td></tr>')
        if b2 is not None:
            glance += ('<tr><td style="padding:9px 12px; color:#475569; font-size:14px; border-bottom:1px solid #f1f5f9;">'
                       '<strong style="color:#0f172a;">💎 Top Luxury Within £5k:</strong> '
                       + escape(b2.resort_name) + ' · ' + escape(b2.board_basis) + '</td></tr>')
        if b3 is not None:
            glance += ('<tr><td style="padding:9px 12px; color:#475569; font-size:14px; border-bottom:1px solid #f1f5f9;">'
                       '<strong style="color:#0f172a;">☀️ Best Winter Facilities:</strong> '
                       + escape(b3.resort_name) + ' — ' + str(b3.dec_ambient_c[0]) + '–' + str(b3.dec_ambient_c[1]) + '°C air, sea ' + str(b3.sea_temp_c) + '°C</td></tr>')
        b4 = buckets["value"][0] if buckets["value"] else None
        if b4 is not None:
            glance += ('<tr><td style="padding:9px 12px; color:#475569; font-size:14px;">'
                       '<strong style="color:#0f172a;">🏆 Best Overall Value:</strong> '
                       + escape(b4.resort_name) + ' — VALUE ' + f'{b4.value_score:.0f}' + '/100 (winter-first score)</td></tr>')
        glance += '</table>'
        out.append(glance)

        # Chips align with the caller's `deals` order; index them by resort
        # name so the card order below (cheapest first) stays correct.
        chip_by_resort = {}
        if history_chips is not None:
            chip_by_resort = {d.resort_name: history_chips[i] for i, d in enumerate(deals) if i < len(history_chips)}

        rooms_n = len(config.rooms)
        ordered = sorted(deals, key=lambda d: d.total_package_price_gbp)
        # Gmail clips emails over 102 KB. Cap rendered cards to top 10 to keep
        # HTML payload strictly under 70 KB while all deals are tracked in history.
        rendered_deals = ordered[:10]
        for deal in rendered_deals:
            stars_str = '★' * deal.star_rating + '☆' * (5 - deal.star_rating)
            img = DEST_IMAGES.get(deal.destination_key.lower(), DEST_IMAGES["hurghada"])
            live = deal.confidence == 'verified-exact-date'
            under = 5000.0 - deal.total_package_price_gbp
            out.append('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:separate; border-spacing:0; margin:0 0 14px 0; background:#ffffff; border:1px solid #e2e8f0; border-radius:12px; overflow:hidden;">')
            out.append('<tr>')
            # Left: destination photo (hotel-specific photos are not on free CDNs)
            out.append('<td width="260" valign="top" style="padding:0; line-height:0;">')
            out.append('<img src="' + escape(img, quote=True) + '" alt="' + escape(deal.destination_key) + '" width="260" height="208" style="width:260px; height:208px; object-fit:cover; display:block; border-radius:11px 0 0 11px;">')
            out.append('</td>')
            # Right: everything a booker needs, scannable in one glance
            out.append('<td valign="top" style="padding:16px 20px;">')
            out.append('<div style="margin-bottom:3px;"><strong style="color:#0f172a; font-size:20px;">' + escape(deal.resort_name) + '</strong> <span style="color:#f59e0b; font-size:14px;">' + stars_str + '</span></div>')
            cabin_badge = ""
            cabin_is_premium = getattr(deal, "cabin_class", "ECONOMY") in ("BUSINESS", "FIRST", "PREMIUM_ECONOMY")
            if getattr(deal, "cabin_class", "") == "BUSINESS":
                cabin_badge = '<span style="background:#fdf2f8; color:#9d174d; padding:3px 10px; border-radius:9999px; font-size:13px; font-weight:700;">💼 Business Class' + ('' if live else ' (estimate)') + '</span> '
            elif getattr(deal, "cabin_class", "") == "PREMIUM_ECONOMY":
                cabin_badge = '<span style="background:#f0fdfa; color:#0f766e; padding:3px 10px; border-radius:9999px; font-size:13px; font-weight:700;">✨ Premium Economy' + ('' if live else ' (estimate)') + '</span> '
            elif getattr(deal, "cabin_class", "") == "FIRST":
                cabin_badge = '<span style="background:#fdf2f8; color:#9d174d; padding:3px 10px; border-radius:9999px; font-size:13px; font-weight:700;">🥇 First Class' + ('' if live else ' (estimate)') + '</span> '
            out.append('<div style="margin:5px 0 7px;">')
            out.append(cabin_badge)
            out.append('<span style="background:#eff6ff; color:#1d4ed8; padding:3px 10px; border-radius:9999px; font-size:13px; font-weight:700;">' + escape(deal.board_basis) + '</span> ')
            out.append('<span style="background:' + ('#dcfce7' if live else '#fef3c7') + '; color:' + ('#166534' if live else '#92400e') + '; padding:3px 10px; border-radius:9999px; font-size:13px; font-weight:700;">' + ('🟢 LIVE VERIFIED' if live else '🟡 BENCHMARK PRICE') + '</span> ')
            out.append('<span style="background:#16a34a; color:#ffffff; padding:3px 10px; border-radius:9999px; font-size:13px; font-weight:800;">▼' + str(deal.vs_peak_pct) + '% vs summer peak · save £' + f'{deal.vs_peak_saving_gbp:,.0f}' + '</span>')
            history_chip = chip_by_resort.get(deal.resort_name, '')
            if history_chip:
                out.append(' ' + history_chip)
            out.append('</div>')
            out.append('<div style="color:#64748b; font-size:14px; margin-bottom:7px;">📍 ' + escape(deal.destination_label) + ' (' + escape(deal.destination_airport) + ') · ' + escape(deal.outbound_date) + ' → ' + escape(deal.return_date) + ' · ' + str(deal.nights) + ' nights</div>')
            if deal.highlights:
                out.append('<div style="color:#475569; font-size:14px; margin-bottom:8px;">✨ ' + escape(' · '.join(deal.highlights)) + '</div>')
            # Recovered criteria strip: value score, deal class, and the
            # 0-10 scores that matter to this household (mosque, food first).
            crit = ('🕌 ' + escape(deal.mosque_name) + ' — ' + str(deal.mosque_walk_minutes) + ' min walk'
                    if deal.mosque_name else '🕌 mosque access not assessed')
            out.append('<div style="color:#334155; font-size:14px; margin-bottom:4px;"><strong style="color:#7c3aed;">VALUE ' + f'{deal.value_score:.0f}' + '/100</strong> · '
                       + '<span style="background:#faf5ff; color:#6d28d9; padding:2px 8px; border-radius:6px; font-size:12px; font-weight:700;">' + escape(deal.deal_class.replace('_', ' ')) + '</span></div>')
            out.append('<div style="color:#334155; font-size:14px; margin-bottom:4px;">' + crit + ' · 🍽️ food ' + f'{deal.food_reality_score:.0f}' + '/10 · 💎 luxury ' + f'{deal.actual_luxury_score:.0f}' + '/10 · ❄️ winter ' + f'{deal.winter_facilities_score:.0f}' + '/10 · 🎯 activities ' + f'{deal.activities_score:.0f}' + '/10 · ✈️ flights ' + f'{deal.flight_quality_score:.0f}' + '/10</div>')
            if deal.food_review_summary:
                out.append('<div style="color:#64748b; font-size:13px; margin-bottom:8px;"><strong style="color:#475569;">Food reviews:</strong> ' + escape(deal.food_review_summary) + '</div>')
            # Facts strip: flights | stay | December weather | BIG price
            cabin_label = f" ({deal.cabin_class.replace('_', ' ').title()})" if getattr(deal, "cabin_class", "ECONOMY") != "ECONOMY" else ""
            # Premium cabins name a real business-capable carrier in full —
            # never truncate to an LCC fragment. Benchmark estimates carry an
            # explicit live-check note; only verified-exact-date is a live fare.
            flight_carrier_display = escape(deal.airline) if cabin_is_premium else escape(deal.airline.split('/')[0].strip())
            flight_note = "" if live else ("<br><span style=\"font-size:11px;\">estimate — live cabin check required</span>" if cabin_is_premium else "")
            out.append('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; background:#f8fafc; border-radius:8px; margin-bottom:10px;"><tr>')
            out.append('<td style="padding:10px 12px; color:#64748b; font-size:13px;">✈️ Flights' + cabin_label + '<br><strong style="color:#0f172a; font-size:16px;">£' + f'{deal.flight_price_total_gbp:,.0f}' + '</strong><br><span style="font-size:12px;">' + flight_carrier_display + '</span>' + flight_note + '</td>')
            suite_label = deal.unit_architecture or (str(rooms_n) + ' rooms')
            out.append('<td style="padding:10px 12px; color:#64748b; font-size:13px; border-left:1px solid #e2e8f0;">🏨 Stay<br><strong style="color:#0f172a; font-size:16px;">£' + f'{deal.hotel_price_total_gbp:,.0f}' + '</strong><br><span style="font-size:12px;">' + escape(suite_label) + ' · ' + str(deal.nights) + 'n</span></td>')
            if deal.sea_temp_c:
                out.append('<td style="padding:10px 12px; color:#64748b; font-size:13px; border-left:1px solid #e2e8f0;">🌡️ December<br><strong style="color:#0f172a; font-size:16px;">' + str(deal.dec_ambient_c[0]) + '–' + str(deal.dec_ambient_c[1]) + '°C</strong><br><span style="font-size:12px;">sea ' + str(deal.sea_temp_c) + '°C</span></td>')
            else:
                out.append('<td style="padding:10px 12px; color:#64748b; font-size:13px; border-left:1px solid #e2e8f0;">🌡️ December<br><strong style="color:#0f172a; font-size:16px;">' + str(deal.dec_ambient_c[0]) + '–' + str(deal.dec_ambient_c[1]) + '°C</strong><br><span style="font-size:12px;">city stay, no sea swimming</span></td>')
            out.append('<td align="right" valign="middle" style="padding:8px 10px;">')
            out.append('<div style="color:#059669; font-size:30px; font-weight:800; white-space:nowrap;">£' + f'{deal.total_package_price_gbp:,.0f}' + '</div>')
            out.append('<div style="color:#64748b; font-size:13px; white-space:nowrap;">£' + f'{deal.price_per_person_gbp:,.0f}' + 'pp · D2D £' + f'{deal.true_d2d_gbp:,.0f}' + '</div>')
            out.append('<div style="color:#b45309; font-size:12px; white-space:nowrap;">summer peak £' + f'{deal.peak_summer_total_gbp:,.0f}' + '</div>')
            out.append('</td>')
            out.append('</tr></table>')
            # Property-targeted actions: book THIS hotel dated, or compare
            # every vendor's price for it on one card.
            out.append('<a href="' + escape(deal.booking_deep_url, quote=True) + '" style="background:#2563eb; color:#ffffff; text-decoration:none; padding:12px 22px; border-radius:8px; font-weight:700; font-size:15px; display:inline-block;">Book this hotel, your dates →</a>')
            out.append(' ') 
            out.append('<a href="' + escape(deal.compare_url, quote=True) + '" style="' + btn_compare + '">Compare all vendors →</a>')
            out.append('<div style="margin-top:6px;">')
            out.append('<a href="' + escape(deal.flight_booking_url, quote=True) + '" style="color:#2563eb; font-size:14px; text-decoration:none; font-weight:600;">flights only</a>')
            out.append('<span style="color:#cbd5e1;"> · </span>')
            out.append('<a href="' + escape(deal.expedia_deep_url, quote=True) + '" style="color:#2563eb; font-size:14px; text-decoration:none;">Expedia</a>')
            out.append('<span style="color:#cbd5e1;"> · </span>')
            out.append('<a href="' + escape(deal.hotel_booking_url, quote=True) + '" style="color:#2563eb; font-size:14px; text-decoration:none;">Resort direct</a>')
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
            out.append('<a href="' + escape(guide_url, quote=True) + '" style="color:#2563eb; font-size:14px; text-decoration:none;">' + guide_label + '</a>')
            out.append('</td>')
            out.append('</tr></table>')

        if len(ordered) > len(rendered_deals):
            out.append('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; margin:10px 0 16px 0;"><tr><td align="center" style="padding:10px; color:#64748b; font-size:13px;">')
            out.append('Showing top ' + str(len(rendered_deals)) + ' of ' + str(len(ordered)) + ' packages under budget (ranked by total price). All observations tracked in price history.')
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
        out.append('<tr><td style="padding:14px; background:#fef3c7; border-radius:6px; color:#78350f; font-size:14px; line-height:1.5;">')
        out.append('<strong style="color:#92400e;">⚠ No live prices collected</strong> — these are provider search entry points, not verified checkout deep links. Some providers accept only the first departure airport or room count in a URL. Reapply every origin option, the exact room occupancy <strong>' + escape(room_occupancy) + '</strong>, preferred departure time, board basis, baggage and transfers before relying on a result. Verify the final whole-party checkout total and protection before booking.')
        out.append('</td></tr></table>')
    out.append('</td></tr></table>')
    out.append('</td></tr></table></body></html>')
    
    return ''.join(out)
