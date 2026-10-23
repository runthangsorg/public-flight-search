#!/usr/bin/env python3
"""Research a verified photo and the guest ratings of every property the July and December reports can show.

RUN BY HAND, ON A LAPTOP. Never in CI and never at send time: the e-mail only hot-links what this wrote down.

    /home/kc/dealsearch/.venv/bin/python tools/hotel_research.py --evidence-dir <dir with the private evidence files>

It writes two PUBLIC data files beside ``multi_centre.json`` (URLs and plain facts only, no captured HTML):

* ``src/public_flight_search/data/hotel_images.json`` (schema ``hotel_images/1``): one verified photo per property;
* ``src/public_flight_search/data/hotel_reviews.json`` (schema ``hotel_reviews/1``): each site's own rating, scale,
  review count, read date and page, and, for a site that gave nothing, why ("walled", "no page found").

WHAT IT DOES, PER PROPERTY
1. One web search for the property (public results page) to find its pages: Booking.com, TripAdvisor, Agoda, its own
   site, an operator's page. A search that is refused stops the search lane; it is never retried around.
2. Reads each page through the dealsearch repo's own fetch lane with ``allow_render=False``: plain HTTP only, no browser,
   so a JS challenge is never solved. A page that walls (DataDome, an AWS WAF 202, a 403/429) is recorded as a wall and
   that source is left empty for the property; after three walls in a row a site is not asked again this run.
3. Takes the photo from the page's ``og:image``, the rating from its JSON-LD ``aggregateRating``, and keeps either only
   if the page is the property's own (its title names the property) and the value passes the checks below.
4. VERIFIES a photo: the URL answers HTTP 200 with an ``image/*`` content type and the picture is at least 400 x 240
   (or, with no image library, at least 20 KB). A property without a verified photo gets NO entry: never a placeholder.
5. Brings in ratings an earlier read already holds: Google and Accor figures from the private hotel evidence
   (``--evidence-dir``) and TripAdvisor figures from ``research/hotel_facts.json``, each with its own read date.

Nothing is ever averaged or converted: Booking is out of 10, Google and TripAdvisor out of 5, and each figure is kept on
its own scale. A rating that could not be read stays absent.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from public_flight_search.hotel_evidence import normalise_property_name  # noqa: E402

DATA = ROOT / "src" / "public_flight_search" / "data"
IMAGES_PATH = DATA / "hotel_images.json"
REVIEWS_PATH = DATA / "hotel_reviews.json"

MIN_WIDTH, MIN_HEIGHT, MIN_BYTES_WITHOUT_PIL = 400, 240, 20_000
WALL_STOP_AFTER = 3

#: Sites that are not a property's own page, or its operator's: they are searched for but never taken as "official".
_AGGREGATORS = (
    "booking.com", "tripadvisor.", "agoda.", "expedia.", "hotels.com", "trip.com", "kayak.", "trivago.", "skyscanner.",
    "facebook.", "instagram.", "youtube.", "wikipedia.", "twitter.", "x.com", "pinterest.", "lonelyplanet.", "viator.",
    "getyourguide.", "airbnb.", "google.", "bing.", "yelp.", "mapcarta.", "hotelscombined.", "momondo.", "priceline.",
    "orbitz.", "travelocity.", "ostrovok.", "makemytrip.", "klook.", "tiktok.", "reddit.", "linkedin.",
)
#: Hosts of tour operators whose pages describe a lodge: a photo from one is labelled "operator".
OPERATOR_HOSTS = ("kuoni", "tourcompass", "rainbowtours", "africanmeccasafaris", "african-pride", "safari.co.za",
                  "kenyasafari", "siyabona", "krugerpark", "sanparks", "hotelguide")
#: A photo URL that names one of these is a logo or an icon, not a hotel.
_NOT_A_PHOTO = ("logo", "favicon", "icon", "sprite", "placeholder", ".svg", "avatar", "badge")
#: Words that carry no name: stripped before checking that a page's title names the property.
_STOPWORDS = {"hotel", "resort", "the", "spa", "and", "by", "a", "de", "of", "in", "at", "villas", "villa", "suites",
              "suite", "lodge", "camp", "beach", "club", "collection", "luxury", "all", "inclusive", "golf"}
#: Query-string keys a stored URL may never carry: they identify a visitor, a click or a session.
TRACKING_KEYS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid", "msclkid",
                 "aid", "sid", "label", "ref", "affid", "affiliate", "token", "session", "sessionid", "cid", "src"}


# ---------------------------------------------------------------------------
# Pure helpers (tested without a network)
# ---------------------------------------------------------------------------

def clean_url(url: str) -> str:
    """The URL without a fragment and without tracking parameters; ``""`` when it is not an https page."""
    parts = urllib.parse.urlsplit(str(url or "").strip())
    if parts.scheme != "https" or not parts.netloc:
        return ""
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
             if k.lower() not in TRACKING_KEYS and not k.lower().startswith("utm_")]
    return urllib.parse.urlunsplit(("https", parts.netloc, parts.path, urllib.parse.urlencode(query), ""))


def host_of(url: str) -> str:
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def classify_page(url: str) -> str:
    """``booking`` | ``tripadvisor`` | ``agoda`` | ``expedia`` | ``other`` | ``skip`` for a search-result URL."""
    host, path = host_of(url), urllib.parse.urlsplit(url).path
    if host.endswith("booking.com"):
        return "booking" if "/hotel/" in path else "skip"
    if "tripadvisor." in host:
        return "tripadvisor" if "Hotel_Review" in path else "skip"
    if "agoda." in host:
        return "agoda" if "/hotel/" in path else "skip"
    if "expedia." in host:
        return "expedia" if "Hotel-Information" in path else "skip"
    if any(token in host for token in _AGGREGATORS):
        return "skip"
    return "other"


def search_results(html: str) -> list[str]:
    """The result links of a DuckDuckGo HTML results page, in order, redirects unwrapped."""
    out: list[str] = []
    for match in re.finditer(r'class="result__a"[^>]*href="([^"]+)"', html):
        href = unescape(match.group(1))
        if "uddg=" in href:
            href = urllib.parse.unquote(href.split("uddg=", 1)[1].split("&", 1)[0])
        if href.startswith("//"):
            href = "https:" + href
        if href.startswith("https://") and href not in out:
            out.append(href)
    return out


def _meta(html: str, prop: str) -> str:
    for pattern in (rf'<meta[^>]+(?:property|name)=["\']{re.escape(prop)}["\'][^>]*content=["\']([^"\']+)["\']',
                    rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\']{re.escape(prop)}["\']'):
        found = re.search(pattern, html, flags=re.I)
        if found:
            return unescape(found.group(1)).strip()
    return ""


def og_image(html: str, base_url: str) -> str:
    """The page's ``og:image`` (or ``twitter:image``) as an absolute https URL, or ``""``."""
    raw = _meta(html, "og:image:secure_url") or _meta(html, "og:image") or _meta(html, "twitter:image")
    if not raw:
        return ""
    return urllib.parse.urljoin(base_url, raw) if not raw.startswith("//") else "https:" + raw


