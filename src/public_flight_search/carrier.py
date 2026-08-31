"""Carrier canonicalization — maps airline codes and names to canonical form.

Lifted from private muscat_deal_finder.py with all PII removed.
Handles multi-carrier strings like "G9 + W9" and IATA codes.
"""

from __future__ import annotations

import re
from typing import Dict, Optional


CARRIER_CANONICAL_NAMES: Dict[str, str] = {
    "etihad": "Etihad Airways", "ey": "Etihad Airways",
    "emirates": "Emirates", "ek": "Emirates",
    "oman air": "Oman Air", "wy": "Oman Air", "oman": "Oman Air",
    "air arabia": "Air Arabia", "g9": "Air Arabia", "airarabia": "Air Arabia",
    "british airways": "British Airways", "ba": "British Airways",
    "easyjet": "easyJet", "u2": "easyJet", "easy": "easyJet",
    "ryanair": "Ryanair", "fr": "Ryanair",
    "wizz air": "Wizz Air", "w9": "Wizz Air UK", "w6": "Wizz Air",
    "turkish airlines": "Turkish Airlines", "tk": "Turkish Airlines", "turkish": "Turkish Airlines",
    "pegasus": "Pegasus Airlines", "pc": "Pegasus Airlines",
    "flydubai": "Flydubai", "fz": "Flydubai", "fly dubai": "Flydubai",
    "salamair": "SalamAir", "salam air": "SalamAir", "ov": "SalamAir",
    "ajet": "AJet", "vf": "AJet",
    "qatar airways": "Qatar Airways", "qr": "Qatar Airways", "qatar": "Qatar Airways",
    "lufthansa": "Lufthansa", "lh": "Lufthansa",
    "klm": "KLM", "kl": "KLM",
    "air france": "Air France", "af": "Air France",
    "swiss": "Swiss", "lx": "Swiss",
    "austrian": "Austrian Airlines", "os": "Austrian Airlines",
    "gulf air": "Gulf Air", "gf": "Gulf Air",
    "saudia": "Saudia", "sv": "Saudia",
    "egyptair": "EgyptAir", "ms": "EgyptAir",
    "royal jordanian": "Royal Jordanian", "rj": "Royal Jordanian",
    "iberia": "Iberia", "ib": "Iberia",
    "finnair": "Finnair", "ay": "Finnair",
    "aer lingus": "Aer Lingus", "ei": "Aer Lingus",
    "aegean": "Aegean Airlines", "a3": "Aegean Airlines",
    "wizz air uk": "Wizz Air UK",
}


def canonicalize_carrier(carrier: str) -> str:
    """Map a carrier string (code or name) to its canonical name."""
    if not carrier:
        return "Unknown airline"
    key = carrier.strip().lower()
    if key in CARRIER_CANONICAL_NAMES:
        return CARRIER_CANONICAL_NAMES[key]
    if re.match(r"^[a-z]{2}$", key):
        return CARRIER_CANONICAL_NAMES.get(key, carrier.strip().title())
    return carrier.strip().title()


def canonicalize_carrier_string(carrier_string: str) -> str:
    """Handle multi-carrier strings like 'G9 + W9' or 'Etihad + Air Arabia'."""
    if not carrier_string:
        return "Unknown airline"
    parts = re.split(r"\s*[+&,/]\s*", carrier_string.strip())
    canonical = [canonicalize_carrier(p) for p in parts if p.strip()]
    if len(canonical) == 1:
        return canonical[0]
    return " + ".join(canonical)
