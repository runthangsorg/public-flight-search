"""Runtime-configured holiday search plan with truthful provider entry links."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
import json
from typing import Any

from .config import ConfigError, _airports, _dates, _text, _window


PROVIDERS = (
    ("loveholidays", "https://www.loveholidays.com/holidays/"),
    ("On the Beach", "https://www.onthebeach.co.uk/holidays"),
    ("Jet2holidays", "https://www.jet2holidays.com/"),
    ("TUI", "https://www.tui.co.uk/holidays/"),
    ("easyJet holidays", "https://www.easyjet.com/en/holidays"),
    ("British Airways Holidays", "https://www.britishairways.com/content/holidays"),
    ("Expedia", "https://www.expedia.co.uk/"),
    ("TravelSupermarket", "https://www.travelsupermarket.com/en-gb/holidays/"),
)


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
    destinations = "".join(
        f"<section><h2>{escape(item.label)}</h2><p>Airports: {', '.join(item.airports)}</p>"
        + "<div>" + "".join(
            f'<a href="{url}">{escape(name)}</a>' for name, url in PROVIDERS
        ) + "</div></section>"
        for item in config.destinations
    )
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><style>
    body{{background:#07131e;color:#edf6ff;font-family:Arial;margin:0}}main{{max-width:860px;margin:auto;padding:28px}}section{{background:#102538;border:1px solid #25465e;border-radius:14px;padding:18px;margin:14px 0}}a{{display:inline-block;background:#7dd3fc;color:#062033;text-decoration:none;padding:9px 12px;margin:5px;border-radius:8px;font-weight:700}}.warn{{color:#fde68a}}</style></head><body><main>
    <h1>{escape(config.report_title)}</h1><p>Generated {escape(generated_at)}</p>
    <p><strong>{config.travellers} travellers</strong> · rooms {escape(' + '.join(map(str, config.rooms)))} · depart {', '.join(config.outbound_dates)} · return {', '.join(config.return_dates)} · preferred flight time {escape(config.departure_window[0])}–{escape(config.departure_window[1])}</p>
    <h2>Official search entry points</h2>{destinations}
    <p class="warn">No live package price was collected in this planning run. Open each official provider, apply the exact party and room occupancy, and verify the whole-party checkout total, baggage and protection before booking.</p>
    </main></body></html>"""
