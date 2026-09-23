"""Self-create ("DIY") holiday: the same trip bought as its separate parts.

A package is one purchase; the same week can also be assembled by buying the
flight from the airline and the room from the hotel. The owner asked to see
both, priced, on every card — so the card has to show the flight leg, the room,
the ground legs, and a DIY total that is the SUM OF ITS PARTS.

Two rules this module exists to enforce.

**The total is computed, never carried.** :attr:`DiyOption.total_gbp` is a
property over :attr:`DiyOption.components`. Change the fare and the total moves
with it; there is no field holding a stale number that a later edit can forget
to update.

**Terminology.** "Direct" alone is banned because it means two different
things. A trajectory is ``Nonstop`` or ``1-Stop Connecting via <hub>``; a
purchasing channel is ``Airline-Direct Booking`` or ``OTA Intermediary``. A
trajectory is only ever stated where this repository holds verified nonstop
route authority for the airport — everywhere else the card says so rather than
guessing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

#: Purchasing channels. Never the bare word "Direct".
AIRLINE_DIRECT = "Airline-Direct Booking"
OTA_INTERMEDIARY = "OTA Intermediary"
HOTEL_DIRECT = "Hotel-Direct Booking"
GROUND = "Ground transport"

#: Flight trajectories.
NONSTOP = "Nonstop"
TRAJECTORY_UNVERIFIED = "trajectory not verified — confirm on the airline site"

#: Nonstop route authority this repository has actually verified, from the
#: catalogue's own route notes (holidays.py, "Route authority verified"). An
#: airport absent here gets TRAJECTORY_UNVERIFIED: an unverified nonstop claim
#: is exactly the kind of assertion the provenance gates forbid.
NONSTOP_ROUTE_AUTHORITY: dict[str, frozenset[str]] = {
    "FUE": frozenset({"easyJet", "Jet2", "Ryanair"}),
    "LPA": frozenset({"easyJet", "Jet2", "Ryanair", "British Airways"}),
    "PFO": frozenset({"Ryanair", "Jet2", "TUI", "British Airways", "easyJet"}),
}


def trajectory_label(*, destination_airport: str, carrier: str) -> str:
    """``Nonstop`` only where route authority was verified for that carrier."""
    authorised = NONSTOP_ROUTE_AUTHORITY.get((destination_airport or "").upper())
    if not authorised:
        return TRAJECTORY_UNVERIFIED
    names = {part.strip() for part in (carrier or "").replace("/", ",").split(",")}
    return NONSTOP if names & authorised else TRAJECTORY_UNVERIFIED


#: Hosts that sell on their own behalf. Anything else that sells a flight is an
#: intermediary, including a metasearch results page.
_AIRLINE_HOSTS = (
    "easyjet.com", "jet2.com", "ryanair.com", "britishairways.com",
    "tui.co.uk", "emirates.com", "qatarairways.com", "omanair.com",
    "etihad.com", "turkishairlines.com", "sunexpress.com", "flypgs.com",
    "wizzair.com", "airarabia.com", "flydubai.com", "vueling.com",
    "iberia.com", "aegeanair.com", "royalairmaroc.com", "egyptair.com",
)


def flight_channel(url: str) -> str:
    """Classify a flight link as airline-direct or an OTA intermediary."""
    host = (urlparse(url or "").hostname or "").lower().rstrip(".")
    if not host:
        return OTA_INTERMEDIARY
    for airline in _AIRLINE_HOSTS:
        if host == airline or host.endswith("." + airline):
            return AIRLINE_DIRECT
    return OTA_INTERMEDIARY


@dataclass(frozen=True)
class DiyComponent:
    """One separately-bought part of a self-created holiday."""

    label: str
    amount_gbp: float
    channel: str
    url: str = ""
    #: Where the component's own site cannot be dated, a dated search page for
    #: the same legs — labelled with its own channel, since a metasearch link
    #: is an intermediary and must not read as the airline's own price.
    dated_search_url: str = ""
    confidence: str = "market-supported"
    source_url: str = ""
    observed_timestamp: str = ""
    note: str = ""

    @property
    def dated_search_channel(self) -> str:
        return flight_channel(self.dated_search_url) if self.dated_search_url else ""

    @property
    def is_verified(self) -> bool:
        return self.confidence == "verified-exact-date"


@dataclass(frozen=True)
class DiyOption:
    """The self-create route for one hotel card."""

    components: tuple[DiyComponent, ...] = field(default_factory=tuple)

    @property
    def total_gbp(self) -> float:
        """Sum of the parts, every time it is read.

        D2D arithmetic integrity: no cached total. If a live fare replaces a
        benchmark, this figure moves with it or the arithmetic is a lie.
        """
        return round(sum(c.amount_gbp for c in self.components), 2)

    @property
    def confidence(self) -> str:
        """The weakest link's confidence — a total is only as good as its worst
        part. One live fare does not make a benchmark room rate verified."""
        labels = {c.confidence for c in self.components}
        for weakest in ("blocked/unknown", "stale-cache", "market-supported"):
            if weakest in labels:
                return weakest
        return "verified-exact-date" if labels == {"verified-exact-date"} else "market-supported"


#: The package side has no observed vendor quote, so no winner can be declared.
PACKAGE_NOT_PRICED = "package price not verified"


@dataclass(frozen=True)
class DiyComparison:
    """DIY total against a package total, and which one actually wins."""

    diy_total_gbp: float
    package_total_gbp: Optional[float]
    package_confidence: str = "market-supported"

    @property
    def delta_gbp(self) -> Optional[float]:
        """Package minus DIY: positive means self-creating is cheaper."""
        if self.package_total_gbp is None:
            return None
        return round(self.package_total_gbp - self.diy_total_gbp, 2)

    @property
    def winner(self) -> str:
        delta = self.delta_gbp
        if delta is None:
            return "unknown"
        if delta > 0:
            return "diy"
        if delta < 0:
            return "package"
        return "level"

    @property
    def statement(self) -> str:
        delta = self.delta_gbp
        if delta is None:
            return (
                f"{PACKAGE_NOT_PRICED} — self-create totals £{self.diy_total_gbp:,.0f}; "
                "price the same dates on a vendor link above to see which wins"
            )
        if delta > 0:
            return f"self-create is £{delta:,.0f} cheaper than the package"
        if delta < 0:
            return f"the package is £{abs(delta):,.0f} cheaper than self-creating"
        return "self-create and the package come out level"


def build_diy_option(
    *,
    flight_total_gbp: float,
    flight_carrier: str,
    flight_url: str,
    destination_airport: str,
    outbound_date: str,
    return_date: str,
    adults: int,
    hotel_total_gbp: float,
    hotel_name: str,
    hotel_url: str,
    nights: int,
    uk_ground_gbp: float = 0.0,
    transfer_gbp: float = 0.0,
    cabin_class: str = "ECONOMY",
    flight_confidence: str = "market-supported",
    flight_source_url: str = "",
    flight_observed_at: str = "",
    hotel_confidence: str = "market-supported",
    airline_booking_url: str = "",
) -> DiyOption:
    """Assemble the self-create route for one hotel card.

    ``airline_booking_url`` is the carrier's own booking page when one is
    known; ``flight_url`` (the dated metasearch link the report already
    computes) is then carried alongside it as the intermediary that at least
    holds the exact dates.
    """
    cabin = (cabin_class or "ECONOMY").replace("_", " ").title()
    trajectory = trajectory_label(
        destination_airport=destination_airport, carrier=flight_carrier
    )
    primary = airline_booking_url or flight_url
    flight = DiyComponent(
        label=(
            f"Flights {adults}× {cabin} — {flight_carrier} · {trajectory} · "
            f"{outbound_date} out, {return_date} back"
        ),
        amount_gbp=round(float(flight_total_gbp), 2),
        channel=flight_channel(primary),
        url=primary,
        dated_search_url=flight_url if primary != flight_url else "",
        confidence=flight_confidence,
        source_url=flight_source_url,
        observed_timestamp=flight_observed_at,
        note=(
            ""
            if flight_confidence == "verified-exact-date"
            else "benchmark fare — reprice on the airline's own page before booking"
        ),
    )
    hotel = DiyComponent(
        label=f"{hotel_name} — {nights} nights, booked with the hotel",
        amount_gbp=round(float(hotel_total_gbp), 2),
        channel=HOTEL_DIRECT,
        url=hotel_url,
        confidence=hotel_confidence,
        note=f"enter {outbound_date} → {return_date} for {adults} on the hotel's own site",
    )
    components = [flight, hotel]
    if uk_ground_gbp:
        components.append(
            DiyComponent(
                label="UK ground transport, return",
                amount_gbp=round(float(uk_ground_gbp), 2),
                channel=GROUND,
                confidence="market-supported",
            )
        )
    if transfer_gbp:
        components.append(
            DiyComponent(
                label="Resort transfer, return",
                amount_gbp=round(float(transfer_gbp), 2),
                channel=GROUND,
                confidence="market-supported",
                note="a package usually includes this; self-creating does not",
            )
        )
    return DiyOption(components=tuple(components))


#: The airline's OWN booking entry point, for carriers the holiday catalogue
#: actually names. Landing pages, not dated deep links: a per-airline dated
#: grammar is recorded separately where one has been verified. An unknown
#: carrier returns "" so the card falls back to the dated metasearch link
#: rather than sending the reader to a guessed URL.
AIRLINE_BOOKING_PAGES: dict[str, str] = {
    "easyJet": "https://www.easyjet.com/en/",
    "Jet2": "https://www.jet2.com/",
    "Ryanair": "https://www.ryanair.com/gb/en",
    "British Airways": "https://www.britishairways.com/travel/home/public/en_gb/",
    "TUI": "https://www.tui.co.uk/flight",
    "Emirates": "https://www.emirates.com/uk/english/",
    "Qatar Airways": "https://www.qatarairways.com/en-gb/homepage.html",
    "Oman Air": "https://www.omanair.com/en",
    "Etihad Airways": "https://www.etihad.com/en-gb",
    "Turkish Airlines": "https://www.turkishairlines.com/en-gb/",
    "SunExpress": "https://www.sunexpress.com/en/",
    "Pegasus": "https://www.flypgs.com/en",
    "Wizz Air": "https://wizzair.com/en-gb",
    "Vueling": "https://www.vueling.com/en",
    "Royal Air Maroc": "https://www.royalairmaroc.com/uk-en",
    "EgyptAir": "https://www.egyptair.com/en/",
}


def airline_booking_page(carrier: str) -> str:
    """The airline's own booking page for a carrier string.

    A benchmark carrier is often a SET ("easyJet / Jet2 / Ryanair"): the first
    name that is a known airline wins, because the card has room for one
    airline-direct link and the alternatives are reachable from the dated
    search beside it. An unrecognised name returns "" rather than a guess.
    """
    for part in (carrier or "").replace("/", ",").split(","):
        name = part.strip()
        if name in AIRLINE_BOOKING_PAGES:
            return AIRLINE_BOOKING_PAGES[name]
    return ""
