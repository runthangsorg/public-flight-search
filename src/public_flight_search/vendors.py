"""Package-holiday vendor links, with the real search grammar per vendor.

The owner's complaint this module answers: every hotel card ended in the same
generic Booking.com search, so the e-mail was a hotel-metasearch digest
pretending to be a package-holiday report. A package holiday is bought from a
tour operator — Love Holidays, Destination2, On the Beach, TUI, Jet2holidays,
easyJet holidays, British Airways Holidays — so the card has to carry one link
per operator, and each link has to carry the actual search: departure
airport(s), outbound and return dates, nights, and the party.

HONESTY CONTRACT
----------------
Three link kinds, and the renderer must show which one it is:

``DEEP_LINK``
    The constructed URL lands on a dated, party-correct results page. Every
    search parameter in ``carried`` was observed being honoured.
``PREFILLED_SEARCH``
    The URL carries some of the search and the reader completes the rest on
    the vendor's own widget. This is *not* a deep link and is never labelled
    as one.
``DESTINATION_PAGE``
    The vendor accepts no search parameters in a URL at all (POST-only search,
    or opaque internal IDs). The link is the vendor's own page for that
    destination — never a bare homepage, which was the old behaviour.

No vendor link is ever a price. A constructed URL has not been priced, so
every link carries :data:`PRICE_NOT_VERIFIED`; only a fare or rate actually
observed on an exact date may be labelled ``verified-exact-date`` elsewhere in
the report.

OBSERVED GRAMMAR (Camoufox renders / curl, 2026-09-23)
------------------------------------------------------
Love Holidays — the site emits its own query grammar in links on its
homepage, which is where these parameter names come from:

    search results page, emitted by loveholidays itself:
    https://www.loveholidays.com/holidays/?destinationIds=1101&flexibility=0
        &nights=7&rooms=2&f._type=searchSelectionFilters&sort=POPULAR
        &dateType=absolute
    hotel page, emitted by loveholidays itself:
    https://www.loveholidays.com/holidays/l/?date=2026-10-04&boardBasis=
        &masterId=2233&departureAirports=&rooms=2&nights=7&source=srp

    So ``date``, ``departureAirports``, ``rooms``, ``nights``, ``flexibility``,
    ``sort`` and ``dateType`` are loveholidays' own parameter names. ``rooms``
    is adults-per-room, comma-separated per room: the widget's default
    "1 Room / 2 Adults" is emitted as ``rooms=2``.

    ``destinationIds`` is opaque, but it is NOT underivable: each destination
    page publishes its own id in the search link it renders, so the reader is
    sent to the site's own dated search instead of a country landing page that
    ignores the parameters (read 2026-09-24; Turkey's own next-page link is
    ``/holidays/?destinationIds=1036&flexibility=0&nights=7&rooms=2&…``).
    Where a destination publishes no id, the older destination-page link is
    used rather than inventing one.

    NOT MACHINE-VERIFIED: loveholidays' results pages are DataDome-protected
    (``blocked_reason: datadome-challenge`` on every render of ``/holidays/``
    and of a destination page), so the parameters could not be watched being
    honoured. The homepage itself renders, which is where the grammar and the
    destination slugs below were read from. Hence PREFILLED_SEARCH, not
    DEEP_LINK.

Destination2 — its search cannot be deep-linked at all. The homepage search
form is ``<form action="/search" method="post">`` (observed in the served
HTML), and a GET to ``/search`` with those field names answers HTTP 301 to
itself, looping until curl gives up:

    https://www.destination2.co.uk/search?searchrequest.searchtype=package&...
        -> 301, Location: the same path, repeated to --max-redirs

    Its per-destination pages do resolve (HTTP 200, verified for every
    destination mapped below), so Destination2 gets a DESTINATION_PAGE link.
    Its hotel pages take a board-basis parameter — e.g.
    https://www.destination2.co.uk/hotels/rixos-premium-dubai?b=HB — but no
    dates or party, so that is not a dated deep link either.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlencode

#: The URL lands on a dated, party-correct results page.
DEEP_LINK = "deep-link"
#: The URL carries part of the search; the reader finishes it on the vendor site.
PREFILLED_SEARCH = "prefilled-search"
#: The vendor accepts no search parameters; this is its page for the destination.
DESTINATION_PAGE = "destination-page"

#: Every vendor link carries this. A URL is not a quote.
PRICE_NOT_VERIFIED = "search link, price not verified"

#: The day the grammar in this module was observed live.
GRAMMAR_OBSERVED_ON = "2026-09-23"


@dataclass(frozen=True)
class VendorLink:
    """One package vendor's entry point for one hotel card.

    ``carried`` names the search parameters the URL actually expresses, so the
    renderer can tell the reader what is still to be entered by hand instead
    of implying the link did all the work.
    """

    vendor: str
    url: str
    kind: str
    carried: tuple[str, ...]
    note: str
    observed_on: str = GRAMMAR_OBSERVED_ON
    example_url: str = ""

    @property
    def price_label(self) -> str:
        return PRICE_NOT_VERIFIED

    @property
    def is_deep_link(self) -> bool:
        return self.kind == DEEP_LINK

    @property
    def kind_label(self) -> str:
        if self.kind == DEEP_LINK:
            return "deep link — dates & party carried"
        if self.kind == PREFILLED_SEARCH:
            return "prefilled search — finish on the vendor site"
        return "destination page — dates & party entered on the vendor site"


@dataclass(frozen=True)
class TripQuery:
    """The search one hotel card is asking every vendor to run."""

    destination_key: str
    destination_airport: str
    origin_airports: tuple[str, ...]
    outbound_date: str
    return_date: str
    nights: int
    adults: int
    rooms: tuple[int, ...]
    resort_name: str = ""

    @property
    def rooms_param(self) -> str:
        """Adults per room, comma separated — loveholidays' own ``rooms=``."""
        return ",".join(str(int(r)) for r in self.rooms) if self.rooms else str(self.adults)

    @property
    def origins_param(self) -> str:
        return ",".join(a.upper() for a in self.origin_airports)


