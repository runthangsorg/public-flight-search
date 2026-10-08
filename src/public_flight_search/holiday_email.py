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
from .cabin import SHORT_HAUL_CABIN
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
    wet_season_words_compact,
)
from .google_flights import build_google_flights_legs_url
from .multi_centre import load_multi_centre, trip_legs_for_dates
from .vendors import build_vendor_links, trip_from_deal

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

    A card priced from an OPERATOR PACKAGE has no split to show. The operator
    displayed one figure for flights + board + rooms; dividing it into a
    flight half and a stay half would be a split nobody published, so the
    package is the single part and it sums to itself by construction (owner
    decision 2, 2026-10-04).
    """
    total = headline_total(deal)
    if bool(getattr(deal, "package_priced", False)):
        package = getattr(deal, "operator_package", None)
        if package is not None:
            return ([("flights + board + rooms", total)], total)
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
    summed = round(sum(amount for _, amount in parts), 2)
    if parts and abs(summed - total) > 0.5:
        parts.append(("other", round(total - summed, 2)))
    return parts, total


def _pound_int(value: Any) -> int:
    """The whole-pound figure :func:`_gbp` will PRINT for ``value``.

    The same rounding ``_gbp`` uses - Python's round-half-to-even - so this is
    the printed number, not a nicer-looking one. Returning an int is the point:
    the breakdown line ends in ``= £X``, which is an equality claim, and an
    equality claim has to be true of the digits on the page.
    """
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return 0
    if amount != amount or amount in (float("inf"), float("-inf")):
        # NaN/inf print as "nan"/"inf" through _gbp and cannot be reconciled;
        # treat them as nothing rather than render a line that cannot add up.
        return 0
    return int(round(amount))


#: The cabin words a reader knows, keyed by the deal's own ``cabin_class``.
#: AMEND-H1 §6 allows airport codes on the flight rows; this is the one place
#: a cabin is named in the compact e-mail, and "business" / "economy" /
#: "premium economy" are the words the owner uses about them.
_CABIN_WORDS: dict[str, str] = {
    "BUSINESS": "business",
    "ECONOMY": "economy",
    "PREMIUM_ECONOMY": "premium economy",
    "FIRST": "first",
    "MIXED_CABIN": "mixed cabins",
}


def cabin_words(deal: PackageDeal) -> str:
    """``business`` / ``economy`` / ``premium economy``, or "" if unstated."""
    return _CABIN_WORDS.get(str(getattr(deal, "cabin_class", "") or "").strip().upper(), "")


def breakdown_display_parts(deal: PackageDeal) -> tuple[list[tuple[str, int]], int]:
    """The breakdown parts AS PRINTED, and the headline AS PRINTED.

    ``breakdown_parts`` is exact - floats that really do sum to the headline -
    but the line renders each part through ``_gbp``, which rounds every part
    independently. Two cards shipped a line whose printed parts were a pound
    short of the printed total (REVIEW-H3 P0): the invariant held on the
    floats and failed on the page, which is the only place a reader checks it.

    So the arithmetic is done here, on the printed integers: every part but the
    last is rounded, and the last carries whatever is left over. The line then
    adds up to the digit.
    """
    parts, total = breakdown_parts(deal)
    headline = _pound_int(total)
    if not parts:
        return [], headline
    labels = [label for label, _ in parts]
    displayed = [_pound_int(amount) for _, amount in parts]
    # The residual is at most a couple of pounds - it is the sum of the
    # independent roundings - and it lands on the last part, which is the
    # smallest and least audited number on the line. The fare itself is never
    # the part that absorbs it.
    residual = headline - sum(displayed)
    amounts = displayed[:-1] + [displayed[-1] + residual]
    if amounts[-1] <= 0 and len(amounts) > 1:
        # A last part of a few pence would go negative once the residual lands
        # on it, and a negative transfer is worse than a merged label. Merging
        # keeps the sum exact: (a + b) where b <= 0 is still a.
        labels = labels[:-2] + [f"{labels[-2]} + {labels[-1]}"]
        amounts = amounts[:-2] + [amounts[-2] + amounts[-1]]
    return list(zip(labels, amounts)), headline


def breakdown_words(deal: PackageDeal) -> str:
    """``flights £648 (economy) + stay £1,200 + transfers £42 = £1,890``.

    The printed pounds are the ones that were added up, and the cabin is named
    on the flight line because the headline is that flight: on a Business card
    the fare is most of the price and nothing else on the card says which
    cabin it is (REVIEW-H3 P1). A package-priced card names the cabin on its
    single part for the same reason — the package IS the flights, the board and
    the rooms, and its cabin is the one the operator searched.
    """
    parts, headline = breakdown_display_parts(deal)
    if not parts:
        return ""
    cabin = cabin_words(deal)
    body = " + ".join(
        f"{label} £{amount:,}"
        + (f" ({cabin})" if label.startswith("flights") and cabin else "")
        for label, amount in parts
    )
    return f"{body} = £{headline:,}"


def freshness_tag(deal: PackageDeal, *, generated_at: Any) -> tuple[str, str]:
    """The card's one provenance tag: words, colour, and never a badge wall.

    REPLY-H0 §4 replaces three badges with three sentences. The tag names the
    WEAKER of the two legs, because the headline is both legs: a live fare
    beside an estimated room rate is not a live price.

    BRIEF-H17 §6 (2026-10-06) makes that literal. "Live price" claims the WHOLE
    price was checked, so it may only appear where it was: a read for these exact
    dates, or an operator's own quote for them. A card whose flights are live and
    whose stay is the catalogue's — six December cards said "Live price · checked
    today" directly above "so the stay here is the catalogue's estimate" — reads
    "Flights live · stay estimated" instead, which names the live leg and the
    estimated one and contradicts nothing. A nightly carried from another pair is
    an estimate too, so it says which estimate: "Flights live · stay from a read
    rate" (its board line names the pair it came from).
    """
    confidence = str(getattr(deal, "confidence", "") or "")
    live = confidence == "verified-exact-date"
    stale = confidence == "stale-cache"
    age = observation_age_hours(getattr(deal, "live_observed_at", ""), generated_at)
    if (live or stale) and age is not None and age > hol.live_verify.EVIDENCE_MAX_AGE_HOURS:
        # The same render-time ageing the detailed card applies: an observation
        # that has aged out may not claim to be live.
        live, stale = False, True
    basis = str(getattr(deal, "hotel_rate_basis", "") or "")
    hotel_estimated = basis == "estimate"
    hotel_read = getattr(deal, "hotel_evidence", None) is not None
    # A stay whose nightly came from a read for ANOTHER pair (BRIEF-H14 §1). It
    # is not a catalogue guess, and it is not a read for these dates either: the
    # card names the read on its board line, and the tag here says only that the
    # stay is from a read rate. "checked today" would be claiming both halves
    # were read for this trip, which is the claim the owner's report caught.
    stay_from_read = basis == "read-rate-estimate"
    # The only two bases that are a price FOR THESE DATES. Anything else on a
    # live card is the catalogue's own figure or an estimate of one, and the tag
    # may not say the price was checked.
    stay_is_a_price_for_these_dates = basis in (
        "exact-date-rate", "operator package")
    if live:
        if stay_from_read:
            return "Flights live · stay from a read rate", "green"
        if not stay_is_a_price_for_these_dates:
            return "Flights live · stay estimated", "green"
        return f"Live price · checked {_checked_words(age)}", "green"
    if stale:
        return f"Seen {relative_age_label(age) or 'earlier'}", "amber"
    if stay_from_read:
        return "Stay read for other dates", "grey"
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
# The operator's own package price, beside the headline and never instead
# ---------------------------------------------------------------------------

#: The exporter writes one clause per room into ``derived_total_gbp.how``:
#: ``room 1 GBP 3,884.24 (2 adults, <room name>) + room 2 GBP 5,509.55 (3 adults,
#: <room name>)``. Those clauses carry the per-room figures, which is the only
#: place they exist, so they are lifted out for the card. Prose that does not
#: match is not guessed at: the card falls back to the exporter's own words,
#: clipped, because a wrong per-room figure is worse than a long one.
_ROOM_CLAUSE = re.compile(
    r"room\s+(\d+)\s*£\s*([\d,]+(?:\.\d+)?)\s*\(\s*(\d+)\s*adults?", re.IGNORECASE
)

#: Link kinds that carry the operator's own quote for THESE dates. A
#: ``search-page`` or ``destination-page`` link would drop the reader on a form
#: with no dates on it, so the operator's name is shown as plain text instead.
_PACKAGE_LINK_KINDS: frozenset[str] = frozenset({"deep-link", "prefilled-search"})


def _rooms_added_words(package: Any) -> str:
    """``2 rooms added: room 1 GBP 4,113 (2 adults), room 2 GBP 5,848 (3 adults)``.

    Empty when the exporter's wording carries no per-room figures, which is the
    signal to print nothing here rather than a half-parsed sentence.
    """
    clauses = _ROOM_CLAUSE.findall(str(getattr(package, "how", "") or ""))
    if len(clauses) < 2:
        return ""
    rooms = ", ".join(
        f"room {number} £{_pound_int(amount.replace(',', '')):,} ({adults} adults)"
        for number, amount, adults in clauses
    )
    return f"{len(clauses)} rooms added: {rooms}"


def _package_line_html(deal: PackageDeal, *, travellers: int) -> str:
    """One card's package line as HTML, from the same segments as the text part.

    Only the operator's own name is a link, and only when the link carries this
    trip's quote. Everything else is escaped plain text.
    """
    segments = _package_segments(deal, travellers=travellers)
    if not segments:
        return ""
    url = _package_link(deal)
    out: list[str] = []
    for text, is_operator in segments:
        if is_operator and url:
            out.append(
                f'<a href="{escape(url, quote=True)}" style="color:{_ACCENT}; '
                f'text-decoration:none;">{_esc(text)} ↗</a>'
            )
        elif is_operator:
            # No link that keeps the dates: say so rather than offer a dead end.
            out.append(_esc(text))
            out.append(
                '<span style="color:%s;"> (dates to enter on their site)</span>'
                % _MUTED
            )
        else:
            out.append(_esc(text))
    return "".join(out)


def package_words(deal: PackageDeal, *, travellers: int) -> str:
    """``Package deal: £9,394 for 5 - Example Holidays, Bed & Breakfast, 2 rooms``.

    Empty when no qualifying operator package was read for this card's dates,
    which is the state of every card before the seam existed.

    The line never becomes the headline: it is the operator's own price for one
    booking on these dates, sitting BESIDE the engine's total so the reader can
    see the gap. WP4d D2/D3; AMEND-H1's rule that the card carries one headline
    price is untouched - this is a comparison line with its own subject, not a
    second headline.
    """
    segments = _package_segments(deal, travellers=travellers)
    if not segments:
        return ""
    # Concatenated, not joined: every segment carries its own punctuation (the
    # em dash after the price, the comma after the operator, the middot before
    # each tail), so a separator here would print "operator · , board".
    return "".join(text for text, _ in segments)


def _package_segments(
    deal: PackageDeal, *, travellers: int
) -> list[tuple[str, bool]]:
    """``[(text, is_the_operator_name)]`` for one card's package line.

    One list, two renderings. The HTML marks the operator's name as the link
    (or not) and the plain-text part prints the same words, so the two can never
    drift into saying different things - which is the failure mode this
    renderer's other fixes were about.

    Two shapes, and the difference matters. On a card the engine priced itself
    the package is a COMPARISON beside that headline. On a card priced FROM an
    operator package (owner decision 2, 2026-10-04) the package IS the headline,
    so the line says so in its first words and states what the figure covers —
    flights, board and rooms for the party, with the rooms counted — rather
    than "£X less than booking separately", which would be comparing the
    headline with itself.
    """
    package = getattr(deal, "operator_package", None)
    if package is None:
        return []
    board = hol.BOARD_LABELS.get(
        str(getattr(package, "board", "")).strip().upper(),
        str(getattr(package, "board", "") or ""),
    )
    operator = str(getattr(package, "operator", "") or "").strip()
    rooms = int(getattr(package, "rooms", 0) or 0)
    priced = bool(getattr(deal, "package_priced", False))
    lead = (
        f"This price is the operator's package: {_gbp(getattr(package, 'total_gbp', 0.0))} for {int(travellers)}"
        if priced
        else f"Package deal: {_gbp(getattr(package, 'total_gbp', 0.0))} for {int(travellers)}"
    )
    # What the figure covers. On a comparison line the operator's own board is
    # enough; on the headline it has to be explicit, because this is the only
    # place the reader learns the price includes the flights.
    detail = (
        f"flights + {board}, {rooms} {'room' if rooms == 1 else 'rooms'}"
        if priced
        else f"{board}, {rooms} {'room' if rooms == 1 else 'rooms'}"
    )
    tail: list[str] = []
    checked = _day_words(getattr(package, "observed_at", ""), generated_at="")
    if checked:
        tail.append(f"checked {checked}")
    gap = float(getattr(package, "vs_engine_gbp", 0.0) or 0.0)
    if gap > 0:
        tail.append(f"{_gbp(gap)} less than booking separately")
    elif gap < 0:
        tail.append(f"{_gbp(abs(gap))} more than booking separately")
    elif not priced:
        # On a package-priced card this clause could not be said at all: the gap
        # is measured against the ENGINE's own quote for the same trip, so "the
        # same as booking separately" is only true when the engine priced this
        # headline itself.
        tail.append("the same as booking separately")
    # (text, is_operator_name). The operator's name is its own segment so the
    # HTML can link exactly that and nothing else.
    segments = [(f"{lead} — ", False), (operator, True), (f", {detail}", False)]
    for extra in tail:
        segments.append((f" · {extra}", False))
    return segments


def _package_link(deal: PackageDeal) -> str:
    """The operator's own quote URL, or "" when the link would drop the dates.

    A ``search-page`` or ``destination-page`` link lands the reader on a form
    with nothing filled in, so it is shown as words instead of a link that
    promises this trip's price and cannot deliver it.
    """
    package = getattr(deal, "operator_package", None)
    if package is None:
        return ""
    kind = str(getattr(package, "link_kind", "")).strip().lower()
    if kind not in _PACKAGE_LINK_KINDS:
        return ""
    url = str(getattr(package, "source_url", "") or "")
    return url if url.startswith(("http://", "https://")) else ""


# ---------------------------------------------------------------------------
# The over-budget list's package note (owner brief H9, 2026-10-04)
# ---------------------------------------------------------------------------

#: Board words for the over-budget note. The card's line uses ``BOARD_LABELS``
#: ("Bed & Breakfast"); the sentence the owner asked for on this list is
#: "flights + B&B", a shorter spelling of the same board, so it is spelled here
#: rather than by widening a map every other renderer reads.
_OVER_PACKAGE_BOARD: dict[str, str] = {
    "BB": "B&B",
    "HB": "Half Board",
    "FB": "Full Board",
    "AI": "All Inclusive",
    "RO": "Room Only",
}

# ---------------------------------------------------------------------------
# A HELD-BACK RESORT IS NAMED, WITH ITS PRICE AND ITS REASON
# (owner brief H16 §1, 2026-10-06)
# ---------------------------------------------------------------------------

#: What priced a held-back row's two halves, in the fewest words that are still
#: true of them. The audit page spells the same two facts out in full
#: (``holidays._FLIGHT_BASIS_WORDS`` / ``_HOTEL_BASIS_WORDS``); these are the
#: short forms of the same wordings, so the two renderers cannot disagree about
#: what priced a number and neither has to be shortened at the call site.
_HELD_FLIGHT_WORDS: dict[str, str] = {
    "verified-exact-date": "a live fare read",
    "stale-cache": "an observed fare, not live",
    "benchmark": "a benchmark fare",
}
_HELD_STAY_WORDS: dict[str, str] = {
    # The three bases a row's stay can carry are the card's own three
    # (``PackageDeal.hotel_rate_basis``), so this reads them and the card's
    # words elsewhere stay the reference.
    "exact-date-rate": "a rate read for these dates",
    "read-rate-estimate": "a rate read for another pair",
    "market-supported": "a rate read for these dates",
    "estimate": "an estimate",
}


def _row_field(row: Any, key: str, default: str = "") -> str:
    """A row's field — rows are dicts, and a patched test row may be anything."""
    getter = getattr(row, "get", None)
    if callable(getter):
        return str(getter(key, default) or default)
    return str(getattr(row, key, default) or default)


