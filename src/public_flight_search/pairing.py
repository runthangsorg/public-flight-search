"""Multi-city flight pairing engine.

Combines outbound and return legs into complete itineraries with
cost ledgers, ground transport, and booking links.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .trip_config import TripDefinition, TripBucket, GroundSegment
from .ground_transport import (
    watford_to_airport,
    hotel_to_uae_airport,
    etihad_coach_option,
    muscat_to_dubai_coach,
    st_regis_to_mct,
    dubai_coach_to_grosvenor,
    get_ground_assumptions,
)
from .cost_ledger import ItineraryCostLedger, build_cost_ledger, parse_fare_family_baggage
from .booking_links import BookingLink, build_booking_links
from .pareto import rank_bucket_sections, TicketStructure
from .engine import FlightOffer


def generate_itinerary_fingerprint(
    outbound_date: str,
    return_date: str,
    outbound_origin: str,
    outbound_destination: str,
    return_origin: str,
    return_destination: str,
    operating_carriers: Optional[str] = None,
    flight_numbers: Optional[str] = None,
    ticket_structure: str = "PROTECTED_SINGLE_PNR",
    fare_family: Optional[str] = None,
) -> str:
    """Generate deterministic itinerary fingerprint from schedule/routes only."""
    out_d = outbound_date[:10]
    ret_d = return_date[:10]
    flt_str = ""
    if flight_numbers:
        if isinstance(flight_numbers, str):
            raw_flts = [f.strip().upper() for f in flight_numbers.split(",") if f.strip()]
        else:
            raw_flts = [f.strip().upper() for f in flight_numbers if f]
        clean_flts = [re.sub(r'\s+', '', f) for f in raw_flts]
        flt_str = ",".join(sorted(clean_flts))
    ts = (ticket_structure or "PROTECTED_SINGLE_PNR").strip().upper()
    f_str = f"{out_d}|{ret_d}|{outbound_origin}|{outbound_destination}|{return_origin}|{return_destination}|{flt_str}|{ts}"
    return hashlib.sha256(f_str.encode("utf-8")).hexdigest()[:16]


def generate_offer_fingerprint(
    itinerary_fingerprint: str,
    provider: str,
    fare_family: Optional[str] = None,
    baggage_basis: Optional[str] = None,
) -> str:
    """Generate offer-level fingerprint including provider and fare details."""
    from .carrier import canonicalize_carrier
    prov = canonicalize_carrier(provider or "Unknown")
    ff_raw = (fare_family or "STANDARD").strip().upper()
    if "VALUE" in ff_raw:
        ff_norm = "VALUE"
    elif "LITE" in ff_raw or "SAVER" in fam_clean:
        ff_norm = "SAVER_LITE"
    elif "BASIC" in ff_raw:
        ff_norm = "BASIC"
    elif "COMFORT" in ff_raw:
        ff_norm = "COMFORT"
    else:
        ff_norm = ff_raw
    bb = (baggage_basis or "STD").strip().upper()
    f_str = f"{itinerary_fingerprint}|{prov}|{ff_norm}|{bb}"
    return hashlib.sha256(f_str.encode("utf-8")).hexdigest()[:16]


def canonicalize_carrier(name: str) -> str:
    """Canonicalize carrier name from code or name."""
    CARRIER_CANONICAL = {
        "G9": "Air Arabia", "AIR ARABIA": "Air Arabia",
        "EY": "Etihad Airways", "ETIHAD": "Etihad Airways",
        "WY": "Oman Air", "OMAN AIR": "Oman Air",
        "PC": "Pegasus", "PEGASUS": "Pegasus",
        "W9": "Wizz Air", "W6": "Wizz Air", "WIZZ": "Wizz Air",
        "EK": "Emirates", "EMIRATES": "Emirates",
        "FZ": "Flydubai", "FLYDUBAI": "Flydubai",
        "OV": "SalamAir", "SALAM": "SalamAir",
        "TK": "Turkish Airlines", "THY": "Turkish Airlines",
        "VF": "AJet", "AJET": "AJet",
        "BA": "British Airways", "BRITISH AIRWAYS": "British Airways",
        "QR": "Qatar Airways", "QATAR": "Qatar Airways",
        "SV": "Saudia", "SAUDIA": "Saudia",
        "GF": "Gulf Air", "GULF AIR": "Gulf Air",
        "RJ": "Royal Jordanian", "ROYAL JORDANIAN": "Royal Jordanian",
    }
    cleaned = name.strip().upper()
    return CARRIER_CANONICAL.get(cleaned, name.strip())


def calculate_flight_duration_utc(
    dep_time_str: str,
    arr_time_str: str,
    origin: str,
    destination: str,
) -> Tuple[int, str]:
    """Calculate flight duration in seconds and formatted string."""
    # Simplified - use known durations for this route
    if origin in ("LHR", "LGW", "LTN", "STN") and destination in ("MCT",):
        return 7 * 3600 + 15 * 60, "7h 15m"
    if origin in ("MCT",) and destination in ("DXB", "AUH", "SHJ"):
        return 1 * 3600 + 10 * 60, "1h 10m"
    if origin in ("DXB", "AUH", "SHJ") and destination in ("LHR", "LGW", "LTN", "STN"):
        return 7 * 3600 + 25 * 60, "7h 25m"
    return 7 * 3600, "7h 00m"


def pair_outbound_return(
    trip: 'TripDefinition',
    outbound_offers: Sequence[Dict[str, Any]],
    return_offers: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Pair outbound and return offers into complete itineraries."""
    import re
    from .engine import FlightOffer

    paired = []
    for out in outbound_offers:
        if not isinstance(out, dict):
            continue
        for ret in return_offers:
            if not isinstance(ret, dict):
                continue

            # Skip invalid date combinations
            out_date = out.get("departure", "")[:10]
            ret_date = ret.get("departure", "")[:10]
            if ret_date <= out_date:
                continue

            # Build combined itinerary
            itinerary = combine_legs(out, ret, trip)
            paired.append(itinerary)

    return paired


