"""Open-jaw and roundtrip pairing logic.

Pairs one-way flight offers into complete itineraries, handling:
- Roundtrip (same airports both ways)
- Open-jaw (fly into A, return from B)
- Multi-city / surface segments
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .trip_config import TripDefinition, TicketStructure


def _fingerprint(outbound: Mapping[str, Any], inbound: Mapping[str, Any]) -> str:
    parts = (
        outbound.get("origin", ""),
        outbound.get("destination", ""),
        outbound.get("departure", ""),
        inbound.get("origin", ""),
        inbound.get("destination", ""),
        inbound.get("departure", ""),
        str(outbound.get("airline", "")),
        str(inbound.get("airline", "")),
    )
    return "|".join(parts)


def _is_compatible_pair(
    outbound: Mapping[str, Any],
    inbound: Mapping[str, Any],
    trip: TripDefinition,
) -> bool:
    """Check if two one-way offers form a valid pair for this trip."""
    out_dest = outbound.get("destination", "")
    in_orig = inbound.get("origin", "")

    if out_dest == in_orig:
        return True

    for seg_origin, seg_dest in trip.surface_segments:
        if out_dest == seg_origin and in_orig == seg_dest:
            return True
        if out_dest == seg_dest and in_orig == seg_origin:
            return True

    return False


def _determine_ticket_type(
    outbound: Mapping[str, Any],
    inbound: Mapping[str, Any],
    trip: TripDefinition,
) -> str:
    """Classify the ticket structure for a paired itinerary."""
    out_dest = outbound.get("destination", "")
    in_orig = inbound.get("origin", "")

    if out_dest == in_orig:
        return TicketStructure.PROTECTED_SINGLE_PNR

    for seg_origin, seg_dest in trip.surface_segments:
        if out_dest == seg_origin and in_orig == seg_dest:
            return TicketStructure.TWO_INDEPENDENT_PROTECTED_TICKETS

    return TicketStructure.UNBUNDLED_SELF_TRANSFER


def _calculate_surface_leg(
    outbound: Mapping[str, Any],
    inbound: Mapping[str, Any],
    trip: TripDefinition,
) -> Optional[Dict[str, Any]]:
    """Calculate surface segment details if applicable."""
    out_dest = outbound.get("destination", "")
    in_orig = inbound.get("origin", "")

    if out_dest == in_orig:
        return None

    for seg_origin, seg_dest in trip.surface_segments:
        if out_dest == seg_origin and in_orig == seg_dest:
            return {
                "type": "surface",
                "origin": seg_origin,
                "destination": seg_dest,
                "mode": "ground_transport",
            }

    return None


def pair_itineraries(
    outbound_offers: Sequence[Mapping[str, Any]],
    inbound_offers: Sequence[Mapping[str, Any]],
    trip: TripDefinition,
) -> List[Dict[str, Any]]:
    """Pair one-way outbound and inbound offers into complete itineraries.

    Returns a list of paired itineraries with:
    - outbound/inbound offer details
    - ticket type classification
    - surface segment info (if open-jaw)
    - combined cost
    - combined duration
    - combined stops
    """
    paired: list[Dict[str, Any]] = []
    seen: set[str] = set()

    for out_offer in outbound_offers:
        for in_offer in inbound_offers:
            if not _is_compatible_pair(out_offer, in_offer, trip):
                continue

            fp = _fingerprint(out_offer, in_offer)
            if fp in seen:
                continue
            seen.add(fp)

            ticket_type = _determine_ticket_type(out_offer, in_offer, trip)
            surface = _calculate_surface_leg(out_offer, in_offer, trip)

            out_price = float(out_offer.get("price", out_offer.get("airfare_gbp", 0)))
            in_price = float(in_offer.get("price", in_offer.get("airfare_gbp", 0)))
            out_duration = int(out_offer.get("duration_minutes", out_offer.get("total_flight_minutes", 0)))
            in_duration = int(in_offer.get("duration_minutes", in_offer.get("total_flight_minutes", 0)))
            out_stops = int(out_offer.get("stops", out_offer.get("total_stops", 0)))
            in_stops = int(in_offer.get("stops", in_offer.get("total_stops", 0)))

            out_baggage = float(out_offer.get("baggage_uplift_gbp", 0))
            in_baggage = float(in_offer.get("baggage_uplift_gbp", 0))

            paired.append({
                "outbound": out_offer,
                "inbound": in_offer,
                "ticket_type": ticket_type,
                "surface_segment": surface,
                "cash_cost_gbp": round(out_price + in_price, 2),
                "with_bags_gbp": round(out_price + out_baggage + in_price + in_baggage, 2),
                "total_trip_travel_minutes": out_duration + in_duration + (
                    surface.get("estimated_minutes", 300) if surface else 0
                ),
                "total_stops": out_stops + in_stops,
                "outbound_date": out_offer.get("departure", "")[:10],
                "return_date": in_offer.get("departure", "")[:10],
                "outbound_origin": out_offer.get("origin", ""),
                "outbound_destination": out_offer.get("destination", ""),
                "return_origin": in_offer.get("origin", ""),
                "return_destination": in_offer.get("destination", ""),
                "outbound_airline": out_offer.get("airline", "Unknown"),
                "inbound_airline": in_offer.get("airline", "Unknown"),
                "outbound_duration_minutes": out_duration,
                "inbound_duration_minutes": in_duration,
                "outbound_stops": out_stops,
                "inbound_stops": in_stops,
                "is_roundtrip": (
                    out_offer.get("origin") == in_offer.get("destination")
                    and out_offer.get("destination") == in_offer.get("origin")
                ),
            })

    return paired