def _raw_field(row: Any, key: str, default: Any = None) -> Any:
    """A row's field unstringified — for the ones that are a tuple of dates."""
    getter = getattr(row, "get", None)
    if callable(getter):
        value = getter(key, default)
        return default if value is None else value
    return getattr(row, key, default)


def _over_package(row: Any) -> Any:
    """The operator package attached to an over-budget row, or None."""
    getter = getattr(row, "get", None)
    if callable(getter):
        return getter("package")
    return getattr(row, "package", None)


def _nights_between(first: Any, second: Any) -> Optional[int]:
    """Nights between two ISO days, or None when either will not parse."""
    try:
        start = datetime.strptime(str(first), "%Y-%m-%d")
        end = datetime.strptime(str(second), "%Y-%m-%d")
    except (TypeError, ValueError):
        return None
    return (end - start).days


def _package_is_comparable(package: Any, row_nights: Optional[int]) -> bool:
    """Whether this package may be judged against the row's ceiling.

    True for one that is the SAME trip: within two nights of the row's own
    stay. A package read for a materially shorter holiday is a different trip,
    and saying it "fits the budget" beside a fortnight's price would be
    answering a question nobody asked (REVIEW-H9 P2-7). Two nights is the
    tolerance because a day either side of a departure is a schedule
    difference, not a different holiday.

    The ceiling itself is checked where the claim is written, in
    ``over_package_segments``.
    """
    if row_nights is None:
        return True
    try:
        from .package_evidence import PACKAGE_NIGHTS_TOLERANCE, package_shortfall_nights

        shortfall = package_shortfall_nights(package, row_nights)
    except Exception:  # noqa: BLE001 - a missing field must not break the note
        return True
    if shortfall is None:
        return True
    return shortfall <= PACKAGE_NIGHTS_TOLERANCE


