"""Production job entry points; configuration and delivery remain runtime-only."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import os

from .config import load_flight_config
from .google_flights import build_google_flights_url, search_google_flights
from .holidays import _date_pairs, load_holiday_config, render_holiday_report
from .mailer import send_html
from .report import render_flight_report


def run_flight_digest(*, dry_run: bool) -> dict[str, int | bool]:
    config = load_flight_config(os.environ.get("FLIGHT_SEARCH_CONFIG_JSON", ""))

    observed_offers = asyncio.run(search_google_flights(config.searches))

    google_links: dict[str, dict[str, str]] = {}
    for search in config.searches:
        for origin in search.origins:
            for dest in search.destinations:
                for day in search.dates:
                    key = f"{origin}_{dest}_{day}"
                    google_links[key] = {
                        "url": build_google_flights_url(
                            origin=origin,
                            destination=dest,
                            date=day,
                            travellers=search.travellers,
                            cabin_class=search.cabin_class,
                        ),
                        "label": f"{origin}→{dest} {day}",
                    }

    html = render_flight_report(
        config,
        observed_offers,
        google_links=google_links,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
    if not dry_run:
        send_html(os.environ.get("FLIGHT_EMAIL_SUBJECT", "Flight deal digest"), html)
    result = {
        "search_count": len(config.searches),
        "offer_count": sum(len(v) for v in observed_offers.values()),
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
