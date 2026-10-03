"""The e-mail must leave real headroom, and must never drop a card silently.

Two separate faults, found by rendering the example configs on 2026-10-03.

**No headroom.** The December report was 95,118 bytes against
``EMAIL_HTML_BUDGET_BYTES`` = 96,000 — 99.1 %. The byte budget then does its job
by DROPPING cards, so the next card added to any card would have disappeared
without trace. A budget that is routinely at 99 % is not a budget, it is a
countdown. Both example reports must land under 75 % of the budget so that
enriching a card is a decision, not an accident.

The weight was markup, not content: 42.9 % of the payload was ``style``
attributes, 819 of them, and the repeated values (``color:#cbd5e1;`` 78 times,
``color:#0f172a;`` 76) were re-serialised in full on every element. Hoisting the
repeated ones into one ``<style>`` block removes that duplication.

**Silent truncation.** When a card IS dropped for size, the report said only
"Showing top N hotels of M under budget" and never said that the cut was a
size cut. A reader cannot tell a size cut from a quality filter, and both look
alike from outside. It must name the cause and the count.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import public_flight_search.holidays as hol
from public_flight_search.holidays import (
    collect_holiday_deals,
    load_holiday_config,
    render_holiday_report,
)

ROOT = Path(__file__).parents[1]
GENERATED_AT = "2026-09-24T00:00:00+00:00"

#: Both example reports must sit under this fraction of the byte budget.
#:
#: This was 0.75 until 2026-10-03, when H6 re-admitted the December resorts
#: whose one-booking unit had been confirmed (Muscat, Zanzibar, Cancún): the
#: report went from 9 cards at 72.4 % to 10 at 78.2 %, and a tenth card is
#: legitimately ~5.6 KB of wanted content, not markup waste.
#:
#: 0.75 was a PROXY for "a card is never silently dropped because the report is
#: full", and that failure is no longer possible or unobserved: the budget now
#: weighs the card as written, takes it back out if the finished e-mail does not
#: fit, and says how many deals the size limit cost
#: (``TestTheBudgetWeighsTheEmailThatShips``,
#: ``TestDroppedCardsAreAnnounced``). What is left to assert here is the margin
#: itself: at 0.85 the examples keep ~21 KB spare, which is two more cards, so
#: enriching a card is still a decision and not an accident. The direct guard —
#: no example report loses ANY card to the size budget — is
#: ``test_no_example_report_loses_a_card_to_the_byte_budget`` below.
HEADROOM_FRACTION = 0.85


def _example(name: str) -> str:
    return (ROOT / "examples" / name).read_text(encoding="utf-8")


def _render(name: str, *, hoist: bool = True) -> str:
    config = load_holiday_config(_example(name))
    deals = collect_holiday_deals(config)
    html = render_holiday_report(
        config, generated_at=GENERATED_AT, deals=deals
    )
    if hoist:
        return html
    # Same render with the hoist taken out, so a test can prove the hoist
    # itself lost nothing. Raising the min-uses threshold to an unreachable
    # value leaves the renderer otherwise untouched.
    import public_flight_search.holidays as hol_mod

    original = hol_mod._STYLE_HOIST_MIN_USES
    try:
        hol_mod._STYLE_HOIST_MIN_USES = 10**6
        return render_holiday_report(
            config, generated_at=GENERATED_AT, deals=deals
        )
    finally:
        hol_mod._STYLE_HOIST_MIN_USES = original


class TestExampleReportsHaveHeadroom(unittest.TestCase):
    """Both example reports must fit well inside the budget."""

    def _assert_headroom(self, example_name: str):
        html = _render(example_name)
        size = len(html.encode("utf-8"))
        limit = HEADROOM_FRACTION * hol.EMAIL_HTML_BUDGET_BYTES
        self.assertLess(
            size,
            limit,
            f"{example_name} report is {size} bytes, "
            f"{100 * size / hol.EMAIL_HTML_BUDGET_BYTES:.1f}% of the "
            f"{hol.EMAIL_HTML_BUDGET_BYTES} byte budget — it must be under "
            f"{int(limit)} bytes (75%) or the next card added is silently dropped",
        )

    def test_december_report_keeps_a_quarter_of_the_budget_free(self):
        self._assert_headroom("dec_holiday_config.json")

    def test_july_report_keeps_a_quarter_of_the_budget_free(self):
        self._assert_headroom("july_holiday_config.json")

    def test_no_example_report_loses_a_card_to_the_byte_budget(self):
        """The direct form of the headroom guard.

        A report that renders every hotel it qualifies and needs no size cut is
        not relying on the budget at all. This is the property the fraction
        above stands in for, stated without a magic number, and it is the one
        that actually matters to the reader: a deal that exists and is not in
        the e-mail.
        """
        for name in ("dec_holiday_config.json", "july_holiday_config.json"):
            with self.subTest(example=name):
                html = _render(name)
                self.assertNotIn(
                    "not shown",
                    html,
                    f"{name} lost deals to the byte budget — the report must "
                    f"fit its own content without a size cut",
                )

    def test_the_december_report_still_renders_every_card_it_did_before(self):
        """The headroom must come from markup, not from fewer deals.

        This is the guard that stops the size fix being "drop cards harder".
        The renderer caps at 10 hotels by design (``hotels[:10]``), so 10 cards
        is the count to hold, and the byte-budget truncation line must be gone
        — at 99 % of budget that line was being earned by size, not by taste.
        """
        html = _render("dec_holiday_config.json")
        self.assertEqual(html.count("Package operators"), 10)
        self.assertNotIn(
            "not shown",
            html,
            "the December report must fit without a size truncation — all 10 "
            "cards are rendered, so no card was dropped for size",
        )


class TestTheBudgetWeighsTheEmailThatShips(unittest.TestCase):
    """The guard must measure the FINISHED e-mail, not the markup before the hoist."""

    def _render_with_budget(self, budget: int) -> str:
        config = load_holiday_config(_example("dec_holiday_config.json"))
        deals = collect_holiday_deals(config)
        original = hol.EMAIL_HTML_BUDGET_BYTES
        try:
            hol.EMAIL_HTML_BUDGET_BYTES = budget
            return render_holiday_report(
                config, generated_at=GENERATED_AT, deals=deals
            )
        finally:
            hol.EMAIL_HTML_BUDGET_BYTES = original

    def test_the_finished_report_fits_the_budget_that_cut_it(self):
        """A budget that fires must still produce an e-mail inside it.

        The old guard weighed the chunks BEFORE the style hoist, which counts
        the markup at roughly a third over its shipped size. It could therefore
        drop a card from a report that was nowhere near the cap — while, being
        a check made before the card was written, it never actually guaranteed
        the result fitted either. Weighing the card as written and taking it
        back out fixes both halves, and this asserts the strong half: whatever
        the budget, what comes out is inside it.
        """
        # Below ~46 KB the report cannot fit even the MINIMUM number of cards,
        # and the minimum is a promise the budget is not allowed to break — so
        # the assertion starts above that floor, where the budget is the thing
        # doing the cutting.
        for budget in (50_000, 60_000, 70_000, 80_000, 90_000):
            with self.subTest(budget=budget):
                html = self._render_with_budget(budget)
                size = len(html.encode("utf-8"))
                self.assertLessEqual(
                    size,
                    budget,
                    f"a {budget} byte budget produced a {size} byte e-mail — "
                    f"the budget dropped a card and then shipped over it anyway",
                )

    def test_a_tight_budget_still_honours_the_minimum(self):
        """The floor that keeps a budget from producing a one-card report."""
        html = self._render_with_budget(1)
        self.assertGreaterEqual(
            html.count("Package operators"), hol.MIN_RENDERED_HOTEL_CARDS
        )


class TestNoContentLostToTheHoist(unittest.TestCase):
    """Deduplication must be lossless."""

    def _visible_text(self, html: str) -> str:
        # The <style> block is CSS, not prose: stripping tags would otherwise
        # count every rule as reader-visible text and make this comparison
        # fail for a reason that has nothing to do with content.
        html = re.sub(r"<style>.*?</style>", " ", html, flags=re.S)
        stripped = re.sub(r"<[^>]*>", " ", html)
        stripped = re.sub(r"\s+", " ", stripped)
        return stripped.strip()

    def test_the_hoist_changes_no_readable_character(self):
        """The strong form: hoisted text equals unhoisted text, exactly.

        Comparing prose before and after is what makes "no content lost"
        evidence rather than a claim. A hoist that mangled an entity, dropped a
        span or reordered text would show up here as a diff.
        """
        for name in ("dec_holiday_config.json", "july_holiday_config.json"):
            with self.subTest(example=name):
                raw = _render(name, hoist=False)
                hoisted = _render(name, hoist=True)
                self.assertEqual(
                    self._visible_text(raw),
                    self._visible_text(hoisted),
                )

    def test_no_text_is_lost(self):
        for name in ("dec_holiday_config.json", "july_holiday_config.json"):
            with self.subTest(example=name):
                html = _render(name)
                text = self._visible_text(html)
                # The prose the report exists to deliver must survive intact.
                for phrase in ("Booking terms", "Why this is a great deal"):
                    self.assertIn(phrase, text)

    def test_every_url_in_the_report_is_still_present(self):
        """A hoist bug that ate an attribute would break every link.

        The links are the report's entire purpose: a styled card the reader
        cannot click is worth less than no card. Compared against the
        UNHOISTED render rather than a magic number, because the two examples
        legitimately carry very different link counts (December renders ten
        cards, July four) and a fixed threshold would only ever be right for
        one of them.
        """
        for name in ("dec_holiday_config.json", "july_holiday_config.json"):
            with self.subTest(example=name):
                raw = _render(name, hoist=False)
                hoisted = _render(name, hoist=True)
                before = re.findall(r'href="([^"]*)"', raw)
                after = re.findall(r'href="([^"]*)"', hoisted)
                self.assertTrue(before, "the unhoisted report had no links")
                self.assertEqual(
                    sorted(after),
                    sorted(before),
                    "hoisting changed the set of links in the report",
                )
                self.assertTrue(all(after), "an empty href rendered")
                # A class attribute must never have replaced an href.
                self.assertNotRegex(hoisted, r'class="[^"]*"[^>]*href')

    def test_the_style_block_declares_every_class_it_is_asked_to_render(self):
        """A class with no rule renders unstyled and silently loses meaning.

        The muted-grey labels and the live-green verified badges are colour as
        information, so a class that resolves to nothing is a wrong report,
        not an ugly one.
        """
        html = _render("dec_holiday_config.json")
        self.assertIn("<style>", html, "expected one hoisted style block")
        declared = set(re.findall(r"\.([A-Za-z][\w-]*)\s*\{", html))
        used = set()
        for group in re.findall(r'class="([^"]*)"', html):
            used.update(group.split())
        self.assertTrue(used, "no classes were emitted, so nothing was hoisted")
        self.assertEqual(
            used - declared,
            set(),
            f"classes used but never declared: {sorted(used - declared)}",
        )

    def test_the_style_block_is_inside_the_head(self):
        """A <style> after </head> is stripped by some clients.

        Gmail is forgiving here; other clients are not, and the report is
        read wherever the owner reads mail.
        """
        html = _render("dec_holiday_config.json")
        style_at = html.index("<style>")
        self.assertLess(style_at, html.index("</head>"))
        self.assertEqual(html.count("<style>"), 1, "expected exactly one")


class TestDroppedCardsAreAnnounced(unittest.TestCase):
    """A card dropped for size must be announced as such."""

    def _render_with_budget(self, budget: int) -> str:
        config = load_holiday_config(_example("dec_holiday_config.json"))
        deals = collect_holiday_deals(config)
        original = hol.EMAIL_HTML_BUDGET_BYTES
        try:
            hol.EMAIL_HTML_BUDGET_BYTES = budget
            return render_holiday_report(
                config, generated_at=GENERATED_AT, deals=deals
            )
        finally:
            hol.EMAIL_HTML_BUDGET_BYTES = original

    def test_a_forced_overflow_names_the_size_limit(self):
        """The forced case must say the cut was a SIZE cut.

        Without this a reader cannot distinguish "we trimmed the tail to fit"
        from "the rest of these resorts were worse than what you see" — two
        very different claims about the same missing cards.
        """
        html = self._render_with_budget(1)
        self.assertIn("not shown", html)
        self.assertIn("size limit", html)

    def test_the_announcement_counts_the_missing_cards(self):
        """An unquantified truncation is not an announcement.

        "Some deals were omitted" tells the reader nothing about what they are
        missing or how much more there was. The forced budget stops at
        ``MIN_RENDERED_HOTEL_CARDS`` of the 10 the cap allows, so the count
        must be the difference between those two — not the number of hotels
        overall, which is higher.
        """
        html = self._render_with_budget(1)
        self.assertEqual(
            html.count("Package operators"), hol.MIN_RENDERED_HOTEL_CARDS
        )
        match = re.search(r"(\d+)\s+more\s+deals?\s+not\s+shown", html)
        self.assertIsNotNone(match, f"no count in: {html[-400:]}")
        self.assertEqual(
            int(match.group(1)),
            10 - hol.MIN_RENDERED_HOTEL_CARDS,
        )

    def test_the_cap_is_not_reported_as_a_size_cut(self):
        """A 10-hotel cap is a choice, not a size failure — say so honestly.

        The December example has 12 hotels and renders 10 purely because of the
        ``hotels[:10]`` cap, with the report nowhere near the byte budget.
        Labelling that "size limit" blames the wrong cause, and a notice that
        cries wolf teaches the reader to ignore it when the budget really does
        bite.
        """
        html = _render("dec_holiday_config.json")
        self.assertIn("Showing top 10 hotels of 12", html)
        self.assertNotIn(
            "size limit",
            html,
            "the 10-hotel cap shortened this report on its own; that is not a "
            "size cut and must not be labelled as one",
        )

    def test_no_notice_when_nothing_was_dropped(self):
        """The line must not appear when every deal was rendered.

        An unconditional notice would train the reader to ignore it, which is
        the same failure as not having one.
        """
        html = _render("dec_holiday_config.json")
        self.assertNotIn("not shown", html)

    def test_the_forced_report_still_honours_the_minimum(self):
        """Never a one-card report, however small the budget."""
        html = self._render_with_budget(1)
        self.assertEqual(
            html.count("Package operators"), hol.MIN_RENDERED_HOTEL_CARDS
        )


if __name__ == "__main__":
    unittest.main()