# ---------------------------------------------------------------------------
# Love Holidays
# ---------------------------------------------------------------------------

LOVEHOLIDAYS_SEARCH = "https://www.loveholidays.com/holidays/"

#: Destination-page slugs EMITTED BY loveholidays itself on its homepage
#: (2026-09-23). Only slugs the site published are used — a guessed slug is a
#: 404, and a 404 is worse than a coarser but real page. The Canaries are
#: anchored at country level because that is the granularity loveholidays
#: published; the appended search still carries the destination airport's
#: dates and party.
LOVEHOLIDAYS_DESTINATION_SLUGS: dict[str, str] = {
    "antalya": "turkey-holidays.html",
    "malta": "malta-holidays.html",
    "hurghada": "egypt-holidays.html",
    "cairo": "egypt-holidays.html",
    "tenerife": "spain-holidays.html",
    "lanzarote": "spain-holidays.html",
    "fuerteventura": "spain-holidays.html",
    "gran_canaria": "spain-holidays.html",
    "madeira": "portugal-holidays.html",
    "cape_verde": "cape-verde-islands-holidays.html",
    "paphos": "cyprus-holidays.html",
}


#: Destination ids loveholidays publishes IN ITS OWN SEARCH LINKS on each of
#: the destination pages above (read 2026-09-24). Its results pages are
#: DataDome-protected, so this is the one way to express the destination without
#: guessing: the link is the site's own next-page link, plus the dates and party.
#: Spain published a comma-separated list (mainland plus the island groups) and
#: it is used verbatim rather than truncated to one id. Keyed by the slug above,
#: so a slug with no published id keeps the destination-page link.
LOVEHOLIDAYS_DESTINATION_IDS: dict[str, str] = {
    "turkey-holidays.html": "1036",
    "spain-holidays.html": "987,391,474",
    "cyprus-holidays.html": "526",
    "egypt-holidays.html": "219",
    "malta-holidays.html": "897",
    "portugal-holidays.html": "917",
    "cape-verde-islands-holidays.html": "215",
}


