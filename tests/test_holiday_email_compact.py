"""The compact holiday e-mail (owner brief 2026-10-04, BRIEF-H1 Part 2).

Everything the redesign promises is pinned here, from synthetic fixtures only:

* ONE price per card — the door-to-door total for the party — and the
  breakdown line under it adds up to that headline exactly (AMEND-H1 §1).
* Movement is against the LAST observation: cheaper / dearer / no change /
  first time tracked, never a benchmark (AMEND-H1 §2).
* One at-a-glance table, one row per deal, with the one key line under it.
* A long-haul card has exactly three flight rows; an unpriced stopover says
  "price on request" and links the itinerary rather than printing a stale
  number (owner note of 2026-10-04).
* The critic's own complaints cannot come back: no ISO timestamp, no "Direct",
  no benchmark percentage, no collapsible <details>, no workflow or script
  name, and 12 deals still fit under 1,500 words.
* ``HOLIDAY_REPORT_STYLE=detailed`` still produces the previous renderer's
  e-mail, and the plain-text part mirrors the HTML.
"""

from __future__ import annotations

from email import message_from_string
from html import unescape
import os
from pathlib import Path
import re
import unittest
from unittest.mock import patch

from public_flight_search import holidays as hol
from public_flight_search.holiday_email import (
    breakdown_parts,
    departure_range_words,
    freshness_tag,
    nights_words,
    link_row,
    movement_words,
    render_holiday_report_compact,
    render_holiday_report_compact_text,
)
from public_flight_search.holidays import (
    PackageDeal,
    load_holiday_config,
    render_holiday_report,
)

ROOT = Path(__file__).parents[1]
DEC = ROOT / "examples" / "dec_holiday_config.json"
JULY = ROOT / "examples" / "july_holiday_config.json"

GENERATED_AT = "2026-10-04T09:30:00+00:00"
LAST_REPORT_AT = "2026-10-01T06:00:00+00:00"

_TAG_RE = re.compile(r"<[^>]+>")

#: Names a reader must never be shown: they are how this job is built, not
#: what the holiday costs.
_SCRIPT_NAMES = (
    "holiday-planner",
    "july-holiday-planner",
    "run_holiday_planner",
    "HOLIDAY_HISTORY_PATH",
    "workflow",
    "public_flight_search",
    "HOLIDAY_SEARCH_CONFIG_JSON",
    "HOLIDAY_REPORT_STYLE",
    ".yml",
    ".py",
    "github",
    "Actions",
)


def visible_text(html: str) -> str:
    """What the reader sees: tags and attributes gone, entities resolved."""
    return unescape(_TAG_RE.sub(" ", html))


def word_count(html: str) -> int:
    return len(visible_text(html).split())


def _deal(index: int = 0, **overrides) -> PackageDeal:
    """A synthetic long-haul deal: 5 travellers, 8 nights, one booking."""
    base = dict(
        resort_name=f"Test Resort {index}",
        destination_label="Kuta Mandalika, Lombok",
        destination_key="lombok",
        star_rating=5,
        board_basis="Bed & Breakfast",
        outbound_date="2027-07-05",
        return_date="2027-07-17",
        nights=12,
        airline="Test Air",
        origin="LHR",
        origin_airports=("LHR",),
        destination_airport="LOP",
        flight_price_total_gbp=2400.0,
        hotel_price_total_gbp=3600.0,
        total_package_price_gbp=6000.0,
        price_per_person_gbp=1200.0,
        uk_ground_gbp=16.5,
        transfer_gbp=25.0,
        true_d2d_gbp=6041.5,
        flight_booking_url="https://www.google.com/travel/flights/search?tfs=abc",
        hotel_booking_url="https://example.invalid/hotel",
        booking_deep_url="https://www.booking.com/searchresults.html?ss=Test",
        compare_url="https://www.google.com/travel/hotels?q=Test",
        is_under_budget=True,
        unit_architecture="Two-bedroom pool villa",
        rooms_in_unit=1,
        dec_ambient_c=(28, 31),
        sea_temp_c=28,
        beach="walkable beach on site",
        highlights=("Plunge pool",),
    )
    base.update(overrides)
    return PackageDeal(**base)


def _option(kind: str, cabin: str, flight: float, stay: float, **extra) -> dict:
    row = {
        "kind": kind,
        "cabin": cabin,
        "flight_cost": flight,
        "hotel_cost": stay,
        "total_pkg": flight + stay,
        "true_d2d": flight + stay + 41.5,
        "within_budget": True,
    }
    row.update(extra)
    return row


def _long_haul_options(**extra) -> tuple:
    return (
        _option("business", "BUSINESS", 2400.0, 3600.0, **extra),
        _option("economy", "ECONOMY", 900.0, 3600.0),
    )


def _stopover(hub: str = "DOH", label: str = "Doha", flight: float = 2900.0) -> dict:
    return _option(
        "stopover",
        "ECONOMY",
        flight,
        3600.0,
        hub=hub,
        hub_label=label,
        hub_hotel="Rixos Gulf Hotel Doha",
        hub_board="Bed & Breakfast",
        stopover_hotel_cost=1356.98,
        stopover_nights=4,
        outbound="2027-07-05",
        returning="2027-07-17",
        origin="LHR",
        source_url="https://www.google.com/travel/flights/search?tfs=multi",
    )


def _config(**overrides):
    config = load_holiday_config(JULY.read_text(encoding="utf-8"))
    for key, value in overrides.items():
        object.__setattr__(config, key, value)
    return config


def _deals(count: int = 12, **overrides):
    return [
        _deal(index, total_package_price_gbp=4000.0 + 250.0 * index, **overrides)
        for index in range(count)
    ]


