"""One self-contained dossier per multi-stop trip: what it is, where you sleep, how you fly, and what else sells it.

Owner, 22 Oct 2026: "easily understandable and followable but also full verbose details of itineraries, flights,
times stayed, hotel reviews, and deep links to actual bookings etc. and equiv pre-packaged vendor holidays vs mine".

This module builds ONE plain structure per trip (``build_trip_dossiers``) and two renderings of it (``dossier_html``
at three levels of detail, ``dossier_lines`` for the plain-text part), so the HTML and the text cannot disagree about
a date, a figure or a link. Every figure and word comes from a trip row the e-mail already holds:

* the itinerary and the dated stays are ``multi_centre.trip_legs_for_dates`` and ``trip_stays_for_dates`` for the
  report's own date pair, so the day a flight leaves is the day the stay it leaves ends, and the nights the pair adds
  beyond the plan are named instead of absorbed;
* the flight is the private reader's whole-trip read for exactly those legs (carrier, stops, layover and duration of
  the FIRST flight on the card, the read date, the page it was read from), or "not read for these dates yet" with the
  search link. Clock times are shown only if the read carries ``departure_local`` / ``arrival_local``; it does not
  yet, so each dossier says "not captured" once (the data contract below);
* a guest rating is shown only where ``hotel_evidence`` holds one for that exact property, with its source, count and
  read date; everywhere else "guest rating not collected";
* a hotel link is built only for a named property with known nights, and carries exactly the check-in and check-out
  printed beside it, so a test can decode the dates out of the link and compare;
* a package and our build of the same shape (``compare_with``) sit side by side with the pound difference computed
  from the two figures.

DATA CONTRACT for flight details (what the private pricer writes on a priced ``stopover_reads/1`` multi-centre row, and
what this page prints). Older rows carry only the FIRST flight's ``carrier``, ``stops``, ``layovers`` and ``duration``,
and optionally its ``departure_local`` / ``arrival_local`` (``YYYY-MM-DDTHH:MM:SS``, local to each airport); a page built
from one prints those and says, once, that the other flights' times are not captured. Newer rows (dealsearch 509fdbf)
also carry ``flights``: one object per leg in date order,
``{origin, destination, departure_local, arrival_local, carrier, stops, duration, layover, cabin, vendor}``
(for example ``"duration": "14h 30m"``, ``"layover": "1h 40m AUH"``), plus the row's ``cabin`` (``ECONOMY`` |
``BUSINESS`` | ``MIXED``) and, when MIXED, ``cabin_mix`` ("Business LHR-JRO, ZNZ-LHR + Economy JRO-ZNZ"). When ``flights`` is
present each flight is matched to its dated leg by airports (and the departure date where two legs share airports; the
list's order is not trusted and nothing is matched by position) and printed on that leg's line with its own times,
carrier, stops, layover, duration and cabin; a leg with no matching flight, or a flight that states no clock time, says
"times not captured for this flight" for itself alone, and nothing says the other flights' times are missing. A field a
flight does not state is not printed: an arrival that is absent is never replaced by a guess.
"""

from __future__ import annotations

from datetime import datetime
from html import escape
import re
from typing import Any, Mapping, Optional, Sequence
from urllib.parse import urlparse

from . import holidays as hol
from .hotel_evidence import normalise_property_name
from .multi_centre import MultiCentreTrip, counterparts, trip_legs_for_dates, trip_stays_for_dates

#: Levels of detail, most detail first. Level 0 is the whole dossier; level 1 drops the longest prose and the
#: second-choice links; level 2 is a stub that keeps the price, the flights status and the links. The e-mail asks
#: for a lower level for the LAST dossiers first when it is near Gmail's size limit.
FULL, TRIMMED, SHORT = 0, 1, 2

#: What the e-mail says in the place of what it left out; the text part is always full.
SHORTENED_WORDS = "Shortened to fit Gmail's size limit: the booking links and the rest are in the plain-text version."
TRIMMED_WORDS = "Shortened to fit Gmail's size limit: the longest notes are in the plain-text version."

NO_PACKAGE_WORDS = "no equivalent vendor package found yet"
NO_CARD_PACKAGE_WORDS = "no vendor package read for these dates"
NO_BUILD_WORDS = "no self-build of this shape yet"
NO_RATING_WORDS = "guest rating not collected"
NO_PROPERTY_WORDS = "no property chosen yet, so no booking link"
NO_NIGHTS_WORDS = "nights per property not stated"
NO_TIMES_WORDS = "Departure and arrival times not captured for these flights."
FIRST_TIMES_WORDS = "Times shown are for the first flight only; the other flights' times are not captured."
NO_LEG_TIMES_WORDS = "times not captured for this flight"
TIMES_ARE_LOCAL_WORDS = "All clock times are local to each airport."

#: Airports the trip data names, in plain words. An airport not listed prints as its code: a name is never guessed.
AIRPORT_PLACES: dict[str, str] = {
    "LHR": "London", "LGW": "London Gatwick", "JRO": "Kilimanjaro", "ZNZ": "Zanzibar", "NBO": "Nairobi",
    "JNB": "Johannesburg", "CPT": "Cape Town", "MRU": "Mauritius", "DAR": "Dar es Salaam", "DPS": "Bali",
    "LOP": "Lombok", "DAD": "Da Nang", "HND": "Tokyo", "OKA": "Okinawa", "MCT": "Muscat", "AUH": "Abu Dhabi",
    "DXB": "Dubai", "HKT": "Phuket", "BKK": "Bangkok", "USM": "Koh Samui", "MQP": "Kruger", "HDS": "Hoedspruit",
}

_MONTH_ABBR = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_DAY_ABBR = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_CARRIER_RUNTOGETHER = re.compile(r"(?<=[a-z])(?=[A-Z][a-z])")

#: Where a trip is grouped, in the order the owner reads them. The group's label is the heading over its dossiers.
AFRICA_GROUP = "Africa safari + beach, multi-stop"
OTHER_GROUP = "Two-centre trips"
_TANZANIA_FOCUS_RE = re.compile(r"Serengeti|Tanzania|Ngorongoro|Nyerere|Sayari", re.I)

_ROOMS_FOR_HOTEL_SEARCH = 2  # owner rule: a 2-bedroom unit or 2 rooms, never 3


def _he():
    """``holiday_email``, imported late: it imports this module, so a top-level import would be circular."""
    from . import holiday_email

    return holiday_email


# ---------------------------------------------------------------------------
# Small words
# ---------------------------------------------------------------------------

