"""Curator deal ideas (owner, 21 Nov 2026): a public link page's deals matched to the trip's dates, read without
requesting an operator's page, and shown as ideas that never price a card. Every page, link and figure here is
synthetic."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from public_flight_search import curated_leads as cl
from public_flight_search.holidays import load_holiday_config
from public_flight_search.weekly_fares import insert_section

ROOT = Path(__file__).resolve().parents[1]
JULY = ROOT / "examples" / "july_holiday_config.json"
WORKFLOW = ROOT / ".github" / "workflows" / "july-holiday-planner.yml"
NOW = datetime(2026, 11, 21, 9, 0, tzinfo=timezone.utc)
CONFIG = SimpleNamespace(outbound_dates=("2027-06-25", "2027-06-30"), min_nights=12, max_nights=21,
                         origins=("LHR", "LGW"), travellers=5)
OPERATOR = "https://www.icelolly.com/holiday-search/v2/results/111-222+abc"


def linktree(links):
    data = {"props": {"pageProps": {"links": links}}}
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></html>'


def awin(target):
    from urllib.parse import quote

    return "https://www.awin1.com/cread.php?awinmid=1&awinaffid=2&ued=" + quote(target, safe=":/") + "&platform=sl"


class Network:
    """A page per source and a redirect header per short link; records every address asked for."""

    def __init__(self, links, redirects):
        self.page = linktree(links)
        self.redirects = redirects
        self.asked = []

    def fetch_page(self, url):
        self.asked.append(url)
        return self.page

    def fetch_location(self, url):
        self.asked.append(url)
        return self.redirects.get(url, "")


def read(links, redirects, now=NOW, config=CONFIG):
    net = Network(links, redirects)
    payload = cl.read_curated_leads(config, [{"name": "Example Curator", "url": "https://linktr.ee/example"}],
                                    net.fetch_page, net.fetch_location, now=now)
    return payload, net


class TitleTests(unittest.TestCase):
    def test_price_basis_stars_and_board_come_from_the_title(self):
        got = cl.parse_title("5⭐️ All Inclusive Sunport 🇹🇷 Resort with Direct Flights 🏝️ - £299pp")
        self.assertEqual((got["price_gbp"], got["basis"], got["stars"], got["board"]),
                         (299.0, "pp", 5, "All inclusive"))
        self.assertEqual(got["title"], "5* All Inclusive Sunport Resort with Direct Flights")

    def test_per_night_price_is_not_read_as_a_trip_price(self):
        got = cl.parse_title("5* Island Holiday with Flights - £91pppn")
        self.assertEqual((got["price_gbp"], got["basis"]), (91.0, "pppn"))
        self.assertEqual(cl.per_person_total({**got, "nights": 10}), 910.0)
        self.assertIsNone(cl.per_person_total({**got, "nights": 0}))

    def test_a_bare_price_gets_no_basis_and_a_price_without_a_pound_sign_is_read(self):
        self.assertEqual(cl.parse_title("4* City Break - £129")["basis"], "")
        got = cl.parse_title("5* All Inclusive Resort 10 nights & Flights - 259pp")
        self.assertEqual((got["price_gbp"], got["basis"]), (259.0, "pp"))

    def test_a_deposit_or_a_was_price_is_not_the_deal_price(self):
        got = cl.parse_title("Island 5* All Inclusive £499pp (£29pp deposit)")
        self.assertEqual((got["price_gbp"], got["title"]), (499.0, "Island 5* All Inclusive (£29pp deposit)"))
        got = cl.parse_title("5* Resort was £699 now £449pp")
        self.assertEqual((got["price_gbp"], got["title"]), (449.0, "5* Resort was £699"))

    def test_a_price_at_the_front_is_cut_out_of_the_name(self):
        got = cl.parse_title("£299pp – Island 5* All Inclusive")
        self.assertEqual((got["price_gbp"], got["title"], got["stars"]), (299.0, "Island 5* All Inclusive", 5))

    def test_a_black_star_and_a_keycap_are_read_or_removed(self):
        self.assertEqual(cl.parse_title("Island 5\u2605 All Inclusive - £399pp")["stars"], 5)
        self.assertNotIn("\u20e3", cl.parse_title("Island 5\ufe0f\u20e3 nights - £399pp")["title"])

    def test_a_year_or_a_night_count_is_never_the_price(self):
        self.assertIsNone(cl.parse_title("CHEAP FLIGHTS 2026")["price_gbp"])
        self.assertEqual(cl.parse_title("5* Resort 14 nights July 2027 - £387pp")["price_gbp"], 387.0)


class LinkTests(unittest.TestCase):
    def test_operator_address_is_read_from_the_redirect_and_the_operator_is_never_asked(self):
        target = OPERATOR + "/LHR+LGW/2027-06-26/14/2+8+4?boardBases=AI&ratings=5&orderby=price+asc"
        payload, net = read([{"title": "5* Resort - £500pp", "url": "https://tidd.ly/abc"}],
                            {"https://tidd.ly/abc": awin(target)})
        lead = payload["leads"][0]
        self.assertEqual(lead["operator_url"], target)
        self.assertEqual((lead["airports"], lead["departure"], lead["nights"], lead["party"], lead["board"]),
                         (["LHR", "LGW"], "2027-06-26", 14, "2+8+4", "All inclusive"))
        self.assertEqual(net.asked, ["https://linktr.ee/example", "https://tidd.ly/abc"])

    def test_a_plus_in_the_operator_path_survives_unwrapping(self):
        self.assertIn("/LHR+LGW/", cl.wrapped_target(awin(OPERATOR + "/LHR+LGW/2027-06-26/14/2")))

    def test_a_link_straight_to_an_operator_is_not_requested(self):
        asked = []
        self.assertEqual(cl.resolve("https://www.example-operator.co.uk/deal/1", lambda u: asked.append(u) or ""),
                         "https://www.example-operator.co.uk/deal/1")
        self.assertEqual(asked, [])

    def test_a_forwarding_host_that_gives_no_redirect_leaves_the_lead_undated(self):
        payload, _ = read([{"title": "5* Resort - £500pp", "url": "https://tidd.ly/gone"}], {})
        self.assertEqual((payload["leads"][0]["operator_url"], payload["leads"][0]["fit"]), ("", "undated"))

    def test_only_https_addresses_are_asked_or_returned(self):
        asked = []
        hops = {"https://tidd.ly/a": "http://tidd.ly/b", "https://tidd.ly/c": "http://169.254.169.254/latest"}

        def location(url):
            asked.append(url)
            return hops.get(url, "")

        self.assertEqual(cl.resolve("https://tidd.ly/a", location), "")
        self.assertEqual(cl.resolve("https://tidd.ly/c", location), "")
        self.assertEqual(cl.resolve("http://tidd.ly/a", location), "")
        self.assertEqual(asked, ["https://tidd.ly/a", "https://tidd.ly/c"])

    def test_a_wrapped_address_that_is_itself_a_forwarder_is_followed_and_a_loop_ends(self):
        target = OPERATOR + "/LHR/2027-06-26/7/2"
        hops = {"https://prf.hn/x": awin("https://tidd.ly/y"), "https://tidd.ly/y": awin(target),
                "https://tidd.ly/loop": "https://tidd.ly/loop"}
        self.assertEqual(cl.resolve("https://prf.hn/x", lambda u: hops.get(u, "")), target)
        asked = []
        self.assertEqual(cl.resolve("https://tidd.ly/loop", lambda u: asked.append(u) or hops[u]), "")
        self.assertEqual(len(asked), 4)

    def test_a_zero_night_link_is_not_a_stay(self):
        self.assertEqual(cl.parse_operator_url(OPERATOR + "/LHR/2027-06-26/0/2")["departure"], "")

    def test_an_unknown_operator_shape_gives_a_name_and_no_date(self):
        got = cl.parse_operator_url("https://www.example-operator.co.uk/deal/travel/2027-06-26/break")
        self.assertEqual((got["operator"], got["departure"], got["nights"]), ("example-operator", "", 0))

    def test_an_impossible_date_in_the_path_is_not_a_departure(self):
        self.assertEqual(cl.parse_operator_url(OPERATOR + "/LHR/2027-13-45/7/2")["departure"], "")

    def test_tracking_parameters_are_dropped_from_the_stored_address(self):
        self.assertEqual(cl.strip_tracking(OPERATOR + "/LHR/2027-06-26/7/2?ratings=5&awc=1_2_3&utm_source=AWIN"),
                         OPERATOR + "/LHR/2027-06-26/7/2?ratings=5")

    def test_a_link_with_no_price_is_not_a_lead_and_its_link_is_not_followed(self):
        payload, net = read([{"title": "CHEAP FLIGHTS 2026", "url": "https://skyscanner.pxf.io/x"}], {})
        self.assertEqual(payload["leads"], [])
        self.assertEqual(net.asked, ["https://linktr.ee/example"])

    def test_an_unreadable_page_is_no_links_not_an_error(self):
        self.assertEqual(cl.parse_linktree("<html>challenge</html>"), [])
        self.assertEqual(cl.parse_linktree('<script id="__NEXT_DATA__">{broken</script>'), [])


class WindowTests(unittest.TestCase):
    WIN = cl.window(CONFIG)

    def fit(self, departure, nights, airports=("LHR",)):
        return cl.classify({"departure": departure, "nights": nights, "airports": list(airports)}, self.WIN,
                           NOW.date())

    def test_a_match_needs_the_date_the_nights_and_a_home_airport(self):
        self.assertEqual(self.fit("2027-06-27", 14), ("match", ""))
        self.assertEqual(self.fit("2027-06-27", 14, ("MAN",))[0], "idea")

    def test_inside_the_window_with_too_few_nights_is_near_and_says_why(self):
        self.assertEqual(self.fit("2027-06-27", 7), ("near", "inside your window, 7 nights (yours 12-21)"))

    def test_near_is_fourteen_days_either_side_and_counts_the_gap(self):
        self.assertEqual(self.fit("2027-07-01", 14), ("near", "1 day after your window"))
        self.assertEqual(self.fit("2027-06-11", 14), ("near", "14 days before your window"))
        self.assertEqual(self.fit("2027-06-10", 14)[0], "idea")
        self.assertEqual(self.fit("2027-07-15", 14)[0], "idea")

    def test_a_posted_date_that_has_passed_is_past_and_no_date_is_undated(self):
        self.assertEqual(self.fit("2026-11-20", 7)[0], "past")
        self.assertEqual(self.fit("", 0)[0], "undated")

    def test_your_dates_link_moves_only_the_date_nights_and_airports(self):
        lead = {"operator": "icelolly", "operator_url": OPERATOR + "/STN/2027-03-08/5/2+8?ratings=5"}
        self.assertEqual(cl.your_dates_url(lead, self.WIN),
                         (OPERATOR + "/LHR+LGW/2027-06-25/14/2+8?ratings=5", "25 Jun · 14n"))
        self.assertEqual(cl.your_dates_url({"operator": "wowcher", "operator_url": "https://x"}, self.WIN), ("", ""))

    def test_the_example_config_gives_a_window(self):
        win = cl.window(load_holiday_config(JULY.read_text(encoding="utf-8")))
        self.assertTrue(win["first"] <= win["last"] and win["origins"] and win["min_nights"] <= win["max_nights"])


class SectionTests(unittest.TestCase):
    def payload(self):
        links, redirects = [], {}
        for i, (title, path) in enumerate([
                ("5* Fits Resort - £900pp", "/LHR/2027-06-26/14/2+8?pinnedAccommodationId=1"),
                ("5* Near Resort - £400pp", "/LGW/2027-07-01/5/2?pinnedAccommodationId=2"),
                ("5* Spring Resort from LONDON - £250pp", "/LHR/2027-03-08/5/2?pinnedAccommodationId=3"),
                ("5* Spring Resort from MANCHESTER - £240pp", "/MAN/2027-03-07/5/2?pinnedAccommodationId=3"),
                ("5* Spring Resort second link - £260pp", "/LGW/2027-03-09/5/2?pinnedAccommodationId=3"),
                ("5* Other Resort same region - £300pp", "/LGW/2027-03-09/5/2?pinnedAccommodationId=4"),
                ("5* Gone Resort - £100pp", "/LHR/2026-11-01/7/2")]):
            short = f"https://tidd.ly/{i}"
            links.append({"title": title, "url": short})
            redirects[short] = awin(OPERATOR + path)
        links.append({"title": "City Break <b>voucher</b> - £59pp", "url": "https://tidd.ly/v"})
        redirects["https://tidd.ly/v"] = awin("https://www.example-vouchers.co.uk/deal/travel/city-break")
        return read(links, redirects)[0]

    def test_rows_are_matches_then_near_then_one_idea_per_place_from_a_home_airport(self):
        payload = self.payload()
        self.assertEqual([r["fit"] for r in cl.shown_rows(payload)], ["match", "near"])
        self.assertEqual([r["title"] for r in cl.shown_rows(payload, ("idea",))],
                         ["5* Spring Resort from LONDON", "5* Other Resort same region"])
        text = cl.render_section_text(payload)
        self.assertIn("On other dates (4), the best from your airports: 5* Spring Resort from LONDON £250 pp, "
                      "8 Mar 2027; 5* Other Resort same region £300 pp, 9 Mar 2027", text)
        self.assertNotIn("Spring Resort from LONDON:", text, "an other-date idea is never a table row")

    def test_the_caption_says_whose_price_it_is_and_counts_what_fits(self):
        text = cl.render_section_text(self.payload())
        self.assertIn("this run did not check them and they are not a price for 5", text)
        self.assertIn("1 fits your window (25 Jun to 30 Jun 2027, 12-21 nights); 1 within 14 days of it.", text)
        self.assertIn("1 posted for a date that has passed are left out.", text)
        self.assertNotIn("Gone Resort", text)

    def test_curator_text_is_escaped_and_only_https_links_are_linked(self):
        payload = self.payload()
        payload["leads"][0]["link"] = "javascript:alert(1)"
        html = cl.render_section_html(payload)
        self.assertIn("City Break &lt;b&gt;voucher&lt;/b&gt;", html)
        self.assertNotIn("<b>voucher", html)
        self.assertNotIn("javascript:", html)

    def test_the_section_sits_above_the_footnote_and_is_capped(self):
        body = '<div class="b"><div style="x"><div style="y">Not shown</div>rows</div></div>'
        merged = insert_section(body, cl.render_section_html(self.payload()))
        self.assertLess(merged.index("Deal ideas from curators"), merged.index(">Not shown</div>"))
        many = self.payload()
        many["leads"] = [{**many["leads"][1], "place_key": str(n), "title": f"Near {n}"} for n in range(40)]
        self.assertEqual(len(cl.shown_rows(many)), cl.MAX_ROWS)
        self.assertLess(len(cl.render_section_html(many).encode("utf-8")), 16_000)

    def test_a_file_older_than_a_week_or_of_another_schema_is_not_shown(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "curated_leads.json")
            Path(path).write_text(json.dumps(self.payload()), encoding="utf-8")
            self.assertIsNotNone(cl.load_curated_leads(path, NOW + timedelta(days=7)))
            self.assertIsNone(cl.load_curated_leads(path, NOW + timedelta(days=9)))
            Path(path).write_text(json.dumps({"schema": "other/1"}), encoding="utf-8")
            self.assertIsNone(cl.load_curated_leads(path, NOW))
        self.assertEqual(cl.render_section_html(None), "")

    def test_every_lead_carries_its_provenance(self):
        for lead in self.payload()["leads"]:
            self.assertEqual(lead["confidence_label"], "curator-posted")
            self.assertTrue(lead["source_url"].startswith("https://") and lead["observed_at"] and lead["link"])

    def test_no_further_page_is_read_once_the_budget_is_spent(self):
        net = Network([{"title": "5* Resort - £500pp", "url": "https://tidd.ly/abc"}], {})
        ticks = iter([0.0, 0.0, 0.0, 500.0])
        sources = [{"name": "one", "url": "https://linktr.ee/one"}, {"name": "two", "url": "https://linktr.ee/two"}]
        payload = cl.read_curated_leads(CONFIG, sources, net.fetch_page, net.fetch_location, now=NOW,
                                        budget_seconds=180, clock=lambda: next(ticks))
        self.assertEqual(net.asked, ["https://linktr.ee/one", "https://tidd.ly/abc"])
        self.assertEqual([s["links"] for s in payload["sources"]], [1, 0])

    def test_links_are_not_followed_once_the_budget_is_spent(self):
        net = Network([{"title": "5* Resort - £500pp", "url": "https://tidd.ly/abc"}], {})
        ticks = iter([0.0, 0.0, 500.0])
        payload = cl.read_curated_leads(CONFIG, [{"name": "c", "url": "https://linktr.ee/example"}], net.fetch_page,
                                        net.fetch_location, now=NOW, budget_seconds=180, clock=lambda: next(ticks))
        self.assertEqual(net.asked, ["https://linktr.ee/example"])
        self.assertEqual(payload["leads"][0]["fit"], "undated")


class WiringTests(unittest.TestCase):
    def test_a_july_dry_run_with_a_leads_file_puts_the_section_in_the_body(self):
        import contextlib
        import io
        import os
        from unittest.mock import patch

        from public_flight_search import jobs
        from public_flight_search import weekly_fares as wf

        payload, _ = read([{"title": "City Break voucher - £59pp", "url": "https://tidd.ly/v"}],
                          {"https://tidd.ly/v": awin("https://www.example-vouchers.co.uk/deal/travel/city-break")},
                          now=datetime.now(timezone.utc))
        bodies = []
        real = wf.insert_section

        def spy(html, section):
            bodies.append(real(html, section))
            return bodies[-1]

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "curated_leads.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            keep = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "PYTHONPATH")}
            keep.update(CURATED_LEADS_PATH=str(path), HOLIDAY_HISTORY_PATH=str(Path(tmp) / "h.jsonl"),
                        JULY_WEEKLY_FARES_PATH=str(Path(tmp) / "none.json"),
                        BUSINESS_DEALS_HISTORY=str(Path(tmp) / "none.jsonl"),
                        BUSINESS_DEALS_MULTIVENDOR_HISTORY=str(Path(tmp) / "none2.jsonl"))
            with patch.dict(os.environ, keep, clear=True), patch.object(wf, "insert_section", spy), \
                    contextlib.redirect_stdout(io.StringIO()):
                result = jobs.run_holiday_planner(dry_run=True, config_path=str(JULY), expect_season="july")
        self.assertFalse(result["email_sent"])
        self.assertIn("Deal ideas from curators", bodies[-1])
        self.assertIn("City Break voucher £59 pp", bodies[-1])
        self.assertLess(bodies[-1].index("Deal ideas from curators"), bodies[-1].index(">Not shown</div>"))

    def test_sources_are_https_pages_and_the_environment_can_replace_them(self):
        self.assertTrue(all(s["url"].startswith("https://") for s in cl.load_sources()))
        self.assertTrue(cl.load_sources())
        got = cl.load_sources(env={"CURATED_LEAD_SOURCES": "https://linktr.ee/one, http://insecure.example/x"})
        self.assertEqual(got, [{"name": "one", "url": "https://linktr.ee/one"}])

    def test_the_workflow_reads_the_ideas_before_the_build_and_cannot_fail_the_run(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        step = text[text.index("- name: Read curator deal ideas"):text.index("- name: Build and optionally deliver")]
        self.assertIn("continue-on-error: true", step)
        self.assertIn("curated-leads", step)
        self.assertIn("--out data/curated_leads.json", step)

    def test_no_operator_host_is_a_forwarding_host(self):
        for host in ("www.icelolly.com", "www.wowcher.co.uk", "www.skyscanner.net", "linktr.ee"):
            self.assertFalse(cl._is_tracker(f"https://{host}/x"), host)
        self.assertTrue(cl._is_tracker("https://www.awin1.com/cread.php") and cl._is_tracker("https://tidd.ly/a"))


if __name__ == "__main__":
    unittest.main()
