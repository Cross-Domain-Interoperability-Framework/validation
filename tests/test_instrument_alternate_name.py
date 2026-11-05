"""Tests for schema:alternateName on instruments (FrameAndValidate).

Framing collapses a one-element array to a scalar, and the instrument schema types
schema:alternateName as an array on the instrument and on its schema:hasPart
components, so remove_nulls_and_normalize() has to wrap it back. A Person or
Organization keeps the string, and so does a manifest part, which is not a
schema:Thing.
"""

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

from FrameAndValidate import remove_nulls_and_normalize


class InstrumentAlternateName(unittest.TestCase):
    def test_instrument_and_components_are_wrapped(self):
        out = remove_nulls_and_normalize({"schema:instrument": {
            "@type": ["schema:Product", "schema:Thing"],
            "schema:name": "ICP-MS",
            "schema:alternateName": "iCAP RQ",
            "schema:hasPart": [{
                "@type": ["schema:Thing"],
                "schema:name": "Autosampler",
                "schema:alternateName": "ASX-560",
            }],
        }})
        instrument = out["schema:instrument"]
        if isinstance(instrument, list):
            instrument = instrument[0]
        self.assertEqual(instrument["schema:alternateName"], ["iCAP RQ"])
        self.assertEqual(instrument["schema:hasPart"][0]["schema:alternateName"], ["ASX-560"])

    def test_agent_and_manifest_part_keep_the_string(self):
        out = remove_nulls_and_normalize({
            "schema:publisher": {"@type": ["schema:Organization"], "schema:alternateName": "EX"},
            "schema:hasPart": [{"@type": ["schema:MediaObject"], "schema:alternateName": "part.csv"}],
        })
        self.assertEqual(out["schema:publisher"]["schema:alternateName"], "EX")
        self.assertEqual(out["schema:hasPart"][0]["schema:alternateName"], "part.csv")


if __name__ == "__main__":
    unittest.main()
