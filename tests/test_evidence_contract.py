"""The live-evidence consumption contract.

WHY this file exists
--------------------

The private hunt crawls a hand-written list of airports, date pairs and
origins. The public report consumes exactly one date pair, from exactly one
origin, for exactly the airports that survive ``filter_resorts``. Nothing
tied the two together except two docstrings and the operator's memory.

Measured 2026-09-23 against the real evidence file: 125 records harvested,
20 consumed, and only **8 December cards** actually carried a live fare —
because the hunt spent its browser reads on six airports (AGA, CAI, DOH,
FNC, MCT, MLA) that have no card at all, while ACE and PFO, which do have
cards, were never hunted.

The contract below is the machine-readable answer to "what will the report
actually look up?" — so the hunt can be aimed from data instead of guessed.
These tests fail if the pairing, origins, cabins or card set move without
the hunt being re-aimed.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import json
import tempfile
import unittest

from public_flight_search.holidays import (
    _date_pairs,
    collect_holiday_deals,
    load_holiday_config,
    priceable_date_pairs,
    shortlist_date_pairs,
)
from public_flight_search.live_verify import (
    _target_date_pair,
    evidence_contract_gaps,
    evidence_consumption_contract,
    evidence_freshness,
    load_live_flight_evidence,
)

ROOT = Path(__file__).parents[1]
DEC_CONFIG = ROOT / "examples" / "dec_holiday_config.json"
JULY_CONFIG = ROOT / "examples" / "july_holiday_config.json"

SYNTHETIC = """
{
  "report_title": "Contract test",
  "party": {"travellers": 5, "rooms": [2, 2, 1]},
  "origins": ["LHR", "LGW"],
  "departure_window": ["06:00", "23:59"],
  "outbound_dates": ["2026-12-20", "2026-12-22", "2026-12-24"],
  "return_dates": ["2026-12-28", "2026-12-30", "2026-12-31"],
  "destinations": [
    {"key": "antalya", "label": "Antalya", "airports": ["AYT"]}
  ]
}
"""


#: A fixed instant the loader accepts: not in the future, not stale.
#:
#: Every loader call below injects it as ``now`` as well as stamping it on the
#: records, so the age is exactly 0h and no calendar date can turn these tests
#: red. Before that, the loader ignored ``now`` (``del now``) and measured the
#: real clock: this literal would have silently expired 72h after it was
#: written, failing the contract tests — and every holiday report run, since
#: the workflow runs the suite before it builds.
OBSERVED_AT = "2026-09-23T00:00:00+00:00"


def _observed_now() -> datetime:
    return datetime.fromisoformat(OBSERVED_AT)


def _load(path: Path):
    return load_holiday_config(path.read_text(encoding="utf-8"))


def _airport_cabins(loaded) -> set[tuple[str, str]]:
    """The (airport, cabin) half of every loader key.

    The loader keys entries by (airport, cabin, outbound, return, origin) so
    one run can hold a fare per priced date pair and origin; the contract is
    about airports and cabins, so that is the half asserted on here.
    """
    return {tuple(key[:2]) for key in loaded}


def _fare(loaded, key: tuple[str, str]):
    """The single fare loaded for one (airport, cabin), whatever pair it carries."""
    for loaded_key, evidence in loaded.items():
        if tuple(loaded_key[:2]) == key:
            return evidence
    raise AssertionError(f"no evidence loaded for {key}: {sorted(loaded)}")


class TestPricedPairIsTheSingleSourceOfTruth(unittest.TestCase):
    def test_contract_priced_pair_is_the_shortlist_middle(self):
        config = load_holiday_config(SYNTHETIC)
        contract = evidence_consumption_contract(config)
        expected = shortlist_date_pairs(config)[1]
        self.assertEqual((contract.outbound, contract.return_date), expected)

    def test_a_config_whose_cross_product_holds_out_of_band_pairs_never_headlines_one(self):
        """The rule the new July window exposed.

        Its cross product contains pairs shorter than the stay band (26 June ->
        3 July is 7 nights; 29 June -> 3 July is 4), and the shortlist used to
        be drawn from that cross product rather than from the pairs inside the
        band - so the headline could become a pair no card ever prices, and the
        hunt would spend its reads on a date the report never shows.

        The out-of-band pairs are DERIVED from the shipped config rather than
        pasted: the window moves, and a pinned date here turns every window
        change into a red suite.
        """
        config = load_holiday_config(JULY_CONFIG.read_text(encoding="utf-8"))
        priceable = priceable_date_pairs(config)
        shortlist = shortlist_date_pairs(config)
        contract = evidence_consumption_contract(config)

        for pair in shortlist:
            self.assertIn(pair, priceable, pair)
            self.assertTrue(
                config.min_nights
                <= (date.fromisoformat(pair[1]) - date.fromisoformat(pair[0])).days
                <= config.max_nights,
                pair,
            )
        self.assertEqual(
            (contract.outbound, contract.return_date), shortlist[len(shortlist) // 2]
        )
        # The premise: this config does offer pairs outside the band...
        out_of_band = [pair for pair in _date_pairs(config) if pair not in priceable]
        self.assertTrue(out_of_band, "the window no longer holds an out-of-band pair")
        # ...and none of them is ever shortlisted, let alone the headline.
        for pair in out_of_band:
            with self.subTest(pair=pair):
                self.assertNotIn(pair, shortlist)

    def test_target_date_pair_delegates_to_the_contract(self):
        # One definition, two entry points: if these ever disagree, the hunt
        # is aimed at a pair the loader will reject.
        config = load_holiday_config(SYNTHETIC)
        contract = evidence_consumption_contract(config)
        self.assertEqual(
            _target_date_pair(config), (contract.outbound, contract.return_date)
        )

    def test_contract_origin_is_the_origin_the_report_prices_from(self):
        config = load_holiday_config(SYNTHETIC)
        contract = evidence_consumption_contract(config)
        self.assertEqual(contract.origin, "LHR")
        self.assertEqual(contract.travellers, config.travellers)


class TestContractMatchesCollectorExactly(unittest.TestCase):
    """The contract key set must equal what the collector can ever verify.

    Built by injecting a valid whole-party fare for every contract key at an
    infinite budget, then asserting the collector verifies exactly those
    (airport, cabin) pairs — no more, no fewer.
    """

    def _write_evidence(self, entries: list[dict]) -> str:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False
        ) as handle:
            json.dump({"evidence": entries}, handle)
            return handle.name

    def _verified_keys(self, config) -> set[tuple[str, str]]:
        """Keys the collector verifies when EVERY priced pair carries a fare.

        The collector prices every pair in the config's nights band and takes
        the cheapest, so evidence on one pair only verifies a card while a
        cheaper unobserved pair wins. A hunt that covers the priced pairs —
        which is what the contract now asks for — verifies exactly the keys
        in it, and this asserts that end to end.
        """
        contract = evidence_consumption_contract(config)
        path = self._write_evidence(
            [
                {
                    "airport": airport,
                    "cabin_class": cabin,
                    "basis": "whole_party_return_total",
                    "total_gbp": 1000.0,
                    "source_url": "https://example.invalid/hunt",
                    "observed_at": OBSERVED_AT,
                    "travellers": contract.travellers,
                    "origin": contract.origin,
                    "exact_dates": {"outbound": outbound, "return": returning},
                }
                for airport, cabin in contract.keys
                for outbound, returning in priceable_date_pairs(config)
            ]
        )
        loaded = load_live_flight_evidence(
            config, path=path, now=_observed_now()
        )
        deals = collect_holiday_deals(
            config, max_budget_gbp=float("inf"), live_flight_offers=loaded or None
        )
        return {
            (deal.destination_airport, deal.cabin_class)
            for deal in deals
            if deal.confidence == "verified-exact-date"
        }

    def test_december_contract_covers_every_verifiable_card(self):
        config = _load(DEC_CONFIG)
        contract = evidence_consumption_contract(config)
        self.assertEqual(self._verified_keys(config), set(contract.keys))

    def test_july_contract_covers_every_verifiable_card(self):
        config = _load(JULY_CONFIG)
        contract = evidence_consumption_contract(config)
        self.assertEqual(self._verified_keys(config), set(contract.keys))


class TestRealConfigContractsAreGolden(unittest.TestCase):
    def test_december_prices_the_headline_pair_from_lhr(self):
        contract = evidence_consumption_contract(_load(DEC_CONFIG))
        self.assertEqual(
            (contract.outbound, contract.return_date),
            ("2026-12-20", "2026-12-28"),
        )
        self.assertEqual(contract.origin, "LHR")
        self.assertEqual(contract.travellers, 5)
        # The hunt is aimed at the whole shortlist, not just the headline
        # pair: the collector prices every priceable pair, so crawling one
        # pair wastes the reads the other two would have paid for.
        self.assertEqual(
            list(contract.hunt_date_pairs),
            [
                ("2026-12-17", "2026-12-25"),
                ("2026-12-20", "2026-12-28"),
                ("2026-12-23", "2026-12-31"),
            ],
        )
        self.assertEqual(contract.origins, ("LHR", "LGW", "LTN", "STN"))

    def test_december_contract_lists_only_airports_that_have_cards(self):
        contract = evidence_consumption_contract(_load(DEC_CONFIG))
        # Airports the hunt crawled in September 2026 that have no card at
        # all: hunting them can never price anything. (Doha and Muscat got
        # December resorts on 2026-09-30, so they left this list.)
        for dead in ("AGA", "CAI", "FNC", "MLA"):
            self.assertNotIn(dead, contract.airports, dead)
        # Card-bearing airports, including the two that were never hunted.
        # MCT/ZNZ/MRU/CUN left on 2026-10-02: their only resort needed three
        # rooms or had an unverified unit, so the one-booking rule filtered it.
        # They came BACK on 2026-10-03 (H6): InterContinental Muscat is two
        # rooms on one booking, Nungwi's unit is the four-bedroom Presidential
        # Villa, and Grand Fiesta's is the Ocean Front Two Bedroom Family &
        # Friends Suite - three properties that now genuinely have a
        # one-booking unit, so hunting their airports prices something.
        for live in ("ACE", "AYT", "FUE", "HRG", "LPA", "PFO", "TFS", "DOH",
                     "MCT", "ZNZ", "CUN"):
            self.assertIn(live, contract.airports, live)
        for filtered in ("MRU",):
            self.assertNotIn(filtered, contract.airports, filtered)

    def test_july_contract_follows_the_cabin_rule_on_the_priced_pair(self):
        # Since 2026-09-29 the July example is long-haul only (owner: nothing
        # within 6 hours; Lombok and Thailand). Every card-bearing July
        # airport is over 8 hours from London, so under the cabin rule the
        # hunt is aimed at Business only. The Far East watch keys (Bali, Da
        # Nang, Japan) and Doha/Muscat have no July resort cards (Doha and
        # Muscat are July stopovers, priced separately), so they add no
        # airports to the contract. ZNZ returned on 2026-10-03 (H6): Nungwi
        # Dreams' one-booking unit for 5 is its four-bedroom Presidential
        # Villa, not three Standard Rooms.
        #
        # The pair itself is derived from the shipped config (the shortlist
        # middle), not pasted: the owner's July window moved twice in a day and
        # a pinned date turns the next move into a red suite. The cabin rule,
        # which is what this test is about, stays pinned.
        config = _load(JULY_CONFIG)
        contract = evidence_consumption_contract(config)
        shortlist = shortlist_date_pairs(config)
        self.assertTrue(shortlist, "the shipped July config prices no pair")
        self.assertEqual(
            (contract.outbound, contract.return_date),
            shortlist[len(shortlist) // 2],
        )
        self.assertEqual(set(contract.airports), {"HKT", "LOP", "USM", "ZNZ"})
        self.assertEqual({cabin for _, cabin in contract.keys}, {"BUSINESS"})

    def test_contract_serializes_for_the_hunt(self):
        config = _load(JULY_CONFIG)
        contract = evidence_consumption_contract(config)
        payload = contract.as_dict()
        # The hunt gets the shortlist: three pairs, all of them inside the
        # nights band, so no read is spent on a date no card prices.
        shortlist = shortlist_date_pairs(config)
        self.assertEqual(len(shortlist), 3)
        for pair in shortlist:
            with self.subTest(pair=pair):
                self.assertIn(pair, priceable_date_pairs(config))
        self.assertEqual(
            payload["hunt_date_pairs"], [list(pair) for pair in shortlist]
        )
        self.assertEqual(payload["origin"], "LHR")
        self.assertEqual(payload["origins"], ["LHR", "LGW", "LTN", "STN"])
        self.assertIn("USM/BUSINESS", payload["keys"])
        self.assertNotIn("USM/ECONOMY", payload["keys"])
        # Self-contained: everything `python -m live --config` reads, plus
        # the four things the hunt gets wrong if it is handed the report's
        # own config (which pairs/origins/cabins/airports are priced).
        self.assertEqual(
            set(contract.hunt_config_overrides()),
            {
                "party",
                "destinations",
                "origins",
                "date_pairs",
                "cabin_classes",
                "airports",
            },
        )


class TestContractGaps(unittest.TestCase):
    def test_card_airport_without_evidence_is_reported_missing(self):
        config = _load(DEC_CONFIG)
        contract = evidence_consumption_contract(config)
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False
        ) as handle:
            json.dump(
                {
                    "evidence": [
                        {
                            "airport": "AYT",
                            "cabin_class": "ECONOMY",
                            "basis": "whole_party_return_total",
                            "total_gbp": 1000.0,
                            "source_url": "https://example.invalid/hunt",
                            "observed_at": OBSERVED_AT,
                            "travellers": contract.travellers,
                            "origin": contract.origin,
                            "exact_dates": {
                                "outbound": contract.outbound,
                                "return": contract.return_date,
                            },
                        }
                    ]
                },
                handle,
            )
            path = handle.name
        loaded = load_live_flight_evidence(
            config, path=path, now=_observed_now()
        )
        gaps = evidence_contract_gaps(config, loaded)
        self.assertNotIn("AYT/ECONOMY", gaps["missing"])
        self.assertIn("ACE/ECONOMY", gaps["missing"])
        self.assertIn("PFO/ECONOMY", gaps["missing"])
        # Since 2026-10-03 (H6) the December report has three long-haul cards again:
        # Muscat, Nungwi and Cancun each have a confirmed one-booking unit, so
        # their keys are Business. Everything else is still Economy.
        self.assertEqual(
            sorted(k for k in gaps["missing"] if not k.endswith("/ECONOMY")),
            ["CUN/BUSINESS", "ZNZ/BUSINESS"],
        )

    def test_evidence_for_an_airport_with_no_card_is_reported_unused(self):
        config = _load(DEC_CONFIG)
        loaded = {("ZZZ", "ECONOMY"): object()}
        gaps = evidence_contract_gaps(config, loaded)
        self.assertEqual(gaps["unused"], ["ZZZ/ECONOMY"])


class TestEvidenceFreshness(unittest.TestCase):
    def test_freshness_reports_newest_observation_and_staleness(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(
                {
                    "evidence": [
                        {"airport": "AYT", "observed_at": "2026-09-20T00:00:00+00:00"},
                        {"airport": "TFS", "observed_at": "2026-09-23T00:00:00+00:00"},
                    ]
                },
                handle,
            )
            path = handle.name
        fresh = evidence_freshness(
            path, now="2026-09-23T06:00:00+00:00"
        )
        self.assertEqual(fresh["record_count"], 2)
        self.assertEqual(fresh["newest_observed_at"], "2026-09-23T00:00:00+00:00")
        self.assertAlmostEqual(fresh["age_hours"], 6.0, places=3)
        self.assertFalse(fresh["stale"])

    def test_expired_evidence_is_flagged_rather_than_silently_dropped(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
            json.dump(
                {"evidence": [{"airport": "AYT", "observed_at": "2026-09-18T00:00:00+00:00"}]},
                handle,
            )
            path = handle.name
        fresh = evidence_freshness(path, now="2026-09-23T06:00:00+00:00")
        self.assertTrue(fresh["stale"])
        self.assertGreater(fresh["age_hours"], 72)

    def test_missing_file_is_reported_not_crashed(self):
        fresh = evidence_freshness("/nonexistent/evidence.json")
        self.assertEqual(fresh["record_count"], 0)
        self.assertIsNone(fresh["age_hours"])
        self.assertTrue(fresh["stale"])


class TestEvidenceContractCommand(unittest.TestCase):
    def test_cli_emits_the_hunt_overrides(self):
        from public_flight_search.cli import main

        import contextlib
        import io

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = main(
                [
                    "evidence-contract",
                    "--config",
                    str(JULY_CONFIG),
                    "--hunt-config",
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        # Derived from the shipped config's shortlist, not a pasted window: the
        # CLI must emit exactly what the contract prices, whenever it moves.
        config = _load(JULY_CONFIG)
        self.assertEqual(
            payload["date_pairs"],
            [list(pair) for pair in shortlist_date_pairs(config)],
        )
        self.assertEqual(payload["origins"], ["LHR", "LGW", "LTN", "STN"])
        self.assertEqual(payload["airports"], ["HKT", "LOP", "USM", "ZNZ"])

    def test_hunt_config_drives_the_hunt_on_its_own(self):
        # Regression: the fragment carried only origins/date_pairs/cabins/
        # airports, so `python -m live --config <file>` built ZERO routes —
        # the private hunt reads party.travellers and destinations[].airports
        # and nothing else, so aiming it from the CLI output did no work at
        # all. Everything the reader touches has to be in the emitted file.
        import contextlib
        import io

        from public_flight_search.cli import main

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = main(
                [
                    "evidence-contract",
                    "--config",
                    str(DEC_CONFIG),
                    "--hunt-config",
                ]
            )
        self.assertEqual(code, 0)
        payload = json.loads(buffer.getvalue())
        # A party size the evidence loader will accept, not the reader's
        # default of 1 traveller (which every fare would then be dropped for).
        self.assertEqual(payload["party"], {"travellers": 5})
        # One entry per contracted airport: load_routes uses airports[0], so a
        # multi-airport entry would silently hunt only its first airport.
        entries = payload["destinations"]
        self.assertTrue(entries)
        self.assertTrue(all(len(entry["airports"]) == 1 for entry in entries))
        self.assertEqual(
            {entry["airports"][0] for entry in entries},
            set(payload["airports"]),
        )

    def test_cli_rejects_unknown_flags(self):
        from public_flight_search.cli import main

        with self.assertRaises(SystemExit):
            main(["evidence-contract", "--send"])

    def test_cli_fails_fast_on_a_missing_explicit_config(self):
        # Regression: an explicit but missing path silently fell through to
        # env, then to examples/dec_holiday_config.json. A typo therefore
        # printed a valid DECEMBER contract with exit 0 and aimed the hunt at
        # the wrong report entirely.
        from public_flight_search.cli import main

        import contextlib
        import io

        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            with self.assertRaises(SystemExit) as raised:
                main(
                    [
                        "evidence-contract",
                        "--config",
                        "examples/july_holday_config.json",
                    ]
                )
        self.assertIn("does not exist", str(raised.exception))
        self.assertEqual(buffer.getvalue(), "")  # no contract was emitted

    def test_cli_requires_a_path_after_config(self):
        from public_flight_search.cli import main

        with self.assertRaises(SystemExit):
            main(["evidence-contract", "--config"])


class TestCatalogProvenance(unittest.TestCase):
    def test_contract_states_which_catalogue_produced_its_keys(self):
        # December prices WINTER_RESORT_CATALOG; July prices the summer
        # catalogue layered over it. The contract says which, so a hunt never
        # has to infer the list its target airports came from.
        from public_flight_search.holidays import (
            RESORT_CATALOG_NAME,
            SUMMER_RESORT_CATALOG_NAME,
        )

        for path, expected in (
            (DEC_CONFIG, RESORT_CATALOG_NAME),
            (JULY_CONFIG, SUMMER_RESORT_CATALOG_NAME),
        ):
            with self.subTest(config=path.name):
                contract = evidence_consumption_contract(_load(path))
                self.assertEqual(contract.catalog, expected)
                self.assertEqual(contract.as_dict()["catalog"], expected)

    def test_keys_come_from_the_catalogue_the_collector_reads(self):
        # Destinations with no catalogue entry have no card in either season,
        # so their airports must never appear as hunt targets. This is what
        # made MLA/DOH/MCT/FNC/AGA dead crawl targets in September 2026.
        from public_flight_search.holidays import (
            WINTER_RESORT_CATALOG,
            resort_catalog,
        )

        july = _load(JULY_CONFIG)
        december = _load(DEC_CONFIG)
        self.assertIs(resort_catalog(), WINTER_RESORT_CATALOG)
        self.assertIs(resort_catalog(december), WINTER_RESORT_CATALOG)
        for absent in ("malta", "taghazout"):
            self.assertNotIn(absent, resort_catalog(), absent)
            self.assertNotIn(absent, resort_catalog(july), absent)
        # Doha and Muscat are December destinations since 2026-09-30, priced
        # at December rates: they must never reach the July catalogue view.
        for december_only in ("doha", "muscat"):
            self.assertIn(december_only, resort_catalog(december), december_only)
            self.assertNotIn(december_only, resort_catalog(july), december_only)

        contract = evidence_consumption_contract(july)
        self.assertEqual(set(contract.airports), {"HKT", "LOP", "USM", "ZNZ"})
        for dead in ("MLA", "DOH", "AGA"):
            self.assertNotIn(dead, contract.airports, dead)

    def test_december_never_hunts_a_summer_resort_airport(self):
        # The December config lists phuket and krabi; if the July Thai
        # resorts shared a catalogue with December, its hunt would be aimed at
        # USM/HKT and its cards priced at July rates.
        contract = evidence_consumption_contract(_load(DEC_CONFIG))
        for summer_only in ("USM", "LOP", "HKT"):
            self.assertNotIn(summer_only, contract.airports, summer_only)


class TestAgeReferenceIsInjectedNotGuessed(unittest.TestCase):
    """The loader must measure age against ``now``, not the wall clock.

    Regression, found by review 2026-09-23: ``load_live_flight_evidence``
    accepted ``now`` and then did ``del now``, measuring every age against
    ``datetime.now()``. The equivalence tests inject a fixed ``observed_at``,
    so they passed while the wall clock was near it and would all have failed
    on 2026-09-26 — blocking every holiday report, since the workflow runs
    the suite before it builds. That is the same literal-date expiry class
    this module's sibling fix removed from ``trip_config``.
    """

    def _write(self, observed: str, config) -> str:
        contract = evidence_consumption_contract(config)
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False
        ) as handle:
            json.dump(
                {
                    "evidence": [
                        {
                            "airport": "AYT",
                            "cabin_class": "ECONOMY",
                            "basis": "whole_party_return_total",
                            "total_gbp": 1000.0,
                            "source_url": "https://example.invalid/hunt",
                            "observed_at": observed,
                            "travellers": contract.travellers,
                            "origin": contract.origin,
                            "exact_dates": {
                                "outbound": contract.outbound,
                                "return": contract.return_date,
                            },
                        }
                    ]
                },
                handle,
            )
            return handle.name

    def test_an_injected_now_decides_freshness_not_the_calendar(self):
        config = _load(DEC_CONFIG)
        # Long before today: the real clock can only ever call this stale.
        observed = "2020-01-01T00:00:00+00:00"
        path = self._write(observed, config)

        self.assertEqual(load_live_flight_evidence(config, path=path), {})
        loaded = load_live_flight_evidence(
            config, path=path, now=datetime.fromisoformat(observed)
        )
        self.assertIn(("AYT", "ECONOMY"), _airport_cabins(loaded))

    def test_a_fixed_fixture_stays_valid_years_later(self):
        # The equivalence fixture must not depend on the day it runs.
        config = _load(DEC_CONFIG)
        observed = OBSERVED_AT
        path = self._write(observed, config)
        loaded = load_live_flight_evidence(
            config, path=path, now=datetime.fromisoformat(observed)
        )
        self.assertEqual(_airport_cabins(loaded), {("AYT", "ECONOMY")})


class TestFutureDatedEvidenceIsConsistent(unittest.TestCase):
    """A record the loader rejects must not be reported as fresh."""

    def test_future_dated_observation_is_not_the_newest_fresh_record(self):
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False
        ) as handle:
            json.dump(
                {
                    "evidence": [
                        {"airport": "AYT", "observed_at": "2026-09-30T00:00:00+00:00"}
                    ]
                },
                handle,
            )
            path = handle.name
        fresh = evidence_freshness(path, now="2026-09-23T06:00:00+00:00")
        # Before: stale=False with age_hours -150, while the loader's own skip
        # log said "observed_at is in the future" for the same record.
        self.assertTrue(fresh["stale"])
        self.assertIsNone(fresh["newest_observed_at"])
        self.assertEqual(fresh["future_dated"], 1)
        self.assertEqual(fresh["record_count"], 1)

    def test_a_usable_record_wins_over_a_future_dated_one(self):
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False
        ) as handle:
            json.dump(
                {
                    "evidence": [
                        {"airport": "AYT", "observed_at": "2026-09-23T00:00:00+00:00"},
                        {"airport": "TFS", "observed_at": "2026-09-30T00:00:00+00:00"},
                    ]
                },
                handle,
            )
            path = handle.name
        fresh = evidence_freshness(path, now="2026-09-23T06:00:00+00:00")
        self.assertEqual(fresh["newest_observed_at"], "2026-09-23T00:00:00+00:00")
        self.assertEqual(fresh["future_dated"], 1)
        self.assertFalse(fresh["stale"])


class TestReportableCabinsAreOneSet(unittest.TestCase):
    """The loader gate and the renderable cabins must be one definition."""

    def test_evidence_cabins_is_the_shared_report_cabin_set(self):
        from public_flight_search.config import REPORT_CABINS
        from public_flight_search.live_verify import EVIDENCE_CABINS

        self.assertEqual(EVIDENCE_CABINS, REPORT_CABINS)

    def test_first_is_reportable_because_the_report_renders_it(self):
        # holidays.py renders a "🥇 First Class" badge and lists First in the
        # "other cabin options" table, so the loader excluding FIRST meant a
        # FIRST fare could be requested by the contract and rejected on load.
        from public_flight_search.live_verify import EVIDENCE_CABINS

        self.assertIn("FIRST", EVIDENCE_CABINS)

    def test_every_contract_cabin_can_actually_be_loaded(self):
        from public_flight_search.live_verify import EVIDENCE_CABINS

        for path in (DEC_CONFIG, JULY_CONFIG):
            with self.subTest(config=path.name):
                contract = evidence_consumption_contract(_load(path))
                cabins = {cabin for _, cabin in contract.keys}
                self.assertLessEqual(cabins, EVIDENCE_CABINS)

    def test_a_legacy_first_class_config_contract_is_loadable(self):
        # The divergence the set-unification prevents: the contract must never
        # ask for a cabin the evidence loader refuses. Since 2026-09-28 a
        # config's cabin fields are legacy — the cabin is derived from flight
        # hours — so a config that still says FIRST loads, its contract asks
        # for the derived cabin (Antalya, 4h30: ECONOMY), and evidence for
        # that cabin loads.
        config = load_holiday_config(
            SYNTHETIC.replace(
                '"destinations": [',
                '"cabin_classes": ["FIRST"],\n  "destinations": [',
            )
        )
        contract = evidence_consumption_contract(config)
        self.assertEqual({cabin for _, cabin in contract.keys}, {"ECONOMY"})

        observed = "2026-09-23T00:00:00+00:00"
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False
        ) as handle:
            json.dump(
                {
                    "evidence": [
                        {
                            "airport": "AYT",
                            "cabin_class": "ECONOMY",
                            "basis": "whole_party_return_total",
                            "total_gbp": 2000.0,
                            "source_url": "https://example.invalid/hunt",
                            "observed_at": observed,
                            "travellers": contract.travellers,
                            "origin": contract.origin,
                            "exact_dates": {
                                "outbound": contract.outbound,
                                "return": contract.return_date,
                            },
                        }
                    ]
                },
                handle,
            )
            path = handle.name
        loaded = load_live_flight_evidence(
            config, path=path, now=datetime.fromisoformat(observed)
        )
        self.assertIn(("AYT", "ECONOMY"), _airport_cabins(loaded))


class TestLiveEvidenceCountsAreLabelledHonestly(unittest.TestCase):
    """``live_flight_airports`` must count airports, not keys."""

    @staticmethod
    def _evidence(airport: str, cabin: str, *, stale: bool = False):
        from public_flight_search.live_verify import LiveFareEvidence

        return LiveFareEvidence(
            airport=airport,
            total_gbp=1000.0,
            basis="whole_party_return_total",
            source_url="https://example.invalid/search",
            observed_at="2026-09-21T00:00:00+00:00",
            cabin_class=cabin,
            stale=stale,
        )

    def test_one_airport_with_three_cabins_is_one_airport(self):
        from public_flight_search.jobs import _live_evidence_counts

        counts = _live_evidence_counts(
            {
                ("AYT", "ECONOMY"): self._evidence("AYT", "ECONOMY"),
                ("AYT", "PREMIUM_ECONOMY"): self._evidence("AYT", "PREMIUM_ECONOMY"),
                ("AYT", "BUSINESS"): self._evidence("AYT", "BUSINESS"),
            }
        )
        # Before: len(mapping) == 3, so one airport reported as three.
        self.assertEqual(counts["live_flight_airports"], 1)
        self.assertEqual(counts["live_flight_cabins"], 3)
        self.assertEqual(counts["stale_flight_fares"], 0)

    def test_a_stale_fare_is_never_counted_as_live_coverage(self):
        """``live_flight_*`` has to keep meaning live. An aged fare is consumed —
        it prices the card — so counting it here would overstate live coverage,
        which is the class of claim this module exists to keep honest."""
        from public_flight_search.jobs import _live_evidence_counts

        counts = _live_evidence_counts(
            {
                ("AYT", "ECONOMY"): self._evidence("AYT", "ECONOMY"),
                ("LPA", "ECONOMY"): self._evidence("LPA", "ECONOMY", stale=True),
            }
        )
        self.assertEqual(counts["live_flight_airports"], 1)
        self.assertEqual(counts["live_flight_cabins"], 1)
        self.assertEqual(counts["stale_flight_fares"], 1)
        self.assertEqual(counts["stale_flight_airports"], 1)

    def test_empty_evidence_counts_zero(self):
        from public_flight_search.jobs import _live_evidence_counts

        self.assertEqual(
            _live_evidence_counts({}),
            {
                "live_flight_airports": 0,
                "live_flight_cabins": 0,
                "stale_flight_fares": 0,
                "stale_flight_airports": 0,
            },
        )


if __name__ == "__main__":
    unittest.main()
