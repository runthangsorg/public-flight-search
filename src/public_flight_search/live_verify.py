"""Live flight-evidence boundary for the public engine.

Why this module no longer scrapes Google Flights for prices
-----------------------------------------------------------

It used to fetch the results page over plain HTTP and, when it found an
amount, convert it into a whole-party return total with::

    estimate = one_way_per_person * travellers * 2

That number was then stamped ``verified-exact-date`` on the holiday deal.
It was wrong twice over, and the correction matters more than the code:

1. **The figure is fabricated.** A return total derived from a one-way
   per-person fare is an estimate wearing a verification label. The
   repository's own rule is that an estimate, filename match, benchmark or
   unreviewed extraction is never described as verified evidence.
2. **The page carries no fares at all.** Verified 2026-09-16: the HTML the
   server returns contains zero currency amounts across every
   ``AF_initDataCallback`` payload (``ds:0``–``ds:4``). Fares are loaded by
   a follow-up XHR once JavaScript runs, so a plain HTTP fetch cannot
   obtain a real fare no matter how it is parsed. The old parser also read
   an assumed payload path (``payload[3][0]``) that had since become
   ``None``, so it returned nothing on every run — which is why the
   fabricated branch was so rarely exercised, and why
   ``live_flight_airports`` was always 0.

Where real live prices come from instead
----------------------------------------

Browser automation, on the private compute tiers only, because public
GitHub-hosted runners must not run it. The private ``dealsearch`` engine
drives a real browser, clears the consent wall, reads the rendered
itinerary cards and records the whole-party total the provider actually
displayed — with times, carrier, stops, layover and per-tier baggage.
See ``holiday_scraper/live/`` in that repository.

This module is therefore an **honest seam**, not a scraper:

* :func:`try_live_flight_offers` returns only evidence that satisfies the
  whole-party, exact-date contract. Today that is nothing, and it says so.
* :class:`LiveFareEvidence` forces the basis to travel with the figure, so
  a per-person amount can never be consumed as a party total.
* No function here invents, extrapolates or multiplies a price. Empty
  evidence leaves deals at ``market-supported`` benchmarks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Mapping, Optional

#: Bases on which a displayed amount can be a whole-trip total. Only these
#: may promote a deal to ``verified-exact-date``.
WHOLE_PARTY_BASES: frozenset[str] = frozenset(
    {
        "whole_party_return_total",
        "whole_party_one_way_total",
    }
)

#: Bases that describe something other than the party's total for the trip.
#: These are explicitly *not* promotable, which is the whole point: the old
#: code multiplied a per-person one-way amount and called it verified.
NON_PROMOTABLE_BASES: frozenset[str] = frozenset(
    {
        "per_person_one_way",
        "per_person_return",
        "nightly_room_rate",
        "derived_from_per_person",
    }
)


@dataclass(frozen=True)
class LiveFareEvidence:
    """A live fare together with the basis it was displayed on.

    The basis is mandatory precisely so that a consumer cannot silently
    treat a per-person amount as a party total.
    """

    airport: str
    total_gbp: float
    basis: str
    source_url: str
    observed_at: str
    exact_date_match: bool = True
    note: str = ""

    @property
    def promotable(self) -> bool:
        """True only when this may label a deal ``verified-exact-date``."""
        return self.basis in WHOLE_PARTY_BASES and self.exact_date_match

    @property
    def is_non_promotable_basis(self) -> bool:
        return self.basis in NON_PROMOTABLE_BASES


def _live_enabled() -> bool:
    import os

    return os.getenv("HOLIDAY_LIVE_FLIGHTS", "").lower() in {"1", "true", "yes"}


def live_evidence_unavailable_reason() -> str:
    """Human-readable statement of why no live fares are available here.

    Surfaced in the job summary so an operator sees why the report is on
    benchmarks instead of assuming the live path ran cleanly.
    """
    return (
        "Live exact-date fares require a real browser (the results page "
        "carries no fares in its server-rendered HTML). Browser automation "
        "does not run on public runners: it runs on the private compute "
        "tiers. Deals therefore remain market-supported benchmarks."
    )


def try_live_flight_offers(
    config, *, max_searches: int = 12
) -> Mapping[str, LiveFareEvidence]:
    """Return promotable live fare evidence keyed by airport.

    Returns an empty mapping. That is a deliberate, documented outcome
    rather than a failure being swallowed: a plain HTTP request cannot
    obtain a fare from these results pages, so there is nothing honest to
    return, and returning a derived figure would be the bug this module
    exists to prevent.

    Callers must treat an empty mapping as "stay on benchmarks" and must
    never read it as a zero price.
    """
    if not _live_enabled():
        return {}

    # The HTTP path is retained only as an explicit capability statement.
    # If a future provider does serve fares to a non-browser client, its
    # reader must return LiveFareEvidence carrying a whole-party basis —
    # never a bare float, and never a multiplied per-person figure.
    return {}
