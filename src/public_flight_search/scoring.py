"""Weighted multi-criteria scoring engine for flight options.

Lifted from private flight_intelligence_engine.py with all PII removed.
Scoring weights, cabin inconvenience, connection penalties, and Pareto
suppression are preserved exactly.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional, Sequence

from .trip_config import (
    CabinClass, BusinessProductType, TicketStructure,
    DEFAULT_SCORING_WEIGHTS,
)


def _parse_dt(value: str) -> datetime:
    clean = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(clean)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _date_distance(left: str, right: str) -> int:
    return abs((datetime.fromisoformat(left[:10]).date() - datetime.fromisoformat(right[:10]).date()).days)


def _scale(value: float, low: float, high: float) -> float:
    if high <= low:
        return 0.0
    return max(0.0, min(100.0, (value - low) / (high - low) * 100.0))


def _normalise_cabin(value: Any) -> str:
    text = str(value or "").strip().upper().replace(" ", "_")
    if text in {"BUSINESS", "C", "CLUB_WORLD"}:
        return CabinClass.BUSINESS
    return CabinClass.ECONOMY


def _normalise_product(segment: Mapping[str, Any]) -> str:
    explicit = str(segment.get("business_product_type") or "").strip().upper()
    if explicit in {
        BusinessProductType.LIE_FLAT, BusinessProductType.ANGLED_FLAT,
        BusinessProductType.RECLINER, BusinessProductType.EURO_BUSINESS,
        BusinessProductType.UNKNOWN,
    }:
        return explicit
    seat = str(segment.get("seat_type") or "").strip().upper().replace("-", "_").replace(" ", "_")
    if seat in {"FULLY_FLAT", "FULL_FLAT", "LIE_FLAT", "FLAT_BED"}:
        return BusinessProductType.LIE_FLAT
    if "ANGLED" in seat:
        return BusinessProductType.ANGLED_FLAT
    if "RECLIN" in seat:
        return BusinessProductType.RECLINER
    if seat in {"ECONOMY_SEAT", "STANDARD", "BLOCKED_MIDDLE"}:
        return BusinessProductType.EURO_BUSINESS
    return BusinessProductType.UNKNOWN


def normalize_offer(raw: Mapping[str, Any], requested_cabin: str) -> Dict[str, Any]:
    """Normalize provider data without upgrading mixed segments to full Business."""
    normalized = dict(raw)
    raw_segments = list(raw.get("segments") or [])
    if not raw_segments:
        raw_segments = [{
            "origin": raw.get("origin"), "destination": raw.get("destination"),
            "cabin_class": raw.get("cabin_class", requested_cabin),
            "business_product_type": raw.get("business_product_type"),
            "seat_type": raw.get("seat_type", "UNKNOWN"),
            "aircraft": raw.get("aircraft", "UNKNOWN"),
            "operating_carrier": raw.get("operating_carrier", raw.get("airline", "Unknown")),
            "marketing_carrier": raw.get("marketing_carrier", raw.get("airline", "Unknown")),
            "duration_minutes": raw.get("duration_minutes", raw.get("flight_minutes", 0)),
        }]

    segments: list[Dict[str, Any]] = []
    cabin_set: set[str] = set()
    business_minutes = 0
    longhaul_business_minutes = 0
    business_products: list[str] = []

    for raw_segment in raw_segments:
        segment = dict(raw_segment)
        cabin = _normalise_cabin(segment.get("cabin_class", requested_cabin))
        duration = int(segment.get("duration_minutes") or 0)
        product = _normalise_product(segment) if cabin == CabinClass.BUSINESS else BusinessProductType.UNKNOWN
        segment.update({
            "cabin_class": cabin,
            "business_product_type": product,
            "duration_minutes": duration,
        })
        segments.append(segment)
        cabin_set.add(cabin)
        if cabin == CabinClass.BUSINESS:
            business_minutes += duration
            if duration >= 300:
                longhaul_business_minutes += duration
            business_products.append(product)

    if cabin_set == {CabinClass.BUSINESS}:
        overall_cabin = CabinClass.BUSINESS
    elif CabinClass.BUSINESS in cabin_set:
        overall_cabin = CabinClass.MIXED
    else:
        overall_cabin = CabinClass.ECONOMY

    product_order = {
        BusinessProductType.LIE_FLAT: 0,
        BusinessProductType.ANGLED_FLAT: 1,
        BusinessProductType.RECLINER: 2,
        BusinessProductType.EURO_BUSINESS: 3,
        BusinessProductType.UNKNOWN: 4,
    }
    principal_product = min(business_products, key=lambda item: product_order[item]) if business_products else BusinessProductType.UNKNOWN

    normalized.update({
        "segments": segments,
        "cabin_class": overall_cabin,
        "business_product_type": principal_product,
        "business_minutes": business_minutes,
        "longhaul_business_minutes": longhaul_business_minutes,
        "total_flight_minutes": sum(s["duration_minutes"] for s in segments),
    })
    return normalized


def normalize_party_baggage(raw_offer: Mapping[str, Any], traveller_count: int, target_kg: int) -> Dict[str, Any]:
    """Normalize checked baggage for the whole party."""
    target_total = traveller_count * target_kg
    per_traveller = raw_offer.get("included_checked_bag_kg_per_traveller")
    explicit_total = raw_offer.get("included_checked_bag_kg_total")
    if explicit_total is not None:
        included_total = int(explicit_total)
    elif per_traveller is not None:
        included_total = int(per_traveller) * traveller_count
    else:
        included_total = 0
    shortfall = max(0, target_total - included_total)
    uplift_per_traveller = raw_offer.get("checked_bag_uplift_gbp_per_traveller")
    explicit_uplift = raw_offer.get("checked_bag_uplift_gbp_total")
    if shortfall == 0:
        uplift = 0.0
    elif explicit_uplift is not None:
        uplift = float(explicit_uplift)
    elif uplift_per_traveller is not None:
        uplift = float(uplift_per_traveller) * traveller_count
    else:
        uplift = 0.0
    return {
        "traveller_count": traveller_count,
        "target_checked_baggage_kg_total": target_total,
        "included_checked_baggage_kg_total": included_total,
        "checked_baggage_shortfall_kg": shortfall,
        "baggage_uplift_gbp": round(uplift, 2),
    }


def _cabin_inconvenience(option: Mapping[str, Any]) -> float:
    if option.get("business_minutes", 0) <= 0:
        return 82.0
    product = option.get("business_product_type")
    product_penalty = {
        BusinessProductType.LIE_FLAT: 4.0,
        BusinessProductType.ANGLED_FLAT: 20.0,
        BusinessProductType.RECLINER: 42.0,
        BusinessProductType.EURO_BUSINESS: 66.0,
        BusinessProductType.UNKNOWN: 55.0,
    }.get(product, 55.0)
    if option.get("cabin_class") == CabinClass.MIXED:
        product_penalty += 18.0
    return min(100.0, product_penalty)


def _connections_inconvenience(option: Mapping[str, Any]) -> float:
    value = float(option.get("total_stops", 0)) * 20.0
    ticket_type = option.get("ticket_type")
    if ticket_type == TicketStructure.UNBUNDLED_SELF_TRANSFER:
        value += 45.0
    elif ticket_type == TicketStructure.UNSAFE_SELF_TRANSFER:
        value += 100.0
    elif ticket_type == TicketStructure.TWO_INDEPENDENT_PROTECTED_TICKETS:
        value += 8.0
    return min(100.0, value)


def _airport_inconvenience(option: Mapping[str, Any]) -> float:
    airport = option.get("return_origin", "")
    convenience = {"DXB": 5.0, "SHJ": 48.0, "AUH": 38.0, "MCT": 5.0}
    return convenience.get(airport, 55.0)


def calculate_date_penalty(
    outbound_departure: str,
    return_date: str,
    preferred_outbound: str = "",
    preferred_return: str = "",
) -> float:
    """Calculate date preference penalty. Lower is better."""
    if not preferred_outbound:
        return 0.0
    outbound = _parse_dt(outbound_departure)
    out_day = outbound.date().isoformat()
    hour = outbound.hour
    evening = 17 <= hour <= 23

    if out_day == preferred_outbound:
        outbound_penalty = 0.0 if evening else 8.0
    else:
        distance = _date_distance(out_day, preferred_outbound)
        outbound_penalty = 12.0 + 10.0 * distance

    if preferred_return:
        ret_distance = _date_distance(return_date[:10], preferred_return)
        return_penalty = ret_distance * 6.0
    else:
        return_penalty = 0.0

    return round(outbound_penalty + return_penalty, 2)


def score_bucket_options(
    options: Sequence[Mapping[str, Any]],
    weights: Optional[Mapping[str, float]] = None,
) -> list[Dict[str, Any]]:
    """Score and rank options using weighted multi-criteria analysis."""
    weights = dict(weights or DEFAULT_SCORING_WEIGHTS)
    if abs(sum(weights.values()) - 1.0) > 0.0001:
        raise ValueError("Scoring weights must sum to 1.0")
    if not options:
        return []

    prices = [float(option.get("cash_cost_gbp", 0)) for option in options]
    journey_values = [
        float(option.get("total_trip_travel_minutes", 0)) + 8.0 * float(option.get("hassle_score", 0))
        for option in options
    ]

    scored: list[Dict[str, Any]] = []
    for original in options:
        option = dict(original)
        price_component = _scale(float(option.get("cash_cost_gbp", 0)), min(prices), max(prices))
        d2d_component = _scale(
            float(option.get("total_trip_travel_minutes", 0)) + 8.0 * float(option.get("hassle_score", 0)),
            min(journey_values), max(journey_values),
        )
        date_component = min(100.0, float(option.get("date_preference_penalty", 0)) / 45.0 * 100.0)
        cabin_component = _cabin_inconvenience(option)
        connection_component = _connections_inconvenience(option)
        airport_component = _airport_inconvenience(option)
        history_component = 50.0

        components = {
            "price_value": price_component,
            "door_to_door_hassle": d2d_component,
            "preferred_dates_timing": date_component,
            "cabin_quality": cabin_component,
            "connections_protection": connection_component,
            "airport_convenience": airport_component,
            "historical_attractiveness": history_component,
        }
        option["score_components"] = {k: round(v, 2) for k, v in components.items()}
        option["decision_score"] = round(sum(components[k] * weights[k] for k in weights), 2)
        scored.append(option)

    return sorted(scored, key=lambda x: x["decision_score"])


def _dominates(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    left_values = (
        float(left.get("cash_cost_gbp", 0)),
        float(left.get("total_trip_travel_minutes", 0)),
        float(left.get("date_preference_penalty", 0)),
        float(left.get("hassle_score", 0)),
        _cabin_inconvenience(left),
    )
    right_values = (
        float(right.get("cash_cost_gbp", 0)),
        float(right.get("total_trip_travel_minutes", 0)),
        float(right.get("date_preference_penalty", 0)),
        float(right.get("hassle_score", 0)),
        _cabin_inconvenience(right),
    )
    no_worse = all(lv <= rv for lv, rv in zip(left_values, right_values))
    materially_better = (
        left_values[0] <= right_values[0] - 20.0
        or left_values[1] <= right_values[1] - 45.0
        or left_values[2] <= right_values[2] - 8.0
        or left_values[3] <= right_values[3] - 8.0
        or left_values[4] <= right_values[4] - 15.0
    )
    return no_worse and materially_better


def pareto_suppress(options: Sequence[Mapping[str, Any]]) -> list[Dict[str, Any]]:
    """Remove Pareto-dominated options."""
    candidates = [dict(o) for o in options]
    result = []
    for option in candidates:
        dominated = any(
            other is not option and _dominates(other, option)
            for other in candidates
        )
        if not dominated:
            result.append(option)
    return result
