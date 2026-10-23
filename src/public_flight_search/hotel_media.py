"""A photo and each site's own guest rating for every property the reports show: the data the e-mail hot-links.

Two PUBLIC data files sit beside ``multi_centre.json``; ``tools/hotel_research.py`` writes them by hand on a laptop and it
is never run in CI or at send time:

* ``hotel_images.json`` (``hotel_images/1``): ``{"properties": {<normalised name>: {name, image_url, page_url, source}}}``,
  one VERIFIED photo per property (HTTP 200, an ``image/*`` content type, a sensible size). A property whose photo could
  not be verified has no entry: there is never a placeholder and never a stock photo of somewhere else;
* ``hotel_reviews.json`` (``hotel_reviews/1``): ``{"properties": {<normalised name>: {name, ratings: [...], not_read: {...}}}}``
  where each rating is one site's own figure (``source``, ``score``, ``scale``, ``count``, ``observed_at``, ``source_url``)
  and ``not_read`` says, for a site that gave nothing, why ("wall: ...", "no page found", "no read").

Keys are ``hotel_evidence.normalise_property_name`` of the property's name, the same normalisation every other lookup in
this package uses, so a rating read here meets the one the private evidence holds for the same hotel.

Nothing in this module reaches the network or the clock. It is read once by the job and handed to the renderers as a
``HotelMedia``; a renderer given ``None`` shows no photo and no researched rating, exactly as one given no fares prices
no trip. A missing, unreadable or wrongly shaped file is an empty ``HotelMedia``: the report is then what it was before
photos existed. Ratings are never converted or averaged: Booking is out of 10, Google and TripAdvisor out of 5, and each
is shown on its own scale.
"""

from __future__ import annotations

import json
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from .hotel_evidence import HotelRating, normalise_property_name

DATA_DIR = Path(__file__).with_name("data")
DEFAULT_IMAGES_PATH = str(DATA_DIR / "hotel_images.json")
DEFAULT_REVIEWS_PATH = str(DATA_DIR / "hotel_reviews.json")

IMAGES_SCHEMA = "hotel_images/1"
REVIEWS_SCHEMA = "hotel_reviews/1"

#: The order sites are shown in; any other source follows, alphabetically.
SITE_ORDER = ("Google", "TripAdvisor", "Booking")

#: Query-string keys a stored URL may never carry: they identify a visitor, a click or a session.
TRACKING_KEYS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid", "msclkid", "aid", "sid",
    "label", "ref", "affid", "affiliate", "token", "session", "sessionid", "cid", "src",
})


def url_is_clean(url: Any) -> bool:
    """An https page or picture with no fragment and no tracking parameter."""
    parts = urllib.parse.urlsplit(str(url or ""))
    if parts.scheme != "https" or not parts.netloc or parts.fragment:
        return False
    for key, _value in urllib.parse.parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() in TRACKING_KEYS or key.lower().startswith("utm_"):
            return False
    return True


@dataclass(frozen=True)
class HotelMedia:
    """The researched photos and ratings, by normalised property name."""

    images: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    ratings: Mapping[str, tuple[HotelRating, ...]] = field(default_factory=dict)
    not_read: Mapping[str, Mapping[str, str]] = field(default_factory=dict)

    def image_for(self, name: str) -> Optional[Mapping[str, str]]:
        """``{"image_url", "page_url", "source", "name"}`` for a property with a verified photo, else ``None``."""
        return self.images.get(normalise_property_name(name))

    def ratings_for(self, name: str) -> tuple[HotelRating, ...]:
        return self.ratings.get(normalise_property_name(name), ())

    def not_read_for(self, name: str) -> Mapping[str, str]:
        """``{"booking": "wall: http-202", ...}``: the sites that gave nothing, and why. Empty when none was recorded."""
        return self.not_read.get(normalise_property_name(name), {})


EMPTY = HotelMedia()


def _read_json(path: str, schema: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict) or payload.get("schema") != schema:
        return {}
    props = payload.get("properties")
    return props if isinstance(props, dict) else {}


def _rating_from(name: str, item: Any) -> Optional[HotelRating]:
    if not isinstance(item, dict):
        return None
    try:
        score = float(item["score"])
        scale = float(item.get("scale") or 5)
    except (KeyError, TypeError, ValueError):
        return None
    source = str(item.get("source", "")).strip()
    url = str(item.get("source_url", "")).strip()
    if not source or scale <= 0 or not (0 < score <= scale) or not url_is_clean(url):
        return None
    return HotelRating(
        property_name=name, source=source, score=score, scale=scale,
        review_count=str(item.get("count", "") or "").strip(), where="researched page",
        source_url=url, observed_at=str(item.get("observed_at", "") or ""),
    )


def load_hotel_media(images_path: str = DEFAULT_IMAGES_PATH, reviews_path: str = DEFAULT_REVIEWS_PATH) -> HotelMedia:
    """Read both data files; an entry that fails a rule is dropped, never repaired. Missing files give ``EMPTY``."""
    images: dict[str, dict[str, str]] = {}
    for key, item in _read_json(images_path, IMAGES_SCHEMA).items():
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        image, page = str(item.get("image_url", "")), str(item.get("page_url", ""))
        if name and normalise_property_name(name) == key and url_is_clean(image) and url_is_clean(page):
            images[key] = {"name": name, "image_url": image, "page_url": page, "source": str(item.get("source", ""))}
    ratings: dict[str, tuple[HotelRating, ...]] = {}
    not_read: dict[str, dict[str, str]] = {}
    for key, item in _read_json(reviews_path, REVIEWS_SCHEMA).items():
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name or normalise_property_name(name) != key:
            continue
        rows = tuple(r for r in (_rating_from(name, raw) for raw in item.get("ratings") or ()) if r is not None)
        if rows:
            ratings[key] = merge_ratings(rows)
        reasons = item.get("not_read")
        if isinstance(reasons, dict):
            not_read[key] = {str(k).lower(): str(v) for k, v in reasons.items()}
    return HotelMedia(images=images, ratings=ratings, not_read=not_read)


def _site_rank(source: str) -> tuple[int, str]:
    for index, site in enumerate(SITE_ORDER):
        if source.casefold() == site.casefold():
            return index, ""
    return len(SITE_ORDER), source.casefold()


def merge_ratings(*groups: Sequence[HotelRating]) -> tuple[HotelRating, ...]:
    """Every site's own figure, the NEWEST read per site, in the order Google, TripAdvisor, Booking, then the rest.

    One figure per site: two reads of one site are two looks at one number, and only the newer is a statement about now.
    Figures from different sites are never combined: there is no average and no "overall" rating anywhere.
    """
    best: dict[str, HotelRating] = {}
    for group in groups:
        for rating in group or ():
            key = str(rating.source).casefold()
            if key not in best or str(rating.observed_at) > str(best[key].observed_at):
                best[key] = rating
    return tuple(sorted(best.values(), key=lambda r: _site_rank(str(r.source))))


__all__ = [
    "DEFAULT_IMAGES_PATH", "DEFAULT_REVIEWS_PATH", "EMPTY", "HotelMedia", "load_hotel_media", "merge_ratings",
    "url_is_clean",
]
