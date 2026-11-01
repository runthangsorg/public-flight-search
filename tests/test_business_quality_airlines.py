"""Business deals: show the good airline, not just the cheapest fare (owner, 1 Nov 2026).

The 1 Nov box mail led with EgyptAir AMS-NBO at about £1,806 per person when Qatar Airways was about
£1,829 on the same page, and "Qatar has a much superior business class". The watcher keeps the cheapest
acceptable fare per search; with ``airline_quality`` configured it also keeps the cheapest tier-1 fare and
leads with it when it costs at most ``quality_premium_pct`` more per person. Same rule as dealsearch 6c7acf4.
"""

from __future__ import annotations

import json
import unittest

from public_flight_search import business_deals as bd
from public_flight_search.business_airlines import airline_tier
from public_flight_search.engine import FlightOffer

from test_business_deals import EXAMPLE, NOW, JobCase, raw_config

DEP, RET = "2027-03-01", "2027-03-15"
TIER_1 = ["Qatar Airways", "Emirates", "Etihad", "Singapore Airlines", "Cathay Pacific", "ANA", "JAL",
          "EVA Air", "Turkish Airlines", "Virgin Atlantic", "British Airways", "Kenya Airways", "Ethiopian"]


def nbo_config(**over):
    base = raw_config(
        destinations=[{"code": "NBO", "label": "Nairobi", "region": "africa", "hours_from_london": 8.5}],
        absolute_caps_gbp={"africa": 2500}, trip_nights=[14], travellers=5,
        airline_quality={"tier_1": TIER_1, "banned": ["Air India", "Air India Express", "LOT", "EgyptAir"]},
        quality_premium_pct=10,
    )
    base.update(over)
    return base


def nbo_offer(price, airline, *, origin="LHR", duration=1000, stops=1):
    return FlightOffer.from_mapping({
        "origin": origin, "destination": "NBO", "departure": f"{DEP}T10:00:00", "price": price,
        "currency": "GBP", "stops": stops, "duration_minutes": duration, "provider": "Google Flights",
        "booking_url": f"https://example.test/{origin}-NBO/{airline.replace(' ', '-')}", "airline": airline,
    })


def fetch_offers(by_origin):
    def fetch(spec):
        return bd.FetchOutcome("ok", [o for o in by_origin.get(spec.origin, ())])
    return fetch


class AirlineTierTests(unittest.TestCase):
    def test_tier_one_carrier(self):
        self.assertEqual(airline_tier("Qatar Airways", TIER_1), 1)

    def test_other_carrier_is_tier_two(self):
        self.assertEqual(airline_tier("Iberia", TIER_1), 2)

    def test_mixed_itinerary_takes_the_worst_carrier(self):
        self.assertEqual(airline_tier("Qatar Airways, Iberia", TIER_1), 2)
        self.assertEqual(airline_tier("Qatar Airways, British Airways", TIER_1), 1)

    def test_whole_words_only(self):
        self.assertEqual(airline_tier("ANA", TIER_1), 1)
        self.assertEqual(airline_tier("Panama Airways", TIER_1), 2)

    def test_no_tier_list_means_everyone_is_tier_two(self):
        self.assertEqual(airline_tier("Qatar Airways", ()), 2)


class ConfigTests(unittest.TestCase):
    def test_example_config_carries_the_owner_tiers(self):
        cfg = bd.load_config(EXAMPLE.read_text(encoding="utf-8"), today=NOW.date())
        self.assertIn("Qatar Airways", cfg.tier_1_airlines)
        self.assertEqual(cfg.quality_premium_pct, 10)
        self.assertIn("EgyptAir", cfg.exclude_airlines)

    def test_banned_names_join_the_exclusions(self):
        cfg = bd.load_config(nbo_config(airline_quality={"tier_1": TIER_1, "banned": ["Kulula"]}),
                             today=NOW.date())
        self.assertIn("Kulula", cfg.exclude_airlines)

    def test_unknown_quality_key_is_refused(self):
        with self.assertRaises(bd.BusinessDealsConfigError):
            bd.load_config(nbo_config(airline_quality={"tier_one": TIER_1}), today=NOW.date())

    def test_without_airline_quality_nothing_changes(self):
        cfg = bd.load_config(raw_config(), today=NOW.date())
        self.assertEqual(cfg.tier_1_airlines, ())