def over_package_link(row: Any) -> str:
    """The operator's own quote URL for this row's package, or "".

    The H8 link rule, unchanged: only a link that carries this trip's quote
    (``deep-link``/``prefilled-search``) becomes a link; anything else is
    words, so the reader is never sent to a form with nothing filled in.
    """
    package = _over_package(row)
    if package is None:
        return ""
    kind = str(getattr(package, "link_kind", "")).strip().lower()
    if kind not in _PACKAGE_LINK_KINDS:
        return ""
    url = str(getattr(package, "source_url", "") or "")
    return url if url.startswith(("http://", "https://")) else ""


def over_package_segments(
    row: Any, *, travellers: int, generated_at: str = ""
) -> list[tuple[str, bool]]:
    """``[("— package deal £10,957 for 5 (", False), ("Destination2", True), …]``.

    The owner's sentence (brief H9, 2026-10-04), in segments so the HTML can
    link exactly the operator's name and the text part can print the same
    words. Two honesties beyond the literal wording:

    * the board is spelled the way the sentence spells it ("flights + B&B"),
      which is not the card line's "Bed & Breakfast";
    * when the operator quoted OTHER dates than the row's — the usual case,
      because a row's own pair is by definition the expensive one — the dates
      are appended, so the note never implies this trip's price for a read
      that was for the neighbouring fortnight;
    * a package that is itself over the row's ceiling is not quoted at all,
      because "fits the budget" would then say the opposite of the row.
    """
    package = _over_package(row)
    if package is None:
        return []
    operator = str(getattr(package, "operator", "") or "").strip()
    if not operator:
        return []
    raw_board = str(getattr(package, "board", "") or "")
    board = _OVER_PACKAGE_BOARD.get(raw_board.strip().upper(), raw_board)
    rooms = int(getattr(package, "rooms", 0) or 0)
    total = float(getattr(package, "total_gbp", 0.0) or 0.0)
    # The sentence claims the package FITS. Say nothing when it does not: the
    # collector attaches only in-budget reads, but this is where the claim is
    # made, so this is where it is judged — a row with no ceiling cannot be
    # judged and is left alone.
    ceiling = _row_field(row, "max_budget_gbp")
    if ceiling:
        try:
            if total > float(ceiling):
                return []
        except ValueError:
            pass
    include = f"flights + {board}" if board else "flights"
    segments: list[tuple[str, bool]] = [
        (f"— package deal £{total:,.0f} for {int(travellers)} (", False),
        (operator, True),
        (f", {include}, {rooms} {'room' if rooms == 1 else 'rooms'})", False),
    ]
    package_out = str(getattr(package, "outbound_date", "") or "")
    package_return = str(getattr(package, "return_date", "") or "")
    row_out = _row_field(row, "outbound")
    row_return = _row_field(row, "return")
    if package_out and (package_out, package_return) != (row_out, row_return):
        segments.append((
            f" for {_range_words(package_out, package_return, generated_at=generated_at)}",
            False,
        ))
    # NIGHTS, and the one thing the date range cannot say on its own: a
    # package read for a SHORTER stay than the row is a different holiday, not
    # the same trip cheaper. Two calendars can share an end date and still be
    # a fortnight apart, so the number is printed whenever the nights differ
    # (REVIEW-H9 P2-7).
    row_nights = _nights_between(row_out, row_return)
    package_nights = _nights_between(package_out, package_return)
    if (
        row_nights is not None and package_nights is not None
        and package_nights != row_nights
    ):
        segments.append((
            f", {package_nights} nights against this row's {row_nights}",
            False,
        ))
    if not _package_is_comparable(package, row_nights):
        # The note would otherwise compare a three-week holiday with the
        # fortnight above it and say "fits the budget", which is a claim about
        # a trip nobody is being offered. It stays quotable, with its own
        # nights named above; only the verdict is withheld.
        return []
    segments.append((" fits the budget", False))
    return segments


