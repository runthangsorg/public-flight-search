"""Tickets beyond a hub that cost less than a ticket to the hub (owner, 21 Nov 2026): the gap is measured, never
booked, and every output carries what such a ticket costs beyond its fare. Airlines and fares are synthetic."""

from __future__ import annotations

import contextlib
import io
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from public_flight_search import beyond_fares as bf
from public_flight_search.config import FlightSearch
from public_flight_search.engine import FlightOffer
from public_flight_search.google_flights import _parse_flight_cards

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 21, 9, 0, tzinfo=timezone.utc)
DAY = "2027-02-10"
HUB = bf.Hub("HUB", "Hub City", ("HUB",), ("AAA", "BBB", "CCC"))


def offer(destination, price, *, via=(), airline="Test Air", currency="GBP"):
    return FlightOffer(origin="LHR", destination=destination, departure=f"{DAY}T09:00:00", price=price,
                       currency=currency, stops=len(via), duration_minutes=300 + 200 * len(via),
                       provider="Google Flights", booking_url="https://example.test/f", airline=airline,
                       leg_hours=(4.0,) * (len(via) + 1), via_airports=tuple(via))


def fetcher(table, asked=None):
    def fetch(read):
        if asked is not None:
            asked.append(read.destination)
        return table.get(read.destination, ("ok", ()))
    return fetch


class FindTests(unittest.TestCase):
    def find(self, table, **kwargs):
        return bf.find_beyond_fares("LHR", HUB, DAY, fetcher(table), now=NOW, **kwargs)

    def test_a_cheaper_ticket_through_the_hub_is_a_lead_with_its_saving(self):
        result = self.find({"HUB": ("ok", [offer("HUB", 200.0)]),
                            "AAA": ("ok", [offer("AAA", 140.0, via=("HUB",))])})
        lead = result["leads"][0]
        self.assertEqual((lead["ticketed_to"], lead["leave_at"], lead["per_person_gbp"]), ("AAA", "HUB", 140.0))
        self.assertEqual((lead["saving_gbp"], lead["saving_pct"]), (60.0, 30.0))
        self.assertEqual(result["nonstop"]["per_person_gbp"], 200.0)

    def test_a_ticket_through_another_city_or_with_two_stops_or_unnamed_is_not_counted(self):
        result = self.find({"HUB": ("ok", [offer("HUB", 200.0)]),
                            "AAA": ("ok", [offer("AAA", 90.0, via=("XXX",))]),
                            "BBB": ("ok", [offer("BBB", 90.0, via=("HUB", "XXX"))]),
                            "CCC": ("ok", [FlightOffer(origin="LHR", destination="CCC", departure=f"{DAY}T09:00:00",
                                                       price=90.0, currency="GBP", stops=1, duration_minutes=500,
                                                       provider="Google Flights")])})
        self.assertEqual(result["leads"], [])
        self.assertEqual([r["status"] for r in result["reads"][1:]], ["none through the hub"] * 3)

    def test_the_comparison_is_with_the_nonstop_fare_not_a_cheaper_connecting_one(self):
        result = self.find({"HUB": ("ok", [offer("HUB", 120.0, via=("XXX",)), offer("HUB", 200.0)]),
                            "AAA": ("ok", [offer("AAA", 150.0, via=("HUB",))])})
        self.assertEqual((result["nonstop"]["per_person_gbp"], result["leads"][0]["saving_gbp"]), (200.0, 50.0))

    def test_a_small_gap_is_not_a_lead(self):
        result = self.find({"HUB": ("ok", [offer("HUB", 200.0)]),
                            "AAA": ("ok", [offer("AAA", 185.0, via=("HUB",))]),
                            "BBB": ("ok", [offer("BBB", 205.0, via=("HUB",))])})
        self.assertEqual(result["leads"], [])
        self.assertEqual([r["status"] for r in result["reads"][1:3]], ["through fare, no saving"] * 2)

    def test_without_a_nonstop_fare_no_onward_city_is_read(self):
        asked = []
        result = bf.find_beyond_fares("LHR", HUB, DAY, fetcher({"HUB": ("refused", ())}, asked), now=NOW)
        self.assertEqual((asked, result["nonstop"], result["leads"]), (["HUB"], None, []))
        self.assertEqual(result["reads"], [{"destination": "HUB", "status": "refused"}])
        self.assertIn("nothing to compare with", bf.render_text(result))

    def test_a_refused_or_walled_read_is_named_and_counts_for_nothing(self):
        result = self.find({"HUB": ("ok", [offer("HUB", 200.0)]), "AAA": ("wall", [offer("AAA", 50.0, via=("HUB",))]),
                            "BBB": ("refused", ())})
        self.assertEqual(result["leads"], [])
        self.assertEqual([r["status"] for r in result["reads"][1:3]], ["wall", "refused"])

    def test_a_fare_in_another_currency_is_not_compared(self):
        result = self.find({"HUB": ("ok", [offer("HUB", 200.0)]),
                            "AAA": ("ok", [offer("AAA", 90.0, via=("HUB",), currency="USD")])})
        self.assertEqual(result["leads"], [])

    def test_a_hub_with_two_airports_takes_the_cheaper_nonstop_and_either_as_the_connection(self):
        tokyo = bf.Hub("TYO", "Tokyo", ("HND", "NRT"), ("CTS",))
        table = {"HND": ("ok", [offer("HND", 700.0)]), "NRT": ("ok", [offer("NRT", 650.0)]),
                 "CTS": ("ok", [offer("CTS", 500.0, via=("NRT",))])}
        result = bf.find_beyond_fares("LHR", tokyo, DAY, fetcher(table), now=NOW)
        self.assertEqual((result["nonstop"]["destination"], result["leads"][0]["leave_at"]), ("NRT", "NRT"))
        self.assertEqual(result["leads"][0]["saving_gbp"], 150.0)

    def test_leads_are_ordered_by_saving_and_carry_provenance_and_the_caveats(self):
        result = self.find({"HUB": ("ok", [offer("HUB", 300.0)]),
                            "AAA": ("ok", [offer("AAA", 250.0, via=("HUB",))]),
                            "BBB": ("ok", [offer("BBB", 150.0, via=("HUB",))])})
        self.assertEqual([lead["ticketed_to"] for lead in result["leads"]], ["BBB", "AAA"])
        for lead in result["leads"]:
            self.assertTrue(lead["source_url"].startswith("https://") and lead["observed_at"])
            self.assertEqual(lead["confidence_label"], "results-page, one traveller")
        self.assertEqual(result["caveats"], list(bf.CAVEATS))
        joined = " ".join(bf.CAVEATS)
        for phrase in ("One way only", "Hand luggage only", "conditions of carriage", "reroutes", "visa"):
            self.assertIn(phrase, joined)


