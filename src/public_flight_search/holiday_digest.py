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

Since 14 Nov 2026 (owner: "massively improve it, design, intuitiveness ... itineraries") a trip whose flights AND every
planned night's stay were read is ONE trip-total card: the figure, what it is made of, the budget it is measured
against, and the itinerary day by day with each stay's own price, seller and link (``trip_totals``). A trip with only
some stays read says which nights are still open; a trip with flights alone is one compact row, not a card. The summary
at the top answers "what can we book, and for how much" before any card is opened.

Light backgrounds with dark text throughout: Gmail strips ``<body>`` styles.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from html import escape
from typing import Any, Mapping, Optional, Sequence
from urllib.parse import urlparse

from . import cabin as cabin_module
from . import trip_totals
from . import watchlist as watchlist_module
from .package_evidence import PackagePrice
from .trip_totals import StayPrice

_NOT_NAMED = ("not named", "not read", "not collected", "unnamed")
_SHOPS = (("google.com/travel/flights", "Google Flights"), ("kayak.", "Kayak"), ("skyscanner.", "Skyscanner"),
          ("expedia.", "Expedia"), ("tui.", "TUI"), ("loveholidays.", "loveholidays"), ("onthebeach.", "On the Beach"),
          ("jet2", "Jet2"), ("destination2.", "Destination2"), ("ba.com", "BA Holidays"))




@dataclass(frozen=True)
class Card:
    #: "package" (an operator's price), "trip" (flights + every stay read), "part" (flights + some stays read),
    #: "flights" (flights read, no stay read) or "stay" (a watch-list stay read, flights not included).
    kind: str
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
    #: The trip's dated stays, priced or not (``trip_totals.StayPrice``); empty for a package or a watch-list stay.
    stays: tuple[StayPrice, ...] = ()
    flights_gbp: Optional[float] = None
    stays_gbp: float = 0.0
    nights_priced: int = 0
    nights_planned: int = 0
    #: One line per flight of the read ("27 Jun London → Zanzibar · Economy · Carrier · 1 stop · 14h 30m").
    legs: tuple[str, ...] = ()
    why: str = ""
    catch: str = ""
    budget: float = 0.0
    travellers: int = 5

    @property
    def fits(self) -> Optional[bool]:
        """Whether the WHOLE trip fits the budget; None when the figure is not a whole trip (or no budget is set)."""
        if self.kind not in ("package", "trip") or self.budget <= 0:
            return None
        return self.total_gbp <= self.budget


@dataclass(frozen=True)
class Pending:
    """Something named but not priced, with the reason and a link that opens the search."""

    name: str
    reason: str = ""
    url: str = ""
    group: str = ""      # "" | "Gili Islands" | "Maldives"


@dataclass(frozen=True)
class Digest:
    cards: tuple[Card, ...]
    not_priced: tuple[str, ...]
    watch: tuple[Any, ...] = ()
    refused: Mapping[str, str] = None  # type: ignore[assignment]
    pending: tuple[Pending, ...] = ()


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


def _package_card(price: PackagePrice, budget: float, travellers: int) -> Optional[Card]:
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
        hotel=f"{price.property_name}, {price.board}", facts=tuple(facts), halal=fact.tag if fact else "",
        budget=budget, travellers=travellers)


def _stay_line(trip: Any) -> str:
    parts = []
    for stop in getattr(trip, "stops", ()) or ():
        hotel = str(getattr(stop, "hotel", "") or "")
        named = hotel and not any(w in hotel.lower() for w in _NOT_NAMED)
        label = f"{stop.place.split('(')[0].strip()} {int(stop.nights)}n"
        parts.append(f"{label}: {hotel.split(',')[0]}" if named else label)
    return "; ".join(parts)


_CABIN_WORDS = {"BUSINESS": "Business", "FIRST": "First", "PREMIUM_ECONOMY": "Premium economy", "ECONOMY": "Economy"}


def _stops_words(stops: Any) -> str:
    try:
        count = int(stops)
    except (TypeError, ValueError):
        return ""
    return "nonstop" if count == 0 else f"{count} stop" + ("s" if count != 1 else "")


def _leg_lines(read: Mapping[str, Any]) -> tuple[str, ...]:
    """One line per flight the read itemises; empty when it itemises none (then the summary line stands alone)."""
    lines = []
    for flight in read.get("flights") or ():
        if not isinstance(flight, Mapping):
            continue
        origin, destination = str(flight.get("origin") or ""), str(flight.get("destination") or "")
        if not (origin and destination):
            continue
        bits = [f"{_day(flight.get('departure_local'))} {origin} → {destination}".strip(),
                _CABIN_WORDS.get(str(flight.get("cabin") or "").upper(), ""),
                str(flight.get("carrier") or "").strip(), _stops_words(flight.get("stops")),
                str(flight.get("duration") or "").strip()]
        lines.append(" · ".join(b for b in bits if b))
    return tuple(lines)


#: Said on every card whose stay total is a nightly figure times the nights, because a hotel's own
#: booking page may add taxes and resort fees on top of what Google showed.
DERIVED_TOTAL_NOTE = ("stay totals are the nightly price shown times the nights; "
                      "taxes and resort fees may be added at booking")


def _has_derived_stay(cards: Sequence[Card]) -> bool:
    """True when any card in this section has a priced stay whose total is a nightly figure x nights.

    The sentence about that is printed ONCE per section, in its caption: repeated inside every card
    it read as a footnote to nothing (14 Nov 2026).
    """
    return any(stay.priced and stay.derived_total for card in cards for stay in card.stays)


def _section_caption(sub: str, cards: Sequence[Card]) -> str:
    """A section's sub-caption, with the derived-total sentence once when its rows need it."""
    return f"{sub} {DERIVED_TOTAL_NOTE}" if _has_derived_stay(cards) else sub


def _room_only_part(nights: int) -> str:
    """How a card names the nights it priced from a room-only read."""
    return f"{nights} nights room only, no meals" if nights != 1 else "1 night room only, no meals"


