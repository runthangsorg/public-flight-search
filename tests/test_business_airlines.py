"""No business class on low-cost carriers or Air India (owner, 27 Oct 2026).

The first business-deals mail led with IndiGo AMS-DEL; the owner does not want business class on
low-cost carriers or on Air India. Synthetic offers only.
"""

from __future__ import annotations

import unittest

from public_flight_search import business_deals as bd
from public_flight_search.business_airlines import excluded_airline
from public_flight_search.engine import FlightOffer

from tests.test_business_deals import DEP, raw_config
from tests.test_business_row import UNCAPPED, _base_card, _business_option, _fare, _load


def _offer(price, airline):
    return FlightOffer.from_mapping({
        "origin": "LHR", "destination": "BKK", "departure": f"{DEP}T10:00:00", "price": price,
        "currency": "GBP", "stops": 1, "duration_minutes": 800, "provider": "Google Flights",
        "booking_url": "https://example.test/LHR-BKK", "airline": airline,
    })


class TheListTests(unittest.TestCase):
    def test_low_cost_carriers_and_air_india_are_named(self):
        for names, hit in ((("IndiGo",), "IndiGo"), ("Air India Express", "Air India Express"),
                           ("Lufthansa, Air India", "Air India"), (("flydubai",), "flydubai"), (("LOT",), "LOT")):
            with self.subTest(names=names):
                self.assertEqual(excluded_airline(names), hit)

    def test_full_service_airlines_are_not(self):
        for names in (("Etihad Airways",), ("Qatar Airways",), ("Air Indiana",), ()):
            with self.subTest(names=names):
                self.assertEqual(excluded_airline(names), "")


class TheDealsJobTests(unittest.TestCase):
    def test_an_indigo_business_fare_is_rejected_and_the_next_one_kept(self):
        cfg = bd.load_config(raw_config(), today=bd.date(2027, 1, 15))
        spec = bd.SearchSpec("LHR", "BKK", DEP)
        row, rejected = bd.cheapest_observation(
            [_offer(646, "IndiGo"), _offer(900, "Air India"), _offer(1118, "LOT"), _offer(1300, "Qatar Airways")], spec, cfg,
            bd.datetime(2027, 1, 15, tzinfo=bd.timezone.utc))
        self.assertEqual((row["airline"], row["fare_gbp"], rejected), ("Qatar Airways", 1300.0, 3))

    def test_the_config_can_add_an_airline_and_is_validated(self):
        cfg = bd.load_config(raw_config(exclude_airlines=["Gulf Air"]), today=bd.date(2027, 1, 15))
        self.assertEqual(cfg.exclude_airlines, ("Gulf Air",))
        self.assertIsNone(bd._accept(_offer(1118, "Gulf Air"), bd.SearchSpec("LHR", "BKK", DEP), cfg))
        with self.assertRaises(bd.BusinessDealsConfigError):
            bd.load_config(raw_config(exclude_airlines="IndiGo"), today=bd.date(2027, 1, 15))


class ThePlannerTests(unittest.TestCase):
    def test_a_business_read_on_air_india_never_prices_the_business_row(self):
        config, base = _base_card()
        pair = (base.outbound_date, base.return_date)
        records = _load(config, [_fare(base.destination_airport, cabin="BUSINESS", total=9_000.0, stops=1,
                                       carrier="Air India", pair=pair, origin=base.origin)])
        deal = bd_collect(config, records)
        self.assertTrue(_business_option(deal)["not_priced"])

    def test_economy_on_the_same_airline_is_still_evidence(self):
        config, base = _base_card()
        pair = (base.outbound_date, base.return_date)
        records = _load(config, [_fare(base.destination_airport, cabin="ECONOMY", total=4_000.0, stops=1,
                                       carrier="Air India", pair=pair, origin=base.origin)])
        self.assertTrue(records)


def bd_collect(config, records):
    from public_flight_search.holidays import collect_holiday_deals

    return collect_holiday_deals(config, max_budget_gbp=UNCAPPED, live_flight_offers=records)[0]


if __name__ == "__main__":
    unittest.main()
