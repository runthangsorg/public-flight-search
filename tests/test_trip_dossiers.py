"""One self-contained dossier per trip, a summary table that links to them, and a vendor-versus-ours block (22 Oct 2026).

Owner, 22 Oct 2026, on the freshness-strip layout: "it looks ok but claude needs to consider design and layout again
to make it easily understandable and followable but also full verbose details of itineraries, flights, times stayed,
hotel reviews, and deep links to actual bookings etc. and equiv pre-packaged vendor holidays vs mine".

What these tests pin, from SYNTHETIC reads and the shipped ``multi_centre.json``:

* reading order: start here, how current, the summary table, then one dossier per trip in the table's order, then the
  single resorts, then the rest; every table row links to a dossier that exists;
* every dossier has its labelled sections, and a detail the data does not hold is said to be not collected, never
  invented (flight times, guest ratings, a property that has not been chosen, a counterpart package);
* every link opens the thing it names: the dates inside a hotel link and inside the flights link equal the dates the
  dossier prints for that stay and those legs;
* a package and our build of the same shape sit side by side, with the pound difference stated and computed;
* the whole e-mail stays under the Gmail byte budget, shortens the LEAST important detail first, never drops a trip,
  and says what it shortened; the plain-text part keeps every dossier in full.
"""

from __future__ import annotations

import base64
import contextlib
import io
import json
import re
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch

from public_flight_search import holidays as hol
from public_flight_search.holiday_email import (
    _multi_centre_rows,
    multi_centre_wanted,
    render_holiday_report_compact,
    render_holiday_report_compact_text,
)
from public_flight_search.hotel_evidence import HotelRating, normalise_property_name
from public_flight_search.multi_centre import trip_legs_for_dates, trip_stays_for_dates
from public_flight_search.trip_dossier import build_trip_dossiers

from test_holiday_email_compact import _config, _deals, visible_text
from test_multi_centre_reads import _multi_centre_read

NOW = "2026-10-22T13:25:00+00:00"
STAMPS = {k: "2026-10-21T03:40:00+00:00"
          for k in ("safari_flights", "resort_flights", "hotel_rates", "operator_packages")}
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _words(iso: str) -> str:
    year, month, day = (int(p) for p in iso.split("-"))
    return f"{day} {MONTHS[month - 1]}"


def _reads(trip_ids=None, **overrides):
    """A fares registry holding one SYNTHETIC dated read per wanted trip (or per listed id)."""
    config = _config()
    wanted = [w for w in multi_centre_wanted(config) if trip_ids is None or w["trip"] in trip_ids]
    rows = []
    for want in wanted:
        row = _multi_centre_read(want, observed_at="2026-10-20T10:00:00+00:00", total=5134.0)
        row.update({"carrier": "Kenya AirwaysVirgin Atlantic", "stops": 1, "layovers": "3 hrs NBO",
                    "duration": "12 hrs 50 min"})
        row.update(overrides)
        rows.append(row)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "stopover_reads_synthetic.json"
        path.write_text(json.dumps({"schema": hol.STOPOVER_READS_SCHEMA, "rows": rows}), encoding="utf-8")
        with contextlib.redirect_stderr(io.StringIO()):
            _stops, fares = hol.load_batch_reads(str(path))
    hol.consume_stopover_skip_log()
    return fares


#: The size tests ask for the real budget; every other test looks at the FULL dossiers, so it lifts the budget:
#: a budget that shortens the last trips would make "every dossier has its sections" a test of the shortening.
UNLIMITED = 10 ** 9


def _html(*, fares=None, deals=None, ratings=None, budget=UNLIMITED, **kw):
    with patch.object(hol, "EMAIL_HTML_BUDGET_BYTES", budget):
        return render_holiday_report_compact(
            _config(), generated_at=NOW, deals=_deals(4) if deals is None else deals,
            evidence_stamps=STAMPS, multi_centre_fares=fares, hotel_ratings=ratings, **kw)


def _text(*, fares=None, deals=None, ratings=None, **kw):
    return render_holiday_report_compact_text(
        _config(), generated_at=NOW, deals=_deals(4) if deals is None else deals,
        evidence_stamps=STAMPS, multi_centre_fares=fares, hotel_ratings=ratings, **kw)


def _rows(fares=None):
    return _multi_centre_rows(_config(), fares=fares)


def _dossiers(fares=None, ratings=None):
    return build_trip_dossiers(_config(), _rows(fares), generated_at=NOW, hotel_ratings=ratings)


def _slice(html: str, anchor: str) -> str:
    """One dossier's HTML: from its anchor to the next anchor of any dossier, resort or section."""
    start = html.index(f'id="{anchor}"')
    ends = [html.find(marker, start + 1) for marker in ('id="trip-', 'id="deal-', 'id="resorts"')]
    ends = [e for e in ends if e > 0]
    return html[start:min(ends)] if ends else html[start:]


