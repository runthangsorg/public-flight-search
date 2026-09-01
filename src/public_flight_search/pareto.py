"""Pareto dominance suppression and deduplication for itinerary options."""

from __future__ import annotations

from typing import List, Dict, Any, Sequence, Tuple, Set
from dataclasses import dataclass


@dataclass(frozen=True)
class TicketStructure:
    PROTECTED_SINGLE_PNR = "PROTECTED_SINGLE_PNR"
    TWO_INDEPENDENT_PROTECTED_TICKETS = "TWO_INDEPENDENT_PROTECTED_TICKETS"
    UNBUNDLED_SELF_TRANSFER = "UNBUNDLED_SELF_TRANSFER"
    UNSAFE_SELF_TRANSFER = "UNSAFE_SELF_TRANSFER"


PROTECTION_RANK = {
    TicketStructure.PROTECTED_SINGLE_PNR: 3,
    TicketStructure.TWO_INDEPENDENT_PROTECTED_TICKETS: 2,
    TicketStructure.UNBUNDLED_SELF_TRANSFER: 1,
    TicketStructure.UNSAFE_SELF_TRANSFER: 0,
}


def _fingerprint_key(option: Dict[str, Any]) -> str:
    """Generate a deduplication fingerprint for an option."""
    parts = [
        str(option.get("outbound_date", "")),
        str(option.get("return_date", "")),
        str(option.get("outbound_origin", "")),
        str(option.get("outbound_destination", "")),
        str(option.get("return_origin", "")),
        str(option.get("return_destination", "")),
        str(option.get("ticket_type", "")),
    ]
    return "|".join(parts)


def deduplicate_options(options: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate options on fingerprint, keeping the lowest cost."""
    seen: Dict[str, Dict[str, Any]] = {}
    for opt in options:
        fp = _fingerprint_key(opt)
        if fp not in seen or opt.get("cash_cost_gbp", 999999) < seen[fp].get("cash_cost_gbp", 999999):
            seen[fp] = opt
    return list(seen.values())


def _dominates(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """Return True if option A strictly dominates option B."""
    # Must be same date pair to compare
    if a.get("outbound_date") != b.get("outbound_date"):
        return False
    if a.get("return_date") != b.get("return_date"):
        return False

    a_norm = a.get("normalized_fare_with_bags", a.get("cash_cost_gbp", 999999))
    b_norm = b.get("normalized_fare_with_bags", b.get("cash_cost_gbp", 999999))
    a_d2d = a.get("all_in_preferred", a.get("cash_cost_gbp", 999999))
    b_d2d = b.get("all_in_preferred", b.get("cash_cost_gbp", 999999))
    a_stops = a.get("outbound_stops", 0) + a.get("inbound_stops", 0)
    b_stops = b.get("outbound_stops", 0) + b.get("inbound_stops", 0)
    a_score = a.get("decision_score", 999)
    b_score = b.get("decision_score", 999)
    a_prot = PROTECTION_RANK.get(a.get("ticket_type", ""), 2)
    b_prot = PROTECTION_RANK.get(b.get("ticket_type", ""), 2)

    # A dominates B if A is no worse on all metrics and strictly better on at least one
    no_worse = (
        a_norm <= b_norm
        and a_d2d <= b_d2d
        and a_stops <= b_stops
        and a_score <= b_score
        and a_prot >= b_prot
    )
    strictly_better = (
        a_norm < b_norm
        or a_d2d < b_d2d
        or a_stops < b_stops
        or a_score < b_score
        or a_prot > b_prot
    )

    return no_worse and strictly_better


def suppress_pareto_dominated(options: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Mark Pareto-dominated options as ineligible.

    An option A dominates B if they share the same date pair and:
    - A has <= normalized fare with bags
    - A has <= all-in door-to-door cost
    - A has <= total stops
    - A has <= decision score
    - A has >= ticket protection
    - A is strictly better on at least one metric
    """
    for opt in options:
        opt["is_pareto_dominated"] = False

    for i, a in enumerate(options):
        if not a.get("is_eligible_deal", True):
            continue
        for j, b in enumerate(options):
            if i == j:
                continue
            if not b.get("is_eligible_deal", True):
                continue
            if b.get("is_pareto_dominated", False):
                continue

            if _dominates(a, b):
                b["is_pareto_dominated"] = True
                b["dominated_by_fingerprint"] = a.get("fingerprint", "")
                b["is_eligible_deal"] = False

    return options


def rank_bucket_sections(
    options: List[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """Return ranked sections after Pareto suppression and deduplication."""
    eligible = [o for o in options if o.get("is_eligible_deal", True)]

    # Suppress dominated
    suppressed = suppress_pareto_dominated(eligible)

    # Deduplicate
    unique = deduplicate_options(suppressed)

    # Re-filter eligible
    final = [o for o in unique if o.get("is_eligible_deal", True)]

    # Sort by decision score, then cash cost
    final.sort(key=lambda x: (x.get("decision_score", 999), x.get("cash_cost_gbp", 999999)))

    sections = {
        "overall": final[:10],
        "economy": [o for o in final if o.get("cabin_class") == "ECONOMY"][:5],
        "business": [o for o in final if o.get("business_minutes", 0) > 0][:5],
    }
    return sections