"""Cabin policy: BUSINESS only on a NONSTOP London flight over 8 hours.

Two owner rules, the second narrowing the first.

Rule 1 (2026-09-28): no premium economy as a DESTINATION'S HEADLINE cabin, and
BUSINESS only for a flight OVER 8 hours from London; everything else is
ECONOMY. The boundary is derived in code (``cabin.py``) from each
destination's ``flight_hours``, so a config can no longer price a four-hour
hop in Business, as the July 2027 example did.

Rule 2 (2026-10-04, verbatim from ``cabin.py``): "you should only quote
business class for direct flights, else always quote economy for when its 1
stopover". NONSTOP is therefore a NECESSARY condition, and it is SEASONAL, so
it lives on the config destination as ``nonstop_from_london`` with a
``nonstop_source`` naming who said so and when it was read.

The rule this whole file exists to hold: **UNKNOWN MEANS NOT NONSTOP**. A
destination that says nothing about a nonstop is ECONOMY, never Business.
Pinned boundary: 7.9 h -> ECONOMY, 8.1 h -> BUSINESS, and 8.0 h exactly is not
OVER eight hours, so ECONOMY.

Owner direction 2026-09-30: Premium Economy IS now shown as a reader-visible
comparison row in the per-card "Flight options" breakdown (business/economy/
premium-economy/stopover, side by side) — that is a different thing from the
headline cabin this rule governs, and does not reopen it.
"""

import dataclasses
import json
import unittest
from pathlib import Path

from public_flight_search.cabin import (
    DEFAULT_FLIGHT_HOURS_LHR,
    YEAR_ROUND_NONSTOP_LHR,
    cabin_for_flight_hours,
    destination_cabin,
    is_long_haul_route,
    resolve_nonstop_from_london,
)
from public_flight_search.config import ConfigError
from public_flight_search.holidays import (
    FAR_EAST_PRICE_LABEL,
    FAR_EAST_WATCH,
    collect_holiday_deals,
    destination_cabins,
    far_east_watch_rows,
    load_holiday_config,
    priceable_date_pairs,
    priced_date_pair,
    render_far_east_watch,
    render_holiday_report,
    shortlist_date_pairs,
)

ROOT = Path(__file__).parents[1]
EXAMPLES = ROOT / "examples"
DEC = EXAMPLES / "dec_holiday_config.json"
JULY = EXAMPLES / "july_holiday_config.json"

#: Every destination the planners carried before 2026-09-28. All are under
#: eight hours from London, so every one must now price ECONOMY.
PRE_RULE_DESTINATIONS = {
    "antalya", "malta", "taghazout", "hurghada", "cairo", "muscat", "doha",
    "tenerife", "madeira", "lanzarote", "cape_verde", "fuerteventura",
    "gran_canaria", "paphos",
}
#: Langkawi, Penang and Singapore left with Malaysia/Singapore on 2026-10-02.
#: Okinawa joined the December watch on 2026-10-04 (H9) but is listed OUT of its
#: season there, so it is not in this list: see the out-of-season test below.
FAR_EAST_DECEMBER = ["phuket", "krabi", "phu_quoc"]
#: The December watch row that is deliberately outside its season.
FAR_EAST_DECEMBER_OUT_OF_SEASON = ["okinawa"]
#: July since 2026-09-29: Lombok and Thailand lead (resort cards, no watch
#: row), then the watch destinations. Kota Kinabalu left with Malaysia. H9
#: (2026-10-04) replaced Tokyo with Okinawa, which now carries real resort
#: cards, and added the Riviera Maya at the end.
LONG_HAUL_JULY = ["lombok", "koh_samui", "koh_phangan", "khao_lak", "zanzibar", "bali", "da_nang", "okinawa", "riviera_maya"]
#: Watch rows only: bali and da_nang. Okinawa has catalogue resorts in July, so
#: it is priced as real cards and NOT repeated as an unverified watch row.
FAR_EAST_JULY = ["bali", "da_nang"]

