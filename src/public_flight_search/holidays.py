"""Runtime-configured holiday search plan with parametric provider search URLs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from html import escape
import json
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


def render_holiday_report(config: HolidayConfig, *, generated_at: str) -> str:
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
    out.append('</td></tr></table></body></html>')
    
    return ''.join(out)
