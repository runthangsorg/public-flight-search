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


# --------------------------------------------------------------------------- #
# A party of five in three rooms (2 + 2 + 1), the last shape a trip total tries
# --------------------------------------------------------------------------- #

def _three_room_rate(name, check_in, check_out, nightly, *, board="BB", **over):
    """One synthetic three-room read; sum(nightly) is what the page showed per night."""
    nights = (__import__("datetime").date.fromisoformat(check_out)
              - __import__("datetime").date.fromisoformat(check_in)).days
    units = [{"name": "SYNTHETIC room A", "adults": 2, "guests_stated": "2 guests"},
             {"name": "SYNTHETIC room B", "adults": 2, "guests_stated": "2 guests"},
             {"name": "SYNTHETIC room C", "adults": 1, "guests_stated": "1 guest"}]
    record = {
        "property_name": name, "destination_key": "synthetic", "season": "summer",
        "vendor": "SYNTHETIC Seller as listed on Google Hotels", "check_in": check_in,
        "check_out": check_out, "nights": nights, "party": {"adults": 5, "children": 0},
        "booking_shape": "three_rooms_one_booking", "units": units,
        "rate_name": "SYNTHETIC three-room rate", "board": board,
        "price_basis": "nightly_room_rate", "currency": "GBP", "taxes_included": None,
        "prices_shown": [{"unit": unit["name"], "nightly": nightly} for unit in units],
        "terms": [{"unit": unit["name"], "cancellation": "not stated", "payment": "not stated"} for unit in units],
        "source_url": f"https://example.org/SYNTHETIC-three-{name.replace(' ', '-')}",
        "observed_at": "2026-11-14T09:00:00+00:00", "exact_date_match": True,
        "confidence": "verified-exact-date",
        "derived_stay_total": {"value": nightly * len(units) * nights, "currency": "GBP",
                               "how": "(room 1 + room 2 + room 3 nightly price shown) x nights"},
    }
    record.update(over)
    return record


