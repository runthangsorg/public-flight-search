"""Production job entry points; configuration and delivery remain runtime-only."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path

from .config import load_flight_config, build_search_plan
from .google_flights import build_google_flights_url, search_google_flights
from .holidays import _date_pairs, collect_holiday_deals, count_provider_entries, load_holiday_config, render_holiday_report
from .holiday_history import (
    append_history,
    build_change_digest,
    last_history_observation,
    read_history,
    render_change_digest_html,
    render_history_html,
    summarize_trends,
)
from .mailer import send_html
from .report import render_flight_report
from .trip_config import (
    DEFAULT_TRIP_DEFINITIONS,
    DEFAULT_HOLIDAY_TRIP_DEFINITION,
    TripDefinition,
    TripBucket,
)
from .pairing import pair_outbound_return, combine_legs
from .pareto import rank_bucket_sections


class FlightCollectionError(RuntimeError):
    """Prevent an empty fare collection from becoming a misleading email."""


logger = logging.getLogger(__name__)


def run_flight_digest(*, dry_run: bool) -> dict[str, int | bool]:
    """Run September UAE flight digest with multi-city pairing."""
    config = load_flight_config(os.environ.get("FLIGHT_SEARCH_CONFIG_JSON", ""))

    # Build search plan from trip definitions
    search_plan = build_search_plan(DEFAULT_TRIP_DEFINITIONS)

    # Search the same provider-neutral plan that is later paired and grouped.
    # The runtime config remains the report/fallback boundary; FlightSearch is
    # deliberately not given a synthetic ``bucket`` attribute.
    raw_offers = asyncio.run(search_google_flights(search_plan))

    request_metadata = {}
    for trip in DEFAULT_TRIP_DEFINITIONS:
        for request in trip.build_search_plan():
            request_metadata[request.key] = (trip.bucket, request.key)

    # Organize raw offers by trip bucket, direction, cabin
    offers_by_bucket = {}
    for request in search_plan:
        bucket, _ = request_metadata[request.key]
        direction = "OUTBOUND" if "_OUTBOUND_" in request.key else "RETURN"
        cabin = request.cabin_class
        offers_by_bucket.setdefault(bucket, {}).setdefault(direction, {})[cabin] = []

    # Map raw offers to the search plan
    for request in search_plan:
        bucket, _ = request_metadata[request.key]
        direction = "OUTBOUND" if "_OUTBOUND_" in request.key else "RETURN"
        cabin = request.cabin_class

        # Search results are already grouped by this request key.  The HTTP
        # adapter returns FlightOffer dataclasses, while pairing consumes
        # mappings; normalize at this boundary and derive direction from the
        # request rather than requiring a non-existent offer field.
        for offer in raw_offers.get(request.key, ()):
            normalized = (
                offer.to_public_dict()
                if hasattr(offer, "to_public_dict")
                else dict(offer)
            )

            # Normalize offer for pairing
            normalized["bucket"] = bucket
            normalized["direction"] = direction
            normalized["cabin_class"] = cabin
            offers_by_bucket[bucket][direction][cabin].append(normalized)

    # Pair outbound + return legs for each trip bucket
    final_offers = {}
    for trip in DEFAULT_TRIP_DEFINITIONS:
        bucket = trip.key
        trip_offers = []

        for cabin in trip.cabin_classes:
            outbound = offers_by_bucket.get(bucket, {}).get("OUTBOUND", {}).get(cabin, [])
            return_leg = offers_by_bucket.get(bucket, {}).get("RETURN", {}).get(cabin, [])

            if not outbound or not return_leg:
                continue

            paired = pair_outbound_return(trip, outbound, return_leg)

            # Add trip metadata and combine legs
            for paired in paired:
                paired["bucket"] = bucket
                paired["trip_key"] = trip.key
                paired["trip_label"] = trip.label
                paired["cabin_class"] = cabin
                trip_offers.append(paired)

        # Apply Pareto suppression and ranking
        if trip_offers:
            sections = rank_bucket_sections(trip_offers)
            final_offers[bucket] = sections["overall"]

    if not any(final_offers.values()):
        print(json.dumps({
            "email_sent": False,
            "itinerary_count": 0,
            "search_count": len(config.searches),
            "status": "collection_failed",
        }, sort_keys=True))
        raise FlightCollectionError("no live paired fare evidence was collected; email suppressed")

    # Build Google Flights links from the actual search plan
    google_links: dict[str, dict[str, str]] = {}
    for request in search_plan:
        for origin in request.origins:
            for dest in request.destinations:
                for day in request.dates:
                    key = f"{origin}_{dest}_{day}"
                    google_links[key] = {
                        "url": build_google_flights_url(
                            origin=origin,
                            destination=dest,
                            date=day,
                            travellers=request.travellers,
                            cabin_class=request.cabin_class,
                        ),
                        "label": f"{origin}→{dest} {day}",
                    }

    # Render report with multi-city support
    html = render_flight_report(
        config,
        final_offers,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        trip_definitions=DEFAULT_TRIP_DEFINITIONS,
    )

    if not dry_run:
        send_html(os.environ.get("FLIGHT_EMAIL_SUBJECT", "Flight deal digest"), html)

    result = {
        "search_count": len(config.searches),
        "trip_count": len(DEFAULT_TRIP_DEFINITIONS),
        "itinerary_count": sum(len(v) for v in final_offers.values()),
        "email_sent": not dry_run,
    }
    print(json.dumps(result, sort_keys=True))
    return result


def run_holiday_planner(
    *,
    dry_run: bool,
    force_send: bool = False,
    config_path: str = "",
) -> dict[str, int | bool]:
    payload = ""
    if config_path and os.path.exists(config_path):
        with open(config_path, encoding="utf-8") as handle:
            payload = handle.read()
    if not payload:
        payload = (
            os.environ.get("HOLIDAY_SEARCH_CONFIG_JSON")
            or os.environ.get("JULY_HOLIDAY_SEARCH_CONFIG_JSON")
            or ""
        )
    if not payload and os.environ.get("HOLIDAY_CONFIG_PATH"):
        cpath = os.environ["HOLIDAY_CONFIG_PATH"]
        if os.path.exists(cpath):
            with open(cpath, encoding="utf-8") as handle:
                payload = handle.read()
    if not payload:
        dec_example = Path(__file__).parents[2] / "examples" / "dec_holiday_config.json"
        if dec_example.exists():
            payload = dec_example.read_text(encoding="utf-8")

    config = load_holiday_config(payload)
    # Bounded live flight injection (GHA-safe HTTP only, no browser).
    # Disabled by default; enable with HOLIDAY_LIVE_FLIGHTS=1. Full
    # Camoufox/FlareSolverr package verification stays in the private
    # flightdealsearch engine on local/VM compute.
    live_offers: dict[str, float] = {}
    live_attempted = False
    try:
        from .live_verify import try_live_flight_offers

        live_attempted = True
        live_offers = dict(try_live_flight_offers(config))
    except Exception:
        live_offers = {}
    deals = collect_holiday_deals(
        config, max_budget_gbp=config.max_budget_gbp,
        live_flight_offers=live_offers or None,
    )
    # MEMORY BEFORE BUILD: the workflow seeds `history_path` from the
    # private repo in a dedicated bash step (proven transport) BEFORE this
    # job runs, so trends, chips and the change digest describe real
    # movement instead of 'first time tracked'. Dry runs ignore memory
    # entirely (a dry run must reflect a fresh build, never prior state).
    is_july = "july" in config.report_title.lower() or any("-07-" in d for d in config.outbound_dates)
    default_history_name = "july_holiday_price_history.jsonl" if is_july else "holiday_price_history.jsonl"
    history_path = Path(
        os.environ.get("HOLIDAY_HISTORY_PATH", f"data/{default_history_name}")
    )
    seeded_rows = 0 if dry_run else len(read_history(path=history_path))
    # Trends are computed BEFORE today's observation is appended, so the
    # chips always compare against prior runs only.
    trends = summarize_trends(deals, path=history_path)
    digest = build_change_digest(trends, path=history_path)
    html = render_holiday_report(
        config,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        deals=deals,
        history_chips=render_history_html(trends),
        change_digest_html=render_change_digest_html(digest),
    )
    # Last PRIOR observation: read BEFORE today's append lands.
    last_prior = "" if dry_run else last_history_observation(path=history_path)
    appended = 0 if dry_run else append_history(deals, path=history_path)
    # ANTI-DUPLICATE SEND: benchmark-driven deals rarely move day to day.
    # A 3x-week identical blast trains the reader to ignore the inbox, so
    # the email only goes out when something a reader would care about
    # happened: any drop, any rise, any new resort, or the very first run.
    # A flat re-quote is suppressed (still tracked, still persisted).
    # force_send overrides — and is itself overridden by dry-run so a dry
    # run can never email.
    send_email = (not dry_run) and (
        bool(force_send)
        or not digest["has_prior"]
        or bool(digest["drops"])
        or bool(digest["rises"])
        or bool(digest["new"])
        # Composite-ranking movement is reader-worthy even when benchmarks
        # are price-quiet: "your best-value pick changed" justifies the send.
        or bool(digest.get("value_changes"))
    )
    default_subject = "July Summer Luxury Holiday Watch" if is_july else "December Holiday Package Watch"
    subject = os.environ.get("HOLIDAY_EMAIL_SUBJECT") or default_subject
    if send_email:
        send_html(subject, html)
    date_combination_count = len(_date_pairs(config))
    result = {
        "destination_count": len(config.destinations),
        "date_combination_count": date_combination_count,
        # Exact rendered-link count: Jet2 is omitted where it has no product.
        "provider_entry_count": count_provider_entries(config),
        "deal_count": len(deals),
        "live_flight_airports": len(live_offers),
        "live_attempted": live_attempted,
        "history_observations_appended": appended,
        "history_seeded_rows": seeded_rows,
        "send_skipped_no_change": (not dry_run) and not send_email,
        "last_prior_observation": last_prior,
        "email_sent": send_email,
    }
    print(json.dumps(result, sort_keys=True))
    return result
