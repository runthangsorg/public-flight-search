"""T9: no season offers a Singapore or Malaysia destination.

Owner decision 2026-10-02: "dont include singapore, malaysia or langkawi" was a
July instruction; the same scope now applies to December. Langkawi, Penang and
Singapore are removed from the December config, and no Singapore/Malaysia
destination survives in either season's config or the catalogue either resolves
to. Routing via a Singapore or Kuala Lumpur airport is still fine — only
destinations are excluded.
"""

from __future__ import annotations

from pathlib import Path
import unittest

from public_flight_search.holidays import (
    WINTER_RESORT_CATALOG,
    load_holiday_config,
    resort_catalog,
)

ROOT = Path(__file__).parents[1]
CONFIGS = {
    "july": ROOT / "examples" / "july_holiday_config.json",
    "december": ROOT / "examples" / "dec_holiday_config.json",
}

#: Destination keys that are Singapore or Malaysia. Kota Kinabalu is Sabah,
#: Malaysia — it left with the rest of the country.
BANNED_KEYS = {"singapore", "langkawi", "penang", "kota_kinabalu", "kuala_lumpur"}
BANNED_AIRPORTS = {"SIN", "LGK", "PEN", "BKI", "KUL"}


class NoSingaporeOrMalaysiaTests(unittest.TestCase):
    def test_no_config_offers_a_singapore_or_malaysia_destination(self):
        for name, path in CONFIGS.items():
            config = load_holiday_config(path.read_text(encoding="utf-8"))
            for dest in config.destinations:
                with self.subTest(season=name, dest=dest.key):
                    self.assertNotIn(dest.key, BANNED_KEYS)
                    self.assertFalse(set(dest.airports) & BANNED_AIRPORTS, dest.airports)

    def test_no_catalogue_resorts_a_singapore_or_malaysia_destination(self):
        for name, path in CONFIGS.items():
            config = load_holiday_config(path.read_text(encoding="utf-8"))
            catalog = resort_catalog(config)
            for key in catalog:
                with self.subTest(season=name, key=key):
                    self.assertNotIn(key, BANNED_KEYS)

    def test_the_winter_catalogue_has_no_singapore_or_malaysia_key(self):
        for key in WINTER_RESORT_CATALOG:
            with self.subTest(key=key):
                self.assertNotIn(key, BANNED_KEYS)


if __name__ == "__main__":
    unittest.main()
