"""Production job entry points; configuration and delivery remain runtime-only."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import os

from .config import load_flight_config
from .google_flights import search_google_flights
from .holidays import load_holiday_config, render_holiday_report
from .mailer import send_html
from .report import render_flight_report


def run_flight_digest(*, dry_run: bool) -> dict[str, int | bool]:
    config = load_flight_config(os.environ.get("FLIGHT_SEARCH_CONFIG_JSON", ""))
    offers = asyncio.run(search_google_flights(config.searches))
    html = render_flight_report(
        config, offers, generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    if not dry_run:
        send_html(os.environ.get("FLIGHT_EMAIL_SUBJECT", "Flight deal digest"), html)
    result = {
        "search_count": len(config.searches),
        "offer_count": sum(len(value) for value in offers.values()),
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
    result = {
        "destination_count": len(config.destinations),
        "provider_entry_count": len(config.destinations) * 8,
        "email_sent": not dry_run,
    }
    print(json.dumps(result, sort_keys=True))
    return result