def _date(iso: str) -> Optional[datetime]:
    try:
        return datetime.strptime(str(iso)[:10], "%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def day_words(iso: str) -> str:
    """``27 Jun``: a date a reader can say; the stamp itself when it will not parse."""
    parsed = _date(iso)
    return f"{parsed.day} {_MONTH_ABBR[parsed.month - 1]}" if parsed else str(iso or "")


def weekday_words(iso: str) -> str:
    """``Sun 27 Jun``."""
    parsed = _date(iso)
    return f"{_DAY_ABBR[parsed.weekday()]} {parsed.day} {_MONTH_ABBR[parsed.month - 1]}" if parsed else str(iso or "")


def window_words(check_in: str, check_out: str) -> str:
    return f"{day_words(check_in)} → {day_words(check_out)}"


def nights_phrase(count: int) -> str:
    return f"{int(count)} night{'s' if int(count) != 1 else ''}"


def place_words(code: str) -> str:
    code = str(code or "").strip().upper()
    name = AIRPORT_PLACES.get(code)
    if name is None:
        return code
    return name if code in ("LHR", "LGW") else f"{name} ({code})"


def carriers_words(raw: Any) -> str:
    """``Kenya Airways + Virgin Atlantic`` out of the parser's ``Kenya AirwaysVirgin Atlantic``.

    The card's text runs two airlines' names together, and the private reader's own parser
    splits them the same way (a lower-case letter directly followed by a Capital and a lower-case letter, in a name
    that already has a space). A name with no space is left as it is.
    """
    text = str(raw or "").strip()
    if not text:
        return ""
    if " " not in text:
        return text
    return " + ".join(part.strip() for part in _CARRIER_RUNTOGETHER.split(text) if part.strip())


def stops_words(stops: Any) -> str:
    try:
        count = int(stops)
    except (TypeError, ValueError):
        return ""
    if count < 0:
        return ""
    return "nonstop" if count == 0 else f"{count} stop{'s' if count != 1 else ''}"


def _clock(stamp: Any) -> tuple[str, str]:
    """``("21:40", "27 Jun")`` out of a local ISO stamp, or ``("", "")``."""
    try:
        parsed = datetime.fromisoformat(str(stamp).strip())
    except (TypeError, ValueError):
        return "", ""
    return parsed.strftime("%H:%M"), f"{parsed.day} {_MONTH_ABBR[parsed.month - 1]}"


def _host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _tfs(url: str) -> str:
    """The encoded itinerary of a Google Flights link (its ``tfs`` parameter), or ``""``."""
    from urllib.parse import parse_qs

    try:
        return parse_qs(urlparse(str(url)).query).get("tfs", [""])[0]
    except ValueError:
        return ""


def _http(url: Any) -> str:
    text = str(url or "").strip()
    return text if text.startswith(("http://", "https://")) else ""


# ---------------------------------------------------------------------------
# The owner's order
# ---------------------------------------------------------------------------

def owner_order(rows: Sequence[Mapping[str, Any]]) -> list[tuple[str, str, list[Mapping[str, Any]]]]:
    """``[(key, label, rows)]`` in the order the owner reads them: Tanzania safari + Zanzibar first.

    Africa first (the Tanzania safari + Zanzibar trips, then the rest, cheapest low end first within each), then the
    Asian two-centre trips cheapest first. One definition, because the summary table, the dossiers and the plain text
    must list the same trips in the same order.
    """
    africa = [r for r in rows if getattr(r["trip"], "region", "") == "africa"]
    other = [r for r in rows if getattr(r["trip"], "region", "") != "africa"]

    def low(row: Mapping[str, Any]) -> float:
        try:
            return float(row.get("low") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def focus_first(row: Mapping[str, Any]) -> tuple[int, float]:
        title = str(getattr(row["trip"], "title", ""))
        focus = bool(_TANZANIA_FOCUS_RE.search(title)) and "zanzibar" in title.lower()
        return (0 if focus else 1, low(row))

    groups: list[tuple[str, str, list[Mapping[str, Any]]]] = []
    if africa:
        groups.append(("africa", AFRICA_GROUP, sorted(africa, key=focus_first)))
    if other:
        groups.append(("other", OTHER_GROUP, sorted(other, key=low)))
    return groups


def is_tanzania_focus(trip: Any) -> bool:
    title = str(getattr(trip, "title", ""))
    return bool(_TANZANIA_FOCUS_RE.search(title)) and "zanzibar" in title.lower()


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------

def hotel_links(name: str, area: str, check_in: str, check_out: str, *, travellers: int,
                page: str = "") -> list[tuple[str, str]]:
    """The searches that open THIS property for THESE dates, then the page we hold for it, if any.

    Built with the same builders the resort cards use, so a link on a trip and a link on a card are the same kind of
    link: Booking.com's search keyed on the property name with the exact dates and party, and the Google Hotels card
    for the property with every vendor's dated price. Without both dates there is no dated link at all; the page we
    hold for the property (``page``) is still offered, labelled by what it is.
    """
    out: list[tuple[str, str]] = []
    if check_in and check_out:
        kwargs = dict(resort_name=name, destination_key=area, departure_date=check_in, return_date=check_out,
                      adults=int(travellers), rooms=_ROOMS_FOR_HOTEL_SEARCH)
        out.append(("Booking.com", hol.build_booking_com_property_url(**kwargs)))
        out.append(("Google Hotels", hol.build_google_hotels_property_url(**kwargs)))
    if _http(page):
        out.append(("Source page", _http(page)))
    return out


def rating_entries(ratings: Sequence[Any]) -> list[dict[str, str]]:
    """Each guest rating a property holds, as words, count, read date and the page it came from."""
    out: list[dict[str, str]] = []
    for rating in ratings or ():
        try:
            score = float(getattr(rating, "score"))
            scale = float(getattr(rating, "scale", 5) or 5)
        except (TypeError, ValueError):
            continue
        words = f"{str(getattr(rating, 'source', '') or 'Guests').strip()} {score:g}/{scale:g}"
        count = str(getattr(rating, "review_count", "") or "").strip()
        if count:
            words += f" ({count} reviews)"
        read = day_words(str(getattr(rating, "observed_at", "") or "")[:10]) if getattr(rating, "observed_at", "") else ""
        if read:
            words += f", read {read}"
        out.append({"words": words, "url": _http(getattr(rating, "source_url", ""))})
    return out


# ---------------------------------------------------------------------------
# The structure
# ---------------------------------------------------------------------------

def _flight_facts(item: Mapping[str, Any]) -> dict[str, str]:
    """One flight of the read's ``flights`` list as words, from only the fields it states.

    Nothing is derived: a flight with no arrival prints no arrival, a stop count that is not a number prints no stops,
    and a time that does not parse prints no time.
    """
    dep_time, dep_day = _clock(item.get("departure_local"))
    arr_time, arr_day = _clock(item.get("arrival_local"))
    stop_text = stops_words(item.get("stops"))
    layover = str(item.get("layover") or item.get("layovers") or "").strip()
    route = (f"{stop_text} ({layover})" if layover and stop_text and stop_text != "nonstop" else stop_text)
    cabin = str(item.get("cabin") or "").strip()
    return {
        "departs": dep_time,
        # the arrival's date is printed only when it is not the day of departure (an overnight flight)
        "arrives": (arr_time if not arr_time or arr_day == dep_day else f"{arr_day} {arr_time}"),
        "carrier": carriers_words(item.get("carrier")),
        "route": route,
        "duration": str(item.get("duration") or "").strip(),
        "cabin": cabin.capitalize() if cabin else "",
        "vendor": str(item.get("vendor") or "").strip(),
    }


def leg_flight_words(facts: Optional[Mapping[str, str]]) -> str:
    """One flight on one line: ``departs 09:30 · arrives 28 Jun 02:00 · Etihad Airways · 1 stop (...) · 14h 30m · Business``.

    ``None`` (no flight in the read matched this leg) and a flight that states no clock time both say, for THIS
    flight only, that its times are not captured; they never borrow another flight's times.
    """
    if facts is None:
        return NO_LEG_TIMES_WORDS
    parts = []
    if facts["departs"]:
        parts.append(f"departs {facts['departs']}")
    if facts["arrives"]:
        parts.append(f"arrives {facts['arrives']}")
    parts += [facts[k] for k in ("carrier", "route", "duration", "cabin") if facts[k]]
    if not (facts["departs"] or facts["arrives"]):
        parts.append(NO_LEG_TIMES_WORDS)
    return " · ".join(parts)


def _match_flights(legs: Sequence[tuple[str, str, str]], flights: Any) -> list[dict[str, Any]]:
    """Each dated leg with the flight of the read's ``flights`` list that is ITS flight, or ``None``.

    A flight belongs to the leg whose airports it names; where two legs share airports the departure date decides.
    The list's order is not trusted and nothing is matched by position, so a list that is short, shuffled or partly
    junk can only leave a leg without a flight, never give it somebody else's.
    """
    clean = [item for item in flights if isinstance(item, dict)] if isinstance(flights, (list, tuple)) else []
    used: set[int] = set()
    out: list[dict[str, Any]] = []
    for origin, destination, day in legs:
        picked: Optional[int] = None
        for need_date in (True, False):
            for index, item in enumerate(clean):
                if index in used:
                    continue
                if (str(item.get("origin", "")).strip().upper() != origin
                        or str(item.get("destination", "")).strip().upper() != destination):
                    continue
                if need_date and str(item.get("departure_local", ""))[:10] != day:
                    continue
                picked = index
                break
            if picked is not None:
                break
        if picked is not None:
            used.add(picked)
        out.append({"leg": (origin, destination, day),
                    "flight": _flight_facts(clean[picked]) if picked is not None else None})
    return out


def _flight_block(row: Mapping[str, Any]) -> dict[str, Any]:
    he = _he()
    trip: MultiCentreTrip = row["trip"]
    read = row.get("read") or None
    legs = [(o, d, day) for o, d, day in row["legs"]]
    flights_line = next(((line.gbp, line.basis) for line in trip.cost_lines if "flight" in line.label.lower()), None)
    block: dict[str, Any] = {
        "price_uses": ("" if read or flights_line is None else
                       f"The price above includes {he._gbp(flights_line[0])} for flights"
                       + (f" ({flights_line[1]})" if flights_line[1] else "") + "."),
        "status": "read" if read else "unread",
        "legs": [(place_words(o), place_words(d), day) for o, d, day in legs],
        "search_url": row["url"],
        "shape": trip.flight_shape,
        "cabin": str(row.get("cabin") or "ECONOMY").strip().capitalize() if str(row.get("cabin") or "ECONOMY") != "ECONOMY" else "Economy",
        "read_line": "", "read_url": "", "first_flight": "", "times": "", "times_note": NO_TIMES_WORDS,
        "same_search": False,
        "has_flights": False, "leg_flights": [{"leg": leg, "flight": None} for leg in legs],
        "vendor": "", "search_cabin_note": "", "options": [],
    }
    if not read:
        return block
    block.update(_read_block(row, read, legs, cabin_default=block["cabin"]))
    # Both products (23 Oct 2026): one option per cabin that was read, the Business-long-haul one first. Each carries its
    # own price, date, vendor, cabin words and, where the read has them, every flight; ``options`` is what the page
    # prints when there are two, and the top-level fields above stay the primary read's, so one-read pages are unchanged.
    options = []
    for key in ("business", "economy"):
        option_read = (row.get("reads") or {}).get(key)
        if option_read:
            options.append({"key": key, "label": _he().cabin_label(key, option_read), "read": option_read,
                            **_read_block(row, option_read, legs, cabin_default=block["cabin"])})
    block["options"] = options
    return block


def _read_block(row: Mapping[str, Any], read: Mapping[str, Any], legs: Sequence[tuple[str, str, str]], *,
                cabin_default: str) -> dict[str, Any]:
    """What ONE read says: its price line, page, first flight, times and (when it has them) every flight."""
    he = _he()
    block: dict[str, Any] = {
        "read_line": "", "read_url": "", "first_flight": "", "times": "", "times_note": NO_TIMES_WORDS,
        "same_search": False, "has_flights": False,
        "leg_flights": [{"leg": leg, "flight": None} for leg in legs], "vendor": "", "search_cabin_note": "",
    }
    party = he._read_party(read)
    # What the read's price is made of: a mixed read names which legs are in which cabin, never "Economy".
    read_cabin = str(read.get("cabin") or "").strip().upper()
    if read_cabin == "MIXED":
        cabin_words = str(read.get("cabin_mix") or "").strip() or "mixed cabins"
    elif read_cabin:
        cabin_words = read_cabin.capitalize()
    else:
        cabin_words = cabin_default
    block["read_line"] = (f"{he._gbp(read.get('total_gbp'))} for {party}, the whole trip, {cabin_words}, "
                          f"read {he._read_day_words(read.get('observed_at'))} for these exact dates")
    block["read_url"] = _http(read.get("source_url")) or row["url"]
    # The read's page IS the search when it carries the same legs (the private reader builds it with the same
    # encoder): then one link serves both, and the dossier does not repeat it under Links.
    block["same_search"] = _tfs(block["read_url"]) == _tfs(row["url"]) and bool(_tfs(row["url"]))
    parts = [carriers_words(read.get("carrier"))]
    stop_text = stops_words(read.get("stops"))
    layover = str(read.get("layovers") or "").strip()
    if stop_text:
        parts.append(f"{stop_text} ({layover})" if layover and stop_text != "nonstop" else stop_text)
    duration = str(read.get("duration") or "").strip()
    if duration:
        parts.append(duration)
    block["first_flight"] = " · ".join(p for p in parts if p)
    dep_time, dep_day = _clock(read.get("departure_local"))
    arr_time, arr_day = _clock(read.get("arrival_local"))
    if dep_time and arr_time:
        block["times"] = f"departs {dep_time} on {dep_day}, arrives {arr_time} on {arr_day} (local times)"
        block["times_note"] = FIRST_TIMES_WORDS
    # A read in a cabin other than Economy was not made on the Economy search this page links.
    if read_cabin and read_cabin != "ECONOMY":
        block["search_cabin_note"] = "The flights search link opens Economy, not the cabin this price was read in."
    # The newer rows carry every flight, in date order. When they do, each leg prints its own flight and the
    # first-flight shortcut (and its "other flights are not captured") is not used: nothing is missing to say.
    if isinstance(read.get("flights"), (list, tuple)) and read.get("flights"):
        block["has_flights"] = True
        block["leg_flights"] = _match_flights(legs, read.get("flights"))
        block["first_flight"], block["times"], block["times_note"] = "", "", ""
        vendors = []
        for lf in block["leg_flights"]:
            vendor = (lf["flight"] or {}).get("vendor", "")
            if vendor and vendor not in vendors:
                vendors.append(vendor)
        block["vendor"] = ", ".join(vendors)
    if not block["vendor"] and str(read.get("vendor") or "").strip():
        block["vendor"] = str(read.get("vendor")).strip()
    block["cabin_words"] = cabin_words
    return block


def _step_sequence(row: Mapping[str, Any], plan, details: Optional[Mapping[tuple, str]] = None) -> list[dict[str, Any]]:
    """The itinerary in order: each flight (slim) and each stay, from the legs and the dated stays.

    A flight is shown after the stay whose airport it leaves from; a change of plane (a leg that starts where the last
    one ended) follows it on the same day. The flight home is always last.
    """
    legs = [(o, d, day) for o, d, day in row["legs"]]
    steps: list[dict[str, Any]] = []
    used = 0

    def emit(leg: tuple[str, str, str]) -> None:
        steps.append({"type": "flight", "when": weekday_words(leg[2]),
                      "text": f"Fly {place_words(leg[0])} → {place_words(leg[1])}", "iso": leg[2],
                      "detail": (details or {}).get(tuple(leg), "")})

    def follow(from_airport: str, until: str, *, include_last: bool) -> None:
        nonlocal used
        current = from_airport
        while used < len(legs) - (0 if include_last else 1) and legs[used][0] == current:
            emit(legs[used])
            current = legs[used][1]
            used += 1
            if current == until:
                break

    first_airport = legs[0][0]
    first_stop = plan.stays[0].stop.airport if plan.stays else ""
    follow(first_airport, first_stop, include_last=False)
    for index, stay in enumerate(plan.stays):
        steps.append({"type": "stay", "stay": stay})
        nxt = plan.stays[index + 1].stop.airport if index + 1 < len(plan.stays) else ""
        follow(stay.stop.airport, nxt, include_last=index + 1 == len(plan.stays))
    while used < len(legs):
        emit(legs[used])
        used += 1
    return steps


def _lodge_block(lodge_stay, stop, *, travellers: int, ratings_by_name: Mapping[str, Sequence[Any]]) -> dict[str, Any]:
    lodge = lodge_stay.lodge
    dated = bool(lodge_stay.check_in and lodge_stay.check_out)
    area = lodge.area or str(stop.place).split("(")[0].split(",")[0].strip()
    held = ratings_by_name.get(normalise_property_name(lodge.name), ()) if ratings_by_name else ()
    return {
        "name": lodge.name,
        "check_in": lodge_stay.check_in,
        "check_out": lodge_stay.check_out,
        "nights": lodge_stay.nights,
        "window": (f"{window_words(lodge_stay.check_in, lodge_stay.check_out)} · {nights_phrase(lodge_stay.nights or 0)}"
                   if dated else NO_NIGHTS_WORDS),
        "board": lodge.board or "board not stated",
        "note": lodge.note,
        "ratings": rating_entries(held),
        "links": hotel_links(lodge.name, area, lodge_stay.check_in, lodge_stay.check_out,
                             travellers=travellers, page=lodge.url),
    }


def _stay_block(stay, *, travellers: int, ratings_by_name: Mapping[str, Sequence[Any]]) -> dict[str, Any]:
    stop = stay.stop
    return {
        "place": stop.place,
        "check_in": stay.check_in,
        "check_out": stay.check_out,
        "nights": stay.nights,
        "window": window_words(stay.check_in, stay.check_out),
        "cut": stay.nights < stop.nights,
        "lodges": [_lodge_block(ls, stop, travellers=travellers, ratings_by_name=ratings_by_name)
                   for ls in stay.lodges],
        # The source's own words about the rooms and board, shown only when no property is named for the stop.
        "hotel_text": "" if stay.lodges else stop.hotel,
        "basis": stop.basis,
    }


def _shape_words(trip: MultiCentreTrip) -> str:
    """``4 nights Arusha + Tarangire safari (Mount Meru Hotel, Kirurumu Tarangire Lodge) + 5 nights Zanzibar ...``"""
    parts = []
    for stop in trip.stops:
        place = stop.place.split(" (")[0].strip()
        named = ", ".join(lodge.name for lodge in stop.lodges)
        parts.append(f"{nights_phrase(stop.nights)} {place}" + (f" ({named})" if named else ""))
    return " + ".join(parts)


def _flights_words(trip: MultiCentreTrip, row: Mapping[str, Any]) -> str:
    """What a side of a pair says about its flights, in a few words and from its own data.

    An operator package states whether flights are in its price (every one shipped says so in its reference).
    A self-build names its flights line when the price is itemised, and otherwise the read for its own dates,
    if there is one.
    """
    he = _he()
    if trip.kind == "operator":
        text = trip.operator_ref.lower()
        return "included in the price" if "flight" in text else "not stated"
    for line in trip.cost_lines:
        if "flight" in line.label.lower():
            return f"{he._gbp(line.gbp)} in the price, {line.basis}" if line.basis else f"{he._gbp(line.gbp)} in the price"
    read = row.get("read")
    if read:
        return f"{he._gbp(read.get('total_gbp'))} read {he._read_day_words(read.get('observed_at'))}"
    return "not itemised"


def _side(row: Mapping[str, Any], *, kind_label: str) -> dict[str, Any]:
    he = _he()
    trip: MultiCentreTrip = row["trip"]
    nights = max(1, trip.total_nights)
    return {
        "id": trip.id, "anchor": f"trip-{trip.id}", "title": trip.title, "kind_label": kind_label,
        "price_words": he._multi_centre_price_words(row["low"], row["high"]),
        "low": float(row["low"]), "high": float(row["high"]),
        "nights": trip.total_nights,
        "per_night": f"{he._gbp(float(row['low']) / nights)} a night",
        "shape": _shape_words(trip),
        "operator_ref": trip.operator_ref,
        "price_label": trip.price_label(),
        "lines": [(line.label, line.gbp, line.basis) for line in trip.cost_lines],
        "basis": trip.cost_basis,
        "catch": trip.catch,
        "flight_shape": trip.flight_shape,
        "read": bool(row.get("read")),
        "flights_words": _flights_words(trip, row),
    }


def _pair_block(row: Mapping[str, Any], other_row: Mapping[str, Any], *, first: bool) -> dict[str, Any]:
    """A vendor package and our build of the same shape, side by side, with the difference worked out."""
    he = _he()
    mine, theirs = row["trip"], other_row["trip"]
    package_row, build_row = (row, other_row) if mine.kind == "operator" else (other_row, row)
    package = _side(package_row, kind_label="Operator package")
    ours = _side(build_row, kind_label="Our build")
    gap = round(ours["low"]) - round(package["low"])
    if gap > 0:
        headline = f"Our build comes to {he._gbp(gap)} more than the package (low ends: {he._gbp(ours['low'])} against {he._gbp(package['low'])})."
    elif gap < 0:
        headline = f"Our build comes to {he._gbp(-gap)} less than the package (low ends: {he._gbp(ours['low'])} against {he._gbp(package['low'])})."
    else:
        headline = f"Our build and the package have the same low end ({he._gbp(ours['low'])})."
    lines = [headline]
    if package["high"] > package["low"]:
        if ours["low"] < package["low"]:
            lines.append(f"The package's range is {package['price_words']}; ours is below all of it.")
        elif ours["low"] <= package["high"]:
            lines.append(f"The package's range is {package['price_words']}; ours falls inside it.")
        else:
            lines.append(f"The package's range is {package['price_words']}; ours is above all of it.")
    delta = ours["nights"] - package["nights"]
    if delta:
        lines.append(f"Ours is {nights_phrase(abs(delta))} {'longer' if delta > 0 else 'shorter'} "
                     f"({ours['nights']} against {package['nights']}), "
                     f"so a night costs about {ours['per_night'].replace(' a night', '')} with ours against "
                     f"{package['per_night'].replace(' a night', '')} with the package (low end divided by nights).")
    else:
        lines.append(f"Both are {nights_phrase(ours['nights'])}: a night costs about "
                     f"{ours['per_night'].replace(' a night', '')} with ours against "
                     f"{package['per_night'].replace(' a night', '')} with the package.")
    return {"package": package, "ours": ours, "difference": lines,
            "other_id": theirs.id, "other_anchor": f"trip-{theirs.id}", "other_title": theirs.title,
            "first": first}


def build_trip_dossiers(config: Any, rows: Sequence[Mapping[str, Any]], *, generated_at: Any,
                        hotel_ratings: Optional[Mapping[str, Sequence[Any]]] = None) -> list[dict[str, Any]]:
    """One structure per trip, in the owner's order (Tanzania safari + Zanzibar first).

    ``rows`` are ``holiday_email._multi_centre_rows``; ``hotel_ratings`` maps a normalised property name to the
    ratings ``hotel_evidence`` holds for it (``hotel_evidence.ratings_index()``), and ``None`` is exactly "none
    collected": a lodge is then said to be unrated, never rated from memory.
    """
    he = _he()
    travellers = int(getattr(config, "travellers", 5))
    budget = float(getattr(config, "max_budget_gbp", 0.0) or 0.0)
    trips = [row["trip"] for row in rows]
    pairs = counterparts(trips)
    by_id = {row["trip"].id: row for row in rows}
    ratings_by_name = dict(hotel_ratings or {})
    dossiers: list[dict[str, Any]] = []
    order_index = {r["trip"].id: i for i, r in enumerate(
        row for _k, _l, grp in owner_order(rows) for row in grp)}
    for group_key, group_label, group_rows in owner_order(rows):
        for row in group_rows:
            trip: MultiCentreTrip = row["trip"]
            try:
                plan = trip_stays_for_dates(trip, row["outbound"], row["return"])
            except ValueError:
                continue
            flight = _flight_block(row)
            # With ONE read each flight is printed on its leg's Itinerary line; with two products the Flights section
            # carries both sets, so the Itinerary stays the plan and does not pick one of them.
            details = ({tuple(lf["leg"]): leg_flight_words(lf["flight"]) for lf in flight["leg_flights"]}
                       if flight["has_flights"] and len(flight["options"]) < 2 else {})
            steps = []
            for step in _step_sequence(row, plan, details):
                if step["type"] == "stay":
                    steps.append({"type": "stay", **_stay_block(step["stay"], travellers=travellers,
                                                               ratings_by_name=ratings_by_name)})
                else:
                    steps.append(step)
            other_rows = [by_id[t.id] for t in pairs.get(trip.id, []) if t.id in by_id]
            pair = _pair_block(row, other_rows[0], first=order_index[trip.id] < order_index[other_rows[0]["trip"].id]) if other_rows else None
            if plan.unplanned_nights:
                plan_note = (f"The plan ends {day_words(plan.plan_end)} and your flight home is "
                             f"{day_words(plan.return_date)}: {nights_phrase(plan.unplanned_nights)} "
                             f"({window_words(plan.plan_end, plan.return_date)}) are not planned or priced here.")
            elif plan.cut_nights:
                plan_note = (f"This plan is {nights_phrase(plan.cut_nights)} longer than the dates, so the last stay "
                             f"is cut at the flight home on {day_words(plan.return_date)}.")
            else:
                plan_note = ""
            source_links: list[tuple[str, str]] = []
            lodge_pages = {lodge.url for stop in trip.stops for lodge in stop.lodges if lodge.url}
            for url in trip.source_urls:
                if _http(url) and url not in lodge_pages:
                    label = "Operator's page" if trip.kind == "operator" else f"Rates: {_host(url)}"
                    source_links.append((label, url))
            dossiers.append({
                "id": trip.id,
                "anchor": f"trip-{trip.id}",
                "group": group_key,
                "group_label": group_label,
                "trip": trip,
                "title": trip.title,
                "kind_label": he._multi_centre_kind_label(trip),
                "nights": trip.total_nights,
                "price_words": he._multi_centre_price_words(row["low"], row["high"]),
                "price_label": trip.price_label(),
                "verdict": he._multi_centre_verdict(row),
                "fits": row["fits"],
                "budget": budget,
                "operator_ref": trip.operator_ref,
                "warnings": list(row.get("warnings") or ()),
                "steps": steps,
                "stays": [s for s in steps if s["type"] == "stay"],
                "has_lodges": any(lodge for s in steps if s["type"] == "stay" for lodge in s["lodges"]),
                "any_rated": any(lodge["ratings"] for s in steps if s["type"] == "stay" for lodge in s["lodges"]),
                "plan_note": plan_note,
                "flight": flight,
                "cabin_totals": list(row.get("cabin_totals") or ()),
                "cabin_missing": list(row.get("cabin_missing") or ()),
                "bundled_flights": bool(flight["options"]) and not row.get("cabin_totals"),
                "pair": pair,
                "no_pair_words": (NO_BUILD_WORDS if trip.kind == "operator" else NO_PACKAGE_WORDS),
                "lines": [(line.label, line.gbp, line.basis) for line in trip.cost_lines],
                "cost_basis": trip.cost_basis,
                "why": trip.why,
                "catch": trip.catch,
                "links": source_links,
                "search_url": row["url"],
                "read": bool(row.get("read")),
            })
    return dossiers


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------
#
# SIZE. Gmail clips an HTML part near 102 KB, and a dossier's text is a fraction of its bytes: the first version spent
# three quarters of every dossier on tags and style attributes. So the markup is deliberately plain: the card's
# <td> sets the font size and colour once, lines inside a block break with <br> instead of opening a <div> each, a
# muted line is one <span>, and the itinerary is divs with a left rule rather than a table of cells.

def _palette() -> tuple[str, str, str, str]:
    he = _he()
    return he._INK, he._MUTED, he._ACCENT, he._LINE


_RAIL = "#cbd5e1"  # the timeline rule: the muted slate, one step darker than a hairline


def _k(text_html: str) -> str:
    """Key text: ink, one size up, bold. The card's own default is muted 11 px, so this is the exception."""
    return f'<b style="color:{_palette()[0]};font-size:12px">{text_html}</b>'


def _a(url: str, label: str, *, bold: bool = False, arrow: bool = True) -> str:
    accent = _palette()[2]
    return (f'<a href="{escape(url, quote=True)}" style="color:{accent};text-decoration:none'
            f'{";font-weight:600" if bold else ""}">{escape(label)}{" ↗" if arrow else ""}</a>')


def _heading(text: str) -> str:
    accent = _palette()[2]
    return (f'<div style="font-weight:700;color:{accent};text-transform:uppercase;'
            f'margin:11px 0 2px">{escape(text)}</div>')


def _links_html(links: Sequence[tuple[str, str]]) -> str:
    return " · ".join(_a(url, label, bold=True) for label, url in links)


def _lodge_html(lodge: Mapping[str, Any], level: int, *, say_unrated: bool) -> str:
    note = f' · {escape(lodge["note"])}' if lodge["note"] and level == FULL else ""
    parts = [f'<div class="lodge" style="margin:5px 0 0 0">{_k(escape(lodge["name"]))} · {escape(lodge["window"])}'
             f'<br>{escape(lodge["board"])}{note}']
    ratings = lodge["ratings"][:1] if level != FULL else lodge["ratings"][:2]
    if ratings:
        bits = [_a(r["url"], r["words"]) if r["url"] else escape(r["words"]) for r in ratings]
        parts.append("<br>Reviews: " + " · ".join(bits))
    elif say_unrated:
        parts.append(f"<br>Reviews: {NO_RATING_WORDS}")
    links = lodge["links"] if level == FULL else [lk for lk in lodge["links"] if lk[0] != "Google Hotels"]
    if links:
        parts.append("<br>" + _links_html(links))
    elif lodge["check_in"] == "":
        parts.append("<br>no dated booking link: the nights at this property are not stated")
    parts.append("</div>")
    return "".join(parts)


def _stay_html(stay: Mapping[str, Any], level: int, *, show_basis: bool, say_unrated: bool) -> str:
    out = [f'<div style="border-left:3px solid {_RAIL};padding:2px 0 3px 8px;margin:3px 0">'
           f'{_k(escape(stay["window"]) + " · " + escape(nights_phrase(stay["nights"])))} · {escape(stay["place"])}']
    if stay["cut"]:
        out.append("<br>cut at the flight home")
    if stay["lodges"]:
        out.extend(_lodge_html(lodge, level, say_unrated=say_unrated) for lodge in stay["lodges"])
    else:
        if level == FULL and stay["hotel_text"]:
            out.append("<br>" + escape(stay["hotel_text"]))
        out.append("<br>" + NO_PROPERTY_WORDS)
    if level == FULL and show_basis and stay["basis"]:
        out.append(f'<div style="margin:3px 0 0 0">Basis: {escape(stay["basis"])}</div>')
    out.append("</div>")
    return "".join(out)


def _short_stop_line(stay: Mapping[str, Any]) -> str:
    """One stay on one line, for the short form: the dates, the nights, the place and the properties by name."""
    names = ", ".join(lodge["name"] for lodge in stay["lodges"])
    return (f'{_k(escape(stay["window"]) + " · " + escape(nights_phrase(stay["nights"])))} · '
            f'{escape(stay["place"])}' + (f" ({escape(names)})" if names else ""))


def _itinerary_html(d: Mapping[str, Any], level: int) -> str:
    out = [_heading("Itinerary")]
    # Where no property on the trip has a guest rating (the usual state of a safari lodge) the page says so ONCE,
    # under the itinerary, instead of repeating it under every property; where some do, each says its own.
    unrated_everywhere = d["has_lodges"] and not d["any_rated"]
    for step in d["steps"]:
        if step["type"] == "flight":
            detail = (f'<br><span style="color:{_palette()[0]}">{escape(step["detail"])}</span>'
                      if step.get("detail") else "")
            out.append(f'<div style="margin:2px 0">{escape(step["when"])} · {escape(step["text"])}{detail}</div>')
        else:
            out.append(_stay_html(step, level, show_basis=not d["lines"], say_unrated=not unrated_everywhere))
    if unrated_everywhere:
        out.append(f'<div style="margin:3px 0 0 0">Reviews: {NO_RATING_WORDS} for any property on this trip.</div>')
    if d["plan_note"]:
        out.append(f'<div style="margin:3px 0 0 0;color:#92400e">{escape(d["plan_note"])}</div>')
    return "".join(out)


def _flights_notes(f: Mapping[str, Any], level: int) -> list[str]:
    """The plain words under the read line, as unescaped text pieces (the callers escape and join them)."""
    notes: list[str] = []
    if f["price_uses"]:
        notes.append(f["price_uses"])
    if f["status"] == "read":
        if f["has_flights"]:
            notes.append("Each flight's own times, carrier, stops, duration and cabin are on its line in the "
                         "Itinerary above. " + TIMES_ARE_LOCAL_WORDS)
            if f["vendor"]:
                notes.append(f"Read through {f['vendor']}.")
        else:
            if f["first_flight"]:
                notes.append(f"First flight on that read: {f['first_flight']}")
            if f["times"]:
                notes.append(f"First flight {f['times']}")
            notes.append("The other flights on this trip were not itemised by the read.")
    if f["times_note"]:
        notes.append(f["times_note"])
    notes.append(f["search_cabin_note"] or f"Searched as {f['cabin']}, 5 travellers.")
    if level == FULL and f["shape"]:
        notes.append(f["shape"])
    return notes


def _upper_first(text: str) -> str:
    return text[:1].upper() + text[1:]


def _option_leg_lines(option: Mapping[str, Any]) -> list[tuple[str, str]]:
    """``[(leg words, that flight's words)]`` for an option whose read carries every flight."""
    return [(f"{day_words(lf['leg'][2])} {place_words(lf['leg'][0])} → {place_words(lf['leg'][1])}",
             leg_flight_words(lf["flight"])) for lf in option["leg_flights"]]


def _two_option_notes(d: Mapping[str, Any], level: int) -> list[str]:
    """Words under the two reads: what each product is, the local-time line, and what is not captured, once each."""
    f = d["flight"]
    notes = [_he().CABIN_NOTE]
    if any(o["has_flights"] for o in f["options"]):
        notes.append(TIMES_ARE_LOCAL_WORDS)
    lacking = next((o for o in f["options"] if not o["has_flights"]), None)
    if lacking is not None and lacking["times_note"]:
        notes.append(lacking["times_note"])
    if d["bundled_flights"]:
        notes.append("This trip's price includes its own flights, so it does not change with these reads; "
                     "they are shown for comparison.")
    cabin_note = next((o["search_cabin_note"] for o in f["options"] if o["search_cabin_note"]), "")
    notes.append(cabin_note or f"Searched as {f['cabin']}, 5 travellers.")
    if level == FULL and f["shape"]:
        notes.append(f["shape"])
    return notes


def _flights_two_html(d: Mapping[str, Any], level: int) -> str:
    """Both products' reads under Flights: price, date, vendor, cabin words, link, and every flight where the read has them.

    The Business-long-haul option's flights are printed at every level and the all-economy option's from the full
    level up: when the page has to be shortened, the second product's per-flight lines go before the first's.
    """
    ink = _palette()[0]
    f = d["flight"]
    out = [_heading("Flights")]
    for index, option in enumerate(f["options"]):
        out.append(f'<div style="margin:{"0" if index == 0 else "7px"} 0 0 0"><b style="color:{ink}">{escape(_upper_first(option["label"]))}:</b> '
                   + _a(option["read_url"], option["read_line"], bold=True) + "</div>")
        lines = []
        if option["vendor"]:
            lines.append(f"Read through {escape(option['vendor'])}.")
        if option["has_flights"] and (level == FULL or index == 0):
            lines += [f'{escape(leg)}: <span style="color:{ink}">{escape(words)}</span>'
                      for leg, words in _option_leg_lines(option)]
        elif not option["has_flights"] and option["first_flight"] and level == FULL:
            lines.append(f"First flight on that read: {escape(option['first_flight'])}")
        if lines:
            out.append("<div>" + "<br>".join(lines) + "</div>")
    out.append('<div style="margin:7px 0 0 0">' + "<br>".join(escape(n) for n in _two_option_notes(d, level)) + "</div>")
    return "".join(out)


def _flights_html(d: Mapping[str, Any], level: int) -> str:
    if len(d["flight"]["options"]) == 2:
        return _flights_two_html(d, level)
    f = d["flight"]
    out = [_heading("Flights")]
    if f["status"] == "read":
        out.append("<div>" + _a(f["read_url"], f["read_line"], bold=True) + "</div>")
    else:
        out.append("<div>Not read for these dates yet. " + _a(f["search_url"], "Search these flights", bold=True) + "</div>")
    out.append("<div>" + "<br>".join(escape(n) for n in _flights_notes(f, level)) + "</div>")
    return "".join(out)


def _short_flights_html(d: Mapping[str, Any]) -> str:
    """The short form's Flights section: the read, and when the read has every flight, each leg's line."""
    f = d["flight"]
    if len(f["options"]) == 2:
        return _flights_two_html(d, SHORT)
    ink = _palette()[0]
    head = ("<div>" + (_a(f["read_url"], f["read_line"], bold=True) if f["status"] == "read"
                       else "Not read for these dates yet. " + _a(f["search_url"], "Search these flights", bold=True))
            + "</div>")
    if f["has_flights"]:
        lines = "<br>".join(
            f'{escape(day_words(lf["leg"][2]))} {escape(place_words(lf["leg"][0]))} → {escape(place_words(lf["leg"][1]))}: '
            f'<span style="color:{ink}">{escape(leg_flight_words(lf["flight"]))}</span>'
            for lf in f["leg_flights"])
        return _heading("Flights") + head + "<div>" + lines + "<br>" + escape(TIMES_ARE_LOCAL_WORDS) + "</div>"
    return _heading("Flights") + head + "<div>" + escape(f["times_note"]) + "</div>"


def _pair_html(d: Mapping[str, Any], level: int) -> str:
    ink, muted, accent, line = _palette()
    pair = d["pair"]
    if pair is None:
        return _heading("Package vs our build") + f"<div>None for this trip: {escape(d['no_pair_words'])}.</div>"
    package, ours = pair["package"], pair["ours"]
    if level != FULL and not pair["first"]:
        # The comparison is printed once, under the first of the two pages; this one points at it.
        return (_heading("Package vs our build")
                + f"<div>{_k(escape(pair['difference'][0]))}<br>The side-by-side is under "
                  f'<a href="#{pair["other_anchor"]}" style="color:{accent};text-decoration:none;font-weight:600">'
                  f'{escape(pair["other_title"])}</a>.</div>')
    cell = 'valign="top" style="padding:3px 4px"'
    label = f'valign="top" style="padding:3px 4px 3px 0;text-transform:uppercase;font-size:10px;width:46px"'

    def title(side: Mapping[str, Any]) -> str:
        text = escape(side["title"])
        if side["id"] == d["id"]:
            return _k(text)
        return f'<a href="#{side["anchor"]}" style="color:{ink};font-size:12px"><b>{text}</b></a>'

    def row(name: str, left: str, right: str) -> str:
        return f'<tr><td {label}>{name}</td><td {cell}>{left}</td><td {cell}>{right}</td></tr>'

    def made(side: Mapping[str, Any]) -> str:
        """What a side's figure is made of, as a sentence a full-width line can carry."""
        if side["lines"]:
            return " + ".join(f"£{gbp:,.0f} {escape(text)}" for text, gbp, _b in side["lines"])
        return escape(side["basis"])

    def price(side: Mapping[str, Any]) -> str:
        return f'<b style="font-size:14px;color:{accent}">{escape(side["price_words"])}</b><br>{escape(side["price_label"])}'

    tag = f'<b style="font-size:10px;color:{accent};text-transform:uppercase">%s</b><br>'
    rows = [row("", tag % "Operator package" + title(package), tag % "Our build" + title(ours)),
            row("For 5", price(package), price(ours)),
            row("Nights", f'{package["nights"]} nights<br>{escape(package["per_night"])}',
                f'{ours["nights"]} nights<br>{escape(ours["per_night"])}'),
            row("Flights", escape(package["flights_words"]), escape(ours["flights_words"]))]
    out = [_heading("Package vs our build"),
           '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse">'
           + "".join(rows) + "</table>",
           f'<div style="margin:4px 0 0 0">{_k(escape(pair["difference"][0]))}</div>']
    extra = [escape(x) for x in pair["difference"][1:]]
    if level == FULL:
        # Full width, under the table: a sentence about how each figure was made does not fit a 150 px column.
        extra.append(f"<b>The package is made of:</b> {made(package)}")
        extra.append(f"<b>Our build is made of:</b> {made(ours)}")
        extra.append(f"<b>Catch of the package:</b> {escape(package['catch'])}")
        extra.append(f"<b>Catch of our build:</b> {escape(ours['catch'])}")
    if extra:
        out.append("<div>" + "<br>".join(extra) + "</div>")
    return "".join(out)


def _price_html(d: Mapping[str, Any], level: int) -> str:
    out = [_heading("What the price covers")]
    if d["lines"]:
        out.append("<div>" + "<br>".join(
            f"<b>£{gbp:,.0f}</b> · {escape(text)}" + (f" — {escape(basis)}" if basis and level == FULL else "")
            for text, gbp, basis in d["lines"]) + "</div>")
    notes: list[str] = []
    if d["cabin_totals"]:
        notes.append("The flights line is the figure this price was first built with; the totals at the top "
                     "replace it with the read for these exact dates.")
    if level == FULL and d["cost_basis"]:
        notes.append(escape(d["cost_basis"]))
    elif not d["lines"]:
        notes.append(escape(d["cost_basis"]))
    if d["why"]:
        notes.append(f"<b>Why it is here:</b> {escape(d['why'])}")
    notes.append(f"<b>The catch:</b> {escape(d['catch'])}")
    out.append("<div>" + "<br>".join(notes) + "</div>")
    return "".join(out)


def _header_html(d: Mapping[str, Any]) -> str:
    ink, muted, accent, _line = _palette()
    he = _he()
    fits = d["fits"]
    if fits is True:
        chip = ("#dcfce7", "#166534", "low end fits the budget")
    elif fits is None:
        chip = ("#f1f5f9", "#475569", "no budget set, no verdict")
    else:
        chip = ("#fef3c7", "#92400e", f"low end {d['verdict'].replace('low end ', '')} the {he._gbp(d['budget'])} budget")
    out = [f'<div style="text-transform:uppercase;letter-spacing:.04em">'
           f'{escape(d["kind_label"])} · {d["nights"]} nights · {escape(d["price_label"])}</div>',
           f'<div style="font-size:16px;font-weight:700;line-height:1.3;color:{ink}">{escape(d["title"])}</div>']
    if d["operator_ref"]:
        out.append(f'<div>{escape(d["operator_ref"])}</div>')
    if d["cabin_totals"]:
        # The trip's own price itemises its flights, so its total can be said under each read (23 Oct 2026).
        for item in d["cabin_totals"]:
            if item["fits"] is None:
                tchip = ("#f1f5f9", "#475569", "no budget set, no verdict")
            elif item["fits"]:
                tchip = ("#dcfce7", "#166534", f"fits the {he._gbp(d['budget'])} budget")
            else:
                tchip = ("#fef3c7", "#92400e", f"{he._gbp(item['gap'])} over the {he._gbp(d['budget'])} budget")
            out.append(f'<div style="margin:6px 0 0 0">{escape(item["label"])}<br>'
                       f'<b style="font-size:22px;line-height:1.1;color:{accent}">{escape(he._gbp(item["total"]))}</b> '
                       f'for 5, door to door <span style="background:{tchip[0]};color:{tchip[1]};padding:2px 8px;'
                       f'border-radius:9999px">{escape(tchip[2])}</span></div>')
        for label in d["cabin_missing"]:
            out.append(f'<div style="margin:4px 0 0 0">{escape(label)} has not been read for these dates yet.</div>')
    else:
        out += [f'<div style="margin:5px 0 0 0"><b style="font-size:24px;line-height:1.1;color:{accent}">'
                f'{escape(d["price_words"])}</b> for 5, door to door</div>',
                f'<div style="margin:4px 0 0 0"><span style="background:{chip[0]};color:{chip[1]};'
                f'padding:2px 8px;border-radius:9999px">{escape(chip[2])}</span></div>']
    for warning in d["warnings"]:
        out.append(f'<div style="margin:3px 0 0 0;color:#92400e">{escape(f"⚠ {warning}")}</div>')
    return "".join(out)


def _links_section_html(d: Mapping[str, Any]) -> str:
    links = list(d["links"])
    if d["search_url"] and not d["flight"]["same_search"]:
        links.append(("Flights search", d["search_url"]))
    if not links:
        return ""
    return _heading("Links") + "<div>" + _links_html(links) + "</div>"


def dossier_html(d: Mapping[str, Any], level: int = FULL) -> str:
    """One trip's dossier card. ``level`` is FULL, TRIMMED or SHORT (see the module constants)."""
    muted, line = _palette()[1], _palette()[3]
    out = [f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" id="{d["anchor"]}" '
           f'style="border-collapse:collapse;background:#ffffff;border:1px solid {line};border-radius:10px;margin:12px 0 0 0">'
           f'<tr><td style="padding:12px 14px;font-size:11px;color:{muted};line-height:1.45">',
           _header_html(d)]
    if level == SHORT:
        f = d["flight"]
        out.append(_heading("Itinerary"))
        out.append("<div>" + "<br>".join(_short_stop_line(step) for step in d["stays"]) + "</div>")
        if d["plan_note"]:
            out.append(f'<div style="color:#92400e">{escape(d["plan_note"])}</div>')
        out.append(_short_flights_html(d))
        out.append(_heading("Package vs our build"))
        if d["pair"] is not None:
            out.append(f'<div>{escape(d["pair"]["difference"][0])} <a href="#{d["pair"]["other_anchor"]}" '
                       f'style="color:{_palette()[2]};text-decoration:none">See the other trip</a></div>')
        else:
            out.append(f"<div>None for this trip: {escape(d['no_pair_words'])}.</div>")
        out.append(f'<div style="margin:6px 0 0 0"><b>Why it is here:</b> {escape(d["why"])}<br>'
                   f'<b>The catch:</b> {escape(d["catch"])}</div>')
        out.append(_links_section_html(d))
        out.append(f'<div style="margin:8px 0 0 0">{escape(SHORTENED_WORDS)}</div>')
    else:
        out.append(_pair_html(d, level))
        out.append(_itinerary_html(d, level))
        out.append(_flights_html(d, level))
        out.append(_price_html(d, level))
        out.append(_links_section_html(d))
        if level == TRIMMED:
            out.append(f'<div style="margin:8px 0 0 0">{escape(TRIMMED_WORDS)}</div>')
    out.append("</td></tr></table>")
    return "".join(out)


# ---------------------------------------------------------------------------
# Plain text
# ---------------------------------------------------------------------------

def dossier_lines(d: Mapping[str, Any]) -> list[str]:
    """The same dossier as plain text. Always full: the text part has no byte budget to meet."""
    he = _he()
    out = [f"{d['title']}",
           f"  {d['kind_label']} · {d['nights']} nights · {d['price_words']} for 5, door to door · {d['price_label']}"]
    if d["operator_ref"]:
        out.append(f"  {d['operator_ref']}")
    if d["cabin_totals"]:
        he = _he()
        for item in d["cabin_totals"]:
            out.append(f"  {item['label']}: {he._cabin_total_words(item, d['budget'])} (for 5, door to door)")
        out.extend(f"  {label} has not been read for these dates yet." for label in d["cabin_missing"])
    else:
        out.append(f"  {d['verdict'] if d['fits'] is not True else 'low end fits the budget'}")
    for warning in d["warnings"]:
        out.append(f"  ! {warning}")
    out.append("")
    pair = d["pair"]
    out.append("  Package vs our build")
    if pair is None:
        out.append(f"    None for this trip: {d['no_pair_words']}.")
    else:
        for side in (pair["package"], pair["ours"]):
            out.append(f"    {side['kind_label']}: {side['title']}")
            out.append(f"      {side['price_words']} for 5 · {side['price_label']}")
            out.append(f"      {side['nights']} nights · {side['per_night']}")
            out.append(f"      Flights: {side['flights_words']}")
            if side["lines"]:
                for label, gbp, basis in side["lines"]:
                    out.append(f"      £{gbp:,.0f} · {label}" + (f" ({basis})" if basis else ""))
            else:
                out.append(f"      {side['basis']}")
            out.append(f"      Catch: {side['catch']}")
        out.extend(f"    {line}" for line in pair["difference"])
    out.append("  Itinerary")
    for step in d["steps"]:
        if step["type"] == "flight":
            out.append(f"    {step['when']}: {step['text']}")
            if step.get("detail"):
                out.append(f"      {step['detail']}")
            continue
        out.append(f"    {step['window']} · {nights_phrase(step['nights'])} · {step['place']}")
        if step["cut"]:
            out.append("      cut at the flight home")
        if step["lodges"]:
            for lodge in step["lodges"]:
                out.append(f"      {lodge['name']} · {lodge['window']} · {lodge['board']}"
                           + (f" · {lodge['note']}" if lodge["note"] else ""))
                if lodge["ratings"]:
                    for rating in lodge["ratings"]:
                        out.append(f"        Reviews: {rating['words']}" + (f" {rating['url']}" if rating["url"] else ""))
                else:
                    out.append(f"        Reviews: {NO_RATING_WORDS}")
                for label, url in lodge["links"]:
                    out.append(f"        {label}: {url}")
        else:
            if step["hotel_text"]:
                out.append(f"      {step['hotel_text']}")
            out.append(f"      {NO_PROPERTY_WORDS}")
        if step["basis"] and not d["lines"]:
            out.append(f"      Basis: {step['basis']}")
    if d["plan_note"]:
        out.append(f"    {d['plan_note']}")
    f = d["flight"]
    out.append("  Flights")
    if len(f["options"]) == 2:
        for option in f["options"]:
            out.append(f"    {_upper_first(option['label'])}: {option['read_line']}: {option['read_url']}")
            if option["vendor"]:
                out.append(f"      Read through {option['vendor']}.")
            if option["has_flights"]:
                out.extend(f"      {leg}: {words}" for leg, words in _option_leg_lines(option))
            elif option["first_flight"]:
                out.append(f"      First flight on that read: {option['first_flight']}")
        out.extend(f"    {note}" for note in _two_option_notes(d, FULL))
    elif f["status"] == "read":
        out.append(f"    {f['read_line']}: {f['read_url']}")
        out.extend(f"    {note}" for note in _flights_notes(f, FULL))
    else:
        out.append(f"    Not read for these dates yet. Search these flights: {f['search_url']}")
        out.extend(f"    {note}" for note in _flights_notes(f, FULL))
    out.append("    Searched legs: " + " · ".join(
        f"{o} → {dst} {day_words(day)}" for o, dst, day in f["legs"]))
    if f["status"] == "read":
        out.append(f"    Open the same search yourself: {f['search_url']}")
    out.append("  What the price covers")
    if d["lines"]:
        for label, gbp, basis in d["lines"]:
            out.append(f"    £{gbp:,.0f} · {label}" + (f" — {basis}" if basis else ""))
    out.append(f"    {d['cost_basis']}")
    if d["why"]:
        out.append(f"    Why it is here: {d['why']}")
    out.append(f"    The catch: {d['catch']}")
    out.append("  Links")
    for label, url in list(d["links"]) + [("Flights search", d["search_url"])]:
        out.append(f"    {label}: {url}")
    out.append("")
    return out