def _render(deals=None, *, config=None, **kwargs) -> str:
    return render_holiday_report_compact(
        config or _config(),
        generated_at=GENERATED_AT,
        deals=_deals() if deals is None else deals,
        **kwargs,
    )


class HeaderTests(unittest.TestCase):
    def test_the_header_states_the_departure_range_and_the_nights(self):
        text = visible_text(_render())
        self.assertIn("5 travellers", text)
        self.assertIn("one booking", text)
        # DERIVED from the config, never pasted. The header's whole job is to
        # state the window this config prices, and the owner's window moved on
        # 2026-10-04 (depart 25-30 June 2027), so a header test that quotes the
        # dates breaks on every window change without testing anything new. It
        # is asserted against the shared helper the header itself calls.
        config = _config()
        self.assertIn(
            f"departing {departure_range_words(config, generated_at=GENERATED_AT)}",
            text,
        )
        self.assertIn(nights_words(config), text)

    def test_december_states_its_own_window_not_july_s(self):
        text = visible_text(_render(config=load_holiday_config(DEC.read_text(encoding="utf-8"))))
        self.assertIn("departing 17–23 Dec", text)
        self.assertIn("8 nights", text)

    def test_the_window_is_derived_from_the_config_never_hard_coded(self):
        config = _config(outbound_dates=("2027-07-08", "2027-07-09", "2027-07-10"))
        text = visible_text(_render(config=config))
        self.assertIn("departing 8–10 Jul", text)

    def test_prices_checked_is_plain_words_not_an_iso_stamp(self):
        html = _render()
        text = visible_text(html)
        self.assertIn("Prices checked Sun 4 Oct", text)
        self.assertNotIn("2026-10-04", text)
        self.assertNotIn("T09:30", html)

    def test_no_iso_date_reaches_the_header(self):
        header = _render()[:4000]
        self.assertNotRegex(header, r"\d{4}-\d{2}-\d{2}")


class AtAGlanceTableTests(unittest.TestCase):
    def test_one_row_per_deal_carrying_the_total_for_five(self):
        deals = _deals(12)
        html = _render(deals)
        for deal in deals:
            self.assertIn(deal.resort_name, html)
        # One anchor per card, and the table links to each of them.
        for index in range(1, 13):
            self.assertIn(f'href="#deal-{index}"', html)
        self.assertIn("Total for 5", html)

    def test_the_table_states_the_key_line_once(self):
        text = visible_text(_render())
        self.assertIn("Every price is the total for 5, door to door.", text)

    def test_the_key_line_carries_the_party_size_from_the_config(self):
        text = visible_text(_render(config=_config(travellers=4)))
        self.assertIn("Every price is the total for 4, door to door.", text)

    def test_the_table_has_no_price_change_column(self):
        """Owner 2026-10-08: price changes are not worth the space.

        The sixth "vs last time" column held "first time tracked" or "£210
        cheaper" on every row, and on a phone it wrapped every row to two
        lines. Five columns: resort, where, dates, board, total. The plain-text
        glance list drops the same field.
        """
        trend = {"resort_name": "Test Resort 0", "current": 4000.0,
                 "prior_last": 4210.0, "prior_observations": 3}
        deals = _deals(2)
        html = _render(deals=deals, trends=[trend], last_report_at=LAST_REPORT_AT)
        self.assertNotIn("vs last time", html)
        header_start = html.rindex("<tr>", 0, html.index(">Resort</td>"))
        header = html[header_start:html.index("</tr>", header_start)]
        self.assertEqual(header.count("<td"), 5)
        first_row_start = html.index("<tr>", header_start + 1)
        first_row = html[first_row_start:html.index("</tr>", first_row_start)]
        self.assertEqual(first_row.count("<td"), 5)
        text = render_holiday_report_compact_text(
            _config(), generated_at=GENERATED_AT, deals=deals,
            trends=[trend], last_report_at=LAST_REPORT_AT,
        )
        glance = [line for line in text.splitlines() if re.match(r"  \d+\. ", line)]
        self.assertEqual(len(glance), 2)
        for line in glance:
            self.assertTrue(line.endswith("£6,042"), line)

    def test_rows_are_ordered_by_the_total_the_table_shows(self):
        """The table sorts by the door-to-door total it displays, not the package-only price.

        The 7 Oct 2026 December e-mail showed Seaside Palm Beach (£3,002) above
        Annabelle Hotel (£2,974): both sort keys were the package-only price
        (2,933 vs 2,940), while the displayed headline adds transfers and UK
        ground. A table headed 'Total for 5' must read cheapest-first on that
        total, and the cards below it must follow the same order.
        """
        # Same package order as ever, but the displayed totals cross over:
        # package 2,933 + transfers 69 = 3,002; package 2,940 + transfers 34 = 2,974.
        deals = [
            _deal(0, resort_name="Cheaper Package Dearer Door",
                  total_package_price_gbp=2933.0, true_d2d_gbp=3002.0),
            _deal(1, resort_name="Dearer Package Cheaper Door",
                  total_package_price_gbp=2940.0, true_d2d_gbp=2974.0),
        ]
        text = visible_text(_render(deals=deals))
        self.assertLess(
            text.index("Dearer Package Cheaper Door"),
            text.index("Cheaper Package Dearer Door"),
        )


