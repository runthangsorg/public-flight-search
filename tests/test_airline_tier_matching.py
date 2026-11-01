"""Tier-1 matching reads carriers the way the pages write them (owner, 1 Nov 2026).

Two gaps in the first cut. Google Flights names carriers in full ("Japan Airlines", "All Nippon
Airways") while ``airline_quality`` may hold the short code ("JAL", "ANA"), and a tier name shorter
than the carrier never matched, so those fares were silently never tier-1. And a carrier string
written in prose ("Emirates and flydubai") was one carrier, so a mixed itinerary could score tier-1
and could dodge a ban. Synthetic strings only: no network, no browser.
"""

from __future__ import annotations

import unittest

from public_flight_search.business_airlines import (
    airline_tier,
    carrier_banned,
    carrier_named,
    excluded_airline,
    split_airlines,
)

T1 = ["Qatar Airways", "Emirates", "Etihad", "British Airways", "JAL", "ANA", "Kenya Airways"]


class AliasTests(unittest.TestCase):
    def test_a_short_code_and_the_full_name_are_the_same_carrier(self):
        pairs = (("JAL", "Japan Airlines"), ("ANA", "All Nippon Airways"))
        for short, full in pairs:
            for carrier, tier in ((short, [short]), (full, [short]), (short, [full]), (full, [full])):
                with self.subTest(carrier=carrier, tier=tier):
                    self.assertEqual(airline_tier(carrier, tier), 1)

    def test_the_example_configs_short_codes_score_the_full_names(self):
        self.assertEqual(airline_tier("Japan Airlines", T1), 1)
        self.assertEqual(airline_tier("All Nippon Airways", T1), 1)

    def test_a_word_that_only_contains_the_code_is_not_the_carrier(self):
        for carrier in ("Panama Airways", "Company Air", "Jalisco Airways"):
            with self.subTest(carrier=carrier):
                self.assertEqual(airline_tier(carrier, T1), 2)
                self.assertEqual(airline_tier(carrier, ["ANA"]), 2)

    def test_a_mixed_itinerary_with_an_alias_carrier_takes_the_worst(self):
        self.assertEqual(airline_tier("Japan Airlines, Iberia", T1), 2)
        self.assertEqual(airline_tier("All Nippon Airways, Japan Airlines", T1), 1)


class CarrierSplitTests(unittest.TestCase):
    def test_prose_separates_carriers_for_a_tier(self):
        for carriers in ("Qatar Airways and Iberia", "Qatar Airways; Iberia",
                         "Qatar Airways (operated by Iberia)", "Qatar Airways / Iberia",
                         "Qatar Airways + Iberia", "Qatar Airways & Iberia"):
            with self.subTest(carriers=carriers):
                self.assertEqual(airline_tier(carriers, T1), 2)

    def test_every_carrier_tier_one_still_leads(self):
        for carriers in ("Qatar Airways, British Airways", "Qatar Airways and British Airways",
                         "Qatar Airways; Emirates", "Qatar Airways (British Airways)"):
            with self.subTest(carriers=carriers):
                self.assertEqual(airline_tier(carriers, T1), 1)

    def test_the_split_names_the_carriers(self):
        self.assertEqual(split_airlines("Emirates and flydubai"), ["Emirates", "flydubai"])
        self.assertEqual(split_airlines("Qatar Airways (operated by Iberia)"),
                         ["Qatar Airways", "operated by Iberia"])
        self.assertEqual(split_airlines(("Emirates", " Qatar Airways ")), ["Emirates", "Qatar Airways"])

    def test_a_ban_is_not_dodged_by_prose(self):
        for carriers in ("Emirates and flydubai", "Emirates; flydubai", "Emirates / flydubai",
                         "Emirates + flydubai", "Emirates & flydubai", "Emirates (flydubai)"):
            with self.subTest(carriers=carriers):
                self.assertIn(excluded_airline(carriers), ("flydubai",))
                self.assertTrue(carrier_banned("flydubai", ("Air India", "flydubai")))

    def test_an_operated_by_a_banned_carrier_is_banned(self):
        self.assertEqual(excluded_airline("Emirates (operated by flydubai)"), "operated by flydubai")


class OnlyTheseDelimitersWereAddedTests(unittest.TestCase):
    """``excluded_airline`` filters live fares (``metasearch.usable_options``, ``business_deals._accept``).

    An input that carries none of the new delimiters (";", the word "and", "(") must return exactly
    what it did before this change: only delimiters were added, nothing was removed or reordered.
    """

    def test_the_pre_existing_inputs_return_what_they_did(self):
        cases = (
            (("IndiGo",), "IndiGo"),
            (("Air India",), "Air India"),
            (("Air India Express",), "Air India Express"),
            (("Lufthansa", "Air India"), "Air India"),
            ("Air India Express", "Air India Express"),
            ("Lufthansa, Air India", "Air India"),
            ("Vueling, Air India", "Vueling"),
            ("IndiGo/Air India", "IndiGo"),
            ("Air India/LOT", "Air India"),
            ("LOT+IndiGo", "LOT"),
            ("LOT&IndiGo", "LOT"),
            ("Qatar Airways / British Airways + Emirates & Iberia", ""),
            ("Air India, Qatar Airways, LOT", "Air India"),
            ("Air Indiana", ""),
            ("Air Indiaa", ""),
            ("Display Air", ""),
            (("Lufthansa", "Qatar Airways"), ""),
            ((), ""),
            ("", ""),
        )
        for names, expected in cases:
            with self.subTest(names=names):
                self.assertEqual(excluded_airline(names), expected)

    def test_a_legacy_split_is_unchanged(self):
        self.assertEqual(split_airlines("Vueling, Air India"), ["Vueling", "Air India"])
        self.assertEqual(split_airlines("AirAsia X"), ["AirAsia X"])
        self.assertEqual(split_airlines("Air India"), ["Air India"])

    def test_the_config_extra_list_still_bans(self):
        self.assertEqual(excluded_airline(("Gulf Air",), extra=("Gulf Air",)), "Gulf Air")
        self.assertEqual(excluded_airline("Lufthansa, Gulf Air", extra=("Gulf Air",)), "Gulf Air")
        self.assertFalse(carrier_banned("Gulf Air", ()))
        self.assertTrue(carrier_named("Gulf Air", ("Gulf Air",)))


if __name__ == "__main__":
    unittest.main()
