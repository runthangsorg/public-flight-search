"""Climate exclusions and warnings (owner direction 2026-10-15, 20:45 BST).

"avoid all monsoon areas, remove from the hotels and locations". Two kinds of
climate fact live in ``data/climate_exclusions.json`` and they behave in
opposite ways:

* **exclusions** — a stay that falls inside a rainy season is never offered.
  The place is gone from the cards, the glance table, the two-centre block and
  the watch list, and the run names it once in the e-mail's Notes;
* **warnings** — a rainy season that mostly ends before the reader lands (Japan's
  tsuyu) keeps the stay and prints a ⚠ line instead. Japan's main-island cities
  stay allowed on the owner's own word: "if going japan then tokyo etc. would
  be stays for a few days too" (20:55 BST).

A **connection** through an excluded airport — a leg with no nights, HKT→BKK→
USM — is not a stay and is never gated.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

DEFAULT_PATH = Path(__file__).parent / "data" / "climate_exclusions.json"


@dataclass(frozen=True)
class ExclusionArea:
    """One rainy season a stay must not be sold in."""

    id: str
    airports: tuple[str, ...]
    place_words: tuple[str, ...]
    months: tuple[int, ...]
    why: str
    source: str


@dataclass(frozen=True)
class WarningArea:
    """One rainy season a stay may be sold in, with a line about it."""

    id: str
    airports: tuple[str, ...]
    place_words: tuple[str, ...]
    months: tuple[int, ...]
    text: str


@dataclass(frozen=True)
class ClimateRules:
    areas: tuple[ExclusionArea, ...] = ()
    warnings: tuple[WarningArea, ...] = ()


def load_climate_rules(path: Path | str = DEFAULT_PATH) -> ClimateRules:
    """The committed table. A missing or unreadable file is no rules at all —
    the report is then exactly what it was before the table existed."""
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - absence of data is not an error here
        return ClimateRules()
    if not isinstance(data, Mapping):
        return ClimateRules()

    areas: list[ExclusionArea] = []
    for item in data.get("areas", []) or []:
        if not isinstance(item, Mapping):
            continue
        try:
            areas.append(
                ExclusionArea(
                    id=str(item.get("id", "")),
                    airports=tuple(str(a).upper() for a in (item.get("airports") or ())),
                    place_words=tuple(
                        str(w).strip().lower() for w in (item.get("place_words") or ())
                        if str(w).strip()
                    ),
                    months=tuple(sorted({int(m) for m in (item.get("months") or ())})),
                    why=str(item.get("why", "")),
                    source=str(item.get("source", "")),
                )
            )
        except (TypeError, ValueError):
            continue

    warnings: list[WarningArea] = []
    for item in data.get("warnings", []) or []:
        if not isinstance(item, Mapping):
            continue
        try:
            warnings.append(
                WarningArea(
                    id=str(item.get("id", "")),
                    airports=tuple(str(a).upper() for a in (item.get("airports") or ())),
                    place_words=tuple(
                        str(w).strip().lower() for w in (item.get("place_words") or ())
                        if str(w).strip()
                    ),
                    months=tuple(sorted({int(m) for m in (item.get("months") or ())})),
                    text=str(item.get("text", "")),
                )
            )
        except (TypeError, ValueError):
            continue

    return ClimateRules(areas=tuple(areas), warnings=tuple(warnings))


def stay_months_for_pairs(
    pairs: Sequence[tuple[Any, Any]],
) -> set[int]:
    """Every calendar month at least one night of these stays falls in.

    A stay that touches 30 June and 7 July is months {6, 7}: the rule the brief
    sets is "any night of the stay", not the departure month.
    """
    months: set[int] = set()
    for outbound, returning in pairs:
        try:
            out = datetime.strptime(str(outbound), "%Y-%m-%d")
            ret = datetime.strptime(str(returning), "%Y-%m-%d")
        except ValueError:
            continue
        if ret < out:
            out, ret = ret, out
        cur = out.replace(day=1)
        end = ret.replace(day=1)
        while cur <= end:
            months.add(cur.month)
            cur = (
                cur.replace(year=cur.year + 1, month=1)
                if cur.month == 12
                else cur.replace(month=cur.month + 1)
            )
    return months


_WORD = re.compile(r"[a-z0-9]+")


def _matches(
    text: Optional[str],
    airports: Sequence[str],
    *,
    area_airports: Sequence[str],
    place_words: Sequence[str],
) -> bool:
    """Does this place name or airport code name that area?

    Place words are matched as whole words AND as substrings, because the table
    holds both "bangkok" and "khao lak" — a two-word place is one phrase, not
    two independent words.
    """
    hay_airports = {str(a).upper() for a in airports if str(a).strip()}
    for code in area_airports:
        if code in hay_airports:
            return True
    if not text:
        return False
    lowered = str(text).lower()
    words = set(_WORD.findall(lowered))
    for word in place_words:
        if word in words or word in lowered:
            return True
    return False


def exclusion_for(
    *,
    text: Optional[str] = None,
    airports: Optional[Sequence[str]] = None,
    stay_months: Optional[set[int]] = None,
    rules: Optional[ClimateRules] = None,
) -> Optional[ExclusionArea]:
    """The exclusion area this STAY falls inside, or None to let it through."""
    rules = load_climate_rules() if rules is None else rules
    months = stay_months or set()
    if not months:
        return None
    for area in rules.areas:
        if set(area.months) & months and _matches(
            text, airports or (), area_airports=area.airports,
            place_words=area.place_words,
        ):
            return area
    return None


def warnings_for(
    *,
    text: Optional[str] = None,
    airports: Optional[Sequence[str]] = None,
    stay_months: Optional[set[int]] = None,
    rules: Optional[ClimateRules] = None,
) -> list[WarningArea]:
    """The ⚠ lines this STAY carries. Warnings never remove anything."""
    rules = load_climate_rules() if rules is None else rules
    months = stay_months or set()
    if not months:
        return []
    return [
        area for area in rules.warnings
        if set(area.months) & months and _matches(
            text, airports or (), area_airports=area.airports,
            place_words=area.place_words,
        )
    ]