def _load_all(rates):
    """(breakfast load, room-only load, three-room load) of ONE synthetic evidence file."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "hotel.json"
        path.write_text(json.dumps({"schema": "holiday_hotel_evidence/1", "travellers": 5,
                                    "rates": list(rates), "unit_checks": [], "ratings": [], "facts": [],
                                    "blocked": []}), encoding="utf-8")
        breakfast = dict(he.load_hotel_evidence(_config(), path=str(path), now=NOW))
        he.consume_hotel_skip_log()
        room_only = dict(he.load_room_only_rates(str(path), _config(), now=NOW))
        three = dict(he.load_three_room_rates(str(path), _config(), now=NOW))
    return breakfast, room_only, three


def _build3(rows, three_only):
    return hd.build_digest(_config(), rows=rows, package_prices={}, watch=(), generated_at=NOW,
                           three_room_rates=three_only or None)


class ThreeRoomLoaderTests(unittest.TestCase):
    def setUp(self):
        self.name, self.check_in, self.check_out = "SYNTHETIC Palm Cove Resort", "2027-07-01", "2027-07-05"

    def test_it_keeps_only_the_three_room_shape(self):
        two_rooms = _rate(self.name, self.check_in, self.check_out, 300.0, two_rooms=True)
        one_unit = _rate(self.name, self.check_in, self.check_out, 380.0)
        three = _three_room_rate(self.name, self.check_in, self.check_out, 200.0)
        breakfast, room_only, three_room = _load_all([two_rooms, one_unit, three])
        self.assertEqual([entry.cheapest.booking_shape for entry in three_room.values()],
                         ["three_rooms_one_booking"])
        self.assertEqual(sorted(entry.cheapest.booking_shape for entry in breakfast.values()),
                         ["single_unit", "two_rooms_one_booking"],
                         "the deal loader's accepted shapes are unchanged")
        self.assertEqual(room_only, {}, "a three-room rate is not a room-only rate")

    def test_any_board_counts_but_the_board_is_kept(self):
        three = _three_room_rate(self.name, self.check_in, self.check_out, 200.0, board="RO")
        _, _, three_room = _load_all([three])
        self.assertEqual([entry.cheapest.board for entry in three_room.values()], ["RO"])

    def test_every_other_gate_still_applies(self):
        cases = {
            "stale": _three_room_rate(self.name, self.check_in, self.check_out, 200.0,
                                      observed_at="2026-10-01T09:00:00+00:00"),
            "wrong party": _three_room_rate(self.name, self.check_in, self.check_out, 200.0,
                                            party={"adults": 4, "children": 0}),
            "wrong dates (not exact)": _three_room_rate(self.name, self.check_in, self.check_out, 200.0,
                                                        exact_date_match=False),
            "wrong season": _three_room_rate(self.name, "2027-12-01", "2027-12-05", 200.0),
            "no source": _three_room_rate(self.name, self.check_in, self.check_out, 200.0, source_url=""),
            "no positive price": _three_room_rate(self.name, self.check_in, self.check_out, 0.0),
        }
        for label, rate in cases.items():
            _, _, three_room = _load_all([rate])
            self.assertEqual(three_room, {}, label)

    def test_a_missing_or_unreadable_file_is_an_empty_mapping_and_nothing_is_printed(self):
        import contextlib
        import io
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertEqual(he.load_three_room_rates("/nonexistent/SYNTHETIC.json", _config(), now=NOW), {})
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "broken.json"
                path.write_text("{not json", encoding="utf-8")
                self.assertEqual(he.load_three_room_rates(str(path), _config(), now=NOW), {})
        self.assertEqual(stderr.getvalue(), "")


class ThreeRoomPreferenceTests(unittest.TestCase):
    def setUp(self):
        self.rows = _rows([deal_read(BUILD, "MIXED", 8_000)])
        self.lodges = _plan_lodges(self.rows[0])

    def _maps(self, *extra):
        rates = [_three_room_rate(name, check_in, check_out, 200.0) for name, check_in, check_out in self.lodges]
        return _load_all(rates + list(extra))

    def test_breakfast_or_better_in_one_unit_wins_then_room_only_then_three_rooms(self):
        name, check_in, check_out = self.lodges[0]
        rates = [_three_room_rate(n, ci, co, 200.0) for n, ci, co in self.lodges]
        rates.append(_rate(name, check_in, check_out, 500.0, board="BB"))
        _, room_only_split, three_room = _load_all(rates)
        self.assertEqual(room_only_split, {})
        self.assertNotIn((name, check_in, check_out, "single_unit"),
                         {(k[0], k[1], k[2], k[3]) for k in three_room})
        rate = tt._rate_for({}, name, check_in, check_out, three_room_rates=three_room)
        self.assertEqual(rate.booking_shape, "three_rooms_one_booking")

    def test_the_order_is_breakfast_then_room_only_then_three_rooms(self):
        name, check_in, check_out = self.lodges[0]
        three = _three_room_rate(name, check_in, check_out, 200.0, board="BB")
        _, _, three_room = _load_all([three])
        breakfast, _, _ = _load_all([_rate(name, check_in, check_out, 500.0, board="BB")])
        _, room_only, _ = _load_all([_rate(name, check_in, check_out, 400.0, board="RO")])
        self.assertEqual(tt._rate_for(breakfast, name, check_in, check_out,
                                      room_only_rates=room_only, three_room_rates=three_room).board, "BB")
        self.assertEqual(tt._rate_for(room_only, name, check_in, check_out,
                                      room_only_rates=room_only, three_room_rates=three_room).board, "RO")
        chosen = tt._rate_for({}, name, check_in, check_out, room_only_rates={}, three_room_rates=three_room)
        self.assertEqual(chosen.booking_shape, "three_rooms_one_booking")

    def test_a_three_room_rate_wins_only_when_no_one_unit_or_two_room_read_prices_the_night(self):
        name, check_in, check_out = self.lodges[0]
        three = _three_room_rate(name, check_in, check_out, 200.0)
        one_unit = _rate(name, check_in, check_out, 900.0, board="BB")
        breakfast, _, _ = _load_all([three, one_unit])
        three_room = _load_all([three])[2]
        chosen = tt._rate_for(breakfast, name, check_in, check_out, three_room_rates=three_room)
        self.assertEqual(chosen.booking_shape, "single_unit", "the dearer one-unit read still wins")

    def test_the_stay_line_says_three_rooms_and_their_guests_in_html_and_text(self):
        _, _, three_room = self._maps()
        digest = _build3(self.rows, three_room)
        (card,) = digest.cards
        self.assertEqual(card.kind, "trip")
        self.assertTrue(all(stay.three_rooms for stay in card.stays))
        self.assertEqual(card.stays[0].rooms_words, "3 rooms (2 + 2 + 1 guests)")
        html = hd.render_digest_html(_config(), digest, generated_at=NOW)
        text = hd.render_digest_text(_config(), digest, generated_at=NOW)
        for part in (html, text):
            self.assertIn("3 rooms (2 + 2 + 1 guests)", part)
        self.assertNotIn("2 rooms", html)
