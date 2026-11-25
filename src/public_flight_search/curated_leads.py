"""Deal ideas from public curator pages, matched to the trip's own dates (owner, 21 Nov 2026).

"Scrape these deals to get ideas of cheap deals ... and any dates that match mine." A deal curator's link page
(a Linktree) lists hand-picked package deals as affiliate short links. The short link's own redirect header
names the operator search it points to, and that search's address carries the departure airport, date, nights
and party, so the dates are read without ever requesting the operator's page.

What this is not: a price read. The figure is the curator's own, per person for the party in the link, at the
time they posted it. A lead never prices a card; the e-mail says so above the rows.
"""

from __future__ import annotations

import html as _html
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

from .weekly_fares import _H, _TD, _TH, _stamp, write_atomic

SCHEMA = "curated_leads/1"
DEFAULT_PATH = "data/curated_leads.json"
SOURCES_PATH = Path(__file__).parent / "data" / "curated_sources.json"
CONFIDENCE = "curator-posted"
#: A lead this many days either side of the departure window is "near": the same search is worth re-dating.
NEAR_DAYS = 14
#: The section is ideas, not a catalogue: the rows it may take in an e-mail Gmail clips near 102 KB.
MAX_ROWS = 12
MAX_UNDATED = 3
#: A file older than this is last week's page, so the section is left out rather than shown as current.
MAX_AGE_DAYS = 8
DEFAULT_BUDGET_SECONDS = 180
MAX_LINKS_PER_SOURCE = 120
#: Hosts that only forward. A link on one of these is asked for its redirect header; any other host is the
#: operator itself and is never requested.
TRACKER_HOSTS = ("tidd.ly", "awin1.com", "pxf.io", "prf.hn")
#: Query keys under which an affiliate network carries the operator address inside its own redirect.
_WRAPPED_KEYS = ("ued", "murl", "u", "url")
_TRACKING_KEYS = re.compile(r"^(utm_.*|awc|label|source|sv1|sv_campaign_id|ito|usr_src|irclickid|platform)$", re.I)
_USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
               "Chrome/131.0.0.0 Safari/537.36")
_BOARDS = {"AI": "All inclusive", "FB": "Full board", "HB": "Half board", "BB": "Breakfast", "RO": "Room only",
           "SC": "Self catering"}
_ICELOLLY = re.compile(r"^/holiday-search/v2/results/(?P<dest>[^/]+)/(?P<airports>[A-Z]{3}(?:\+[A-Z]{3})*)/"
                       r"(?P<date>\d{4}-\d{2}-\d{2})/(?P<nights>\d{1,2})/(?P<party>\d+(?:\+\d+)*)/?$")
_EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\U000027BF\u2B00-\u2BFF\uFE0F\u200D\u20E3]")


# --------------------------------------------------------------------------------------------- the curator page

def load_sources(path: Path = SOURCES_PATH, env: Mapping[str, str] = os.environ) -> list[dict]:
    """The curator pages to read: ``CURATED_LEAD_SOURCES`` (comma-separated https addresses) or the data file."""
    listed = [u.strip() for u in str(env.get("CURATED_LEAD_SOURCES", "")).split(",") if u.strip()]
    if listed:
        raw = [{"name": urlsplit(u).path.strip("/") or urlsplit(u).netloc, "url": u} for u in listed]
    else:
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8")).get("sources", [])
        except (OSError, ValueError, AttributeError):
            raw = []
    return [{"name": str(s.get("name") or s["url"]), "url": str(s["url"])} for s in raw
            if isinstance(s, dict) and str(s.get("url", "")).startswith("https://")]


def parse_linktree(page: str) -> list[dict]:
    """``[{title, url}]`` from a Linktree page's own embedded data; an unreadable page is an empty list."""
    found = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page or "", re.S)
    if not found:
        return []
    try:
        links = json.loads(found.group(1))["props"]["pageProps"]["links"]
    except (ValueError, KeyError, TypeError):
        return []
    out: list[dict] = []

    def take(items: Any) -> None:
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict) or len(out) >= MAX_LINKS_PER_SOURCE:
                continue
            title, url = str(item.get("title") or "").strip(), str(item.get("url") or "").strip()
            if title and url.startswith("https://"):
                out.append({"title": title, "url": url})
            take(item.get("children"))

    take(links)
    return out


