"""Properties to price, and what is known about them that is not a price (owner, 8 Nov 2026).

``data/watchlist.json`` holds leads (Gili Islands villas and resorts, Maldives resorts that need a seaplane) that were
opened on the property's own page but have no dated, sourced rate yet, so they can be named and never priced. It also
carries the one other fact the owner asked for: halal. "Prefer halal restaurants and hotels" is honoured only from a
source, so ``halal_fact`` answers only for a property whose own page was quoted; no source means no tag, and no tag
never means "not halal".
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DATA_PATH = Path(__file__).parent / "data" / "watchlist.json"


@dataclass(frozen=True)
class HalalFact:
    tag: str
    source_url: str
    read_on: str


@dataclass(frozen=True)
class WatchEntry:
    name: str
    area: str
    kind: str
    url: str
    read_on: str
    seaplane_required: bool = False
    seaplane_source_url: str = ""
    halal: Optional[HalalFact] = None


def _key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name).lower())


def load_watchlist(path: Path = DATA_PATH) -> tuple[WatchEntry, ...]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    entries = []
    for item in raw.get("entries", []) if isinstance(raw, dict) else []:
        halal = item.get("halal")
        fact = None
        if isinstance(halal, dict) and str(halal.get("source_url", "")).startswith("https://") and halal.get("tag"):
            fact = HalalFact(str(halal["tag"]), str(halal["source_url"]), str(halal.get("read_on", "")))
        entries.append(WatchEntry(
            name=str(item["name"]), area=str(item.get("area", "")), kind=str(item.get("kind", "")),
            url=str(item.get("url", "")), read_on=str(item.get("read_on", "")),
            seaplane_required=bool(item.get("seaplane_required", False)),
            seaplane_source_url=str(item.get("seaplane_source_url", "")), halal=fact))
    return tuple(entries)


def halal_fact(name: str) -> Optional[HalalFact]:
    """The sourced halal tag for a property, or ``None`` when no source says so."""
    wanted = _key(name)
    if not wanted:
        return None
    for entry in load_watchlist():
        if entry.halal is not None and _key(entry.name) in (wanted,):
            return entry.halal
    return None
