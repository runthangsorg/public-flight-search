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
    airports: tuple[str, ...],
    departure_date: str,
    return_date: str,
    adults: int,
    rooms: int,
) -> str:
    params = {
        "destination": destination,
        "departureAirports": ",".join(airports),
        "departureDate": departure_date,
        "returnDate": return_date,
        "adults": str(adults),
        "rooms": str(rooms),
    }
    return "https://www.loveholidays.com/search/?" + urlencode(params)


def build_on_the_beach_url(
    *,
    destination: str,
    airports: tuple[str, ...],
    departure_date: str,
    return_date: str,
    adults: int,
) -> str:
    params = {
        "destination": destination,
        "departureAirport": airports[0] if airports else "",
        "departureDate": departure_date,
        "returnDate": return_date,
        "adults": str(adults),
    }
    return "https://www.onthebeach.co.uk/holidays/search/?" + urlencode(params)


def build_jet2_url(
    *,
    destination: str,
    airports: tuple[str, ...],
    departure_date: str,
    return_date: str,
    adults: int,
    rooms: int,
) -> str:
    params = {
        "destination": destination,
        "departureAirport": airports[0] if airports else "",
        "departureDate": departure_date,
        "returnDate": return_date,
        "adults": str(adults),
        "rooms": str(rooms),
    }
    return "https://www.jet2holidays.com/search/?" + urlencode(params)


def build_tui_url(
    *,
    destination: str,
    airports: tuple[str, ...],
    departure_date: str,
    return_date: str,
    adults: int,
) -> str:
    params = {
        "destination": destination,
        "departureAirport": airports[0] if airports else "",
        "departureDate": departure_date,
        "returnDate": return_date,
        "adults": str(adults),
    }
    return "https://www.tui.co.uk/holidays/search/?" + urlencode(params)


def build_easyjet_url(
    *,
    destination: str,
    airports: tuple[str, ...],
    departure_date: str,
    return_date: str,
    adults: int,
) -> str:
    params = {
        "destination": destination,
        "departureAirport": airports[0] if airports else "",
        "departureDate": departure_date,
        "returnDate": return_date,
        "adults": str(adults),
    }
    return "https://www.easyjet.com/en/holidays/search/?" + urlencode(params)


def build_ba_holidays_url(
    *,
    destination: str,
    airports: tuple[str, ...],
    departure_date: str,
    return_date: str,
    adults: int,
) -> str:
    params = {
        "destination": destination,
        "departureAirport": airports[0] if airports else "",
        "departureDate": departure_date,
        "returnDate": return_date,
        "adults": str(adults),
    }
    return "https://www.britishairways.com/holidays/search/?" + urlencode(params)


def build_provider_urls(
    *,
    destination_key: str,
    destination_label: str,
    airports: tuple[str, ...],
    departure_date: str,
    return_date: str,
    adults: int,
    rooms: int,
) -> dict[str, str]:
    return {
        "loveholidays": build_loveholidays_url(
            destination=destination_key,
            airports=airports,
            departure_date=departure_date,
            return_date=return_date,
            adults=adults,
            rooms=rooms,
        ),
        "on_the_beach": build_on_the_beach_url(
            destination=destination_key,
            airports=airports,
            departure_date=departure_date,
            return_date=return_date,
            adults=adults,
        ),
        "jet2": build_jet2_url(
            destination=destination_key,
            airports=airports,
            departure_date=departure_date,
            return_date=return_date,
            adults=adults,
            rooms=rooms,
        ),
        "tui": build_tui_url(
            destination=destination_key,
            airports=airports,
            departure_date=departure_date,
            return_date=return_date,
            adults=adults,
        ),
        "easyjet": build_easyjet_url(
            destination=destination_key,
            airports=airports,
            departure_date=departure_date,
            return_date=return_date,
            adults=adults,
        ),
        "ba_holidays": build_ba_holidays_url(
            destination=destination_key,
            airports=airports,
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
    destinations = ""
    for dest in config.destinations:
        outbound = config.outbound_dates[0] if config.outbound_dates else ""
        ret = config.return_dates[0] if config.return_dates else ""
        urls = build_provider_urls(
            destination_key=dest.key,
            destination_label=dest.label,
            airports=dest.airports,
            departure_date=outbound,
            return_date=ret,
            adults=config.travellers,
            rooms=len(config.rooms),
        )
        links = "".join(
            f'<a href="{escape(url, quote=True)}" style="display: inline-block; margin: 5px 8px 5px 0; padding: 10px 16px; background-color: #38bdf8; color: #08111f; text-decoration: none; border-radius: 8px; font-weight: 700; font-size: 13px;">{escape(name)}</a> '
            for name, url in [
                ("LoveHolidays", urls["loveholidays"]),
                ("On the Beach", urls["on_the_beach"]),
                ("Jet2holidays", urls["jet2"]),
                ("TUI", urls["tui"]),
                ("easyJet holidays", urls["easyjet"]),
                ("British Airways Holidays", urls["ba_holidays"]),
            ]
        )
        destinations += (
            f"<section style='background-color: #102538; border: 1px solid #25465e; border-radius: 14px; padding: 18px 20px; margin: 16px 0;'>"
            f"<h2 style='font-size: 20px; color: #f8fafc; margin: 0 0 6px 0;'>{escape(dest.label)}</h2>"
            f"<p style='color: #94a3b8; font-size: 13px; margin: 0 0 14px 0;'>Airports: {', '.join(dest.airports)}</p>"
            f"<div style='margin-top: 10px;'>{links}</div></section>"
        )
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><style>
    body{{background:#07131e;color:#edf6ff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;margin:0}}main{{max-width:860px;margin:auto;padding:28px 18px 48px}}section{{background:#102538;border:1px solid #25465e;border-radius:14px;padding:18px;margin:14px 0}}a{{display:inline-block;background:#38bdf8;color:#08111f;text-decoration:none;padding:10px 16px;margin:5px 8px 5px 0;border-radius:8px;font-weight:700;font-size:13px}}.warn{{color:#fde68a;font-size:13px;line-height:1.5;background:#392d14;padding:12px;border-radius:8px}}</style></head><body style="background-color: #07131e; color: #edf6ff; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; margin: 0;"><main style="max-width:860px;margin:auto;padding:28px 18px 48px;">
    <h1 style="font-size:28px;margin:0 0 8px;color:#f8fafc;">{escape(config.report_title)}</h1><p style="color:#94a3b8;font-size:14px;margin:0 0 20px 0;">Generated {escape(generated_at)}</p>
    <p style="color:#cbd5e1;font-size:14px;line-height:1.5;margin:0 0 24px 0;"><strong style="color:#f8fafc;">{config.travellers} travellers</strong> · rooms {escape(' + '.join(map(str, config.rooms)))} · depart {', '.join(config.outbound_dates)} · return {', '.join(config.return_dates)} · preferred flight time {escape(config.departure_window[0])}–{escape(config.departure_window[1])}</p>
    <h2 style="font-size:22px;color:#f8fafc;margin:28px 0 14px 0;">Official search entry points</h2>{destinations}
    <p class="warn" style="color:#fde68a;font-size:13px;line-height:1.5;background-color:#392d14;padding:14px;border-radius:8px;margin-top:28px;">No live package price was collected in this planning run. Open each official provider, apply the exact party and room occupancy, and verify the whole-party checkout total, baggage and protection before booking.</p>
    </main></body></html>"""