def _trip_card(row: Mapping[str, Any], hotel_rates: Optional[Mapping[Any, Any]] = None, *,
               budget: float = 0.0, travellers: int = 5,
               room_only_rates: Optional[Mapping[Any, Any]] = None) -> Optional[Card]:
    reads = row.get("reads") or {}
    read = reads.get("economy") or reads.get("business")
    if not read:
        return None
    trip = row["trip"]
    try:
        flights_total = float(read.get("total_gbp"))
    except (TypeError, ValueError):
        return None
    try:
        nights = (datetime.fromisoformat(str(row["return"])[:10]) - datetime.fromisoformat(str(row["outbound"])[:10])).days
    except ValueError:
        nights = int(row["nights"])
    mixed = str(read.get("cabin", "")).upper() == "MIXED"
    cabin_words = ("Business on the long legs" if mixed else
                   "Business" if str(read.get("cabin", "")).upper() == "BUSINESS" else "Economy")
    bits = [str(read.get("carrier") or "").strip(), str(read.get("duration") or "").strip()]
    flights = f"{cabin_words}" + (": " + ", ".join(b for b in bits if b) if any(bits) else "")
    url = str(read.get("source_url") or row.get("url") or "")
    # A run may have only room-only reads for this trip's nights (every Google Hotels row states no meal), so
    # the card is priced whenever EITHER load has anything: `trip_total` prefers the breakfast read.
    priced = (trip_totals.trip_total(row, hotel_rates, flights_gbp=flights_total,
                                     room_only_rates=room_only_rates)
              if (hotel_rates or room_only_rates) else None)
    facts = (((f"stays are planned for {int(row['nights'])} of the {nights} nights",) if int(row["nights"]) != nights else ())
             + ((str(trip.why).strip(),) if str(getattr(trip, "why", "")).strip() else ()))
    common = dict(
        title=trip.title, place=" + ".join(s.place.split("(")[0].strip() for s in trip.stops), nights=nights,
        dates=f"{_day(row['outbound'])} – {_day(row['return'])}", shop=shop_name(url, read.get("vendor")), url=url,
        read_on=_read_day(read.get("observed_at")), flights=flights, hotel=_stay_line(trip), facts=facts, halal="",
        flights_gbp=flights_total, legs=_leg_lines(read), why=str(getattr(trip, "why", "") or "").strip(),
        catch=str(getattr(trip, "catch", "") or "").strip(), budget=budget, travellers=travellers)
    people = f"{travellers} people"
    if priced is not None and priced.complete and priced.nights_planned == nights:
        return Card(kind="trip", total_gbp=float(priced.total_gbp),
                    covers=(f"trip total, {people}: flights + every night's stay"
                            + (f" ({_room_only_part(priced.room_only_nights)})" if priced.room_only_nights else "")),
                    stays=priced.stays,
                    stays_gbp=priced.stays_gbp, nights_priced=priced.nights_priced,
                    nights_planned=priced.nights_planned, **common)
    if priced is not None and priced.any_stay_priced:
        return Card(kind="part", total_gbp=flights_total + priced.stays_gbp,
                    covers=(f"flights + {priced.nights_priced} of {nights} nights' stay, {people}; "
                            f"the other nights are not priced"
                            + (f"; {priced.room_only_nights} nights room only" if priced.room_only_nights else "")),
                    stays=priced.stays, stays_gbp=priced.stays_gbp, nights_priced=priced.nights_priced,
                    nights_planned=priced.nights_planned, **common)
    return Card(kind="flights", total_gbp=flights_total, covers=f"flights only, {people}, stays not priced",
                stays=priced.stays if priced is not None else (), **common)


def _watch_card(entry: Any, pair: Optional[tuple[str, str]], hotel_rates: Optional[Mapping[Any, Any]], *,
                travellers: int,
                room_only_rates: Optional[Mapping[Any, Any]] = None) -> Optional[Card]:
    if not (pair and (hotel_rates or room_only_rates)):
        return None
    rate = trip_totals._rate_for(hotel_rates, entry.name, pair[0], pair[1], room_only_rates)
    if rate is None:
        return None
    nights = (datetime.fromisoformat(pair[1]) - datetime.fromisoformat(pair[0])).days
    stay = StayPrice(place=str(entry.area), property_name=str(entry.name), check_in=pair[0], check_out=pair[1],
                     nights=nights, total_gbp=float(rate.price_gbp), board=str(rate.board or ""),
                     seller=trip_totals._seller(rate), source_url=str(rate.source_url or ""),
                     observed_at=str(rate.observed_at or ""), unit="; ".join(tuple(rate.units or ())[:2]),
                     two_rooms=str(rate.booking_shape or "") == "two_rooms_one_booking",
                     unit_guests=tuple(getattr(rate, "unit_guests", ()) or ()),
                     derived_total=bool(getattr(rate, "derived_total", False)),
                     property_url=str(entry.url or ""))
    facts = []
    if getattr(entry, "seaplane_required", False):
        facts.append("reached by seaplane: the transfer is charged by the resort and is not in this figure")
    return Card(kind="stay", title=str(entry.name), place=str(entry.area), nights=nights,
                dates=f"{_day(pair[0])} – {_day(pair[1])}", total_gbp=float(rate.price_gbp),
                covers=(f"stay only, {travellers} people, "
                        f"{(stay.board_words or 'board as stated') + (' (no meals)' if stay.board == 'RO' else '')}; "
                        "flights not included"),
                shop=stay.seller, url=stay.source_url, read_on=_read_day(stay.observed_at), flights="",
                hotel=stay.unit, facts=tuple(facts), halal=entry.halal.tag if getattr(entry, "halal", None) else "",
                stays=(stay,), stays_gbp=float(rate.price_gbp), nights_priced=nights, nights_planned=nights,
                travellers=travellers)


def _stays_only_card(row: Mapping[str, Any], hotel_rates: Optional[Mapping[Any, Any]],
                     room_only_rates: Optional[Mapping[Any, Any]], *, budget: float, travellers: int,
                     reason: str) -> Optional[Card]:
    """A trip with dated stays read but no accepted fare: a partly priced card, flights not priced.

    The stays are real, dated and bookable, so they belong on a card even when no fare may be
    shown; before this the trip was only a name under "Not yet priced" and the one thing a reader
    could act on was invisible. It is never a whole trip, even with every night priced, because
    the flights are still missing.
    """
    if not (hotel_rates or room_only_rates):
        return None
    trip = row["trip"]
    priced = trip_totals.trip_total(row, hotel_rates, flights_gbp=None, room_only_rates=room_only_rates)
    if priced is None or not priced.any_stay_priced:
        return None
    try:
        nights = (datetime.fromisoformat(str(row["return"])[:10]) - datetime.fromisoformat(str(row["outbound"])[:10])).days
    except ValueError:
        nights = int(row["nights"])
    facts = (((f"stays are planned for {int(row['nights'])} of the {nights} nights",) if int(row["nights"]) != nights else ())
             + ((str(trip.why).strip(),) if str(getattr(trip, "why", "")).strip() else ()))
    people = f"{travellers} people"
    return Card(
        kind="part", total_gbp=float(priced.stays_gbp),
        covers=(f"{priced.nights_priced} of {nights} nights' stay, {people}; flights not priced yet"
                + (f"; {priced.room_only_nights} nights room only" if priced.room_only_nights else "")),
        stays=priced.stays, stays_gbp=priced.stays_gbp, nights_priced=priced.nights_priced,
        nights_planned=priced.nights_planned,
        title=trip.title, place=" + ".join(s.place.split("(")[0].strip() for s in trip.stops), nights=nights,
        dates=f"{_day(row['outbound'])} – {_day(row['return'])}", shop="", url=str(row.get("url") or ""),
        read_on="", flights=f"not priced; {reason}", hotel=_stay_line(trip), facts=facts, halal="",
        flights_gbp=None, legs=(), why=str(getattr(trip, "why", "") or "").strip(),
        catch=str(getattr(trip, "catch", "") or "").strip(), budget=budget, travellers=travellers)


