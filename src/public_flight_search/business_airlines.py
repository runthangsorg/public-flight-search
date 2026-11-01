"""Airlines the owner does not want to fly in business class (owner, 27 Oct 2026).

The first business-deals mail led with an IndiGo fare; the owner answered that business class on
low-cost carriers, or on Air India (and later LOT), is not wanted. Every business-class pick here (the business-deals
job, and the planner's BUSINESS fares loaded by ``live_verify``) drops a fare flown by one of these.
A config may add names (``exclude_airlines``); it cannot remove these. dealsearch keeps the same
list in holiday_scraper/live/business_airlines.py.

Carrier matching lives here too (owner, 1 Nov 2026): ``split_airlines`` reads one page's carrier
string as separate carriers, ``carrier_banned`` reads a ban list and ``carrier_named`` scores the
``airline_quality.tier_1`` list, so a ban and a tier never disagree about where a carrier ends.
dealsearch keeps the same helpers in holiday_scraper/live/business_airlines.py.
"""

from __future__ import annotations

import re
from typing import Iterable, Union

EXCLUDED_FOR_BUSINESS = (
    # named by the owner (LOT added 27 Oct 2026; EgyptAir 31 Oct 2026)
    "Air India", "Air India Express", "LOT", "EgyptAir", "Egypt Air",
    # low-cost and hybrid carriers that sell a "business" or "stretch" seat
    "IndiGo", "SpiceJet", "Akasa Air", "flydubai", "Air Arabia", "flynas", "Jazeera Airways", "Pegasus",
    "Eurowings", "Ryanair", "easyJet", "Wizz Air", "Jet2", "Vueling", "Transavia", "Volotea",
    "Norse Atlantic", "Play", "French bee", "ZIPAIR", "Scoot", "Jetstar", "AirAsia", "Air Asia", "VietJet",
    "Cebu Pacific",
)

#: Where one carrier ends and the next begins in a page's own words: ", / + &", ";", the word "and",
#: and an opening bracket ("Qatar Airways (operated by Iberia)" names two carriers).
_CARRIER_SPLIT = re.compile(r"\s*[,/+&;(]\s*|\s+and\s+", re.IGNORECASE)

#: Short codes the owner writes in ``airline_quality.tier_1`` and the full names Google Flights
#: returns. Either spelling names the other, so neither form has to be guessed (owner, 1 Nov 2026).
AIRLINE_ALIASES = (
    ("jal", "japan airlines"),
    ("ana", "all nippon airways"),
)


def _norm(name: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (name or "").lower()))


def split_airlines(airlines: Union[str, Iterable[str]]) -> list[str]:
    """The carriers in one string (or an iterable of names), each on its own.

    Shared by ``excluded_airline`` and ``airline_tier``, so "Emirates and flydubai" is two carriers
    for a ban and for a tier alike. A trailing bracket is dropped with the bracket that opened it.
    """
    if not isinstance(airlines, str):
        return [str(a).strip() for a in airlines]
    parts = (p.strip().rstrip(")").strip() for p in _CARRIER_SPLIT.split(airlines))
    return [part for part in parts if part]


def _names_carrier(carrier_norm: str, name_norm: str) -> bool:
    """``name_norm`` as whole words inside ``carrier_norm``: "Air India" catches "Air India Express"."""
    return re.search(rf"(?:^| ){re.escape(name_norm)}(?: |$)", carrier_norm) is not None


def _alias_forms(name: str) -> tuple[str, ...]:
    """``name`` normalised, plus the other spelling of any alias pair it is half of."""
    norm = _norm(name)
    if not norm:
        return ()
    for short, full in AIRLINE_ALIASES:
        if norm == short:
            return (norm, full)
        if norm == full:
            return (norm, short)
    return (norm,)


def carrier_banned(carrier: str, names: Iterable[str]) -> bool:
    """True when ``carrier`` is on ``names``, read the one way a ban is read: the name, as whole
    words, inside the name the page gave ("Air India" catches "Air India Express", not "Air Indiana")."""
    flown = _norm(carrier)
    return bool(flown) and any(_names_carrier(flown, b) for b in (_norm(n) for n in names) if b)


def carrier_named(carrier: str, names: Iterable[str]) -> bool:
    """True when ``carrier`` is one of ``names``: whole words either way round, aliases honoured.

    Google Flights names carriers in full ("Japan Airlines") while ``airline_quality`` may hold the
    short code ("JAL"), and neither contains the other, so both directions count and
    ``AIRLINE_ALIASES`` bridges that pair.
    """
    return any(_names_carrier(mine, theirs) or _names_carrier(theirs, mine)
               for mine in _alias_forms(carrier) for name in names for theirs in _alias_forms(name))


def excluded_airline(airlines: Union[str, Iterable[str]], extra: Iterable[str] = ()) -> str:
    """The first of ``airlines`` that is on the list (or ``extra``), as the page named it; ``""`` for none.

    A name matches as whole words: "Air India" catches "Air India Express", not "Air Indiana".
    """
    banned = (*EXCLUDED_FOR_BUSINESS, *extra)
    for airline in split_airlines(airlines):
        if carrier_banned(airline, banned):
            return str(airline).strip()
    return ""


def airline_tier(airlines: Union[str, Iterable[str]], tier_1: Iterable[str]) -> int:
    """1 when every carrier named is on ``tier_1``, else 2 (owner, 1 Nov 2026: "Qatar has a much superior business class").

    Offers name their carriers without saying which operates, so every name counts as operating: a mixed
    itinerary takes the worst tier among them. Bans are ``excluded_airline``'s job, decided before this.
    """
    good = tuple(n for n in tier_1 if _norm(n))
    flown = [c for c in split_airlines(airlines) if _norm(c)]
    if not good or not flown:
        return 2
    return 1 if all(carrier_named(carrier, good) for carrier in flown) else 2