def _ids(html: str) -> list[str]:
    return re.findall(r'id="trip-([A-Z]{2}-\d+)"', html)


def _table_ids(html: str) -> list[str]:
    """The trips the at-a-glance table links to, in its order."""
    table = html[html.index("Every option at a glance"):html.index('id="trips"')]
    return re.findall(r'href="#trip-([A-Z]{2}-\d+)"', table)


def _tfs_legs(url: str) -> list[tuple[str, str, str]]:
    """(origin, destination, date) of every leg a Google Flights ``tfs=`` link searches, decoded from it."""
    raw = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["tfs"][0]
    payload = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    dates = [m.decode() for m in re.findall(rb"\x12\n(\d{4}-\d{2}-\d{2})", payload)]
    airports = [m.decode() for m in re.findall(rb"\x12\x03([A-Z]{3})", payload)]
    assert len(airports) == 2 * len(dates), (airports, dates)
    return [(airports[2 * i], airports[2 * i + 1], dates[i]) for i in range(len(dates))]


def _hotel_link_dates(url: str):
    """The (check-in, check-out) a hotel-site link carries, decoded from its own query string."""
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    host = urllib.parse.urlparse(url).netloc
    if "booking.com" in host:
        return query["checkin"][0], query["checkout"][0]
    if "google.com" in host:
        first, second = query["dates"][0].split(",")
        return first, second
    if "expedia" in host:
        return query["startDate"][0], query["endDate"][0]
    raise AssertionError(f"not a hotel-site link: {url}")


class ReadingOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fares = _reads()
        cls.html = _html(fares=cls.fares)

    def test_start_here_then_how_current_then_the_table_then_the_dossiers_then_the_resorts(self):
        h = self.html
        order = [h.index("Start here"), h.index("How current this is"), h.index("Every option at a glance"),
                 h.index('id="trip-'), h.index('id="resorts"'), h.index('id="deal-1"')]
        self.assertEqual(order, sorted(order))

    def test_start_here_is_two_short_lines_and_jumps_to_the_three_answers(self):
        h = self.html
        box = h[h.index("Start here"):h.index("How current this is")]
        text = visible_text(box)
        guidance = text[:text.index("Quick answers")]
        self.assertLess(len(guidance.split()), 45, "start-here guidance is a line or two, not a page")
        self.assertLess(len(text.split()), 130)
        for label in ("Cheapest that fits", "Tanzania safari", "Package vs our build"):
            self.assertIn(label, text)
        for target in re.findall(r'href="#([^"]+)"', box):
            self.assertIn(f'id="{target}"', h, f"start-here jumps to a page that does not exist: {target}")
        self.assertGreaterEqual(len(re.findall(r'href="#', box)), 3)

    def test_every_table_row_links_to_a_dossier_that_exists_exactly_once(self):
        table_ids = _table_ids(self.html)
        self.assertEqual(sorted(table_ids), sorted({r["trip"].id for r in _rows(self.fares)}))
        for ident in table_ids:
            self.assertEqual(self.html.count(f'id="trip-{ident}"'), 1, ident)

    def test_the_dossiers_come_in_the_order_the_table_lists_them(self):
        self.assertEqual(_ids(self.html), _table_ids(self.html))

    def test_tanzania_safari_plus_zanzibar_dossiers_come_first(self):
        by_id = {r["trip"].id: r["trip"] for r in _rows(self.fares)}
        first = [by_id[i].title for i in _ids(self.html)[:4]]
        for title in first[:3]:
            self.assertRegex(title, r"Serengeti|Tanzania|Ngorongoro|Nyerere|Sayari")
            self.assertIn("Zanzibar", title)

    def test_group_headings_survive_as_labels_over_the_dossiers(self):
        text = visible_text(self.html)
        self.assertIn("Africa safari + beach", text)
        self.assertIn("Two-centre trips", text)
        self.assertLess(text.index("Africa safari + beach"), text.index("Two-centre trips"))

    def test_the_resort_cards_follow_every_dossier_and_the_rest_follows_the_cards(self):
        h = self.html
        last_trip = h.rindex('id="trip-')
        self.assertLess(last_trip, h.index('id="deal-1"'))
        self.assertLess(h.index('id="deal-4"'), h.index("Notes") if "Notes" in h else len(h))

    def test_the_plain_text_has_the_same_order(self):
        text = _text(fares=self.fares)
        marks = [text.index("Start here"), text.index("Every option at a glance"),
                 text.index("Itinerary"), text.rindex("Test Resort 0 ")]
        self.assertEqual(marks, sorted(marks))


class EveryDossierHasItsSectionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = _html(fares=_reads())
        cls.rows = {r["trip"].id: r for r in _rows(_reads())}

    def test_every_dossier_has_a_price_an_itinerary_flights_and_links_section(self):
        for ident in self.rows:
            with self.subTest(trip=ident):
                part = visible_text(_slice(self.html, f"trip-{ident}"))
                for heading in ("Itinerary", "Flights", "Links"):
                    self.assertIn(heading, part)
                self.assertRegex(part, r"£[\d,]+")

    def test_every_dossier_states_the_package_comparison_or_the_lack_of_one(self):
        for ident in self.rows:
            with self.subTest(trip=ident):
                part = visible_text(_slice(self.html, f"trip-{ident}"))
                self.assertTrue(
                    "Package vs our build" in part
                    or "no equivalent vendor package found yet" in part
                    or "no self-build of this shape yet" in part, part[:300])

    def test_every_dossier_names_the_nights_and_the_dates_of_each_stay(self):
        for ident, row in self.rows.items():
            with self.subTest(trip=ident):
                plan = trip_stays_for_dates(row["trip"], row["outbound"], row["return"])
                part = visible_text(_slice(self.html, f"trip-{ident}"))
                for stay in plan.stays:
                    self.assertIn(f"{_words(stay.check_in)} → {_words(stay.check_out)}", part)
                    self.assertRegex(part, rf"{stay.nights} nights?")

    def test_a_dossier_stays_inside_a_readable_length(self):
        for ident in self.rows:
            with self.subTest(trip=ident):
                # A full dossier is the verbose page the owner asked for, in labelled sections; this is the bound
                # that keeps it from becoming a wall (the whole e-mail is bound by bytes, not by this).
                # 650 until 23 Oct 2026. A page whose price itemises its flights now carries two totals, the note on what
                # each product is, and, when both reads have every flight, six flight lines: measured worst case 886
                # words (AF-10 with both products and per-leg lists), 685 with the Economy-only reads used here. The
                # structure (short labelled sections) is what keeps it readable; this bound still stops a wall.
                self.assertLess(len(visible_text(_slice(self.html, f"trip-{ident}")).split()), 950)


class NotCollectedIsSaidNotInventedTests(unittest.TestCase):
    def test_a_trip_with_no_read_says_so_and_offers_the_search(self):
        html = _html(fares=None)
        part = _slice(html, "trip-AF-01")
        self.assertIn("Not read for these dates yet", visible_text(part))
        row = {r["trip"].id: r for r in _rows()}["AF-01"]
        self.assertIn(row["url"].replace("&", "&amp;"), part)

    def test_times_of_day_are_said_to_be_missing_exactly_once_per_dossier(self):
        html = _html(fares=_reads())
        for ident in _ids(html):
            with self.subTest(trip=ident):
                self.assertEqual(visible_text(_slice(html, f"trip-{ident}")).count("not captured"), 1)

    def test_a_mixed_cabin_read_says_which_legs_are_in_which_cabin_and_is_not_called_economy(self):
        mix = "Business LHR-JRO, ZNZ-LHR + Economy JRO-ZNZ"
        fares = _reads(["AF-01"], cabin="MIXED", cabin_mix=mix, total_gbp=21000.0)
        part = visible_text(_slice(_html(fares=fares), "trip-AF-01"))
        self.assertIn(f"the whole trip, {mix}, read", part)
        self.assertNotIn("the whole trip, Economy, read", part)
        text = _text(fares=fares)
        self.assertIn(mix, text)

    def test_a_pure_economy_read_still_says_economy(self):
        part = visible_text(_slice(_html(fares=_reads(["AF-01"])), "trip-AF-01"))
        self.assertIn("the whole trip, Economy, read", part)

    def test_times_that_the_read_carries_are_shown_and_not_called_missing(self):
        fares = _reads(["AF-01"], departure_local="2027-06-27T21:40:00", arrival_local="2027-06-28T13:05:00")
        part = visible_text(_slice(_html(fares=fares), "trip-AF-01"))
        self.assertIn("21:40", part)
        self.assertIn("13:05", part)
        self.assertNotIn("times not captured", part)
        self.assertEqual(part.count("not captured"), 1, "the other flights' times are still said to be missing, once")
        self.assertIn("first flight", part.lower())

    def test_the_read_flight_is_described_with_its_carriers_stops_layover_and_duration(self):
        part = visible_text(_slice(_html(fares=_reads(["AF-01"])), "trip-AF-01"))
        self.assertIn("Kenya Airways + Virgin Atlantic", part, "the parser's run-together names are split for the reader")
        self.assertNotIn("Kenya AirwaysVirgin", part)
        self.assertIn("1 stop", part)
        self.assertIn("3 hrs NBO", part)
        self.assertIn("12 hrs 50 min", part)
        self.assertIn("£5,134 for 5", part)
        self.assertIn("20 Oct", part)

    def test_a_self_build_priced_with_flights_from_other_dates_says_which_figure_its_price_uses(self):
        part = visible_text(_slice(_html(fares=None), "trip-AF-08"))
        self.assertIn("Not read for these dates yet", part)
        self.assertIn("The price above includes £5,134 for flights", part)
        self.assertIn("nearest dates", part)
        self.assertNotIn("The price above includes", visible_text(_slice(_html(fares=None), "trip-AF-01")),
                         "a trip with no flights line in its price has nothing to say here")

    def test_the_read_links_to_the_page_it_was_read_from(self):
        fares = _reads(["AF-01"])
        part = _slice(_html(fares=fares), "trip-AF-01")
        source = next(iter(fares.values()))["source_url"]
        self.assertIn(source, part)

    def test_a_trip_none_of_whose_properties_has_a_rating_says_so_once_not_under_each(self):
        part = visible_text(_slice(_html(), "trip-AF-01"))
        self.assertEqual(part.count("guest rating not collected"), 1)  # three named properties, one statement
        self.assertIn("guest rating not collected for any property on this trip", part)

    def test_a_lodge_with_a_rating_shows_score_source_count_and_link_and_is_not_called_unrated(self):
        rating = HotelRating(property_name="Breezes Beach Club & Spa", source="Google", score=4.5, scale=5.0,
                             review_count="3.9k", where="Google Hotels hotel page",
                             source_url="https://www.google.com/travel/search?q=SYNTHETIC",
                             observed_at="2026-10-02T15:20:00+00:00")
        ratings = {normalise_property_name("Breezes Beach Club & Spa"): (rating,)}
        html = _html(ratings=ratings)
        part = _slice(html, "trip-AF-01")
        text = visible_text(part)
        self.assertIn("Google 4.5/5", text)
        self.assertIn("3.9k reviews", text)
        self.assertIn("2 Oct", text)
        self.assertIn("https://www.google.com/travel/search?q=SYNTHETIC", part)
        self.assertEqual(text.count("guest rating not collected"), 2,
                         "once a property on the trip is rated, each of the other two says for itself that it is not")
        self.assertNotIn("for any property on this trip", text)

    def test_a_stop_with_no_property_chosen_says_so_and_builds_no_booking_link(self):
        html = _html()
        part = _slice(html, "trip-MC-05")
        text = visible_text(part)
        self.assertIn("no property chosen yet", text)
        self.assertNotIn("booking.com", part)

    def test_properties_whose_nights_are_not_itemised_say_so_and_get_no_dates(self):
        part = visible_text(_slice(_html(), "trip-AF-03"))
        self.assertIn("nights per property not stated", part)

    def test_the_nights_the_date_pair_adds_are_named(self):
        part = visible_text(_slice(_html(), "trip-AF-01"))
        self.assertIn("8 nights", part)
        self.assertIn("not planned or priced", part)

    def test_no_dossier_calls_a_guess_a_price(self):
        for ident in _ids(_html()):
            part = visible_text(_slice(_html(), f"trip-{ident}"))
            self.assertNotIn("SYNTHETIC", part)
            self.assertNotRegex(part, r"\bnan\b|\binf\b|\bNone\b(?! for this trip)")


class LinksOpenWhatTheyNameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fares = _reads()
        cls.rows = {r["trip"].id: r for r in _rows(cls.fares)}
        cls.dossiers = {d["id"]: d for d in _dossiers(cls.fares)}
        cls.html = _html(fares=cls.fares)

    def test_the_flights_link_searches_the_legs_the_dossier_prints_with_the_dates_it_prints(self):
        for ident, row in self.rows.items():
            with self.subTest(trip=ident):
                legs = trip_legs_for_dates(row["trip"], row["outbound"], row["return"])
                self.assertEqual(_tfs_legs(row["url"]), list(legs))
                part = _slice(self.html, f"trip-{ident}")
                self.assertIn(row["url"].replace("&", "&amp;"), part)
                text = visible_text(part)
                for origin, destination, day in legs:
                    self.assertIn(_words(day), text)

    def test_every_hotel_link_carries_exactly_the_check_in_and_check_out_the_dossier_prints(self):
        checked = 0
        for ident, dossier in self.dossiers.items():
            for stay in dossier["stays"]:
                for lodge in stay["lodges"]:
                    for label, url in lodge["links"]:
                        if not any(host in url for host in ("booking.com", "google.com/travel/hotels", "expedia")):
                            continue
                        checked += 1
                        with self.subTest(trip=ident, lodge=lodge["name"], link=label):
                            self.assertTrue(lodge["check_in"] and lodge["check_out"])
                            self.assertEqual(_hotel_link_dates(url), (lodge["check_in"], lodge["check_out"]))
                            self.assertEqual(urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get(
                                "group_adults", urllib.parse.parse_qs(urllib.parse.urlparse(url).query).get(
                                    "adults", ["5"]))[0], "5")
        self.assertGreater(checked, 20, "the shipped trips name enough properties to be worth checking")

    def test_the_dates_a_hotel_link_carries_are_the_dates_printed_beside_that_property(self):
        """Read each property's own block out of the HTML: the dates in its words are the dates in its links."""
        checked = 0
        for ident, dossier in self.dossiers.items():
            part = _slice(self.html, f"trip-{ident}")
            blocks = re.findall(r'<div class="lodge"[^>]*>(.*?)</div>', part, flags=re.S)
            lodges = [lodge for stay in dossier["stays"] for lodge in stay["lodges"]]
            self.assertEqual(len(blocks), len(lodges), ident)
            for block, lodge in zip(blocks, lodges):
                text = visible_text(block)
                self.assertIn(lodge["name"], text)
                if not lodge["check_in"]:
                    self.assertIn("nights per property not stated", text)
                    continue
                self.assertIn(f"{_words(lodge['check_in'])} → {_words(lodge['check_out'])}", text, (ident, lodge["name"]))
                for href in re.findall(r'href="([^"]+)"', block):
                    url = href.replace("&amp;", "&")
                    if any(host in url for host in ("booking.com", "google.com/travel/hotels", "expedia")):
                        checked += 1
                        self.assertEqual(_hotel_link_dates(url), (lodge["check_in"], lodge["check_out"]), (ident, lodge["name"]))
        self.assertGreater(checked, 40)

    def test_a_stop_with_a_property_gets_the_property_name_in_the_search_not_a_town_alone(self):
        for ident, dossier in self.dossiers.items():
            for stay in dossier["stays"]:
                for lodge in stay["lodges"]:
                    for _label, url in lodge["links"]:
                        if "booking.com" in url:
                            ss = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["ss"][0]
                            self.assertTrue(ss.startswith(lodge["name"]), (ident, ss))

    def test_the_search_names_the_property_and_the_area_the_data_gives_and_nothing_else(self):
        """A bare "Zanzibar" would be expanded to Nungwi by the destination table; the data names the right coast."""
        for ident, dossier in self.dossiers.items():
            trip = self.rows[ident]["trip"]
            for stay, stop in zip(dossier["stays"], trip.stops):
                for lodge, spec in zip(stay["lodges"], stop.lodges):
                    for _label, url in lodge["links"]:
                        if "booking.com" in url:
                            ss = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["ss"][0]
                            area = hol.HOLIDAY_SEARCH_QUERIES.get(spec.area.lower(), spec.area)
                            self.assertEqual(ss, f"{spec.name} {area}".strip(), (ident, ss))
                            # a bare key of the destination table expands to ITS town: only ones that mean the
                            # same place as the property are allowed to rely on that.
                            if spec.area.lower() in hol.HOLIDAY_SEARCH_QUERIES:
                                self.assertIn(spec.area, ("Muscat", "Okinawa"), (ident, spec.name))
        kiwengwa = [l for d in self.dossiers.values() for s in d["stays"] for l in s["lodges"]
                    if l["name"] == "Bluebay Beach Resort & Spa"]
        for lodge in kiwengwa:
            for _label, url in lodge["links"]:
                self.assertNotIn("Nungwi", urllib.parse.unquote_plus(url))

    def test_an_operator_trip_links_the_operators_own_page_and_a_self_build_its_rate_pages(self):
        for ident, row in self.rows.items():
            part = _slice(self.html, f"trip-{ident}")
            for url in row["trip"].source_urls:
                self.assertIn(url.replace("&", "&amp;"), part, (ident, url))

    def test_every_link_is_http_and_none_is_a_placeholder(self):
        for url in re.findall(r'href="([^"]+)"', self.html):
            if url.startswith("#"):
                continue
            self.assertRegex(url, r"^https://", url)


