"""A room-only stay counts in a TRIP total, clearly labelled — and never in a holiday deal card.

Nearly every Google Hotels row states no meal, so it is recorded with board ``RO`` and
``load_hotel_evidence`` drops it ("no breakfast (room only)"). That gate is right for a single-resort
deal card and stays. For a multi-stop trip total a dated room-only price is still a real price for
that night, so a second load of the same file (``load_room_only_rates``) holds the room-only rates
under every other gate, and ``trip_total`` uses one only when no breakfast-or-better read exists.

Synthetic names and invented figures throughout.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from public_flight_search import holiday_digest as hd
from public_flight_search import hotel_evidence as he
from public_flight_search import trip_totals as tt

from test_holiday_email_compact import _config
from test_price_says_what_it_covers import BUILD, deal_read, load
from test_trip_totals import NOW, _hotel_rates, _plan_lodges, _rate, _rows


def _loads(rates):
    """(breakfast-or-better load, room-only load) of ONE synthetic evidence file."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "hotel.json"
        path.write_text(json.dumps({"schema": "holiday_hotel_evidence/1", "travellers": 5,
                                    "rates": list(rates), "unit_checks": [], "ratings": [], "facts": [],
                                    "blocked": []}), encoding="utf-8")
        breakfast = dict(he.load_hotel_evidence(_config(), path=str(path), now=NOW))
        he.consume_hotel_skip_log()
        room_only = dict(he.load_room_only_rates(str(path), _config(), now=NOW))
    return breakfast, room_only


def _build(rows, breakfast, room_only):
    return hd.build_digest(_config(), rows=rows, package_prices={}, watch=(), generated_at=NOW,
                           hotel_rates=breakfast or None, room_only_rates=room_only or None)


class RoomOnlyLoaderTests(unittest.TestCase):
    def test_it_keeps_the_room_only_rate_and_not_the_breakfast_one(self):
        name, check_in, check_out = "SYNTHETIC Palm Cove Resort", "2027-07-01", "2027-07-05"
        breakfast, room_only = _loads([_rate(name, check_in, check_out, 300.0, board="RO"),
                                       _rate(name, check_in, check_out, 400.0, board="BB")])
        self.assertEqual([entry.cheapest.board for entry in room_only.values()], ["RO"])
        self.assertEqual([entry.cheapest.board for entry in breakfast.values()], ["BB"])

    def test_every_other_gate_still_applies(self):
        name, check_in, check_out = "SYNTHETIC Palm Cove Resort", "2027-07-01", "2027-07-05"
        cases = {
            "stale": _rate(name, check_in, check_out, 300.0, board="RO", observed="2026-10-01T09:00:00+00:00"),
            "wrong party": _rate(name, check_in, check_out, 300.0, board="RO", adults=2),
            "wrong dates (not exact)": dict(_rate(name, check_in, check_out, 300.0, board="RO"),
                                            exact_date_match=False),
            "wrong season": _rate(name, "2027-12-01", "2027-12-05", 300.0, board="RO"),
            "not one booking": dict(_rate(name, check_in, check_out, 300.0, board="RO"),
                                    booking_shape="one_room_of_three"),
            "no source": dict(_rate(name, check_in, check_out, 300.0, board="RO"), source_url=""),
        }
        for label, rate in cases.items():
            _, room_only = _loads([rate])
            self.assertEqual(room_only, {}, label)

    def test_a_missing_or_unreadable_file_is_an_empty_mapping(self):
        self.assertEqual(he.load_room_only_rates("/nonexistent/SYNTHETIC.json", _config(), now=NOW), {})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "broken.json"
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(he.load_room_only_rates(str(path), _config(), now=NOW), {})

    def test_it_leaves_the_main_loads_state_alone(self):
        name, check_in, check_out = "SYNTHETIC Palm Cove Resort", "2027-07-01", "2027-07-05"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hotel.json"
            path.write_text(json.dumps({
                "schema": "holiday_hotel_evidence/1", "travellers": 5,
                "rates": [_rate(name, check_in, check_out, 300.0, board="RO"),
                          _rate(name, check_in, check_out, 400.0, board="BB")],
                "unit_checks": [], "ratings": [{"property_name": name, "source": "Google", "score": 4.5,
                                                "scale": 5, "review_count": "100", "where": "overview",
                                                "source_url": "https://example.org/SYNTHETIC-rating",
                                                "observed_at": NOW}],
                "facts": [], "blocked": []}), encoding="utf-8")
            he.load_hotel_evidence(_config(), path=str(path), now=NOW)
            skipped = he.consume_hotel_skip_log()
            before = len(he.supplemental_for(name, "ratings"))
            he.load_room_only_rates(str(path), _config(), now=NOW)
        self.assertTrue(any("room only" in reason for reason in skipped), "the main load said why it dropped it")
        self.assertEqual(he.consume_hotel_skip_log(), [], "the room-only load adds no skip of its own")
        self.assertEqual(len(he.supplemental_for(name, "ratings")), before, "the index still belongs to the main load")