_KIND_ORDER = {"trip": 0, "package": 1, "part": 2, "stay": 3, "flights": 4}


def _reference_pair(config: Any) -> Optional[tuple[str, str]]:
    try:
        from . import holidays as hol

        pairs = hol.priceable_date_pairs(config)
    except Exception:  # noqa: BLE001 - no pair means no watch-list stay card, never a failed e-mail
        return None
    return tuple(pairs[len(pairs) // 2]) if pairs else None  # type: ignore[return-value]


def _unique_carriers(carriers: Any) -> list[str]:
    """The carriers named once each, first seen first, case-insensitively.

    A read names its carrier on every long leg, so the same airline arrived twice and the reason
    read "RwandAir, RwandAir"; two trips set aside for the same airline then formed two headings
    ("Egyptair" and "Egyptair, Egyptair").
    """
    seen: set[str] = set()
    names: list[str] = []
    for carrier in carriers or ():
        name = str(carrier).strip()
        if name and name.casefold() not in seen:
            seen.add(name.casefold())
            names.append(name)
    return names


def _business_hidden_reason(hidden: Mapping[str, Any]) -> str:
    """Why a Business read was set aside: on whom it was flown, and what is still to read.

    The old wording said no business fare had been read at all whenever the
    economy read had a long leg, which was false for every trip whose business
    read was set aside on the carrier list. The reason now names the carriers
    the read was on, so the reader can see the trip is NOT unread — it is read
    on an airline the owner's rule does not accept.
    """
    carriers = _unique_carriers(hidden.get("carriers"))
    if carriers:
        return (f"a business fare was read on {', '.join(carriers)}, which is not on the accepted airline list; "
                "a fare on an accepted airline is still to be read")
    return ("a business fare was read, but not on an accepted airline; "
            "a fare on an accepted airline is still to be read")


def build_digest(config: Any, *, rows: Sequence[Mapping[str, Any]], package_prices: Mapping[Any, PackagePrice],
                 watch: Optional[Sequence[Any]] = None, generated_at: str = "",
                 hotel_rates: Optional[Mapping[Any, Any]] = None,
                 room_only_rates: Optional[Mapping[Any, Any]] = None) -> Digest:
    budget = float(getattr(config, "max_budget_gbp", 0.0) or 0.0)
    travellers = int(getattr(config, "travellers", 5) or 5)
    cards: list[Card] = []
    not_priced: list[str] = []
    pending: list[Pending] = []
    refused: dict[str, str] = {}
    for price in (package_prices or {}).values():
        card = _package_card(price, budget, travellers)
        if card is None:
            refused[price.property_name] = cabin_module_reason()
            not_priced.append(price.property_name)
            pending.append(Pending(price.property_name, "package read in economy with a leg over 8 hours; needs a business read",
                                   str(price.source_url or "")))
        else:
            cards.append(card)
    for row in rows:
        card = _trip_card(row, hotel_rates, budget=budget, travellers=travellers,
                          room_only_rates=room_only_rates)
        reason = ("the economy fare read has a leg over 8 hours; a business fare is still to be read"
                  if row.get("economy_refused") else "no fare read for these dates yet")
        hidden = row.get("business_hidden")
        if hidden:
            # A fare WAS read, on an airline the rule does not accept: name it instead of
            # claiming the trip is unread (owner, 14 Nov 2026).
            reason = _business_hidden_reason(hidden)
        if card is None:
            # No accepted fare, but real dated stays: those are bookable, so the trip is a partly
            # priced card rather than a line under "Not yet priced" (and the reason moves onto its
            # Flights row). A lead follows the same rule.
            card = _stays_only_card(row, hotel_rates, room_only_rates, budget=budget,
                                    travellers=travellers, reason=reason)
        if card is not None:
            cards.append(card)
            continue
        not_priced.append(row["trip"].title)
        if str(getattr(row["trip"], "confidence", "")) == "lead":
            # A new idea with no figure yet: say what makes it worth reading, not a reason it is missing.
            pending.append(Pending(row["trip"].title, str(getattr(row["trip"], "why", "") or "").strip(),
                                   str(row.get("url") or ""), "ideas"))
        else:
            pending.append(Pending(row["trip"].title, reason, str(row.get("url") or "")))
    entries = tuple(watch) if watch is not None else watchlist_module.load_watchlist()
    pair = _reference_pair(config)
    for entry in entries:
        card = _watch_card(entry, pair, hotel_rates, travellers=travellers,
                          room_only_rates=room_only_rates)
        if card is not None:
            cards.append(card)
            continue
        not_priced.append(entry.name)
        group = "Gili Islands" if "Gili" in entry.area else "Maldives" if "Maldives" in entry.area else ""
        pending.append(Pending(entry.name, "no dated rate read for the whole party yet", str(entry.url or ""), group))
    # Partly priced cards that HAVE a flight read come before the stays-only ones: a fare is the
    # harder half to read, and the figure on the stays-only card is not a trip price.
    cards.sort(key=lambda c: (_KIND_ORDER.get(c.kind, 9), 0 if c.fits else 1,
                              0 if c.flights_gbp is not None else 1, _band(c.total_gbp),
                              0 if c.halal else 1, c.total_gbp))
    return Digest(cards=tuple(cards), not_priced=tuple(dict.fromkeys(not_priced)), watch=entries, refused=refused,
                  pending=tuple(pending))


def cabin_module_reason() -> str:
    return "economy flights with a leg over 8 hours: needs a business read"


# ---------------------------------------------------------------------------
# HTML. Inline styles only, tables for the price rows (Outlook and Gmail both keep them), one column at 600 px.
# ---------------------------------------------------------------------------

_INK, _MUTED, _LINE, _CARD, _ACCENT, _OK = "#1f2a30", "#4f5f67", "#d3dde2", "#f2f6f8", "#155f8f", "#1d5c30"
_GOOD_BG, _GOOD_INK, _WARN_BG, _WARN_INK = "#DCFCE7", "#166534", "#FEF3C7", "#92400E"


def _e(text: Any) -> str:
    return escape(str(text))


def _span(config: Any) -> str:
    outs = sorted(getattr(config, "outbound_dates", ()) or ())
    span = f"{_day(outs[0])}–{_day(outs[-1])}" if outs else ""
    return f"{int(getattr(config, 'travellers', 5))} travellers · leaving {span} · confirmed prices only"


_SECTION = ("font-size:13px; font-weight:700; text-transform:uppercase; letter-spacing:0.5px; color:#334155; "
            "margin:22px 0 4px; border-bottom:2px solid #CBD5E1; padding-bottom:4px;")
_SUB = "font-size:12px; color:#475569; margin:0 0 10px;"
_ROW = "font-size:13px; line-height:1.45; color:#1E293B; margin:0 0 4px;"
_LINK = "color:#0369A1; font-weight:600; text-decoration:underline;"


def _a(url: str, label: str) -> str:
    return f'<a href="{_e(url)}" style="{_LINK}">{_e(label)}</a>' if url else _e(label)


def _chip(text: str, bg: str, ink: str) -> str:
    return (f'<span style="display:inline-block; background:{bg}; color:{ink}; font-size:11px; font-weight:700; '
            f'padding:2px 7px; border-radius:10px; margin:0 4px 4px 0;">{_e(text)}</span>')


def _chips(c: Card) -> str:
    chips = []
    if c.fits is True:
        chips.append(_chip(f"fits the {_gbp(c.budget)} budget", _GOOD_BG, _GOOD_INK))
    elif c.fits is False:
        chips.append(_chip(f"{_gbp(c.total_gbp - c.budget)} over budget", _WARN_BG, _WARN_INK))
    if c.kind == "part" and c.nights - c.nights_priced > 0:
        chips.append(_chip(f"{c.nights - c.nights_priced} nights still to price", _WARN_BG, _WARN_INK))
    if c.halal:
        chips.append(_chip(c.halal, _GOOD_BG, _GOOD_INK))
    return f'<div style="margin:0 0 4px;">{"".join(chips)}</div>' if chips else ""


def _budget_bar(c: Card) -> str:
    """How much of the budget the whole trip uses, as a two-cell bar. Only for a whole-trip figure."""
    if c.fits is None:
        return ""
    share = max(4, min(100, round(c.total_gbp / c.budget * 100)))
    colour = "#16A34A" if c.fits else "#D97706"
    rest = (f'<td style="background:#E2E8F0; height:6px; font-size:0; line-height:0;">&nbsp;</td>' if share < 100 else "")
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin:6px 0 2px; '
            f'border-collapse:collapse;"><tr><td width="{share}%" style="background:{colour}; height:6px; font-size:0; '
            f'line-height:0;">&nbsp;</td>{rest}</tr></table>'
            f'<div style="font-size:11px; color:#475569;">{round(c.total_gbp / c.budget * 100)}% of the '
            f'{_gbp(c.budget)} budget</div>')


def _price_block(c: Card) -> str:
    each = f" · {_gbp(c.total_gbp / c.travellers)} each" if c.kind in ("trip", "package") and c.travellers else ""
    made_of = ""
    if c.kind in ("trip", "part") and c.flights_gbp is not None:
        made_of = (f'<br><span style="font-size:12px; color:#334155;">flights {_gbp(c.flights_gbp)} + stays '
                   f'{_gbp(c.stays_gbp)}</span>')
    found = ""
    if c.kind in ("package", "flights"):
        found = (f'<br><span style="font-size:12px; color:#334155;">Found: {_a(c.url, c.shop)} · read '
                 f'{_e(c.read_on)}</span>')
    return (f'<div style="background:#F1F5F9; padding:8px 10px; border-radius:4px; margin-bottom:8px;">'
            f'<span style="font-size:22px; font-weight:800; color:#0F172A;">{_gbp(c.total_gbp)}</span>'
            f'{" so far:" if c.kind == "part" else ""}'
            f'<span style="font-size:12px; color:#334155;"> {_e(c.covers)}{_e(each)}</span>{made_of}{found}'
            f'{_budget_bar(c)}</div>')


def _stay_facts(s: StayPrice) -> list[str]:
    """The plain facts of a priced stay, in the order a reader needs them.

    Board, the booking's shape, then — when the figure is derived — how it was derived, then the
    seller once. No exporter display strings: "room only · 2 rooms (3 + 2 guests) · Booking.com ·
    read 14 Nov".
    """
    facts = [s.board_words, s.rooms_words]
    if s.derived_total:
        facts.append(f"nightly price × {s.nights} night{'s' if s.nights != 1 else ''}")
    return [fact for fact in facts if fact]


def _per_night_words(stay: StayPrice) -> str:
    """The stay's total divided by its nights, to the pound; ``""`` when the nights are unknown."""
    if stay.total_gbp is None or not stay.nights:
        return ""
    return _gbp(float(stay.total_gbp) / stay.nights)


def _stay_row(s: StayPrice) -> str:
    when = f"{_day(s.check_in)} – {_day(s.check_out)}"
    name = _a(s.property_url, s.property_name) if s.property_name else _e("hotel not chosen yet")
    left = (f'<b>{_e(when)}</b> · {s.nights} night{"s" if s.nights != 1 else ""} · {_e(s.place)}<br>{name}')
    if s.priced:
        detail = " · ".join(_stay_facts(s))
        per_night = f" · ({_per_night_words(s)} a night)" if _per_night_words(s) else ""
        left += (f'<br><span style="font-size:12px; color:#475569;">{_e(detail)}{" · " if detail else ""}'
                 f'{_a(s.source_url, s.seller or "seller")} · read {_e(_read_day(s.observed_at))}{_e(per_night)}</span>')
        right = f'<b>{_gbp(s.total_gbp)}</b>'
    else:
        left += f'<br><span style="font-size:12px; color:{_WARN_INK};">{_e(s.reason or "not priced")}</span>'
        right = '<span style="color:#92400E;">not priced</span>'
    cell = "padding:6px 0; border-top:1px solid #E2E8F0; font-size:13px; line-height:1.4; color:#1E293B; vertical-align:top;"
    return (f'<tr><td style="{cell}">{left}</td>'
            f'<td align="right" style="{cell} white-space:nowrap; padding-left:8px;">{right}</td></tr>')


def _itinerary_html(c: Card) -> str:
    rows = []
    cell = "padding:6px 0; border-top:1px solid #E2E8F0; font-size:13px; line-height:1.4; color:#1E293B; vertical-align:top;"
    if c.kind in ("trip", "part", "flights") and (c.flights_gbp is not None or c.flights):
        legs = "".join(f'<br><span style="font-size:12px; color:#475569;">{_e(leg)}</span>' for leg in c.legs[:6])
        source = (f'<br><span style="font-size:12px; color:#475569;">{_a(c.url, c.shop)} · read {_e(c.read_on)}</span>'
                  if c.flights_gbp is not None and c.shop else "")
        price = (f'<b>{_gbp(c.flights_gbp)}</b>' if c.flights_gbp is not None
                 else f'<span style="color:{_WARN_INK};">not priced</span>')
        rows.append(f'<tr><td style="{cell}"><b>Flights</b> · {_e(c.flights)}{legs}{source}</td>'
                    f'<td align="right" style="{cell} white-space:nowrap; padding-left:8px;">{price}</td></tr>')
    rows.extend(_stay_row(s) for s in c.stays)
    if not rows:
        return ""
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; '
            f'margin:0 0 6px;">{"".join(rows)}</table>')