class PairsAreVisibleInTheTableTests(unittest.TestCase):
    def test_a_paired_trip_says_so_in_its_table_row_and_an_unpaired_one_does_not(self):
        html = _html(fares=_reads())
        table = visible_text(html[html.index("Every option at a glance"):html.index('id="trips"')])
        rows = {r["trip"].id: r["trip"] for r in _rows()}
        for ident, expected in (("AF-01", "compared with our build"), ("AF-02", "compared with our build"),
                                ("AF-07", "compared with our build"), ("AF-08", "compared with an operator package"),
                                ("AF-09", "compared with an operator package"), ("AF-10", "compared with an operator package")):
            line = table[table.index(rows[ident].title):]
            line = line[:line.index("over") if "over" in line[:300] else 300]
            self.assertIn(expected, line, ident)
        self.assertEqual(table.count("compared with"), 6, "exactly the three pairs, both sides")


class PackageVersusOurBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fares = _reads()
        cls.html = _html(fares=cls.fares)
        cls.rows = {r["trip"].id: r["trip"] for r in _rows(cls.fares)}

    def _block(self, ident):
        part = visible_text(_slice(self.html, f"trip-{ident}"))
        start = part.index("Package vs our build")
        end = part.index("Itinerary")
        return part[start:end]

    def test_a_package_and_our_build_of_the_same_shape_sit_side_by_side_in_both_dossiers(self):
        for ident, other in (("AF-01", "AF-08"), ("AF-08", "AF-01"), ("AF-02", "AF-09"), ("AF-07", "AF-10")):
            block = self._block(ident)
            for trip in (self.rows[ident], self.rows[other]):
                self.assertIn(trip.title, block, (ident, trip.id))
            self.assertIn(f'href="#trip-{other}"', _slice(self.html, f"trip-{ident}"))

    def test_the_pound_difference_is_computed_from_the_two_figures_and_stated(self):
        kuoni, ours = self.rows["AF-01"], self.rows["AF-08"]
        gap = round(ours.cost_low_gbp - kuoni.cost_low_gbp)
        self.assertGreater(gap, 0)
        for ident in ("AF-01", "AF-08"):
            self.assertIn(f"£{gap:,} more", self._block(ident))

    def test_a_cheaper_build_says_less_not_more(self):
        package, ours = self.rows["AF-07"], self.rows["AF-10"]
        gap = round(package.cost_low_gbp - ours.cost_low_gbp)
        self.assertGreater(gap, 0)
        self.assertIn(f"£{gap:,} less", self._block("AF-10"))
        self.assertIn(f"£{gap:,} less", self._block("AF-07"), "the sentence is about the pair, not about whose page it is on")

    def test_both_sides_show_price_nights_and_cost_a_night_so_unequal_lengths_are_visible(self):
        block = self._block("AF-01")
        for trip in (self.rows["AF-01"], self.rows["AF-08"]):
            self.assertIn(f"{trip.total_nights} nights", block)
            self.assertIn(f"£{round(trip.cost_low_gbp / trip.total_nights):,} a night", block)

    def test_the_itemised_lines_of_our_build_are_listed(self):
        block = self._block("AF-08")
        for line in self.rows["AF-08"].cost_lines:
            self.assertIn(f"£{line.gbp:,.0f}", block)

    def test_the_catch_of_each_side_is_kept_in_the_comparison(self):
        block = self._block("AF-01")
        self.assertIn(self.rows["AF-01"].catch, block)
        self.assertIn(self.rows["AF-08"].catch, block)

    def test_trips_with_no_counterpart_say_which_kind_is_missing(self):
        for ident in ("AF-03", "AF-04", "AF-05", "AF-06"):
            self.assertIn("no self-build of this shape yet", visible_text(_slice(self.html, f"trip-{ident}")), ident)
        for ident in ("AF-11", "MC-01", "MC-05", "MC-07"):
            self.assertIn("no equivalent vendor package found yet", visible_text(_slice(self.html, f"trip-{ident}")), ident)

    def test_the_plain_text_carries_the_same_pair(self):
        text = _text(fares=self.fares)
        start = text.index(self.rows["AF-01"].title, text.index("Itinerary") - 3000)
        self.assertIn("Package vs our build", text)
        gap = round(self.rows["AF-08"].cost_low_gbp - self.rows["AF-01"].cost_low_gbp)
        self.assertIn(f"£{gap:,} more", text)
        self.assertTrue(start > 0)