class OnePricePerCardTests(unittest.TestCase):
    def test_the_headline_is_the_door_to_door_total_not_the_package_total(self):
        html = _render()
        self.assertIn("£6,042", html)
        self.assertIn("total for 5, door to door", html)

    def test_the_breakdown_parts_sum_to_the_headline(self):
        for deal in _deals(4):
            parts, total = breakdown_parts(deal)
            self.assertAlmostEqual(sum(amount for _, amount in parts), total, places=2)
            self.assertEqual(
                [label for label, _ in parts], ["flights", "stay", "transfers"]
            )

    def test_the_breakdown_line_prints_the_sum_it_claims(self):
        # The cabin is named on the flight part (REVIEW-H3 P1): the headline IS
        # that flight, and nothing else on a short-haul card says which cabin.
        text = visible_text(_render())
        self.assertIn(
            "flights £2,400 (economy) + stay £3,600 + transfers £42 = £6,042", text
        )

    def test_the_cabin_is_named_on_the_flight_part_for_every_cabin(self):
        for cabin, word in (
            ("ECONOMY", "economy"),
            ("PREMIUM_ECONOMY", "premium economy"),
            ("BUSINESS", "business"),
            ("FIRST", "first"),
        ):
            with self.subTest(cabin=cabin):
                text = visible_text(_render(deals=[_deal(cabin_class=cabin)]))
                self.assertIn(f"flights £2,400 ({word}) +", text)

    def test_the_package_only_figure_is_never_printed_as_a_price(self):
        html = _render()
        # £6,000 is the package total: it appears only inside the sum, never as
        # a total of its own.
        self.assertNotRegex(html, r">£6,000<")

    def test_per_person_appears_once_per_card_in_body_type(self):
        text = visible_text(_render(deals=_deals(1)))
        self.assertEqual(text.count("about £1,208 each"), 1)
        self.assertIsNone(re.search(r"\bpp\b", text))

    def test_a_hand_built_deal_whose_parts_do_not_add_up_names_the_gap(self):
        deal = _deal(true_d2d_gbp=6100.0)
        html = _render(deals=[deal])
        self.assertIn("other £", visible_text(html))
        parts, total = breakdown_parts(deal)
        self.assertEqual(parts[-1][0], "other")
        self.assertAlmostEqual(sum(amount for _, amount in parts), total, places=2)


class PrintedBreakdownArithmeticTests(unittest.TestCase):
    """The line's pounds must add up ON THE PAGE (REVIEW-H3 P0).

    ``test_the_breakdown_parts_sum_to_the_headline`` asserts the invariant on
    the FLOATS, which is a true statement about a representation nobody reads.
    The line prints whole pounds, each rounded on its own, and two shipped
    cards printed a headline a pound away from the sum of their own parts -
    which is why the invariant held in the suite and failed in the e-mail.

    So these parse the printed ``£N`` figures back out of the rendered HTML and
    out of the text part, over several deals whose parts deliberately carry
    pence, and add them up as a reader would.
    """

    #: ``flights £N + stay £N (+ transfers £N | other £N) = £N``, with the
    #: cabin word the P1 added between the fare and the ``+``.
    _LINE = re.compile(
        r"flights £([\d,]+)(?: \([a-z ]+\))?"
        r" \+ stay £([\d,]+)"
        r"(?: \+ (?:transfers|other|transfers \+ other) £([\d,]+))?"
        r" = £([\d,]+)"
    )

    #: Parts with pence, so independent rounding is actually exercised. The
    #: first two reproduce the two cards REVIEW-H3 measured as a pound out.
    _ODD_PARTS = (
        (623.4, 2399.6, 74.3),
        (13372.4, 6099.2, 16.5),
        (2400.0, 3600.0, 41.5),
        (845.5, 1290.5, 62.4),
        (4199.5, 2799.5, 39.5),
        (710.6, 1544.4, 55.6),
    )

    def _deals_with_pence(self):
        deals = []
        for index, (flight, stay, ground) in enumerate(self._ODD_PARTS):
            deals.append(
                _deal(
                    index,
                    flight_price_total_gbp=flight,
                    hotel_price_total_gbp=stay,
                    uk_ground_gbp=ground - 25.0,
                    transfer_gbp=25.0,
                    total_package_price_gbp=round(flight + stay, 2),
                    true_d2d_gbp=round(flight + stay + ground, 2),
                    cabin_class=("BUSINESS", "ECONOMY", "PREMIUM_ECONOMY")[index % 3],
                )
            )
        return deals

    @staticmethod
    def _pounds(figure: str) -> int:
        return int(figure.replace(",", ""))

    def _assert_lines_add_up(self, text: str, expected_cards: int):
        lines = self._LINE.findall(text)
        self.assertEqual(
            len(lines), expected_cards,
            f"expected one breakdown line per card, parsed {lines}",
        )
        for parts in lines:
            shown = [self._pounds(part) for part in parts[:3] if part]
            total = self._pounds(parts[3])
            self.assertEqual(
                sum(shown), total,
                f"printed parts {shown} do not add up to the printed headline "
                f"£{total:,}",
            )

    def test_the_printed_html_parts_add_up_to_the_printed_headline(self):
        deals = self._deals_with_pence()
        self._assert_lines_add_up(visible_text(_render(deals=deals)), len(deals))

    def test_the_printed_text_parts_add_up_to_the_printed_headline(self):
        deals = self._deals_with_pence()
        text = render_holiday_report_compact_text(
            _config(), generated_at=GENERATED_AT, deals=deals
        )
        self._assert_lines_add_up(text, len(deals))

    def test_html_and_text_print_the_same_breakdown_for_every_card(self):
        deals = self._deals_with_pence()
        html_lines = self._LINE.findall(visible_text(_render(deals=deals)))
        text_lines = self._LINE.findall(
            render_holiday_report_compact_text(
                _config(), generated_at=GENERATED_AT, deals=deals
            )
        )
        self.assertEqual(html_lines, text_lines)

    def test_a_card_with_no_fare_printed_still_balances(self):
        # A zero fare is not printed at all (``breakdown_parts`` keeps only
        # positive parts), so the line is ``stay + transfers = total`` - and
        # the residual then lands on transfers, the only part left to carry it.
        deal = _deal(
            flight_price_total_gbp=0.0,
            hotel_price_total_gbp=2399.6,
            uk_ground_gbp=16.4,
            transfer_gbp=57.9,
            total_package_price_gbp=2399.6,
            true_d2d_gbp=2473.9,
        )
        text = visible_text(_render(deals=[deal]))
        self.assertNotIn("flights £", text)
        stay, transfers, total = re.search(
            r"stay £([\d,]+) \+ transfers £([\d,]+) = £([\d,]+)", text
        ).groups()
        self.assertEqual(self._pounds(stay) + self._pounds(transfers), self._pounds(total))

    def test_a_deal_whose_parts_overshoot_its_headline_still_balances(self):
        # A negative figure is never printed: the shortfall becomes its own
        # part, and the printed integers still add up.
        deal = _deal(
            flight_price_total_gbp=60.4,
            hotel_price_total_gbp=40.4,
            uk_ground_gbp=0.4,
            transfer_gbp=0.0,
            total_package_price_gbp=100.8,
            true_d2d_gbp=100.4,
        )
        text = visible_text(_render(deals=[deal]))
        self._assert_lines_add_up(text, 1)
        self.assertNotRegex(text, r"£-")