def _card_html(c: Card) -> str:
    """One full card: chips, title, the figure and what it is made of, then the itinerary with each line's price."""
    edge = {"trip": "#16A34A", "package": "#0284C7", "part": "#D97706", "stay": "#7C3AED"}.get(c.kind, "#0284C7")
    if c.fits is False:
        edge = "#D97706"
    body = _itinerary_html(c)
    if c.kind == "package":
        body = (f'<div style="{_ROW}"><b>Flights</b> {_e(c.flights)}</div>'
                + (f'<div style="{_ROW}"><b>Hotel</b> {_e(c.hotel)}</div>' if c.hotel else ""))
    notes = []
    if c.kind in ("trip", "part", "flights") and c.why:
        notes.append(f'<b>Why it is special</b> {_e(c.why)}')
    if c.kind in ("trip", "part") and c.catch:
        notes.append(f'<b>Watch out</b> {_e(c.catch)}')
    if c.kind in ("trip", "part"):
        notes.append("<b>Not in the figure</b> airport transfers, meals beyond the board shown, park or activity fees")
    shown = {c.why}
    notes.extend(_e(f) for f in c.facts[:3] if f not in shown and not f.startswith("fits the budget")
                 and " over the " not in f)
    notes_html = "".join(f'<div style="font-size:12px; color:#475569; margin-top:5px; border-top:1px dashed #E2E8F0; '
                         f'padding-top:4px; line-height:1.4;">{n}</div>' for n in notes)
    return (f'<div data-kind="card-{_e(c.kind)}" style="background:#FFFFFF; border:1px solid #CBD5E1; '
            f'border-left:4px solid {edge}; border-radius:6px; '
            f'padding:12px; margin-bottom:12px; color:#0F172A;">{_chips(c)}'
            f'<div style="font-size:16px; font-weight:700; color:#0F172A; margin:0 0 2px; line-height:1.3;">{_e(c.title)}</div>'
            f'<div style="font-size:12px; color:#475569; margin:0 0 8px;">{c.nights} nights · {_e(c.dates)}'
            f'{" · " + _e(c.place) if c.kind == "stay" and c.place else ""}</div>'
            f'{_price_block(c)}{body}{notes_html}</div>')


