"""Holiday price history persistence.

Append-only JSONL store so the 3x-week GHA holiday planner can track
historical prices across runs. Commit-friendly: one JSON object per line,
stable field order, cheap to diff and append in a commit-back step.

Complements the SQLite fare-history store (history_db.py), which stays
migration-only for flight fare observations; this module tracks the
package-holiday dimension (resort x dates) instead.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

HISTORY_DEFAULT_PATH = Path("data/holiday_price_history.jsonl")

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"run-{stamp}-{os.getpid()}"


def _fingerprint(resort: str, dest_key: str, outbound: str, return_: str, unit: str = "") -> str:
    # `unit` (room architecture) is part of the identity: quoting a 2-bed
    # family suite is NOT the same product as 3 separate rooms, and their
    # price histories must stay separate series.
    raw = f"{resort}|{dest_key}|{outbound}|{return_}|{unit}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _deal_fingerprint(deal: Any) -> str:
    return _fingerprint(
        str(getattr(deal, "resort_name", "")),
        str(getattr(deal, "destination_key", "")),
        str(getattr(deal, "outbound_date", "")),
        str(getattr(deal, "return_date", "")),
        str(getattr(deal, "unit_architecture", "")),
    )


def append_history(
    deals: Iterable[Any],
    *,
    path: Optional[Path] = None,
    live_airports: Optional[int] = None,
) -> int:
    """Append one observation line per deal. Returns count appended.

    Never raises: history must not break email delivery. Corrupt prior
    lines are preserved verbatim.
    """
    out_path = Path(path) if path else HISTORY_DEFAULT_PATH
    rows: List[Dict[str, Any]] = []
    run_id = _run_id()
    now = _utc_now_iso()
    today = now[:10]
    try:
        for d in deals:
            total = float(getattr(d, "total_package_price_gbp", 0.0))
            if not math.isfinite(total):
                logger.warning("Skipping history row with non-finite price: %r", d)
                continue
            rows.append(
                {
                    "fingerprint": _deal_fingerprint(d),
                    "resort_name": str(getattr(d, "resort_name", "")),
                    "destination_key": str(getattr(d, "destination_key", "")),
                    "destination_label": str(getattr(d, "destination_label", "")),
                    "outbound_date": str(getattr(d, "outbound_date", "")),
                    "return_date": str(getattr(d, "return_date", "")),
                    "nights": getattr(d, "nights", 0),
                    "unit_architecture": str(getattr(d, "unit_architecture", "")),
                    "total_package_price_gbp": total,
                    "price_per_person_gbp": float(getattr(d, "price_per_person_gbp", 0.0)),
                    "flight_price_total_gbp": float(getattr(d, "flight_price_total_gbp", 0.0)),
                    "hotel_price_total_gbp": float(getattr(d, "hotel_price_total_gbp", 0.0)),
                    "true_d2d_gbp": float(getattr(d, "true_d2d_gbp", 0.0)),
                    "confidence": str(getattr(d, "confidence", "")),
                    # "verified-exact-date" confidence IS the codebase's
                    # signal for live evidence (see holidays.py live_used).
                    "live_used": str(getattr(d, "confidence", "")) == "verified-exact-date",
                    "value_score": float(getattr(d, "value_score", 0.0) or 0.0),
                    "rank_value": int(getattr(d, "rank_value", 0) or 0),
                    "observed_at": now,
                    "run_id": run_id,
                }
            )
    except Exception:
        logger.exception("Failed building history rows; appending none")
        return 0
    if not rows:
        return 0
    # Day-level idempotency: at most one observation per resort+dates per
    # UTC day, so job retries / manual re-runs never inflate the trend stats.
    seen: set = set()
    try:
        for row in read_history(path=out_path):
            seen.add((row.get("fingerprint"), str(row.get("observed_at", ""))[:10]))
    except Exception:
        logger.exception("Could not read existing history for dedupe; appending without dedupe")
    rows = [r for r in rows if (r["fingerprint"], r["observed_at"][:10]) not in seen]
    if not rows:
        return 0
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "a", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, sort_keys=True) + "\n")
        return len(rows)
    except OSError:
        # History is best-effort: delivery must never depend on it.
        logger.exception("Could not write history file %s", out_path)
        return 0


def read_history(
    *,
    path: Optional[Path] = None,
    fingerprint: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Read observations (oldest-first). Skips corrupt lines silently.

    With ``limit``, returns the most recent ``limit`` lines still in
    oldest-first order.
    """
    in_path = Path(path) if path else HISTORY_DEFAULT_PATH
    if not in_path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        with open(in_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if fingerprint is not None and row.get("fingerprint") != fingerprint:
                    continue
                rows.append(row)
    except OSError:
        return []
    if limit is not None and len(rows) > limit:
        rows = rows[-limit:]
    return rows


def summarize_trends(
    deals: Iterable[Any],
    *,
    path: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Per-deal trend summary vs history (prior runs only).

    Returns rows aligned with input order, each carrying prior-min/max and
    delta so the report can show movement vs the cheapest-ever price.
    """
    out: List[Dict[str, Any]] = []
    deal_list = list(deals)
    try:
        history = read_history(path=path)
    except Exception:
        history = []
    by_fp: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in history:
        fp = str(row.get("fingerprint", ""))
        if fp:
            by_fp[fp].append(row)

    for d in deal_list:
        fp = _deal_fingerprint(d)
        current = float(getattr(d, "total_package_price_gbp", 0.0))
        prior = by_fp.get(fp, [])
        if prior:
            min_price = min(float(r.get("total_package_price_gbp", 0.0)) for r in prior)
            max_price = max(float(r.get("total_package_price_gbp", 0.0)) for r in prior)
            obs_count = len(prior)
            last_price = float(prior[-1].get("total_package_price_gbp", 0.0))
            last_rank = int(prior[-1].get("rank_value", 0) or 0)
            last_score = float(prior[-1].get("value_score", 0.0) or 0.0)
        else:
            min_price = max_price = 0.0
            obs_count = 0
            last_price = None
            last_rank = None
            last_score = None
        current_rank = int(getattr(d, "rank_value", 0) or 0)
        current_score = float(getattr(d, "value_score", 0.0) or 0.0)
        out.append(
            {
                "fingerprint": fp,
                "resort_name": str(getattr(d, "resort_name", "")),
                "current": current,
                "prior_min": min_price if prior else None,
                "prior_max": max_price if prior else None,
                "prior_last": last_price,
                "delta_vs_min": (current - min_price) if prior else None,
                "delta_vs_last": (current - last_price) if prior else None,
                "prior_observations": obs_count,
                # Value-score rank movement vs the last observation. Zero
                # ranks (legacy rows / unregistered resorts) compare as None
                # rather than a fake +/- movement.
                "current_value_score": current_score,
                "prior_value_score": last_score,
                "score_delta": (round(current_score - last_score, 1) if (last_score is not None) else None),
                "current_rank": current_rank,
                "prior_rank": last_rank if last_rank else None,
                "rank_delta": (
                    (last_rank - current_rank)
                    if (last_rank and current_rank)
                    else None
                ),
            }
        )
    return out


def build_change_digest(
    trends: List[Dict[str, Any]],
    *,
    path: Optional[Path] = None,
) -> Dict[str, Any]:
    """What changed since the last report: drops, rises, new resorts.

    Compares each deal's current price against its LAST observation (the
    previous report's number), not the cheapest-ever. ``has_prior`` is
    False until at least one deal has any history — the first run has
    nothing to compare and the digest says so by being empty.
    """
    drops: List[Dict[str, Any]] = []
    rises: List[Dict[str, Any]] = []
    new: List[str] = []
    value_changes: List[Dict[str, Any]] = []
    unchanged = 0
    has_prior = False
    for t in trends:
        if t.get("prior_observations"):
            has_prior = True
        rank_delta = t.get("rank_delta")
        if rank_delta and t.get("prior_rank"):
            value_changes.append(
                {
                    "name": str(t.get("resort_name", "")),
                    "current_rank": int(t.get("current_rank", 0) or 0),
                    "prior_rank": int(t.get("prior_rank", 0) or 0),
                    "delta": int(rank_delta),
                }
            )
        prev = t.get("prior_last")
        if prev is None:
            new.append(str(t.get("resort_name", "")))
            continue
        delta = float(t.get("current", 0.0)) - float(prev)
        if delta <= -0.01:
            drops.append({"name": str(t.get("resort_name", "")), "current": float(t.get("current", 0.0)), "prev": float(prev), "delta": delta})
        elif delta >= 0.01:
            rises.append({"name": str(t.get("resort_name", "")), "current": float(t.get("current", 0.0)), "prev": float(prev), "delta": delta})
        else:
            unchanged += 1
    return {
        "has_prior": has_prior,
        "drops": drops,
        "rises": rises,
        "new": new,
        "value_changes": value_changes,
        "unchanged": unchanged,
        "last_report_at": last_history_observation(path=path),
    }


_LAST_AT_RE = re.compile(r'"observed_at": "([^"]+)"')


def last_history_observation(*, path: Optional[Path] = None) -> str:
    """Timestamp of the most recent observation in history ('' if none).

    Reads the tail of the file only — cheap even as history grows.
    """
    in_path = Path(path) if path else HISTORY_DEFAULT_PATH
    if not in_path.exists():
        return ""
    try:
        with open(in_path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 4096))
            tail = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
    stamps = _LAST_AT_RE.findall(tail)
    return stamps[-1] if stamps else ""


def render_change_digest_html(digest: Dict[str, Any]) -> str:
    """One compact strip: what changed since the last report. Empty when
    there is no prior data (first run) — never a wall of noise."""
    if not digest.get("has_prior"):
        return ""
    parts: List[str] = []
    for d in digest.get("drops", []):
        parts.append(
            '<span style="background:#dcfce7;color:#166534;padding:3px 10px;border-radius:9999px;font-size:13px;font-weight:700;">&#9660; '
            + escape(d["name"])
            + " £"
            + f"{abs(d['delta']):,.0f} cheaper</span>"
        )
    for d in digest.get("rises", []):
        parts.append(
            '<span style="background:#fee2e2;color:#991b1b;padding:3px 10px;border-radius:9999px;font-size:13px;font-weight:700;">&#9650; '
            + escape(d["name"])
            + " £"
            + f"{d['delta']:,.0f} pricier</span>"
        )
    for name in digest.get("new", []):
        parts.append(
            '<span style="background:#dbeafe;color:#1d4ed8;padding:3px 10px;border-radius:9999px;font-size:13px;font-weight:700;">✦ '
            + escape(name)
            + " new</span>"
        )
    for v in digest.get("value_changes", []):
        arrow = "&#9650;" if int(v["delta"]) > 0 else "&#9660;"
        bg, fg = ("#dbeafe", "#1d4ed8") if int(v["delta"]) > 0 else ("#fef3c7", "#92400e")
        parts.append(
            '<span style="background:' + bg + ";color:" + fg
            + ';padding:3px 10px;border-radius:9999px;font-size:13px;font-weight:700;">'
            + arrow + " "
            + escape(v["name"])
            + f" value rank {v['current_rank']} (was {v['prior_rank']})</span>"
        )
    unchanged = int(digest.get("unchanged", 0))
    if unchanged and parts:
        parts.append(
            '<span style="color:#64748b;font-size:13px;">'
            + str(unchanged)
            + " unchanged</span>"
        )
    stamp = str(digest.get("last_report_at") or "")
    when = ""
    if stamp:
        when = (
            '<span style="color:#94a3b8;font-size:13px;">vs last report '
            + escape(stamp[:16].replace("T", " "))
            + " UTC</span>"
        )
    if not parts:
        return (
            '<p style="margin:0 0 14px 0; color:#64748b; font-size:14px;">'
            "No price movement since the last report — every tracked resort is at its previous price. "
            + when
            + "</p>"
        )
    parts.append(when)
    return (
        '<div style="margin:0 0 14px 0; line-height:2;">'
        + " ".join(parts)
        + "</div>"
    )


def render_history_html(trends: List[Dict[str, Any]]) -> List[str]:
    """Compact HTML snippets (per deal, input order) for the email report."""
    snippets: List[str] = []
    for t in trends:
        if not t.get("prior_observations"):
            snippets.append(
                '<span style="color:#64748b;font-size:12px;">first time tracked</span>'
            )
            continue
        delta = t.get("delta_vs_min")
        obs = t["prior_observations"]
        if delta is None:
            snippets.append("")
            continue
        if delta <= -0.01:
            chip = (
                '<span style="background:#dcfce7;color:#166534;'
                'padding:1px 8px;border-radius:9999px;font-size:12px;">'
                f"&pound;{abs(delta):.2f} below tracked min</span>"
            )
        elif delta >= 0.01:
            chip = (
                '<span style="background:#fee2e2;color:#991b1b;'
                'padding:1px 8px;border-radius:9999px;font-size:12px;">'
                f"&pound;{delta:.2f} above tracked min</span>"
            )
        else:
            chip = (
                '<span style="background:#e2e8f0;color:#334155;'
                'padding:1px 8px;border-radius:9999px;font-size:12px;">'
                "at tracked min</span>"
            )
        snippets.append(
            f'<span style="color:#64748b;font-size:12px;">{obs} obs &middot; min &pound;{t["prior_min"]:.2f}</span> {chip}'
        )
        # Value-rank movement chip: only when both ranks are known and the
        # composite ranking actually moved. Price-quiet runs still surface
        # "your best-value pick changed" — the movement that matters when
        # benchmarks are static.
        rank_delta = t.get("rank_delta")
        if rank_delta:
            if rank_delta > 0:
                rank_chip = (
                    '<span style="background:#dbeafe;color:#1d4ed8;'
                    'padding:1px 8px;border-radius:9999px;font-size:12px;">'
                    f"&#9650; value rank {t['current_rank']} (was {t['prior_rank']})</span>"
                )
            else:
                rank_chip = (
                    '<span style="background:#fef3c7;color:#92400e;'
                    'padding:1px 8px;border-radius:9999px;font-size:12px;">'
                    f"&#9660; value rank {t['current_rank']} (was {t['prior_rank']})</span>"
                )
            snippets[-1] = snippets[-1] + " " + rank_chip
    return snippets