class MovementTests(unittest.TestCase):
    def _trend(self, **overrides) -> dict:
        row = {
            "resort_name": "Test Resort 0",
            "current": 4000.0,
            "prior_last": 4210.0,
            "prior_observations": 3,
        }
        row.update(overrides)
        return row

    def test_cheaper_than_the_last_report(self):
        words = movement_words(self._trend(), last_report_at=LAST_REPORT_AT)
        self.assertEqual(words, "£210 cheaper than 1 Oct")

    def test_dearer_than_the_last_report(self):
        words = movement_words(self._trend(prior_last=3905.0), last_report_at=LAST_REPORT_AT)
        self.assertEqual(words, "£95 dearer than 1 Oct")

    def test_no_change_since_the_last_report(self):
        words = movement_words(self._trend(prior_last=4000.0), last_report_at=LAST_REPORT_AT)
        self.assertEqual(words, "no change since 1 Oct")

    def test_first_time_tracked_without_history(self):
        self.assertEqual(movement_words(None), "first time tracked")
        self.assertEqual(
            movement_words(self._trend(prior_last=None)), "first time tracked"
        )

    def test_the_card_states_the_movement_and_the_table_summarises_it(self):
        # Same wording, same number: the card keeps the date, the one-line
        # table column drops the redundant "than 1 Oct".
        html = _render(trends=[self._trend()], last_report_at=LAST_REPORT_AT)
        text = visible_text(html)
        self.assertIn("£210 cheaper than 1 Oct", text)
        self.assertIn("£210 cheaper", text)
        self.assertEqual(text.count("£210 cheaper than 1 Oct"), 1)

    def test_no_benchmark_movement_anywhere_in_the_email(self):
        html = _render(
            trends=[self._trend()],
            digest={
                "has_prior": True,
                "drops": [{"name": "Test Resort 1", "current": 1.0, "prev": 2.0, "delta": -10.0}],
                "rises": [],
                "new": [],
                "last_report_at": LAST_REPORT_AT,
            },
            last_report_at=LAST_REPORT_AT,
        )
        text = visible_text(html).lower()
        for banned in ("benchmark estimate", "below our estimate", "summer peak",
                       "value score", "vs peak", "%"):
            self.assertNotIn(banned, text, banned)


class FreshnessTests(unittest.TestCase):
    def test_a_live_fare_read_yesterday(self):
        # A read for THESE dates is the only stay that may sit under "Live
        # price" (BRIEF-H17 §6): the word claims the whole price was checked.
        deal = _deal(confidence="verified-exact-date",
                     hotel_rate_basis="exact-date-rate",
                     live_observed_at="2026-10-03T09:00:00+00:00")
        self.assertEqual(
            freshness_tag(deal, generated_at=GENERATED_AT), ("Live price · checked yesterday", "green")
        )

    def test_a_live_fare_older_than_the_threshold_stops_claiming_live(self):
        # The loader may have called it live; at render time it has aged past
        # live_verify.EVIDENCE_MAX_AGE_HOURS, so the card says "Seen", never
        # "Live price".
        deal = _deal(confidence="verified-exact-date",
                     hotel_rate_basis="exact-date-rate",
                     live_observed_at="2026-09-29T09:00:00+00:00")
        self.assertEqual(
            freshness_tag(deal, generated_at=GENERATED_AT), ("Seen 5 days ago", "amber")
        )

    def test_a_stale_observation_says_seen_not_estimate(self):
        deal = _deal(confidence="stale-cache", live_observed_at="2026-09-29T09:00:00+00:00")
        self.assertEqual(
            freshness_tag(deal, generated_at=GENERATED_AT), ("Seen 5 days ago", "amber")
        )

    def test_a_benchmark_says_estimate_no_live_price(self):
        self.assertEqual(
            freshness_tag(_deal(), generated_at=GENERATED_AT),
            ("Estimate — no live price", "amber"),
        )

    def test_a_live_fare_beside_an_estimated_stay_is_not_a_live_price(self):
        deal = _deal(confidence="verified-exact-date", hotel_rate_basis="estimate",
                     live_observed_at="2026-10-03T09:00:00+00:00")
        self.assertEqual(freshness_tag(deal, generated_at=GENERATED_AT),
                         ("Flights live · stay estimated", "green"))

    def test_a_live_fare_beside_the_catalogue_stay_is_not_a_live_price(self):
        # BRIEF-H17 §6, and the case six December cards hit: the chip said "Live
        # price · checked today" on the line above "so the stay here is the
        # catalogue's estimate". The tag may not claim the price was checked
        # when one of its two legs is the catalogue's own nightly.
        deal = _deal(confidence="verified-exact-date",
                     hotel_rate_basis="market-supported",
                     live_observed_at="2026-10-03T09:00:00+00:00")
        self.assertEqual(freshness_tag(deal, generated_at=GENERATED_AT),
                         ("Flights live · stay estimated", "green"))

    def test_a_live_fare_beside_a_read_for_another_pair_says_which_estimate(self):
        deal = _deal(confidence="verified-exact-date",
                     hotel_rate_basis="read-rate-estimate",
                     live_observed_at="2026-10-03T09:00:00+00:00")
        self.assertEqual(freshness_tag(deal, generated_at=GENERATED_AT),
                         ("Flights live · stay from a read rate", "green"))

    def test_no_live_card_may_say_live_price(self):
        # Whatever the stay's basis, the word "Live price" requires a live fare.
        for basis in ("", "estimate", "market-supported", "read-rate-estimate",
                      "exact-date-rate", "operator package"):
            with self.subTest(basis=basis or "(none)"):
                tag, _colour = freshness_tag(
                    _deal(hotel_rate_basis=basis), generated_at=GENERATED_AT)
                self.assertNotIn("Live price", tag)

    def test_the_tag_is_two_or_three_words_of_plain_english(self):
        text = visible_text(_render())
        for banned in ("LIVE VERIFIED", "OBSERVED, NOT LIVE", "BENCHMARK PRICE",
                       "D2D", "verified-exact-date", "stale-cache"):
            self.assertNotIn(banned, text, banned)


