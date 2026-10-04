"""Production job entry points; configuration and delivery remain runtime-only."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import sys
from typing import Optional

from .holidays import (
    _date_pairs,
    collect_holiday_deals,
    count_provider_entries,
    far_east_watch_rows,
    load_holiday_config,
    render_holiday_report,
)
from .holiday_email import (
    render_holiday_report_compact,
    render_holiday_report_compact_text,
)
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


def _live_evidence_default_path() -> str:
    """Where the workflow seeds the private engine's evidence export.

    The single definition of the default tier, so ``_evidence_path`` and any
    future caller cannot disagree about it.
    """
    from .live_verify import DEFAULT_EVIDENCE_PATH

    return DEFAULT_EVIDENCE_PATH


logger = logging.getLogger(__name__)


#: The compact e-mail is the default (owner brief 2026-10-04, BRIEF-H1):
#: one price per card, one at-a-glance table, no benchmark badges.
#: ``HOLIDAY_REPORT_STYLE=detailed`` selects the previous renderer, which keeps
#: every price, provenance row and comparison this one drops — so a report can
#: still be audited end to end without a code change.
DETAILED_REPORT_STYLE = "detailed"


def _report_style() -> str:
    return os.environ.get("HOLIDAY_REPORT_STYLE", "").strip().lower()


def _evidence_path(named: str, env_name: str, default: str) -> str:
    """Where one evidence file is read from: argument, then env, then default.

    All three tiers, in that order, because they answer to different callers.
    The workflow seeds the file at the default and passes nothing; an operator
    overrides with the env var; a TEST must be able to name its own path,
    because both defaults are CWD-relative and a checkout with ``data/`` on it
    is a different machine from CI. The argument tier exists so that omission
    is visible at the call site rather than silently resolved from whatever
    happens to be in the working directory.
    """
    if named:
        return named
    return os.environ.get(env_name, default)


def _live_evidence_counts(live_offers) -> dict[str, int]:
    """Distinct airports and cabins among the fares, split by liveness.

    Keys are read positionally: the loader keys entries by
    ``(airport, cabin, outbound, return, origin)`` so one run can hold a
    fare per date pair and origin, while callers still hand in plain
    ``(airport, cabin)`` maps. Both are read here, and both count airports
    by AIRPORT — three cabins priced for AYT alone would otherwise have been
    reported as three "airports", the same mislabel the workflow seed log
    carried.

    ``live_*`` counts only fares that may be labelled live. An aged exact-date
    fare is still consumed (it prices the card and is labelled ``stale-cache``),
    so counting it as live coverage would overstate precisely what this module
    exists to keep honest. It gets its own count instead.
    """
    live = [key for key, ev in live_offers.items() if getattr(ev, "promotable", False)]
    stale = [key for key, ev in live_offers.items() if getattr(ev, "stale", False)]
    return {
        "live_flight_airports": len({str(key[0]) for key in live}),
        "live_flight_cabins": len({str(key[1]) for key in live}),
        "stale_flight_fares": len(stale),
        "stale_flight_airports": len({str(key[0]) for key in stale}),
    }


def config_season(config) -> str:
    """Which holiday a config prices: ``"july"``, ``"december"`` or ``"unknown"``.

    The two planners are separate schedules with separate secrets, and the engine reads
    ``HOLIDAY_SEARCH_CONFIG_JSON`` BEFORE ``JULY_HOLIDAY_SEARCH_CONFIG_JSON``. Nothing in a
    July run therefore knew it was a July run: handing it the December secret produced a
    perfectly valid December report, emailed on the July schedule, with only ``config_source``
    in a log line to say so. The season is derived from the signals the history-file choice
    already used - the report title and the departure dates - so the two can never disagree.
    """
    title = str(getattr(config, "report_title", "") or "").lower()
    dates = [str(day) for day in (getattr(config, "outbound_dates", ()) or ())]
    july = "july" in title or any("-07-" in day for day in dates)
    december = "december" in title or any("-12-" in day for day in dates)
    if july and not december:
        return "july"
    if december and not july:
        return "december"
    # A name-and-date conflict is not a season we can vouch for: say so rather than pick.
    return "unknown"


def _write_step_summary(result: dict) -> None:
    """Put the four facts that change what was emailed onto the run page.

    ``config_source`` lives in the result JSON, which lives in the log, so a run priced by
    the wrong config or with no live fares was invisible to anyone who did not go digging.
    GitHub provides the file this writes to; anywhere else this is a no-op.
    """
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    season = result.get("config_season") or "unknown"
    mismatch = bool(result.get("config_season_mismatch"))
    rows = [
        ("Config used", result.get("config_source") or "(none)"),
        ("Season this config prices", season + ("  ⚠️ MISMATCH" if mismatch else "")),
        ("Deals / destinations", f"{result.get('deal_count', 0)} / {result.get('destination_count', 0)}"),
        ("Live fares used",
         f"{result.get('live_flight_airports', 0)} airports "
         f"(stale cache: {result.get('stale_flight_airports', 0)}, "
         f"aged out: {result.get('live_evidence_age_hours')}h)"),
        ("Hotel rates used",
         f"{result.get('hotel_rates_priced_cards', 0)} cards priced from "
         f"{result.get('hotel_rate_properties', 0)} read properties"),
        ("Email sent", "yes" if result.get("email_sent") else
         f"no ({result.get('email_skipped_reason') or result.get('email_cooldown_reason') or 'no change'})"),
    ]
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("### Holiday planner run\n\n| Field | Value |\n|---|---|\n")
            for key, value in rows:
                handle.write(f"| {key} | {value} |\n")
            handle.write("\n")
    except OSError:
        return


def run_holiday_planner(
    *,
    dry_run: bool,
    force_send: bool = False,
    config_path: str = "",
    expect_season: str = "",
    hotel_evidence_path: str = "",
    live_evidence_path: str = "",
    package_evidence_path: str = "",
) -> dict[str, int | bool]:
    # WHICH CONFIG THIS RUN USED belongs in the result, not in an operator's
    # guess. Five shapes reach this function — an explicit --config path, two
    # env secrets, an env path, then a committed fallback file — and they
    # price different holidays. On 2026-09-24 the July workflow bound an
    # empty env var of a name that does not exist over the real secret, so
    # the scheduled run silently priced the committed fallback: a valid
    # report, about the right dates, emailed, with nothing in the summary to
    # say which config produced it.
    payload = ""
    config_source = ""
    if config_path:
        # An explicit path that does not exist is operator error, never a
        # reason to fall through to a different holiday. `evidence-contract`
        # already fails fast on this exact mistake (a misspelt July path
        # printed a valid December contract and exited 0); the job had the
        # same hole one layer down.
        if not os.path.exists(config_path):
            raise SystemExit(f"--config path does not exist: {config_path}")
        with open(config_path, encoding="utf-8") as handle:
            payload = handle.read()
        if payload:
            config_source = f"config-path:{config_path}"
    if not payload:
        for env_name in (
            "HOLIDAY_SEARCH_CONFIG_JSON",
            "JULY_HOLIDAY_SEARCH_CONFIG_JSON",
        ):
            if os.environ.get(env_name):
                payload = os.environ[env_name]
                config_source = f"env:{env_name}"
                break
    if not payload and os.environ.get("HOLIDAY_CONFIG_PATH"):
        cpath = os.environ["HOLIDAY_CONFIG_PATH"]
        if os.path.exists(cpath):
            with open(cpath, encoding="utf-8") as handle:
                payload = handle.read()
            if payload:
                config_source = f"env:HOLIDAY_CONFIG_PATH={cpath}"
    if not payload:
        dec_example = Path(__file__).parents[2] / "examples" / "dec_holiday_config.json"
        if dec_example.exists():
            payload = dec_example.read_text(encoding="utf-8")
            if payload:
                config_source = f"fallback-file:{dec_example.name}"

    config = load_holiday_config(payload)
    from . import live_verify

    evidence_path = _evidence_path(
        live_evidence_path,
        "HOLIDAY_LIVE_EVIDENCE_PATH",
        _live_evidence_default_path(),
    )
    # Bounded live flight injection (GHA-safe HTTP only, no browser).
    live_offers: dict[tuple[str, ...], object] = {}
    live_attempted = False
    live_skipped: list[str] = []
    during_live_error: Optional[str] = None
    try:
        live_attempted = True
        live_offers = dict(
            live_verify.try_live_flight_offers(config, path=evidence_path)
        )
        live_skipped = live_verify.consume_skip_log()
    except Exception as exc:
        # Never silent: an empty mapping and a crashed seam look identical in
        # the result JSON, and the difference matters (a crash means the
        # numbers below describe nothing, not "no evidence yet").
        live_offers = {}
        during_live_error = f"{type(exc).__name__}: {exc}"
        live_skipped = [f"live-evidence load failed: {during_live_error}"]
        print(
            f"live-evidence: load failed: {during_live_error}", file=sys.stderr
        )
    # HOTEL EVIDENCE (owner brief 2026-10-03, H3): the same seam for the stay.
    # The workflow seeds `hotel-evidence.json` from the private repo before
    # this job runs, so a run with no file simply keeps the catalogue rates.
    from . import hotel_evidence as hotel_evidence_module

    hotel_evidence_path = _evidence_path(
        hotel_evidence_path, "HOLIDAY_HOTEL_EVIDENCE_PATH",
        hotel_evidence_module.DEFAULT_HOTEL_EVIDENCE_PATH,
    )
    hotel_rates: dict[tuple[str, str, str], object] = {}
    hotel_skipped: list[str] = []
    hotel_evidence_error: Optional[str] = None
    try:
        hotel_rates = dict(
            hotel_evidence_module.load_hotel_evidence(
                config, path=hotel_evidence_path, now=datetime.now(timezone.utc).isoformat()
            )
        )
        hotel_skipped = hotel_evidence_module.consume_hotel_skip_log()
    except Exception as exc:
        hotel_rates = {}
        hotel_evidence_error = f"{type(exc).__name__}: {exc}"
        hotel_skipped = [f"hotel-evidence load failed: {hotel_evidence_error}"]
        print(
            f"hotel-evidence: load failed: {hotel_evidence_error}", file=sys.stderr
        )
    # OPERATOR PACKAGE PRICES (owner brief 2026-10-04, WP4d D1): the third
    # evidence seam, loaded where the other two are, with its path pinned at the
    # call site, the same clock, and the same "a missing file changes nothing
    # else about the run" rule. It rides the card as information; it never
    # prices, ranks or filters anything.
    from . import package_evidence as package_evidence_module

    resolved_package_path = _evidence_path(
        package_evidence_path, "HOLIDAY_PACKAGE_EVIDENCE_PATH",
        package_evidence_module.DEFAULT_PACKAGE_EVIDENCE_PATH,
    )
    package_prices: dict[tuple[str, str, str, str], object] = {}
    package_skipped: list[str] = []
    package_evidence_error: Optional[str] = None
    package_file_found = False
    package_newest_observed_at = ""
    try:
        package_file_found = os.path.exists(resolved_package_path)
        package_prices = dict(
            package_evidence_module.load_package_evidence(
                config, path=resolved_package_path,
                now=datetime.now(timezone.utc).isoformat(),
            )
        )
        package_skipped = package_evidence_module.consume_package_skip_log()
        for entry in package_prices.values():
            stamp = str(getattr(entry, "observed_at", "") or "")
            if stamp > package_newest_observed_at:
                package_newest_observed_at = stamp
    except Exception as exc:
        package_prices = {}
        package_evidence_error = f"{type(exc).__name__}: {exc}"
        package_skipped = [f"package-evidence load failed: {package_evidence_error}"]
        print(
            f"package-evidence: load failed: {package_evidence_error}", file=sys.stderr
        )
    # CONSUMPTION CONTRACT (2026-09-23): the report prices ONE date pair from
    # ONE origin for a specific set of (airport, cabin) keys, and the private
    # hunt has no other way to learn that set. Before this was recorded, 125
    # harvested records priced 8 December cards: six crawled airports had no
    # card at all while two card airports (ACE, PFO) were never crawled. The
    # contract is emitted here and by `evidence-contract` so the next hunt is
    # aimed from data. Missing keys are what to crawl; unused keys are waste.
    contract = None
    gaps: dict[str, list[str]] = {"missing": [], "unused": []}
    freshness = {
        "record_count": 0,
        "newest_observed_at": None,
        "age_hours": None,
        "stale": True,
        "future_dated": 0,
    }
    contract_error: Optional[str] = None
    try:
        contract = live_verify.evidence_consumption_contract(config)
        gaps = live_verify.evidence_contract_gaps(config, live_offers)
        freshness = live_verify.evidence_freshness(evidence_path)
    except Exception as exc:
        # The fallback shape is deliberately identical to a genuinely missing
        # cache, so it MUST be labelled: without this an operator re-runs a
        # hunt to "refresh" a cache that was never stale, and the contract
        # silently disappears from the summary on exactly the runs that need
        # it. Report the cause rather than swallowing it.
        contract, gaps = None, {"missing": [], "unused": []}
        contract_error = f"{type(exc).__name__}: {exc}"
        print(f"live-evidence: contract failed: {contract_error}", file=sys.stderr)
    deals = collect_holiday_deals(
        config, max_budget_gbp=config.max_budget_gbp,
        live_flight_offers=live_offers or None,
        hotel_evidence=hotel_rates or None,
        package_evidence=package_prices or None,
    )
    # MEMORY BEFORE BUILD: the workflow seeds `history_path` from the
    # private repo in a dedicated bash step (proven transport) BEFORE this
    # job runs, so trends, chips and the change digest describe real
    # movement instead of 'first time tracked'. Dry runs ignore memory
    # entirely (a dry run must reflect a fresh build, never prior state).
    season = config_season(config)
    # REFUSE TO SEND THE WRONG HOLIDAY. A mismatch here means the operator's own secret was not
    # the one in force (the generic name wins over the July one) or a --config path pointed at
    # the other season. Either way the report is real, about the right dates, and about the
    # wrong trip - so it does not go out, and the reason is in the result rather than inferred.
    season_mismatch = bool(expect_season) and season not in (expect_season, "unknown")
    season_mismatch_reason = (
        f"this is the {expect_season} planner but the config prices {season} ({config_source})"
        if season_mismatch else ""
    )
    if season_mismatch_reason:
        print(f"refusing to send: {season_mismatch_reason}", file=sys.stderr)
    is_july = season == "july"
    default_history_name = "july_holiday_price_history.jsonl" if is_july else "holiday_price_history.jsonl"
    history_path = Path(
        os.environ.get("HOLIDAY_HISTORY_PATH", f"data/{default_history_name}")
    )
    seeded_rows = 0 if dry_run else len(read_history(path=history_path))
    # Trends are computed BEFORE today's observation is appended, so the
    # chips always compare against prior runs only.
    trends = summarize_trends(deals, path=history_path)
    digest = build_change_digest(trends, path=history_path)
    detailed = _report_style() == DETAILED_REPORT_STYLE
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    render_kwargs: dict = {
        "generated_at": generated_at,
        "deals": deals,
        "history_chips": render_history_html(trends),
        "change_digest_html": render_change_digest_html(digest),
    }
    if not detailed:
        # Movement has to be stated in words against the LAST observation, so
        # the compact renderer is given the trend rows themselves rather than
        # the rendered chips (AMEND-H1 §2).
        render_kwargs.update(
            trends=trends,
            digest=digest,
            last_report_at=str(digest.get("last_report_at") or ""),
        )
    render = render_holiday_report if detailed else render_holiday_report_compact
    html = render(config, **render_kwargs)
    # The plain-text part the mailer already sends used to say "open this in an
    # HTML-capable client", which carried none of the decision; it now mirrors
    # the HTML in the same order with the same numbers.
    text = (
        ""
        if detailed
        else render_holiday_report_compact_text(config, **render_kwargs)
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
    # HOLIDAY_SEND_EVERY_RUN: the owner wants every scheduled run mailed so
    # the price history is read 3x a week, flat or not. Dry runs still never send.
    send_every_run = os.environ.get("HOLIDAY_SEND_EVERY_RUN", "").strip().lower() in (
        "1", "true", "yes",
    )
    send_email = (not dry_run) and (
        bool(force_send)
        or send_every_run
        or not digest["has_prior"]
        or bool(digest["drops"])
        or bool(digest["rises"])
        or bool(digest["new"])
        # Composite-ranking movement is reader-worthy even when benchmarks
        # are price-quiet: "your best-value pick changed" justifies the send.
        or bool(digest.get("value_changes"))
    )
    # SEND COOLDOWN (2026-09-22: 3 near-identical emails in 35 minutes while
    # hunt batches landed): a reader-worthy change no longer sends if the
    # last email went out less than HOLIDAY_EMAIL_COOLDOWN_MINUTES ago
    # (default 180). force_send still overrides; dry runs never reach here.
    cooldown_minutes = float(os.environ.get("HOLIDAY_EMAIL_COOLDOWN_MINUTES", "180"))
    cooldown_reason = ""
    if send_email and not force_send and last_prior and cooldown_minutes > 0:
        try:
            last_dt = datetime.fromisoformat(last_prior.replace("Z", "+00:00"))
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            age_minutes = (datetime.now(timezone.utc) - last_dt).total_seconds() / 60.0
            if age_minutes < cooldown_minutes:
                send_email = False
                cooldown_reason = (
                    f"last email {age_minutes:.0f}m ago < {cooldown_minutes:.0f}m cooldown"
                )
        except ValueError:
            pass  # unparseable timestamp: never suppress on bad data
    if cooldown_reason:
        print(f"email suppressed by cooldown: {cooldown_reason}")
    default_subject = "July Summer Luxury Holiday Watch" if is_july else "December Holiday Package Watch"
    subject = os.environ.get("HOLIDAY_EMAIL_SUBJECT") or default_subject
    if season_mismatch:
        # Last, so it outranks every other send decision: a forced send is still the wrong
        # holiday, and the cooldown is not the reason it was suppressed.
        send_email = False
    if send_email:
        send_html(subject, html, text=text)
    date_combination_count = len(_date_pairs(config))
    result = {
        # Which config priced this report. A fallback or a legacy env name
        # here means the operator's own secret is not the one in force.
        "config_source": config_source,
        # Which holiday that config actually prices, so a July run cannot quietly report on
        # December without saying so.
        "config_season": season,
        "config_season_mismatch": season_mismatch,
        "email_skipped_reason": season_mismatch_reason,
        "destination_count": len(config.destinations),
        "date_combination_count": date_combination_count,
        # Exact rendered-link count: Jet2 is omitted where it has no product.
        "provider_entry_count": count_provider_entries(config),
        "deal_count": len(deals),
        # Far East destination watches (benchmark, unverified) leading the report.
        "far_east_watch_count": len(far_east_watch_rows(config)),
        # (airport, cabin) keys, not airports: three cabins with fares for
        # AYT alone is ONE airport, and the label has to mean what it says.
        **_live_evidence_counts(live_offers),
        "live_attempted": live_attempted,
        # On the path the RUN used, not on a path re-derived from the
        # environment. It used to re-read the env var and the default here,
        # so a run pointed at one file reported on another: the summary could
        # say the export was found while the evidence came from nowhere, or
        # the reverse. A flag that describes a file this run never opened is
        # worse than no flag.
        "live_evidence_file_found": os.path.exists(evidence_path),
        "live_skipped": live_skipped,
        # The contract, the gap it leaves and how old the cache is. A run that
        # silently reverts to benchmarks should be visibly a stale-cache run.
        "live_evidence_contract": contract.as_dict() if contract else {},
        "live_evidence_missing_keys": gaps["missing"],
        "live_evidence_unused_keys": gaps["unused"],
        "live_evidence_record_count": freshness["record_count"],
        "live_evidence_newest_observed_at": freshness["newest_observed_at"],
        "live_evidence_age_hours": freshness["age_hours"],
        "live_evidence_stale": freshness["stale"],
        "live_evidence_future_dated": freshness["future_dated"],
        # Non-null means the seam itself failed, so every live-evidence field
        # above is a fallback shape rather than a measurement.
        "live_evidence_contract_error": contract_error,
        "live_evidence_load_error": during_live_error,
        # Hotel evidence: what actually priced a stay, and what was refused.
        # An operator who sees a catalogue rate needs to know whether a rate
        # was loaded and rejected, or simply never collected.
        "hotel_evidence_file_found": os.path.exists(hotel_evidence_path),
        "hotel_rate_properties": len(
            {key[0] for key in hotel_rates}
        ),
        "hotel_rates_priced_cards": sum(
            1 for deal in deals if deal.hotel_evidence is not None
        ),
        "hotel_evidence_skipped": hotel_skipped,
        "hotel_evidence_load_error": hotel_evidence_error,
        # Operator package prices (WP4d D1). The same question as the two seams
        # above, and it matters more here: `package_prices_on_cards` counts the
        # cards that actually show a package, so a non-zero `package_evidence_
        # record count` with zero on cards means the export describes resorts
        # this report does not price - which is waste the hunt can be aimed away
        # from, the same class of finding the consumption contract exists for.
        "package_evidence_file_found": package_file_found,
        "package_evidence_newest_observed_at": package_newest_observed_at or None,
        "package_prices_on_cards": sum(
            1 for deal in deals if deal.operator_package is not None
        ),
        "package_evidence_skipped": package_skipped,
        "package_evidence_load_error": package_evidence_error,
        "history_observations_appended": appended,
        "history_seeded_rows": seeded_rows,
        "send_skipped_no_change": (not dry_run) and not send_email,
        "last_prior_observation": last_prior,
        "email_sent": send_email,
        "email_cooldown_reason": cooldown_reason,
    }
    print(json.dumps(result, sort_keys=True))
    _write_step_summary(result)
    return result