#: Destinations whose LONDON TIME is genuinely seasonal, so the built-in
#: table (which has no season) cannot mirror both configs. Cancún is a Virgin
#: Atlantic nonstop, 11h01, from 18 Oct 2026 to 11 Apr 2027: December sits
#: inside that season, June/July 2027 does not, so the two configs state their
#: own hours. Every other destination must match the table exactly, which is
#: what stops the table drifting away from the configs.
SEASON_DEPENDENT_HOURS = frozenset({"riviera_maya"})


def _payload(destinations, **root):
    payload = {
        "report_title": "Cabin test", "party": {"travellers": 5, "rooms": [2, 2, 1]},
        "departure_window": ["06:00", "23:59"], "origins": ["LHR"],
        "outbound_dates": ["2026-12-22"], "return_dates": ["2026-12-30"],
        "destinations": destinations,
    }
    payload.update(root)
    return json.dumps(payload)


class BoundaryTests(unittest.TestCase):
    def test_7_9_hours_is_economy(self):
        self.assertEqual(cabin_for_flight_hours(7.9, True), "ECONOMY")

    def test_8_1_hours_is_business(self):
        self.assertEqual(cabin_for_flight_hours(8.1, True), "BUSINESS")

    def test_exactly_8_hours_is_economy(self):
        self.assertEqual(cabin_for_flight_hours(8.0, True), "ECONOMY")


