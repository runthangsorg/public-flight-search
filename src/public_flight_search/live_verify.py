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
  whole-party, exact-date contract. The evidence arrives as a committed
  file exported by the private engine (``holiday_live_evidence.json``),
  seeded by the workflow alongside price history; every entry is
  re-validated here for basis, exact dates, party size and freshness.
* :class:`LiveFareEvidence` forces the basis to travel with the figure, so
  a per-person amount can never be consumed as a party total.
* No function here invents, extrapolates or multiplies a price. Empty
  evidence leaves deals at ``market-supported`` benchmarks.
"""

from __future__ import annotations

import json
import sys
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
    carrier: str = ""
    cabin_class: str = "ECONOMY"

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


#: Evidence older than this is treated as stale cache, never as live.
EVIDENCE_MAX_AGE_HOURS = 72

#: Where the workflow lands the private engine's evidence file.
DEFAULT_EVIDENCE_PATH = "data/holiday_live_evidence.json"


#: Cabins the holiday report may consume live evidence for. The December
#: report prices ECONOMY/PREMIUM_ECONOMY/BUSINESS cards; the July mandate is
#: BUSINESS-led. FIRST has no card in either report today.
EVIDENCE_CABINS: frozenset[str] = frozenset(
    {"ECONOMY", "PREMIUM_ECONOMY", "BUSINESS"}
)


def _target_date_pair(config) -> tuple[str, str]:
    """The exact outbound/return pair the report is actually priced on.

    Must match the pair selection in ``holidays.collect_holiday_deals``:
    the middle element of the shortlisted date pairs.
    """
    from .holidays import _date_pairs, _shortlist_pairs

    pairs = _shortlist_pairs(_date_pairs(config))
    if not pairs:
        return "", ""
    return pairs[len(pairs) // 2]


#: Skips from the most recent evidence load, surfaced in the job summary
#: so an operator sees exactly why an airport stayed on benchmarks.
_SKIP_LOG: list[str] = []


def consume_skip_log() -> list[str]:
    """Return and clear the skip reasons recorded by the last evidence load."""
    items = list(_SKIP_LOG)
    _SKIP_LOG.clear()
    return items


def _warn_skip(airport: str, reason: str) -> None:
    message = f"{airport or '?'}: {reason}"
    _SKIP_LOG.append(message)
    print(f"live-evidence: skipping {message}", file=sys.stderr)


def _parse_observed_at(raw: str) -> Optional[datetime]:
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value


def load_live_flight_evidence(
    config,
    *,
    path: str = DEFAULT_EVIDENCE_PATH,
    now: Optional[datetime] = None,
) -> dict[str, LiveFareEvidence]:
    """Load live-fare evidence produced by the private ``dealsearch`` engine.

    The private engine drives a real browser, reads the itinerary card the
    provider actually rendered, and records the whole-party total WITH its
    price basis and provenance. Its exporter writes this file; the public
    workflow seeds it from the private repo exactly like price history.

    Acceptance is deliberately strict — an entry is consumed only when
    every one of these holds:

    * ``basis`` is a whole-party basis (per-person amounts are never
      multiplied up — that was the fabrication this module exists to
      prevent);
    * the hunt's outbound/return dates match the report's priced pair
      exactly;
    * the hunt's party size matches ``config.travellers`` (a whole-party
      total is only valid for the party it was quoted for);
    * the observation is younger than ``EVIDENCE_MAX_AGE_HOURS`` — older
      observations are stale cache, not live;
    * ``source_url`` is a real http(s) URL and ``total_gbp`` is a positive
      finite number.

    Anything else is skipped with a reason on stderr. A missing or
    unreadable file returns an empty mapping (stay on benchmarks) — never
    a fabricated figure and never a crash.
    """
    del now  # parameter kept for test injection via _parse_observed_at callers
    target_outbound, target_return = _target_date_pair(config)
    if not target_outbound:
        return {}

    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError) as exc:
        print(f"live-evidence: unreadable {path}: {exc}", file=sys.stderr)
        return {}

    entries = payload.get("evidence", []) if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        print(f"live-evidence: {path} has no evidence list", file=sys.stderr)
        return {}

    now_dt = datetime.now(timezone.utc)
    evidence: dict[str, LiveFareEvidence] = {}
    for index, item in enumerate(entries):
        if not isinstance(item, dict):
            _warn_skip(f"#{index}", "not an object")
            continue
        airport = str(item.get("airport", "")).strip().upper()
        basis = str(item.get("basis", "")).strip()
        try:
            total = float(item.get("total_gbp"))
        except (TypeError, ValueError):
            _warn_skip(airport, "total_gbp missing or not a number")
            continue
        if not airport or not total > 0 or total != total or total in (
            float("inf"), float("-inf")
        ):
            _warn_skip(airport or f"#{index}", "airport missing or total not positive/finite")
            continue
        if basis not in WHOLE_PARTY_BASES:
            _warn_skip(airport, f"basis {basis!r} is not a whole-party basis")
            continue
        source_url = str(item.get("source_url", "")).strip()
        if not source_url.startswith(("http://", "https://")):
            _warn_skip(airport, "source_url missing or not http(s)")
            continue
        observed_raw = str(item.get("observed_at", "")).strip()
        observed = _parse_observed_at(observed_raw)
        if observed is None:
            _warn_skip(airport, "observed_at missing or unparseable")
            continue
        age_hours = (now_dt - observed).total_seconds() / 3600.0
        if age_hours < 0:
            _warn_skip(airport, "observed_at is in the future")
            continue
        if age_hours > EVIDENCE_MAX_AGE_HOURS:
            _warn_skip(airport, f"stale: observed {age_hours:.0f}h ago (max {EVIDENCE_MAX_AGE_HOURS}h)")
            continue
        exact_dates = item.get("exact_dates") or {}
        if (
            str(exact_dates.get("outbound", "")).strip() != target_outbound
            or str(exact_dates.get("return", "")).strip() != target_return
        ):
            _warn_skip(
                airport,
                f"dates {exact_dates.get('outbound')}…{exact_dates.get('return')} "
                f"do not match the priced pair {target_outbound}…{target_return}",
            )
            continue
        try:
            hunted_travellers = int(item.get("travellers"))
        except (TypeError, ValueError):
            _warn_skip(airport, "travellers missing — party size unverifiable")
            continue
        if hunted_travellers != int(getattr(config, "travellers", 0)):
            _warn_skip(airport, f"party {hunted_travellers} != report party {config.travellers}")
            continue
        # Origin must match too: a whole-party fare read from a different
        # departure airport answers a different question (and the report's
        # UK ground cost is origin-specific).
        entry_origin = str(item.get("origin", "")).strip().upper()
        report_origin = str(getattr(config, "origins", [""])[0]).strip().upper()
        if entry_origin and entry_origin != report_origin:
            _warn_skip(airport, f"origin {entry_origin} != report origin {report_origin}")
            continue

        entry_cabin = str(item.get("cabin_class", "ECONOMY")).strip().upper()
        if entry_cabin not in EVIDENCE_CABINS:
            _warn_skip(airport, f"cabin {entry_cabin!r} is not a reportable cabin")
            continue
        entry = LiveFareEvidence(
            airport=airport,
            total_gbp=total,
            basis=basis,
            source_url=source_url,
            observed_at=observed_raw,
            exact_date_match=True,
            note=str(item.get("note", "")).strip(),
            carrier=str(item.get("carrier", "")).strip(),
            cabin_class=entry_cabin,
        )
        # Key by (airport, cabin): the report renders ECONOMY, PREMIUM_ECONOMY
        # and BUSINESS cards for the same airport, and an ECONOMY fare must
        # never price (let alone LIVE-verify) a Business card. Freshness
        # tie-break is now within a cabin, not within an airport.
        key = (airport, entry_cabin)
        existing = evidence.get(key)
        if existing is None or observed > _parse_observed_at(existing.observed_at):
            evidence[key] = entry
    return evidence


def try_live_flight_offers(
    config,
    *,
    max_searches: int = 12,
    path: str = DEFAULT_EVIDENCE_PATH,
) -> Mapping[str, LiveFareEvidence]:
    """Return promotable live fare evidence keyed by (airport, cabin).

    Two activation paths, both explicit operator actions:

    * the evidence file exists (the workflow seeds it from the private
      engine's committed export — no network is touched here);
    * ``HOLIDAY_LIVE_FLIGHTS`` is set (historical gate, kept for tests).

    With neither, returns an empty mapping: a deliberate, documented
    outcome — deals stay on benchmarks, never on a derived figure.
    ``max_searches`` is retained for signature compatibility and unused.
    """
    del max_searches
    import os

    if not _live_enabled() and not os.path.exists(path):
        return {}
    return load_live_flight_evidence(config, path=path)