class WellFormedTests(unittest.TestCase):
    """Gmail repairs broken markup its own way, so every level of every page must open and close what it opens."""

    VOID = {"br", "hr", "img", "meta", "input", "link"}

    def _unbalanced(self, html):
        from html.parser import HTMLParser

        problems, stack, void = [], [], self.VOID

        class Parser(HTMLParser):
            def handle_starttag(self, tag, attrs):
                if tag not in void:
                    stack.append(tag)

            def handle_endtag(self, tag):
                if tag in void:
                    return
                if stack and stack[-1] == tag:
                    stack.pop()
                else:
                    problems.append(f"</{tag}> closes {stack[-1] if stack else 'nothing'}")

        Parser().feed(html)
        return problems + [f"<{tag}> never closed" for tag in stack]

    def test_every_level_of_every_page_is_balanced(self):
        from public_flight_search import trip_dossier as td

        for dossier in _dossiers(_reads()):
            for level in (td.FULL, td.TRIMMED, td.SHORT):
                with self.subTest(trip=dossier["id"], level=level):
                    self.assertEqual(self._unbalanced(td.dossier_html(dossier, level)), [])

    def test_the_whole_e_mail_is_balanced_at_a_generous_and_at_a_tight_budget(self):
        for budget in (UNLIMITED, 90_000, 20_000):
            with self.subTest(budget=budget):
                self.assertEqual(self._unbalanced(_html(fares=_reads(), deals=_deals(3), budget=budget)), [])


class SizeAndShorteningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fares = _reads()
        cls.trip_ids = [r["trip"].id for r in _rows(cls.fares)]
        cls.ids_in_order = _ids(_html(fares=cls.fares, deals=_deals(1)))

    def _bytes(self, html):
        return len(html.encode("utf-8"))

    def _levels(self, html):
        """0 full, 1 trimmed, 2 short: read off the one line each shortened page ends with."""
        levels = []
        for ident in _ids(html):
            text = visible_text(_slice(html, f"trip-{ident}"))
            levels.append(2 if "the booking links and the rest are in the plain-text" in text
                          else 1 if "the longest notes are in the plain-text" in text else 0)
        return levels

    def test_the_real_shape_fits_the_budget_with_every_trip_read_and_twelve_cards(self):
        html = _html(fares=self.fares, deals=_deals(12), budget=hol.EMAIL_HTML_BUDGET_BYTES)
        self.assertLessEqual(self._bytes(html), hol.EMAIL_HTML_BUDGET_BYTES)

    def test_every_trip_is_in_the_table_and_has_a_page_whatever_the_budget(self):
        for budget in (110_000, 96_000, 84_000, 78_000):
            with self.subTest(budget=budget):
                html = _html(fares=self.fares, deals=_deals(2), budget=budget)
                self.assertEqual(sorted(_table_ids(html)), sorted(self.trip_ids))
                self.assertEqual(sorted(_ids(html)), sorted(self.trip_ids), "a short dossier is still a dossier page")
                self.assertLessEqual(self._bytes(html), budget)

    def test_a_budget_below_the_floor_still_sends_every_trip_in_its_short_form(self):
        html = _html(fares=self.fares, deals=_deals(2), budget=20_000)
        self.assertEqual(sorted(_table_ids(html)), sorted(self.trip_ids))
        self.assertEqual(self._levels(html), [2] * len(self.trip_ids), "every page is in the short form and says so")

    def test_the_last_trips_are_shortened_first_and_the_first_trips_keep_their_detail(self):
        for budget in (110_000, 96_000, 84_000, 78_000):
            with self.subTest(budget=budget):
                levels = self._levels(_html(fares=self.fares, deals=_deals(2), budget=budget))
                self.assertEqual(levels, sorted(levels), "once a trip is shortened every trip after it is too")
        tight = self._levels(_html(fares=self.fares, deals=_deals(2), budget=84_000))
        self.assertLess(tight[0], tight[-1], "the Tanzania safari + Zanzibar pages lose detail last")
        self.assertEqual(tight[-1], 2)

    def test_the_least_important_detail_goes_first_trimmed_before_short(self):
        """Between full and short there is a trimmed form: the longest prose and the second-choice links go first."""
        html = _html(fares=self.fares, deals=_deals(2), budget=96_000)
        levels = self._levels(html)
        self.assertIn(1, levels, "trimming is tried before any trip is cut to its short form")
        trimmed = _slice(html, f"trip-{_ids(html)[levels.index(1)]}")
        self.assertNotIn("google.com/travel/hotels", trimmed, "the Google Hotels comparison link is a second-choice link")
        self.assertIn("booking.com", trimmed, "the Booking.com search for the property and dates stays")
        full = _slice(_html(fares=self.fares, deals=_deals(1), budget=400_000), f"trip-{self.ids_in_order[0]}")
        self.assertIn("google.com/travel/hotels", full)

    def test_the_line_over_the_trips_says_what_was_shortened(self):
        text = visible_text(_html(fares=self.fares, deals=_deals(2), budget=84_000))
        self.assertRegex(text, r"Shortened to fit Gmail's size limit: \d+ (trips? trimmed|in short form)")
        self.assertIn("plain-text", text)
        self.assertIn("still in the table", text)
        self.assertIn("the last trips listed are the shortest", text)

    def test_a_short_dossier_keeps_the_dates_the_properties_the_price_the_flights_status_and_the_links(self):
        html = _html(fares=self.fares, deals=_deals(2), budget=20_000)
        for row in _rows(self.fares):
            trip = row["trip"]
            part = _slice(html, f"trip-{trip.id}")
            text = visible_text(part)
            self.assertRegex(text, r"£[\d,]+", trip.id)
            self.assertIn("Flights", text)
            self.assertIn("https://", part, trip.id)
            plan = trip_stays_for_dates(trip, row["outbound"], row["return"])
            for stay in plan.stays:
                self.assertIn(f"{_words(stay.check_in)} → {_words(stay.check_out)}", text, trip.id)
                for lodge in stay.lodges:
                    self.assertIn(lodge.lodge.name, text, trip.id)
            self.assertIn("not captured", text)
            self.assertIn(trip.why, text)
            self.assertIn(trip.catch, text)
            self.assertTrue("no equivalent vendor package found yet" in text
                            or "no self-build of this shape yet" in text or "Package vs our build" in text)

    def test_when_nothing_needs_shortening_nothing_is_said_to_be_shortened(self):
        html = _html(fares=self.fares, deals=_deals(1), budget=400_000)
        self.assertNotIn("Shortened to fit", visible_text(html))
        self.assertEqual(self._levels(html), [0] * len(self.trip_ids))

    def test_the_plain_text_keeps_every_dossier_in_full_whatever_the_html_did(self):
        with patch.object(hol, "EMAIL_HTML_BUDGET_BYTES", 40_000):
            text = _text(fares=self.fares, deals=_deals(4))
        self.assertNotIn("Shortened to fit", text)
        for row in _rows(self.fares):
            trip = row["trip"]
            self.assertIn(trip.title, text)
            for stop in trip.stops:
                for lodge in stop.lodges:
                    self.assertIn(lodge.name, text, (trip.id, lodge.name))
        self.assertEqual(text.count("Itinerary"), len(self.trip_ids))
        self.assertGreaterEqual(text.count("Booking.com: https://"), 20)


