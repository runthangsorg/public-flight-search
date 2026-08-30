"""Command-line entry point for bounded flight-offer filtering."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional, Sequence

from .engine import SearchCriteria, search_offers
from .io import load_json_source
from .jobs import run_flight_digest, run_holiday_planner


def _codes(value: str) -> frozenset[str]:
    return frozenset(part.strip().upper() for part in value.split(",") if part.strip())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, help="local JSON file or HTTPS endpoint")
    parser.add_argument("--origins", default="")
    parser.add_argument("--destinations", default="")
    parser.add_argument("--max-stops", type=int, default=2)
    parser.add_argument("--max-duration-minutes", type=int, default=1440)
    parser.add_argument("--max-price", type=float)
    parser.add_argument("--currency")
    parser.add_argument("--max-results", type=int, default=10)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] in {"flight-digest", "holiday-planner"}:
        command = arguments.pop(0)
        dry_run = "--dry-run" in arguments
        if set(arguments) - {"--dry-run"}:
            raise SystemExit("only --dry-run is accepted for production jobs")
        if command == "flight-digest":
            run_flight_digest(dry_run=dry_run)
        else:
            run_holiday_planner(dry_run=dry_run)
        return 0
    args = build_parser().parse_args(arguments)
    if not 1 <= args.max_results <= 100:
        raise SystemExit("--max-results must be between 1 and 100")
    criteria = SearchCriteria(
        origins=_codes(args.origins),
        destinations=_codes(args.destinations),
        max_stops=args.max_stops,
        max_duration_minutes=args.max_duration_minutes,
        max_price=args.max_price,
        currency=args.currency,
    )
    offers = search_offers(load_json_source(args.source), criteria)
    print(
        json.dumps(
            [offer.to_public_dict() for offer in offers[: args.max_results]],
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
