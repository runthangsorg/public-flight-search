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

from pathlib import Path
import json
import tempfile
import unittest

from public_flight_search.holidays import (
    _date_pairs,
    _shortlist_pairs,
    collect_holiday_deals,
    load_holiday_config,
)
from public_flight_search.live_verify import (
    _target_date_pair,
    evidence_consumption_contract,
    evidence_contract_gaps,
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


def _load(path: Path):
    return load_holiday_config(path.read_text(encoding="utf-8"))


class TestPricedPairIsTheSingleSourceOfTruth(unittest.TestCase):
    def test_contract_priced_pair_is_the_shortlist_middle(self):
        config = load_holiday_config(SYNTHETIC)
        contract = evidence_consumption_contract(config)
        expected = _shortlist_pairs(_date_pairs(config))[1]
        self.assertEqual((contract.outbound, contract.return_date), expected)

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

    #: A fixed instant the loader will accept: not in the future, not stale.
    OBSERVED_AT = "2026-09-23T00:00:00+00:00"

    def _write_evidence(self, entries: list[dict]) -> str:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False
        ) as handle:
            json.dump({"evidence": entries}, handle)
            return handle.name

    def _verified_keys(self, config) -> set[tuple[str, str]]:
        contract = evidence_consumption_contract(config)
        path = self._write_evidence(
            [
                {
                    "airport": airport,
                    "cabin_class": cabin,
                    "basis": "whole_party_return_total",
                    "total_gbp": 1000.0,
                    "source_url": "https://example.invalid/hunt",
                    "observed_at": self.OBSERVED_AT,
                    "travellers": contract.travellers,
                    "origin": contract.origin,
                    "exact_dates": {
                        "outbound": contract.outbound,
                        "return": contract.return_date,
                    },
                }
                for airport, cabin in contract.keys
            ]
        )
        loaded = load_live_flight_evidence(config, path=path)
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
    def test_december_prices_the_middle_pair_from_lhr(self):
        contract = evidence_consumption_contract(_load(DEC_CONFIG))
        self.assertEqual(
            (contract.outbound, contract.return_date),
            ("2026-12-22", "2026-12-30"),
        )
        self.assertEqual(contract.origin, "LHR")
        self.assertEqual(contract.travellers, 5)
        self.assertEqual(list(contract.hunt_date_pairs), [("2026-12-22", "2026-12-30")])

    def test_december_contract_lists_only_airports_that_have_cards(self):
        contract = evidence_consumption_contract(_load(DEC_CONFIG))
        # Airports the hunt crawled in September 2026 that have no card at
        # all: hunting them can never price anything.
        for dead in ("AGA", "CAI", "DOH", "FNC", "MCT", "MLA"):
            self.assertNotIn(dead, contract.airports, dead)
        # Card-bearing airports, including the two that were never hunted.
        for live in ("ACE", "AYT", "FUE", "HRG", "LPA", "PFO", "TFS"):
            self.assertIn(live, contract.airports, live)

    def test_july_contract_is_business_led_on_the_priced_pair(self):
        contract = evidence_consumption_contract(_load(JULY_CONFIG))
        self.assertEqual(
            (contract.outbound, contract.return_date),
            ("2027-07-20", "2027-07-27"),
        )
        self.assertEqual(set(contract.airports), {"AYT", "HRG", "PFO", "TFS"})
        self.assertEqual({cabin for _, cabin in contract.keys}, {"BUSINESS"})

    def test_contract_serializes_for_the_hunt(self):
        contract = evidence_consumption_contract(_load(JULY_CONFIG))
        payload = contract.as_dict()
        self.assertEqual(
            payload["hunt_date_pairs"], [["2027-07-20", "2027-07-27"]]
        )
        self.assertEqual(payload["origin"], "LHR")
        self.assertIn("AYT/BUSINESS", payload["keys"])
        # The hunt reuses the report's own config, so only the four things it
        # currently gets wrong are overridden.
        self.assertEqual(
            set(contract.hunt_config_overrides()),
            {"origins", "date_pairs", "cabin_classes", "airports"},
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
                            "observed_at": "2026-09-23T00:00:00+00:00",
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
        loaded = load_live_flight_evidence(config, path=path)
        gaps = evidence_contract_gaps(config, loaded)
        self.assertNotIn("AYT/ECONOMY", gaps["missing"])
        self.assertIn("ACE/ECONOMY", gaps["missing"])
        self.assertIn("PFO/BUSINESS", gaps["missing"])

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
        self.assertEqual(payload["date_pairs"], [["2027-07-20", "2027-07-27"]])
        self.assertEqual(payload["origins"], ["LHR"])
        self.assertEqual(payload["airports"], ["AYT", "HRG", "PFO", "TFS"])

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
        # The July report prices from a constant named WINTER_RESORT_CATALOG.
        # That is surprising enough that the contract states it rather than
        # leaving a hunt to infer it.
        from public_flight_search.holidays import RESORT_CATALOG_NAME

        for path in (DEC_CONFIG, JULY_CONFIG):
            with self.subTest(config=path.name):
                contract = evidence_consumption_contract(_load(path))
                self.assertEqual(contract.catalog, RESORT_CATALOG_NAME)
                self.assertEqual(contract.as_dict()["catalog"], RESORT_CATALOG_NAME)

    def test_keys_come_from_the_catalogue_the_collector_reads(self):
        # Destinations with no catalogue entry have no card in either season,
        # so their airports must never appear as hunt targets. This is what
        # made MLA/DOH/MCT/FNC/AGA dead crawl targets in September 2026.
        from public_flight_search.holidays import (
            WINTER_RESORT_CATALOG,
            resort_catalog,
        )

        self.assertIs(resort_catalog(), WINTER_RESORT_CATALOG)
        for absent in ("malta", "taghazout", "doha", "muscat"):
            self.assertNotIn(absent, resort_catalog(), absent)

        contract = evidence_consumption_contract(_load(JULY_CONFIG))
        self.assertEqual(set(contract.airports), {"AYT", "HRG", "PFO", "TFS"})
        for dead in ("MLA", "DOH", "MCT", "AGA"):
            self.assertNotIn(dead, contract.airports, dead)


if __name__ == "__main__":
    unittest.main()
