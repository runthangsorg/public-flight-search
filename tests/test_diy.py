import unittest

from public_flight_search import diy


def fixture_option(**overrides) -> diy.DiyOption:
    base = dict(
        flight_total_gbp=1150.0,
        flight_carrier="easyJet / Jet2 / Ryanair",
        flight_url="https://www.google.com/travel/flights/search?tfs=abc",
        destination_airport="FUE",
        outbound_date="2026-12-22",
        return_date="2026-12-30",
        adults=5,
        hotel_total_gbp=1520.0,
        hotel_name="Sample Bay Resort",
        hotel_url="https://example.test/resort",
        nights=8,
        uk_ground_gbp=16.5,
        transfer_gbp=15.0,
    )
    base.update(overrides)
    return diy.build_diy_option(**base)


class DiyArithmeticTests(unittest.TestCase):
    def test_total_is_the_sum_of_its_parts(self):
        option = fixture_option()
        self.assertEqual(option.total_gbp, 1150.0 + 1520.0 + 16.5 + 15.0)

    def test_total_moves_when_the_fare_moves(self):
        # The D2D rule: a total that does not recompute when the fare changes
        # is a cached lie. Same trip, dearer flight, bigger total.
        cheap = fixture_option(flight_total_gbp=1150.0)
        dear = fixture_option(flight_total_gbp=1450.0)
        self.assertEqual(round(dear.total_gbp - cheap.total_gbp, 2), 300.0)

    def test_ground_legs_are_omitted_when_zero_not_shown_as_free(self):
        option = fixture_option(uk_ground_gbp=0.0, transfer_gbp=0.0)
        self.assertEqual(len(option.components), 2)
        self.assertEqual(option.total_gbp, 2670.0)

    def test_confidence_is_the_weakest_component(self):
        # One live fare does not make a benchmark room rate verified.
        option = fixture_option(flight_confidence="verified-exact-date")
        self.assertEqual(option.confidence, "market-supported")

    def test_all_verified_components_give_a_verified_total(self):
        option = diy.build_diy_option(
            flight_total_gbp=900.0,
            flight_carrier="Jet2",
            flight_url="https://www.jet2.com/",
            destination_airport="FUE",
            outbound_date="2026-12-22",
            return_date="2026-12-30",
            adults=5,
            hotel_total_gbp=1000.0,
            hotel_name="Sample Bay Resort",
            hotel_url="https://example.test/resort",
            nights=8,
            flight_confidence="verified-exact-date",
            hotel_confidence="verified-exact-date",
        )
        self.assertEqual(option.confidence, "verified-exact-date")


class DiyVersusPackageTests(unittest.TestCase):
    def test_self_create_cheaper_is_stated_with_the_difference(self):
        comparison = diy.DiyComparison(diy_total_gbp=2701.5, package_total_gbp=2950.5)
        self.assertEqual(comparison.delta_gbp, 249.0)
        self.assertEqual(comparison.winner, "diy")
        self.assertIn("self-create is £249 cheaper", comparison.statement)

    def test_package_cheaper_is_stated_the_other_way_round(self):
        comparison = diy.DiyComparison(diy_total_gbp=3100.0, package_total_gbp=2950.0)
        self.assertEqual(comparison.delta_gbp, -150.0)
        self.assertEqual(comparison.winner, "package")
        self.assertIn("the package is £150 cheaper", comparison.statement)

    def test_level_is_level(self):
        comparison = diy.DiyComparison(diy_total_gbp=2950.0, package_total_gbp=2950.0)
        self.assertEqual(comparison.winner, "level")
        self.assertIn("level", comparison.statement)

    def test_unpriced_package_declares_no_winner(self):
        # A constructed vendor link is not a quote. With no observed package
        # total the card must say so rather than invent a comparison.
        comparison = diy.DiyComparison(diy_total_gbp=2701.5, package_total_gbp=None)
        self.assertIsNone(comparison.delta_gbp)
        self.assertEqual(comparison.winner, "unknown")
        self.assertIn("package price not verified", comparison.statement)
        self.assertIn("2,702", comparison.statement)


class TerminologyTests(unittest.TestCase):
    def test_nonstop_only_where_route_authority_was_verified(self):
        self.assertEqual(
            diy.trajectory_label(destination_airport="FUE", carrier="easyJet / Jet2"),
            "Nonstop",
        )

    def test_unverified_airport_never_claims_nonstop(self):
        label = diy.trajectory_label(destination_airport="MCT", carrier="Oman Air")
        self.assertEqual(label, diy.TRAJECTORY_UNVERIFIED)
        self.assertNotIn("Nonstop", label)

    def test_unauthorised_carrier_on_a_known_airport_is_not_nonstop(self):
        self.assertEqual(
            diy.trajectory_label(destination_airport="FUE", carrier="Emirates"),
            diy.TRAJECTORY_UNVERIFIED,
        )

    def test_the_bare_word_direct_is_never_emitted(self):
        option = fixture_option()
        comparison = diy.DiyComparison(diy_total_gbp=option.total_gbp, package_total_gbp=None)
        blob = " ".join(
            [c.label + " " + c.channel + " " + c.note for c in option.components]
            + [comparison.statement]
        )
        for word in blob.replace(",", " ").split():
            self.assertNotEqual(word.strip(".·").lower(), "direct", blob)

    def test_airline_host_is_airline_direct_and_metasearch_is_an_intermediary(self):
        self.assertEqual(diy.flight_channel("https://www.jet2.com/"), diy.AIRLINE_DIRECT)
        self.assertEqual(
            diy.flight_channel("https://www.google.com/travel/flights"),
            diy.OTA_INTERMEDIARY,
        )

    def test_a_brand_inside_a_hostile_hostname_is_not_airline_direct(self):
        self.assertEqual(
            diy.flight_channel("https://www.jet2.com.attacker.example/book"),
            diy.OTA_INTERMEDIARY,
        )

    def test_airline_booking_page_becomes_primary_and_metasearch_stays_dated(self):
        option = fixture_option(airline_booking_url="https://www.easyjet.com/en/buy/flights")
        flight = option.components[0]
        self.assertEqual(flight.channel, diy.AIRLINE_DIRECT)
        self.assertEqual(flight.dated_search_channel, diy.OTA_INTERMEDIARY)
        self.assertIn("tfs=", flight.dated_search_url)


if __name__ == "__main__":
    unittest.main()