def _flight_rows_html(cards: Sequence[Card]) -> str:
    """Flights-only reads as compact rows: a fare is one line until a stay is priced beside it."""
    cell = "padding:7px 0; border-top:1px solid #E2E8F0; font-size:13px; line-height:1.4; color:#1E293B; vertical-align:top;"
    rows = []
    for c in cards:
        open_nights = "; ".join(f"{s.place} {s.nights}n" + (f" ({s.property_name})" if s.property_name else "")
                                for s in c.stays if not s.priced) or c.hotel
        facts = "".join(f'<br><span style="font-size:12px; color:#475569; font-style:italic;">{_e(f)}</span>'
                        for f in c.facts[:2])
        rows.append(
            f'<tr data-kind="row-flights"><td style="{cell}"><b>{_e(c.title)}</b><br>'
            f'<span style="font-size:12px; color:#475569;">{c.nights} nights · {_e(c.dates)} · {_e(c.flights)} · '
            f'{_a(c.url, c.shop)} · read {_e(c.read_on)}</span>'
            + (f'<br><span style="font-size:12px; color:#475569;">Stays to price: {_e(open_nights)}</span>' if open_nights else "")
            + facts + '</td>'
            f'<td align="right" style="{cell} white-space:nowrap; padding-left:8px;"><b>{_gbp(c.total_gbp)}</b><br>'
            f'<span style="font-size:11px; color:#475569;">flights only</span></td></tr>')
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse; '
            f'background:#FFFFFF; border:1px solid #CBD5E1; border-radius:6px;"><tr><td style="padding:2px 12px;">'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">'
            f'{"".join(rows)}</table></td></tr></table>')


_ROW_CELL = ("padding:7px 0; border-top:1px solid #E2E8F0; font-size:13px; line-height:1.4; "
             "color:#1E293B; vertical-align:top;")
_SMALL = "font-size:12px; color:#475569;"


def _is_full_card(c: Card) -> bool:
    """Full-size cards: whole trips, packages, and partly priced trips whose FLIGHTS are read.

    Everything else — a trip whose stays are read but whose fare is not, and a watch-list stay —
    is a compact row: the full detail rides in the attached trip pages, and twelve full cards of
    stays-only trips made the body nine screens tall (14 Nov 2026).
    """
    return c.kind in ("trip", "package") or (c.kind == "part" and c.flights_gbp is not None)


def _is_stays_row(c: Card) -> bool:
    return c.kind == "part" and c.flights_gbp is None


def _fare_reason(c: Card) -> str:
    """The reason a stays-only card carries on its Flights row, without the "not priced; " prefix."""
    text = str(c.flights or "")
    return text[len("not priced; "):] if text.startswith("not priced; ") else text


def _seller_is_property(stay: StayPrice) -> bool:
    """True when the seller IS the property, so the line need not name the same thing twice."""
    seller = str(stay.seller or "").strip().casefold()
    return bool(seller) and seller == str(stay.property_name or "").strip().casefold()