class FlightRowTests(unittest.TestCase):
    def test_a_long_haul_card_has_exactly_three_option_rows(self):
        html = _render(deals=[_deal(flight_options=_long_haul_options())])
        self.assertEqual(html.count("2 nights each way"), 1)
        for cabin in ("Business", "Economy"):
            self.assertIn(cabin, html)

    def test_a_short_haul_card_has_no_flight_table(self):
        html = _render(deals=[_deal(flight_options=())])
        self.assertNotIn("2 nights each way", html)

    def test_the_route_is_nonstop_and_never_the_word_direct(self):
        html = _render(deals=[_deal(flight_options=_long_haul_options())])
        self.assertIn("Nonstop LHR–LOP", html)
        self.assertIsNone(re.search(r"\bdirect\b", visible_text(html), re.IGNORECASE))

    def test_a_one_stop_route_is_named_in_words(self):
        deal = _deal(flight_options=_long_haul_options(),
                     routing="no London nonstop: 1 stop via Singapore (BA + Scoot)")
        html = _render(deals=[deal])
        self.assertIn("1-Stop via Singapore", html)
        self.assertNotIn("1 stop via Singapore", html)

    def test_each_row_is_a_total_for_the_party_not_a_flight_figure(self):
        html = _render(deals=[_deal(flight_options=_long_haul_options())])
        self.assertIn("£6,042", html)
        self.assertIn("£4,542", html)

    def test_a_priced_stopover_shows_its_total(self):
        deal = _deal(flight_options=_long_haul_options() + (_stopover(),))
        html = _render(deals=[deal])
        self.assertIn("1-Stop via Doha, 2 nights each way", html)
        self.assertNotIn("price on request", html)

    def test_an_unpriced_stopover_says_price_on_request_and_links_the_itinerary(self):
        html = _render(deals=[_deal(flight_options=_long_haul_options())])
        self.assertIn("price on request", html)
        self.assertIn("travel/flights/search", html)

    def test_no_card_prints_a_stale_stopover_number(self):
        # The committed multi-city reads are for the old dates, so the stopover
        # option is absent from the options tuple: the row must offer the
        # itinerary, not reuse a fare read for a different holiday.
        html = _render(deals=[_deal(flight_options=_long_haul_options())])
        self.assertNotIn("multi-city fare read", html)


class BoardTests(unittest.TestCase):
    def test_the_priced_basis_leads_and_per_person_follows(self):
        text = visible_text(_render(deals=[_deal(board_basis="All Inclusive")]))
        # "about", because round(total / 5) does not multiply back to the
        # total on any total that is not a multiple of five (REVIEW-H6 P1).
        self.assertIn("All Inclusive · about £1,208 each", text)

    def test_the_per_head_share_is_never_printed_as_exact(self):
        # The line is an equality claim the layout invites the reader to check:
        # total above, share below. GBP 6,042 / 5 = 1,208.4, so GBP 1,208 x 5
        # is GBP 6,040 - two pounds out. "about" is the honest word for it, and
        # the only alternative (five different per-head figures on one line) is
        # worse to read than a rounded share marked as rounded.
        text = visible_text(_render(deals=[_deal()]))
        self.assertIn("about £1,208 each", text)
        self.assertNotRegex(text, r"(?<!about )£1,208 each")

    def test_a_total_that_divides_exactly_is_still_marked_about(self):
        # 6,040 / 5 = 1,208 exactly. The word does not appear and disappear
        # depending on the arithmetic: "about" describes the figure, not the
        # rounding, so a reader is not left wondering why this card differs.
        deal = _deal(true_d2d_gbp=6040.0, total_package_price_gbp=5998.5)
        text = visible_text(_render(deals=[deal]))
        self.assertIn("about £1,208 each", text)

    def test_island_board_options_are_each_priced_for_the_party(self):
        deal = _deal(
            board_basis="Bed & Breakfast",
            board_options=(
                {"basis": "BB", "label": "Bed & Breakfast", "hotel_cost": 3600.0},
                {"basis": "HB", "label": "Half Board", "hotel_cost": 4200.0},
                {"basis": "AI", "label": "All Inclusive", "hotel_cost": 5400.0},
            ),
        )
        text = visible_text(_render(deals=[deal]))
        self.assertIn("Bed & Breakfast · about £1,208 each", text)
        self.assertIn("Half Board £6,642", text)
        self.assertIn("All Inclusive £7,842", text)
        self.assertIn("(each for 5)", text)

    def test_board_words_never_board_codes(self):
        html = _render(deals=[_deal(board_basis="Half Board")])
        text = visible_text(html)
        self.assertIn("Half Board", text)
        self.assertNotRegex(html, r">\s*(AI|HB|FB|BB)\s*<")