def parse_title(title: str) -> dict:
    """What a curator's link title states: the name, the price and its basis, stars and board.

    ``basis`` is ``pppn`` (per person per night), ``pp`` or empty when the title names no basis; nothing is
    assumed for a bare "£89".
    """
    text = re.sub("(\\d)\\s*[\u2B50\u2605\u2606]\uFE0F?", r"\1* ", str(title or ""))
    text = re.sub(r"\s+", " ", _EMOJI.sub(" ", text)).strip()
    price: Optional[float] = None
    basis = ""
    # A deposit ("£29pp deposit") and a struck-through figure ("was £699") are prices of something else.
    priced = [m for m in re.finditer(r"£\s*(\d[\d,]*)(?:\.\d\d)?\s*(pppn|pp\b|p\b)?|\b(\d{2,4})\s*(pppn|pp)\b",
                                     text, re.I)
              if not re.match(r"\s*deposit\b", text[m.end():], re.I)
              and not re.search(r"\b(?:was|save|deposit(?: of)?)\s*$", text[:m.start()], re.I)]
    if priced:
        last = priced[-1]
        price = float((last.group(1) or last.group(3)).replace(",", ""))
        unit = (last.group(2) or last.group(4) or "").lower()
        basis = "pppn" if unit == "pppn" else ("pp" if unit else "")
        before = re.sub(r"[\s\-–:,(]*(?:from|now)?\s*$", "", text[:last.start()], flags=re.I)
        after = re.sub(r"^[\s\-–:,/)]+", "", text[last.end():])
        text = re.sub(r"\s+", " ", f"{before} {after}").strip() or text
    stars = re.search(r"\b([3-5])\s*\*", text)
    lowered = text.lower()
    board = ("Ultra all inclusive" if re.search(r"ultra (all )?inclusive", lowered)
             else "All inclusive" if "all inclusive" in lowered
             else "Half board" if "half board" in lowered
             else "Breakfast" if re.search(r"breakfast|b&b", lowered) else "")
    return {"title": text[:90], "price_gbp": price, "basis": basis,
            "stars": int(stars.group(1)) if stars else None, "board": board}


# ------------------------------------------------------------------------------------------ the link behind it

def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def _is_tracker(url: str) -> bool:
    host = _host(url)
    return any(host == t or host.endswith("." + t) for t in TRACKER_HOSTS)


def _query_pairs(query: str) -> list[tuple[str, str]]:
    """Query pairs decoded with ``unquote`` (never ``unquote_plus``): a "+" in an operator path is a real plus."""
    pairs = []
    for part in query.split("&"):
        key, _, value = part.partition("=")
        if key:
            pairs.append((unquote(key), unquote(value)))
    return pairs


def wrapped_target(location: str) -> str:
    """The operator address an affiliate redirect carries in its own query, or empty."""
    for key, value in _query_pairs(urlsplit(location).query):
        if key in _WRAPPED_KEYS and value.startswith("https://"):
            return value
    return ""


def resolve(url: str, fetch_location: Callable[[str], str], *, max_hops: int = 4) -> str:
    """The operator address behind a short link, asking only forwarding hosts for their redirect header."""
    current = url
    for _ in range(max_hops):
        if not current.startswith("https://"):
            return ""
        if not _is_tracker(current):
            return current
        location = fetch_location(current)
        if not location:
            return ""
        current = wrapped_target(location) or urljoin(current, location)
    return current if current.startswith("https://") and not _is_tracker(current) else ""


def strip_tracking(url: str) -> str:
    parts = urlsplit(url)
    kept = "&".join(p for p in parts.query.split("&") if p and not _TRACKING_KEYS.match(p.partition("=")[0]))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, kept, ""))