class RoomOnlyTripTotalTests(unittest.TestCase):
    def setUp(self):
        self.rows = _rows([deal_read(BUILD, "MIXED", 8_000)])
        self.lodges = _plan_lodges(self.rows[0])

    def test_a_breakfast_rate_wins_over_a_cheaper_room_only_one(self):
        name, check_in, check_out = self.lodges[0]
        other = self.lodges[1]
        breakfast, room_only = _loads([
            _rate(name, check_in, check_out, 300.0, board="BB"),
            _rate(name, check_in, check_out, 100.0, board="RO"),
            _rate(other[0], other[1], other[2], 300.0, board="BB")])
        total = tt.trip_total(self.rows[0], breakfast, flights_gbp=8_000.0, room_only_rates=room_only)
        stay = total.stays[0]
        self.assertEqual(stay.board, "BB")
        self.assertEqual(stay.total_gbp, 300.0 * stay.nights)
        self.assertEqual(total.room_only_nights, 0)

    def test_a_trip_priced_only_by_room_only_reads_is_complete_and_counts_its_room_only_nights(self):
        breakfast, room_only = _loads([_rate(name, check_in, check_out, 200.0, board="RO")
                                       for name, check_in, check_out in self.lodges])
        self.assertEqual(breakfast, {}, "no breakfast-or-better read exists")
        self.assertTrue(room_only)
        total = tt.trip_total(self.rows[0], breakfast or None, flights_gbp=8_000.0, room_only_rates=room_only)
        self.assertTrue(total.complete)
        self.assertEqual(total.room_only_nights, total.nights_planned)
        self.assertEqual(total.total_gbp, 8_000.0 + 200.0 * total.nights_planned)
        self.assertEqual({stay.board_words for stay in total.stays}, {"room only"})

    def test_trip_total_works_with_no_breakfast_mapping_at_all(self):
        _, room_only = _loads([_rate(name, check_in, check_out, 200.0, board="RO")
                               for name, check_in, check_out in self.lodges])
        total = tt.trip_total(self.rows[0], None, flights_gbp=8_000.0, room_only_rates=room_only)
        self.assertTrue(total.complete)

    def test_the_card_says_how_many_nights_are_room_only(self):
        _, room_only = _loads([_rate(name, check_in, check_out, 200.0, board="RO")
                               for name, check_in, check_out in self.lodges])
        card = _build(self.rows, {}, room_only).cards[0]
        self.assertEqual(card.kind, "trip")
        self.assertIn(f"({card.nights} nights room only, no meals)", card.covers)
        self.assertIn("trip total, 5 people: flights + every night's stay", card.covers)
        self.assertTrue(all(stay.board_words == "room only" for stay in card.stays))
        text = hd.render_digest_text(_config(), _build(self.rows, {}, room_only), generated_at=NOW)
        self.assertIn("room only", text)

    def test_a_priced_breakfast_trip_keeps_the_present_wording(self):
        breakfast, room_only = _loads([_rate(name, check_in, check_out, 200.0, board="BB")
                                       for name, check_in, check_out in self.lodges])
        card = _build(self.rows, breakfast, room_only).cards[0]
        self.assertEqual(card.covers, "trip total, 5 people: flights + every night's stay")

    def test_a_partly_priced_card_adds_its_room_only_nights(self):
        name, check_in, check_out = self.lodges[0]
        _, room_only = _loads([_rate(name, check_in, check_out, 200.0, board="RO")])
        card = _build(self.rows, {}, room_only).cards[0]
        self.assertEqual(card.kind, "part")
        self.assertIn("the other nights are not priced", card.covers)
        self.assertTrue(card.covers.endswith(f"; {card.stays[0].nights} nights room only"), card.covers)

    def test_a_watch_list_stay_priced_room_only_says_no_meals(self):
        pair = hd._reference_pair(_config())
        entry = type("Entry", (), {"name": "SYNTHETIC Island Villa", "area": "Gili Meno",
                                   "url": "https://example.org/SYNTHETIC-villa", "halal": None})()
        _, room_only = _loads([_rate(entry.name, pair[0], pair[1], 200.0, board="RO")])
        digest = hd.build_digest(_config(), rows=self.rows, package_prices={}, watch=(entry,),
                                 generated_at=NOW, room_only_rates=room_only)
        stays = [c for c in digest.cards if c.kind == "stay"]
        self.assertTrue(stays, "the watch-list entry is priced from its room-only read")
        self.assertEqual(stays[0].covers,
                         "stay only, 5 people, room only (no meals); flights not included")


if __name__ == "__main__":
    unittest.main()
