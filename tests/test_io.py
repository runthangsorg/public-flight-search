import json
import tempfile
import unittest
from pathlib import Path

from public_flight_search.io import SourceError, load_json_source


class SourceTests(unittest.TestCase):
    def test_loads_a_bounded_local_json_list(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "offers.json"
            source.write_text(json.dumps([{"provider": "sample"}]), encoding="utf-8")
            self.assertEqual(load_json_source(str(source)), [{"provider": "sample"}])

    def test_rejects_unsupported_schemes_before_opening(self):
        with self.assertRaises(SourceError):
            load_json_source("ftp://example.test/offers.json")

    def test_rejects_oversized_local_source(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "offers.json"
            source.write_bytes(b"x" * 33)
            with self.assertRaises(SourceError):
                load_json_source(str(source), max_bytes=32)


if __name__ == "__main__":
    unittest.main()
