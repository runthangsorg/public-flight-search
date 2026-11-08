"""Layout tests lay out pages, not the 8-hour leg rule (owner rule 4, 8 Nov 2026).

Their synthetic Economy reads state one journey and no per-flight durations, so under the rule they would not be offered
and the page under test would be empty. ``lift_leg_rule`` switches the Economy gate off for a test module the way the
retired premium cap was lifted for the both-cabins tests; the rule itself is tested in ``test_business_over_eight_hours``.
"""

from unittest.mock import patch

from public_flight_search import cabin


def lift_leg_rule():
    return patch.object(cabin, "economy_allowed", lambda legs: True)