def image_candidates(html: str, base_url: str, limit: int = 8) -> list[str]:
    """Photo URLs on a page, best first: its ``og:image``, then a JSON-LD ``image``, then the first ``<img>`` tags.

    Absolute https URLs only, logos and icons dropped, each once. The caller verifies them in order and keeps the first
    that is a real photograph, so the order only decides which is tried first.
    """
    found: list[str] = []

    def add(raw: str) -> None:
        raw = unescape(str(raw or "")).strip()
        if not raw or raw.startswith("data:"):
            return
        absolute = urllib.parse.urljoin(base_url, raw) if not raw.startswith("//") else "https:" + raw
        if looks_like_a_photo_url(absolute) and absolute not in found:
            found.append(absolute)

    add(og_image(html, base_url))
    for block in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, flags=re.I | re.S):
        try:
            payload = json.loads(block.strip())
        except ValueError:
            continue
        stack = [payload]
        while stack:
            node = stack.pop(0)
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                image = node.get("image")
                for item in (image if isinstance(image, list) else [image]):
                    add(item.get("url") if isinstance(item, dict) else item)
                stack.extend(v for v in node.values() if isinstance(v, (dict, list)))
    for tag in re.findall(r"<img\b[^>]*>", html, flags=re.I):
        srcset = re.search(r'srcset=["\']([^"\']+)["\']', tag, flags=re.I)
        if srcset:
            add(srcset.group(1).split(",")[-1].strip().split(" ")[0])
        for attr in ("data-src", "data-lazy-src", "src"):
            found_attr = re.search(rf'{attr}=["\']([^"\']+)["\']', tag, flags=re.I)
            if found_attr:
                add(found_attr.group(1))
    return found[:limit]


