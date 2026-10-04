"""The compact holiday e-mail: one price per card, one table, no jargon.

Owner brief 2026-10-04 (BRIEF-H1 Part 2). AMEND-H1 and REPLY-H0 are the
authority on the wording of prices and labels, and this module follows them:

* ONE number per card: the door-to-door total for the whole party, large. The
  package-only figure is never printed, and the one breakdown line under the
  headline adds up to it exactly (AMEND-H1 §1).
* Movement is against the LAST observation, never against a benchmark
  (AMEND-H1 §2). No benchmark percentage and no "below our estimate" text may
  appear anywhere in this e-mail.
* The first screen is the at-a-glance table, one row per deal, with one key
  line under it: every price is the total for 5, door to door (AMEND-H1 §3).
* No ``<details>``: Gmail strips it, so everything the critique put in Details
  is dropped here and stays in the detailed renderer (AMEND-H1 §4).
* Labels are the critique's (AMEND-H1 §7): "Live price · checked yesterday",
  "Seen 5 days ago", "Estimate — no live price", "total for 5, door to door",
  "£378 each", "Nonstop"/"1-Stop via …".

The HTML part and the plain-text part are rendered from ONE set of plain-text
card structures (``_build_cards``), so the two cannot drift apart in order or
in numbers. Every figure is computed from the deal's own components at render
time — no price is ever retyped.

``holidays.render_holiday_report`` is untouched and still reachable with
``HOLIDAY_REPORT_STYLE=detailed``.
"""

from __future__ import annotations

from datetime import datetime
from html import escape
import re
from typing import Any, Mapping, Optional, Sequence, Union

from . import holidays as hol
from .holidays import (
    HolidayConfig,
    PackageDeal,
    board_code,
    deal_in_monsoon,
    deal_travel_month,
    far_east_watch_rows,
    observation_age_hours,
    relative_age_label,
    stopover_search_url,
)
from .vendors import build_vendor_links, trip_from_deal

#: Lines in the "what changed" block. The change digest keeps its own per-kind
#: caps (4 drops, 2 rises, 4 new) because it is a ticker; this e-mail states one
#: resort per line, and six lines is as many as a phone screen shows before the
#: reader starts skipping them.
MAX_WHAT_CHANGED_LINES: int = 6

#: Per-card caps. A card that answers "what does this cost, is it fresh, has it
#: moved, how do I book it" in this many lines is the whole point of the
#: redesign; anything more is what made the old e-mail unreadable.
MAX_WHY_LINES: int = 3
MAX_LINKS: int = 3
MAX_WARNINGS: int = 2

#: Flight options a long-haul card shows: Business, Economy on the same route,
#: and one Gulf stopover. Premium Economy, mixed-cabin fares and the other
#: hubs are comparisons, not options (REPLY-H0 §3), and stay in the detailed
#: renderer.
FLIGHT_OPTION_KINDS: tuple[str, ...] = ("business", "economy")

_MONTH_ABBR = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)
_DAY_ABBR = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

