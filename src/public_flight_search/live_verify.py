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

# ``config`` sits below ``holidays`` in the import graph, so importing the
# shared cabin set from there stays acyclic (holidays imports this module).
from .config import REPORT_CABINS

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
    #: True when the observation is older than ``EVIDENCE_MAX_AGE_HOURS``.
    stale: bool = False

    @property
    def promotable(self) -> bool:
        """True only when this may label a deal ``verified-exact-date``."""
        return (
            self.basis in WHOLE_PARTY_BASES
            and self.exact_date_match
            and not self.stale
        )

    @property
    def usable(self) -> bool:
        """True when this may price a card at all, fresh or aged.

        Age decides the *label*, not whether the number is worth showing. An
        aged whole-party exact-date fare for the dates and party this report
        prices is real evidence that is merely not current; a benchmark is a
        typical price for nobody in particular. Dropping the aged record is what
        made a Friday observation revert the following Monday's report to
        benchmarks with nothing in the output to say it had happened.
        """
        return self.basis in WHOLE_PARTY_BASES and self.exact_date_match

    @property
    def confidence(self) -> str:
        """The provenance label this evidence earns, as the card renders it."""
        if self.promotable:
            return "verified-exact-date"
        return "stale-cache" if self.usable else "market-supported"

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


#: Evidence older than this is stale cache: it may still be shown, but it may
#: never be labelled live. ONE threshold, shared by the loader, the job's
#: ``live_evidence_stale`` flag and the card's amber label (owner rule
#: 2026-10-02): 48 hours, so a two-day-old fare is not called live.
EVIDENCE_MAX_AGE_HOURS = 48

#: The ceiling beyond which an aged observation is no longer evidence of
#: anything and is discarded outright. A fare read two months ago prices nothing
#: today, so it must not stand in for one. Between ``EVIDENCE_MAX_AGE_HOURS`` and
#: here a record is kept and labelled ``stale-cache``; past here it is dropped.
EVIDENCE_STALE_CACHE_MAX_AGE_HOURS = 24 * 30

#: Where the workflow lands the private engine's evidence file.
DEFAULT_EVIDENCE_PATH = "data/holiday_live_evidence.json"


#: Cabins the holiday report may consume live evidence for.
#:
#: Derived from ``config.REPORT_CABINS`` — the same set the holiday config
#: loader validates against — so the loader gate and the renderable-cabin set
#: cannot drift. Hardcoding a narrower list here is what made a FIRST fare
#: consumable by the contract and simultaneously rejected by the loader.
EVIDENCE_CABINS: frozenset[str] = REPORT_CABINS


