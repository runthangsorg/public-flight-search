"""The July e-mail body: confirmed prices and searches only, one compact card each (owner, 8 Nov 2026).

"the email is too dense and hard to read and repetitive. i only want confirmed prices and searches with links and
details of where you found what. confirmed package holidays can be included from real priced sites like tui, expedia,
etc."

A card is shown only for a figure that was READ: an operator package whose exact-date price the private engine read
(``package_evidence``), or a flight search whose price was read for the trip's own dates. Every card says what the
figure covers, where it was found (shop, link, the day it was read), the flights, the stay and one or two facts. No
catalogue estimate, range or "no reads loaded" line reaches the body; what could not be priced is one short list of
names at the end. Rule 4 (any leg over 8 hours is Business) decides which reads may be offered, and halal-friendly
properties (only where a source says so, ``watchlist.halal_fact``) come first among cards in the same £1,000 band.

Light backgrounds with dark text throughout: Gmail strips ``<body>`` styles.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from html import escape
from typing import Any, Mapping, Optional, Sequence
from urllib.parse import urlparse

from . import cabin as cabin_module
from . import watchlist as watchlist_module
from .package_evidence import PackagePrice

_NOT_NAMED = ("not named", "not read", "not collected", "unnamed")
_SHOPS = (("google.com/travel/flights", "Google Flights"), ("kayak.", "Kayak"), ("skyscanner.", "Skyscanner"),
          ("expedia.", "Expedia"), ("tui.", "TUI"), ("loveholidays.", "loveholidays"), ("onthebeach.", "On the Beach"),
          ("jet2", "Jet2"), ("destination2.", "Destination2"), ("ba.com", "BA Holidays"))


@dataclass(frozen=True)
class Card:
    kind: str            # "package" | "flights"
    title: str
    place: str
    nights: int
    dates: str
    total_gbp: float
    covers: str
    shop: str
    url: str
    read_on: str         # "8 Nov"
    flights: str
    hotel: str
    facts: tuple[str, ...]
    halal: str = ""


@dataclass(frozen=True)
class Digest:
    cards: tuple[Card, ...]
    not_priced: tuple[str, ...]
    watch: tuple[Any, ...] = ()
    refused: Mapping[str, str] = None  # type: ignore[assignment]


def _gbp(value: Any) -> str:
    try:
        return "£" + f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return "£0"


def _day(text: Any) -> str:
    try:
        d = datetime.fromisoformat(str(text)[:10])
    except ValueError:
        return ""
    return f"{d.day} {d.strftime('%b')}"


def _read_day(text: Any) -> str:
    try:
        d = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return "date unknown"
    return f"{d.day} {d.strftime('%b')}"


def shop_name(url: Any, vendor: Any = "") -> str:
    """The seller's name for a link: the read's own vendor when it names one, else from the host."""
    if str(vendor or "").strip() and str(vendor).strip().lower() not in ("google", "google-flights"):
        return str(vendor).strip().capitalize() if str(vendor).islower() else str(vendor).strip()
    text = str(url or "").lower()
    for needle, name in _SHOPS:
        if needle in text:
            return name
    host = urlparse(text).netloc.removeprefix("www.")
    return host or "the seller"


def _band(total: float) -> int:
    return int(total // 1000)


def _package_card(price: PackagePrice, budget: float) -> Optional[Card]:
    cabin = str(price.flight_cabin or "").upper()
    hours = cabin_module.resolve_flight_hours(price.destination_key, None)
    if cabin not in ("BUSINESS", "FIRST") and not (hours is not None and hours <= cabin_module.BUSINESS_FLIGHT_HOURS):
        return None
    fact = watchlist_module.halal_fact(price.property_name)
    facts = []
    if budget > 0:
        facts.append("fits the budget" if price.total_gbp <= budget else f"{_gbp(price.total_gbp - budget)} over the {_gbp(budget)} budget")
    if price.room_descriptions:
        facts.append("; ".join(price.room_descriptions[:2]))
    rooms = f"{price.rooms} room" + ("s" if price.rooms != 1 else "")
    return Card(
        kind="package", title=price.property_name, place=str(price.destination_key).replace("_", " ").title(),
        nights=int(price.nights), dates=f"{_day(price.outbound_date)} – {_day(price.return_date)}",
        total_gbp=float(price.total_gbp), covers=f"package: flights + hotel, {price.board}, {rooms}",
        shop=price.operator, url=price.source_url, read_on=_read_day(price.observed_at),
        flights=(price.flight_summary or f"flights included, {cabin.lower() or 'economy'}"),
        hotel=f"{price.property_name}, {price.board}", facts=tuple(facts), halal=fact.tag if fact else "")


def _stay_line(trip: Any) -> str:
    parts = []
    for stop in getattr(trip, "stops", ()) or ():
        hotel = str(getattr(stop, "hotel", "") or "")
        named = hotel and not any(w in hotel.lower() for w in _NOT_NAMED)
        label = f"{stop.place.split('(')[0].strip()} {int(stop.nights)}n"
        parts.append(f"{label}: {hotel.split(',')[0]}" if named else label)
    return "; ".join(parts)


def _trip_card(row: Mapping[str, Any]) -> Optional[Card]:
    reads = row.get("reads") or {}
    read = reads.get("economy") or reads.get("business")
    if not read:
        return None
    trip = row["trip"]
    try:
        total = float(read.get("total_gbp"))
    except (TypeError, ValueError):
        return None
    mixed = str(read.get("cabin", "")).upper() == "MIXED"
    cabin_words = ("Business on the long legs" if mixed else
                   "Business" if str(read.get("cabin", "")).upper() == "BUSINESS" else "Economy")
    bits = [str(read.get("carrier") or "").strip(), str(read.get("duration") or "").strip()]
    flights = f"{cabin_words}" + (": " + ", ".join(b for b in bits if b) if any(bits) else "")
    url = str(read.get("source_url") or row.get("url") or "")
    return Card(
        kind="flights", title=trip.title, place=" + ".join(s.place.split("(")[0].strip() for s in trip.stops),
        nights=int(row["nights"]), dates=f"{_day(row['outbound'])} – {_day(row['return'])}", total_gbp=total,
        covers="flights only, 5 people, stays not priced", shop=shop_name(url, read.get("vendor")), url=url,
        read_on=_read_day(read.get("observed_at")), flights=flights, hotel=_stay_line(trip),
        facts=((str(trip.why).strip(),) if str(getattr(trip, "why", "")).strip() else ()), halal="")


def build_digest(config: Any, *, rows: Sequence[Mapping[str, Any]], package_prices: Mapping[Any, PackagePrice],
                 watch: Optional[Sequence[Any]] = None, generated_at: str = "") -> Digest:
    budget = float(getattr(config, "max_budget_gbp", 0.0) or 0.0)
    cards: list[Card] = []
    not_priced: list[str] = []
    refused: dict[str, str] = {}
    for price in (package_prices or {}).values():
        card = _package_card(price, budget)
        if card is None:
            refused[price.property_name] = cabin_module_reason()
            not_priced.append(price.property_name)
        else:
            cards.append(card)
    for row in rows:
        card = _trip_card(row)
        if card is None:
            not_priced.append(row["trip"].title)
        else:
            cards.append(card)
    entries = tuple(watch) if watch is not None else watchlist_module.load_watchlist()
    not_priced.extend(e.name for e in entries)
    cards.sort(key=lambda c: (0 if c.kind == "package" else 1, _band(c.total_gbp), 0 if c.halal else 1, c.total_gbp))
    return Digest(cards=tuple(cards), not_priced=tuple(dict.fromkeys(not_priced)), watch=entries, refused=refused)


def cabin_module_reason() -> str:
    return "economy flights with a leg over 8 hours: needs a business read"


_INK, _MUTED, _LINE, _CARD, _ACCENT, _OK = "#1f2a30", "#4f5f67", "#d3dde2", "#f2f6f8", "#155f8f", "#1d5c30"


def _e(text: Any) -> str:
    return escape(str(text))


def _span(config: Any) -> str:
    outs = sorted(getattr(config, "outbound_dates", ()) or ())
    span = f"{_day(outs[0])}–{_day(outs[-1])}" if outs else ""
    return f"{int(getattr(config, 'travellers', 5))} travellers · leaving {span} · confirmed prices only"


def _card_html(c: Card) -> str:
    tag = (f' <span style="background:#dcf1e2; color:{_OK}; border-radius:9px; padding:1px 7px; font-size:12px; '
           f'font-weight:600;">{_e(c.halal)}</span>' if c.halal else "")
    facts = "".join(f'<div style="color:{_MUTED}; font-size:13px; margin-top:2px;">{_e(f)}</div>' for f in c.facts)
    link = f'<a href="{_e(c.url)}" style="color:{_ACCENT};">{_e(c.shop)}</a>' if c.url else _e(c.shop)
    return (f'<div style="background:{_CARD}; border:1px solid {_LINE}; border-left:5px solid #2b8fb3; border-radius:8px; '
            f'padding:10px 12px; margin:10px 0; color:{_INK}; font-size:14px; line-height:1.45;">'
            f'<div style="font-size:16px; font-weight:700;">{_e(c.title)}{tag}</div>'
            f'<div style="color:{_MUTED}; font-size:13px;">{c.nights} nights · {_e(c.dates)}</div>'
            f'<div style="margin-top:4px;"><span style="font-size:20px; font-weight:700; color:{_INK};">{_gbp(c.total_gbp)}</span>'
            f' for 5 <span style="color:{_MUTED};">· {_e(c.covers)}</span></div>'
            f'<div>Found: {link} · read {_e(c.read_on)}</div>'
            f'<div>Flights: {_e(c.flights)}</div>'
            + (f'<div>Hotel: {_e(c.hotel)}</div>' if c.hotel else "") + facts + '</div>')


def _not_priced_html(digest: Digest) -> str:
    if not digest.not_priced:
        return ""
    gili = [e.name for e in digest.watch if "Gili" in e.area]
    maldives = [e.name for e in digest.watch if "Maldives" in e.area]
    watched = set(gili) | set(maldives)
    others = [n for n in digest.not_priced if n not in watched]
    lines = []
    if others:
        lines.append(_e(", ".join(others)))
    if gili:
        lines.append(f"Gili Islands: {_e(', '.join(gili))}")
    if maldives:
        lines.append(f"Maldives (seaplane transfer needed, to be priced in): {_e(', '.join(maldives))}")
    return (f'<h2 style="font-size:16px; margin:22px 0 6px; color:{_INK};">Not yet priced</h2>'
            f'<div style="font-size:13px; color:{_MUTED}; line-height:1.5;">' + "<br>".join(lines) + "</div>")


def render_digest_html(config: Any, digest: Digest, *, generated_at: str, attachment_name: str = "") -> str:
    title = _e(getattr(config, "report_title", "July holiday watch"))
    packages = [c for c in digest.cards if c.kind == "package"]
    searches = [c for c in digest.cards if c.kind == "flights"]
    out = [f'<div style="max-width:720px; margin:0 auto; padding:14px 16px; background:#ffffff; color:{_INK}; '
           f'font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">',
           f'<h1 style="font-size:21px; margin:4px 0 4px; color:#3C4C55;">{title}</h1>',
           f'<div style="color:{_MUTED}; font-size:13px;">{_e(_span(config))} · checked {_e(_read_day(generated_at))}</div>']
    if packages:
        out.append(f'<h2 style="font-size:16px; margin:20px 0 4px; color:{_INK};">Confirmed packages</h2>')
        out.extend(_card_html(c) for c in packages)
    if searches:
        out.append(f'<h2 style="font-size:16px; margin:20px 0 4px; color:{_INK};">Flight searches, flights only</h2>')
        out.extend(_card_html(c) for c in searches)
    if not digest.cards:
        out.append(f'<div style="margin:16px 0; color:{_INK};">Nothing confirmed this week: no package or flight price was read for the trip dates.</div>')
    out.append(_not_priced_html(digest))
    if attachment_name:
        out.append(f'<div style="font-size:12px; color:{_MUTED}; margin-top:16px;">Full trip pages for every option are '
                   f'attached: {_e(attachment_name)}</div>')
    out.append("</div>")
    return "".join(out)


def render_digest_text(config: Any, digest: Digest, *, generated_at: str, attachment_name: str = "") -> str:
    lines = [str(getattr(config, "report_title", "July holiday watch")),
             f"{_span(config)} · checked {_read_day(generated_at)}", ""]
    for c in digest.cards:
        lines += [f"{c.title}{' [' + c.halal + ']' if c.halal else ''}",
                  f"  {c.nights} nights · {c.dates} · {_gbp(c.total_gbp)} for 5 · {c.covers}",
                  f"  Found: {c.shop} · read {c.read_on} · {c.url}", f"  Flights: {c.flights}"]
        if c.hotel:
            lines.append(f"  Hotel: {c.hotel}")
        lines += [f"  {f}" for f in c.facts] + [""]
    if not digest.cards:
        lines += ["Nothing confirmed this week: no package or flight price was read for the trip dates.", ""]
    if digest.not_priced:
        lines += ["Not yet priced: " + ", ".join(digest.not_priced)]
    if attachment_name:
        lines += ["", f"Full trip pages for every option are attached: {attachment_name}"]
    return "\n".join(lines) + "\n"