class WarningTests(unittest.TestCase):
    def test_a_monsoon_resort_is_warned_about_in_words(self):
        deal = _deal(outbound_date="2027-07-05", monsoon_months=(7,))
        text = visible_text(_render(deals=[deal]))
        self.assertIn("Monsoon in Jul", text)

    def test_at_most_two_warnings_per_card(self):
        deal = _deal(
            board_basis="board unverified",
            hotel_rate_basis="estimate",
            atol_protected=False,
            monsoon_months=(7,),
        )
        text = visible_text(_render(deals=[deal]))
        self.assertLessEqual(text.count("⚠"), 2)


class CompactnessTests(unittest.TestCase):
    def test_twelve_deals_stay_under_the_word_cap(self):
        # 1,800, raised from 1,500 on 2026-10-04 (H9). The Two-centre section
        # the owner asked for is about 300 words of REQUIRED content — five
        # itineraries, each a title, a cost range, a budget verdict, one line of
        # why and one of catch — and it is not decoration that can be cut to
        # hit a number. What the cap still does is bound the whole e-mail: a
        # report that grows past it is a report nobody reads on a phone.
        html = _render(deals=_deals(12))
        self.assertLess(word_count(html), 1800)

    def test_the_dropped_sections_cannot_come_back(self):
        text = visible_text(_render(deals=_deals(12)))
        for dropped in (
            "value score",
            "Food reviews",
            "Package operators",
            "Self-create",
            "Prices last checked",
            "ATOL",
            "Door-to-Door Transparency",
            "All-Inclusive Economics",
            "Details",
        ):
            self.assertNotIn(dropped, text, dropped)

    def test_no_collapsible_details_survive_a_stripping_client(self):
        html = _render(deals=_deals(12))
        self.assertNotIn("<details", html.lower())

    def test_no_workflow_or_script_name_reaches_the_reader(self):
        text = visible_text(_render(deals=_deals(12))).lower()
        for name in _SCRIPT_NAMES:
            self.assertNotIn(name.lower(), text, name)

    def test_the_email_stays_inside_the_gmail_payload_cap(self):
        html = _render(deals=_deals(12))
        self.assertLess(len(html.encode("utf-8")), hol.EMAIL_HTML_BUDGET_BYTES)

    def test_three_links_per_card_at_most(self):
        # The first link is labelled by what it books (BRIEF-H16 §3), so both
        # branches are pinned here: a package-priced card keeps the operator's
        # package search, and a card the engine priced keeps the hotel.
        deal = _deal(package_priced=True)
        links = link_row(deal, _config())
        self.assertEqual([label for label, _ in links],
                         ["Book this package", "Compare prices", "Hotel page"])
        html = _render(deals=[deal])
        for label, _ in links:
            self.assertEqual(html.count(f">{label} ↗<"), 1)
        self.assertEqual(html.count(">Hotel page ↗<"), 1)

    def test_a_card_the_engine_priced_books_the_hotel_not_a_package(self):
        links = link_row(_deal(), _config())
        self.assertEqual([label for label, _ in links],
                         ["Book the hotel", "Compare prices", "Hotel page"])
        html = _render(deals=[_deal()])
        self.assertEqual(html.count(">Book the hotel ↗<"), 1)
        self.assertNotIn("Book this package", html)


