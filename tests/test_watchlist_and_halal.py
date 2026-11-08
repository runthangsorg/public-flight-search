"""The watchlist names Gili and Maldives properties without pricing them, and halal is shown only from a source
(owner, 8 Nov 2026: "prefer halal restaurants and hotels"; "look more into gili, and maldives options too (that must
include water aeroplane)")."""

from __future__ import annotations

import unittest

from public_flight_search import watchlist


class WatchlistTests(unittest.TestCase):
    def setUp(self):
        self.entries = watchlist.load_watchlist()

    def test_it_holds_gili_and_maldives_options(self):
        areas = " ".join(e.area for e in self.entries)
        for island in ("Gili Trawangan", "Gili Meno", "Gili Air", "Maldives"):
            self.assertIn(island, areas)

    def test_every_entry_points_at_the_propertys_own_page_and_carries_no_price(self):
        for e in self.entries:
            self.assertTrue(e.url.startswith("https://"), e.name)
        import json
        raw = json.loads(watchlist.DATA_PATH.read_text(encoding="utf-8"))
        for item in raw["entries"]:
            self.assertFalse({"price", "price_gbp", "rate", "total_gbp", "from_gbp"} & set(item), item["name"])

    def test_a_maldives_resort_is_flagged_as_needing_the_seaplane(self):
        maldives = [e for e in self.entries if "Maldives" in e.area]
        self.assertGreaterEqual(len(maldives), 3)
        self.assertTrue(all(e.seaplane_required for e in maldives))

    def test_halal_is_known_only_where_the_propertys_own_page_was_quoted(self):
        fact = watchlist.halal_fact("Vila Ombak")
        self.assertIsNotNone(fact)
        self.assertEqual(fact.tag, "halal food on site")
        self.assertTrue(fact.source_url.startswith("https://"))
        self.assertIsNone(watchlist.halal_fact("Pondok Santi Estate"), "no source, no tag")
        self.assertIsNone(watchlist.halal_fact("Angsana Velavaru"))
        self.assertIsNone(watchlist.halal_fact(""))

    def test_a_halal_block_with_no_source_is_ignored(self):
        import json, tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "w.json"
            path.write_text(json.dumps({"entries": [{"name": "X", "halal": {"tag": "halal", "source_url": ""}}]}))
            self.assertIsNone(watchlist.load_watchlist(path)[0].halal)


if __name__ == "__main__":
    unittest.main()