def _compact_stay_line(s: StayPrice) -> str:
    """One small line per priced stay: what it is, what it costs, and how it was read."""
    parts = [f"{s.nights} night{'s' if s.nights != 1 else ''}", _gbp(s.total_gbp)]
    per_night = _per_night_words(s)
    if per_night:
        parts[-1] = f"{_gbp(s.total_gbp)} ({per_night} a night)"
    for fact in _stay_facts(s):
        parts.append(fact)
    seller = "" if _seller_is_property(s) else _a(s.source_url, s.seller or "seller")
    if seller:
        parts.append(seller)
    return f'<br><span style="{_SMALL}">{_a(s.source_url, s.property_name or "hotel not chosen yet")} · ' + \
           " · ".join(parts) + "</span>"


def _still_to_price_html(c: Card) -> str:
    open_nights = "; ".join(f"{s.place} {s.nights}n ({s.property_name or 'hotel not chosen'})"
                            for s in c.stays if not s.priced)
    return (f'<br><span style="font-size:12px; color:{_WARN_INK};">still to price: {_e(open_nights)}</span>'
            if open_nights else "")


def _stays_rows_html(cards: Sequence[Card]) -> str:
    """The stays-read rows: the trip, its stays figure, the fare's reason, then one line per stay."""
    rows = []
    for c in _sorted_stays_rows(cards):
        why = (f'<br><span style="font-size:12px; color:#475569; font-style:italic;">Why it is special: {_e(c.why)}</span>'
               if c.why else "")
        stay_lines = "".join(_compact_stay_line(s) for s in c.stays if s.priced)
        rows.append(
            f'<tr data-kind="row-stays-only"><td style="{_ROW_CELL}"><b>{_e(c.title)}</b><br>'
            f'<span style="{_SMALL}">{c.nights} nights · {_e(c.dates)} · fare: {_e(_fare_reason(c))}</span>'
            f'{stay_lines}{_still_to_price_html(c)}{why}</td>'
            f'<td align="right" style="{_ROW_CELL} white-space:nowrap; padding-left:8px;">'
            f'<b>{_gbp(c.stays_gbp)}</b><br><span style="font-size:11px; color:#475569;">'
            f'{c.nights_priced} of {c.nights} nights</span></td></tr>')
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="border-collapse:collapse; background:#FFFFFF; border:1px solid #CBD5E1; border-radius:6px;">'
            f'<tr><td style="padding:2px 12px;"><table role="presentation" width="100%" cellpadding="0" '
            f'cellspacing="0" style="border-collapse:collapse;">{"".join(rows)}</table></td></tr></table>')


def _watch_rows_html(cards: Sequence[Card]) -> str:
    """A watch-list stay as one compact row: name, figure, then how its night was read."""
    rows = []
    for c in cards:
        stay = next((s for s in c.stays if s.priced), None)
        if stay is None:
            continue
        detail = [c.place or "", c.dates]
        per_night = _per_night_words(stay)
        if per_night:
            detail.append(f"{per_night} a night")
        detail += _stay_facts(stay)
        seller = "" if _seller_is_property(stay) else _a(stay.source_url, stay.seller or "seller")
        if seller:
            detail.append(seller)
        detail.append(f"read {_read_day(stay.observed_at)}")
        facts = "".join(f'<br><span style="font-size:12px; color:#475569; font-style:italic;">{_e(fact)}</span>'
                        for fact in c.facts)
        tag = f' {_chip(c.halal, _GOOD_BG, _GOOD_INK)}' if c.halal else ""
        rows.append(
            f'<tr data-kind="row-stay"><td style="{_ROW_CELL}"><b>{_a(stay.source_url, c.title)}</b>{tag}<br>'
            f'<span style="{_SMALL}">{_e(" · ".join(part for part in detail if part))}</span>{facts}</td>'
            f'<td align="right" style="{_ROW_CELL} white-space:nowrap; padding-left:8px;">'
            f'<b>{_gbp(c.total_gbp)}</b><br><span style="font-size:11px; color:#475569;">'
            f'{c.nights} night{"s" if c.nights != 1 else ""}</span></td></tr>')
    return (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
            f'style="border-collapse:collapse; background:#FFFFFF; border:1px solid #CBD5E1; border-radius:6px;">'
            f'<tr><td style="padding:2px 12px;"><table role="presentation" width="100%" cellpadding="0" '
            f'cellspacing="0" style="border-collapse:collapse;">{"".join(rows)}</table></td></tr></table>')


def _sorted_stays_rows(cards: Sequence[Card]) -> list[Card]:
    """Rows by how much of the trip is priced, most first, then by the figure: the closest to a card leads."""
    def share(c: Card) -> float:
        return (c.nights_priced / c.nights_planned) if c.nights_planned else 0.0

    return sorted(cards, key=lambda c: (-share(c), c.stays_gbp))


def _summary_html(digest: Digest, budget: float) -> str:
    """The answer first: what is bookable this week, cheapest first, before any card."""
    whole = [c for c in digest.cards if c.kind in ("trip", "package")]
    if not whole:
        part = [c for c in digest.cards if c.kind == "part"]
        flights = [c for c in digest.cards if c.kind == "flights"]
        stays = [c for c in digest.cards if c.kind == "stay"]
        if not (part or flights or stays):
            return ""
        # Count what is SHOWN, each kind once: a reader looking for a whole trip wants to know how
        # close each one is, not how many rows there are.
        clauses: list[str] = []
        with_flights = [c for c in part if c.flights_gbp is not None]
        stays_only = [c for c in part if c.flights_gbp is None]
        if with_flights:
            count = len(with_flights)
            clauses.append(f"{count} trip{'s' if count != 1 else ''} "
                           f"{'have' if count != 1 else 'has'} flights and some stays read")
        if stays_only:
            count = len(stays_only)
            clauses.append(f"{count} {'have' if count != 1 else 'has'} stays only")
        if flights:
            count = len(flights)
            clauses.append(f"{count} {'have' if count != 1 else 'has'} flights only")
        if not clauses:
            return ""
        return (f'<div style="background:#FFFBEB; border:1px solid #FDE68A; border-radius:6px; padding:10px 12px; '
                f'margin:12px 0 0; font-size:13px; color:#1E293B; line-height:1.45;"><b>No whole trip is priced yet this '
                f'week.</b> {", ".join(clauses)} (below); a trip moves up to a full card once its flights and every '
                f'night are read for these dates.</div>')
    whole = sorted(whole, key=lambda c: c.total_gbp)
    fit = [c for c in whole if c.fits]
    head = f"{len(whole)} whole trip{'s' if len(whole) != 1 else ''} priced"
    if budget > 0:
        head += f" · {len(fit)} fit{'s' if len(fit) == 1 else ''} the {_gbp(budget)} budget"
    cell = "padding:5px 0; border-top:1px solid #BBF7D0; font-size:13px; color:#1E293B; vertical-align:top;"
    rows = "".join(
        f'<tr><td style="{cell}">{_e(c.title)}<br><span style="font-size:11px; color:#475569;">{c.nights} nights · '
        f'{"operator package" if c.kind == "package" else "flights + stays"}</span></td>'
        f'<td align="right" style="{cell} white-space:nowrap; padding-left:8px;"><b>{_gbp(c.total_gbp)}</b><br>'
        f'<span style="font-size:11px; color:{_GOOD_INK if c.fits else _WARN_INK};">'
        f'{"fits" if c.fits else ("over" if c.fits is False else "")}</span></td></tr>' for c in whole[:6])
    return (f'<div style="background:#F0FDF4; border:1px solid #BBF7D0; border-radius:6px; padding:10px 12px; '
            f'margin:12px 0 0;"><div style="font-size:14px; font-weight:700; color:#14532D; margin:0 0 4px;">{_e(head)}</div>'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">'
            f'{rows}</table></div>')