class NotesAndListsTests(unittest.TestCase):
    def test_over_budget_resorts_are_one_line_each(self):
        config = _config()
        rows = (
            {
                "resort_name": "Test Over Resort",
                "destination_label": "Kuta Mandalika, Lombok",
                "destination_key": "lombok",
                "max_budget_gbp": config.max_budget_gbp,
                "true_d2d": config.max_budget_gbp + 500.0,
                "total_pkg": config.max_budget_gbp + 460.0,
                "airport": "LOP",
                "outbound": "2027-07-05",
                "return": "2027-07-17",
                "nights": 12,
                "origin": "LHR",
                "cabin": "ECONOMY",
                "flight_cost": 2400.0,
                "flight_confidence": "benchmark",
                "hotel_cost": 3600.0,
                "hotel_confidence": "market-supported",
                "unit": "Two-bedroom pool villa",
                "board": "Bed & Breakfast",
                "flight_options": (),
            },
        )
        with patch.object(hol, "LAST_OVER_BUDGET", rows):
            text = visible_text(_render(deals=_deals(2)))
        self.assertIn("Test Over Resort", text)
        self.assertIn("£500 over", text)

    def test_strict_filters_are_one_short_line_per_resort_in_the_notes(self):
        with patch.object(hol, "LAST_FILTERED_OUT", (("Test Dropped Resort", "board unverified — the rate read did not state breakfast"),)):
            html = _render(deals=_deals(2))
        text = visible_text(html)
        self.assertIn("Test Dropped Resort — board unverified", text)
        self.assertTrue(text.index("Notes") > text.index("Test Resort 1"))

    def test_a_resort_whose_guest_rating_was_never_read_is_named_in_the_notes(self):
        hol.SUITE_ARCHITECTURE.setdefault(
            "Test Unread Resort",
            {
                "suite_type": "test unit", "suite_nightly_gbp": 100.0,
                "suite_peak_nightly_gbp": 100.0, "beach_walkable": True,
                "pool_heated_c": 28, "tripadvisor": None, "nonstop_from": (),
            },
        )
        text = visible_text(_render(deals=[_deal(resort_name="Test Unread Resort")]))
        self.assertIn("Test Unread Resort — guest rating not checked", text)

    def test_a_reason_cut_off_mid_clause_is_not_printed(self):
        # The shape that shipped three times (REVIEW-H3 P1). It is only 62
        # characters, so the 96-character clip cannot catch it and it carries
        # no ellipsis: verbatim it reads as a broken sentence at the bottom of
        # the e-mail. It is refused instead - the detailed renderer's strict
        # filters block still carries it.
        truncated = "no rate read for these dates yet — the card appears once one is"
        with patch.object(hol, "LAST_FILTERED_OUT", (("Test Cut Resort", truncated),)):
            text = visible_text(_render(deals=_deals(1)))
        self.assertNotIn("Test Cut Resort", text)

    def test_the_refusal_only_catches_reasons_that_stop_on_a_dangling_word(self):
        # The legitimate reason shapes are lower-case fragments with no full
        # stop, and a rule that demanded one would delete the whole section.
        kept = (
            "user exclusion / waterpark-only",
            "needs 3 rooms — breaks the one-unit rule",
            "no verified one-unit room sleeping 5 (2-bed suite / interconnecting)",
            "no genuine walkable private beach attached",
            "board unverified — the rate read did not state breakfast, so it is not assumed",
            "TripAdvisor 4.2 < 4.5",
            "island resort without each sold board basis priced separately",
            "room only — not a deal: breakfast is the minimum",
        )
        with patch.object(hol, "LAST_FILTERED_OUT", tuple(
                (f"Kept Resort {index}", reason) for index, reason in enumerate(kept))):
            text = visible_text(_render(deals=_deals(1)))
        for reason in kept:
            with self.subTest(reason=reason):
                self.assertIn(reason, text)

    def test_a_reason_longer_than_a_line_is_clipped_with_an_ellipsis(self):
        long_reason = "x" * 140
        with patch.object(hol, "LAST_FILTERED_OUT", (("Test Long Resort", long_reason),)):
            text = visible_text(_render(deals=_deals(1)))
        self.assertIn("…", text)
        self.assertNotIn("x" * 100, text)

    def test_no_source_reason_literal_ends_mid_clause(self):
        # The literals themselves, so the guard above stays a backstop rather
        # than the only thing between a truncated sentence and the reader.
        source = (ROOT / "src" / "public_flight_search" / "holidays.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("the card appears once one is\"", source)
        self.assertIn(
            "the card appears \"\n                        \"once one is read.\"",
            source,
        )


class TextPartTests(unittest.TestCase):
    def test_the_plain_text_part_mirrors_the_html_order_and_numbers(self):
        deals = _deals(3)
        html = _render(deals=deals)
        text = render_holiday_report_compact_text(
            _config(), generated_at=GENERATED_AT, deals=deals
        )
        for deal in deals:
            self.assertLess(text.index(deal.resort_name), 10_000)
            self.assertIn("£6,042", text)
        self.assertIn("At a glance", text)
        self.assertIn("total for 5, door to door", text)
        # The glance table row order and the card order are the same.
        positions = [text.index(deal.resort_name) for deal in deals]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("Prices checked Sun 4 Oct", text)

    # Owner, 2026-10-08: "why are you giving me useless price changes bullets
    # wasting space, I don't care about that". The "What changed" block used to
    # open both parts with one ▼/▲/✦ line per resort that moved; it is gone from
    # both, whatever the digest holds. The digest itself is still computed: it
    # decides whether a run sends when HOLIDAY_SEND_EVERY_RUN is off.
    _DIGESTS = (
        {   # prices moved, both ways, and a resort came under budget
            "has_prior": True,
            "drops": [{"name": "Test Resort 1", "current": 1.0, "prev": 2.0, "delta": -10.0}],
            "rises": [{"name": "Test Resort 2", "current": 3.0, "prev": 2.0, "delta": 15.0}],
            "new": ["Test Resort 0"],
            "last_report_at": LAST_REPORT_AT,
        },
        {   # a first run: nothing to compare with
            "has_prior": False, "drops": [], "rises": [],
            "new": ["Test Resort 0", "Test Resort 1"], "last_report_at": "",
        },
        {   # prior data, nothing moved
            "has_prior": True, "drops": [], "rises": [], "new": [],
            "unchanged": 12, "last_report_at": LAST_REPORT_AT,
        },
    )
    _DIGEST_WORDS = (
        "What changed",
        "▼ Test Resort",
        "▲ Test Resort",
        "✦",
        "now under budget",
        "First time tracked",
        "nothing to compare with yet",
        "Every tracked resort is at its previous price",
    )

    def test_neither_part_carries_a_price_change_digest(self):
        for digest in self._DIGESTS:
            with self.subTest(has_prior=digest["has_prior"], moved=bool(digest["drops"])):
                html = _render(deals=_deals(3), digest=digest, last_report_at=LAST_REPORT_AT)
                text = render_holiday_report_compact_text(
                    _config(), generated_at=GENERATED_AT, deals=_deals(3),
                    digest=digest, last_report_at=LAST_REPORT_AT,
                )
                for part_name, part in (("html", visible_text(html)), ("text", text)):
                    for words in self._DIGEST_WORDS:
                        self.assertNotIn(words, part, f"{part_name}: {words}")

    def test_a_pre_rendered_digest_is_not_printed_either(self):
        # The detailed renderer's own digest HTML used to be the fallback when
        # no digest rows were passed, so a caller could still put it back.
        rendered = '<div>What changed: ▼ Test Resort 1 £10 cheaper</div>'
        html = _render(deals=_deals(2), change_digest_html=rendered)
        text = render_holiday_report_compact_text(
            _config(), generated_at=GENERATED_AT, deals=_deals(2),
            change_digest_html=rendered,
        )
        for part in (visible_text(html), text):
            self.assertNotIn("What changed", part)
            self.assertNotIn("£10 cheaper", part)

    def test_the_text_part_states_the_same_breakdown_and_tag(self):
        deals = [_deal(confidence="stale-cache", live_observed_at="2026-09-29T09:00:00+00:00")]
        text = render_holiday_report_compact_text(_config(), generated_at=GENERATED_AT, deals=deals)
        self.assertIn("flights £2,400 (economy) + stay £3,600 + transfers £42 = £6,042", text)
        self.assertIn("Seen 5 days ago", text)
        self.assertIn("total for 5, door to door", visible_text(_render(deals=deals)))


