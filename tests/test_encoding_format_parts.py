"""Tests for schema:encodingFormat on manifest parts (FrameAndValidate).

Framing collapses a one-element array to a scalar. The manifest types a
schema:hasPart item's schema:encodingFormat as an array, and the wrap used to
fire only on DataDownload and MediaObject nodes, so an untyped part (as NIAID
records give them) kept the string and failed. An EntryPoint keeps the string,
which is what its schema wants.
"""

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from FrameAndValidate import remove_nulls_and_normalize


class EncodingFormatOnParts(unittest.TestCase):
    def test_untyped_part_is_wrapped(self):
        out = remove_nulls_and_normalize({"schema:hasPart": [{
            "schema:name": "Codebook.pdf",
            "schema:url": "https://example.org/codebook.pdf",
            "schema:encodingFormat": "application/pdf",
        }]})
        self.assertEqual(out["schema:hasPart"][0]["schema:encodingFormat"], ["application/pdf"])

    def test_typed_file_still_wrapped(self):
        out = remove_nulls_and_normalize({"schema:distribution": {
            "@type": "schema:DataDownload", "schema:encodingFormat": "text/csv"}})
        dist = out["schema:distribution"]
        dist = dist[0] if isinstance(dist, list) else dist
        self.assertEqual(dist["schema:encodingFormat"], ["text/csv"])

    def test_entry_point_keeps_the_string(self):
        out = remove_nulls_and_normalize({"schema:relatedLink": [{
            "schema:target": {"@type": ["schema:EntryPoint"],
                              "schema:encodingFormat": ["application/json"]}}]})
        self.assertEqual(out["schema:relatedLink"][0]["schema:target"]["schema:encodingFormat"],
                         "application/json")


if __name__ == "__main__":
    unittest.main()