def parse_operator_url(url: str) -> dict:
    """What the operator address itself says. Only shapes seen on a real curator link are read; others give
    the operator's name and nothing else, so a date is never guessed."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    name = host[4:] if host.startswith("www.") else host
    out: dict = {"operator": name.split(".")[0], "airports": [], "departure": "", "nights": 0, "party": "",
                 "board": "", "place_key": ""}
    shaped = _ICELOLLY.match(parts.path) if name == "icelolly.com" else None
    if shaped:
        try:
            date.fromisoformat(shaped["date"])
        except ValueError:
            return out
        if int(shaped["nights"]) <= 0:
            return out
        query = dict(_query_pairs(parts.query))
        out.update(airports=shaped["airports"].split("+"), departure=shaped["date"], nights=int(shaped["nights"]),
                   party=shaped["party"], board=_BOARDS.get(query.get("boardBases", "").upper(), ""),
                   # What makes two links one idea: the operator's ids for the place and the property the
                   # link pins, or for a link that pins none (the place's own search) its star and board filters.
                   place_key=":".join([shaped["dest"].split("+")[0]] + (
                       [query["pinnedAccommodationId"]] if query.get("pinnedAccommodationId")
                       else ["", query.get("ratings", ""), query.get("boardBases", "")])))
    return out


def party_words(party: str) -> str:
    """"2+8+4" is two adults and children aged 8 and 4."""
    bits = [b for b in str(party).split("+") if b.isdigit()]
    if not bits:
        return ""
    adults, children = int(bits[0]), len(bits) - 1
    words = f"{adults} adult{'s' if adults != 1 else ''}"
    return words + (f" + {children} child{'ren' if children != 1 else ''}" if children else "")


# ------------------------------------------------------------------------------------------- against the window

def window(config: Any) -> dict:
    outs = sorted(str(d) for d in getattr(config, "outbound_dates", ()) or ())
    return {"first": outs[0] if outs else "", "last": outs[-1] if outs else "",
            "min_nights": int(getattr(config, "min_nights", 0) or 0),
            "max_nights": int(getattr(config, "max_nights", 0) or 0),
            "origins": [str(o).upper() for o in getattr(config, "origins", ()) or ()]}


def classify(lead: Mapping[str, Any], win: Mapping[str, Any], today: date) -> tuple[str, str]:
    """``(fit, note)``: match, near, idea, past or undated, and for a near lead what differs from the window."""
    if not lead.get("departure"):
        return "undated", ""
    leaves = date.fromisoformat(lead["departure"])
    if leaves < today:
        return "past", ""
    if not win.get("first"):
        return "idea", ""
    first, last = date.fromisoformat(win["first"]), date.fromisoformat(win["last"])
    from_home = bool(set(lead.get("airports") or ()) & set(win.get("origins") or ()))
    nights_fit = win["min_nights"] <= int(lead.get("nights") or 0) <= win["max_nights"]
    inside = first <= leaves <= last
    if inside and nights_fit and from_home:
        return "match", ""
    if from_home and first - timedelta(days=NEAR_DAYS) <= leaves <= last + timedelta(days=NEAR_DAYS):
        if inside:
            when = "inside your window"
        elif leaves < first:
            gap = (first - leaves).days
            when = f"{gap} day{'s' if gap != 1 else ''} before your window"
        else:
            gap = (leaves - last).days
            when = f"{gap} day{'s' if gap != 1 else ''} after your window"
        if not nights_fit:
            when += f", {lead.get('nights')} nights (yours {win['min_nights']}-{win['max_nights']})"
        return "near", when
    return "idea", ""


def your_dates_url(lead: Mapping[str, Any], win: Mapping[str, Any]) -> tuple[str, str]:
    """``(address, label)`` for the same operator search moved to the window's first date and home airports.

    Every part keeps a form seen on a posted link (airports joined by "+", the party as posted), and the
    stay is 14 nights when the window allows it, else its shortest. Empty when the lead is not re-datable.
    """
    if lead.get("operator") != "icelolly" or not win.get("first") or not win.get("origins"):
        return "", ""
    parts = urlsplit(str(lead.get("operator_url", "")))
    shaped = _ICELOLLY.match(parts.path)
    if not shaped:
        return "", ""
    nights = 14 if win["min_nights"] <= 14 <= win["max_nights"] else win["min_nights"]
    path = (f"/holiday-search/v2/results/{shaped['dest']}/{'+'.join(win['origins'])}/{win['first']}/"
            f"{nights}/{shaped['party']}")
    first = date.fromisoformat(win["first"])
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, "")), f"{first.day} {first:%b} · {nights}n"


def per_person_total(lead: Mapping[str, Any]) -> Optional[float]:
    """The posted price per person for the whole stay; a per-night price needs the nights from the link."""
    price = lead.get("price_gbp")
    if price is None:
        return None
    if lead.get("basis") == "pppn":
        return float(price) * int(lead["nights"]) if lead.get("nights") else None
    return float(price)


def read_curated_leads(config: Any, sources: Sequence[Mapping[str, str]], fetch_page: Callable[[str], str],
                       fetch_location: Callable[[str], str], *, now: Optional[datetime] = None,
                       budget_seconds: Optional[float] = None,
                       clock: Callable[[], float] = time.monotonic) -> dict:
    """Read every source page and the redirect header of each of its links; classify against the config."""
    now = now or datetime.now(timezone.utc)
    win = window(config)
    started = clock()
    leads: list[dict] = []
    read_sources: list[dict] = []
    for source in sources:
        if budget_seconds is not None and clock() - started >= budget_seconds:
            read_sources.append({"name": source["name"], "url": source["url"], "links": 0})
            continue
        links = parse_linktree(fetch_page(source["url"]))
        read_sources.append({"name": source["name"], "url": source["url"], "links": len(links)})
        for link in links:
            stated = parse_title(link["title"])
            if stated["price_gbp"] is None:
                continue  # a link with no price is a signpost, not a deal
            out_of_time = budget_seconds is not None and clock() - started >= budget_seconds
            operator_url = "" if out_of_time else resolve(link["url"], fetch_location)
            lead = {**stated, "link": link["url"], "source": source["name"], "source_url": source["url"],
                    "observed_at": now.isoformat(timespec="seconds"), "confidence_label": CONFIDENCE,
                    "operator_url": strip_tracking(operator_url) if operator_url else "",
                    **parse_operator_url(operator_url)}
            if not lead["board"]:
                lead["board"] = stated["board"]
            lead["fit"], lead["fit_note"] = classify(lead, win, now.date())
            lead["your_dates_url"], lead["your_dates_label"] = (
                your_dates_url(lead, win) if lead["fit"] in ("near", "idea") else ("", ""))
            leads.append(lead)
    return {"schema": SCHEMA, "generated_at": now.isoformat(timespec="seconds"),
            "travellers": int(getattr(config, "travellers", 0) or 0), "window": win,
            "sources": read_sources, "leads": leads}


# ------------------------------------------------------------------------------------------------- the network

def _request(url: str) -> urllib.request.Request:
    return urllib.request.Request(url, headers={
        "User-Agent": _USER_AGENT, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.9", "Accept-Encoding": "identity"})


def fetch_page(url: str) -> str:
    try:
        with urllib.request.urlopen(_request(url), timeout=30) as response:
            return response.read(4_000_000).decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError, ValueError):
        return ""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def make_location_fetch(delay: float = 0.5) -> Callable[[str], str]:
    """Ask a forwarding host where a link goes, without following it, at a polite gap."""
    opener = urllib.request.build_opener(_NoRedirect)
    last = [0.0]

    def fetch(url: str) -> str:
        wait = delay * random.uniform(0.8, 1.4) - (time.monotonic() - last[0])
        if last[0] and wait > 0:
            time.sleep(wait)
        try:
            with opener.open(_request(url), timeout=10):
                return ""
        except urllib.error.HTTPError as error:
            return str(error.headers.get("Location") or "") if 300 <= error.code < 400 else ""
        except (urllib.error.URLError, OSError, ValueError):
            return ""
        finally:
            last[0] = time.monotonic()

    return fetch


# -------------------------------------------------------------------------------------------------- the section

def load_curated_leads(path: str = DEFAULT_PATH, now: Optional[datetime] = None) -> Optional[dict]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        return None
    read = _stamp(payload.get("generated_at"))
    now = now or datetime.now(timezone.utc)
    return payload if read and now - read <= timedelta(days=MAX_AGE_DAYS) else None


def _gbp(value: float) -> str:
    return f"£{value:,.0f}"


def _day(iso: str, *, year: bool = False) -> str:
    try:
        when = date.fromisoformat(str(iso)[:10])
    except ValueError:
        return "?"
    return f"{when.day} {when:%b}" + (f" {when.year}" if year else "")


def _price_words(lead: Mapping[str, Any]) -> str:
    unit = {"pppn": " pp/night", "pp": " pp"}.get(str(lead.get("basis")), "")
    return _gbp(float(lead["price_gbp"])) + unit


def _airport_words(airports: Sequence[str], home: Sequence[str]) -> str:
    """The trip's own airports first when the link offers them; a long list is cut and counted."""
    mine = [a for a in airports if a in home]
    listed = mine or list(airports)
    more = len(airports) - len(listed[:4])
    return ", ".join(listed[:4]) + (f" +{more} more" if more > 0 else "")


