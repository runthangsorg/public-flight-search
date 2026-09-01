"""Ground transport assumptions for door-to-door cost modeling.

All values are estimates requiring checkout-day revalidation. Sources cited
where available; confidence levels: HIGH/MEDIUM/LOW per assumption.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Any


@dataclass(frozen=True)
class GroundAssumption:
    """A single ground transport assumption with provenance."""
    minutes: int
    cost_gbp: float
    source: str
    observed_at: str
    confidence: str  # HIGH, MEDIUM, LOW
    variability_minutes: int = 0
    note: str = ""


WATFORD_ANCHOR = "Watford, UK"
ASSUMPTION_OBSERVED_AT = "2026-08-26T00:00:00+00:00"

GROUND_ASSUMPTIONS: Dict[str, GroundAssumption] = {
    "WATFORD_LHR": GroundAssumption(
        minutes=45,
        cost_gbp=3.0,
        source="Legacy calibrated local estimate; RailAir/public-transport fare requires recheck",
        observed_at=ASSUMPTION_OBSERVED_AT,
        confidence="LOW",
    ),
    "WATFORD_LGW": GroundAssumption(
        minutes=90,
        cost_gbp=20.0,
        source="Legacy calibrated local estimate via central London",
        observed_at=ASSUMPTION_OBSERVED_AT,
        confidence="LOW",
    ),
    "WATFORD_LTN": GroundAssumption(
        minutes=35,
        cost_gbp=30.0,
        source="Legacy calibrated taxi estimate",
        observed_at=ASSUMPTION_OBSERVED_AT,
        confidence="LOW",
    ),
    "WATFORD_STN": GroundAssumption(
        minutes=75,
        cost_gbp=72.0,
        source="Legacy calibrated taxi/public-transport estimate",
        observed_at=ASSUMPTION_OBSERVED_AT,
        confidence="LOW",
    ),
    "GROSVENOR_DXB": GroundAssumption(
        minutes=35,
        cost_gbp=24.0,
        variability_minutes=15,
        source="https://www.rta.ae/wps/portal/rta/ae/home/promotion/taxi-fare (route time/cost estimated from RTA tariff)",
        observed_at=ASSUMPTION_OBSERVED_AT,
        confidence="MEDIUM",
    ),
    "GROSVENOR_SHJ": GroundAssumption(
        minutes=70,
        cost_gbp=38.0,
        variability_minutes=35,
        source="https://rta.ae/wps/portal/rta/ae/home/rta-services/service-details?serviceId=205 (route time estimated; includes cross-emirate traffic exposure)",
        observed_at=ASSUMPTION_OBSERVED_AT,
        confidence="LOW",
    ),
    "GROSVENOR_AUH_TAXI": GroundAssumption(
        minutes=75,
        cost_gbp=55.0,
        variability_minutes=20,
        source="Route estimate from Dubai Marina; fare and traffic require checkout-day revalidation",
        observed_at=ASSUMPTION_OBSERVED_AT,
        confidence="LOW",
    ),
    "GROSVENOR_AL_WASL": GroundAssumption(
        minutes=25,
        cost_gbp=15.0,
        variability_minutes=15,
        source="Route estimate to Etihad Al Wasl Centre pickup",
        observed_at=ASSUMPTION_OBSERVED_AT,
        confidence="LOW",
    ),
    "ETIHAD_COACH": GroundAssumption(
        minutes=120,
        cost_gbp=0.0,
        source="https://www.etihad.com/content/dam/eag/etihadairways/etihadcom/Global/pdf/etihad-shuttle/schedule-to-and-from-dxb.pdf",
        observed_at=ASSUMPTION_OBSERVED_AT,
        confidence="HIGH",
        note="Official timetable slots are 120 minutes although the service page advertises approximately 75 minutes. Requires Etihad PNR and 2h airport check-in buffer.",
    ),
    "MCT_ST_REGIS": GroundAssumption(
        minutes=15,
        cost_gbp=10.0,
        source="https://www.marriott.com/en-us/hotels/mctxr-the-st-regis-al-mouj-muscat-resort/overview/",
        observed_at=ASSUMPTION_OBSERVED_AT,
        confidence="MEDIUM",
    ),
    "MUSCAT_DUBAI_COACH": GroundAssumption(
        minutes=360,
        cost_gbp=22.0,
        source="https://api.alkhanjrygroups.com/bus-availability/2/0 (OMR 10 fare and departures; elapsed time estimated)",
        observed_at=ASSUMPTION_OBSERVED_AT,
        confidence="LOW",
    ),
    "DUBAI_COACH_GROSVENOR": GroundAssumption(
        minutes=35,
        cost_gbp=20.0,
        source="Estimated Dubai coach drop-off to Grosvenor House taxi; exact drop-off and traffic require recheck",
        observed_at=ASSUMPTION_OBSERVED_AT,
        confidence="LOW",
    ),
}


def get_ground_assumptions() -> Dict[str, GroundAssumption]:
    return dict(GROUND_ASSUMPTIONS)


def watford_to_airport(airport: str) -> GroundAssumption | None:
    """Get Watford to London airport ground assumption."""
    key = f"WATFORD_{airport.upper()}"
    return GROUND_ASSUMPTIONS.get(key)


def hotel_to_uae_airport(hotel: str, airport: str) -> GroundAssumption | None:
    """Get UAE hotel to airport ground assumption."""
    if hotel.upper() == "GROSVENOR" and airport in ("DXB", "SHJ", "AUH"):
        if airport == "DXB":
            return GROUND_ASSUMPTIONS["GROSVENOR_DXB"]
        if airport == "SHJ":
            return GROUND_ASSUMPTIONS["GROSVENOR_SHJ"]
        if airport == "AUH":
            # Return both options for AUH (taxi vs coach)
            return GROUND_ASSUMPTIONS["GROSVENOR_AUH_TAXI"]
    return None


def etihad_coach_option() -> GroundAssumption:
    """Get Etihad coach option for AUH from Grosvenor via Al Wasl."""
    return GROUND_ASSUMPTIONS["ETIHAD_COACH"]


def muscat_to_dubai_coach() -> GroundAssumption:
    """Get Muscat to Dubai coach assumption."""
    return GROUND_ASSUMPTIONS["MUSCAT_DUBAI_COACH"]


def st_regis_to_mct() -> GroundAssumption:
    """Get St Regis Al Mouj to MCT airport."""
    return GROUND_ASSUMPTIONS["MCT_ST_REGIS"]


def dubai_coach_to_grosvenor() -> GroundAssumption:
    """Dubai coach drop-off to Grosvenor House."""
    return GROUND_ASSUMPTIONS["DUBAI_COACH_GROSVENOR"]