"""Runtime-configured holiday search plan with parametric provider search URLs."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
import json
from typing import Any
from urllib.parse import quote_plus, urlencode

from .config import ConfigError, _airports, _dates, _text, _window


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
    params = {
        "destination": destination,
        "departureAirports": ",".join(origin_airports),
        "departureDate": departure_date,
        "returnDate": return_date,
        "adults": str(adults),
        "rooms": str(rooms),
    }
    return "https://www.loveholidays.com/search/?" + urlencode(params)


def build_on_the_beach_url(
    *,
    destination: str,
    origin_airports: tuple[str, ...],
    departure_date: str,
    return_date: str,
    adults: int,
) -> str:
    params = {
        "destination": destination,
        "departureAirport": origin_airports[0] if origin_airports else "",
        "departureDate": departure_date,
        "returnDate": return_date,
        "adults": str(adults),
    }
    return "https://www.onthebeach.co.uk/holidays/search/?" + urlencode(params)


def build_jet2_url(
    *,
    destination: str,
    origin_airports: tuple[str, ...],
    departure_date: str,
    return_date: str,
    adults: int,
    rooms: int,
) -> str:
    params = {
        "destination": destination,
        "departureAirport": origin_airports[0] if origin_airports else "",
        "departureDate": departure_date,
        "returnDate": return_date,
        "adults": str(adults),
        "rooms": str(rooms),
    }
    return "https://www.jet2holidays.com/search/?" + urlencode(params)


def build_tui_url(
    *,
    destination: str,
    origin_airports: tuple[str, ...],
    departure_date: str,
    return_date: str,
    adults: int,
) -> str:
    params = {
        "destination": destination,
        "departureAirport": origin_airports[0] if origin_airports else "",
        "departureDate": departure_date,
        "returnDate": return_date,
        "adults": str(adults),
    }
    return "https://www.tui.co.uk/holidays/search/?" + urlencode(params)


def build_easyjet_url(
    *,
    destination: str,
    origin_airports: tuple[str, ...],
    departure_date: str,
    return_date: str,
    adults: int,
) -> str:
    params = {
        "destination": destination,
        "departureAirport": origin_airports[0] if origin_airports else "",
        "departureDate": departure_date,
        "returnDate": return_date,
        "adults": str(adults),
    }
    return "https://www.easyjet.com/en/holidays/search/?" + urlencode(params)


def build_ba_holidays_url(
    *,
    destination: str,
    origin_airports: tuple[str, ...],
    departure_date: str,
    return_date: str,
    adults: int,
) -> str:
    params = {
        "destination": destination,
        "departureAirport": origin_airports[0] if origin_airports else "",
        "departureDate": departure_date,
        "returnDate": return_date,
        "adults": str(adults),
    }
    return "https://www.britishairways.com/holidays/search/?" + urlencode(params)


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
    return HolidayConfig(
        report_title=_text(raw.get("report_title", "Holiday package watch"), "report_title"),
        travellers=travellers,
        rooms=rooms,
        departure_window=_window(raw.get("departure_window")),
        origins=_airports(raw.get("origins"), "origins"),
        outbound_dates=_dates(raw.get("outbound_dates"), "outbound_dates"),
        return_dates=_dates(raw.get("return_dates"), "return_dates"),
        destinations=destinations,
    )


def render_holiday_report(config: HolidayConfig, *, generated_at: str) -> str:
    out = []
    out.append('<!DOCTYPE html><html><head><meta charset="utf-8"><title>')
    out.append(escape(config.report_title))
    out.append('</title></head><body style="margin:0; padding:0; background:#08111f; font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif; line-height:1.5;">')
    out.append('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px; margin:0 auto; background:#08111f;">')
    out.append('<tr><td style="padding:24px 16px;">')
    out.append('<h1 style="margin:0 0 4px 0; color:#f8fafc; font-size:22px; font-weight:800;">')
    out.append(escape(config.report_title))
    out.append('</h1>')
    out.append('<p style="margin:0 0 16px 0; color:#9eb0c7; font-size:13px;">Generated ')
    out.append(escape(generated_at))
    out.append(' · ')
    out.append(str(len(config.destinations)))
    out.append(' destinations · package search links</p>')
    out.append('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; margin-bottom:20px;">')
    out.append('<tr><td style="padding:10px 12px; background:#0d1520; color:#9eb0c7; font-size:13px;">')
    out.append('<strong style="color:#f8fafc;">' + str(config.travellers) + '</strong> travellers · <strong style="color:#f8fafc;">' + str(len(config.rooms)) + '</strong> room(s) · depart <strong style="color:#f8fafc;">' + escape(config.outbound_dates[0]) + '</strong> · return <strong style="color:#f8fafc;">' + escape(config.return_dates[0]) + '</strong>')
    out.append('</td></tr></table>')
    out.append('<h2 style="margin:0 0 12px 0; color:#f8fafc; font-size:18px; font-weight:700;">Package Deal Search Links</h2>')
    
    outbound = config.outbound_dates[0] if config.outbound_dates else ""
    ret = config.return_dates[0] if config.return_dates else ""
    adults = config.travellers
    rooms = len(config.rooms)
    
    for dest in config.destinations:
        urls = build_provider_urls(
            destination_key=dest.key,
            destination_label=dest.label,
            origin_airports=config.origins,
            departure_date=outbound,
            return_date=ret,
            adults=adults,
            rooms=rooms,
        )
        
        out.append('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; margin:12px 0;">')
        out.append('<tr style="background:#1e293b;"><td colspan="2" style="padding:10px 12px; color:#f8fafc; font-size:15px; font-weight:700;">')
        out.append(escape(dest.label))
        out.append('</td></tr>')
        out.append('<tr style="background:#0d1520;"><td colspan="2" style="padding:6px 12px; color:#94a3b8; font-size:12px;">')
        out.append('From: ' + ', '.join(config.origins) + ' · ' + str(adults) + ' travellers · ' + str(rooms) + ' room(s) · ')
        out.append(escape(outbound) + ' → ' + escape(ret))
        out.append('</td></tr>')
        out.append('<tr style="background:#0d1520;"><td colspan="2" style="padding:4px 12px; color:#6ee7b7; font-size:12px; font-weight:600;">All Inclusive · Half Board · Full Board · Room Only</td></tr>')
        
        for name, url in urls.items():
            out.append('<tr><td colspan="2" style="padding:4px 12px;"><a href="')
            out.append(escape(url, quote=True))
            out.append('" style="color:#38bdf8; text-decoration:none; font-size:13px;">')
            out.append(escape(name))
            out.append('</a></td></tr>')
        
        out.append('</table>')
    
    out.append('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; margin-top:24px;">')
    out.append('<tr><td style="padding:14px; background:#392d14; border-radius:6px; color:#fde68a; font-size:12px; line-height:1.5;">')
    out.append('<strong style="color:#fbbf24;">⚠ No live prices collected</strong> — these are official search entry points. Open each provider, apply the exact party and room occupancy, and verify the whole-party checkout total, baggage, transfers and protection before booking. Filter for <strong>All Inclusive</strong>, <strong>Half Board</strong>, or <strong>Full Board</strong> as needed.')
    out.append('</td></tr></table>')
    out.append('</td></tr></table></body></html>')
    
    return ''.join(out)
