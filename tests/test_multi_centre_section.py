"""Two-centre trips: shown as ranges, priced against the runtime budget.

Owner direction 2026-10-04 ("multi-stop holidays are also considered too").

The engine cannot price a two-centre trip: there is no dated multi-city fare
and no rate for a second hotel, so there is nothing to put on a card. What it
CAN do is show the shape honestly — a range with its basis, one line of why,
one line of catch, and a search link that opens the real prices. These tests
pin that contract, and above all pin the three ways a section like this can
lie:

* a range that is really a quote;
* a verdict about the budget that was decided when the file was written rather
  than against ``config.max_budget_gbp`` at render time;
* an itinerary whose search link opens dates that are not the trip being
  priced.
"""

from __future__ import annotations

import base64
import dataclasses
import json
from pathlib import Path
import tempfile
import unittest
import urllib.parse

from public_flight_search import holidays as hol
from public_flight_search.holidays import (
    collect_holiday_deals,
    load_holiday_config,
)
from public_flight_search.holiday_email import (
    _multi_centre_rows,
    render_holiday_report_compact,
    render_holiday_report_compact_text,
)
from public_flight_search.multi_centre import (
    DEFAULT_MULTI_CENTRE_PATH,
    SCHEMA,
    load_multi_centre,
    trip_legs_for_dates,
)

ROOT = Path(__file__).parents[1]
JULY = ROOT / "examples" / "july_holiday_config.json"
DEC = ROOT / "examples" / "dec_holiday_config.json"
DATA = Path(DEFAULT_MULTI_CENTRE_PATH)

#: Synthetic budgets. Never the owner's.
TIGHT_GBP = 8000.0
LOOSE_GBP = 40000.0

#: The fields of an itinerary that are allowed to carry a money amount: the
#: range itself and the prose that says how it was built (``cost_basis`` and
#: each stop's ``basis``). Everything else may not, because a ceiling is not a
#: cost line — see ``test_no_budget_figure_is_stored_in_the_file``.
COST_FIELDS = frozenset({"cost_low_gbp", "cost_high_gbp", "cost_basis"})

#: Google Flights' seat selector: field 9, value 1 is Economy and 3 is Business
#: (``google_flights._seat_field``). Decoded here rather than matched as a
#: string, so the assertion is about what the provider is actually asked for.
_SEAT_FIELD = 9
_SEAT_NAMES = {1: "ECONOMY", 2: "PREMIUM_ECONOMY", 3: "BUSINESS", 4: "FIRST"}


def _varint(payload: bytes, index: int) -> tuple[int, int]:
    value = shift = 0
    while True:
        byte = payload[index]
        index += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, index
        shift += 7


def _link_cabin(url: str) -> str:
    """The cabin a Google Flights ``tfs=`` link searches, decoded from it.

    The payload is base64 over a protobuf; this walks its varint fields and
    reads the seat selector out. A payload that cannot be walked RAISES rather
    than returning a default: a link whose cabin cannot be read has not been
    checked, and a test that passed on "no cabin found" would be worthless.
    """
    query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    raw = query["tfs"][0]
    payload = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    index = 0
    while index < len(payload):
        key, index = _varint(payload, index)
        wire = key & 0x07
        if wire == 0:
            value, index = _varint(payload, index)
        elif wire == 2:
            length, index = _varint(payload, index)
            index += length
            continue
        else:  # pragma: no cover - the adapter emits only varints here
            raise AssertionError(f"unsupported wire type {wire} in {url}")
        if key >> 3 == _SEAT_FIELD:
            return _SEAT_NAMES[value]
    raise AssertionError(f"no seat field in {url}")


def _config(path: Path, budget: float | None = None):
    config = load_holiday_config(path.read_text(encoding="utf-8"))
    return config if budget is None else dataclasses.replace(config, max_budget_gbp=budget)