def _pending_item(p: Pending) -> str:
    return _a(p.url, p.name) if p.url else _e(p.name)


def _not_priced_html(digest: Digest) -> str:
    if not digest.not_priced:
        return ""
    pending = list(digest.pending) or [Pending(n) for n in digest.not_priced]
    items = []
    trips = [p for p in pending if not p.group]
    by_reason: dict[str, list[Pending]] = {}
    for p in trips:
        by_reason.setdefault(p.reason, []).append(p)
    for reason, group in by_reason.items():
        # The reason once, then one line per trip (owner, 14 Nov 2026): a paragraph of thirteen links
        # separated by semicolons was unreadable, and the reason is the same for every one of them.
        lines = "".join(f'<div style="margin:3px 0 0;">{_pending_item(p)}</div>' for p in group)
        items.append((f'<b style="color:#334155;">{_e(reason)}</b>' if reason else "") + lines)
    ideas = [p for p in pending if p.group == "ideas"]
    if ideas:
        lines = "".join(f'<div style="margin:3px 0 0;">{_pending_item(p)}'
                        + (f' <span style="color:#64748B;">— {_e(p.reason)}</span>' if p.reason else "") + '</div>'
                        for p in ideas)
        items.append(f"<b>New ideas, fares and stays being read</b>{lines}")
    gili = [p for p in pending if p.group == "Gili Islands"]
    maldives = [p for p in pending if p.group == "Maldives"]
    if gili:
        items.append(f"<b>Gili Islands</b>: {', '.join(_pending_item(p) for p in gili)}")
    if maldives:
        items.append(f"<b>Maldives</b> (seaplane transfer to be priced in): {', '.join(_pending_item(p) for p in maldives)}")
    li = "".join(f'<li style="margin:0 0 4px;">{i}</li>' for i in items)
    return (f'<div style="{_SECTION}">Not yet priced</div>'
            f'<ul style="padding-left:16px; margin:4px 0; font-size:12px; color:#334155; line-height:1.5;">{li}</ul>')


def _section(title: str, sub: str = "") -> str:
    return f'<div style="{_SECTION}">{_e(title)}</div>' + (f'<div style="{_SUB}">{_e(sub)}</div>' if sub else "")


def render_digest_html(config: Any, digest: Digest, *, generated_at: str, attachment_name: str = "") -> str:
    title = _e(getattr(config, "report_title", "July holiday watch"))
    budget = float(getattr(config, "max_budget_gbp", 0.0) or 0.0)
    by_kind = {kind: [c for c in digest.cards if c.kind == kind] for kind in _KIND_ORDER}
    out = [f'<div style="max-width:600px; margin:0 auto; padding:12px; background:#F8FAFC; color:#0F172A; '
           f'font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">',
           f'<h1 style="font-size:21px; margin:4px 0 4px; color:#3C4C55;">{title}</h1>',
           f'<div style="color:{_MUTED}; font-size:13px;">{_e(_span(config))} · checked {_e(_read_day(generated_at))}</div>',
           _summary_html(digest, budget)]
    part_with_flights = [c for c in by_kind["part"] if c.flights_gbp is not None]
    stays_only = [c for c in by_kind["part"] if c.flights_gbp is None]
    if by_kind["trip"]:
        out.append(_section("Whole trips, fully priced", _section_caption(
            "Flights and every night's stay were read for these exact dates and the whole party.", by_kind["trip"])))
        out.extend(_card_html(c) for c in by_kind["trip"])
    if by_kind["package"]:
        out.append(_section("Confirmed packages", _section_caption(
            "One operator price: flights and hotel together.", by_kind["package"])))
        out.extend(_card_html(c) for c in by_kind["package"])
    if part_with_flights:
        out.append(_section("Partly priced", _section_caption(
            "Flights and some stays are read; the nights marked are still open.", part_with_flights)))
        out.extend(_card_html(c) for c in part_with_flights)
    if stays_only:
        # Compact rows, not cards: twelve of these as full cards made the body nine screens tall, and
        # the full detail is in the attached trip pages.
        out.append(_section("Stays read, fares still to come", _section_caption(
            "These nights are priced; the trip joins the cards above when its fare is read.", stays_only)))
        out.append(_stays_rows_html(stays_only))
    if by_kind["stay"]:
        out.append(_section("Stays priced, flights separate", _section_caption(
            "A dated rate for the whole party; add the flights.", by_kind["stay"])))
        out.append(_watch_rows_html(by_kind["stay"]))
    if by_kind["flights"]:
        out.append(_section("Flight searches, flights only", "The fare is read; no stay is priced beside it yet."))
        out.append(_flight_rows_html(by_kind["flights"]))
    if not digest.cards:
        out.append(f'<div style="margin:16px 0; color:{_INK};">Nothing confirmed this week: no package or flight price was read for the trip dates.</div>')
    out.append(_not_priced_html(digest))
    if attachment_name:
        out.append(f'<div style="font-size:12px; color:{_MUTED}; margin-top:16px;">Full trip pages for every option are '
                   f'attached: {_e(attachment_name)}</div>')
    out.append("</div>")
    return "".join(out)


def _stay_text(s: StayPrice) -> str:
    when = f"{_day(s.check_in)} – {_day(s.check_out)}"
    name = s.property_name or "hotel not chosen yet"
    if not s.priced:
        return f"    {when} · {s.nights}n · {s.place}: {name}: not priced ({s.reason or 'no read'})"
    detail = " · ".join(_stay_facts(s) + ([s.seller] if s.seller else ["seller"]))
    per_night = f" ({_per_night_words(s)} a night)" if _per_night_words(s) else ""
    return (f"    {when} · {s.nights}n · {s.place}: {name}: {_gbp(s.total_gbp)}{per_night}"
            + (f" · {detail}" if detail else "") + f" · read {_read_day(s.observed_at)} · {s.source_url}")