def page_title(html: str) -> str:
    found = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.I | re.S)
    return unescape(re.sub(r"\s+", " ", found.group(1))).strip() if found else ""


def _tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", re.sub(r"[^\x00-\x7f]", lambda m: m.group(0), str(text).lower()))
    return {w for w in words if w not in _STOPWORDS and len(w) > 1}


def title_names_property(name: str, title: str, url: str = "") -> bool:
    """Whether a page is about this property: most of its distinctive words are in the title or the URL.

    A page that merely came back from a search is not evidence: ``Ocean Paradise Resort`` can be several hotels. The
    check is deliberately plain: at least 60% of the name's distinctive words (and at least one) must appear.
    """
    wanted = _tokens(name)
    if not wanted:
        return False
    haystack = _tokens(title) | _tokens(urllib.parse.unquote(url))
    haystack |= {re.sub(r"[^a-z0-9]", "", w) for w in haystack}
    hit = sum(1 for w in wanted if w in haystack)
    return hit >= 1 and hit / len(wanted) >= 0.6


def looks_like_a_photo_url(url: str) -> bool:
    return bool(url) and url.startswith("https://") and not any(word in url.lower() for word in _NOT_A_PHOTO)


def aggregate_rating(html: str) -> Optional[dict[str, Any]]:
    """``{"score", "best", "count"}`` from the page's JSON-LD ``aggregateRating``, or ``None``.

    Needs a rating value AND a review count: a bare "4" with no count says nothing a reader can weigh. A count of
    zero, a score outside 0..best or a non-numeric value is refused rather than repaired.
    """
    for block in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', html, flags=re.I | re.S):
        try:
            payload = json.loads(block.strip())
        except ValueError:
            continue
        stack = [payload]
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
                continue
            if not isinstance(node, dict):
                continue
            stack.extend(v for v in node.values() if isinstance(v, (dict, list)))
            agg = node.get("aggregateRating")
            if isinstance(agg, dict):
                found = _parse_aggregate(agg)
                if found:
                    return found
    return None


def _parse_aggregate(agg: Mapping[str, Any]) -> Optional[dict[str, Any]]:
    try:
        score = float(str(agg.get("ratingValue")).replace(",", "."))
        count = int(float(str(agg.get("reviewCount") or agg.get("ratingCount") or "").replace(",", "")))
        best = float(str(agg.get("bestRating") or 5).replace(",", "."))
    except (TypeError, ValueError):
        return None
    if count < 1 or best <= 0 or not (0 < score <= best):
        return None
    return {"score": score, "best": best, "count": count}


def verify_image(url: str, fetch_head: Callable[[str], Mapping[str, Any]]) -> tuple[bool, str]:
    """``(ok, why)``: HTTP 200, ``image/*``, and a sensible size.

    ``fetch_head`` returns ``{"status", "content_type", "length", "body"}`` (body may be empty); it is injected so the
    rule is tested without a network. Dimensions are read with Pillow when it is installed; without it the picture
    must be at least ``MIN_BYTES_WITHOUT_PIL`` bytes, because a tracking pixel or an icon is smaller than that.
    """
    result = fetch_head(url)
    if int(result.get("status") or 0) != 200:
        return False, f"http {result.get('status')}"
    ctype = str(result.get("content_type") or "").lower()
    if not ctype.startswith("image/") or "svg" in ctype:
        return False, f"content type {ctype or 'none'}"
    body = result.get("body") or b""
    length = int(result.get("length") or len(body) or 0)
    try:
        from io import BytesIO

        from PIL import Image  # type: ignore

        if body:
            width, height = Image.open(BytesIO(body)).size
            if width < MIN_WIDTH or height < MIN_HEIGHT:
                return False, f"too small ({width}x{height})"
            return True, f"{width}x{height}"
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001 - an unreadable picture is not a photo
        return False, f"unreadable picture ({type(exc).__name__})"
    return (length >= MIN_BYTES_WITHOUT_PIL, f"{length} bytes")


