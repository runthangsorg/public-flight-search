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
``SEARCH_PAGE``
    Like DESTINATION_PAGE but for an operator whose whole search is behind a
    bot wall or a JavaScript app whose URL grammar could not be confirmed
    from its own live site with plain fetches. The link is the operator's own
    search page and the note says the dates and party are entered there. The
    kind exists so a link that does not prefill can never be labelled as one
    that does.

ATOL OPERATORS ON LONG-HAUL CARDS (owner brief 2026-10-03, F1)
--------------------------------------------------------------
A long-haul card also links the six ATOL package operators the owner named:
British Airways Holidays, Qatar Airways Holidays, Emirates Holidays, Etihad
Holidays, Kuoni and Trailfinders. Each URL was checked against the operator's
own live site on 2026-10-03 with plain fetches only — no CAPTCHA solving, no
bot-wall evasion, no logins — and only what the checks could actually support
was built:

- Kuoni (kuoni.co.uk, live HTTP 200): its search widget is JavaScript-only
  (no form action; input placeholder "Search destinations, hotels and
  holidays") and its enquiry forms are POST, so no dates/party can be
  prefilled. Its own sitemap (https://www.kuoni.co.uk/sitemap.xml, live) does
  publish destination pages, so the link is the operator's destination page
  for the card's destination — verified live 200 on 2026-10-03 for koh-samui,
  koh-phangan, khao-lak, lombok-and-gili-islands and cancun.
- British Airways Holidays: ba.com served an Akamai "Information Page"
  interstitial to plain fetchers ("We are experiencing high demand on
  ba.com"), so no URL grammar was observable. Search page, no prefill.
- Emirates Holidays: emiratesholidays.com served a DataDome CAPTCHA wall
  (HTTP 403 to both fetchers). Search page, no prefill.
- Etihad Holidays: etihadholidays.com and holidays.etihad.com both answered
  301 with ``Location: https://www.etihad.com/holidays`` (or /en-ae/holidays)
  — the operator's own redirect — but the page body times out from this
  network, so nothing deeper could be confirmed. Search page, no prefill.
- Qatar Airways Holidays: HTTP 403 and connection timeouts on every fetch
  path tried. Search page, no prefill.
- Trailfinders: every path serves an Incapsula interstitial (NOINDEX,
  NOFOLLOW), sitemap included. Search page, no prefill.

None of the six therefore earns a prefilled URL today: the card's
"Package operators" header carries the dates, party of 5 and origins (that is
the search), and each link's note says the dates and party are entered on the
operator's site. If an operator's grammar is later confirmed from its own
live site — dates observed landing prefilled — its builder upgrades to
``PREFILLED_SEARCH`` and the block footer's label names it.

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
from typing import Optional, Sequence
from urllib.parse import urlencode

#: The URL lands on a dated, party-correct results page.
DEEP_LINK = "deep-link"
#: The URL carries part of the search; the reader finishes it on the vendor site.
PREFILLED_SEARCH = "prefilled-search"
#: The vendor accepts no search parameters; this is its page for the destination.
DESTINATION_PAGE = "destination-page"
#: The operator's own search page, entered by hand: its URL grammar could not
#: be confirmed from its live site with plain fetches (bot wall or JS app).
SEARCH_PAGE = "search-page"

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
        if self.kind == SEARCH_PAGE:
            return (
                "search page — no prefill: dates & party entered "
                "on the operator's site"
            )
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


JET2_DESTINATION_PATHS: dict[str, str] = {
    "malta": "https://www.jet2holidays.com/destinations/malta",
    "antalya": "https://www.jet2holidays.com/destinations/turkey",
    "taghazout": "https://www.jet2holidays.com/destinations/morocco",
    "hurghada": "https://www.jet2holidays.com/destinations/egypt/hurghada",
    "tenerife": "https://www.jet2holidays.com/destinations/canary-islands/tenerife",
    "madeira": "https://www.jet2holidays.com/destinations/portugal/madeira",
    "lanzarote": "https://www.jet2holidays.com/destinations/canary-islands/lanzarote",
    "fuerteventura": "https://www.jet2holidays.com/destinations/canary-islands/fuerteventura",
    "gran_canaria": "https://www.jet2holidays.com/destinations/canary-islands/gran-canaria",
    "paphos": "https://www.jet2holidays.com/destinations/cyprus",
}


EASYJET_DESTINATION_PATHS: dict[str, str] = {
    "malta": "https://www.easyjet.com/en/holidays/malta",
    "antalya": "https://www.easyjet.com/en/holidays/turkey/antalya",
    "cairo": "https://www.easyjet.com/en/holidays/egypt/cairo",
    "taghazout": "https://www.easyjet.com/en/holidays/morocco/agadir",
    "hurghada": "https://www.easyjet.com/en/holidays/egypt/hurghada",
    "tenerife": "https://www.easyjet.com/en/holidays/spain/tenerife",
    "madeira": "https://www.easyjet.com/en/holidays/portugal/madeira",
    "lanzarote": "https://www.easyjet.com/en/holidays/spain/lanzarote",
    "fuerteventura": "https://www.easyjet.com/en/holidays/spain/fuerteventura",
    "gran_canaria": "https://www.easyjet.com/en/holidays/spain/gran-canaria",
}


def build_jet2_link(trip: TripQuery) -> Optional[VendorLink]:
    """Jet2holidays' destination page where it operates."""
    url = JET2_DESTINATION_PATHS.get(trip.destination_key.lower())
    if not url:
        return None
    return VendorLink(
        vendor="Jet2holidays",
        url=url,
        kind=DESTINATION_PAGE,
        carried=("destination",),
        note="Jet2holidays destination page; enter the exact dates and party on its search widget",
        example_url=url,
    )


def build_easyjet_link(trip: TripQuery) -> Optional[VendorLink]:
    """easyJet holidays' destination page where it operates."""
    url = EASYJET_DESTINATION_PATHS.get(trip.destination_key.lower())
    if not url:
        return None
    return VendorLink(
        vendor="easyJet holidays",
        url=url,
        kind=DESTINATION_PAGE,
        carried=("destination",),
        note="easyJet holidays destination page; enter the exact dates and party on its search widget",
        example_url=url,
    )


# ---------------------------------------------------------------------------
# ATOL package operators on long-haul cards (owner brief 2026-10-03, F1)
# ---------------------------------------------------------------------------

#: The day every URL in this section was checked against the operator's own
#: live site (plain fetches only; see the module docstring for per-operator
#: results).
ATOL_GRAMMAR_OBSERVED_ON = "2026-10-03"

BA_HOLIDAYS_SEARCH_PAGE = (
    "https://www.britishairways.com/en-gb/flights-and-holidays/holidays"
)
QATAR_HOLIDAYS_SEARCH_PAGE = "https://www.qatarairways.com/en/holidays.html"
EMIRATES_HOLIDAYS_SEARCH_PAGE = "https://www.emiratesholidays.com/"
ETIHAD_HOLIDAYS_SEARCH_PAGE = "https://www.etihad.com/holidays"
TRAILFINDERS_SEARCH_PAGE = "https://www.trailfinders.com/"
KUONI_DESTINATIONS_INDEX = "https://www.kuoni.co.uk/destinations/"

#: Kuoni destination pages, from Kuoni's own sitemap, each verified live
#: (HTTP 200) on 2026-10-03. Keys absent here fall back to the destinations
#: index rather than a guessed URL.
KUONI_DESTINATION_PATHS: dict[str, str] = {
    "lombok": "https://www.kuoni.co.uk/destinations/south-east-asia/"
              "indonesia/lombok-and-gili-islands/",
    "koh_samui": "https://www.kuoni.co.uk/destinations/south-east-asia/"
                 "thailand/koh-samui/",
    "koh_phangan": "https://www.kuoni.co.uk/destinations/south-east-asia/"
                   "thailand/koh-phangan/",
    "khao_lak": "https://www.kuoni.co.uk/destinations/south-east-asia/"
                "thailand/khao-lak/",
    "riviera_maya": "https://www.kuoni.co.uk/destinations/caribbean/"
                    "mexico/cancun/",
}

#: The URL bases the six operators' links may use. holidays.py folds these
#: into its VERIFIED_LINK_BASES allowlist so the renderer cannot emit a
#: different base for the same operators.
ATOL_OPERATOR_LINK_BASES: tuple[str, ...] = (
    BA_HOLIDAYS_SEARCH_PAGE,
    QATAR_HOLIDAYS_SEARCH_PAGE,
    EMIRATES_HOLIDAYS_SEARCH_PAGE,
    ETIHAD_HOLIDAYS_SEARCH_PAGE,
    TRAILFINDERS_SEARCH_PAGE,
    KUONI_DESTINATIONS_INDEX,
    *KUONI_DESTINATION_PATHS.values(),
)

#: The card's search, stated on every no-prefill note: the reader carries the
#: dates, party and origin from the card's "Package operators" header into the
#: operator's own site.
_ENTER_ON_SITE = (
    "no prefill: the operator's URL grammar could not be confirmed from its own "
    "live site with plain fetches, so enter the card's dates and party there"
)


def build_kuoni_link(trip: TripQuery) -> VendorLink:
    """Kuoni's own page for the destination, from Kuoni's own sitemap.

    Its search widget is JavaScript-only and its enquiry forms are POST, so a
    dated search URL cannot be built; the destination page is the deepest page
    the site itself publishes for the card's destination.
    """
    url = KUONI_DESTINATION_PATHS.get(
        trip.destination_key.lower(), KUONI_DESTINATIONS_INDEX
    )
    fallback = url == KUONI_DESTINATIONS_INDEX
    return VendorLink(
        vendor="Kuoni",
        url=url,
        kind=DESTINATION_PAGE,
        carried=("destination",),
        note=(
            "Kuoni publishes no dated search URL (its search widget is "
            "JavaScript-only and its forms are POST), so this is its page for "
            "the destination — "
            + (
                "the destinations index, because its sitemap publishes no page "
                "for this destination; "
                if fallback
                else ""
            )
            + "enter the card's dates and party on the site"
        ),
        observed_on=ATOL_GRAMMAR_OBSERVED_ON,
        example_url=KUONI_DESTINATION_PATHS["koh_samui"],
    )


def _search_page_link(vendor: str, url: str, *, note_prefix: str) -> VendorLink:
    """A walled operator's search page: honest, unparameterised, labelled."""
    return VendorLink(
        vendor=vendor,
        url=url,
        kind=SEARCH_PAGE,
        carried=(),
        note=note_prefix + " — " + _ENTER_ON_SITE,
        observed_on=ATOL_GRAMMAR_OBSERVED_ON,
        example_url=url,
    )


def build_ba_holidays_link(trip: TripQuery) -> VendorLink:
    """British Airways Holidays' holidays hub.

    ba.com served an Akamai "Information Page" interstitial to plain fetches
    (2026-10-03), so no URL grammar was observable and nothing is prefilled.
    """
    return _search_page_link(
        "British Airways Holidays", BA_HOLIDAYS_SEARCH_PAGE,
        note_prefix="ba.com interstitials plain fetches, so no search grammar "
                    "was observable",
    )


def build_qatar_holidays_link(trip: TripQuery) -> VendorLink:
    """Qatar Airways Holidays' holidays page (403/timeout to plain fetches)."""
    return _search_page_link(
        "Qatar Airways Holidays", QATAR_HOLIDAYS_SEARCH_PAGE,
        note_prefix="qatarairways.com answered 403 / timed out on every plain "
                    "fetch path",
    )


def build_emirates_holidays_link(trip: TripQuery) -> VendorLink:
    """Emirates Holidays' own site root (DataDome CAPTCHA wall to fetchers)."""
    return _search_page_link(
        "Emirates Holidays", EMIRATES_HOLIDAYS_SEARCH_PAGE,
        note_prefix="emiratesholidays.com serves a DataDome CAPTCHA wall to "
                    "plain fetches",
    )


def build_etihad_holidays_link(trip: TripQuery) -> VendorLink:
    """Etihad Holidays' page — the redirect target its own domains publish.

    etihadholidays.com and holidays.etihad.com both 301 to this URL (the
    operator's own redirect), but the page body times out from this network,
    so nothing deeper than the page could be confirmed.
    """
    return _search_page_link(
        "Etihad Holidays", ETIHAD_HOLIDAYS_SEARCH_PAGE,
        note_prefix="etihadholidays.com redirects here but the page body times "
                    "out on plain fetches",
    )


def build_trailfinders_link(trip: TripQuery) -> VendorLink:
    """Trailfinders' site root (Incapsula interstitial on every path)."""
    return _search_page_link(
        "Trailfinders", TRAILFINDERS_SEARCH_PAGE,
        note_prefix="trailfinders.com serves an Incapsula interstitial on every "
                    "path",
    )


def build_atol_operator_links(trip: TripQuery) -> tuple[VendorLink, ...]:
    """The six ATOL package operators, in the brief's order.

    Only links the operators' own live sites support are built: Kuoni's
    destination page (from its own sitemap) and the five search pages whose
    grammar is behind bot walls. Where an operator's grammar is confirmed
    later — dates observed landing prefilled on its live site — its builder
    upgrades to PREFILLED_SEARCH and nothing else needs to change.
    """
    return (
        build_ba_holidays_link(trip),
        build_qatar_holidays_link(trip),
        build_emirates_holidays_link(trip),
        build_etihad_holidays_link(trip),
        build_kuoni_link(trip),
        build_trailfinders_link(trip),
    )


def price_label_line(links: Sequence[VendorLink]) -> str:
    """The one price label under a vendor block, worded for what the links are.

    Every link is not a quote. A block whose links really do prefill the
    search is labelled "prefilled search link, …"; a block containing any
    link that does not prefill must not wear that word, so it reads "search
    link, …" and each link's own tag says which it is.
    """
    all_prefilled = bool(links) and all(
        link.kind == PREFILLED_SEARCH for link in links
    )
    head = "prefilled search link" if all_prefilled else "search link"
    return head + ", price not verified — a link is not a quote."


def build_vendor_links(trip: TripQuery) -> tuple[VendorLink, ...]:
    """Every package vendor's entry point for one hotel card.

    A vendor with no product for the destination is omitted rather than
    linked to a homepage or a 404.
    """
    links: list[VendorLink] = [build_loveholidays_link(trip)]
    for builder in (build_destination2_link, build_jet2_link, build_easyjet_link):
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