def over_package_words(
    row: Any, *, travellers: int, generated_at: str = ""
) -> str:
    """The note as plain text — empty when the row has no qualifying package."""
    segments = over_package_segments(row, travellers=travellers,
                                     generated_at=generated_at)
    return "".join(text for text, _ in segments)


def over_package_html(row: Any, *, travellers: int, generated_at: str = "") -> str:
    """The note as HTML: the operator's name linked under the H8 link rules."""
    segments = over_package_segments(row, travellers=travellers,
                                     generated_at=generated_at)
    if not segments:
        return ""
    url = over_package_link(row)
    out: list[str] = []
    for text, is_operator in segments:
        if is_operator and url:
            out.append(
                f'<a href="{escape(url, quote=True)}" style="color:{_ACCENT}; '
                f'text-decoration:none;">{_esc(text)} ↗</a>'
            )
        elif is_operator:
            out.append(_esc(text))
            out.append(
                '<span style="color:%s;"> (dates to enter on their site)</span>'
                % _MUTED
            )
        else:
            out.append(_esc(text))
    return "".join(out)


def _held_stay_words(row: Any) -> str:
    """The stay half of a held-back line, naming the read it came from when it
    was carried from another pair.

    A nightly derived from a read for a neighbouring fortnight is an estimate
    and has to read as one — the same rule the card's board line follows
    (``hotel_rate_basis`` = ``read-rate-estimate``). The read's own dates are
    in the sentence because "a rate read for another pair" is not something a
    reader can check; "20–27 Jul" is.
    """
    basis = _row_field(row, "hotel_rate_basis") or "market-supported"
    if basis != "read-rate-estimate":
        return _HELD_STAY_WORDS.get(basis, _HELD_STAY_WORDS["estimate"])
    read_dates = _raw_field(row, "hotel_rate_read_dates")
    first, second = (list(read_dates) + ["", ""])[:2]
    if first and second:
        # "another pair" first, then the pair: a reader who saw only the dates
        # could take them for this row's own, which is the one thing they are
        # not. The card's board line says the same thing in its own place.
        return f"a rate read for another pair, {_range_words(first, second)}"
    return _HELD_STAY_WORDS["read-rate-estimate"]


