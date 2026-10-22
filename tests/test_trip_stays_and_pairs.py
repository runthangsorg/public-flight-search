"""Trip data the dossiers are built from: dated stays, named properties, and vendor-versus-ours pairs (22 Oct 2026).

Owner, 22 Oct 2026: "full verbose details of itineraries, flights, times stayed, hotel reviews, and deep links to
actual bookings etc. and equiv pre-packaged vendor holidays vs mine". Everything the e-mail will print per trip comes
from ``multi_centre.json`` through ``multi_centre.py``, so the contract is pinned here, from synthetic items and from
the shipped file:

* ``compare_with`` names the counterpart of a vendor package (or of our build), is checked at load, and works from
  either side;
* a stop can carry named properties (``lodges``) with nights, board and a search area, and a property that is not
  named is never lifted out of free text;
* ``cost_lines`` are kept only when they add up to the trip's own figure;
* ``trip_stays_for_dates`` gives each stop and each property its check-in and check-out from the report's own dates,
  in the same order the flight legs are dated, and says how many nights of the date pair the plan leaves unplanned.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from public_flight_search.multi_centre import (
    DEFAULT_MULTI_CENTRE_PATH,
    consume_multi_centre_skip_log,
    counterparts,
    load_multi_centre,
    trip_legs_for_dates,
    trip_stays_for_dates,
)

SHIPPED = Path(DEFAULT_MULTI_CENTRE_PATH)


def _item(ident="MC-X1", **over):
    base = {
        "id": ident,
        "title": f"Synthetic {ident}",
        "season": "summer",
        "stops": [
            {"place": "Serengeti", "nights": 4, "airport": "JRO", "hotel": "A lodge", "basis": "rate card"},
            {"place": "Zanzibar (Nungwi)", "nights": 7, "airport": "ZNZ", "hotel": "A resort", "basis": "rate card"},
        ],
        "legs": [["LHR", "JRO"], ["JRO", "ZNZ"], ["ZNZ", "LHR"]],
        "flight_shape": "open-jaw",
        "cost_low_gbp": 14000, "cost_high_gbp": 14000,
        "cost_basis": "built line by line",
        "why": "w", "catch": "c", "confidence": "estimate",
        "kind": "self-build",
        "source_urls": ["https://example.org/x"],
    }
    base.update(over)
    return base


def _load(items):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "mc.json"
        path.write_text(json.dumps({"schema": "multi_centre/1", "itineraries": items}))
        consume_multi_centre_skip_log()
        return load_multi_centre(path=str(path), season="summer")


def _operator(ident="OP-1", **over):
    return _item(ident, kind="operator", operator_ref="Synthetic Tours 9-night package", **over)


class CompareWithTests(unittest.TestCase):
    def test_a_pair_is_linked_from_either_side(self):
        trips = _load([_operator("OP-1"), _item("SB-1", compare_with="OP-1")])
        pairs = counterparts(trips)
        self.assertEqual([t.id for t in pairs["OP-1"]], ["SB-1"], "the package side finds our build")
        self.assertEqual([t.id for t in pairs["SB-1"]], ["OP-1"], "our build finds the package")

    def test_a_trip_with_no_counterpart_has_an_empty_list(self):
        trips = _load([_item("SB-1")])
        self.assertEqual(counterparts(trips), {"SB-1": []})

    def test_an_id_that_is_not_in_the_file_is_dropped_with_a_reason_and_the_trip_stays(self):
        trips = _load([_item("SB-1", compare_with="NOPE-9")])
        self.assertEqual([t.id for t in trips], ["SB-1"])
        self.assertEqual(trips[0].compare_with, "")
        self.assertTrue(any("NOPE-9" in line for line in consume_multi_centre_skip_log()))

    def test_two_trips_of_the_same_kind_are_not_a_pair(self):
        trips = _load([_item("SB-1", compare_with="SB-2"), _item("SB-2")])
        self.assertEqual(trips[0].compare_with, "")
        self.assertEqual(counterparts(trips), {"SB-1": [], "SB-2": []})
        self.assertTrue(any("same kind" in line for line in consume_multi_centre_skip_log()))

    def test_a_trip_cannot_be_its_own_counterpart(self):
        trips = _load([_item("SB-1", compare_with="SB-1")])
        self.assertEqual(trips[0].compare_with, "")

    def test_a_package_in_the_other_season_is_not_a_counterpart(self):
        trips = _load([_operator("OP-W", season="winter"), _item("SB-1", compare_with="OP-W")])
        self.assertEqual([t.id for t in trips], ["SB-1"])
        self.assertEqual(trips[0].compare_with, "")


class LodgeAndCostLineTests(unittest.TestCase):
    def _stop_with(self, lodges):
        item = _item()
        item["stops"][0]["lodges"] = lodges
        return _load([item])[0].stops[0]

    def test_a_property_carries_its_nights_board_area_and_page(self):
        stop = self._stop_with([
            {"name": "Town Hotel", "nights": 1, "area": "Arusha"},
            {"name": "Bush Lodge", "nights": 3, "board": "full board", "area": "Tarangire",
             "url": "https://example.org/lodge", "note": "park fees in"},
        ])
        self.assertEqual([(l.name, l.nights, l.board, l.area) for l in stop.lodges],
                         [("Town Hotel", 1, "", "Arusha"), ("Bush Lodge", 3, "full board", "Tarangire")])
        self.assertEqual(stop.lodges[1].url, "https://example.org/lodge")
        self.assertEqual(stop.lodges[1].note, "park fees in")

    def test_unitemised_nights_are_none_not_zero(self):
        stop = self._stop_with([{"name": "Camp A"}, {"name": "Camp B", "nights": ""}])
        self.assertEqual([l.nights for l in stop.lodges], [None, None])

    def test_properties_holding_more_nights_than_the_stop_are_dropped_with_a_reason(self):
        stop = self._stop_with([{"name": "A", "nights": 3}, {"name": "B", "nights": 3}])
        self.assertEqual(stop.lodges, ())
        self.assertTrue(any("more nights" in line for line in consume_multi_centre_skip_log()))

    def test_a_url_that_is_not_http_is_never_kept(self):
        stop = self._stop_with([{"name": "A", "nights": 1, "url": "javascript:alert(1)"}])
        self.assertEqual(stop.lodges[0].url, "")

    def test_cost_lines_are_kept_only_when_they_add_up_to_the_figure(self):
        good = _load([_item(cost_lines=[{"label": "lodge", "gbp": 9000}, {"label": "flights", "gbp": 5000}])])[0]
        self.assertEqual([(l.label, l.gbp) for l in good.cost_lines], [("lodge", 9000.0), ("flights", 5000.0)])
        bad = _load([_item(cost_lines=[{"label": "lodge", "gbp": 9000}, {"label": "flights", "gbp": 4000}])])[0]
        self.assertEqual(bad.cost_lines, (), "a breakdown that does not add up is not printed")
        self.assertTrue(any("add up" in line for line in consume_multi_centre_skip_log()))

    def test_a_range_cannot_be_itemised(self):
        trip = _load([_item(cost_low_gbp=10000, cost_high_gbp=12000,
                            cost_lines=[{"label": "all", "gbp": 10000}])])[0]
        self.assertEqual(trip.cost_lines, ())


class StaysForDatesTests(unittest.TestCase):
    def _trip(self, **over):
        item = _item(**over)
        item["stops"][0]["lodges"] = [
            {"name": "Town Hotel", "nights": 1, "area": "Arusha"},
            {"name": "Bush Lodge", "nights": 3, "area": "Tarangire"},
        ]
        item["stops"][1]["lodges"] = [{"name": "Beach Resort", "nights": 7, "area": "Zanzibar"}]
        return _load([item])[0]

    def test_each_stop_runs_from_where_the_last_ended_by_its_own_nights(self):
        plan = trip_stays_for_dates(self._trip(), "2027-06-27", "2027-07-14")
        self.assertEqual([(s.check_in, s.check_out, s.nights) for s in plan.stays],
                         [("2027-06-27", "2027-07-01", 4), ("2027-07-01", "2027-07-08", 7)])

    def test_properties_inside_a_stop_are_dated_in_order(self):
        plan = trip_stays_for_dates(self._trip(), "2027-06-27", "2027-07-14")
        first = plan.stays[0].lodges
        self.assertEqual([(l.lodge.name, l.check_in, l.check_out) for l in first],
                         [("Town Hotel", "2027-06-27", "2027-06-28"), ("Bush Lodge", "2027-06-28", "2027-07-01")])
        self.assertEqual([(l.check_in, l.check_out) for l in plan.stays[1].lodges], [("2027-07-01", "2027-07-08")])

    def test_the_nights_the_date_pair_adds_are_named_not_silently_absorbed(self):
        plan = trip_stays_for_dates(self._trip(), "2027-06-27", "2027-07-14")
        self.assertEqual(plan.plan_end, "2027-07-08")
        self.assertEqual(plan.return_date, "2027-07-14")
        self.assertEqual(plan.unplanned_nights, 6, "27 Jun + 11 nights = 8 Jul, so 8-14 Jul is six nights nobody planned")

    def test_a_plan_that_exactly_fills_the_pair_has_no_gap(self):
        plan = trip_stays_for_dates(self._trip(), "2027-06-27", "2027-07-08")
        self.assertEqual(plan.unplanned_nights, 0)
        self.assertEqual(plan.stays[-1].check_out, "2027-07-08")

    def test_a_plan_longer_than_the_pair_is_cut_at_the_flight_home_and_says_so(self):
        plan = trip_stays_for_dates(self._trip(), "2027-06-27", "2027-07-04")
        self.assertEqual(plan.stays[-1].check_out, "2027-07-04")
        self.assertEqual(plan.stays[-1].nights, 3, "only the nights that fit before the flight home")
        self.assertEqual(plan.cut_nights, 4)

    def test_a_property_without_itemised_nights_is_not_given_invented_dates(self):
        item = _item()
        item["stops"][0]["lodges"] = [{"name": "Camp A"}, {"name": "Camp B"}]
        plan = trip_stays_for_dates(_load([item])[0], "2027-06-27", "2027-07-14")
        for lodge in plan.stays[0].lodges:
            self.assertEqual((lodge.check_in, lodge.check_out), ("", ""))
        self.assertEqual((plan.stays[0].check_in, plan.stays[0].check_out), ("2027-06-27", "2027-07-01"))

    def test_a_bad_date_pair_raises_like_the_legs_do(self):
        with self.assertRaises(ValueError):
            trip_stays_for_dates(self._trip(), "2027-07-14", "2027-06-27")

    def test_the_flight_between_two_stops_leaves_on_the_day_the_first_stay_ends(self):
        trip = self._trip()
        legs = trip_legs_for_dates(trip, "2027-06-27", "2027-07-14")
        plan = trip_stays_for_dates(trip, "2027-06-27", "2027-07-14")
        self.assertEqual(legs[1][2], plan.stays[0].check_out, "JRO-ZNZ leaves when the safari ends")
        self.assertEqual(legs[0][2], plan.stays[0].check_in)
        self.assertEqual(legs[-1][2], plan.return_date)


class ShippedDataTests(unittest.TestCase):
    """The file the e-mail really ships: every pair resolves, every itemised price adds up."""

    @classmethod
    def setUpClass(cls):
        cls.items = {i["id"]: i for i in json.loads(SHIPPED.read_text(encoding="utf-8"))["itineraries"]}
        consume_multi_centre_skip_log()
        cls.trips = {t.id: t for t in load_multi_centre(season="summer")}
        cls.skips = consume_multi_centre_skip_log()

    def test_no_declared_pair_or_itemisation_was_refused_at_load(self):
        self.assertEqual([line for line in self.skips if "compare_with" in line or "cost lines" in line
                          or "properties" in line], [])

    def test_the_three_obvious_pairs_are_declared(self):
        pairs = counterparts(list(self.trips.values()))
        self.assertEqual([t.id for t in pairs["AF-01"]], ["AF-08"], "Kuoni Tanzania safari + Zanzibar <-> our Ngorongoro + Zanzibar")
        self.assertEqual([t.id for t in pairs["AF-02"]], ["AF-09"], "TourCompass Serengeti fly-in <-> our Sayari Camp + Zanzibar")
        self.assertEqual([t.id for t in pairs["AF-07"]], ["AF-10"], "TourCompass Kruger + Cape Town <-> our Kruger self-drive + Cape Town")

    def test_every_pair_is_one_package_and_one_build(self):
        for ident, others in counterparts(list(self.trips.values())).items():
            for other in others:
                with self.subTest(pair=(ident, other.id)):
                    self.assertNotEqual(self.trips[ident].kind, other.kind)

    def test_a_trip_with_no_pair_is_left_alone_not_forced_into_one(self):
        pairs = counterparts(list(self.trips.values()))
        for ident in ("AF-03", "AF-04", "AF-05", "AF-06", "AF-11", "MC-01", "MC-05", "MC-07"):
            self.assertEqual(pairs[ident], [], ident)

    def test_every_itemised_self_build_adds_up_to_its_own_figure(self):
        itemised = [t for t in self.trips.values() if t.cost_lines]
        self.assertTrue({"AF-08", "AF-09", "AF-10", "AF-11"} <= {t.id for t in itemised})
        for trip in itemised:
            with self.subTest(trip=trip.id):
                self.assertAlmostEqual(sum(l.gbp for l in trip.cost_lines), trip.cost_low_gbp, delta=1.0)

    def test_every_named_property_belongs_to_its_stop_text(self):
        """A property is named from the stop's own words, never from nowhere."""
        for trip in self.trips.values():
            for stop in trip.stops:
                for lodge in stop.lodges:
                    with self.subTest(trip=trip.id, lodge=lodge.name):
                        text = f"{stop.hotel} {stop.place}".lower()
                        head = lodge.name.lower().split(",")[0]
                        self.assertIn(head, text)

    def test_every_lodge_page_we_hold_is_one_the_trip_already_sources(self):
        for trip in self.trips.values():
            for stop in trip.stops:
                for lodge in stop.lodges:
                    if lodge.url:
                        with self.subTest(trip=trip.id, lodge=lodge.name):
                            self.assertIn(lodge.url, trip.source_urls)

    def test_where_nights_are_itemised_they_fit_inside_the_stop(self):
        for trip in self.trips.values():
            for stop in trip.stops:
                itemised = [l.nights for l in stop.lodges if l.nights is not None]
                self.assertLessEqual(sum(itemised), stop.nights, (trip.id, stop.place))

    def test_the_named_safari_lodges_are_there(self):
        names = {l.name for t in self.trips.values() for s in t.stops for l in s.lodges}
        for expected in ("Kirurumu Tarangire Lodge", "Ngorongoro Crater Camp", "Sayari Camp",
                         "Bluebay Beach Resort & Spa", "Breezes Beach Club & Spa"):
            self.assertIn(expected, names)


if __name__ == "__main__":
    unittest.main()
