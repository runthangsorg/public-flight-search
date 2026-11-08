"""How long a flight leg is, for the "any leg over 8 hours is Business" rule (owner, 8 Nov 2026).

A read does not always itemise its flights: the Google multi-city card describes the FIRST journey (stops, duration,
layover and the hub's code) and gives one price for the lot. The rule needs each leg, so where a read says nothing
about a leg its block time is ESTIMATED from the two airports: great-circle distance at a flat cruising speed plus a
fixed allowance for taxi, climb and descent. The estimate is for gating a cabin, never for a price; an airport the table
does not hold has no estimate, and a leg with no estimate is not shown to be short.
"""

from __future__ import annotations

import math
import re
from typing import Any, Mapping, Optional, Sequence

#: (latitude, longitude) in degrees, to the nearest hundredth. Airports the planner can route through or to.
AIRPORTS: dict[str, tuple[float, float]] = {
    "LHR": (51.47, -0.45), "LGW": (51.15, -0.19), "LTN": (51.87, -0.37), "STN": (51.89, 0.24),
    "DOH": (25.27, 51.61), "DXB": (25.25, 55.36), "AUH": (24.43, 54.65), "MCT": (23.59, 58.28),
    "IST": (41.28, 28.74), "ZRH": (47.46, 8.55), "ADD": (8.98, 38.80), "NBO": (-1.32, 36.93),
    "MBA": (-4.03, 39.59), "JRO": (-3.43, 37.07), "ZNZ": (-6.22, 39.22), "DAR": (-6.88, 39.20),
    "JNB": (-26.14, 28.25), "CPT": (-33.97, 18.60), "MRU": (-20.43, 57.68), "SEZ": (-4.67, 55.52),
    "HKT": (8.11, 98.32), "USM": (9.55, 100.06), "BKK": (13.69, 100.75), "DPS": (-8.75, 115.17),
    "LOP": (-8.76, 116.28), "SIN": (1.36, 103.99), "KUL": (2.75, 101.71), "DAD": (16.04, 108.20),
    "HND": (35.55, 139.78), "NRT": (35.77, 140.39), "KIX": (34.43, 135.24), "CTS": (42.78, 141.69),
    "OKA": (26.20, 127.65), "HKD": (41.77, 140.82), "MMB": (43.88, 144.16), "MXP": (45.63, 8.72),
    "VCE": (45.51, 12.35), "CUN": (21.04, -86.87), "DEL": (28.56, 77.10), "CAI": (30.12, 31.41),
    "AMM": (31.72, 35.99), "AMS": (52.31, 4.76), "FRA": (50.03, 8.57), "CDG": (49.01, 2.55),
    "FCO": (41.80, 12.25), "NCE": (43.66, 7.22), "KGL": (-1.97, 30.14), "MLE": (4.19, 73.53),
    "ACE": (28.95, -13.61), "AYT": (36.90, 30.80), "FNC": (32.69, -16.77), "FUE": (28.45, -13.86),
    "HRG": (27.18, 33.80), "LPA": (27.93, -15.39), "PFO": (34.72, 32.49), "TFS": (28.04, -16.57),
    "MQP": (-25.38, 31.11),
}

CRUISE_KMH = 800.0
#: Taxi, climb and descent, added to every leg.
ALLOWANCE_HOURS = 0.5
_EARTH_KM = 6371.0
_CODE_RE = re.compile(r"\b[A-Z]{3}\b")


def _distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * _EARTH_KM * math.asin(math.sqrt(h))


def estimate_hours(origin: str, destination: str) -> Optional[float]:
    """Estimated block hours of a nonstop flight, or ``None`` when either airport is not in the table."""
    a, b = AIRPORTS.get(str(origin).upper()), AIRPORTS.get(str(destination).upper())
    if a is None or b is None:
        return None
    return _distance_km(a, b) / CRUISE_KMH + ALLOWANCE_HOURS


def layover_hubs(text: Any) -> list[str]:
    """The airport codes a read's layover text names, in order (``2 hrs 55 min ADD`` -> ``["ADD"]``)."""
    return _CODE_RE.findall(str(text or ""))


def journey_hours(origin: str, destination: str, via: Sequence[str] = ()) -> list[Optional[float]]:
    """The estimated hours of each flight of a journey, through the named hubs in order."""
    stops = [str(origin).upper(), *[str(v).upper() for v in via], str(destination).upper()]
    return [estimate_hours(a, b) for a, b in zip(stops, stops[1:])]


def read_leg_hours(read: Mapping[str, Any], legs: Sequence[Sequence[str]], parse_duration) -> list[Optional[float]]:
    """Every flight leg's hours for a read of a trip's ``legs`` (``(origin, destination, ...)`` rows).

    In order of trust: the flights a read itemises (each one's own duration); else the first journey as the read
    describes it, with its layover hubs, and the same journey reversed for the leg that flies it home; every other
    leg is estimated as a nonstop between its two airports. ``None`` entries are legs nobody could measure.
    """
    flights = read.get("flights")
    if isinstance(flights, (list, tuple)) and flights:
        hours = [parse_duration(f.get("duration")) if isinstance(f, Mapping) else None for f in flights]
        if all(h is not None for h in hours):
            return hours
    out: list[Optional[float]] = []
    first = legs[0] if legs else None
    via = layover_hubs(read.get("layovers"))
    for index, leg in enumerate(legs):
        origin, destination = str(leg[0]).upper(), str(leg[1]).upper()
        if first is not None and index == 0 and via:
            out.extend(journey_hours(origin, destination, via))
        elif first is not None and via and (origin, destination) == (str(first[1]).upper(), str(first[0]).upper()):
            out.extend(journey_hours(origin, destination, list(reversed(via))))
        else:
            out.append(estimate_hours(origin, destination))
    return out