def held_back_sentence(row: Any, *, travellers: int, generated_at: Any = "") -> str:
    """One compact line for a resort the short-haul rule held back.

    ``Lara Barut Collection · 17–25 Dec · £8,994 for 5, door to door · priced
    by a benchmark fare and a rate read for these dates · held back: Antalya
    Riviera, Turkey has cards within budget``

    BRIEF-H16 §1 (2026-10-06). The owner read the December report, where Lara
    Barut had been item 2 and then appeared nowhere, and asked for the resort
    to be named with its price and the reason. Every piece of the line is a
    fact the collector already holds — the row's own pair, its D2D total, the
    two bases behind that total, and the destination that took the slot — so
    nothing here is a new claim, only an old one said out loud.

    Built ONCE and returned as plain text, because three renderers print it:
    the compact e-mail, its plain-text twin and the audit page. Each escapes it
    in its own way, so the three cannot word it differently.

    Empty for any row that is not held back, so a caller can ask the question
    instead of checking the destination list.
    """
    if not _raw_field(row, "held_back", False):
        return ""
    place = _place(_row_field(row, "destination_label"))
    flight = _HELD_FLIGHT_WORDS.get(
        _row_field(row, "flight_confidence"), _HELD_FLIGHT_WORDS["benchmark"])
    reason = (
        f"held back: {place} has cards within budget" if place
        else "held back: this destination has cards within budget"
    )
    return " · ".join((
        _row_field(row, "resort_name").strip(),
        _range_words(_row_field(row, "outbound"), _row_field(row, "return"),
                     generated_at=generated_at),
        f"{_gbp(_raw_field(row, 'true_d2d', 0.0))} for {int(travellers)}, "
        "door to door",
        f"priced by {flight} and {_held_stay_words(row)}",
        reason,
    ))


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
    """``All Inclusive · about £378 each`` (+ the other boards, each priced for 5).

    AMEND-H5: the priced basis first, then each other basis with its price, in
    words and never as a code. The other bases are re-based onto the same
    door-to-door arithmetic as the headline, so one number means one thing
    across the whole e-mail: the total for the party.

    The per-head share is printed as ``about``, never as an exact figure. It is
    ``round(total / travellers)``, so on any total that is not a multiple of the
    party size the reader's one multiplication does not come back to the total
    above it — measured on 10 of 15 shipped cards, off by up to £2 a head
    (REVIEW-H6 P1). The same arithmetic the breakdown line already fixed one
    line higher. "about" is the honest word for a rounded share; a share that
    multiplies back exactly would need five different per-head figures on one
    line, which is worse to read than a rounded one clearly marked as rounded.
    """
    priced_basis = hol.BOARD_LABELS.get(board_code(getattr(deal, "board_basis", "")), "")
    words = priced_basis or str(getattr(deal, "board_basis", "") or "")
    total = headline_total(deal)
    try:
        per_person = total / float(travellers or 1)
    except (TypeError, ValueError, ZeroDivisionError):
        per_person = 0.0
    if per_person > 0:
        words += f" · about {_gbp(per_person)} each"
    # A stay derived from a read for another pair says so HERE, on the line that
    # names the board and the per-head share, because this is where a reader
    # looks for what the stay costs (BRIEF-H14 §1). After the board, before the
    # other boards: the clause belongs to this card's stay, not to any row.
    read_dates = tuple(getattr(deal, "hotel_rate_read_dates", ()) or ())
    if len(read_dates) == 2:
        words += (f" · estimate from a read rate for "
                  f"{_range_words(read_dates[0], read_dates[1])}")
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
    for index, (label, cost) in enumerate(others):
        # The qualifier rides the FIRST alternative figure, not the end of the
        # line: at the end it reads as governing `£378 each`, which is already
        # per head, and that is the last position-dependent price in the
        # e-mail (REVIEW-H3 P2).
        qualifier = " (each for 5)" if index == 0 else ""
        words += f" · {label} {_gbp(round(total - stay + cost, 2))}{qualifier}"
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
    """The one line that says where five people actually sleep.

    On a card priced at an operator's package that is the PACKAGE's rooms
    (BRIEF-H14 §3, 2026-10-05): the headline is the operator's booking, so the
    catalogue's unit must not describe it — "Presidential Suite, one unit for 5"
    under a price for two Grand Deluxe rooms is a room nobody would get. When
    the engine priced the card itself the catalogue's unit is the card's unit,
    exactly as before.
    """
    travellers = int(config.travellers)
    rooms_words = hol.package_rooms_words(deal)
    if rooms_words:
        return f"Sleeps {travellers} in one booking — {rooms_words}"
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
    """At most three links, the first of them labelled by what it BOOKS.

    BRIEF-H16 §3 (2026-10-06). The first link used to read "Book this package"
    on every card. On Pullman Lombok Merujani that card is priced from a hotel
    rate read on Accor plus an economy flight estimate — two halves the engine
    priced itself — so "this package" was a description of nothing on the card,
    and a reader who clicked it expected to buy £13,787, which is not what the
    vendor sells.

    What the old link actually pointed at is worth stating, because it decided
    the label: a PACKAGE OPERATOR's own search (loveholidays first, then
    Destination2, Jet2, easyJet). Every one of them sells flights plus a hotel,
    so "Book this package" described the destination correctly and the card
    wrongly. That is why the label, not just the words, has to follow the
    price:

    * an operator package priced the card, so an operator's package search is
      the thing that can buy it — unchanged, and still first;
    * nothing did, so the only booking a link on this card can honestly promise
      is the stay, and it goes to the hotel's OWN site (``hotel_booking_url``)
      — for Pullman Lombok, ``pullman.accor.com``, the very page the rate was
      read from. A package search is not relabelled "the hotel": it is not the
      hotel, and it is not this price.
    """
    links: list[tuple[str, str]] = []
    if bool(getattr(deal, "package_priced", False)):
        try:
            vendor = build_vendor_links(trip_from_deal(deal, adults=int(config.travellers),
                                                       rooms=tuple(config.rooms)))
        except Exception:
            vendor = ()
        if vendor and vendor[0].url:
            links.append(("Book this package", str(vendor[0].url)))
    else:
        hotel_site = str(getattr(deal, "hotel_booking_url", "") or "")
        if hotel_site.startswith(("http://", "https://")):
            links.append(("Book the hotel", hotel_site))
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
        season, hazard = wet_season_words_compact(deal)
        out.append(f"{season} in {name} — {hazard}")
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
    # Sort by the door-to-door total the renderer displays (headline_total =
    # package + transfers + UK ground), NOT the package-only price: a table
    # headed "Total for 5" must read cheapest-first on that total, and the
    # cards must follow the same order. The 7 Oct 2026 December run showed
    # Seaside Palm Beach (£3,002) above Annabelle Hotel (£2,974) because both
    # sorted on 2,933 vs 2,940. A deal with no door-to-door figure falls back
    # to the package price, matching headline_total's own fallback order.
    ordered = sorted(deals, key=lambda d: headline_total(d))
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
            "package": package_words(deal, travellers=travellers),
            "package_html": _package_line_html(deal, travellers=travellers),
            "package_how": _rooms_added_words(getattr(deal, "operator_package", None)),
            "board": board_line(deal, travellers=travellers),
            # BRIEF-H15 §2: the card's own words, built once by the engine and
            # printed here verbatim, so this e-mail and the audit page cannot
            # word the same contradiction differently.
            "caution": str(getattr(deal, "hotel_read_refused", "") or "").strip(),
            "tag": tag,
            "tag_colour": tag_colour,
            "movement": movement_words(trend_by_resort.get(str(deal.resort_name)),
                                       last_report_at=last_report_at),
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
#: board column DOES wrap: five nowrap columns do not fit a 380 px phone, and
#: a clipped "Breakfast" is worse than a wrapped "Bed & Breakfast".
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