def build_loveholidays_link(trip: TripQuery) -> VendorLink:
    """Love Holidays' own dated search, or its destination page where it publishes no id.

    Example (Tenerife, 2026-12-22 → 2026-12-30, LGW, 2+2+1)::

        https://www.loveholidays.com/holidays/?destinationIds=987%2C391%2C474
            &date=2026-12-22&nights=8&rooms=2%2C2%2C1&departureAirports=LGW
            &dateType=absolute&flexibility=0&sort=PRICE
    """
    slug = LOVEHOLIDAYS_DESTINATION_SLUGS.get(trip.destination_key.lower())
    destination_ids = LOVEHOLIDAYS_DESTINATION_IDS.get(slug) if slug else None
    params: dict[str, object] = {
        "date": trip.outbound_date,
        "nights": trip.nights,
        "rooms": trip.rooms_param,
        "departureAirports": trip.origins_param,
        "dateType": "absolute",
        "flexibility": 0,
        "sort": "PRICE",
    }
    if destination_ids:
        # The site's own search endpoint, with the destination as the site
        # itself expresses it.
        params = {"destinationIds": destination_ids, **params}
        base = LOVEHOLIDAYS_SEARCH
        note = (
            "the destination is loveholidays' own destinationIds, read from the search "
            "link its destination page publishes, and the dates, nights, party and "
            "departure airports are in its own query grammar; its results page is "
            "bot-protected, so parameter honouring could not be machine-verified"
        )
        carried = ("destination", "outbound date", "nights", "party", "departure airports")
    elif slug:
        base = LOVEHOLIDAYS_SEARCH + slug
        note = (
            "loveholidays publishes no destination id for this region, so this is its "
            "destination page with the search appended; pick the destination there"
        )
        carried = ("outbound date", "nights", "party", "departure airports")
    else:
        base = LOVEHOLIDAYS_SEARCH
        note = (
            "loveholidays publishes no destination page for this region, so the "
            "search carries dates, nights, party and airports only — pick the "
            "destination in its search box"
        )
        carried = ("outbound date", "nights", "party", "departure airports")
    return VendorLink(
        vendor="Love Holidays",
        url=base + "?" + urlencode(params),
        kind=PREFILLED_SEARCH,
        carried=carried,
        note=note,
        example_url=(
            "https://www.loveholidays.com/holidays/?destinationIds=1101"
            "&flexibility=0&nights=7&rooms=2&f._type=searchSelectionFilters"
            "&sort=POPULAR&dateType=absolute"
        ),
    )


# ---------------------------------------------------------------------------
# Destination2
# ---------------------------------------------------------------------------

DESTINATION2_BASE = "https://www.destination2.co.uk/destinations/"

#: Verified HTTP 200 on 2026-09-23, every one of them.
DESTINATION2_DESTINATION_PATHS: dict[str, str] = {
    "antalya": "europe/turkey",
    "malta": "europe/malta",
    "taghazout": "morocco/agadir",
    "hurghada": "middle-east/egypt",
    "cairo": "middle-east/egypt",
    "muscat": "middle-east/oman",
    "doha": "middle-east/qatar",
    "tenerife": "europe/spain/canaries",
    "lanzarote": "europe/spain/canaries",
    "fuerteventura": "europe/spain/canaries",
    "gran_canaria": "europe/spain/canaries",
    "madeira": "europe/portugal",
    "cape_verde": "cape-verde",
    "paphos": "europe/cyprus",
}


def build_destination2_link(trip: TripQuery) -> Optional[VendorLink]:
    """Destination2's own destination page — its search is POST-only.

    Example (Oman)::

        https://www.destination2.co.uk/destinations/middle-east/oman
    """
    path = DESTINATION2_DESTINATION_PATHS.get(trip.destination_key.lower())
    if not path:
        return None
    return VendorLink(
        vendor="Destination2",
        url=DESTINATION2_BASE + path,
        kind=DESTINATION_PAGE,
        carried=("destination",),
        note=(
            "Destination2's search is a POST form; a GET search URL answers a "
            "redirect loop, so no dated link can be built — enter the dates "
            "and party on its own search widget"
        ),
        example_url="https://www.destination2.co.uk/destinations/middle-east/oman",
    )


def build_vendor_links(trip: TripQuery) -> tuple[VendorLink, ...]:
    """Every package vendor's entry point for one hotel card.

    A vendor with no product for the destination is omitted rather than
    linked to a homepage or a 404.
    """
    links: list[VendorLink] = [build_loveholidays_link(trip)]
    for builder in (build_destination2_link,):
        link = builder(trip)
        if link is not None:
            links.append(link)
    return tuple(links)


def trip_from_deal(deal, *, adults: int, rooms: tuple[int, ...]) -> TripQuery:
    """The vendor search one :class:`~public_flight_search.holidays.PackageDeal`
    is asking for. Kept here so the renderer never assembles a query by hand."""
    return TripQuery(
        destination_key=deal.destination_key,
        destination_airport=deal.destination_airport,
        origin_airports=tuple(deal.origin_airports),
        outbound_date=deal.outbound_date,
        return_date=deal.return_date,
        nights=deal.nights,
        adults=int(adults),
        rooms=tuple(rooms),
        resort_name=deal.resort_name,
    )