class ResortCardTests(unittest.TestCase):
    def test_a_card_says_when_no_vendor_package_was_read_for_its_dates(self):
        part = visible_text(_html(deals=_deals(2))[_html(deals=_deals(2)).index('id="deal-1"'):])
        self.assertIn("no vendor package read for these dates", part)

    def test_a_card_with_a_package_shows_it_beside_the_flights_and_stay_with_the_gap_in_pounds(self):
        from public_flight_search.holidays import OperatorPackage
        from test_holiday_email_compact import _deal, _long_haul_options

        package = OperatorPackage(
            operator="Example Holidays", operator_key="example", total_gbp=5800.0, board="BB", rooms=2,
            link_kind="deep-link", source_url="https://www.example.com/package?x=1",
            observed_at="2026-10-20T10:00:00+00:00", provenance="SYNTHETIC", how="", vs_engine_gbp=241.5,
            outbound_date="2027-07-05", return_date="2027-07-17")
        deal = _deal(0, operator_package=package, flight_options=_long_haul_options())
        html = _html(deals=[deal])
        card = visible_text(html[html.index('id="deal-1"'):])
        self.assertIn("Package vs our build", card)
        self.assertIn("Example Holidays", card)
        self.assertIn("£5,800", card)
        self.assertIn("£242 less", card, "241.50 prints as the whole pound the card's own money format gives")
        self.assertIn("flights", card)

    def test_a_card_shows_the_ratings_its_deal_holds_and_the_notes_no_longer_say_unchecked(self):
        from test_holiday_email_compact import _deal

        rating = HotelRating(property_name="Test Resort 0", source="Google", score=4.4, scale=5.0,
                             review_count="789", where="Google Hotels hotel page",
                             source_url="https://www.google.com/travel/search?q=SYNTHETIC-TR0",
                             observed_at="2026-10-02T15:20:00+00:00")
        html = _html(deals=[_deal(0, hotel_ratings=(rating,))])
        card = visible_text(html[html.index('id="deal-1"'):])
        self.assertIn("Google 4.4/5", card)
        self.assertIn("789 reviews", card)
        self.assertNotIn("guest rating not collected", card)

    def test_a_card_never_shows_two_answers_about_the_stops_of_the_fare_that_priced_it(self):
        # 22 Oct 2026: the Economy row used to name the catalogue's routing ("1-Stop via Addis Ababa") beside a read of
        # two stops, and a note under it said the two disagreed. The row now takes the read's own stops (see
        # test_economy_row_route.py), so there is nothing to disagree and no note: the row and the read line agree.
        from test_holiday_email_compact import _deal, _long_haul_options

        deal = _deal(0, flight_options=_long_haul_options(route="2-Stop (Ethiopian)") [:1]
                     + (dict(_long_haul_options()[1], route="2-Stop (Ethiopian)"),),
                     routing="1 stop via Addis Ababa", live_carrier="Ethiopian",
                     live_observed_at="2026-10-04T17:09:15+00:00", live_stops=2, live_duration_minutes=1025)
        html = _html(deals=[deal])
        card = visible_text(html[html.index('id="deal-1"'):])
        self.assertIn("2-Stop (Ethiopian)", card)
        self.assertIn("Ethiopian · 2 stops", card)
        self.assertNotIn("names the usual routing", card)

    def test_a_card_with_no_rating_says_not_collected_in_the_card_itself(self):
        from test_holiday_email_compact import _deal

        html = _html(deals=[_deal(0)])
        card = visible_text(html[html.index('id="deal-1"'):])
        self.assertIn("guest rating not collected", card)

    def test_a_card_whose_read_carries_times_shows_them_and_one_that_does_not_says_so_once(self):
        from test_holiday_email_compact import _deal

        timed = _deal(0, live_carrier="Test Air", live_observed_at="2026-10-20T10:00:00+00:00", live_stops=1,
                      live_layover="2h10 DOH", live_duration_minutes=930,
                      live_departure_local="2027-07-05T14:15:00", live_arrival_local="2027-07-06T06:45:00")
        html = _html(deals=[timed])
        card = visible_text(html[html.index('id="deal-1"'):])
        self.assertIn("14:15", card)
        self.assertIn("06:45", card)
        self.assertIn("outbound", card.lower())
        plain = visible_text(_html(deals=[_deal(0)])[_html(deals=[_deal(0)]).index('id="deal-1"'):])
        self.assertEqual(plain.count("times not captured"), 1)


if __name__ == "__main__":
    unittest.main()