def registrable_domain(host: str) -> str:
    """``kalandara-resort.hotels-in-lombok.com`` -> ``hotels-in-lombok.com`` (and ``x.co.uk`` -> ``x.co.uk``)."""
    labels = host.lower().split(".")
    if len(labels) >= 3 and labels[-2] in ("co", "com", "org", "net", "gov", "ac") and len(labels[-1]) == 2:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def source_label(page_url: str, name: str) -> str:
    """Where a photo's page comes from: ``booking`` | ``tripadvisor`` | ``agoda`` | ``official`` | ``operator`` | ``other``.

    ``official`` only when the page's own registrable domain STARTS with a distinctive word of the property's name
    (``novotellombok.com``); a sub-domain of somebody else's site that merely names the hotel
    (``kalandara-resort.hotels-in-lombok.com``) is ``other``.
    """
    host = host_of(page_url)
    if host.endswith("booking.com"):
        return "booking"
    if "tripadvisor." in host:
        return "tripadvisor"
    if "agoda." in host:
        return "agoda"
    brand = re.sub(r"[^a-z0-9]", "", registrable_domain(host).split(".")[0])
    # The site's own name starts with a distinctive word of the property's ("novotellombok", "kirurumu"): a directory
    # that merely contains a place name ("hotelsinlombok") is not the property's site.
    if any(len(token) > 3 and brand.startswith(token) for token in _tokens(name)):
        return "official"
    if any(op in host for op in OPERATOR_HOSTS):
        return "operator"
    return "other"


def google_page(name: str, area: str = "") -> str:
    """The clean Google Hotels search for a property: its name, nothing about dates or a visitor."""
    query = f"{name} {area}".strip()
    return "https://www.google.com/travel/search?" + urllib.parse.urlencode({"q": query, "hl": "en-GB"})


# ---------------------------------------------------------------------------
# What to research
# ---------------------------------------------------------------------------

def properties_to_cover() -> dict[str, dict[str, str]]:
    """Every property name the reports can show, keyed by normalised name, with a place to search it in.

    The resort cards (both seasons' catalogues) and every named lodge of ``multi_centre.json``, computed from the
    repository so the list cannot drift from what the e-mail prints.
    """
    from public_flight_search import holidays as hol
    from public_flight_search.multi_centre import load_multi_centre

    out: dict[str, dict[str, str]] = {}
    for catalog in (hol.SUMMER_RESORT_CATALOG, hol.WINTER_RESORT_CATALOG):
        for key, resorts in catalog.items():
            area = hol.HOLIDAY_SEARCH_QUERIES.get(key, key.replace("_", " "))
            for resort in resorts:
                out.setdefault(normalise_property_name(resort["name"]), {"name": resort["name"], "area": area, "kind": "resort"})
    for season in ("summer", "winter"):
        for trip in load_multi_centre(season=season):
            for stop in trip.stops:
                for lodge in stop.lodges:
                    out.setdefault(normalise_property_name(lodge.name),
                                   {"name": lodge.name, "area": lodge.area or stop.place.split("(")[0].strip(), "kind": "lodge",
                                    "known_page": lodge.url})
    return out


# ---------------------------------------------------------------------------
# Earlier reads that already exist
# ---------------------------------------------------------------------------