def _safe_link(url: Any) -> str:
    url = str(url or "")
    return url if url.startswith("https://") else ""


def shown_rows(payload: Mapping[str, Any]) -> list[dict]:
    """The dated rows the section shows: every match, then near, then 5-star-first cheapest ideas, capped.

    An idea is shown once per place (three links to one resort from three airports are one idea, the
    cheapest) and only when it leaves from one of the trip's own airports.
    """
    home = set((payload.get("window") or {}).get("origins") or ())
    order = {"match": 0, "near": 1, "idea": 2}

    def key(lead: Mapping[str, Any]) -> tuple:
        total = per_person_total(lead)
        return (order[lead["fit"]], -int(lead.get("stars") or 0) if lead["fit"] == "idea" else 0,
                total if total is not None else float("inf"), str(lead.get("departure")))

    rows: list[dict] = []
    places: set[str] = set()
    for lead in sorted((l for l in payload.get("leads", []) if l.get("fit") in order), key=key):
        if lead["fit"] == "idea":
            if home and not home & set(lead.get("airports") or ()):
                continue
            place = str(lead.get("place_key") or lead.get("title"))
            if place in places:
                continue
        places.add(str(lead.get("place_key") or lead.get("title")))
        rows.append(lead)
    return rows[:MAX_ROWS]


