"""Flight number to airport mapping.

Maps known flight numbers to their correct airport pairs for carriers
that return city codes instead of airport codes.

Lifted from private muscat_deal_finder_v6.py — no PII.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple


FLIGHT_NUMBER_AIRPORT_MAP: Dict[str, Tuple[str, str]] = {
    # Air Arabia UK flights typically from SHJ
    "G9258": ("SHJ", "LGW"),
    "G9265": ("SHJ", "LGW"),
    "G9266": ("LGW", "SHJ"),
    "G9321": ("SHJ", "IST"),
    # Air Arabia UAE domestic
    "G9045": ("SHJ", "AUH"),
    "G9046": ("AUH", "SHJ"),
    # Pegasus flights via SAW
    "PC1162": ("STN", "SAW"),
    "PC830": ("SAW", "MCT"),
    "PC407": ("AUH", "SAW"),
    "PC1185": ("SAW", "LGW"),
    # Oman Air
    "WY102": ("LHR", "MCT"),
    "WY101": ("MCT", "LHR"),
    "WY901": ("MCT", "SLL"),
    "WY902": ("SLL", "MCT"),
    # Etihad
    "EY68": ("LHR", "AUH"),
    "EY692": ("AUH", "MCT"),
    "EY19": ("AUH", "LHR"),
    # Emirates
    "EK029": ("DXB", "LHR"),
    "EK030": ("LHR", "DXB"),
    # Flydubai
    "FZ201": ("DXB", "AUH"),
    "FZ205": ("DXB", "AUH"),
    "FZ231": ("SHJ", "DXB"),
    # Wizz Air
    "W95327": ("LTN", "IST"),
    "W95328": ("IST", "LTN"),
    # SalamAir
    "OV123": ("MCT", "SLL"),
}


def map_flight_numbers_to_airports(
    flight_numbers: List[str], orig: str, dest: str
) -> Tuple[str, str]:
    """Map known flight numbers to their correct airports.

    Returns (first_origin, last_destination).
    """
    first_origin: Optional[str] = None
    last_destination: Optional[str] = None

    for flt in flight_numbers:
        flt_upper = flt.upper().strip()
        if flt_upper in FLIGHT_NUMBER_AIRPORT_MAP:
            mapped_origin, mapped_dest = FLIGHT_NUMBER_AIRPORT_MAP[flt_upper]
            if first_origin is None:
                first_origin = mapped_origin
            last_destination = mapped_dest

    return first_origin or orig, last_destination or dest


def resolve_flight_airports(
    origin: str, destination: str, flight_numbers: Optional[List[str]] = None
) -> Tuple[str, str]:
    """Resolve airport codes, using flight number mapping if available."""
    if not flight_numbers:
        return origin, destination
    return map_flight_numbers_to_airports(flight_numbers, origin, destination)