def evidence_ratings(evidence_dir: Path) -> dict[str, list[dict[str, Any]]]:
    """Google and Accor ratings the private hotel evidence holds, newest per site, with a clean page and the read date."""
    path = evidence_dir / "holiday_hotel_evidence.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for item in payload.get("ratings", []):
        source = str(item.get("source", "")).strip()
        if source not in ("Google", "Accor"):
            continue
        key = normalise_property_name(item.get("property_name", ""))
        try:
            score, scale = float(item["score"]), float(item.get("scale") or 5)
        except (KeyError, TypeError, ValueError):
            continue
        record = {"source": source, "score": score, "scale": scale, "count": str(item.get("review_count", "")).strip(),
                  "observed_at": str(item.get("observed_at", "")), "name": str(item.get("property_name", ""))}
        if (key, source) not in best or record["observed_at"] > best[(key, source)]["observed_at"]:
            best[(key, source)] = record
    out: dict[str, list[dict[str, Any]]] = {}
    for (key, _source), record in best.items():
        out.setdefault(key, []).append(record)
    return out


def tripadvisor_ratings(path: Path) -> dict[str, dict[str, Any]]:
    """The TripAdvisor figures ``research/hotel_facts.json`` holds (read 15 Oct), each with the page it names."""
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, dict[str, Any]] = {}
    for hotel in payload.get("hotels", []):
        rating = hotel.get("guest_rating") or {}
        if str(rating.get("site", "")).lower() != "tripadvisor" or not rating.get("source", "").startswith("https://"):
            continue
        out[normalise_property_name(hotel["name"])] = {
            "source": "TripAdvisor", "score": float(rating["score"]), "scale": float(rating.get("scale") or 5),
            "count": f"{int(rating['count']):,}", "observed_at": str(payload.get("generated_at", "")),
            "source_url": clean_url(rating["source"]),
        }
    return out


# ---------------------------------------------------------------------------
# The live part
# ---------------------------------------------------------------------------

