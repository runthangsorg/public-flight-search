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

        provider_cards = []
        for name, url in [
            ("LoveHolidays", urls["loveholidays"]),
            ("On the Beach", urls["on_the_beach"]),
            ("Jet2holidays", urls["jet2"]),
            ("TUI", urls["tui"]),
            ("easyJet holidays", urls["easyjet"]),
            ("British Airways Holidays", urls["ba_holidays"]),
        ]:
            provider_cards.append(
                f'<a href="{escape(url, quote=True)}" style="display: inline-block; margin: 6px 8px 6px 0; padding: 12px 20px; background: linear-gradient(135deg, #38bdf8, #0ea5e9); color: #08111f; text-decoration: none; border-radius: 10px; font-weight: 700; font-size: 14px; transition: transform 0.2s;">{escape(name)} ↗</a>'
            )

        dates_html = f"{escape(outbound)} → {escape(ret)}"

        destinations += (
            f"<section style='background: linear-gradient(135deg, #101d30 0%, #1a2a42 100%); border: 1px solid #263953; border-radius: 16px; padding: 24px; margin: 20px 0;'>"
            f"<div style='display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;'>"
            f"<h2 style='font-size: 22px; color: #f8fafc; margin: 0;'>{escape(dest.label)}</h2>"
            f"<span style='background: #1e3a5f; color: #7dd3fc; border-radius: 8px; padding: 4px 12px; font-size: 12px; font-weight: 600;'>{escape(dates_html)}</span>"
            f"</div>"
            f"<p style='color: #94a3b8; font-size: 13px; margin: 0 0 6px 0;'>Airports: {', '.join(dest.airports)} · {config.travellers} travellers · rooms {escape(' + '.join(map(str, config.rooms)))}</p>"
            f"<p style='color: #6ee7b7; font-size: 14px; margin: 0 0 16px 0; font-weight: 600;'>Search for: All Inclusive · Half Board · Full Board · Room Only</p>"
            f"<div style='margin-top: 12px;'>{''.join(provider_cards)}</div>"
            f"<p style='color: #94a3b8; font-size: 12px; margin: 16px 0 0 0; line-height: 1.4;'>Click any provider to search live package prices. Apply exact party size, room occupancy, and board basis at checkout. Verify the whole-party total including transfers and protection.</p>"
            f"</section>"
        )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{escape(config.report_title)}</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ margin: 0; background: #08111f; color: #e5edf7; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; line-height: 1.5; }}
    main {{ max-width: 960px; margin: auto; padding: 32px 20px 48px; }}
    h1 {{ font-size: 32px; margin: 0 0 8px; color: #f8fafc; font-weight: 800; }}
    h2 {{ margin-top: 28px; color: #f8fafc; font-weight: 700; }}
    .sub {{ color: #9eb0c7; }}
    section {{ background: linear-gradient(135deg, #101d30 0%, #1a2a42 100%); border: 1px solid #263953; border-radius: 16px; padding: 24px; margin: 20px 0; }}
    a {{ display: inline-block; margin: 6px 8px 6px 0; padding: 12px 20px; background: linear-gradient(135deg, #38bdf8, #0ea5e9); color: #08111f; text-decoration: none; border-radius: 10px; font-weight: 700; font-size: 14px; transition: transform 0.2s; }}
    a:hover {{ transform: translateY(-2px); }}
    .warn {{ color: #fde68a; font-size: 13px; line-height: 1.5; background: #392d14; padding: 14px; border-radius: 8px; }}
    footer {{ margin-top: 40px; color: #8496ad; font-size: 12px; line-height: 1.5; border-top: 1px solid #1e293b; padding-top: 16px; }}
    @media (max-width: 640px) {{ section {{ padding: 16px; }} a {{ margin: 4px; padding: 10px 14px; font-size: 13px; }} }}
  </style>
</head>
<body>
  <main style="max-width: 960px; margin: auto; padding: 32px 20px 48px;">
    <h1 style="font-size: 32px; margin: 0 0 8px; color: #f8fafc; font-weight: 800;">{escape(config.report_title)}</h1>
    <p class="sub" style="color: #9eb0c7; margin: 0 0 24px 0; font-size: 14px;">
      🕐 Generated {escape(generated_at)} · {len(config.destinations)} destinations · package search links
    </p>
    <div style="background: #0d1520; border-radius: 12px; padding: 16px; margin: 0 0 24px 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 16px;">
      <div style="text-align: center;">
        <div style="color: #6ee7b7; font-size: 24px; font-weight: 800;">{config.travellers}</div>
        <div style="color: #8ca0b9; font-size: 12px;">Travellers</div>
      </div>
      <div style="text-align: center;">
        <div style="color: #6ee7b7; font-size: 24px; font-weight: 800;">{escape(' + '.join(map(str, config.rooms)))}</div>
        <div style="color: #8ca0b9; font-size: 12px;">Rooms</div>
      </div>
      <div style="text-align: center;">
        <div style="color: #6ee7b7; font-size: 24px; font-weight: 800;">{escape(config.outbound_dates[0])}</div>
        <div style="color: #8ca0b9; font-size: 12px;">Depart</div>
      </div>
      <div style="text-align: center;">
        <div style="color: #6ee7b7; font-size: 24px; font-weight: 800;">{escape(config.return_dates[-1])}</div>
        <div style="color: #8ca0b9; font-size: 12px;">Return</div>
      </div>
    </div>
    <h2 style="font-size: 22px; color: #f8fafc; margin: 28px 0 14px 0;">Package Deal Search Links</h2>
    {destinations}
    <div class="warn" style="color: #fde68a; font-size: 13px; line-height: 1.5; background-color: #392d14; padding: 16px; border-radius: 10px; margin-top: 28px;">
      <strong style="color: #fbbf24;">⚠️ No live prices collected</strong> — these are official search entry points. Open each provider, apply the exact party and room occupancy, and verify the whole-party checkout total, baggage, transfers and protection before booking. Filter for <strong>All Inclusive</strong>, <strong>Half Board</strong>, or <strong>Full Board</strong> as needed.
    </div>
    <footer style="margin-top: 40px; color: #8496ad; font-size: 12px; line-height: 1.5; border-top: 1px solid #1e293b; padding-top: 16px;">
      Package prices can change instantly. Always verify at checkout.
    </footer>
  </main>
</body>
</html>"""
