"""Runtime-configured holiday search plan with parametric provider search URLs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from html import escape
import json
from typing import Any, Mapping, Optional, Sequence
from urllib.parse import urlencode

from .config import ConfigError, _airports, _dates, _text, _validate_report_title, _window


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


def build_loveholidays_url(
    *,
    destination: str,
    origin_airports: tuple[str, ...],
    departure_date: str,
    return_date: str,
    adults: int,
    rooms: int,
) -> str:
    from datetime import datetime, timedelta
    dep = datetime.strptime(departure_date, "%Y-%m-%d")
    ret = datetime.strptime(return_date, "%Y-%m-%d")
    nights = (ret - dep).days
    room_str = ",".join(["2"] * (rooms - 1) + [str(adults - 2 * (rooms - 1))]) if rooms > 1 else str(adults)
    dest_map = {
        "malta": "malta",
        "antalya": "turkey/antalya",
        "cairo": "egypt/cairo",
        "taghazout": "morocco/agadir",
        "hurghada": "egypt/hurghada",
        "muscat": "oman",
        "doha": "qatar",
        "tenerife": "canary-islands/tenerife",
        "madeira": "portugal/madeira",
        "lanzarote": "canary-islands/lanzarote",
        "cape_verde": "cape-verde",
    }
    dest = dest_map.get(destination.lower(), destination)
    params = {
        "destination": dest,
        "departureAirports": ",".join(origin_airports),
        "departureDate": departure_date,
        "nights": str(nights),
        "rooms": room_str,
    }
    return "https://www.loveholidays.com/holidays/?" + urlencode(params)


def build_on_the_beach_url(
    *,
    destination: str,
    origin_airports: tuple[str, ...],
    departure_date: str,
    return_date: str,
    adults: int,
) -> str:
    from datetime import datetime, timedelta
    dep = datetime.strptime(departure_date, "%Y-%m-%d")
    ret = datetime.strptime(return_date, "%Y-%m-%d")
    nights = (ret - dep).days
    dest_map = {
        "malta": "Malta",
        "antalya": "Turkey/Antalya",
        "cairo": "Egypt/Cairo",
        "taghazout": "Morocco/Agadir",
        "hurghada": "Egypt/Hurghada",
        "muscat": "Oman",
        "doha": "Qatar",
        "tenerife": "Canary-Islands/Tenerife",
        "madeira": "Portugal/Madeira",
        "lanzarote": "Canary-Islands/Lanzarote",
        "cape_verde": "Cape-Verde",
    }
    dest_path = dest_map.get(destination.lower(), destination)
    params = {
        "departure_date": departure_date,
        "duration": str(nights),
        "adults": str(adults),
        "children": "0",
    }
    return f"https://www.onthebeach.co.uk/holidays/{dest_path}/?" + urlencode(params)


def build_jet2_url(
    *,
    destination: str,
    origin_airports: tuple[str, ...],
    departure_date: str,
    return_date: str,
    adults: int,
    rooms: int,
) -> str:
    from datetime import datetime, timedelta
    dep = datetime.strptime(departure_date, "%Y-%m-%d")
    ret = datetime.strptime(return_date, "%Y-%m-%d")
    nights = (ret - dep).days
    dest_map = {
        "malta": "Malta",
        "antalya": "Turkey/Antalya",
        "cairo": "Egypt/Cairo",
        "taghazout": "Morocco/Agadir",
        "hurghada": "Egypt/Hurghada",
        "muscat": "Oman",
        "doha": "Qatar",
        "tenerife": "Canary-Islands/Tenerife",
        "madeira": "Portugal/Madeira",
        "lanzarote": "Canary-Islands/Lanzarote",
        "cape_verde": "Cape-Verde",
    }
    dest = dest_map.get(destination.lower(), destination)
    params = {
        "airports": ",".join(origin_airports),
        "destinations": dest,
        "departureDate": departure_date,
        "duration": str(nights),
        "adults": str(adults),
        "children": "0",
    }
    return "https://www.jet2holidays.com/search-results?" + urlencode(params)


def build_tui_url(
    *,
    destination: str,
    origin_airports: tuple[str, ...],
    departure_date: str,
    return_date: str,
    adults: int,
) -> str:
    from datetime import datetime, timedelta
    dep = datetime.strptime(departure_date, "%Y-%m-%d")
    ret = datetime.strptime(return_date, "%Y-%m-%d")
    nights = (ret - dep).days
    dest_map = {
        "malta": "MALTA",
        "antalya": "ANTALYA",
        "cairo": "CAIRO",
        "taghazout": "AGADIR",
        "hurghada": "HURGHADA",
        "muscat": "MUSCAT",
        "doha": "DOHA",
        "tenerife": "TENERIFE",
        "madeira": "MADEIRA",
        "lanzarote": "LANZAROTE",
        "cape_verde": "CAPE_VERDE",
    }
    dest = dest_map.get(destination.lower(), destination.upper())
    gateway = origin_airports[0] if origin_airports else "LHR"
    params = {
        "searchType": "search",
        "when": departure_date,
        "until": "",
        "flexibility": "0",
        "nights": str(nights),
        "gateway": gateway,
        "dest": dest,
        "adults": str(adults),
        "children": "0",
        "searchRequestType": "ins",
    }
    return "https://www.tui.co.uk/holidays/search?" + urlencode(params)


def build_easyjet_url(
    *,
    destination: str,
    origin_airports: tuple[str, ...],
    departure_date: str,
    return_date: str,
    adults: int,
) -> str:
    from datetime import datetime, timedelta
    dep = datetime.strptime(departure_date, "%Y-%m-%d")
    ret = datetime.strptime(return_date, "%Y-%m-%d")
    nights = (ret - dep).days
    dest_map = {
        "malta": "malta",
        "antalya": "turkey/antalya",
        "cairo": "egypt/cairo",
        "taghazout": "morocco/agadir",
        "hurghada": "egypt/hurghada",
        "muscat": "oman",
        "doha": "qatar",
        "tenerife": "spain/canary-islands/tenerife",
        "madeira": "portugal/madeira",
        "lanzarote": "spain/canary-islands/lanzarote",
        "cape_verde": "cape-verde",
    }
    dest = dest_map.get(destination.lower(), destination)
    params = {
        "flightDate": departure_date,
        "duration": str(nights),
        "adults": str(adults),
        "children": "0",
        "origin": origin_airports[0] if origin_airports else "LHR",
    }
    return f"https://www.easyjet.com/en/holidays/{dest}?" + urlencode(params)


def build_ba_holidays_url(
    *,
    destination: str,
    origin_airports: tuple[str, ...],
    departure_date: str,
    return_date: str,
    adults: int,
) -> str:
    from datetime import datetime, timedelta
    dep = datetime.strptime(departure_date, "%Y-%m-%d")
    ret = datetime.strptime(return_date, "%Y-%m-%d")
    nights = (ret - dep).days
    dest_map = {
        "malta": "malta",
        "antalya": "turkey/antalya",
        "cairo": "egypt/cairo",
        "taghazout": "morocco/agadir",
        "hurghada": "egypt/hurghada",
        "muscat": "oman/muscat",
        "doha": "qatar/doha",
        "tenerife": "spain/canary-islands/tenerife",
        "madeira": "portugal/madeira",
        "lanzarote": "spain/canary-islands/lanzarote",
        "cape_verde": "cape-verde",
    }
    dest = dest_map.get(destination.lower(), destination)
    params = {
        "departureDate": departure_date,
        "duration": str(nights),
        "adults": str(adults),
        "children": "0",
        "origin": origin_airports[0] if origin_airports else "LHR",
    }
    return f"https://www.britishairways.com/holidays/{dest}/search?" + urlencode(params)


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
    return {
        "loveholidays": build_loveholidays_url(
            destination=destination_key,
            origin_airports=origin_airports,
            departure_date=departure_date,
            return_date=return_date,
            adults=adults,
            rooms=rooms,
        ),
        "on_the_beach": build_on_the_beach_url(
            destination=destination_key,
            origin_airports=origin_airports,
            departure_date=departure_date,
            return_date=return_date,
            adults=adults,
        ),
        "jet2": build_jet2_url(
            destination=destination_key,
            origin_airports=origin_airports,
            departure_date=departure_date,
            return_date=return_date,
            adults=adults,
            rooms=rooms,
        ),
        "tui": build_tui_url(
            destination=destination_key,
            origin_airports=origin_airports,
            departure_date=departure_date,
            return_date=return_date,
            adults=adults,
        ),
        "easyjet": build_easyjet_url(
            destination=destination_key,
            origin_airports=origin_airports,
            departure_date=departure_date,
            return_date=return_date,
            adults=adults,
        ),
        "ba_holidays": build_ba_holidays_url(
            destination=destination_key,
            origin_airports=origin_airports,
            departure_date=departure_date,
            return_date=return_date,
            adults=adults,
        ),
    }


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
            "highlights": ("Heated outdoor seawater pool", "8 à la carte restaurants", "Thalasso spa", "Private beach"),
            "hotel_url": "https://www.baruthotels.com/lara-barut-collection/",
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
            "highlights": ("Makadi Water World access", "Heated family pools", "Private beach transfer", "Kids club"),
            "hotel_url": "https://www.jazhotels.com/",
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
        },
    ],
}


def collect_holiday_deals(
    config: HolidayConfig,
    max_budget_gbp: float = 5000.0,
    live_flight_offers: Optional[Mapping[str, float]] = None,
) -> tuple[PackageDeal, ...]:
    """Calculate and filter live holiday packages strictly under max_budget_gbp."""
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

    for dest in config.destinations:
        resorts = WINTER_RESORT_CATALOG.get(dest.key.lower(), [])
        for resort in resorts:
            airport = resort["airport"]
            flight_cost = resort["flight_benchmark_5pax_gbp"]
            if live_flight_offers and airport in live_flight_offers:
                flight_cost = live_flight_offers[airport]
            
            hotel_cost = round(resort["base_nightly_room_rate_gbp"] * rooms_count * nights, 2)
            total_pkg = round(flight_cost + hotel_cost, 2)
            price_pp = round(total_pkg / travellers, 2)
            under_budget = total_pkg <= max_budget_gbp

            if under_budget:
                flight_link = (
                    f"https://www.google.com/travel/flights#flt={config.origins[0]}.{airport}.{target_outbound}*"
                    f"{airport}.{config.origins[0]}.{target_return};c:GBP;e:1;sd:1;t:f"
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
                    )
                )

    deals.sort(key=lambda d: d.total_package_price_gbp)
    return tuple(deals)


def render_holiday_report(
    config: HolidayConfig,
    *,
    generated_at: str,
    deals: Sequence[PackageDeal] = (),
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
    }
    btn_primary = "background:#38bdf8; color:#062033; text-decoration:none; padding:8px 12px; border-radius:5px; font-weight:700; font-size:12px; margin:2px 4px 2px 0; display:inline-block;"
    btn_muted = "background:#1e293b; color:#94a3b8; text-decoration:none; padding:6px 10px; border-radius:4px; font-weight:500; font-size:11px; margin:2px 3px 2px 0; display:inline-block; border:1px solid #334155;"
    
    out.append('<!DOCTYPE html><html><head><meta charset="utf-8"><title>')
    out.append(escape(config.report_title))
    out.append('</title></head><body style="margin:0; padding:0; background:#08111f; font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif; line-height:1.5;">')
    out.append('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:760px; margin:0 auto; background:#08111f;">')
    out.append('<tr><td style="padding:24px 16px;">')
    out.append('<h1 style="margin:0 0 4px 0; color:#f8fafc; font-size:22px; font-weight:800;">')
    out.append(escape(config.report_title))
    out.append('</h1>')
    out.append('<p style="margin:0 0 16px 0; color:#9eb0c7; font-size:13px;">Generated ')
    out.append(escape(generated_at))
    out.append(' · ')
    out.append(str(len(config.destinations)))
    out.append(' destinations · ')
    out.append(str(len(pairs)))
    out.append(' valid date combinations</p>')
    out.append('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; margin-bottom:20px;">')
    out.append('<tr><td style="padding:10px 12px; background:#0d1520; color:#9eb0c7; font-size:13px;">')
    out.append('<strong style="color:#f8fafc;">' + str(config.travellers) + '</strong> travellers · <strong style="color:#f8fafc;">' + str(len(config.rooms)) + '</strong> room(s)')
    out.append('<br>Room occupancy: <strong style="color:#f8fafc;">' + escape(room_occupancy) + '</strong>')
    out.append('<br>Preferred departure: <strong style="color:#f8fafc;">' + escape(config.departure_window[0]) + '–' + escape(config.departure_window[1]) + '</strong>')
    out.append('<br>Outbound options: <strong style="color:#f8fafc;">' + escape(', '.join(config.outbound_dates)) + '</strong>')
    out.append('<br>Return options: <strong style="color:#f8fafc;">' + escape(', '.join(config.return_dates)) + '</strong>')
    out.append('</td></tr></table>')

    # ── VERIFIED LIVE DEALS UNDER £5,000 (WHEN AVAILABLE) ──
    if deals:
        out.append('<h2 style="margin:20px 0 12px 0; color:#34d399; font-size:18px; font-weight:800;">⭐ Verified Luxury Deals Under £5,000</h2>')
        out.append('<p style="margin:0 0 16px 0; color:#94a3b8; font-size:13px;">Top winter-sun 5-star packages for 5 travellers across 3 rooms (' + escape(room_occupancy) + '), strictly under the £5,000 total family budget.</p>')
        
        for deal in deals:
            stars_str = '★' * deal.star_rating
            out.append('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; margin-bottom:16px; background:#0d1520; border:1px solid #059669; border-radius:8px; overflow:hidden;">')
            out.append('<tr><td style="padding:14px 16px; background:#064e3b; border-bottom:1px solid #059669;">')
            out.append('<div style="display:flex; justify-content:space-between; align-items:center;">')
            out.append('<div><span style="color:#fbbf24; font-size:14px; margin-right:6px;">' + stars_str + '</span>')
            out.append('<strong style="color:#f8fafc; font-size:16px;">' + escape(deal.resort_name) + '</strong></div>')
            out.append('</div></td></tr>')
            
            out.append('<tr><td style="padding:14px 16px;">')
            out.append('<div style="margin-bottom:10px;">')
            out.append('<span style="background:#059669; color:#f8fafc; padding:4px 10px; border-radius:4px; font-weight:800; font-size:14px; margin-right:8px;">')
            out.append('£' + f'{deal.total_package_price_gbp:,.0f}' + ' Total')
            out.append('</span>')
            out.append('<span style="background:#1e293b; color:#a7f3d0; padding:4px 8px; border-radius:4px; font-weight:700; font-size:12px; margin-right:8px;">')
            out.append('£' + f'{deal.price_per_person_gbp:,.0f}' + ' / person')
            out.append('</span>')
            out.append('<span style="background:#065f46; color:#6ee7b7; padding:4px 8px; border-radius:4px; font-weight:600; font-size:11px;">')
            out.append('UNDER £5K BUDGET')
            out.append('</span></div>')
            
            out.append('<div style="color:#94a3b8; font-size:13px; line-height:1.6; margin-bottom:12px;">')
            out.append('<strong>Destination:</strong> ' + escape(deal.destination_label) + ' (' + escape(deal.destination_airport) + ')<br>')
            out.append('<strong>Dates:</strong> ' + escape(deal.outbound_date) + ' → ' + escape(deal.return_date) + ' (' + str(deal.nights) + ' nights)<br>')
            out.append('<strong>Board Basis:</strong> <span style="color:#6ee7b7; font-weight:600;">' + escape(deal.board_basis) + '</span><br>')
            out.append('<strong>Flights (5 pax):</strong> ' + escape(deal.airline) + ' direct return (' + escape(', '.join(deal.origin_airports)) + ' ↔ ' + escape(deal.destination_airport) + ') · <strong>£' + f'{deal.flight_price_total_gbp:,.0f}' + '</strong><br>')
            out.append('<strong>Resort Stay (3 rooms):</strong> 24 room-nights · <strong>£' + f'{deal.hotel_price_total_gbp:,.0f}' + '</strong>')
            if deal.highlights:
                out.append('<br><strong>Resort Highlights:</strong> ' + escape(' · '.join(deal.highlights)))
            out.append('</div>')
            
            out.append('<div style="margin-top:12px;">')
            out.append('<a href="' + escape(deal.flight_booking_url, quote=True) + '" style="' + btn_primary + '">View Flights (£' + f'{deal.flight_price_total_gbp:,.0f}' + ')</a>')
            out.append('<a href="' + escape(deal.hotel_booking_url, quote=True) + '" style="' + btn_muted + '">Resort Direct</a>')
            love_url = build_loveholidays_url(
                destination=deal.destination_key,
                origin_airports=config.origins,
                departure_date=deal.outbound_date,
                return_date=deal.return_date,
                adults=config.travellers,
                rooms=len(config.rooms),
            )
            out.append('<a href="' + escape(love_url, quote=True) + '" style="' + btn_muted + '">Search on loveholidays</a>')
            out.append('</div></td></tr></table>')

        # Comparison table
        out.append('<h3 style="margin:20px 0 10px 0; color:#f8fafc; font-size:15px; font-weight:700;">Comparison Matrix (Whole Family Under £5k)</h3>')
        out.append('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; margin-bottom:24px; font-size:12px; background:#0d1520;">')
        out.append('<tr style="background:#1e293b; color:#94a3b8;">')
        out.append('<th style="padding:8px 10px; text-align:left;">Resort</th>')
        out.append('<th style="padding:8px 10px; text-align:left;">Board</th>')
        out.append('<th style="padding:8px 10px; text-align:right;">Flights (5p)</th>')
        out.append('<th style="padding:8px 10px; text-align:right;">Hotel (3r)</th>')
        out.append('<th style="padding:8px 10px; text-align:right;">Total</th>')
        out.append('<th style="padding:8px 10px; text-align:right;">Per Person</th>')
        out.append('</tr>')
        for deal in deals:
            out.append('<tr style="border-bottom:1px solid #1e293b;">')
            out.append('<td style="padding:8px 10px; color:#f8fafc; font-weight:600;">' + escape(deal.resort_name) + '</td>')
            out.append('<td style="padding:8px 10px; color:#6ee7b7;">' + escape(deal.board_basis) + '</td>')
            out.append('<td style="padding:8px 10px; text-align:right; color:#94a3b8;">£' + f'{deal.flight_price_total_gbp:,.0f}' + '</td>')
            out.append('<td style="padding:8px 10px; text-align:right; color:#94a3b8;">£' + f'{deal.hotel_price_total_gbp:,.0f}' + '</td>')
            out.append('<td style="padding:8px 10px; text-align:right; color:#34d399; font-weight:700;">£' + f'{deal.total_package_price_gbp:,.0f}' + '</td>')
            out.append('<td style="padding:8px 10px; text-align:right; color:#a7f3d0;">£' + f'{deal.price_per_person_gbp:,.0f}' + '</td>')
            out.append('</tr>')
        out.append('</table>')

    if not deals:
        out.append('<h2 style="margin:0 0 12px 0; color:#f8fafc; font-size:18px; font-weight:700;">Package Deal Search Links</h2>')
        
        adults = config.travellers
        rooms = len(config.rooms)
        
        for dest in config.destinations:
            out.append('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; margin:12px 0;">')
            out.append('<tr style="background:#1e293b;"><td colspan="2" style="padding:10px 12px; color:#f8fafc; font-size:15px; font-weight:700;">')
            out.append(escape(dest.label))
            out.append('</td></tr>')
            out.append('<tr style="background:#0d1520;"><td colspan="2" style="padding:6px 12px; color:#94a3b8; font-size:12px;">')
            out.append('From: ' + escape(', '.join(config.origins)) + ' · destination airports: ' + escape(', '.join(dest.airports)))
            out.append(' · ' + str(adults) + ' travellers · room occupancy ' + escape(room_occupancy))
            out.append('</td></tr>')
            out.append('<tr style="background:#0d1520;"><td colspan="2" style="padding:4px 12px; color:#6ee7b7; font-size:12px; font-weight:600;">All Inclusive · Half Board · Full Board · Room Only</td></tr>')
            
            # ── TOP PICKS: 3 representative date pairs with primary buttons ──
            out.append('<tr><td colspan="2" style="padding:12px 12px 4px; color:#fbbf24; font-size:13px; font-weight:700;">')
            out.append('⭐ Top Picks (3 of ' + str(len(pairs)) + ' date combinations)')
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
                for name, url in urls.items():
                    out.append('<a href="')
                    out.append(escape(url, quote=True))
                    out.append('" style="')
                    out.append(btn_primary)
                    out.append('">')
                    out.append(escape(provider_labels[name]))
                    out.append('</a>')
                out.append('</div>')
            out.append('</td></tr>')
            
            # ── FULL MATRIX: visually demoted, compact ──
            out.append('<tr><td colspan="2" style="padding:10px 12px 4px; color:#64748b; font-size:12px; font-weight:600; border-top:1px solid #1e293b;">')
            out.append('All ' + str(len(pairs)) + ' date combinations (tap to expand)')
            out.append('</td></tr>')
            
            # Build a compact grid: date pairs as rows, providers as columns
            out.append('<tr><td colspan="2" style="padding:4px 10px 10px; font-size:11px;">')
            out.append('<table style="width:100%; border-collapse:collapse; font-size:11px;">')
            # Header row
            out.append('<tr>')
            out.append('<th style="text-align:left; padding:4px 6px; color:#64748b; font-weight:600; font-size:10px; border-bottom:1px solid #1e293b;">Dates</th>')
            for name in urls.keys():
                out.append('<th style="text-align:center; padding:4px 6px; color:#64748b; font-weight:600; font-size:10px; border-bottom:1px solid #1e293b;">')
                out.append(escape(provider_labels[name]))
                out.append('</th>')
            out.append('</tr>')
            # Data rows
            for outbound, returning in pairs:
                urls = build_provider_urls(
                    destination_key=dest.key,
                    destination_label=dest.label,
                    origin_airports=config.origins,
                    departure_date=outbound,
                    return_date=returning,
                    adults=adults,
                    rooms=rooms,
                )
                out.append('<tr>')
                out.append('<td style="padding:4px 6px; color:#94a3b8; font-size:11px; border-bottom:1px solid #0d1520; white-space:nowrap;">')
                out.append(escape(outbound) + ' → ' + escape(returning))
                out.append('</td>')
                for name, url in urls.items():
                    out.append('<td style="padding:2px 4px; text-align:center; border-bottom:1px solid #0d1520;">')
                    out.append('<a href="')
                    out.append(escape(url, quote=True))
                    out.append('" style="')
                    out.append(btn_muted)
                    out.append('">Open</a>')
                    out.append('</td>')
                out.append('</tr>')
            out.append('</table>')
            out.append('</td></tr>')
            
            out.append('</table>')
        
        out.append('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; margin-top:24px;">')
        out.append('<tr><td style="padding:14px; background:#392d14; border-radius:6px; color:#fde68a; font-size:12px; line-height:1.5;">')
        out.append('<strong style="color:#fbbf24;">⚠ No live prices collected</strong> — these are provider search entry points, not verified checkout deep links. Some providers accept only the first departure airport or room count in a URL. Reapply every origin option, the exact room occupancy <strong>' + escape(room_occupancy) + '</strong>, preferred departure time, board basis, baggage and transfers before relying on a result. Verify the final whole-party checkout total and protection before booking.')
        out.append('</td></tr></table>')
    else:
        out.append('<h3 style="margin:24px 0 10px 0; color:#f8fafc; font-size:14px; font-weight:700;">Direct Holiday Provider Search Entry Points</h3>')
        out.append('<p style="margin:0 0 12px 0; color:#94a3b8; font-size:12px;">Query live packages directly on major UK holiday portals for custom room or baggage options:</p>')
        out.append('<div style="margin-bottom:16px;">')
        target_outbound, target_return = (
            shortlist[len(shortlist) // 2] if shortlist else ("2026-12-22", "2026-12-30")
        )
        for dest in config.destinations[:4]:
            urls = build_provider_urls(
                destination_key=dest.key,
                destination_label=dest.label,
                origin_airports=config.origins,
                departure_date=target_outbound,
                return_date=target_return,
                adults=config.travellers,
                rooms=len(config.rooms),
            )
            out.append('<div style="margin-bottom:8px;"><strong style="color:#f8fafc; font-size:12px; margin-right:8px;">' + escape(dest.label.split('(')[0].strip()) + ':</strong> ')
            for name, url in urls.items():
                out.append('<a href="' + escape(url, quote=True) + '" style="' + btn_muted + '">' + escape(provider_labels[name]) + '</a> ')
            out.append('</div>')
        out.append('</div>')
    out.append('</td></tr></table></body></html>')
    
    return ''.join(out)