class QualityHeadlineTests(JobCase):
    def run_nbo(self, offers, **over):
        cfg = bd.load_config(nbo_config(**over), today=NOW.date())
        out = []
        result = bd.run_job(cfg, history_path=self.history, alerts_path=self.alerts, now=NOW,
                            fetch=fetch_offers({"LHR": offers}), send=lambda s, h, text="": out.append((s, h, text)),
                            print_details=False)
        return result, out

    def test_owner_fixture_egyptair_banned_qatar_leads(self):
        """1 Nov Kayak AMS-NBO for 5: EgyptAir £8,478, Qatar £9,145, Iberia £9,145."""
        result, mails = self.run_nbo([nbo_offer(8478, "EgyptAir"), nbo_offer(9145, "Qatar Airways"),
                                      nbo_offer(9145, "Iberia")])
        self.assertEqual(len(result.deals), 1)
        deal = result.deals[0]
        self.assertEqual(deal.airline, "Qatar Airways")
        self.assertEqual(deal.per_person_gbp, 1829.0)
        self.assertNotIn("EgyptAir", mails[0][2])
        self.assertNotIn("Iberia", mails[0][2], "Iberia is listed only when it is cheaper than Qatar")

    def test_tier_one_within_premium_leads_with_the_cheapest_named(self):
        result, mails = self.run_nbo([nbo_offer(9000, "Iberia"), nbo_offer(9145, "Qatar Airways")])
        deal = result.deals[0]
        self.assertEqual(deal.airline, "Qatar Airways")
        self.assertEqual(deal.total_gbp, 9145.0)
        self.assertIn("cheapest: Iberia £1,800 pp", mails[0][2])
        self.assertIn("cheapest: Iberia £1,800 pp", mails[0][1])

    def test_tier_one_over_premium_keeps_the_cheapest_and_names_tier_one(self):
        result, mails = self.run_nbo([nbo_offer(8000, "Iberia"), nbo_offer(9145, "Qatar Airways")])
        deal = result.deals[0]
        self.assertEqual(deal.airline, "Iberia")
        self.assertIn("best tier-1: Qatar Airways £1,829 pp", mails[0][2])

    def test_premium_is_configurable(self):
        result, _ = self.run_nbo([nbo_offer(8000, "Iberia"), nbo_offer(9145, "Qatar Airways")],
                                 quality_premium_pct=20)
        self.assertEqual(result.deals[0].airline, "Qatar Airways")

    def test_tier_one_over_the_cap_is_not_promoted(self):
        """The headline must itself be a deal: a tier-1 fare over the cap stays a note."""
        result, mails = self.run_nbo([nbo_offer(9000, "Iberia"), nbo_offer(9145, "Qatar Airways")],
                                     absolute_caps_gbp={"africa": 1810})
        self.assertEqual(result.deals[0].airline, "Iberia")
        self.assertIn("best tier-1: Qatar Airways £1,829 pp", mails[0][2])

    def test_mixed_itinerary_is_not_tier_one(self):
        result, _ = self.run_nbo([nbo_offer(9000, "Iberia"), nbo_offer(9100, "Qatar Airways, Iberia")])
        self.assertEqual(result.deals[0].airline, "Iberia")

    def test_history_keeps_one_row_per_search_at_the_cheapest(self):
        self.run_nbo([nbo_offer(9000, "Iberia"), nbo_offer(9145, "Qatar Airways")])
        rows = [json.loads(line) for line in self.history.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["total_gbp"], 9000.0)
        self.assertNotIn("tier_1_option", rows[0])

    def test_alert_records_the_cheapest_so_tomorrow_does_not_refire(self):
        offers = [nbo_offer(9000, "Iberia"), nbo_offer(9145, "Qatar Airways")]
        self.run_nbo(offers)
        alert = json.loads(self.alerts.read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(alert["per_person_gbp"], 1800.0)
        again, mails = self.run_nbo(offers)
        self.assertEqual(again.deals, [])

    def test_without_airline_quality_the_cheapest_still_leads(self):
        result, _ = self.run_nbo([nbo_offer(9000, "Iberia"), nbo_offer(9145, "Qatar Airways")],
                                 **{"airline_quality": None})
        self.assertEqual(result.deals[0].airline, "Iberia")


if __name__ == "__main__":
    unittest.main()
