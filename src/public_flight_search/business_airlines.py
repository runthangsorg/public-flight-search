"""Airlines the owner does not want to fly in business class (owner, 27 Oct 2026).

The first business-deals mail led with an IndiGo fare; the owner answered that business class on
low-cost carriers, or on Air India (and later LOT), is not wanted. Every business-class pick here (the business-deals
job, and the planner's BUSINESS fares loaded by ``live_verify``) drops a fare flown by one of these.
A config may add names (``exclude_airlines``); it cannot remove these. dealsearch keeps the same
list in holiday_scraper/live/business_airlines.py.
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


def _norm(name: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (name or "").lower()))


def excluded_airline(airlines: Union[str, Iterable[str]], extra: Iterable[str] = ()) -> str:
    """The first of ``airlines`` that is on the list (or ``extra``), as the page named it; ``""`` for none.

    A name matches as whole words: "Air India" catches "Air India Express", not "Air Indiana".
    """
    if isinstance(airlines, str):
        airlines = re.split(r"\s*[,/+&]\s*", airlines)
    banned = [n for n in (_norm(b) for b in (*EXCLUDED_FOR_BUSINESS, *extra)) if n]
    for airline in airlines:
        flown = _norm(airline)
        if flown and any(re.search(rf"(?:^| ){re.escape(b)}(?: |$)", flown) for b in banned):
            return str(airline).strip()
    return ""


def airline_tier(airlines: Union[str, Iterable[str]], tier_1: Iterable[str]) -> int:
    """1 when every carrier named is on ``tier_1``, else 2 (owner, 1 Nov 2026: "Qatar has a much superior business class").

    Offers name their carriers without saying which operates, so every name counts as operating: a mixed
    itinerary takes the worst tier among them. Bans are ``excluded_airline``'s job, decided before this.
    """
    if isinstance(airlines, str):
        airlines = re.split(r"\s*[,/+&]\s*", airlines)
    good = [n for n in (_norm(t) for t in tier_1) if n]
    flown = [n for n in (_norm(a) for a in airlines) if n]
    if not good or not flown:
        return 2
    for carrier in flown:
        if not any(re.search(rf"(?:^| ){re.escape(g)}(?: |$)", carrier) for g in good):
            return 2
    return 1