class Researcher:
    def __init__(self, *, pace: float = 2.0, log: Callable[[str], None] = print) -> None:
        sys.path.insert(0, "/home/kc/dealsearch")
        from dealfinder.retail_fetch import StealthFetcher

        self.fetcher = StealthFetcher()
        self.pace = pace
        self.log = log
        self.walls: dict[str, int] = {}
        self.stopped: set[str] = set()
        self.tally: dict[str, dict[str, int]] = {}

    def _count(self, site: str, what: str) -> None:
        self.tally.setdefault(site, {}).setdefault(what, 0)
        self.tally[site][what] += 1

    def fetch(self, url: str, site: str):
        """One plain-HTTP fetch of a public page; a wall is recorded, three in a row stop that site for the run."""
        if site in self.stopped:
            return None, "wall: not asked again this run after repeated walls"
        time.sleep(self.pace)
        result = self.fetcher.fetch_with_escalation(url, kind="html", allow_render=False)
        if result.ok:
            self.walls[site] = 0
            return result, ""
        reason = result.blocked_reason or f"http {result.status_code}"
        self._count(site, "wall")
        self.walls[site] = self.walls.get(site, 0) + 1
        if self.walls[site] >= WALL_STOP_AFTER and site in ("booking", "tripadvisor", "expedia", "search"):
            self.stopped.add(site)
            self.log(f"  [{site}] {WALL_STOP_AFTER} walls in a row ({reason}): not asked again this run")
        return None, f"wall: {reason}"

    def search(self, query: str) -> list[str]:
        result, why = self.fetch("https://html.duckduckgo.com/html/?q=" + urllib.parse.quote_plus(query), "search")
        return search_results(result.text) if result else []

    def head_image(self, url: str) -> Mapping[str, Any]:
        try:
            from curl_cffi import requests as creq  # the dealsearch lane's own HTTP client

            response = creq.get(url, impersonate="safari18_0", timeout=25, headers={"Accept": "image/avif,image/webp,image/*,*/*"})
            return {"status": response.status_code, "content_type": response.headers.get("content-type", ""),
                    "length": len(response.content), "body": response.content[:4_000_000]}
        except Exception as exc:  # noqa: BLE001
            return {"status": 0, "content_type": "", "length": 0, "body": b"", "error": type(exc).__name__}

    def research(self, key: str, info: Mapping[str, str], earlier: Mapping[str, Any]) -> dict[str, Any]:
        name, area = info["name"], info.get("area", "")
        found: dict[str, Any] = {"image": None, "ratings": [], "not_read": {}}
        pages: dict[str, list[str]] = {"booking": [], "tripadvisor": [], "agoda": [], "expedia": [], "other": []}
        for url in ([info["known_page"]] if info.get("known_page", "").startswith("https://") else []):
            pages["other"].append(url)
        for url in self.search(f"{name} {area}".strip()):
            kind = classify_page(url)
            if kind != "skip" and url not in pages[kind]:
                pages[kind].append(url)
        # 1. the three sites the owner named, then Agoda and the operator's/own page for a photo
        for site in ("booking", "tripadvisor"):
            read = None
            if not pages[site]:
                found["not_read"][site] = "no page found"
                continue
            for url in pages[site][:2]:
                result, why = self.fetch(url, site)
                if result is None:
                    found["not_read"][site] = why
                    continue
                if not title_names_property(name, page_title(result.text), url):
                    found["not_read"][site] = "page was not this property"
                    continue
                read = self._read_page(site, url, result, name, found)
                break
            if read is None and site not in found["not_read"]:
                found["not_read"][site] = "page gave no rating"
        # 2. every other source that can give a photo, in order, until one is verified
        pages["other"].sort(key=lambda u: 0 if source_label(u, name) == "official" else 1)
        for site in ("agoda", "other"):
            for url in pages[site][:4]:
                if found["image"] and site == "agoda":
                    break
                result, why = self.fetch(url, site)
                if result is None:
                    self._count(site, "wall")
                    continue
                if not title_names_property(name, page_title(result.text), url):
                    continue
                self._read_page(site, url, result, name, found)
        for site in ("booking", "tripadvisor"):
            if not found["ratings"] or all(r["source"].lower() != site for r in found["ratings"]):
                found["not_read"].setdefault(site, "not read")
        return found

    def _read_page(self, site: str, url: str, result, name: str, found: dict[str, Any]) -> bool:
        base = clean_url(result.final_url or url) or clean_url(url)
        got = False
        if not found["image"]:
            for candidate in image_candidates(result.text, base):
                ok, why = verify_image(candidate, self.head_image)
                self._count(site, "photo_ok" if ok else "photo_rejected")
                if ok:
                    found["image"] = {"image_url": clean_url(candidate) or candidate, "page_url": base,
                                      "source": source_label(base, name), "verified": why}
                    got = True
                    break
        agg = aggregate_rating(result.text)
        label = {"booking": "Booking", "tripadvisor": "TripAdvisor", "agoda": "Agoda"}.get(site)
        if agg and label:
            found["ratings"].append({"source": label, "score": agg["score"], "scale": agg["best"], "count": f"{agg['count']:,}",
                                     "observed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                                     "source_url": base})
            self._count(site, "rating_ok")
            got = True
        elif agg and site == "other":
            found.setdefault("operator_rating", {"source": host_of(base), "score": agg["score"], "scale": agg["best"],
                                                 "count": f"{agg['count']:,}",
                                                 "observed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                                                 "source_url": base})
        return got


def build_files(researched: Mapping[str, Mapping[str, Any]], properties: Mapping[str, Mapping[str, str]],
                google_and_accor: Mapping[str, list], tripadvisor: Mapping[str, Mapping[str, Any]],
                *, today: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """The two data documents, from what was read live and what earlier reads hold. Pure: no network."""
    images: dict[str, Any] = {}
    reviews: dict[str, Any] = {}
    for key, info in properties.items():
        live = researched.get(key) or {"image": None, "ratings": [], "not_read": {}}
        if live.get("image"):
            image = live["image"]
            images[key] = {"name": info["name"], "image_url": image["image_url"], "page_url": image["page_url"],
                           "source": source_label(image["page_url"], info["name"])}
        ratings = {r["source"]: dict(r) for r in live.get("ratings", [])}
        for record in google_and_accor.get(key, []):
            if record["source"] == "Google":
                ratings.setdefault("Google", {"source": "Google", "score": record["score"], "scale": record["scale"],
                                              "count": record["count"], "observed_at": record["observed_at"],
                                              "source_url": google_page(info["name"], info.get("area", ""))})
        if key in tripadvisor and "TripAdvisor" not in ratings:
            ratings["TripAdvisor"] = dict(tripadvisor[key])
        # An operator's or Accor's own figure is added only where none of Google, TripAdvisor or Booking has one.
        if not any(site in ratings for site in ("Google", "TripAdvisor", "Booking")):
            for record in google_and_accor.get(key, []):
                if record["source"] == "Accor":
                    ratings["Accor"] = {"source": "Accor", "score": record["score"], "scale": record["scale"],
                                        "count": record["count"], "observed_at": record["observed_at"],
                                        "source_url": ""}
            if "Accor" not in ratings and live.get("operator_rating"):
                ratings[live["operator_rating"]["source"]] = live["operator_rating"]
            if "Agoda" in ratings:
                pass
        ratings = {s: r for s, r in ratings.items() if r.get("source_url", "").startswith("https://")}
        not_read = {site: why for site, why in (live.get("not_read") or {}).items() if site not in {s.lower() for s in ratings}}
        if "Google" not in ratings:
            not_read["google"] = "no read"
        if ratings or not_read:
            reviews[key] = {"name": info["name"], "ratings": sorted(ratings.values(), key=lambda r: r["source"]),
                            "not_read": dict(sorted(not_read.items()))}
    return ({"schema": "hotel_images/1", "researched_on": today, "properties": dict(sorted(images.items()))},
            {"schema": "hotel_reviews/1", "researched_on": today, "properties": dict(sorted(reviews.items()))})


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--evidence-dir", type=Path, required=True, help="directory holding holiday_hotel_evidence.json")
    parser.add_argument("--only", default="", help="research just this property name (substring)")
    parser.add_argument("--pace", type=float, default=2.0, help="seconds between requests")
    parser.add_argument("--progress", type=Path, default=Path("/dev/shm/hotel_research_progress.json"))
    parser.add_argument("--reverse", action="store_true", help="work from the end of the list (a second process can meet the first)")
    parser.add_argument("--also-progress", type=Path, action="append", default=[],
                        help="another run's progress file: its properties are skipped, and merged into the output")
    parser.add_argument("--merge-only", action="store_true", help="research nothing; build the files from the progress files")
    args = parser.parse_args(list(argv) if argv is not None else None)

    properties = properties_to_cover()
    if args.only:
        properties = {k: v for k, v in properties.items() if args.only.lower() in v["name"].lower()}
    print(f"{len(properties)} properties to research")
    researcher = Researcher(pace=args.pace) if not args.merge_only else None
    researched: dict[str, Any] = {}
    if args.progress.exists():
        researched = json.loads(args.progress.read_text(encoding="utf-8"))
    others: dict[str, Any] = {}
    for other in args.also_progress:
        if other.exists():
            others.update(json.loads(other.read_text(encoding="utf-8")))
    order = list(properties.items())
    if args.reverse:
        order.reverse()
    for index, (key, info) in enumerate(order, start=1):
        if args.merge_only:
            break
        # Re-read the other run's file each time: what it has finished is not done twice.
        for other in args.also_progress:
            if other.exists():
                try:
                    others.update(json.loads(other.read_text(encoding="utf-8")))
                except ValueError:
                    pass
        if key in researched or key in others:
            continue
        print(f"[{index}/{len(properties)}] {info['name']}", flush=True)
        researched[key] = researcher.research(key, info, {})
        args.progress.write_text(json.dumps(researched), encoding="utf-8")
        got = researched[key]
        print(f"    photo={'yes' if got['image'] else 'no'} ratings={[r['source'] for r in got['ratings']]} not_read={got['not_read']}", flush=True)
    researched = {**others, **researched}
    images, reviews = build_files(researched, properties, evidence_ratings(args.evidence_dir),
                                  tripadvisor_ratings(ROOT / "research" / "hotel_facts.json"),
                                  today=datetime.now(timezone.utc).date().isoformat())
    if not args.only:
        IMAGES_PATH.write_text(json.dumps(images, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        REVIEWS_PATH.write_text(json.dumps(reviews, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("tally", json.dumps(researcher.tally if researcher else {}))
    print(f"photos: {len(images['properties'])}/{len(properties)}; properties with a rating: "
          f"{sum(1 for v in reviews['properties'].values() if v['ratings'])}/{len(properties)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
