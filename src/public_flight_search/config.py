"""Strict runtime-only configuration for personalized flight searches."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
import re
from typing import Any, Mapping


_AIRPORT = re.compile(r"^[A-Z]{3}$")
_CLOCK = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class ConfigError(ValueError):
    """Raised when private runtime configuration is invalid or oversized."""


def _text(value: Any, name: str, limit: int = 120) -> str:
    result = " ".join(str(value or "").split())
    if not result or len(result) > limit:
        raise ConfigError(f"{name} must contain 1-{limit} printable characters")
    return result


def _airports(value: Any, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= 8:
        raise ConfigError(f"{name} must contain 1-8 airport codes")
    values = tuple(str(item).upper() for item in value)
    if any(not _AIRPORT.fullmatch(item) for item in values):
        raise ConfigError(f"{name} contains an invalid airport code")
    return values


def _dates(value: Any, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= 8:
        raise ConfigError(f"{name} must contain 1-8 ISO dates")
    parsed: list[str] = []
    for item in value:
        try:
            parsed.append(date.fromisoformat(str(item)).isoformat())
        except ValueError as exc:
            raise ConfigError(f"{name} contains an invalid ISO date") from exc
    return tuple(parsed)


def _window(value: Any) -> tuple[str, str]:
    if not isinstance(value, list) or len(value) != 2:
        raise ConfigError("departure_window must contain earliest and latest times")
    result = (str(value[0]), str(value[1]))
    if any(not _CLOCK.fullmatch(item) for item in result) or result[0] > result[1]:
        raise ConfigError("departure_window must be an ordered HH:MM range")
    return result


@dataclass(frozen=True)
class FlightSearch:
    key: str
    label: str
    origins: tuple[str, ...]
    destinations: tuple[str, ...]
    dates: tuple[str, ...]
    travellers: int
    cabin_class: str
    departure_window: tuple[str, str]
    max_stops: int
    max_duration_minutes: int
    max_price_per_traveller_gbp: float | None


@dataclass(frozen=True)
class FlightConfig:
    report_title: str
    searches: tuple[FlightSearch, ...]


def _parse_search(raw: Mapping[str, Any]) -> FlightSearch:
    allowed = {
        "key", "label", "origins", "destinations", "dates", "travellers",
        "cabin_class", "departure_window", "max_stops",
        "max_duration_minutes", "max_price_per_traveller_gbp",
    }
    unknown = set(raw) - allowed
    if unknown:
        raise ConfigError(f"unknown flight search fields: {sorted(unknown)}")
    travellers = int(raw.get("travellers", 1))
    max_stops = int(raw.get("max_stops", 2))
    duration = int(raw.get("max_duration_minutes", 1440))
    if not 1 <= travellers <= 9 or not 0 <= max_stops <= 3:
        raise ConfigError("travellers or max_stops is out of bounds")
    if not 30 <= duration <= 1440:
        raise ConfigError("max_duration_minutes is out of bounds")
    cabin = str(raw.get("cabin_class", "ECONOMY")).upper()
    if cabin not in {"ECONOMY", "PREMIUM_ECONOMY", "BUSINESS", "FIRST"}:
        raise ConfigError("unsupported cabin_class")
    maximum = raw.get("max_price_per_traveller_gbp")
    maximum = None if maximum is None else float(maximum)
    if maximum is not None and not 1 <= maximum <= 100_000:
        raise ConfigError("max_price_per_traveller_gbp is out of bounds")
    return FlightSearch(
        key=_text(raw.get("key"), "key", 48),
        label=_text(raw.get("label"), "label"),
        origins=_airports(raw.get("origins"), "origins"),
        destinations=_airports(raw.get("destinations"), "destinations"),
        dates=_dates(raw.get("dates"), "dates"),
        travellers=travellers,
        cabin_class=cabin,
        departure_window=_window(raw.get("departure_window", ["00:00", "23:59"])),
        max_stops=max_stops,
        max_duration_minutes=duration,
        max_price_per_traveller_gbp=maximum,
    )


def load_flight_config(payload: str) -> FlightConfig:
    if not payload or len(payload.encode("utf-8")) > 48_000:
        raise ConfigError("flight configuration is empty or oversized")
    try:
        raw = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ConfigError("flight configuration is not valid JSON") from exc
    if not isinstance(raw, dict):
        raise ConfigError("flight configuration must be an object")
    allowed = {"report_title", "searches"}
    unknown = set(raw) - allowed
    if unknown:
        raise ConfigError(f"unknown top-level fields: {sorted(unknown)}")
    searches_raw = raw.get("searches")
    if not isinstance(searches_raw, list) or not 1 <= len(searches_raw) <= 20:
        raise ConfigError("searches must contain 1-20 jobs")
    if not all(isinstance(item, dict) for item in searches_raw):
        raise ConfigError("every search must be an object")
    searches = tuple(_parse_search(item) for item in searches_raw)
    keys = [item.key for item in searches]
    if len(keys) != len(set(keys)):
        raise ConfigError("search keys must be unique")
    return FlightConfig(
        report_title=_text(raw.get("report_title", "Flight deal digest"), "report_title"),
        searches=searches,
    )