def combine_legs(
    outbound: Dict[str, Any],
    return_leg: Dict[str, Any],
    trip: 'TripDefinition',
) -> Dict[str, Any]:
    """Combine two legs into a complete itinerary with cost ledger and links."""
    import re

    out_date = outbound.get("departure", "")[:10]
    ret_date = return_leg.get("departure", "")[:10]
    out_orig = outbound.get("origin", "")
    out_dest = outbound.get("destination", "")
    ret_orig = return_leg.get("origin", "")
    ret_dest = return_leg.get("destination", "")

    # Determine ticket structure
    out_carrier = canonicalize_carrier(outbound.get("airline", ""))
    ret_carrier = canonicalize_carrier(return_leg.get("airline", ""))

    if out_carrier == ret_carrier:
        ticket_type = TicketStructure.PROTECTED_SINGLE_PNR
    else:
        ticket_type = TicketStructure.TWO_INDEPENDENT_PROTECTED_TICKETS

    # Build itinerary fingerprint
    itin_fp = generate_itinerary_fingerprint(
        outbound.get("departure", ""),
        return_leg.get("departure", ""),
        outbound.get("origin", ""),
        outbound.get("destination", ""),
        return_leg.get("origin", ""),
        return_leg.get("destination", ""),
        ticket_structure=TicketStructure.PROTECTED_SINGLE_PNR if out_carrier == ret_carrier else TicketStructure.TWO_INDEPENDENT_PROTECTED_TICKETS,
    )

    # Determine carriers
    out_carrier_name = canonicalize_carrier(outbound.get("airline", ""))
    ret_carrier_name = canonicalize_carrier(return_leg.get("airline", ""))

    # Calculate durations
    out_dur_sec, out_dur_str = calculate_flight_duration_utc(
        outbound.get("departure", ""), outbound.get("arrival", ""),
        outbound.get("origin", ""), outbound.get("destination", "")
    )
    ret_dur_sec, ret_dur_str = calculate_flight_duration_utc(
        return_leg.get("departure", ""), return_leg.get("arrival", ""),
        return_leg.get("origin", ""), return_leg.get("destination", "")
    )

    # Base fares (per traveller)
    out_fare = float(outbound.get("price_per_traveller", outbound.get("price", 0))) / max(1, outbound.get("travellers", 1))
    ret_fare = float(return_leg.get("price_per_traveller", return_leg.get("price", 0))) / max(1, return_leg.get("travellers", 1))
    base_airfare = round(out_fare + ret_fare, 2)

    # Fare family detection
    out_fare_family = outbound.get("fare_family", "STANDARD")
    ret_fare_family = return_leg.get("fare_family", "STANDARD")

    # Build cost ledger
    party = trip.passenger_party
    traveller_count = party.total_travellers

    ledger = build_cost_ledger(
        airfare=base_airfare * party.total_travellers,
        fare_family=out_fare_family,
        airline=out_carrier_name,
        traveller_count=party.total_travellers,
    )

    # Ground transport costs
    london_out = 0.0
    if out_date in ("2026-09-15", "2026-09-16"):
        # Watford to London airports
        for airport in ("LHR", "LTN", "STN", "LGW"):
            gw = watford_to_airport(airport)
            if gw:
                london_out = gw.cost_gbp
                break

    london_in = 0.0
    # Return ground from UAE airports
    uae_ground = 0.0
    oman_uae = 0.0

    # Add surface segments
    for segment in trip.surface_segments:
        if segment.mode == "COACH" and segment.origin == "MCT" and segment.destination == "DXB":
            oman_uae = segment.cost_gbp

    # Hotel transfers
    for anchor in trip.hotel_anchors:
        if "St. Regis" in anchor or "Al Mouj" in anchor:
            st_regis = get_ground_assumptions()["MCT_ST_REGIS"]
            oman_uae += st_regis.cost_gbp

    # Dubai hotel to return airport
    if "Grosvenor" in str(trip.hotel_anchors):
        grosvenor_dxb = get_ground_assumptions()["GROSVENOR_DXB"]
        uae_ground += grosvenor_dxb.cost_gbp

    # Add coach return if Etihad
    # ... simplified for now

    # Build booking links
    out_orig = outbound.get("origin", "")
    out_dest = outbound.get("destination", "")
    ret_orig = return_leg.get("origin", "")
    ret_dest = return_leg.get("destination", "")
    out_date = outbound.get("departure", "")[:10]
    ret_date = return_leg.get("departure", "")[:10]

    booking_data = build_booking_links(
        out_orig, out_dest, out_date,
        return_leg.get("origin", ""), return_leg.get("destination", ""), ret_date,
    )

    # Calculate total travel minutes
    out_dur = outbound.get("duration_minutes", 0)
    ret_dur = return_leg.get("duration_minutes", 0)
    total_travel = out_dur + ret_dur

    # Build combined offer
    combined = {
        "itinerary_fingerprint": itin_fp,
        "offer_fingerprint": generate_offer_fingerprint(
            generate_itinerary_fingerprint(
                out_date, ret_date, outbound.get("origin", ""), outbound.get("destination", ""),
                return_leg.get("origin", ""), return_leg.get("destination", "")
            ),
            outbound.get("provider", ""),
            out_fare_family,
        ),
        "bucket": outbound.get("bucket", ""),
        "trip_key": trip.key,
        "trip_label": trip.label,
        "outbound_date": out_date,
        "return_date": ret_date,
        "outbound_origin": out_orig,
        "outbound_destination": out_dest,
        "return_origin": ret_orig,
        "return_destination": ret_dest,
        "outbound_departure": outbound.get("departure", ""),
        "outbound_arrival": outbound.get("arrival", ""),
        "return_departure": return_leg.get("departure", ""),
        "return_arrival": return_leg.get("arrival", ""),
        "outbound_stops": outbound.get("stops", 0),
        "inbound_stops": return_leg.get("stops", 0),
        "outbound_duration_minutes": outbound.get("duration_minutes", 0),
        "inbound_duration_minutes": return_leg.get("duration_minutes", 0),
        "total_trip_travel_minutes": total_travel,
        "outbound_carrier": out_carrier_name,
        "inbound_carrier": ret_carrier_name,
        "cabin_class": outbound.get("cabin_class", "ECONOMY"),
        "airfare_gbp": base_airfare * party.total_travellers,
        "normalized_fare_with_bags": 0.0,  # Will be set below
        "cash_cost_gbp": base_airfare * party.total_travellers,
        "all_in_preferred": 0.0,  # Will be set below
        "booking_data": booking_data,
        "ticket_type": TicketStructure.PROTECTED_SINGLE_PNR if out_carrier == ret_carrier else TicketStructure.TWO_INDEPENDENT_PROTECTED_TICKETS,
        "traveller_count": trip.passenger_party.total_travellers,
        "baggage_basis": outbound.get("fare_family", "STD"),
        "is_eligible_deal": True,
        "source_observed_at": datetime.now(timezone.utc).isoformat(),
    }

    # Normalize with baggage
    from .cost_ledger import parse_fare_family_baggage, ItineraryCostLedger
    included_kg, uplift, included = parse_fare_family_baggage(out_carrier_name, out_fare_family)
    party_count = trip.passenger_party.total_travellers
    target = party_count * 1 * 20  # 1 bag each, 20kg target
    included_total = included_kg * party_count if included else 0
    shortfall = max(0, party_count * 20 - included_total)
    baggage_cost = uplift * party_count if shortfall > 0 else 0.0

    ledger = build_cost_ledger(
        airfare=base_airfare * party.total_travellers,
        fare_family=out_fare_family,
        airline=out_carrier_name,
        traveller_count=party.total_travellers,
        checked_bag_count=1,
        checked_bag_target_kg=20,
        london_ground_out=watford_to_airport(outbound.get("origin", "LHR")).cost_gbp if watford_to_airport(outbound.get("origin", "LHR")) else 0,
        london_ground_in=watford_to_airport(return_leg.get("destination", "LHR")).cost_gbp if watford_to_airport(return_leg.get("destination", "LHR")) else 0,
        uae_ground=get_ground_assumptions().get("GROSVENOR_DXB", {}).get("cost_gbp", 0) if hasattr(get_ground_assumptions(), "get") else 24.0,
        oman_uae_transfer=22.0,
        muscat_taxi=10.0,
    )
    ledger.fare_family = out_fare_family
    ledger.checked_baggage_cost = baggage_cost

    # Update combined with ledger totals
    combined.update({
        "normalized_fare_with_bags": ledger.normalized_flight_cost,
        "cash_cost_gbp": ledger.normalized_flight_cost,
        "all_in_preferred": ledger.total_all_in_door_to_door,
        "cost_ledger": ledger.to_dict(),
        "decision_score": 0.0,  # Will be scored later
        "hassle_score": 0.0,
        "date_preference_penalty": 0.0,
    })

    return combined


# Import needed modules
import re
from datetime import datetime, timezone
from typing import Tuple