class DataAndReaderTests(unittest.TestCase):
    def test_every_hub_in_the_data_file_is_well_formed(self):
        hubs = bf.load_hubs()
        self.assertGreaterEqual(len(hubs), 5)
        for hub in hubs.values():
            self.assertTrue(hub.airports and hub.beyond, hub.hub)
            self.assertFalse(set(hub.airports) & set(hub.beyond), hub.hub)
            self.assertLessEqual(len(hub.beyond), bf.MAX_BEYOND_PER_HUB)

    def test_the_reader_names_each_connection_airport(self):
        def segment(origin, destination, minutes):
            seg = [None] * 22
            seg[3], seg[6], seg[11] = origin, destination, minutes
            return seg

        flight = [None] * 10
        flight[1], flight[2], flight[3] = ["Sample Air"], [segment("LHR", "HUB", 240), segment("HUB", "AAA", 150)], "LHR"
        flight[4], flight[5], flight[6], flight[7], flight[8], flight[9] = [2030, 9, 1], [8, 15], "AAA", [2030, 9, 1], [17, 0], 480
        payload = [None] * 4
        payload[3] = [[[flight, [[None, 246]]]]]
        html = '<script class="ds:1">AF_initDataCallback({data:' + json.dumps(payload) + ',sideChannel:{}});</script>'
        search = FlightSearch(key="t", label="t", origins=("LHR",), destinations=("AAA",), dates=("2030-09-01",),
                              travellers=1, cabin_class="ECONOMY", departure_window=("00:00", "23:59"), max_stops=1,
                              max_duration_minutes=1440, max_price_per_traveller_gbp=None)
        offers = _parse_flight_cards(html, search=search, origin="LHR", destination="AAA", day="2030-09-01",
                                     booking_url="https://www.google.com/travel/flights/search?tfs=x")
        self.assertEqual((offers[0].stops, offers[0].via_airports), (1, ("HUB",)))

    def test_a_nonstop_offer_names_no_connection(self):
        self.assertEqual(offer("HUB", 100.0).via_airports, ())

    def test_the_live_fetch_reports_googles_error_notice_as_refused(self):
        refused = ('<html><body><script class="ds:1">AF_initDataCallback({data:' + json.dumps([None, None, [["x"]]])
                   + ',errorHasStatus: true});</script></body></html>')
        with patch("public_flight_search.google_flights._fetch_page_html", return_value=refused):
            self.assertEqual(bf.make_google_fetch()(bf.FareRead("LHR", "IST", DAY)), ("refused", ()))
        with patch("public_flight_search.google_flights._fetch_page_html", return_value=None):
            self.assertEqual(bf.make_google_fetch()(bf.FareRead("LHR", "IST", DAY)), ("failed", ()))


class CommandTests(unittest.TestCase):
    def run_main(self, *arguments):
        out, err = io.StringIO(), io.StringIO()
        table = {"IST": ("ok", [offer("IST", 200.0)]), "TBS": ("ok", [offer("TBS", 120.0, via=("IST",))])}
        with patch.object(bf, "make_google_fetch", lambda: fetcher(table)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = bf.main(list(arguments))
        return code, out.getvalue(), err.getvalue()

    def test_the_command_prints_the_lead_and_always_the_caveats(self):
        code, out, err = self.run_main("--hub", "IST", "--date", "2099-02-10")
        self.assertEqual(code, 0)
        self.assertIn("ticket to TBS, leaving at IST: £120 (Test Air), £80 less (40%)", out)
        self.assertIn("Before buying any of these:", out)
        self.assertIn("1 cheaper onward ticket(s)", err)

    def test_an_unknown_hub_or_a_past_date_is_refused(self):
        for arguments in (("--hub", "ZZZ", "--date", "2099-02-10"), ("--hub", "IST", "--date", "2020-01-01")):
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                bf.main(list(arguments))

    def test_nothing_schedules_or_mails_it(self):
        for workflow in (ROOT / ".github" / "workflows").glob("*.yml"):
            self.assertNotIn("beyond-fares", workflow.read_text(encoding="utf-8"), workflow.name)


if __name__ == "__main__":
    unittest.main()
