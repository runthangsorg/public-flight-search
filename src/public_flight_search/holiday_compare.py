"""Holiday deal-delta analysis over the append-only price history.

When a new report lands and a number moved, the reader has one question:
*is this real?* This module answers it from the history alone, in four
honest buckets:

* **Exact price drop** — the SAME product (resort, dates, duration, room,
  cabin, board) is now cheaper than its previous observation.
* **Comparable new low** — the same resort and board are cheaper than any
  like-for-like prior, but the dates/duration/room differ.
* **False price drop** — a lower total that is *only* lower because the
  holiday is shorter, the board is lower, the room architecture changed, a
  live fare became a benchmark, or a transfer disappeared.
* **New deal** — no identical package was ever tracked, and the price per
  person per night is materially below the resort's previous comparables.

Everything here is pure: rows in, report out. No network, no browser, no
clock. A figure is never called a reduction unless the evidence in the row
supports it, and every cross-duration comparison is stated in
**price per person per night** (pppn), the only comparator that is honest
about a 6-night holiday being cheaper than an 8-night one simply because
it is shorter.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Classification vocabulary
# ---------------------------------------------------------------------------

EXACT_DROP = "exact_drop"
NO_CHANGE = "no_change"
PRICE_RISE = "price_rise"
COMPARABLE_NEW_LOW = "comparable_new_low"
NEW_DEAL = "new_deal"
NEW_TRACKED = "new_tracked"
#: Cheaper than a prior, but only because the product was downgraded — the
#: Table 4 material. Never rendered as a reduction.
DOWNGRADED = "downgraded"

#: A saving is significant at any of these thresholds (the reader's brief).
SIGNIFICANT_TOTAL_GBP = 250.0
SIGNIFICANT_PER_PERSON_GBP = 50.0
SIGNIFICANT_PPPN_PCT = 5.0

#: Price-per-person-per-night must be this much lower to count as a
#: "materially" cheaper comparable/new deal.
MATERIAL_PPPN_DROP_PCT = 5.0

#: Board bases, richest last. Used only to detect a DOWNGRADE; an
#: unrecognised label returns ``None`` and never triggers one.
_BOARD_LADDER: Tuple[Tuple[str, int], ...] = (
    ("room only", 0),
    ("self catering", 0),
    ("self-catering", 0),
    ("bed & breakfast", 1),
    ("bed and breakfast", 1),
    ("half board", 2),
    ("half-board", 2),
    ("full board", 3),
    ("full-board", 3),
    ("all inclusive plus", 5),
    ("ultra all inclusive", 6),
    ("all inclusive", 4),
)

def board_rank(board: str) -> Optional[int]:
    """Rank a board basis, richest highest, or ``None`` when unrecognised."""
    text = (board or "").strip().lower()
    if not text:
        return None
    # Longest match first so "all inclusive plus" never reads as
    # "all inclusive" and "half board" never reads as plain "board".
    for label, rank in sorted(_BOARD_LADDER, key=lambda pair: -len(pair[0])):
        if label in text:
            return rank
    return None


# ---------------------------------------------------------------------------
# Observation
# ---------------------------------------------------------------------------

def _as_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if number == number else 0.0  # NaN -> 0.0 safely


@dataclass(frozen=True)
class Observation:
    """One history row, read defensively (legacy rows lack newer fields)."""

    fingerprint: str
    resort_name: str
    destination_key: str
    destination_label: str
    outbound_date: str
    return_date: str
    nights: int
    unit_architecture: str
    cabin_class: str
    board_basis: str
    total_gbp: float
    price_per_person_gbp: float
    flight_gbp: float
    hotel_gbp: float
    true_d2d_gbp: float
    confidence: str
    live_used: bool
    value_score: float
    rank_value: int
    transfer_gbp: float
    uk_ground_gbp: float
    observed_at: str
    run_id: str

    @property
    def price_per_person_per_night(self) -> float:
        """The honest cross-duration comparator.

        Prefers the recorded per-person figure (it already reflects the
        real party size); only falls back to the whole total when the row
        predates that field, and labels the result the same either way.
        """
        nights = self.nights or 0
        if nights <= 0:
            return 0.0
        per_person = self.price_per_person_gbp or 0.0
        if per_person <= 0:
            return round(self.total_gbp / nights, 2)
        return round(per_person / nights, 2)

    @property
    def label(self) -> str:
        parts = [self.resort_name or "unknown resort"]
        if self.nights:
            parts.append(f"{self.nights}n")
        if self.outbound_date:
            parts.append(self.outbound_date)
        if self.cabin_class:
            parts.append(self.cabin_class.lower())
        return " · ".join(parts)


def observation_from_row(row: Dict[str, Any]) -> Observation:
    return Observation(
        fingerprint=str(row.get("fingerprint", "")),
        resort_name=str(row.get("resort_name", "")),
        destination_key=str(row.get("destination_key", "")),
        destination_label=str(row.get("destination_label", "")),
        outbound_date=str(row.get("outbound_date", "")),
        return_date=str(row.get("return_date", "")),
        nights=int(row.get("nights", 0) or 0),
        unit_architecture=str(row.get("unit_architecture", "")),
        cabin_class=str(row.get("cabin_class", "ECONOMY") or "ECONOMY"),
        board_basis=str(row.get("board_basis", "")),
        total_gbp=_as_float(row.get("total_package_price_gbp")),
        price_per_person_gbp=_as_float(row.get("price_per_person_gbp")),
        flight_gbp=_as_float(row.get("flight_price_total_gbp")),
        hotel_gbp=_as_float(row.get("hotel_price_total_gbp")),
        true_d2d_gbp=_as_float(row.get("true_d2d_gbp")),
        confidence=str(row.get("confidence", "")),
        live_used=bool(row.get("live_used", False)),
        value_score=_as_float(row.get("value_score")),
        rank_value=int(row.get("rank_value", 0) or 0),
        transfer_gbp=_as_float(row.get("transfer_gbp")),
        uk_ground_gbp=_as_float(row.get("uk_ground_gbp")),
        observed_at=str(row.get("observed_at", "")),
        run_id=str(row.get("run_id", "")),
    )


def load_observations(path: Path) -> List[Observation]:
    """Read every observation in a JSONL history file (oldest first)."""
    if not path.exists():
        return []
    rows: List[Observation] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                rows.append(observation_from_row(payload))
    return rows


def latest_per_fingerprint(observations: Iterable[Observation]) -> List[Observation]:
    """The newest observation of each distinct product, oldest-first by date."""
    newest: Dict[str, Observation] = {}
    for obs in observations:
        current = newest.get(obs.fingerprint)
        if current is None or obs.observed_at >= current.observed_at:
            newest[obs.fingerprint] = obs
    return sorted(newest.values(), key=lambda o: (o.observed_at, o.fingerprint))


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Classification:
    kind: str
    observation: Observation
    prior: Optional[Observation]
    saving_gbp: float
    saving_per_person_gbp: float
    saving_pppn_pct: float
    reasons: Tuple[str, ...] = ()

    @property
    def significant(self) -> bool:
        return (
            self.saving_gbp > SIGNIFICANT_TOTAL_GBP
            or self.saving_per_person_gbp > SIGNIFICANT_PER_PERSON_GBP
            or self.saving_pppn_pct > SIGNIFICANT_PPPN_PCT
        )


def _saving_metrics(current: Observation, prior: Observation) -> Tuple[float, float, float]:
    saving = round(prior.total_gbp - current.total_gbp, 2)
    per_person = round(prior.price_per_person_gbp - current.price_per_person_gbp, 2)
    prior_pppn = prior.price_per_person_per_night
    pct = 0.0
    if prior_pppn > 0:
        pct = round((1 - current.price_per_person_per_night / prior_pppn) * 100, 1)
    return saving, per_person, pct


def _lfl_key(obs: Observation) -> Tuple[str, str, str]:
    """Like-for-like key: same resort, cabin and board (normalised)."""
    return (
        obs.resort_name.strip().lower(),
        obs.cabin_class.strip().upper(),
        obs.board_basis.strip().lower(),
    )


def _resort_key(obs: Observation) -> Tuple[str, str]:
    return (obs.resort_name.strip().lower(), obs.cabin_class.strip().upper())


def _priors_before(current: Observation, pool: Sequence[Observation]) -> List[Observation]:
    """Earlier observations only — a report never compares to itself."""
    return [o for o in pool if o.observed_at < current.observed_at]


def classify(
    current: Observation,
    pool: Sequence[Observation],
) -> Classification:
    """Bucket one idea/product against everything observed before it.

    ``pool`` is every observation in history; priors are filtered to
    strictly-earlier timestamps so two resorts in the same report are not
    compared with each other.
    """
    earlier = _priors_before(current, pool)
    identical = [o for o in earlier if o.fingerprint == current.fingerprint]
    if identical:
        prior = max(identical, key=lambda o: o.observed_at)
        saving, per_person, pct = _saving_metrics(current, prior)
        if saving > 0.01:
            return Classification(EXACT_DROP, current, prior, saving, per_person, pct)
        if saving < -0.01:
            return Classification(PRICE_RISE, current, prior, saving, per_person, pct)
        return Classification(NO_CHANGE, current, prior, 0.0, 0.0, 0.0)

    resort_earlier = [o for o in earlier if _resort_key(o) == _resort_key(current)]
    if not resort_earlier:
        return Classification(NEW_TRACKED, current, None, 0.0, 0.0, 0.0)

    lfl_earlier = [o for o in resort_earlier if _lfl_key(o) == _lfl_key(current)]
    # A cheaper comparable is only a real low when it is not simply a
    # downgrade wearing a smaller number.
    reference = min(
        lfl_earlier or resort_earlier,
        key=lambda o: o.price_per_person_per_night,
    )
    reasons = downgrade_reasons(reference, current)
    pppn = reference.price_per_person_per_night
    drop_pct = round((1 - current.price_per_person_per_night / pppn) * 100, 1) if pppn > 0 else 0.0
    if not reasons and drop_pct >= MATERIAL_PPPN_DROP_PCT:
        saving, per_person, _ = _saving_metrics(current, reference)
        kind = COMPARABLE_NEW_LOW if lfl_earlier else NEW_DEAL
        return Classification(kind, current, reference, saving, per_person, drop_pct)
    # Either not materially cheaper, or cheaper for the wrong reason.
    return Classification(
        DOWNGRADED if reasons else NO_CHANGE,
        current,
        reference,
        0.0,
        0.0,
        drop_pct,
        tuple(reasons),
    )


def downgrade_reasons(prior: Observation, current: Observation) -> List[str]:
    """Why a lower total is not a genuine price reduction.

    Only ever fires on evidence the row actually carries. A legacy row with
    no board basis recorded cannot accuse the current one of a downgrade.
    """
    reasons: List[str] = []
    if prior.nights and current.nights and current.nights < prior.nights:
        reasons.append(f"fewer nights ({prior.nights}→{current.nights})")
    prior_board, current_board = board_rank(prior.board_basis), board_rank(current.board_basis)
    if prior_board is not None and current_board is not None and current_board < prior_board:
        reasons.append(f"lower board basis ({prior.board_basis}→{current.board_basis})")
    # Cabin is deliberately NOT a downgrade reason. The report renders the
    # same resort in several cabins, so comparing across cabins would flag
    # every Economy card at a resort that also has a Business card. Cabin is
    # part of the comparison key instead, never a like-for-like claim.
    if prior.live_used and not current.live_used and current.total_gbp < prior.total_gbp:
        reasons.append("live fare replaced by a benchmark estimate")
    if prior.transfer_gbp > 0 and current.transfer_gbp <= 0:
        reasons.append("transfer no longer included")
    if prior.unit_architecture and current.unit_architecture != prior.unit_architecture:
        reasons.append(
            f"different room architecture ({prior.unit_architecture}→{current.unit_architecture})"
        )
    return reasons


# ---------------------------------------------------------------------------
# False drops, date/duration combinations, callouts
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FalseDrop:
    current: Observation
    prior: Observation
    apparent_saving_gbp: float
    reasons: Tuple[str, ...]


def detect_false_drops(
    current: Observation,
    pool: Sequence[Observation],
) -> Optional[FalseDrop]:
    """An apparent reduction that the evidence says is not one.

    Looks for an earlier observation of the same resort and cabin whose
    total was HIGHER than this one (so it *looks* like a drop) but whose
    product was richer — more nights, a better board, a higher cabin, a
    live fare, or an included transfer. The largest apparent saving wins.
    """
    earlier = _priors_before(current, pool)
    candidates: List[FalseDrop] = []
    for prior in earlier:
        if _resort_key(prior) != _resort_key(current):
            continue
        apparent = prior.total_gbp - current.total_gbp
        if apparent <= 0.01:
            continue
        reasons = downgrade_reasons(prior, current)
        if reasons:
            candidates.append(
                FalseDrop(current, prior, round(apparent, 2), tuple(reasons))
            )
    if not candidates:
        return None
    return max(candidates, key=lambda fd: fd.apparent_saving_gbp)


@dataclass(frozen=True)
class DateCombination:
    nights: int
    outbound_date: str
    return_date: str
    total_gbp: float
    price_per_person_per_night: float
    observed_at: str


@dataclass(frozen=True)
class DateCombinationGroup:
    resort_name: str
    cabin_class: str
    board_basis: str
    combinations: Tuple[DateCombination, ...]
    longer_cheaper: Tuple[Tuple[DateCombination, DateCombination, float], ...] = ()

    @property
    def best_value(self) -> Optional[DateCombination]:
        priced = [c for c in self.combinations if c.price_per_person_per_night > 0]
        return min(priced, key=lambda c: c.price_per_person_per_night) if priced else None


def build_date_combination_groups(
    latest: Iterable[Observation],
) -> List[DateCombinationGroup]:
    """Group the current report by resort+cabin+board and expose duration maths."""
    groups: Dict[Tuple[str, str, str], List[Observation]] = defaultdict(list)
    for obs in latest:
        groups[_lfl_key(obs)].append(obs)

    out: List[DateCombinationGroup] = []
    for (resort, cabin, board), observations in groups.items():
        combos = tuple(
            DateCombination(
                nights=o.nights,
                outbound_date=o.outbound_date,
                return_date=o.return_date,
                total_gbp=round(o.total_gbp, 2),
                price_per_person_per_night=o.price_per_person_per_night,
                observed_at=o.observed_at,
            )
            for o in sorted(observations, key=lambda o: (o.nights, o.outbound_date))
        )
        longer_cheaper: List[Tuple[DateCombination, DateCombination, float]] = []
        for long_stay in combos:
            for short_stay in combos:
                if long_stay.nights <= short_stay.nights:
                    continue
                if long_stay.total_gbp <= short_stay.total_gbp:
                    longer_cheaper.append(
                        (long_stay, short_stay, round(short_stay.total_gbp - long_stay.total_gbp, 2))
                    )
        out.append(
            DateCombinationGroup(
                resort_name=resort or "unknown resort",
                cabin_class=cabin,
                board_basis=board,
                combinations=combos,
                longer_cheaper=tuple(longer_cheaper),
            )
        )
    out.sort(key=lambda g: (g.resort_name, g.cabin_class, g.board_basis))
    return out


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

@dataclass
class ComparisonReport:
    history_path: str
    observation_count: int
    fingerprints: int
    classifications: List[Classification] = field(default_factory=list)
    false_drops: List[FalseDrop] = field(default_factory=list)
    date_groups: List[DateCombinationGroup] = field(default_factory=list)

    @property
    def exact_drops(self) -> List[Classification]:
        return sorted(
            (c for c in self.classifications if c.kind == EXACT_DROP),
            key=lambda c: -c.saving_gbp,
        )

    @property
    def comparable_deals(self) -> List[Classification]:
        return sorted(
            (
                c
                for c in self.classifications
                if c.kind in (COMPARABLE_NEW_LOW, NEW_DEAL)
            ),
            key=lambda c: c.observation.price_per_person_per_night,
        )


def build_report(observations: Sequence[Observation], *, history_path: str = "") -> ComparisonReport:
    latest = latest_per_fingerprint(observations)
    report = ComparisonReport(
        history_path=history_path,
        observation_count=len(observations),
        fingerprints=len(latest),
    )
    report.classifications = [classify(obs, observations) for obs in latest]
    report.false_drops = [
        fd for obs in latest if (fd := detect_false_drops(obs, observations)) is not None
    ]
    report.date_groups = build_date_combination_groups(latest)
    return report


def _board_matches(observation: Observation, needle: str) -> bool:
    return needle in (observation.board_basis or "").lower()


def _best_by_pppn(candidates: Iterable[Observation]) -> Optional[Observation]:
    priced = [o for o in candidates if o.price_per_person_per_night > 0]
    return min(priced, key=lambda o: o.price_per_person_per_night) if priced else None


@dataclass
class Callouts:
    best_overall_value: Optional[Observation]
    lowest_cash_price: Optional[Observation]
    best_half_board: Optional[Observation]
    best_all_inclusive: Optional[Observation]
    biggest_duration_saving: Optional[Tuple[DateCombination, DateCombination, float]]
    needs_immediate_check: List[Classification]


def build_callouts(report: ComparisonReport) -> Callouts:
    latest = [c.observation for c in report.classifications]
    duration_savings = [
        (pair[0], pair[1], pair[2])
        for group in report.date_groups
        for pair in group.longer_cheaper
    ]
    biggest = max(duration_savings, key=lambda item: item[2]) if duration_savings else None
    urgent = [
        c
        for c in report.classifications
        if c.significant
        and c.kind in (EXACT_DROP, COMPARABLE_NEW_LOW, NEW_DEAL)
    ]
    return Callouts(
        best_overall_value=_best_by_pppn(latest),
        lowest_cash_price=min(latest, key=lambda o: o.total_gbp) if latest else None,
        best_half_board=_best_by_pppn(o for o in latest if _board_matches(o, "half board")),
        best_all_inclusive=_best_by_pppn(o for o in latest if _board_matches(o, "all inclusive")),
        biggest_duration_saving=biggest,
        needs_immediate_check=sorted(urgent, key=lambda c: -abs(c.saving_gbp)),
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _money(value: float) -> str:
    return f"£{value:,.0f}"


def _pct(value: float) -> str:
    return f"{value:+.1f}%"


def _table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> List[str]:
    if not rows:
        return ["_None._"]
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return lines


def render_markdown(report: ComparisonReport, callouts: Callouts) -> str:
    lines: List[str] = []
    lines.append("# Holiday deal-delta analysis")
    lines.append("")
    lines.append(
        f"History: `{report.history_path or '(none)'}` — "
        f"{report.observation_count} observations, {report.fingerprints} products tracked."
    )
    lines.append("")

    # Table 1 — verified exact drops.
    lines.append("## Table 1 — Verified exact price drops")
    lines.append("")
    lines.append("Same resort, dates, duration, room, cabin and board; a lower total.")
    lines.append("")
    lines.append(
        "\n".join(
            _table(
                ["Resort", "Nights", "Was", "Now", "Saving", "Per person", "pppn", "Significant"],
                [
                    [
                        c.observation.resort_name,
                        c.observation.nights,
                        _money(c.prior.total_gbp) if c.prior else "",
                        _money(c.observation.total_gbp),
                        _money(c.saving_gbp),
                        _money(c.saving_per_person_gbp),
                        _pct(c.saving_pppn_pct),
                        "yes" if c.significant else "no",
                    ]
                    for c in report.exact_drops
                ],
            )
        )
    )
    lines.append("")

    # Table 2 — best new comparable deals.
    lines.append("## Table 2 — Best new comparable deals")
    lines.append("")
    lines.append("Like-for-like cheaper, or a materially lower pppn with no identical prior.")
    lines.append("")
    lines.append(
        "\n".join(
            _table(
                ["Resort", "Kind", "Nights", "Board", "Cabin", "Outbound", "Total", "pppn"],
                [
                    [
                        c.observation.resort_name,
                        "comparable new low" if c.kind == COMPARABLE_NEW_LOW else "new deal",
                        c.observation.nights,
                        c.observation.board_basis or "?",
                        c.observation.cabin_class,
                        c.observation.outbound_date,
                        _money(c.observation.total_gbp),
                        _money(c.observation.price_per_person_per_night),
                    ]
                    for c in report.comparable_deals
                ],
            )
        )
    )
    lines.append("")

    # Table 3 — best date and duration combinations.
    lines.append("## Table 3 — Best date and duration combinations")
    lines.append("")
    combo_rows: List[List[str]] = []
    for group in report.date_groups:
        for combo in group.combinations:
            combo_rows.append(
                [
                    group.resort_name,
                    group.board_basis or "?",
                    group.cabin_class,
                    combo.nights,
                    combo.outbound_date,
                    combo.return_date,
                    _money(combo.total_gbp),
                    _money(combo.price_per_person_per_night),
                ]
            )
    lines.append(
        "\n".join(
            _table(
                ["Resort", "Board", "Cabin", "Nights", "Out", "Back", "Total", "pppn"],
                combo_rows,
            )
        )
    )
    if report.date_groups and any(g.longer_cheaper for g in report.date_groups):
        lines.append("")
        lines.append("**More nights for no more cash:**")
        for group in report.date_groups:
            for long_stay, short_stay, saving in group.longer_cheaper:
                lines.append(
                    f"- {group.resort_name}: {long_stay.nights} nights at "
                    f"{_money(long_stay.total_gbp)} is {_money(saving)} cheaper than "
                    f"{short_stay.nights} nights at {_money(short_stay.total_gbp)} "
                    f"({long_stay.outbound_date}→{long_stay.return_date})."
                )
    lines.append("")

    # Table 4 — misleading apparent reductions.
    lines.append("## Table 4 — Misleading apparent reductions")
    lines.append("")
    lines.append(
        "\n".join(
            _table(
                ["Resort", "Apparent saving", "Why it is not a reduction"],
                [
                    [
                        fd.current.resort_name,
                        _money(fd.apparent_saving_gbp),
                        "; ".join(fd.reasons),
                    ]
                    for fd in sorted(report.false_drops, key=lambda f: -f.apparent_saving_gbp)
                ],
            )
        )
    )
    lines.append("")

    # Final callouts.
    lines.append("## Summary callouts")
    lines.append("")
    lines.append(
        f"- **Best overall value:** "
        f"{callouts.best_overall_value.label} at "
        f"{_money(callouts.best_overall_value.price_per_person_per_night)} pppn."
        if callouts.best_overall_value
        else "- **Best overall value:** none priced."
    )
    lines.append(
        f"- **Lowest cash price:** "
        f"{callouts.lowest_cash_price.label} at {_money(callouts.lowest_cash_price.total_gbp)}."
        if callouts.lowest_cash_price
        else "- **Lowest cash price:** none priced."
    )
    lines.append(
        f"- **Best half board:** {callouts.best_half_board.label} at "
        f"{_money(callouts.best_half_board.price_per_person_per_night)} pppn."
        if callouts.best_half_board
        else "- **Best half board:** none tracked."
    )
    lines.append(
        f"- **Best all inclusive:** {callouts.best_all_inclusive.label} at "
        f"{_money(callouts.best_all_inclusive.price_per_person_per_night)} pppn."
        if callouts.best_all_inclusive
        else "- **Best all inclusive:** none tracked."
    )
    if callouts.biggest_duration_saving:
        long_stay, short_stay, saving = callouts.biggest_duration_saving
        lines.append(
            f"- **Most significant date/duration saving:** {long_stay.nights} nights at "
            f"{_money(long_stay.total_gbp)} beats {short_stay.nights} nights at "
            f"{_money(short_stay.total_gbp)} by {_money(saving)}."
        )
    else:
        lines.append("- **Most significant date/duration saving:** none within a resort.")
    if callouts.needs_immediate_check:
        lines.append("- **Needs immediate checking:**")
        for c in callouts.needs_immediate_check[:5]:
            lines.append(
                f"  - {c.observation.label}: {c.kind.replace('_', ' ')}, "
                f"{_money(abs(c.saving_gbp))} move ({_pct(c.saving_pppn_pct)} pppn)."
            )
    else:
        lines.append("- **Needs immediate checking:** nothing significant moved.")
    lines.append("")
    return "\n".join(lines)


def render_json(report: ComparisonReport, callouts: Callouts) -> str:
    def obs_payload(obs: Optional[Observation]) -> Optional[Dict[str, Any]]:
        if obs is None:
            return None
        return {
            "resort_name": obs.resort_name,
            "outbound_date": obs.outbound_date,
            "return_date": obs.return_date,
            "nights": obs.nights,
            "board_basis": obs.board_basis,
            "cabin_class": obs.cabin_class,
            "total_gbp": round(obs.total_gbp, 2),
            "price_per_person_per_night": obs.price_per_person_per_night,
        }

    payload = {
        "history_path": report.history_path,
        "observation_count": report.observation_count,
        "fingerprints": report.fingerprints,
        "exact_drops": [
            {
                "observation": obs_payload(c.observation),
                "prior_total_gbp": round(c.prior.total_gbp, 2) if c.prior else None,
                "saving_gbp": c.saving_gbp,
                "saving_per_person_gbp": c.saving_per_person_gbp,
                "saving_pppn_pct": c.saving_pppn_pct,
                "significant": c.significant,
            }
            for c in report.exact_drops
        ],
        "comparable_deals": [
            {
                "kind": c.kind,
                "observation": obs_payload(c.observation),
                "reference_total_gbp": round(c.prior.total_gbp, 2) if c.prior else None,
                "pppn_drop_pct": c.saving_pppn_pct,
            }
            for c in report.comparable_deals
        ],
        "date_combinations": [
            {
                "resort_name": g.resort_name,
                "cabin_class": g.cabin_class,
                "board_basis": g.board_basis,
                "options": [
                    {
                        "nights": combo.nights,
                        "outbound_date": combo.outbound_date,
                        "return_date": combo.return_date,
                        "total_gbp": combo.total_gbp,
                        "price_per_person_per_night": combo.price_per_person_per_night,
                    }
                    for combo in g.combinations
                ],
                "longer_cheaper": [
                    {
                        "longer_nights": long_stay.nights,
                        "shorter_nights": short_stay.nights,
                        "saving_gbp": saving,
                    }
                    for long_stay, short_stay, saving in g.longer_cheaper
                ],
            }
            for g in report.date_groups
        ],
        "false_drops": [
            {
                "observation": obs_payload(fd.current),
                "prior_total_gbp": round(fd.prior.total_gbp, 2),
                "apparent_saving_gbp": fd.apparent_saving_gbp,
                "reasons": list(fd.reasons),
            }
            for fd in sorted(report.false_drops, key=lambda f: -f.apparent_saving_gbp)
        ],
        "callouts": {
            "best_overall_value": obs_payload(callouts.best_overall_value),
            "lowest_cash_price": obs_payload(callouts.lowest_cash_price),
            "best_half_board": obs_payload(callouts.best_half_board),
            "best_all_inclusive": obs_payload(callouts.best_all_inclusive),
            "biggest_duration_saving_gbp": (
                callouts.biggest_duration_saving[2]
                if callouts.biggest_duration_saving
                else None
            ),
            "needs_immediate_check": [
                {"label": c.observation.label, "kind": c.kind, "saving_gbp": c.saving_gbp}
                for c in callouts.needs_immediate_check
            ],
        },
    }
    return json.dumps(payload, indent=2, sort_keys=True)


DEFAULT_HISTORY_PATHS = (
    Path("data/holiday_price_history.jsonl"),
    Path("data/july_holiday_price_history.jsonl"),
)


def _default_history_path() -> Path:
    for candidate in DEFAULT_HISTORY_PATHS:
        if candidate.exists():
            return candidate
    return DEFAULT_HISTORY_PATHS[0]