class NonstopConditionTests(unittest.TestCase):
    """The brief's six cases for decision 1, one test each."""

    def test_a_nonstop_eleven_hour_flight_is_business(self):
        self.assertEqual(cabin_for_flight_hours(11.0, True), "BUSINESS")

    def test_a_one_stop_fourteen_and_a_half_hour_journey_is_economy(self):
        # Over eight hours by nearly double, and still economy: the owner's rule
        # is about DIRECTNESS first and duration second.
        self.assertEqual(cabin_for_flight_hours(14.5, False), "ECONOMY")

    def test_a_nonstop_six_and_three_quarter_hour_flight_is_economy(self):
        # Doha, the owner's own words: "doha and muscat economy is fine".
        self.assertEqual(cabin_for_flight_hours(6.75, True), "ECONOMY")

    def test_a_stopover_itinerary_is_economy(self):
        # "stop at oman on way out 2d, go thailand, then return 2d oman". The
        # hub stopover is two extra flights and four nights, never a nonstop.
        self.assertEqual(cabin_for_flight_hours(14.5, False), "ECONOMY")
        self.assertFalse(is_long_haul_route(4.0))

    def test_a_missing_nonstop_is_economy(self):
        # Unknown means not nonstop. This is the guard that stops the old bug.
        self.assertEqual(cabin_for_flight_hours(11.0), "ECONOMY")
        self.assertEqual(cabin_for_flight_hours(11.0, None), "ECONOMY")

    def test_the_same_key_is_nonstop_in_one_config_and_not_in_another(self):
        nonstop = load_holiday_config(_payload([
            {"key": "riviera_maya", "label": "Cancún", "airports": ["CUN"],
             "flight_hours": 11.02, "nonstop_from_london": True,
             "nonstop_source": "test: Virgin Atlantic, 18 Oct 2026 - 11 Apr 2027"},
        ]))
        one_stop = load_holiday_config(_payload([
            {"key": "riviera_maya", "label": "Cancún", "airports": ["CUN"],
             "flight_hours": 17.0, "nonstop_from_london": False,
             "nonstop_source": "test: the seasonal service has ended by July"},
        ]))
        self.assertEqual(destination_cabin(nonstop.destinations[0]), "BUSINESS")
        self.assertEqual(destination_cabin(one_stop.destinations[0]), "ECONOMY")
        # ...and the same key with nothing said at all is economy too.
        silent = load_holiday_config(_payload([
            {"key": "riviera_maya", "label": "Cancún", "airports": ["CUN"],
             "flight_hours": 11.02},
        ]))
        self.assertEqual(destination_cabin(silent.destinations[0]), "ECONOMY")

    def test_premium_economy_is_never_derived(self):
        for hours in (1.0, 4.5, 7.9, 8.0, 8.1, 13.0, 17.25):
            for nonstop in (True, False, None):
                with self.subTest(hours=hours, nonstop=nonstop):
                    self.assertIn(
                        cabin_for_flight_hours(hours, nonstop),
                        {"ECONOMY", "BUSINESS"},
                    )

    def test_missing_or_bad_hours_refuse_to_guess(self):
        for bad in (None, 0, -1, "long"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                cabin_for_flight_hours(bad, True)

    def test_a_nonstop_flag_that_is_not_a_boolean_is_unknown_not_yes(self):
        for typo in ("yes", 1, ["true"], {"nonstop": True}):
            with self.subTest(typo=typo):
                self.assertEqual(cabin_for_flight_hours(11.0, typo), "ECONOMY")

    def test_the_year_round_table_carries_year_round_services_only(self):
        # A seasonal nonstop must never be promoted from a built-in table,
        # because the table cannot know the season.
        self.assertNotIn("phuket", YEAR_ROUND_NONSTOP_LHR)
        self.assertNotIn("riviera_maya", YEAR_ROUND_NONSTOP_LHR)
        self.assertTrue(resolve_nonstop_from_london("phuket", None) is False)
        # Everything in the table is genuinely a London nonstop...
        for key in YEAR_ROUND_NONSTOP_LHR:
            with self.subTest(key=key):
                self.assertIn(key, DEFAULT_FLIGHT_HOURS_LHR)
        # ...and none of them is over the boundary, so the table can never be
        # the reason a route is priced Business.
        for key in YEAR_ROUND_NONSTOP_LHR:
            with self.subTest(key=key):
                self.assertLessEqual(DEFAULT_FLIGHT_HOURS_LHR[key], 8.0)


class LongHaulRouteTests(unittest.TestCase):
    def test_a_one_stop_long_journey_is_still_a_long_haul_route(self):
        # "Long haul" answers "is this a long flight?", not "do we quote
        # Business": the stopover rows only exist on long-haul routes, and the
        # owner's own rule is to fly one.
        self.assertTrue(is_long_haul_route(11.67))
        self.assertTrue(is_long_haul_route(24.0))
        self.assertFalse(is_long_haul_route(7.33))
        self.assertFalse(is_long_haul_route(None))


class LoaderDerivesTheCabinTests(unittest.TestCase):
    def test_config_business_on_a_short_hop_prices_economy(self):
        # The July example's old shape: per-destination BUSINESS on a 4h30 hop.
        config = load_holiday_config(_payload(
            [{"key": "antalya", "label": "Antalya", "airports": ["AYT"],
              "cabin_class": "BUSINESS", "flight_hours": 4.5,
              "nonstop_from_london": True}],
            cabin_class="BUSINESS", cabin_classes=["BUSINESS", "PREMIUM_ECONOMY"],
        ))
        dest = config.destinations[0]
        self.assertEqual(dest.cabin_class, "ECONOMY")
        self.assertEqual(destination_cabins(config, dest), ("ECONOMY",))
        deals = collect_holiday_deals(config)
        self.assertTrue(deals)
        self.assertEqual({d.cabin_class for d in deals}, {"ECONOMY"})

    def test_config_economy_on_a_nonstop_long_haul_prices_business(self):
        config = load_holiday_config(_payload(
            [{"key": "riviera_maya", "label": "Cancún", "airports": ["CUN"],
              "cabin_class": "ECONOMY", "flight_hours": 11.02,
              "nonstop_from_london": True,
              "nonstop_source": "test: Virgin Atlantic LHR-CUN, 18 Oct 2026 - 11 Apr 2027"}],
        ))
        self.assertEqual(destination_cabin(config.destinations[0]), "BUSINESS")

    def test_config_business_on_a_one_stop_long_haul_prices_economy(self):
        # 17 hours door to door, and the config still asks for BUSINESS. The
        # rule overrides the config, which is the whole point of deriving it.
        config = load_holiday_config(_payload(
            [{"key": "riviera_maya", "label": "Cancún", "airports": ["CUN"],
              "cabin_class": "BUSINESS", "flight_hours": 17.0,
              "nonstop_from_london": False,
              "nonstop_source": "test: the seasonal service has ended by July"}],
        ))
        self.assertEqual(destination_cabin(config.destinations[0]), "ECONOMY")

    def test_legacy_config_without_hours_uses_the_built_in_table(self):
        # The live December secret predates flight_hours and names premium
        # economy; until it is reloaded it must still load, and price ECONOMY.
        config = load_holiday_config(_payload(
            [{"key": key, "label": key, "airports": ["XXX"]} for key in sorted(PRE_RULE_DESTINATIONS)],
            cabin_class="ECONOMY", cabin_classes=["ECONOMY", "PREMIUM_ECONOMY", "BUSINESS"],
        ))
        for dest in config.destinations:
            with self.subTest(dest=dest.key):
                self.assertEqual(destination_cabins(config, dest), ("ECONOMY",))
        self.assertEqual(config.cabin_classes, ("ECONOMY",))

    def test_unknown_destination_without_hours_fails_at_load(self):
        with self.assertRaises(ConfigError):
            load_holiday_config(_payload([{"key": "atlantis", "label": "A", "airports": ["XXX"]}]))

    def test_unknown_destination_fields_are_still_rejected(self):
        with self.assertRaises(ConfigError):
            load_holiday_config(_payload(
                [{"key": "malta", "label": "Malta", "airports": ["MLA"], "flight_hours": 3.25, "price": 1}]
            ))

    def test_non_numeric_hours_are_rejected(self):
        with self.assertRaises(ConfigError):
            load_holiday_config(_payload(
                [{"key": "malta", "label": "Malta", "airports": ["MLA"], "flight_hours": "3h15"}]
            ))

    def test_a_non_numeric_nonstop_flag_is_rejected(self):
        with self.assertRaises(ConfigError):
            load_holiday_config(_payload(
                [{"key": "malta", "label": "Malta", "airports": ["MLA"],
                  "flight_hours": 3.25, "nonstop_from_london": "yes"}]
            ))

    def test_unsupported_cabin_names_still_fail_loudly(self):
        with self.assertRaises(ConfigError):
            load_holiday_config(_payload(
                [{"key": "malta", "label": "Malta", "airports": ["MLA"], "cabin_class": "LIEFLAT"}]
            ))


class JulyWindowTests(unittest.TestCase):
    """The owner's July window, and the three pairs it actually prices.

    Owner, 2026-10-04: "do not waste time effort searching outside of the 25 june
    to 31st June window for departure ... focus on that". June has 30 days, so
    the window is departures 25-30 June 2027 inclusive.
    """

    def _config(self):
        return load_holiday_config(JULY.read_text(encoding="utf-8"))

    def test_the_departure_window_is_25_to_30_june_2027(self):
        config = self._config()
        self.assertEqual(
            sorted(config.outbound_dates),
            ["2027-06-25", "2027-06-26", "2027-06-27",
             "2027-06-28", "2027-06-29", "2027-06-30"],
        )
        # Every departure is inside the window the owner named.
        for day in config.outbound_dates:
            with self.subTest(day=day):
                self.assertTrue("2027-06-25" <= day <= "2027-06-30")

    def test_the_returns_are_the_nights_band_and_two_long_stays(self):
        config = self._config()
        self.assertEqual(
            sorted(config.return_dates),
            ["2027-07-09", "2027-07-10", "2027-07-11", "2027-07-12",
             "2027-07-13", "2027-07-14", "2027-07-17", "2027-07-20"],
        )
        self.assertEqual((config.min_nights, config.max_nights), (12, 21))

    def test_the_window_fits_both_loader_guards(self):
        # 8 dates per list and 64 combinations: the window must fit the SHAPE
        # as well as the dates, or the config would not load at all. The guards
        # are unchanged — the owner's window is built to fit them.
        config = self._config()
        self.assertLessEqual(len(config.outbound_dates), 8)
        self.assertLessEqual(len(config.return_dates), 8)
        self.assertLessEqual(len(config.outbound_dates) * len(config.return_dates), 64)
        self.assertTrue(priceable_date_pairs(config))

    def test_there_are_thirty_seven_priceable_pairs(self):
        self.assertEqual(len(priceable_date_pairs(self._config())), 37)

    def test_the_shortlist_is_the_three_pairs_the_brief_names(self):
        self.assertEqual(
            shortlist_date_pairs(self._config()),
            (("2027-06-25", "2027-07-09"),    # 14 nights
             ("2027-06-27", "2027-07-14"),    # 17 nights, the headline
             ("2027-06-30", "2027-07-20")),   # 20 nights
        )

    def test_the_headline_pair_is_the_middle_one_and_is_priceable(self):
        config = self._config()
        headline = priced_date_pair(config)
        self.assertEqual(headline, ("2027-06-27", "2027-07-14"))
        self.assertIn(headline, priceable_date_pairs(config))


class CommittedConfigTests(unittest.TestCase):
    def _data(self, path):
        return json.loads(path.read_text(encoding="utf-8"))

    def test_every_destination_carries_hours_a_source_and_a_nonstop_answer(self):
        for path in (DEC, JULY):
            data = self._data(path)
            self.assertNotIn("cabin_class", data, path.name)
            self.assertNotIn("cabin_classes", data, path.name)
            for dest in data["destinations"]:
                with self.subTest(config=path.name, dest=dest["key"]):
                    self.assertIsInstance(dest.get("flight_hours"), (int, float))
                    self.assertGreater(len(dest.get("flight_hours_source", "")), 20)
                    self.assertNotIn("cabin_class", dest)
                    self.assertNotIn("cabin_classes", dest)
                    # Every destination must SAY who answered the nonstop
                    # question and when, and if it answers at all it must
                    # answer with a boolean. An absent flag is the honest
                    # "unknown" — two destinations carry one, because no
                    # source in this repo or the 2026-10-04 research gives the
                    # season END of a seasonal nonstop, and unknown prices
                    # economy.
                    self.assertIn("nonstop_source", dest)
                    self.assertGreater(len(dest.get("nonstop_source", "")), 20)
                    if "nonstop_from_london" in dest:
                        self.assertIsInstance(dest["nonstop_from_london"], bool)
                        self.assertNotIn(
                            "UNKNOWN", dest["nonstop_source"].upper(),
                            "a stated answer and an 'unknown' note cannot both be true",
                        )
                    else:
                        self.assertIn("UNKNOWN", dest["nonstop_source"].upper())

    def test_the_unknown_nonstops_are_the_two_seasonal_services(self):
        # The only two destinations that may leave the question open are the
        # ones whose nonstop is seasonal and whose season end no source gives.
        for path in (DEC, JULY):
            silent = {
                dest["key"] for dest in self._data(path)["destinations"]
                if "nonstop_from_london" not in dest
            }
            self.assertTrue(silent.issubset({"phuket", "khao_lak"}), f"{path.name}: {silent}")
            self.assertTrue(silent, path.name)
            for dest in self._data(path)["destinations"]:
                if dest["key"] in silent:
                    self.assertEqual(destination_cabin(_Shaped(dest)), "ECONOMY")

    def test_the_built_in_table_gives_the_same_cabin_as_the_committed_facts(self):
        for path in (DEC, JULY):
            for dest in self._data(path)["destinations"]:
                with self.subTest(config=path.name, dest=dest["key"]):
                    self.assertEqual(
                        destination_cabin(_Shaped(dest)),
                        cabin_for_flight_hours(
                            dest["flight_hours"], dest.get("nonstop_from_london")
                        ),
                        f"{path.name}:{dest['key']}",
                    )

    def test_the_built_in_hours_mirror_every_committed_destination(self):
        # The built-in table exists for legacy configs, so it must not drift
        # from what the committed configs say a destination is. The one
        # allowlisted exception is honest: Cancún is a nonstop in December
        # (11h01) and a connection in July (about 17h), and a table with no
        # season cannot carry that, so each config states its own hours.
        for path in (DEC, JULY):
            for dest in self._data(path)["destinations"]:
                key = dest["key"]
                if key in SEASON_DEPENDENT_HOURS:
                    continue
                with self.subTest(config=path.name, dest=key):
                    self.assertAlmostEqual(
                        DEFAULT_FLIGHT_HOURS_LHR[key], dest["flight_hours"], places=2,
                    )

    def test_every_pre_rule_destination_is_kept_and_prices_economy(self):
        for path in (DEC, JULY):
            config = load_holiday_config(path.read_text(encoding="utf-8"))
            for dest in config.destinations:
                if dest.key in PRE_RULE_DESTINATIONS:
                    with self.subTest(config=path.name, dest=dest.key):
                        self.assertLess(dest.flight_hours, 8.0)
                        self.assertEqual(dest.cabin_class, "ECONOMY")
        dec_keys = {d["key"] for d in self._data(DEC)["destinations"]}
        self.assertLessEqual(PRE_RULE_DESTINATIONS, dec_keys, "no December destination was dropped")

    def test_far_east_is_added_ranked_first_and_leads_with_its_own_cabin(self):
        # Order is unchanged; the cabin now follows the nonstop rule, which
        # prices every one of these ECONOMY (a one-stop route, or a seasonal
        # nonstop whose season end no source in this repo gives).
        for path, expected in ((DEC, FAR_EAST_DECEMBER), (JULY, LONG_HAUL_JULY)):
            config = load_holiday_config(path.read_text(encoding="utf-8"))
            keys = [d.key for d in config.destinations]
            self.assertEqual(keys[: len(expected)], expected, path.name)
            for dest in config.destinations[: len(expected)]:
                with self.subTest(config=path.name, dest=dest.key):
                    self.assertGreater(dest.flight_hours, 8.0)
                    self.assertEqual(dest.cabin_class, "ECONOMY")

    def test_july_prices_economy_everywhere(self):
        # Owner, 2026-10-04: no current beach destination has a London nonstop
        # in the June/July window, so no July card may quote Business.
        config = load_holiday_config(JULY.read_text(encoding="utf-8"))
        self.assertEqual({d.cabin_class for d in config.destinations}, {"ECONOMY"})
        for deal in collect_holiday_deals(config, max_budget_gbp=config.max_budget_gbp):
            with self.subTest(card=deal.resort_name):
                self.assertEqual(deal.cabin_class, "ECONOMY")
                self.assertNotIn(
                    "business", [str(o.get("kind", "")) for o in deal.flight_options]
                )

    def test_december_business_is_exactly_the_seasonal_nonstop(self):
        # Cancún flies nonstop 18 Oct 2026 - 11 Apr 2027, so December is the one
        # BUSINESS destination in the whole engine, and it is business because
        # a source said the service runs on these dates.
        config = load_holiday_config(DEC.read_text(encoding="utf-8"))
        business = [d.key for d in config.destinations if d.cabin_class == "BUSINESS"]
        self.assertEqual(business, ["riviera_maya"])
        cancun = next(d for d in config.destinations if d.key == "riviera_maya")
        self.assertIs(cancun.nonstop_from_london, True)
        self.assertIn("11 Apr 2027", cancun.nonstop_source)

    def test_far_east_rows_are_in_season_labelled_benchmark_unverified_and_headed_at_their_cabin(self):
        for path, expected in ((DEC, FAR_EAST_DECEMBER), (JULY, FAR_EAST_JULY)):
            config = load_holiday_config(path.read_text(encoding="utf-8"))
            rows = [r for r in far_east_watch_rows(config) if r["in_season"]]
            self.assertEqual([r["key"] for r in rows], expected, path.name)
            for row in rows:
                with self.subTest(config=path.name, dest=row["key"]):
                    self.assertTrue(row["in_season"])
                    self.assertEqual(row["price_basis"], FAR_EAST_PRICE_LABEL)
                    self.assertEqual(row["cabin"], "ECONOMY")
                    self.assertIn("tfs=", row["flights_url"])  # dated Google Flights search
                    self.assertGreater(row["indicative_total_gbp"], 0)
                    # The HEADLINE is the derived cabin's figure, and the two
                    # other cabins stay as named comparisons beside it. A
                    # Business headline on a one-stop row is the bug.
                    self.assertEqual(row["headline_total_gbp"], row["economy_total_gbp"])
                    self.assertEqual(row["headline_pp_gbp"], row["economy_pp_gbp"])
                    # Owner direction 2026-09-30: Economy and Premium Economy shown
                    # alongside Business here too, derived from the one read
                    # benchmark via the same ratios _flight_options uses — never a
                    # second invented benchmark.
                    self.assertGreater(row["economy_total_gbp"], 0)
                    self.assertLess(row["economy_total_gbp"], row["indicative_total_gbp"])
                    self.assertGreater(row["premium_economy_total_gbp"], row["economy_total_gbp"])
                    self.assertLess(row["premium_economy_total_gbp"], row["indicative_total_gbp"])

    def test_december_okinawa_is_watched_and_priced_nowhere(self):
        # H9 (2026-10-04): mainland Japan is about 17°C in December, so Japan is
        # a watch there rather than a card. Okinawa is the one warm Japanese
        # beach, and it is listed with that reason — no price at all, because
        # December is outside the season the watch covers.
        config = load_holiday_config(DEC.read_text(encoding="utf-8"))
        rows = {r["key"]: r for r in far_east_watch_rows(config)}
        self.assertIn("okinawa", rows)
        row = rows["okinawa"]
        self.assertFalse(row["in_season"])
        self.assertIn("17", row["reason"])
        for key in ("indicative_total_gbp", "economy_total_gbp",
                    "premium_economy_total_gbp", "headline_total_gbp"):
            self.assertIsNone(row[key], key)
        self.assertEqual(row["over_budget_gbp"], 0.0)
        # It is still a dated, actionable watch: the search links are live.
        self.assertIn("tfs=", row["flights_url"])

    def test_july_okinawa_is_cards_not_a_watch_row(self):
        # The same key in July has resort entries in the summer catalogue, so
        # it is priced as real cards and never repeated as an unverified watch
        # benchmark beside them.
        config = load_holiday_config(JULY.read_text(encoding="utf-8"))
        keys = [r["key"] for r in far_east_watch_rows(config)]
        self.assertNotIn("okinawa", keys)

    def test_report_leads_with_the_far_east_and_never_calls_it_live(self):
        for path in (DEC, JULY):
            config = load_holiday_config(path.read_text(encoding="utf-8"))
            deals = collect_holiday_deals(config, max_budget_gbp=config.max_budget_gbp)
            html = render_holiday_report(config, generated_at="2026-09-28T12:00:00+00:00", deals=deals)
            with self.subTest(config=path.name):
                start = html.index("Far East first")
                # The next section: the cards, or (a long-haul July priced out
                # by its public budget) the over-budget list.
                ends = [i for i in (html.find("One Family Unit"), html.find("Resorts priced over")) if i >= 0]
                self.assertTrue(ends, "neither cards nor an over-budget list follow the watch")
                first_card = min(ends)
                self.assertLess(start, first_card)
                block = html[start:first_card]
                self.assertIn(FAR_EAST_PRICE_LABEL, block)
                self.assertNotIn("LIVE VERIFIED", block)
                # Never a live/verified claim (owner rule 2026-09-28), and the
                # block must never head a row at Business: every watch
                # destination in both seasons is a one-stop route or an
                # unconfirmed season, so it is Economy (owner rule
                # 2026-10-04). Business survives only as a named comparison.
                self.assertNotIn("pp Business + suite", block)

    def test_a_watch_row_is_headed_at_its_own_derived_cabin(self):
        # A generous ceiling so the rows render in full rather than
        # collapsed, which is where the headline sentence is printed.
        for path in (DEC, JULY):
            config = dataclasses.replace(
                load_holiday_config(path.read_text(encoding="utf-8")),
                max_budget_gbp=90000.0,
            )
            html = render_far_east_watch(config)
            with self.subTest(config=path.name):
                self.assertIn("pp Economy + suite", html)
                self.assertNotIn("pp Business + suite", html)
                # Business is still shown, as a comparison beside the headline.
                self.assertIn("Business ≈ £", html)
                self.assertIn("Premium Economy ≈ £", html)

    def test_watch_table_covers_only_long_haul_keys(self):
        for key in FAR_EAST_WATCH:
            with self.subTest(key=key):
                self.assertGreater(DEFAULT_FLIGHT_HOURS_LHR[key], 8.0)


class _Shaped:
    """The three fields ``destination_cabin`` reads, from a raw config entry."""

    def __init__(self, raw: dict) -> None:
        self.key = raw["key"]
        self.flight_hours = raw.get("flight_hours")
        self.nonstop_from_london = raw.get("nonstop_from_london")


if __name__ == "__main__":
    unittest.main()