def priced_date_pair(config) -> tuple[str, str]:
    """The pair the report is HEADLINE-priced on: the shortlist's middle.

    Single source of truth. ``holidays.collect_holiday_deals`` prices every
    pair inside the config's nights band and resolves ties to this one, so a
    benchmark-only run still displays these dates; the evidence loader and
    the hunt contract both derive it from here, so the pair can never be
    stated twice and disagree.

    ``hunt_date_pairs`` is deliberately WIDER than this (the whole shortlist):
    a hunt that only ever crawls the headline pair wastes two thirds of its
    reads the moment the report prices more than one pair.
    """
    from .holidays import _date_pairs, _shortlist_pairs

    pairs = _shortlist_pairs(_date_pairs(config))
    if not pairs:
        return "", ""
    return pairs[len(pairs) // 2]


#: Retained private name: the original seam, now an alias of the one
#: definition above so callers cannot diverge from the report.
_target_date_pair = priced_date_pair


def evidence_for(
    mapping,
    airport: str,
    cabin: str,
    outbound: str,
    returning: str,
    origin: str,
    *,
    headline: tuple[str, str] = ("", ""),
) -> Optional[LiveFareEvidence]:
    """The fare this run may price one card with, or None.

    Two mapping shapes reach here, and they are NOT interchangeable:

    * the loader's output is keyed
      ``(airport, cabin, outbound, return, origin)``, so a fare observed for
      17→25 out of LGW may only price a card that shows 17→25 out of LGW;
    * a caller-supplied mapping keyed ``(airport, cabin)`` (tests, scripts)
      carries no dates and no origin at all. Such a mapping has always meant
      "the pair this report is priced on", so it is trusted for the headline
      pair only. Trusting it for every pair a widened run now prices would
      let one observation stand in for dates nobody observed — the exact
      fabrication this module exists to prevent.
    """
    if not mapping:
        return None
    if outbound and returning:
        try:
            return mapping[(airport, cabin, outbound, returning, origin)]
        except (KeyError, TypeError):
            pass
    if headline and (outbound, returning) == tuple(headline):
        try:
            return mapping[(airport, cabin)]
        except (KeyError, TypeError):
            return None
    return None


@dataclass(frozen=True)
class EvidenceContract:
    """What one report run will actually look for, stated as data.

    The private hunt cannot read the public report's code, so it guessed its
    date pairs, origins and airports. The guesses were wrong in expensive
    ways: of 125 harvested records only 8 priced a December card, six crawled
    airports had no card at all, and two card airports were never crawled.

    This is the machine-readable replacement for that guess — printed by
    ``python -m public_flight_search evidence-contract`` and recorded in every
    job summary, so a hunt can be aimed from data instead of from memory.
    """

    outbound: str
    return_date: str
    origin: str
    travellers: int
    keys: tuple[tuple[str, str], ...]
    hunt_date_pairs: tuple[tuple[str, str], ...] = ()
    #: Every departure airport the report prices from, in config order. The
    #: hunt needs all of them: a fare observed from LGW is a different fare
    #: from the LHR one, and the collector will price whichever is cheaper.
    origins: tuple[str, ...] = ()
    #: Which resort catalogue produced ``keys``: WINTER_RESORT_CATALOG for a
    #: winter trip, SUMMER_RESORT_CATALOG layered over it for a summer one.
    catalog: str = ""

    @property
    def airports(self) -> tuple[str, ...]:
        return tuple(sorted({airport for airport, _cabin in self.keys}))

    @property
    def cabins(self) -> tuple[str, ...]:
        return tuple(sorted({cabin for _airport, cabin in self.keys}))

    def as_dict(self) -> dict:
        """Full statement of the contract, for logs and job summaries."""
        return {
            "priced_pair": [self.outbound, self.return_date],
            "origin": self.origin,
            "origins": list(self.origins or ((self.origin,) if self.origin else ())),
            "travellers": self.travellers,
            "hunt_date_pairs": [list(pair) for pair in self.hunt_date_pairs],
            "airports": list(self.airports),
            "cabins": list(self.cabins),
            "keys": [f"{airport}/{cabin}" for airport, cabin in self.keys],
            "catalog": self.catalog,
        }

    def hunt_config_overrides(self) -> dict:
        """A self-contained config the private hunt can run as-is.

        ``python -m live --config <file>`` reads ``party.travellers`` and
        ``destinations[].airports`` and nothing else from the payload, so a
        fragment carrying only the four overrides built zero routes — a hunt
        aimed from it did no work at all. This therefore includes both:
        travellers (the evidence loader skips a fare whose party size does
        not match) and one destination entry per contracted airport, which
        is the narrower set the report has cards for.
        """
        return {
            "party": {"travellers": int(self.travellers)},
            "destinations": [
                {"airports": [airport], "label": airport}
                for airport in self.airports
            ],
            "origins": list(self.origins or ((self.origin,) if self.origin else ())),
            "date_pairs": [list(pair) for pair in self.hunt_date_pairs],
            "cabin_classes": list(self.cabins),
            "airports": list(self.airports),
        }


def evidence_consumption_contract(config) -> Optional[EvidenceContract]:
    """The set of ``(airport, cabin)`` keys this run can ever verify.

    Returns ``None`` when the config prices no valid date pair or when no
    destination has a card, in which case no evidence could be consumed and
    a hunt would be wasted spend.
    """
    from .holidays import (
        _date_pairs,
        _shortlist_pairs,
        card_lookup_keys,
        resort_catalog_name,
    )

    outbound, returning = priced_date_pair(config)
    if not outbound:
        return None
    keys = card_lookup_keys(config)
    if not keys:
        return None
    origins = tuple(str(value).strip().upper() for value in (getattr(config, "origins", ()) or ()) if str(value).strip())
    hunt_pairs = _shortlist_pairs(_date_pairs(config)) or ((outbound, returning),)
    return EvidenceContract(
        outbound=outbound,
        return_date=returning,
        origin=origins[0] if origins else "",
        travellers=int(getattr(config, "travellers", 0) or 0),
        keys=keys,
        hunt_date_pairs=hunt_pairs,
        origins=origins,
        catalog=resort_catalog_name(config),
    )


def _key_label(pair: tuple[str, str]) -> str:
    """Render an ``(airport, cabin)`` key the way the job summary shows it."""
    return f"{pair[0]}/{pair[1]}"


def evidence_contract_gaps(config, loaded) -> dict[str, list[str]]:
    """Split loaded evidence into what the report needs and what it can't use.

    ``missing`` is the actionable half: a card that exists and has no live
    fare — i.e. exactly what the next hunt should crawl. ``unused`` is the
    waste half: fares harvested for keys no card will ever look up.
    """
    contract = evidence_consumption_contract(config)
    if contract is None:
        return {"missing": [], "unused": []}
    wanted = set(contract.keys)
    # Positional, not an unpack: the loader keys entries by (airport, cabin,
    # outbound, return, origin) so one key can hold several date pairs, while
    # callers also hand in plain (airport, cabin) maps. Both are read here.
    have = {
        (str(key[0]).strip().upper(), str(key[1]).strip().upper())
        for key in loaded
    }
    return {
        "missing": sorted(_key_label(pair) for pair in wanted - have),
        "unused": sorted(_key_label(pair) for pair in have - wanted),
    }


def evidence_freshness(
    path: str = DEFAULT_EVIDENCE_PATH, *, now: Optional[str] = None
) -> dict:
    """Age of the newest observation in the evidence store.

    The hunt is not automated, so the store lapses between manual runs while
    ``EVIDENCE_MAX_AGE_HOURS`` (72) silently turns every card back into a
    benchmark. Reporting the age makes that expiry visible on every run
    instead of leaving it to be inferred from a wall of skip reasons.

    ``stale`` True means no fresh evidence is available, including when the
    file is missing or unreadable, and including when every observation is
    future-dated. A future-dated record is one the loader rejects outright
    ("observed_at is in the future"), so it cannot be counted as the newest
    observation here: doing so reported ``stale=False`` with a negative
    ``age_hours`` while the same run's skip log said the record was dropped.
    """
    empty = {
        "record_count": 0,
        "newest_observed_at": None,
        "age_hours": None,
        "stale": True,
        "future_dated": 0,
    }
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return empty

    entries = payload.get("evidence", []) if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        return empty

    now_dt = _parse_observed_at(now or "") or datetime.now(timezone.utc)
    newest_raw: Optional[str] = None
    newest_dt: Optional[datetime] = None
    count = 0
    future_dated = 0
    for item in entries:
        if not isinstance(item, dict):
            continue
        count += 1
        raw = str(item.get("observed_at", "")).strip()
        observed = _parse_observed_at(raw)
        if observed is None:
            continue
        if observed > now_dt:
            # Same rejection the loader applies, so the summary cannot
            # contradict its own skip log.
            future_dated += 1
            continue
        if newest_dt is None or observed > newest_dt:
            newest_dt, newest_raw = observed, raw
    if newest_dt is None:
        return {**empty, "record_count": count, "future_dated": future_dated}

    age_hours = (now_dt - newest_dt).total_seconds() / 3600.0
    return {
        "record_count": count,
        "newest_observed_at": newest_raw,
        "age_hours": round(age_hours, 3),
        "stale": age_hours > EVIDENCE_MAX_AGE_HOURS,
        "future_dated": future_dated,
    }


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
    * the hunt's outbound/return dates are one of the pairs this run
      prices (``min_nights``..``max_nights``), and its origin is one of the
      configured origins — a fare is evidence for ITS dates and ITS
      departure airport, and nothing else;
    * the hunt's party size matches ``config.travellers`` (a whole-party
      total is only valid for the party it was quoted for);
    * the observation is younger than ``EVIDENCE_STALE_CACHE_MAX_AGE_HOURS``;
      between ``EVIDENCE_MAX_AGE_HOURS`` (48) and that ceiling it is still
      consumed, but labelled ``stale-cache`` instead of
      ``verified-exact-date`` — an aged exact-date fare is worth showing, it
      just may not claim to be live;
    * ``source_url`` is a real http(s) URL and ``total_gbp`` is a positive
      finite number.

    Entries are returned keyed
    ``(airport, cabin, outbound, return, origin)`` so a run pricing 18 date
    pairs keeps each observation attached to the dates it was read for.

    Anything else is skipped with a reason on stderr. A missing or
    unreadable file returns an empty mapping (stay on benchmarks) — never
    a fabricated figure and never a crash.
    """
    # ``now`` is the age reference, not decoration: the caller injects it so a
    # test can pin a fixed observation instant. Measuring against the wall
    # clock instead made every fixture a time bomb — a literal observed_at
    # passes until it crosses EVIDENCE_MAX_AGE_HOURS, then the record is
    # skipped as stale and the contract tests fail on a date, not a change.
    now_dt = now or datetime.now(timezone.utc)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)
    if not _target_date_pair(config)[0]:
        return {}
    from .holidays import priceable_date_pairs

    priced_pairs = set(priceable_date_pairs(config))
    if not priced_pairs:
        return {}
    configured_origins = tuple(
        str(value).strip().upper()
        for value in (getattr(config, "origins", ()) or ())
        if str(value).strip()
    ) or ("",)
    report_origin = configured_origins[0]

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

    # A run prices exactly one season, but the evidence file holds both. Every
    # record for the OTHER season used to fall through to the per-record date
    # check and print its own "dates do not match" line — hundreds of lines for
    # a single July run. Partition them out first and report one count. This
    # is NOT a rejection: they are real observations, simply for the other
    # planner, and they are left in the file untouched.
    from .holidays import SUMMER_TRIP_MONTHS, WINTER_TRIP_MONTHS

    def _season_of(date_str: str) -> str:
        parts = str(date_str).split("-")
        if len(parts) < 2 or not parts[1].isdigit():
            return ""
        month = int(parts[1])
        if month in SUMMER_TRIP_MONTHS:
            return "summer"
        if month in WINTER_TRIP_MONTHS:
            return "winter"
        return ""

    config_season = ""
    for pair in sorted(priced_pairs):
        config_season = _season_of(pair[0])
        if config_season:
            break

    in_season: list[Any] = []
    other_season_count = 0
    for item in entries:
        if not isinstance(item, dict):
            in_season.append(item)
            continue
        record_season = _season_of(str((item.get("exact_dates") or {}).get("outbound", "")))
        if config_season and record_season and record_season != config_season:
            other_season_count += 1
        else:
            in_season.append(item)
    if other_season_count:
        print(
            f"live-evidence: {other_season_count} record(s) are for the other season "
            f"(this run prices {config_season}); not evaluated",
            file=sys.stderr,
        )

    # …and the same is true of the AIRPORT. A July run prices HKT/LOP/USM, so
    # a fare read for MLA or TFS is for another planner entirely: evaluating it
    # only produced noise ("MLA is stale cache, using it") for a fare no July
    # card will ever look up. The in-scope airports are this season's
    # destinations plus the Gulf stopover hubs, which every long-haul card
    # prices. Reported as one count, same as the season filter above.
    from .holidays import STOPOVER_HUBS

    season_airports = {
        str(code).strip().upper()
        for dest in (getattr(config, "destinations", ()) or ())
        for code in (getattr(dest, "airports", ()) or ())
    }
    season_airports |= {str(hub).strip().upper() for hub in STOPOVER_HUBS}

    other_airport_count = 0
    if season_airports:
        in_scope: list[Any] = []
        for item in in_season:
            code = str(item.get("airport", "")).strip().upper() if isinstance(item, dict) else ""
            if code and code not in season_airports:
                other_airport_count += 1
            else:
                in_scope.append(item)
        in_season = in_scope
        if other_airport_count:
            print(
                f"live-evidence: {other_airport_count} record(s) are for airports this "
                f"season does not price; not evaluated",
                file=sys.stderr,
            )

    evidence: dict[str, LiveFareEvidence] = {}
    for index, item in enumerate(in_season):
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
        if age_hours > EVIDENCE_STALE_CACHE_MAX_AGE_HOURS:
            _warn_skip(
                airport,
                f"expired: observed {age_hours:.0f}h ago "
                f"(max {EVIDENCE_STALE_CACHE_MAX_AGE_HOURS}h)",
            )
            continue
        # An aged record is KEPT, not skipped, and carries its age into the
        # label. It is a real whole-party exact-date observation for the exact
        # dates and party this report prices, so it prices the card; calling it
        # live is what must not happen. ``usable`` prices it, ``promotable``
        # decides the label, and the two are deliberately different questions.
        stale = age_hours > EVIDENCE_MAX_AGE_HOURS
        if stale:
            print(
                f"live-evidence: {airport} is stale cache (observed "
                f"{age_hours:.0f}h ago); using it, labelled stale-cache",
                file=sys.stderr,
            )
        exact_dates = item.get("exact_dates") or {}
        record_pair = (
            str(exact_dates.get("outbound", "")).strip(),
            str(exact_dates.get("return", "")).strip(),
        )
        if record_pair not in priced_pairs:
            sample = ", ".join(
                f"{outbound}→{returning}"
                for outbound, returning in sorted(priced_pairs)[:3]
            )
            _warn_skip(
                airport,
                f"dates {record_pair[0]}…{record_pair[1]} do not match a priced "
                f"pair ({len(priced_pairs)} priced, e.g. {sample})",
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
        # UK ground cost is origin-specific). A record with no origin was
        # hunted for the report's own departure airport — that is what it
        # has always meant, and what it still means here.
        entry_origin = str(item.get("origin", "")).strip().upper() or report_origin
        if entry_origin not in configured_origins:
            _warn_skip(
                airport,
                f"origin {entry_origin} is not a configured origin "
                f"({', '.join(value for value in configured_origins if value)})",
            )
            continue

        entry_cabin = str(item.get("cabin_class", "ECONOMY")).strip().upper()
        if entry_cabin not in EVIDENCE_CABINS:
            _warn_skip(airport, f"cabin {entry_cabin!r} is not a reportable cabin")
            continue
        # Legacy records exported before the cabin-aware seam carry no cabin
        # field. They were whole-party ECONOMY totals by export rule, so
        # defaulting them to ECONOMY is faithful — and the "legacy" marker
        # keeps their provenance honest.
        legacy_record = "cabin_class" not in item
        if legacy_record:
            entry_cabin = "ECONOMY"
        entry = LiveFareEvidence(
            airport=airport,
            total_gbp=total,
            basis=basis,
            source_url=source_url,
            observed_at=observed_raw,
            exact_date_match=True,
            note=(
                ("legacy pre-cabin-seam export; economy by export rule" if legacy_record else str(item.get("note", "")).strip())
            ),
            carrier=str(item.get("carrier", "")).strip(),
            cabin_class=entry_cabin,
            stale=stale,
        )
        # Keyed by (airport, cabin, outbound, return, origin). The cabin
        # component is the 2026-09-22 seam — an ECONOMY fare must never price
        # (let alone LIVE-verify) a Business card — and the date/origin
        # components are the widened-search seam: one run prices every
        # pair in the nights band from every configured origin, so an
        # observation may only stand for the dates and airport it was read
        # at. Freshness is the tie-break WITHIN one such key.
        key = (airport, entry_cabin, record_pair[0], record_pair[1], entry_origin)
        existing = evidence.get(key)
        if existing is None or observed > _parse_observed_at(existing.observed_at):
            evidence[key] = entry
    return evidence


def try_live_flight_offers(
    config,
    *,
    max_searches: int = 12,
    path: str = DEFAULT_EVIDENCE_PATH,
    now: Optional[datetime] = None,
) -> Mapping[str, LiveFareEvidence]:
    """Return usable fare evidence keyed by (airport, cabin).

    "Usable" includes an aged observation, which is returned with
    ``stale=True`` and a ``stale-cache`` label rather than being dropped; only
    ``promotable`` evidence may be rendered as live.

    Two activation paths, both explicit operator actions:

    * the evidence file exists (the workflow seeds it from the private
      engine's committed export — no network is touched here);
    * ``HOLIDAY_LIVE_FLIGHTS`` is set (historical gate, kept for tests).

    With neither, returns an empty mapping: a deliberate, documented
    outcome — deals stay on benchmarks, never on a derived figure.
    ``max_searches`` is retained for signature compatibility and unused.

    ``now`` is the age reference, forwarded to the loader so a caller (a test,
    or a run pinned to the evidence export's own instant) can measure staleness
    against a fixed clock instead of the wall clock. Without it a literal
    ``observed_at`` fixture is a time bomb that goes off once it crosses
    ``EVIDENCE_MAX_AGE_HOURS``.
    """
    del max_searches
    import os

    if not _live_enabled() and not os.path.exists(path):
        return {}
    return load_live_flight_evidence(config, path=path, now=now)