class StyleSwitchTests(unittest.TestCase):
    def test_detailed_style_returns_the_old_renderer_output(self):
        payload = load_holiday_config(DEC.read_text(encoding="utf-8"))
        deals = _deals(3)
        with patch.dict(os.environ, {"HOLIDAY_REPORT_STYLE": "detailed"}):
            from public_flight_search.jobs import _report_style
            style = _report_style()
        self.assertEqual(style, "detailed")
        old = render_holiday_report(payload, generated_at=GENERATED_AT,
                                    deals=[_deal(index) for index in range(3)])
        new = render_holiday_report_compact(payload, generated_at=GENERATED_AT, deals=deals)
        self.assertNotEqual(old, new)
        self.assertIn("Package operators", old)
        self.assertNotIn("Package operators", new)

    def test_the_default_style_is_the_compact_one(self):
        from public_flight_search.jobs import _report_style

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HOLIDAY_REPORT_STYLE", None)
            self.assertNotEqual(_report_style(), "detailed")

    def test_the_job_renders_the_compact_email_by_default(self):
        import tempfile
        from pathlib import Path

        from public_flight_search.jobs import run_holiday_planner

        sent: dict = {}

        def _capture(subject, html, *, text=""):
            sent["html"] = html
            sent["text"] = text

        with tempfile.TemporaryDirectory() as tmp:
            # A real send writes history. It must land in a scratch file, never
            # the checkout's data/holiday_price_history.jsonl: a test that
            # appends there changes what the next dry run reads as "last time".
            env = {
                "HOLIDAY_SEARCH_CONFIG_JSON": DEC.read_text(encoding="utf-8"),
                "HOLIDAY_HISTORY_PATH": str(Path(tmp) / "history.jsonl"),
            }
            with patch.dict(os.environ, env), patch(
                "public_flight_search.jobs.send_html", _capture
            ):
                run_holiday_planner(
                    dry_run=False,
                    force_send=True,
                    hotel_evidence_path=str(Path(tmp) / "absent-hotel.json"),
                    live_evidence_path=str(Path(tmp) / "absent-live.json"),
                )
        self.assertIn("Every price is the total for 5, door to door.", visible_text(sent["html"]))
        self.assertIn("flights £", sent["text"])

    def test_no_email_the_job_sends_carries_the_change_digest(self):
        """Owner 2026-10-08: the price-change bullets go from every holiday e-mail.

        The second of two runs has prior history, so the digest has something
        to say ("No price movement since the last report ..." in the detailed
        renderer, "Every tracked resort is at its previous price" in the
        compact one). Neither style may print it.
        """
        import tempfile

        from public_flight_search.jobs import run_holiday_planner

        for style in ("", "detailed"):
            with self.subTest(style=style or "compact"), tempfile.TemporaryDirectory() as tmp:
                sent: list = []

                def _capture(subject, html, *, text=""):
                    sent.append((html, text))

                env = {
                    "HOLIDAY_SEARCH_CONFIG_JSON": DEC.read_text(encoding="utf-8"),
                    "HOLIDAY_HISTORY_PATH": str(Path(tmp) / "history.jsonl"),
                    "HOLIDAY_REPORT_STYLE": style,
                }
                with patch.dict(os.environ, env), patch(
                    "public_flight_search.jobs.send_html", _capture
                ):
                    for _ in range(2):
                        run_holiday_planner(
                            dry_run=False,
                            force_send=True,
                            hotel_evidence_path=str(Path(tmp) / "absent-hotel.json"),
                            live_evidence_path=str(Path(tmp) / "absent-live.json"),
                        )
                self.assertEqual(len(sent), 2)
                html, text = sent[-1]
                for part in (visible_text(html), text):
                    for words in ("What changed", "No price movement since the last report",
                                  "Every tracked resort is at its previous price",
                                  "vs last report", "now under budget", "more moved"):
                        self.assertNotIn(words, part, words)

    def test_the_job_text_part_is_not_a_placeholder_any_more(self):
        from public_flight_search.mailer import send_html

        with patch.dict(
            os.environ,
            {"SMTP_USER": "a@example.invalid", "SMTP_PASSWORD": "x", "REPORT_RECIPIENT": "b@example.invalid"},
        ), patch("public_flight_search.mailer.smtplib.SMTP") as smtp:
            send_html("subject", "<p>html</p>", text="plain twin")
        sent = smtp.return_value.__enter__.return_value.sendmail.call_args[0][2]
        message = message_from_string(sent)
        parts = {part.get_content_type(): part.get_payload(decode=True).decode("utf-8")
                 for part in message.walk() if not part.is_multipart()}
        self.assertEqual(parts["text/plain"], "plain twin")
        self.assertEqual(parts["text/html"], "<p>html</p>")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()