def _glance_html(cards: Sequence[Mapping[str, Any]], *, travellers: int) -> str:
    """One table, one row per deal — the whole answer to "what is what"."""
    # Five columns. The sixth, "vs last time", went on 2026-10-08 with the
    # price-change bullets: the owner does not want price movement taking
    # space, and on a phone it wrapped every row to two lines.
    head_cells = ("Resort", "Where", "Dates", "Board", "Total for 5")
    out = [
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" ',
        'style="border-collapse:collapse; margin:12px 0 0 0;">',
        '<tr>',
    ]
    aligns = ("left", "left", "left", "left", "right")
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
    ]
    if card["package"]:
        # The operator's own price for one booking on these dates. It sits under
        # the breakdown because that is where the engine's total is, so the
        # reader can see which of the two is dearer without hunting.
        out.append(
            f'<div style="font-size:12px; color:{_INK}; margin:6px 0 0 0;">'
            f'{card["package_html"]}</div>'
        )
        if card["package_how"]:
            out.append(
                f'<div style="font-size:11px; color:{_MUTED}; margin:2px 0 0 0;">'
                f'{_esc(card["package_how"])}</div>'
            )
    out.extend([
        f'<div style="font-size:13px; color:{_INK}; margin:6px 0 0 0;">{_esc(card["board"])}</div>',
        # Directly under the board line, because that is the figure it qualifies.
        # NOT one of ``warnings``: those are capped at two and ordered by how
        # long they last, and a price that its own evidence contradicts must
        # never be the line that gets cut.
        *(
            [f'<div style="font-size:12px; color:#92400e; margin:4px 0 0 0;">'
             f'⚠ {_esc(card["caution"])}</div>']
            if card["caution"] else []
        ),
        '<div style="font-size:11px; margin:6px 0 0 0;">',
        f'<span style="background:{tag_bg}; color:{tag_fg}; padding:2px 8px; ',
        f'border-radius:9999px;">{_esc(card["tag"])}</span> ',
        f'<span style="color:{_MOVEMENT_COLOURS[movement_colour(str(card["movement"]))]}">',
        _esc(card["movement"]), '</span></div>',
    ])
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


# ---------------------------------------------------------------------------
# Two-centre trips: a shape this engine cannot price, shown honestly
# ---------------------------------------------------------------------------

def two_centre_cabin(config: HolidayConfig) -> str:
    """The cabin a two-centre trip's flight link is built in: always ECONOMY.

    Not a literal, and not derived from any one destination: a two-centre trip
    is two flights and a change, so it is never a nonstop London service and the
    owner quotes Business only for a direct flight (owner rule 2026-10-04,
    "only quote business class for direct flights"). Before this the link was
    built with ``cabin_class="BUSINESS"`` hard-coded, so clicking it searched
    Business fares for a holiday this report quotes in Economy — the reader's
    first search would have contradicted the card above it.

    Derived through the cabin policy so the rule cannot drift from the one the
    cards use: every destination's derived cabin is ECONOMY for a one-stop
    route, and a two-centre trip is one by construction. If a two-centre leg
    were ever sold as a nonstop, this would have to change with the policy
    rather than with a string.
    """
    return _TWO_CENTRE_CABIN