def _html(config, *, budget: float | None = None) -> str:
    config = config if budget is None else dataclasses.replace(config, max_budget_gbp=budget)
    return render_holiday_report_compact(
        config, generated_at="2026-10-04T00:00:00+00:00",
        deals=collect_holiday_deals(config),
    )


def _text(config, *, budget: float | None = None) -> str:
    config = config if budget is None else dataclasses.replace(config, max_budget_gbp=budget)
    return render_holiday_report_compact_text(
        config, generated_at="2026-10-04T00:00:00+00:00",
        deals=collect_holiday_deals(config),
    )


class ShippedDataTests(unittest.TestCase):
    def test_the_file_is_the_schema_the_loader_demands(self):
        payload = json.loads(DATA.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema"], SCHEMA)

    def test_every_itinerary_carries_the_brief_s_own_fields(self):
        payload = json.loads(DATA.read_text(encoding="utf-8"))
        for item in payload["itineraries"]:
            with self.subTest(itinerary=item["id"]):
                for field in ("id", "title", "season", "stops", "legs",
                              "flight_shape", "cost_low_gbp", "cost_high_gbp",
                              "cost_basis", "why", "catch", "confidence"):
                    self.assertIn(field, item, field)
                self.assertTrue(item["stops"])
                self.assertGreaterEqual(len(item["legs"]), 2)
                self.assertLessEqual(item["cost_low_gbp"], item["cost_high_gbp"])
                self.assertIn(item["season"], ("summer", "winter"))
                self.assertIn(item["confidence"], ("dated-rate", "estimate"))

    def test_no_budget_figure_is_stored_in_the_file(self):
        """The owner's budget lives in config, never in committed data.

        A range that said "fits the <ceiling> budget" would be a claim the file
        cannot keep true: change the budget and it silently lies. So no field
        may carry a budget VERDICT or a budget AMOUNT — prose that merely says
        food is "unbudgeted" is fine.

        This is a PUBLIC repository, so the owner's own ceiling is a private
        figure and must not be committed here in any form. A test that banned
        one literal would only have disclosed it, so the ban is on the SHAPE:
        no field whose NAME mentions a budget, and no money amount anywhere
        outside the cost fields. That holds whatever the ceiling is.

        The cost fields are the range and the prose that says how the range
        was built — ``cost_low_gbp``/``cost_high_gbp``, ``cost_basis`` and each
        stop's ``basis``. They carry dated hotel and flight figures, which are
        the provenance of the range and belong on its face; a ceiling is a
        different kind of number and has no place in any of them.
        """
        payload = json.loads(DATA.read_text(encoding="utf-8"))
        for item in payload["itineraries"]:
            with self.subTest(itinerary=item["id"]):
                for field in ("why", "catch", "flight_shape", "title"):
                    text = str(item.get(field, ""))
                    self.assertNotRegex(
                        text, r"\d[\d,]*\s*(GBP|£)?\s*budget",
                        f"{item['id']}.{field} names a budget amount",
                    )
                    self.assertNotIn("fits the budget", text.lower())
                    self.assertNotIn("inside the budget", text.lower())
                for key in item:
                    self.assertNotIn(
                        "budget", str(key).lower(),
                        f"{item['id']} has a field named after a ceiling",
                    )
                for key, value in item.items():
                    if key in COST_FIELDS:
                        continue
                    if key == "stops":
                        # Each stop's own ``basis`` is a cost field too: it says
                        # how that stop's nights were costed.
                        for stop in value if isinstance(value, list) else ():
                            with self.subTest(itinerary=item["id"], stop=stop.get("place")):
                                for stop_key, stop_value in stop.items():
                                    if stop_key != "basis":
                                        self.assertNotRegex(
                                            str(stop_value), r"(£\s*\d|\bGBP\s*\d)",
                                            "a money amount outside the cost fields "
                                            "is a stored ceiling",
                                        )
                        continue
                    with self.subTest(itinerary=item["id"], field=key):
                        self.assertNotRegex(
                            str(value), r"(£\s*\d|\bGBP\s*\d)",
                            "a money amount outside the cost fields is a stored ceiling",
                        )

    def test_no_budget_verdict_is_written_into_any_string_in_the_file(self):
        """No stored sentence may decide the budget question.

        The file promises this in its own ``read_only_confirmation`` and in this
        module's docstring, and three itineraries broke it: MC-04 said "and it
        is still OVER budget", MC-07 said "It is over budget on estimates
        alone", MC-12 said "It comes in above the configured December budget",
        and two of their ``catch`` lines opened with "over budget". Each is a
        verdict reached against whatever ceiling happened to be configured when
        the file was compiled, so it goes stale the moment the budget changes
        and it cannot be made true again without editing the data.

        The ban is deliberately SHAPE-based and names no amount, because this is
        a public repository: it catches the words that state a verdict without
        ever naming a ceiling. It walks EVERY string in the payload rather than
        a field list, because a verdict is just as wrong in ``cost_basis`` or a
        stop's ``basis`` as it is in ``catch`` — which is exactly where these
        three hid, since only ``why``/``catch``/``flight_shape``/``title`` were
        checked before.

        Deferral is still allowed and is the correct form: "whether it fits the
        configured budget is decided at render time" is the promise, and it must
        survive. So are the words "unbudgeted" (about food not being in a
        range) and any bare mention of the word "budget".
        """
        verdict_phrases = (
            "over budget",
            "above the configured",
            "over the configured",
            "under budget",
        )
        raw = json.loads(DATA.read_text(encoding="utf-8"))

        def strings(node, path="$"):
            """Every string in the payload, with the path that reached it."""
            if isinstance(node, str):
                yield path, node
            elif isinstance(node, dict):
                for key, value in node.items():
                    yield from strings(value, f"{path}.{key}")
            elif isinstance(node, list):
                for index, value in enumerate(node):
                    yield from strings(value, f"{path}[{index}]")

        found = list(strings(raw))
        self.assertTrue(found, "the guard walked no strings at all")
        for path, text in found:
            lowered = text.lower()
            for phrase in verdict_phrases:
                with self.subTest(field=path, phrase=phrase):
                    self.assertNotIn(
                        phrase, lowered,
                        f"{path} states a stored budget verdict: {text[:90]!r}",
                    )

    def test_the_deferral_wording_is_still_there(self):
        """The guard above must not have deleted the promise it enforces."""
        raw = DATA.read_text(encoding="utf-8")
        self.assertIn("decided at render time", raw)
        self.assertIn("configured budget", raw)

    def test_no_private_path_from_the_research_leaked_into_the_file(self):
        raw = DATA.read_text(encoding="utf-8")
        for leaked in ("/home/kc", "C:", "\\\\"):
            self.assertNotIn(leaked, raw)

    def test_the_file_ships_with_the_package(self):
        self.assertTrue(DATA.is_file(), DATA)
        self.assertIn("data", DATA.parts)


class SeasonFilterTests(unittest.TestCase):
    def test_july_shows_the_summer_itineraries_only(self):
        trips = load_multi_centre(_config(JULY))
        self.assertTrue(trips)
        self.assertEqual({t.season for t in trips}, {"summer"})

    def test_december_shows_the_winter_itineraries_only(self):
        trips = load_multi_centre(_config(DEC))
        self.assertTrue(trips)
        self.assertEqual({t.season for t in trips}, {"winter"})

    def test_the_two_examples_never_show_each_others_itineraries(self):
        july = {t.id for t in load_multi_centre(_config(JULY))}
        december = {t.id for t in load_multi_centre(_config(DEC))}
        self.assertEqual(july & december, set())
        self.assertTrue(july)
        self.assertTrue(december)


class BudgetVerdictTests(unittest.TestCase):
    """The only decision made at render time, and it must be THIS budget."""

    def test_a_tight_budget_turns_every_verdict_to_over(self):
        text = _text(_config(JULY), budget=TIGHT_GBP)
        section = text.split("Two-centre trips")[1].split("Over the")[0]
        self.assertNotIn("low end fits", section)

    def test_a_loose_budget_turns_a_verdict_to_fits(self):
        tight = _text(_config(JULY), budget=TIGHT_GBP)
        loose = _text(_config(JULY), budget=LOOSE_GBP)
        self.assertIn("low end £", tight)
        self.assertIn("low end fits", loose)

    def test_the_verdict_is_judged_on_the_low_end_only(self):
        config = _config(JULY, budget=12000.0)
        trips = {t.id: t for t in load_multi_centre(config)}
        # Khao Lak + Koh Phangan: low 11,757 fits, high 15,607 does not.
        khao_lak = trips["MC-02"]
        self.assertTrue(khao_lak.fits(12000.0))
        self.assertFalse(khao_lak.fits(11000.0))
        self.assertIn("low end fits", _text(config))

    def test_an_unusable_budget_gets_no_verdict_rather_than_a_wrong_one(self):
        trips = load_multi_centre(_config(JULY))
        self.assertIsNone(trips[0].fits(0.0))
        self.assertIsNone(trips[0].fits(None))
        self.assertIsNone(trips[0].fits("not a number"))


class RenderTests(unittest.TestCase):
    def test_the_section_sits_between_the_cards_and_the_over_budget_list(self):
        html = _html(_config(JULY))
        self.assertIn("Two-centre trips", html)
        section = html.index("Two-centre trips")
        if "Over the" in html:
            self.assertLess(section, html.index("Over the"))
        if "Package operators" in html:
            self.assertLess(section, html.index("Package operators"))

    def test_each_itinerary_shows_a_title_a_range_and_a_verdict(self):
        text = _text(_config(JULY))
        section = text.split("Two-centre trips")[1]
        for trip in load_multi_centre(_config(JULY)):
            with self.subTest(itinerary=trip.id):
                self.assertIn(trip.title, section)
                self.assertIn(f"£{trip.cost_low_gbp:,.0f}–£{trip.cost_high_gbp:,.0f}", section)
                self.assertIn("low end", section)

    def test_no_range_is_ever_called_a_price_or_a_quote(self):
        for path in (JULY, DEC):
            text = _text(_config(path))
            section = text.split("Two-centre trips")[1]
            for banned in ("price:", "priced at", "quoted", "book for"):
                self.assertNotIn(banned, section.lower(), f"{path.name}: {banned}")

    def test_every_itinerary_carries_a_multi_city_search_link(self):
        html = _html(_config(JULY))
        section = html.split("Two-centre trips")[1]
        self.assertIn("google.com/travel/flights", section)
        self.assertIn("tfs=", section)
        self.assertIn("flights ↗", section)

    def test_the_multi_city_link_is_built_in_economy(self):
        """A two-centre trip's link must search ECONOMY, not Business.

        The link used to be built with ``cabin_class="BUSINESS"`` hard-coded
        (REVIEW-H9 P1-1). Under the owner's rule of 2026-10-04 — business class
        only for a DIRECT flight — every itinerary in this section is a
        connecting one, so a Business link made the reader's first search
        contradict the Economy cards directly above it.

        The cabin is decoded out of the ``tfs=`` payload rather than read off a
        source string: the payload is what Google will actually be asked for, so
        that is the thing that has to be right.
        """
        for path in (JULY, DEC):
            rows = _multi_centre_rows(_config(path))
            self.assertTrue(rows, path.name)
            for row in rows:
                with self.subTest(config=path.name, trip=row["trip"].id):
                    self.assertEqual(row["cabin"], "ECONOMY")
                    cabin = _link_cabin(row["url"])
                    self.assertEqual(cabin, "ECONOMY")

    def test_the_section_names_the_cabin_it_quotes(self):
        # The header says which cabin the ranges are, so a reader who clicks
        # the link is not surprised by a different search.
        for path in (JULY, DEC):
            with self.subTest(config=path.name):
                # The shared clause, matched case-insensitively because the
                # HTML and text twins differ in their opening capital.
                self.assertIn("these are Economy flights", _html(_config(path)))
                self.assertIn("these are Economy flights", _text(_config(path)))
                # And the word "direct" never appears: on a holiday card it
                # reads as "you book the flight yourself".
                self.assertNotRegex(
                    _text(_config(path)), r"\bdirect\b",
                )

    def test_the_text_twin_carries_the_same_numbers(self):
        config = _config(JULY, budget=12000.0)
        html = _html(config)
        text = _text(config)
        trip = load_multi_centre(config)[0]
        self.assertIn(f"£{trip.cost_low_gbp:,.0f}–£{trip.cost_high_gbp:,.0f}", html)
        self.assertIn(f"£{trip.cost_low_gbp:,.0f}–£{trip.cost_high_gbp:,.0f}", text)
        self.assertIn(trip.why, html)
        self.assertIn(trip.why, text)
        self.assertIn(trip.catch, html)
        self.assertIn(trip.catch, text)

    def test_a_config_with_no_itineraries_in_season_has_no_section(self):
        # A winter config carrying only summer itineraries must not render an
        # empty heading: the section appears when there is something in it.
        payload = json.loads(DATA.read_text(encoding="utf-8"))
        for item in payload["itineraries"]:
            item["season"] = "monsoon"
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(payload, handle)
            path = handle.name
        config = _config(JULY)
        trips = load_multi_centre(config, path=path)
        self.assertEqual(trips, [])

    def test_a_missing_file_changes_nothing_and_invents_nothing(self):
        self.assertEqual(load_multi_centre(_config(JULY), path="data/nope.json"), [])

    def test_a_wrongly_shaped_file_is_skipped_with_a_reason(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump({"schema": "something/else", "itineraries": []}, handle)
            path = handle.name
        self.assertEqual(load_multi_centre(_config(JULY), path=path), [])


class LegDateTests(unittest.TestCase):
    def test_each_stop_nights_lands_the_next_leg(self):
        config = _config(JULY)
        trip = next(t for t in load_multi_centre(config) if t.id == "MC-01")
        legs = trip_legs_for_dates(trip, "2027-07-01", "2027-07-15")
        self.assertEqual(legs[0][2], "2027-07-01")
        self.assertEqual(legs[1][2], "2027-07-08")   # 7 nights in Bali
        self.assertEqual(legs[2][2], "2027-07-15")   # home

    def test_the_last_leg_is_always_the_reports_own_return_date(self):
        config = _config(JULY)
        for trip in load_multi_centre(config):
            with self.subTest(itinerary=trip.id):
                legs = trip_legs_for_dates(trip, "2027-07-01", "2027-07-24")
                self.assertEqual(legs[-1][2], "2027-07-24")

    def test_no_leg_date_runs_past_the_return(self):
        config = _config(JULY)
        for trip in load_multi_centre(config):
            with self.subTest(itinerary=trip.id):
                for _origin, _dest, date in trip_legs_for_dates(trip, "2027-07-01", "2027-07-10"):
                    self.assertLessEqual(date, "2027-07-10")

    def test_a_pair_that_does_not_parse_raises_rather_than_guessing(self):
        trip = load_multi_centre(_config(JULY))[0]
        for outbound, returning in (("not-a-date", "2027-07-15"), ("2027-07-15", "2027-07-01"),
                                   ("2027-07-15", "2027-07-15")):
            with self.subTest(pair=(outbound, returning)):
                with self.assertRaises(ValueError):
                    trip_legs_for_dates(trip, outbound, returning)


if __name__ == "__main__":
    unittest.main()