def _counts(payload: Mapping[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for lead in payload.get("leads", []):
        counts[lead.get("fit", "")] = counts.get(lead.get("fit", ""), 0) + 1
    return counts


def _caption(payload: Mapping[str, Any]) -> str:
    counts = _counts(payload)
    win = payload.get("window") or {}
    travellers = int(payload.get("travellers") or 0)
    names = ", ".join(str(s.get("name")) for s in payload.get("sources", []))
    dated = counts.get("match", 0) + counts.get("near", 0) + counts.get("idea", 0)
    text = (f"Posted by {names}, read {_day(payload.get('generated_at', ''))}: {len(payload.get('leads', []))} "
            f"priced links, {dated} with dates still ahead. Prices are the curator's own for the party in the "
            f"link, as posted; this run did not check them and they are not a price for "
            f"{travellers or 'your party'}.")
    if win.get("first"):
        span = (f"{_day(win['first'])} to {_day(win['last'], year=True)}, "
                f"{win['min_nights']}-{win['max_nights']} nights")
        matches, near = counts.get("match", 0), counts.get("near", 0)
        text += (f" {matches} fit{'s' if matches == 1 else ''} your window ({span}); "
                 f"{near} within {NEAR_DAYS} days of it.")
    if counts.get("past"):
        text += f" {counts['past']} posted for a date that has passed are left out."
    return text


def _undated(payload: Mapping[str, Any]) -> list[dict]:
    rows = [l for l in payload.get("leads", []) if l.get("fit") == "undated" and l.get("price_gbp") is not None]
    return sorted(rows, key=lambda l: float(l["price_gbp"]))


def render_section_html(payload: Optional[Mapping[str, Any]]) -> str:
    if not payload or not payload.get("leads"):
        return ""
    e = _html.escape
    rows = shown_rows(payload)
    undated = _undated(payload)
    if not rows and not undated:
        return ""
    out = [f'<div style="{_H}">Deal ideas from curators</div>',
           f'<div style="font-size:12px; color:#475569; margin-bottom:4px;">{e(_caption(payload))}</div>']
    if rows:
        home = list((payload.get("window") or {}).get("origins") or ())
        out.append('<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" '
                   'style="border-collapse:collapse; background:#FFFFFF;">')
        out.append(f'<tr><th style="{_TH}">Deal</th><th style="{_TH} text-align:right;">Posted</th></tr>')
        tags = {"match": "Fits your dates", "near": "Near your dates"}
        small = 'style="color:#475569; font-size:11px;"'
        for lead in rows:
            link = _safe_link(lead.get("link"))
            title = e(str(lead.get("title", "")))
            title = f'<a href="{e(link)}" style="color:#155f8f;">{title}</a>' if link else title
            when = " · ".join([_day(lead["departure"], year=True), f"{int(lead.get('nights') or 0)} nights",
                               "from " + _airport_words(lead.get("airports") or [], home)])
            detail = " · ".join(e(d) for d in (str(lead.get("board") or ""), party_words(str(lead.get("party", ""))),
                                               str(lead.get("operator") or "")) if d)
            tag = ""
            if lead["fit"] in tags:
                note = f": {e(str(lead['fit_note']))}" if lead.get("fit_note") else ""
                tag = f'<br><span style="color:#166534; font-size:11px; font-weight:700;">{tags[lead["fit"]]}{note}</span>'
            again = _safe_link(lead.get("your_dates_url"))
            yours = (f'<br><a href="{e(again)}" style="color:#155f8f; font-size:11px;">try '
                     f'{e(str(lead.get("your_dates_label", "")))}</a>' if again else "")
            out.append(f'<tr><td style="{_TD}"><strong>{title}</strong>{tag}<br><span {small}>{e(when)}</span>'
                       f'<br><span {small}>{detail}</span></td>'
                       f'<td style="{_TD} text-align:right; white-space:nowrap; vertical-align:top;">'
                       f'{e(_price_words(lead))}{yours}</td></tr>')
        out.append("</table>")
        if any(lead.get("your_dates_url") for lead in rows):
            out.append('<div style="font-size:11px; color:#64748B; margin-top:4px;">"Try" opens the operator\'s '
                       "same search moved to your first date and airports, with the party as posted; set your own "
                       "party on the page.</div>")
    if undated:
        names = []
        for lead in undated[:MAX_UNDATED]:
            link = _safe_link(lead.get("link"))
            label = f"{e(str(lead.get('title', '')))} {e(_price_words(lead))}"
            names.append(f'<a href="{e(link)}" style="color:#155f8f;">{label}</a>' if link else label)
        out.append(f'<div style="font-size:12px; color:#475569; margin-top:6px;">Also posted with dates chosen '
                   f"on the seller's page ({len(undated)}, cheapest first): " + "; ".join(names) + ".</div>")
    return "".join(out)


def render_section_text(payload: Optional[Mapping[str, Any]]) -> str:
    if not payload or not payload.get("leads"):
        return ""
    rows, undated = shown_rows(payload), _undated(payload)
    if not rows and not undated:
        return ""
    lines = ["Deal ideas from curators:", "  " + _caption(payload)]
    for lead in rows:
        tag = {"match": "[fits your dates] ", "near": "[near your dates] "}.get(lead["fit"], "")
        lines.append(f"  {tag}{lead.get('title', '')}: {_price_words(lead)}, {_day(lead['departure'], year=True)}, "
                     f"{int(lead.get('nights') or 0)} nights from {'/'.join(lead.get('airports') or [])}"
                     + (f" ({lead['fit_note']})" if lead.get("fit_note") else "") + f" · {lead.get('link', '')}")
    if undated:
        lines.append(f"  Also posted with dates chosen on the seller's page ({len(undated)}): "
                     + "; ".join(f"{l.get('title', '')} {_price_words(l)}" for l in undated[:MAX_UNDATED]))
    return "\n".join(lines)


def curated_sections(now: Optional[datetime] = None) -> tuple[str, str]:
    """HTML and text for the July body from the file the workflow lands; empty when there is none."""
    payload = load_curated_leads(os.environ.get("CURATED_LEADS_PATH", DEFAULT_PATH), now)
    return render_section_html(payload), render_section_text(payload)


def main(arguments: Sequence[str]) -> int:
    import argparse

    from .holidays import load_holiday_config

    parser = argparse.ArgumentParser(prog="curated-leads")
    parser.add_argument("--config", default="examples/july_holiday_config.json")
    parser.add_argument("--out", default=DEFAULT_PATH)
    parser.add_argument("--budget-seconds", type=float, default=DEFAULT_BUDGET_SECONDS,
                        help="stop asking where links go after this many seconds; later links stay undated")
    args = parser.parse_args(list(arguments))
    config = load_holiday_config(Path(args.config).read_text(encoding="utf-8"))
    payload = read_curated_leads(config, load_sources(), fetch_page, make_location_fetch(),
                                 budget_seconds=args.budget_seconds)
    write_atomic(args.out, payload)
    counts = _counts(payload)
    print(f"curated leads: {sum(s['links'] for s in payload['sources'])} links from {len(payload['sources'])} "
          f"source(s), {len(payload['leads'])} priced; "
          + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())), file=sys.stderr)
    return 0