#: The one constant behind :func:`two_centre_cabin`. Held separately so the
#: derivation above is a single named decision rather than a literal buried in
#: a URL builder, and so a test can assert the rule without a config.
_TWO_CENTRE_CABIN = SHORT_HAUL_CABIN


def _multi_centre_rows(config: HolidayConfig) -> list[dict[str, Any]]:
    """This season's two-centre itineraries with the runtime verdict on each.

    The only thing decided here rather than read from the file is whether the
    LOW end of a range fits the configured budget — and that is computed at
    render time, so the stored file never carries an owner's budget and never
    goes stale when it changes.
    """
    try:
        pairs = hol.priceable_date_pairs(config)
    except Exception:  # noqa: BLE001 - a missing section must not break the e-mail
        return []
    if not pairs:
        return []
    outbound, returning = pairs[len(pairs) // 2]
    try:
        trips = load_multi_centre(config)
    except Exception:  # noqa: BLE001 - see above
        return []
    budget = float(getattr(config, "max_budget_gbp", 0.0) or 0.0)
    rows: list[dict[str, Any]] = []
    for trip in trips:
        try:
            legs = trip_legs_for_dates(trip, outbound, returning)
        except ValueError:
            # No usable date pair means no usable link, and a link is the whole
            # reason this section exists. The itinerary is named in the skip log
            # rather than rendered as a dead end.
            continue
        rows.append({
            "trip": trip,
            "outbound": outbound,
            "return": returning,
            "nights": trip.total_nights,
            "low": trip.cost_low_gbp,
            "high": trip.cost_high_gbp,
            "fits": trip.fits(budget),
            "gap": max(trip.cost_low_gbp - budget, 0.0) if budget > 0 else 0.0,
            "cabin": two_centre_cabin(config),
            "url": build_google_flights_legs_url(
                legs, travellers=int(config.travellers),
                cabin_class=two_centre_cabin(config),
            ),
        })
    return rows


def _multi_centre_verdict(row: Mapping[str, Any]) -> str:
    """Whether the low end fits — or, when it does not, by how much it misses.

    The comparison target is named once in the section header, so each row can
    stay three words long.
    """
    if row["fits"] is True:
        return "low end fits"
    if row["fits"] is None:
        return "budget not set, no verdict"
    return f"low end {_gbp(row['gap'])} over"


def _multi_centre_html(config: HolidayConfig) -> str:
    """The compact "Two-centre trips" block; empty when there are none.

    Placed after the cards and before the over-budget list: these are the
    alternatives to a single-centre trip, so they belong next to the cards the
    reader has just read, not buried under the resorts that did not fit.
    """
    rows = _multi_centre_rows(config)
    if not rows:
        return ""
    out = [
        f'<div style="font-size:12px; color:{_MUTED}; margin:14px 0 0 0;">',
        f'<strong style="color:{_INK};">Two-centre trips</strong> — cost RANGES, not '
        'quotes; no dated multi-city fare was readable. Every leg here connects, '
        'so these are Economy flights like the rest of this report. Low end '
        'against the '
        + _gbp(getattr(config, "max_budget_gbp", 0.0)) + ' budget:</div>',
    ]
    for row in rows:
        trip = row["trip"]
        out.append(
            f'<div style="font-size:12px; color:{_MUTED}; padding:6px 0 0 0;">'
            f'<strong style="color:{_INK};">{_esc(trip.title)}</strong> · '
            f'{_gbp(row["low"])}–{_gbp(row["high"])} · '
            f'{_esc(trip.price_label())} · {_esc(_multi_centre_verdict(row))}<br>'
            f'why: {_esc(trip.why)}<br>'
            f'catch: {_esc(trip.catch)} · '
            f'<a href="{_esc(row["url"])}" style="color:{_ACCENT}; '
            f'text-decoration:none; font-weight:600;">flights ↗</a></div>'
        )
    return "".join(out)


def _multi_centre_lines(config: HolidayConfig) -> list[str]:
    """The plain-text twin of ``_multi_centre_html``."""
    rows = _multi_centre_rows(config)
    if not rows:
        return []
    lines = [
        "Two-centre trips — cost RANGES, not quotes; every leg here connects, so "
        "these are Economy flights like the rest of this report. No dated "
        "multi-city fare was readable. Low end against the "
        + _gbp(getattr(config, "max_budget_gbp", 0.0))
        + " budget:"
    ]
    for row in rows:
        trip = row["trip"]
        lines.append(
            f"  {trip.title} · {_gbp(row['low'])}–{_gbp(row['high'])} · "
            f"{trip.price_label()} · {_multi_centre_verdict(row)}"
        )
        lines.append(f"    why: {trip.why}")
        lines.append(f"    catch: {trip.catch}")
        lines.append(f"    flights ({len(trip.legs)} legs): {row['url']}")
    return lines


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
        held = held_back_sentence(row, travellers=int(config.travellers))
        if held:
            # A HELD-BACK RESORT GETS ITS OWN LINE (BRIEF-H16 §1). The line
            # below states a price and a gap; this one states a price, the pair
            # it is for, what priced it and why it is not a card — which is a
            # different set of facts and does not fit beside "£3,994 over".
            lines.append(
                f'<div style="font-size:12px; color:{_MUTED}; padding:2px 0 0 0;">'
                f'{_esc(held)}</div>'
            )
            continue
        try:
            total = float(row.get("true_d2d", 0.0))
        except (TypeError, ValueError):
            total = 0.0
        over = max(total - budget, 0.0)
        note = over_package_html(row, travellers=int(config.travellers))
        note_html = f' <span style="color:{_INK};">{note}</span>' if note else ""
        lines.append(
            f'<div style="font-size:12px; color:{_MUTED}; padding:2px 0 0 0;">'
            f'{_esc(row.get("resort_name", ""))} · {_esc(_place(row.get("destination_label", "")))} · '
            f'{_gbp(total)} for {int(config.travellers)} · {_gbp(over)} over'
            f'{note_html}</div>'
        )
    return "".join(lines)


def _watch_reason(row: Mapping[str, Any]) -> str:
    """Why a watched destination has no price here — never a benchmark figure."""
    if not row.get("in_season"):
        # A destination can say WHY it is watched outside its season: mainland
        # Japan is 17°C in December, so Okinawa's beach is (H9).
        reason = str(row.get("reason", "") or "").strip()
        if reason:
            return "outside its season — " + reason[0].lower() + reason[1:]
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


#: Words that cannot END an English sentence. A filter reason that stops on one
#: of them was cut off mid-clause, and a truncated sentence at the bottom of the
#: e-mail reads as a broken e-mail — three of them shipped that way before the
#: source literals were completed (REVIEW-H3 P1).
#:
#: This is deliberately NOT "must end in a full stop". Thirteen of the fifteen
#: reason shapes ``holidays`` emits are deliberate lower-case fragments with no
#: terminal punctuation ("user exclusion / waterpark-only", "needs 3 rooms —
#: breaks the one-unit rule"), so a full-stop rule would delete the whole Notes
#: section instead of repairing one sentence. A dangling-word rule catches the
#: actual defect and leaves every legitimate fragment alone.
_DANGLING_ENDINGS: frozenset[str] = frozenset({
    "a", "an", "and", "any", "are", "as", "at", "be", "because", "been", "before",
    "being", "below", "between", "but", "by", "during", "each", "every", "for",
    "from", "has", "have", "her", "his", "if", "in", "into", "is", "its", "no",
    "not", "of", "on", "onto", "or", "over", "per", "so", "than", "that", "the",
    "their", "then", "there", "these", "this", "those", "to", "under", "unless",
    "until", "up", "upon", "was", "were", "which", "while", "with", "within",
    "without", "yet", "you", "your",
})


def _note_reason(reason: Any) -> str:
    """One filter reason, clipped to a line — or "" if it must not be printed.

    Two guards, in this order:

    * a reason ending on a word that cannot end a sentence was truncated
      somewhere upstream, and this renderer refuses to reproduce it verbatim
      (the 96-character clip cannot catch it: the damaged literal was 62
      characters, comfortably inside the limit, and carried no ellipsis to
      mark it). The resort is still listed in the DETAILED renderer's strict
      filters block, so the information is not lost — it is just not printed
      here in a form that reads as damage;
    * anything longer than a line is clipped with an explicit ellipsis, so a
      clip can never be mistaken for the end of the sentence either.
    """
    text = str(reason or "").strip()
    if not text:
        return ""
    last = re.split(r"[\s—–:;,/()]+", text)[-1].strip(" .…!?").lower()
    if last in _DANGLING_ENDINGS:
        return ""
    if len(text) > 96:
        text = text[:93].rstrip() + "…"
    return text


def _notes_html(config: HolidayConfig, deals: Sequence[PackageDeal]) -> str:
    """Strict filters and rules that could not be applied — one line each."""
    lines: list[str] = []
    for name, reason in hol.LAST_FILTERED_OUT:
        text = _note_reason(reason)
        if not text:
            continue
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

    There is no "What changed" block: the owner asked on 2026-10-08 for the
    price-change bullets to go ("I don't care about that"), so neither
    ``digest`` nor a pre-rendered ``change_digest_html`` is printed, and
    ``history_chips`` is ignored as before. ``trends``/``last_report_at`` (or
    the digest's ``last_report_at``) only feed the per-card movement words,
    which sit on the freshness-tag line and cost no space. All of them are
    optional, so a caller with only the detailed renderer's arguments still
    gets a valid e-mail.
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
    out.append(_multi_centre_html(config))
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
    if cards:
        lines.append(
            f"At a glance (every price is the total for {int(config.travellers)}, door to door)"
        )
        for index, card in enumerate(cards, start=1):
            lines.append(
                f"  {index}. {card['name']} · {card['place']} · {card['dates']} · "
                f"{str(card['board']).split(' · ')[0]} · {card['headline']}"
            )
        lines.append("")
    for card in cards:
        lines.append(
            f"{card['name']} {card['stars']} · {card['place']} · {card['dates']} · {card['nights']}"
        )
        lines.append(f"  {card['headline']} — {card['headline_words']}")
        if card["breakdown"]:
            lines.append(f"  {card['breakdown']}")
        if card["package"]:
            lines.append(f"  {card['package']}")
            if card["package_how"]:
                lines.append(f"  {card['package_how']}")
        lines.append(f"  {card['board']}")
        if card["caution"]:
            lines.append(f"  ! {card['caution']}")
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
    lines.extend(_multi_centre_lines(config))
    keys = {d.key.lower() for d in config.destinations}
    over = [row for row in hol.LAST_OVER_BUDGET
            if str(row.get("destination_key", "")).lower() in keys]
    if over:
        budget = float(over[0].get("max_budget_gbp", 0.0))
        lines.append(f"Over the {_gbp(budget)} budget — priced, no option fits")
        for row in over:
            held = held_back_sentence(row, travellers=int(config.travellers))
            if held:
                lines.append(f"  {held}")
                continue
            total = float(row.get("true_d2d", 0.0))
            note = over_package_words(row, travellers=int(config.travellers))
            lines.append(
                f"  {row.get('resort_name', '')} · {_place(row.get('destination_label', ''))} · "
                f"{_gbp(total)} for {int(config.travellers)} · "
                f"{_gbp(max(total - budget, 0.0))} over"
                + (f" {note}" if note else "")
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
        text = _note_reason(reason)
        if not text:
            continue
        lines.append(f"{name} — {text}")
    shown = {d.resort_name for d in deals}
    for name in sorted(shown):
        if hol.tripadvisor_unverified(name):
            lines.append(f"{name} — guest rating not checked")
        if not hol.is_summer_trip(config) and hol.pool_heating_unverified(name):
            lines.append(f"{name} — heated pool not stated")
    return lines
