"""Production job entry points; configuration and delivery remain runtime-only."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import os

from .config import load_flight_config, build_search_plan
from .google_flights import build_google_flights_url, search_google_flights
from .holidays import _date_pairs, load_holiday_config, render_holiday_report
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


def run_holiday_planner(*, dry_run: bool) -> dict[str, int | bool]:
    config = load_holiday_config(os.environ.get("HOLIDAY_SEARCH_CONFIG_JSON", ""))
    html = render_holiday_report(
        config, generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    if not dry_run:
        send_html(os.environ.get("HOLIDAY_EMAIL_SUBJECT", "Holiday package watch"), html)
    date_combination_count = len(_date_pairs(config))
    result = {
        "destination_count": len(config.destinations),
        "date_combination_count": date_combination_count,
        "provider_entry_count": (
            len(config.destinations) * date_combination_count * 6
        ),
        "email_sent": not dry_run,
    }
    print(json.dumps(result, sort_keys=True))
    return result