#: "Nonstop" / "1-Stop via Doha": never the bare word "Direct", which on a
#: holiday card reads as "you book the flight yourself".
_STOP_PREFIX_RE = re.compile(r"^(\d)\s*[- ]?\s*stop\b", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Plain words for dates, money and ages
# ---------------------------------------------------------------------------

def _instant(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 instant (``Z`` accepted), as UTC when naive."""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError):
        return None
    if parsed.tzinfo is None:
        from datetime import timezone

        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _gbp(value: Any) -> str:
    """A whole-pound amount: ``£1,890``."""
    try:
        return "£" + f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return "£0"


def _place(deal_or_label: Any) -> str:
    """A destination label trimmed to its place name ("Cairo, Egypt")."""
    label = getattr(deal_or_label, "destination_label", deal_or_label)
    return str(label or "").split(" (")[0].strip()


def _day_words(day: Any, *, generated_at: Any = "") -> str:
    """``4 Oct`` — a date a reader can say, never an ISO stamp."""
    parsed = _instant(day)
    if parsed is None:
        return str(day or "")
    stamp = _instant(generated_at)
    text = f"{parsed.day} {_MONTH_ABBR[parsed.month - 1]}"
    if stamp is not None and stamp.year != parsed.year:
        text += f" {parsed.year}"
    return text


def _range_words(first: Any, last: Any, *, generated_at: Any = "") -> str:
    """``17–23 Dec``, ``29 Jun – 13 Jul``, or a single date when they match."""
    left = _instant(first)
    right = _instant(last)
    if left is None or right is None:
        return " – ".join(str(x) for x in (first, last) if x)
    if (left.year, left.month, left.day) == (right.year, right.month, right.day):
        return _day_words(first, generated_at=generated_at)
    if left.year == right.year and left.month == right.month:
        return (
            f"{left.day}–{right.day} {_MONTH_ABBR[left.month - 1]}"
        ) + (f" {left.year}" if _year_differs(left, generated_at) else "")
    return (
        f"{left.day} {_MONTH_ABBR[left.month - 1]} – "
        f"{right.day} {_MONTH_ABBR[right.month - 1]}"
    ) + (f" {right.year}" if _year_differs(right, generated_at) else "")


def _year_differs(when: datetime, generated_at: Any) -> bool:
    stamp = _instant(generated_at)
    return stamp is not None and stamp.year != when.year


def _deal_dates_words(deal: PackageDeal, *, generated_at: Any = "") -> str:
    return _range_words(deal.outbound_date, deal.return_date, generated_at=generated_at)


def departure_range_words(config: HolidayConfig, *, generated_at: Any = "") -> str:
    """The configured departure window in words, derived not hard-coded."""
    days = [str(day) for day in (config.outbound_dates or ()) if day]
    if not days:
        return ""
    parsed = [d for d in (_instant(day) for day in days) if d is not None]
    if len(parsed) != len(days):
        return f"{min(days)}–{max(days)}"
    first = min(parsed)
    last = max(parsed)
    return _range_words(first.date().isoformat(), last.date().isoformat(),
                        generated_at=generated_at)


def nights_words(config: HolidayConfig) -> str:
    """``8 nights`` or ``12–21 nights``, from the config's band."""
    low = int(config.min_nights)
    high = int(config.max_nights)
    return f"{low} nights" if low == high else f"{low}–{high} nights"


def party_words(config: HolidayConfig) -> str:
    """``5 travellers · one booking`` — the one-booking rule, when it applies."""
    text = f"{int(config.travellers)} travellers"
    if len(config.rooms) >= 3:
        text += " · one booking"
    return text


def prices_checked_words(generated_at: Any) -> str:
    """``Prices checked Sun 4 Oct`` — never an ISO timestamp."""
    stamp = _instant(generated_at)
    if stamp is None:
        return "Prices checked"
    return (
        f"Prices checked {_DAY_ABBR[stamp.weekday()]} {stamp.day} "
        f"{_MONTH_ABBR[stamp.month - 1]}"
    )


# ---------------------------------------------------------------------------
# One price per card
# ---------------------------------------------------------------------------

def headline_total(deal: PackageDeal) -> float:
    """The one price of this card: door to door, the whole party.

    Falls back to the package total only when a deal carries no door-to-door
    figure at all — a card must never show a price the data cannot support.
    """
    for value in (getattr(deal, "true_d2d_gbp", 0.0), getattr(deal, "total_package_price_gbp", 0.0)):
        try:
            amount = float(value)
        except (TypeError, ValueError):
            continue
        if amount > 0:
            return amount
    return 0.0


def breakdown_parts(deal: PackageDeal) -> tuple[list[tuple[str, float]], float]:
    """``(label, amount)`` parts whose sum IS the headline, and that sum.

    flights + stay + ground/transfer is door-to-door by construction
    (``true_d2d = package + uk_ground + transfer``), so the line under the
    headline always adds up. When a hand-built deal's parts do not add up to
    its own headline, the shortfall is named as its own part rather than
    hidden: an unexplained gap in a breakdown is the thing this redesign
    exists to remove.
    """
    parts: list[tuple[str, float]] = []
    for label, value in (
        ("flights", getattr(deal, "flight_price_total_gbp", 0.0)),
        ("stay", getattr(deal, "hotel_price_total_gbp", 0.0)),
        ("transfers", float(getattr(deal, "uk_ground_gbp", 0.0) or 0.0)
         + float(getattr(deal, "transfer_gbp", 0.0) or 0.0)),
    ):
        try:
            amount = float(value)
        except (TypeError, ValueError):
            amount = 0.0
        if amount > 0:
            parts.append((label, amount))
    total = headline_total(deal)
    summed = round(sum(amount for _, amount in parts), 2)
    if parts and abs(summed - total) > 0.5:
        parts.append(("other", round(total - summed, 2)))
    return parts, total


def breakdown_words(deal: PackageDeal) -> str:
    """``flights £648 + stay £1,200 + transfers £42 = £1,890``."""
    parts, total = breakdown_parts(deal)
    if not parts:
        return ""
    body = " + ".join(f"{label} {_gbp(amount)}" for label, amount in parts)
    return f"{body} = {_gbp(total)}"


def freshness_tag(deal: PackageDeal, *, generated_at: Any) -> tuple[str, str]:
    """The card's one provenance tag: words, colour, and never a badge wall.

    REPLY-H0 §4 replaces three badges with three sentences. The tag names the
    WEAKER of the two legs, because the headline is both legs: a live fare
    beside an estimated room rate is not a live price.
    """
    confidence = str(getattr(deal, "confidence", "") or "")
    live = confidence == "verified-exact-date"
    stale = confidence == "stale-cache"
    age = observation_age_hours(getattr(deal, "live_observed_at", ""), generated_at)
    if (live or stale) and age is not None and age > hol.live_verify.EVIDENCE_MAX_AGE_HOURS:
        # The same render-time ageing the detailed card applies: an observation
        # that has aged out may not claim to be live.
        live, stale = False, True
    hotel_estimated = str(getattr(deal, "hotel_rate_basis", "")) == "estimate"
    hotel_read = getattr(deal, "hotel_evidence", None) is not None
    if live:
        if hotel_estimated:
            return "Live price · stay estimated", "green"
        return f"Live price · checked {_checked_words(age)}", "green"
    if stale:
        return f"Seen {relative_age_label(age) or 'earlier'}", "amber"
    if hotel_read and not hotel_estimated:
        return "Hotel rate read", "grey"
    return "Estimate — no live price", "amber"


def _checked_words(age: Optional[float]) -> str:
    """``yesterday`` / ``today`` / ``3 days ago`` for the live-price tag."""
    if age is None or age < 24:
        return "today"
    days = int(age // 24)
    if days == 1:
        return "yesterday"
    return f"{days} days ago"


# ---------------------------------------------------------------------------
# Movement against the LAST observation, never a benchmark
# ---------------------------------------------------------------------------

def movement_words(trend: Optional[Mapping[str, Any]], *, last_report_at: Any = "",
                   with_date: bool = True) -> str:
    """``£210 cheaper than 12 Oct`` / ``no change since 12 Oct`` / ``first time tracked``.

    AMEND-H1 §2: movement is measured against the previous report's number.
    A benchmark is our own estimate, so a gap against one is not a movement
    and is never worded as one.

    ``with_date=False`` drops the "than/since 12 Oct" clause for the at-a-glance
    column, which is one line wide; the card above it keeps the full sentence,
    so the two carry the same four wordings and the same number.
    """
    if not trend or trend.get("prior_last") is None:
        return "first time tracked"
    when = _day_words(last_report_at) if with_date else ""
    try:
        delta = float(trend.get("current", 0.0)) - float(trend["prior_last"])
    except (TypeError, ValueError):
        return "first time tracked"
    if abs(delta) < 0.5:
        return f"no change since {when}" if when else "no change"
    side = "cheaper" if delta < 0 else "dearer"
    amount = _gbp(abs(delta))
    return f"{amount} {side} than {when}" if when else f"{amount} {side}"


def movement_colour(words: str) -> str:
    if words.startswith("first time tracked") or words.startswith("no change"):
        return "grey"
    return "green" if "cheaper" in words else "amber"


# ---------------------------------------------------------------------------
# Card parts
# ---------------------------------------------------------------------------

def route_words(deal: PackageDeal) -> str:
    """``Nonstop LHR–AYT`` or ``1-Stop via Singapore`` — never "Direct"."""
    routing = str(getattr(deal, "routing", "") or "").strip()
    origin = str(getattr(deal, "origin", "") or "").upper()
    airport = str(getattr(deal, "destination_airport", "") or "").upper()
    nonstop = f"Nonstop {origin}–{airport}"
    if not routing:
        return nonstop
    text = routing.split(":", 1)[-1] if ":" in routing else routing
    text = text.split("(")[0].split(", then")[0].strip()
    if not text or "nonstop" in text.lower():
        return nonstop
    text = _STOP_PREFIX_RE.sub(lambda m: f"{m.group(1)}-Stop", text)
    return text[0].upper() + text[1:] if text else nonstop


def _option_total(option: Mapping[str, Any]) -> float:
    for key in ("true_d2d", "total_pkg"):
        try:
            value = float(option.get(key, 0.0))
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return 0.0


def flight_rows(deal: PackageDeal, *, travellers: int = 5) -> list[tuple[str, str, Union[str, tuple[str, str]]]]:
    """Three rows for a long-haul card: Business, Economy, one Gulf stopover.

    The stopover row is priced only when a whole-party multi-city fare was read
    for THIS card's dates. The committed July reads are for the old dates, so
    that row usually has no price — it then says so and links the itinerary,
    which is the owner's rule for 2026-10-04: never a stale number, and never a
    missing option either.

    Empty for a short-haul card: a destination with no London-stall Business
    option prices one cabin and gets no comparison table at all.
    """
    rows: list[tuple[str, str, Union[str, tuple[str, str]]]] = []
    options = list(getattr(deal, "flight_options", ()) or ())
    if not options:
        return rows
    labels = {"business": "Business", "economy": "Economy"}
    for kind in FLIGHT_OPTION_KINDS:
        for option in options:
            if str(option.get("kind", "")) != kind:
                continue
            total = _option_total(option)
            if total <= 0:
                continue
            rows.append((labels[kind], route_words(deal), _gbp(total)))
            break
    stopovers = [o for o in options if str(o.get("kind", "")) == "stopover"]
    priced = [o for o in stopovers if _option_total(o) > 0]
    if priced:
        # Cheapest option that fits the budget, else the cheapest overall —
        # the same choice the detailed renderer makes, so the two agree.
        cheapest = min(
            priced,
            key=lambda o: (0 if o.get("within_budget") else 1, _option_total(o)),
        )
        hub = str(cheapest.get("hub_label") or cheapest.get("hub") or "Doha")
        rows.append((
            "Economy",
            f"1-Stop via {hub}, 2 nights each way",
            _gbp(_option_total(cheapest)),
        ))
        return rows
    # Not priced for these dates: name one hub and offer the itinerary.
    hub = str(hol.STOPOVER_HUBS[hol.STOPOVER_LINK_HUBS[0]]["label"])
    try:
        url = stopover_search_url(
            hol.STOPOVER_LINK_HUBS[0],
            str(getattr(deal, "destination_airport", "") or "").upper(),
            str(getattr(deal, "outbound_date", "")),
            str(getattr(deal, "return_date", "")),
            origin=str(getattr(deal, "origin", "") or "LHR") or "LHR",
            travellers=int(travellers or 5),
        )
    except Exception:
        url = ""
    total: Union[str, tuple[str, str]] = ("price on request", url) if url else "price on request"
    rows.append(("Economy", f"1-Stop via {hub}, 2 nights each way", total))
    return rows


def board_line(deal: PackageDeal, *, travellers: int) -> str:
    """``All Inclusive · £378 each`` (+ the other boards, each priced for 5).

    AMEND-H5: the priced basis first, then each other basis with its price, in
    words and never as a code. The other bases are re-based onto the same
    door-to-door arithmetic as the headline, so one number means one thing
    across the whole e-mail: the total for the party.
    """
    priced_basis = hol.BOARD_LABELS.get(board_code(getattr(deal, "board_basis", "")), "")
    words = priced_basis or str(getattr(deal, "board_basis", "") or "")
    total = headline_total(deal)
    try:
        per_person = total / float(travellers or 1)
    except (TypeError, ValueError, ZeroDivisionError):
        per_person = 0.0
    if per_person > 0:
        words += f" · {_gbp(per_person)} each"
    options = list(getattr(deal, "board_options", ()) or ())
    if not options:
        return words
    priced_code = board_code(getattr(deal, "board_basis", ""))
    try:
        stay = float(getattr(deal, "hotel_price_total_gbp", 0.0) or 0.0)
    except (TypeError, ValueError):
        stay = 0.0
    # Each other basis is the same trip with a different room rate: subtract the
    # stay this card used, add the one that basis costs. Never a second model.
    others = sorted(
        (
            (str(o.get("label") or o.get("basis") or ""), float(o.get("hotel_cost", 0.0) or 0.0))
            for o in options
            if str(o.get("basis") or o.get("label") or "") != priced_code
        ),
        key=lambda row: row[1],
    )
    for label, cost in others:
        words += f" · {label} {_gbp(round(total - stay + cost, 2))}"
    if others:
        words += " (each for 5)"
    return words


def why_lines(deal: PackageDeal, config: HolidayConfig) -> list[str]:
    """Up to three one-line reasons, reusing what the catalogue already read."""
    lines: list[str] = []
    climate = _climate_words(deal, config)
    if climate:
        lines.append(climate)
    unit = _unit_words(deal, config)
    if unit:
        lines.append(unit)
    for highlight in getattr(deal, "highlights", ()) or ():
        text = str(highlight).strip()
        # A highlight that is really a caveat belongs in the notes, not in the
        # three reasons this card is worth reading.
        if not text or "not verified" in text or "blocked" in text:
            continue
        lines.append(text if len(text) <= 90 else text[:87].rstrip() + "…")
        break
    return lines[:MAX_WHY_LINES]


def _climate_words(deal: PackageDeal, config: HolidayConfig) -> str:
    key = str(getattr(deal, "destination_key", "") or "").lower()
    if hol.is_summer_trip(config):
        air, sea = hol.SUMMER_WEATHER.get(key, ((28, 33), 25))
    else:
        ambient = tuple(getattr(deal, "dec_ambient_c", (0, 0)) or (0, 0))
        air = (int(ambient[0]), int(ambient[1]))
        sea = int(getattr(deal, "sea_temp_c", 0) or 0)
    if not air[1]:
        return ""
    words = f"{air[0]}–{air[1]}°C"
    if sea:
        words += f", sea {sea}°C"
    beach = str(getattr(deal, "beach", "") or "").strip()
    # A beach field can be a sentence (the Andaman coast carries its monsoon
    # warning there). A "why" bullet is one line, and the monsoon warning
    # already says the part that changes a decision.
    if beach and len(beach) <= 60:
        words += f" · {beach}"
    return words


def _unit_words(deal: PackageDeal, config: HolidayConfig) -> str:
    travellers = int(config.travellers)
    unit = str(getattr(deal, "unit_architecture", "") or "").strip()
    rooms = getattr(deal, "rooms_in_unit", None)
    if unit and rooms is not None and int(rooms) < 3:
        return f"Sleeps {travellers} in one booking — {unit}"
    if unit:
        return unit
    if len(config.rooms) >= 2:
        return f"Two connecting rooms on one booking for {travellers}"
    return ""


def link_row(deal: PackageDeal, config: HolidayConfig) -> list[tuple[str, str]]:
    """At most three links: book it, compare prices, the hotel page."""
    links: list[tuple[str, str]] = []
    try:
        vendor = build_vendor_links(trip_from_deal(deal, adults=int(config.travellers),
                                                   rooms=tuple(config.rooms)))
    except Exception:
        vendor = ()
    if vendor and vendor[0].url:
        links.append(("Book this package", str(vendor[0].url)))
    for label, attr in (("Compare prices", "compare_url"), ("Hotel page", "booking_deep_url")):
        url = str(getattr(deal, attr, "") or "")
        if url:
            links.append((label, url))
    return links[:MAX_LINKS]


def warning_lines(deal: PackageDeal, config: HolidayConfig) -> list[str]:
    """Warnings that change a decision — at most two, longest-lived first."""
    out: list[str] = []
    if deal_in_monsoon(deal):
        month = deal_travel_month(deal)
        name = _MONTH_ABBR[month - 1] if month else "your travel month"
        out.append(f"Monsoon in {name} — heavy rain, rough seas")
    try:
        total = headline_total(deal)
        budget = float(config.max_budget_gbp)
    except (TypeError, ValueError):
        total, budget = 0.0, 0.0
    if budget > 0 and total > budget:
        out.append(f"{_gbp(total - budget)} over the {_gbp(budget)} budget")
    if board_code(getattr(deal, "board_basis", "")) == "UNVERIFIED":
        out.append("The rate read did not state what the room includes")
    if str(getattr(deal, "hotel_rate_basis", "")) == "estimate":
        out.append("Stay priced from the nearest dates on sale")
    if getattr(deal, "atol_protected", None) is False:
        out.append("Not an ATOL-protected package")
    return out[:MAX_WARNINGS]


# ---------------------------------------------------------------------------
# The card structures both renderings are built from
# ---------------------------------------------------------------------------

def _cards(config: HolidayConfig, deals: Sequence[PackageDeal], *,
           generated_at: Any,
           trends: Optional[Sequence[Mapping[str, Any]]] = None,
           last_report_at: Any = "") -> list[dict[str, Any]]:
    """One structure per card, cheapest cabin per resort first.

    Same order and same deduplication as the detailed renderer, so a resort
    that leads one e-mail leads the other: the table, the cards and the plain
    text can never disagree about which deal is the cheapest.
    """
    trend_by_resort: dict[str, Mapping[str, Any]] = {}
    for trend in trends or ():
        name = str(trend.get("resort_name", ""))
        # One line per RESORT: the cheapest cabin's trend is the card's trend.
        if name and name not in trend_by_resort:
            trend_by_resort[name] = trend
    travellers = int(config.travellers)
    ordered = sorted(deals, key=lambda d: float(d.total_package_price_gbp or 0.0))
    cards: list[dict[str, Any]] = []
    for deal in ordered:
        tag, tag_colour = freshness_tag(deal, generated_at=generated_at)
        cards.append({
            "deal": deal,
            "anchor": f"deal-{len(cards) + 1}",
            "name": str(deal.resort_name),
            "stars": "★" * max(0, min(5, int(deal.star_rating or 0))),
            "place": _place(deal),
            "dates": _deal_dates_words(deal),
            "nights": f"{int(deal.nights)} nights",
            "headline": _gbp(headline_total(deal)),
            "headline_words": f"total for {travellers}, door to door",
            "breakdown": breakdown_words(deal),
            "board": board_line(deal, travellers=travellers),
            "tag": tag,
            "tag_colour": tag_colour,
            "movement": movement_words(trend_by_resort.get(str(deal.resort_name)),
                                       last_report_at=last_report_at),
            "movement_short": movement_words(trend_by_resort.get(str(deal.resort_name)),
                                             last_report_at=last_report_at, with_date=False),
            "flights": flight_rows(deal, travellers=travellers),
            "why": why_lines(deal, config),
            "links": link_row(deal, config),
            "warnings": warning_lines(deal, config),
        })
    return cards


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

_INK = "#0f172a"
_MUTED = "#64748b"
_ACCENT = "#0f766e"
_LINE = "#e2e8f0"
_TAG_COLOURS = {"green": ("#dcfce7", "#166534"), "amber": ("#fef3c7", "#92400e"),
                "grey": ("#f1f5f9", "#475569")}
#: REPLY-H0 §4 collapses ten card tints and eight badge colours to four: one
#: accent for the headline total, one muted grey for everything explanatory,
#: amber only for "Estimate"/"Seen N days ago" and for a warning, green only
#: for a price that came down.
_MOVEMENT_COLOURS = {"green": "#166534", "amber": "#b45309", "grey": _MUTED}

#: At-a-glance columns that must never wrap mid-value: Dates and Total. The
#: board and movement columns DO wrap: six nowrap columns do not fit a 380 px
#: phone, and a clipped "tracked" is worse than a wrapped "Bed & Breakfast".
_GLANCE_NOWRAP = frozenset({2, 4})


def _esc(text: Any) -> str:
    return escape(str(text if text is not None else ""))


def _header_html(config: HolidayConfig, *, generated_at: Any) -> str:
    return "".join([
        '<div style="font-size:19px; font-weight:700; color:', _INK, '; line-height:1.3;">',
        _esc(config.report_title), '</div>',
        '<div style="font-size:13px; color:', _MUTED, '; margin:4px 0 2px 0;">',
        _esc(party_words(config)), ' · departing ',
        _esc(departure_range_words(config, generated_at=generated_at)),
        ' · ', _esc(nights_words(config)), '</div>',
        '<div style="font-size:12px; color:', _MUTED, ';">',
        _esc(prices_checked_words(generated_at)), '</div>',
    ])


def changed_lines(digest: Optional[Mapping[str, Any]]) -> list[str]:
    """The "what changed" lines — one resort per line, at most six.

    Shared by both renderings so the HTML and the plain-text part can never
    disagree about what moved (that is how a "first time tracked" line once
    ended up beside three resorts that had in fact just come under budget).

    Three states, and no fourth: nothing to compare with yet, prior data with
    no movement, or the movements themselves.
    """
    if not digest:
        return []
    if not digest.get("has_prior"):
        return ["First time tracked — nothing to compare with yet"]
    rows: list[str] = []
    for entry in list(digest.get("drops", []))[:MAX_WHAT_CHANGED_LINES]:
        rows.append(f"▼ {entry['name']} {_gbp(abs(float(entry['delta'])))} cheaper")
    for entry in list(digest.get("rises", []))[:max(0, MAX_WHAT_CHANGED_LINES - len(rows))]:
        rows.append(f"▲ {entry['name']} {_gbp(float(entry['delta']))} dearer")
    for name in list(digest.get("new", []))[:max(0, MAX_WHAT_CHANGED_LINES - len(rows))]:
        # "new" in the digest means the resort crossed INTO the under-budget
        # funnel, which is what the line says: "new" on its own read as fake the
        # moment every run had new resorts.
        rows.append(f"✦ {name} now under budget")
    return rows or ["Every tracked resort is at its previous price"]


def _what_changed_html(digest: Optional[Mapping[str, Any]], *, last_report_at: Any,
                       fallback_html: str = "") -> str:
    """One line per resort that moved, at most six, and never a ticker.

    A caller that passed only the detailed renderer's rendered digest has no
    trend rows to state in words, so its own HTML is used rather than a
    paraphrase nobody can verify.
    """
    if not digest:
        return fallback_html
    lines = changed_lines(digest)
    when = _day_words(digest.get("last_report_at") or last_report_at)
    head = "What changed" + (f" since {when}" if when else "")
    body = "<br>".join(_esc(line) for line in lines)
    return (
        f'<div style="margin:10px 0 0 0; font-size:12px; color:{_MUTED};">'
        f'<strong style="color:{_INK};">{_esc(head)}</strong><br>'
        + body
        + "</div>"
    )


def _glance_html(cards: Sequence[Mapping[str, Any]], *, travellers: int) -> str:
    """One table, one row per deal — the whole answer to "what is what"."""
    head_cells = ("Resort", "Where", "Dates", "Board", "Total for 5", "vs last time")
    out = [
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" ',
        'style="border-collapse:collapse; margin:12px 0 0 0;">',
        '<tr>',
    ]
    aligns = ("left", "left", "left", "left", "right", "left")
    for label, align in zip(head_cells, aligns):
        out.append(
            f'<td align="{align}" style="padding:4px 4px; font-size:11px; color:{_MUTED}; '
            f'border-bottom:2px solid {_LINE};">{_esc(label)}</td>'
        )
    out.append('</tr>')
    for card in cards:
        board = str(card["board"]).split(" · ")[0]
        cells = (
            f'<a href="#{card["anchor"]}" style="color:{_INK}; text-decoration:none; '
            f'font-weight:700;">{_esc(card["name"])}</a>',
            _esc(card["place"]),
            _esc(card["dates"]),
            _esc(board),
            f'<strong style="color:{_ACCENT}; white-space:nowrap;">{_esc(card["headline"])}</strong>',
            # Movement is the one secondary fact in this column, so it is set
            # one step smaller than the price beside it.
            f'<span style="font-size:11px; color:{_MUTED};">{_esc(card["movement_short"])}</span>',
        )
        out.append("<tr>")
        for index, (align, cell) in enumerate(zip(aligns, cells)):
            # Dates, board and the total are never allowed to break mid-value: a
            # range split across two lines ("18–" / "26 Dec") is worse than a
            # narrow column, and this table is read on a 380 px phone.
            nowrap = "white-space:nowrap;" if index in _GLANCE_NOWRAP else ""
            out.append(
                f'<td align="{align}" valign="top" style="padding:6px 4px; font-size:12px; '
                f'color:{_INK}; border-bottom:1px solid {_LINE}; {nowrap}">{cell}</td>'
            )
        out.append("</tr>")
    out.append("</table>")
    out.append(
        f'<div style="margin:6px 0 0 0; font-size:12px; color:{_MUTED};">'
        f'<strong style="color:{_INK};">Every price is the total for {int(travellers)}, '
        f"door to door.</strong></div>"
    )
    return "".join(out)


def _flight_table_html(rows: Sequence[tuple[str, str, Union[str, tuple[str, str]]]]) -> str:
    out = [
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" ',
        'style="border-collapse:collapse; margin:8px 0 0 0;">',
    ]
    for cabin, route, total in rows:
        if isinstance(total, tuple):
            price, url = total
            amount = (
                f'<a href="{_esc(url)}" style="color:{_ACCENT}; text-decoration:none; '
                f'font-weight:700;">{_esc(price)} ↗</a>' if url else _esc(price)
            )
        else:
            amount = f'<strong style="color:{_INK}; white-space:nowrap;">{_esc(total)}</strong>'
        out.append(
            '<tr>'
            f'<td style="padding:3px 4px; font-size:12px; color:{_INK}; white-space:nowrap;">'
            f'{_esc(cabin)}</td>'
            f'<td style="padding:3px 4px; font-size:12px; color:{_MUTED};">'
            f'{_esc(route)}</td>'
            f'<td align="right" style="padding:3px 4px; font-size:12px;">{amount}</td>'
            '</tr>'
        )
    out.append("</table>")
    return "".join(out)


def _card_html(card: Mapping[str, Any]) -> str:
    tag_bg, tag_fg = _TAG_COLOURS.get(str(card["tag_colour"]), _TAG_COLOURS["grey"])
    out = [
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" id="{card["anchor"]}" ',
        f'style="border-collapse:collapse; background:#ffffff; border:1px solid {_LINE}; ',
        'border-radius:10px; margin:12px 0 0 0;"><tr><td style="padding:12px 14px;">',
        '<div style="font-size:16px; font-weight:700; color:', _INK, ';">',
        _esc(card["name"]),
        f' <span style="color:#f59e0b; font-size:12px;">{_esc(card["stars"])}</span></div>',
        f'<div style="font-size:12px; color:{_MUTED}; margin:2px 0 8px 0;">',
        _esc(card["place"]), ' · ', _esc(card["dates"]), ' · ', _esc(card["nights"]), '</div>',
        f'<div style="font-size:26px; font-weight:800; color:{_ACCENT}; line-height:1.1;">',
        _esc(card["headline"]), '</div>',
        f'<div style="font-size:12px; color:{_MUTED};">{_esc(card["headline_words"])}</div>',
        f'<div style="font-size:12px; color:{_MUTED}; margin:2px 0 0 0;">{_esc(card["breakdown"])}</div>',
        f'<div style="font-size:13px; color:{_INK}; margin:6px 0 0 0;">{_esc(card["board"])}</div>',
        '<div style="font-size:11px; margin:6px 0 0 0;">',
        f'<span style="background:{tag_bg}; color:{tag_fg}; padding:2px 8px; ',
        f'border-radius:9999px;">{_esc(card["tag"])}</span> ',
        f'<span style="color:{_MOVEMENT_COLOURS[movement_colour(str(card["movement"]))]}">',
        _esc(card["movement"]), '</span></div>',
    ]
    if card["flights"]:
        out.append(_flight_table_html(card["flights"]))
    if card["why"]:
        out.append(
            f'<div style="font-size:12px; color:{_MUTED}; margin:8px 0 0 0;">'
            + "<br>".join("• " + _esc(line) for line in card["why"])
            + "</div>"
        )
    if card["links"]:
        out.append(f'<div style="font-size:12px; margin:8px 0 0 0;">')
        for index, (label, url) in enumerate(card["links"]):
            if index:
                out.append(f'<span style="color:{_MUTED};"> · </span>')
            out.append(
                f'<a href="{_esc(url)}" style="color:{_ACCENT}; text-decoration:none; '
                f'font-weight:600;">{_esc(label)} ↗</a>'
            )
        out.append("</div>")
    for warning in card["warnings"]:
        out.append(
            f'<div style="font-size:12px; color:#92400e; margin:4px 0 0 0;">⚠ {_esc(warning)}</div>'
        )
    out.append("</td></tr></table>")
    return "".join(out)


def _over_budget_html(config: HolidayConfig) -> str:
    """One compact line per resort priced but over the budget."""
    keys = {d.key.lower() for d in config.destinations}
    rows = [row for row in hol.LAST_OVER_BUDGET
            if str(row.get("destination_key", "")).lower() in keys]
    if not rows:
        return ""
    try:
        budget = float(rows[0].get("max_budget_gbp", 0.0))
    except (TypeError, ValueError):
        budget = 0.0
    lines = [
        f'<div style="font-size:12px; color:{_MUTED}; margin:14px 0 0 0;">',
        f'<strong style="color:{_INK};">Over the {_gbp(budget)} budget</strong>',
        " — priced, no option fits:</div>",
    ]
    for row in rows:
        try:
            total = float(row.get("true_d2d", 0.0))
        except (TypeError, ValueError):
            total = 0.0
        over = max(total - budget, 0.0)
        lines.append(
            f'<div style="font-size:12px; color:{_MUTED}; padding:2px 0 0 0;">'
            f'{_esc(row.get("resort_name", ""))} · {_esc(_place(row.get("destination_label", "")))} · '
            f'{_gbp(total)} for {int(config.travellers)} · {_gbp(over)} over</div>'
        )
    return "".join(lines)


def _watch_reason(row: Mapping[str, Any]) -> str:
    """Why a watched destination has no price here — never a benchmark figure."""
    if not row.get("in_season"):
        return "outside its season"
    if float(row.get("over_budget_gbp", 0.0) or 0.0) > 0:
        return "over budget"
    return "no fare read for these dates"


def _watch_html(config: HolidayConfig) -> str:
    """Destinations watched but never priced — stated as watches, not as deals.

    No figure is printed for a watch row. The critique's own footer said the
    benchmark rows were the ones nobody could act on, and AMEND-H1 §2 removes
    benchmark movement from this e-mail entirely: a destination with no read
    fare gets a dated search link and the words "no live price read".
    """
    rows = far_east_watch_rows(config)
    if not rows:
        return ""
    out = [
        f'<div style="font-size:12px; color:{_MUTED}; margin:12px 0 0 0;">',
        f'<strong style="color:{_INK};">On the watch list</strong> — no live price read, '
        'so no price is shown:</div>',
    ]
    for row in rows:
        name = hol.HOLIDAY_SEARCH_QUERIES.get(str(row.get("key", "")), str(row.get("key", "")))
        url = str(row.get("flights_url", "") or "")
        name_html = (
            f'<a href="{_esc(url)}" style="color:{_ACCENT}; text-decoration:none;">'
            f'{_esc(name)} ↗</a>' if url else _esc(name)
        )
        out.append(
            f'<div style="font-size:12px; color:{_MUTED}; padding:2px 0 0 0;">'
            f'{name_html} · {_esc(_watch_reason(row))}</div>'
        )
    return "".join(out)


def _notes_html(config: HolidayConfig, deals: Sequence[PackageDeal]) -> str:
    """Strict filters and rules that could not be applied — one line each."""
    lines: list[str] = []
    for name, reason in hol.LAST_FILTERED_OUT:
        text = str(reason)
        if len(text) > 96:
            text = text[:93].rstrip() + "…"
        lines.append(f"{_esc(name)} — {_esc(text)}")
    shown = {d.resort_name for d in deals}
    for name in sorted(shown):
        if hol.tripadvisor_unverified(name):
            lines.append(f"{_esc(name)} — guest rating not checked")
        if not hol.is_summer_trip(config) and hol.pool_heating_unverified(name):
            lines.append(f"{_esc(name)} — heated pool not stated")
    if not lines:
        return ""
    out = [
        f'<div style="font-size:11px; color:{_MUTED}; margin:14px 0 0 0;">',
        f'<strong style="color:{_INK};">Notes</strong><br>',
    ]
    for line in lines:
        out.append(line + "<br>")
    out.append("</div>")
    return "".join(out)


def render_holiday_report_compact(
    config: HolidayConfig,
    *,
    generated_at: str,
    deals: Sequence[PackageDeal] = (),
    history_chips: Optional[Sequence[str]] = None,
    change_digest_html: str = "",
    trends: Optional[Sequence[Mapping[str, Any]]] = None,
    digest: Optional[Mapping[str, Any]] = None,
    last_report_at: str = "",
) -> str:
    """The compact holiday e-mail. Same arguments as the detailed renderer.

    ``trends``/``digest``/``last_report_at`` carry what the change digest and
    the history chips carry, in a form this renderer can state in one line per
    resort: AMEND-H1 §2 forbids both the chip wall and any benchmark movement,
    so movement has to come from the trend rows rather than from rendered HTML.
    They are optional so a caller that only has the detailed renderer's
    arguments still gets a valid e-mail (every card then reads "first time
    tracked").
    """
    cards = _cards(config, deals, generated_at=generated_at, trends=trends,
                   last_report_at=last_report_at or str(
                       (digest or {}).get("last_report_at", "") or ""))
    out: list[str] = [
        '<!DOCTYPE html><html><head><meta charset="utf-8"><title>',
        _esc(config.report_title),
        '</title></head><body style="margin:0; padding:0; background:#f1f5f9; ',
        'font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif; ',
        'line-height:1.45;"><table role="presentation" width="100%" bgcolor="#f1f5f9" ',
        'cellpadding="0" cellspacing="0"><tr><td align="center" style="padding:14px 10px;">',
        '<table role="presentation" width="600" cellpadding="0" cellspacing="0" ',
        'style="width:100%; max-width:600px;"><tr><td>',
        _header_html(config, generated_at=generated_at),
    ]
    if digest or change_digest_html:
        out.append(_what_changed_html(digest, last_report_at=last_report_at,
                                      fallback_html=change_digest_html))
    if cards:
        out.append(_glance_html(cards, travellers=int(config.travellers)))
    rendered = 0
    for card in cards:
        card_start = len(out)
        out.append(_card_html(card))
        rendered += 1
        if (
            rendered > hol.MIN_RENDERED_HOTEL_CARDS
            and sum(len(chunk) for chunk in out) + hol._CLOSING_TAIL_ALLOWANCE_BYTES
            > hol.EMAIL_HTML_BUDGET_BYTES
        ):
            del out[card_start:]
            out.append(
                f'<div style="font-size:12px; color:{_MUTED}; margin:12px 0 0 0;">'
                f'{len(cards) - rendered + 1} further deal(s) not shown: this e-mail is near '
                f"Gmail's {hol.EMAIL_HTML_BUDGET_BYTES // 1000} KB payload cap.</div>"
            )
            break
    out.append(_over_budget_html(config))
    out.append(_watch_html(config))
    out.append(_notes_html(config, deals))
    out.append("</td></tr></table></td></tr></table></body></html>")
    return "".join(out)


# ---------------------------------------------------------------------------
# Plain text: the same order, the same numbers
# ---------------------------------------------------------------------------

def render_holiday_report_compact_text(
    config: HolidayConfig,
    *,
    generated_at: str,
    deals: Sequence[PackageDeal] = (),
    history_chips: Optional[Sequence[str]] = None,
    change_digest_html: str = "",
    trends: Optional[Sequence[Mapping[str, Any]]] = None,
    digest: Optional[Mapping[str, Any]] = None,
    last_report_at: str = "",
) -> str:
    """The plain-text twin of ``render_holiday_report_compact``.

    ``mailer.send_html`` sends a text part, so a text part that says "open this
    in an HTML-capable client" is a part that carries none of the decision.
    Built from the same card structures, in the same order.
    """
    cards = _cards(config, deals, generated_at=generated_at, trends=trends,
                   last_report_at=last_report_at or str(
                       (digest or {}).get("last_report_at", "") or ""))
    lines: list[str] = [
        str(config.report_title),
        f"{party_words(config)} · departing "
        f"{departure_range_words(config, generated_at=generated_at)} · {nights_words(config)}",
        prices_checked_words(generated_at),
        "",
    ]
    if digest or change_digest_html:
        when = _day_words(last_report_at or (digest or {}).get("last_report_at") or "")
        lines.append("What changed" + (f" since {when}" if when else ""))
        for line in changed_lines(digest) or ([change_digest_html] if change_digest_html else []):
            lines.append(f"  {line}")
        lines.append("")
    if cards:
        lines.append(
            f"At a glance (every price is the total for {int(config.travellers)}, door to door)"
        )
        for index, card in enumerate(cards, start=1):
            lines.append(
                f"  {index}. {card['name']} · {card['place']} · {card['dates']} · "
                f"{str(card['board']).split(' · ')[0]} · {card['headline']} · {card['movement']}"
            )
        lines.append("")
    for card in cards:
        lines.append(
            f"{card['name']} {card['stars']} · {card['place']} · {card['dates']} · {card['nights']}"
        )
        lines.append(f"  {card['headline']} — {card['headline_words']}")
        if card["breakdown"]:
            lines.append(f"  {card['breakdown']}")
        lines.append(f"  {card['board']}")
        lines.append(f"  {card['tag']} · {card['movement']}")
        for cabin, route, total in card["flights"]:
            price = total[0] if isinstance(total, tuple) else total
            lines.append(f"  {cabin} · {route} · {price}")
        for line in card["why"]:
            lines.append(f"  • {line}")
        if card["links"]:
            lines.append("  " + " · ".join(label for label, _ in card["links"]))
        for warning in card["warnings"]:
            lines.append(f"  ! {warning}")
        lines.append("")
    keys = {d.key.lower() for d in config.destinations}
    over = [row for row in hol.LAST_OVER_BUDGET
            if str(row.get("destination_key", "")).lower() in keys]
    if over:
        budget = float(over[0].get("max_budget_gbp", 0.0))
        lines.append(f"Over the {_gbp(budget)} budget — priced, no option fits")
        for row in over:
            total = float(row.get("true_d2d", 0.0))
            lines.append(
                f"  {row.get('resort_name', '')} · {_place(row.get('destination_label', ''))} · "
                f"{_gbp(total)} for {int(config.travellers)} · "
                f"{_gbp(max(total - budget, 0.0))} over"
            )
        lines.append("")
    watch = far_east_watch_rows(config)
    if watch:
        lines.append("On the watch list — no live price read, so no price is shown")
        for row in watch:
            name = hol.HOLIDAY_SEARCH_QUERIES.get(str(row.get("key", "")), str(row.get("key", "")))
            lines.append(f"  {name} · {_watch_reason(row)}")
        lines.append("")
    notes = _notes_lines(config, deals)
    if notes:
        lines.append("Notes")
        lines.extend("  " + note for note in notes)
    return "\n".join(lines).rstrip() + "\n"


def _notes_lines(config: HolidayConfig, deals: Sequence[PackageDeal]) -> list[str]:
    lines: list[str] = []
    for name, reason in hol.LAST_FILTERED_OUT:
        text = str(reason)
        if len(text) > 96:
            text = text[:93].rstrip() + "…"
        lines.append(f"{name} — {text}")
    shown = {d.resort_name for d in deals}
    for name in sorted(shown):
        if hol.tripadvisor_unverified(name):
            lines.append(f"{name} — guest rating not checked")
        if not hol.is_summer_trip(config) and hol.pool_heating_unverified(name):
            lines.append(f"{name} — heated pool not stated")
    return lines