def _card_text(c: Card) -> list[str]:
    """One full card in the plain-text part, the same figures as its HTML card."""
    fits = " · fits the budget" if c.fits else (f" · {_gbp(c.total_gbp - c.budget)} over budget" if c.fits is False else "")
    lines = [f"{c.title}{' [' + c.halal + ']' if c.halal else ''}",
             f"  {c.nights} nights · {c.dates} · {_gbp(c.total_gbp)} for {c.travellers} · {c.covers}{fits}"]
    if c.kind in ("trip", "part"):
        lines.append(f"  Made of: flights {_gbp(c.flights_gbp)} + stays {_gbp(c.stays_gbp)}")
    if c.kind != "stay":
        lines += [f"  Found: {c.shop} · read {c.read_on} · {c.url}", f"  Flights: {c.flights}"]
        lines += [f"    {leg}" for leg in c.legs[:6]]
    if c.stays:
        lines.append("  Stays:")
        lines += [_stay_text(s) for s in c.stays]
    elif c.hotel:
        lines.append(f"  {'Hotel' if c.kind == 'package' else 'Stays'}: {c.hotel}")
    if c.kind in ("trip", "part") and c.catch:
        lines.append(f"  Watch out: {c.catch}")
    return lines + [f"  {f}" for f in c.facts] + [""]


def _stays_row_text(c: Card) -> list[str]:
    """One stays-read row in the plain-text part: figure, reason, a line per stay, the open nights."""
    lines = [f"{c.title}",
             f"  {_gbp(c.stays_gbp)} so far · {c.nights_priced} of {c.nights} nights",
             f"  {c.nights} nights · {c.dates} · fare: {_fare_reason(c)}"]
    for s in c.stays:
        if not s.priced:
            continue
        parts = [f"{s.nights}n", _gbp(s.total_gbp)]
        per_night = _per_night_words(s)
        if per_night:
            parts[-1] = f"{_gbp(s.total_gbp)} ({per_night} a night)"
        parts += _stay_facts(s)
        if not _seller_is_property(s):
            parts.append(s.seller or "seller")
        lines.append(f"    {s.property_name or 'hotel not chosen yet'} · " + " · ".join(parts))
    open_nights = "; ".join(f"{s.place} {s.nights}n ({s.property_name or 'hotel not chosen'})"
                            for s in c.stays if not s.priced)
    if open_nights:
        lines.append(f"    still to price: {open_nights}")
    if c.why:
        lines.append(f"    Why it is special: {c.why}")
    return lines + [""]


def _watch_row_text(c: Card) -> list[str]:
    """One watch-list stay in the plain-text part: figure, then how its night was read."""
    stay = next((s for s in c.stays if s.priced), None)
    if stay is None:
        return []
    detail = [c.place or "", c.dates]
    per_night = _per_night_words(stay)
    if per_night:
        detail.append(f"{per_night} a night")
    detail += _stay_facts(stay)
    if not _seller_is_property(stay):
        detail.append(stay.seller or "seller")
    detail.append(f"read {_read_day(stay.observed_at)}")
    lines = [f"{c.title}{' [' + c.halal + ']' if c.halal else ''}",
             f"  {c.nights} nights · {_gbp(c.total_gbp)}",
             "  " + " · ".join(part for part in detail if part)]
    lines += [f"  {fact}" for fact in c.facts]
    return lines + [""]


def render_digest_text(config: Any, digest: Digest, *, generated_at: str, attachment_name: str = "") -> str:
    lines = [str(getattr(config, "report_title", "July holiday watch")),
             f"{_span(config)} · checked {_read_day(generated_at)}", ""]
    trips = [c for c in digest.cards if c.kind == "trip"]
    packages = [c for c in digest.cards if c.kind == "package"]
    partly = [c for c in digest.cards if _is_full_card(c) and c.kind == "part"]
    for heading, sub, group in (
        ("Whole trips, fully priced",
         "Flights and every night's stay were read for these exact dates and the whole party.", trips),
        ("Confirmed packages", "One operator price: flights and hotel together.", packages),
        ("Partly priced", "Flights and some stays are read; the nights marked are still open.", partly),
    ):
        if not group:
            continue
        lines += [heading, f"  {_section_caption(sub, group)}", ""]
        for c in group:
            lines += _card_text(c)
    stays_only = [c for c in digest.cards if _is_stays_row(c)]
    if stays_only:
        lines += ["Stays read, fares still to come",
                  "These nights are priced; the trip joins the cards above when its fare is read."]
        if _has_derived_stay(stays_only):
            lines.append(DERIVED_TOTAL_NOTE)
        lines.append("")
        for c in _sorted_stays_rows(stays_only):
            lines += _stays_row_text(c)
    watch = [c for c in digest.cards if c.kind == "stay"]
    if watch:
        lines += ["Stays priced, flights separate",
                  "A dated rate for the whole party; add the flights."]
        if _has_derived_stay(watch):
            lines.append(DERIVED_TOTAL_NOTE)
        lines.append("")
        for c in watch:
            lines += _watch_row_text(c)
    for c in [c for c in digest.cards if c.kind == "flights"]:
        lines += _card_text(c)
    if not digest.cards:
        lines += ["Nothing confirmed this week: no package or flight price was read for the trip dates.", ""]
    if digest.not_priced:
        pending = list(digest.pending) or [Pending(n) for n in digest.not_priced]
        by_reason: dict[str, list[Pending]] = {}
        for p in (p for p in pending if not p.group):
            by_reason.setdefault(p.reason, []).append(p)
        lines.append("Not yet priced")
        for reason, group in by_reason.items():
            if reason:
                lines.append(f"{reason}")
            lines += [f"  {p.name}" for p in group]
        for group_name, label in (("ideas", "New ideas, fares and stays being read"),
                                  ("Gili Islands", "Gili Islands"),
                                  ("Maldives", "Maldives (seaplane transfer to be priced in)")):
            members = [p for p in pending if p.group == group_name]
            if not members:
                continue
            lines.append(label)
            lines += [f"  {p.name}" + (f" — {p.reason}" if p.reason and group_name == "ideas" else "")
                      for p in members]
    if attachment_name:
        lines += ["", f"Full trip pages for every option are attached: {attachment_name}"]
    return "\n".join(lines) + "\n"
