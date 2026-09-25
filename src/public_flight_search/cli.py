"""Command-line entry point for bounded flight-offer filtering."""

from __future__ import annotations

import argparse
import json
import os
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


def _evidence_contract(arguments: list[str]) -> int:
    """Print what a report run will look for, so a hunt can be aimed from it.

    The private hunt cannot read this repository's code: it guessed date
    pairs, origins and airports, and the guesses were mostly unusable. This
    emits the contract as data — ``--hunt-config`` narrows it to just the
    overrides a hunt config needs.
    """
    config_path = ""
    if "--config" in arguments:
        index = arguments.index("--config")
        if index + 1 < len(arguments):
            config_path = arguments[index + 1]
            del arguments[index : index + 2]
        if not config_path:
            raise SystemExit("--config requires a path")
    if set(arguments) - {"--hunt-config"}:
        raise SystemExit(
            "only --config and --hunt-config are accepted for evidence-contract"
        )

    payload = ""
    if config_path:
        # An explicit path that does not exist is operator error, never a
        # reason to fall through. Silently doing so aimed a hunt from the
        # WRONG report: `--config examples/july_holday_config.json` (typo)
        # printed a valid December contract and exited 0. Failing fast is the
        # whole point of a contract emitted for machine consumption.
        if not os.path.exists(config_path):
            raise SystemExit(f"--config path does not exist: {config_path}")
        with open(config_path, encoding="utf-8") as handle:
            payload = handle.read()
    if not payload:
        payload = os.environ.get("HOLIDAY_SEARCH_CONFIG_JSON") or os.environ.get(
            "JULY_HOLIDAY_SEARCH_CONFIG_JSON"
        ) or ""
    if not payload:
        fallback = "examples/dec_holiday_config.json"
        if os.path.exists(fallback):
            with open(fallback, encoding="utf-8") as handle:
                payload = handle.read()

    from .holidays import load_holiday_config
    from .live_verify import evidence_consumption_contract

    contract = evidence_consumption_contract(load_holiday_config(payload))
    if contract is None:
        raise SystemExit("configuration prices no date pair; no hunt to aim")
    print(
        json.dumps(
            contract.hunt_config_overrides()
            if "--hunt-config" in arguments
            else contract.as_dict(),
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "evidence-contract":
        return _evidence_contract(arguments[1:])
    if arguments and arguments[0] in {"flight-digest", "holiday-planner", "july-holiday-planner"}:
        command = arguments.pop(0)
        dry_run = "--dry-run" in arguments
        force_send = "--force-send" in arguments
        config_path = ""
        if "--config" in arguments:
            idx = arguments.index("--config")
            if idx + 1 < len(arguments):
                config_path = arguments[idx + 1]
                del arguments[idx:idx + 2]
        allowed_flags = {"--dry-run", "--force-send"}
        if set(arguments) - allowed_flags:
            raise SystemExit("only --dry-run, --force-send, and --config are accepted for production jobs")
        if command == "flight-digest":
            run_flight_digest(dry_run=dry_run)
        elif command == "july-holiday-planner":
            if not config_path and not os.environ.get("JULY_HOLIDAY_SEARCH_CONFIG_JSON") and not os.environ.get("HOLIDAY_SEARCH_CONFIG_JSON"):
                config_path = "examples/july_holiday_config.json"
            # This command IS the July planner, so a config that prices December is a mistake
            # and never a report: the engine reads the generic secret first, so the wrong
            # secret is one env binding away.
            run_holiday_planner(dry_run=dry_run, force_send=force_send, config_path=config_path,
                                expect_season="july")
        else:
            run_holiday_planner(dry_run=dry_run, force_send=force_send, config_path=config_path,
                                expect_season="december")
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
