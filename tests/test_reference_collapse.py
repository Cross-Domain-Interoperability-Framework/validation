"""collapse_reference_slots must not throw descriptions away.

Framing embeds the whole target under a reference-only key (schema:result,
cdif:qualifies, ...). It used to be collapsed to a bare {@id} unconditionally,
on the premise that the node is described elsewhere. An activity's schema:result
is often the only place its output is described, so those triples never reached
the schema. Now a copy is collapsed only if an equally complete copy survives.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from FrameAndValidate import collapse_reference_slots  # noqa: E402

OUT = {"@id": "#out", "@type": ["schema:Dataset"], "schema:name": "Output"}


class CollapseReferenceSlots(unittest.TestCase):
    def test_only_description_is_kept_inline(self):
        doc = {"@id": "#root", "prov:wasGeneratedBy": [{"schema:result": dict(OUT)}]}
        out = collapse_reference_slots(doc)
        self.assertEqual(out["prov:wasGeneratedBy"][0]["schema:result"], OUT)

    def test_described_elsewhere_is_collapsed(self):
        doc = {"@id": "#root", "schema:hasPart": [dict(OUT)],
               "prov:wasGeneratedBy": [{"schema:result": [dict(OUT)]}]}
        out = collapse_reference_slots(doc)
        self.assertEqual(out["prov:wasGeneratedBy"][0]["schema:result"], [{"@id": "#out"}])
        self.assertEqual(out["schema:hasPart"], [OUT])

    def test_second_reference_copy_collapses_against_first(self):
        doc = {"@id": "#root", "prov:wasGeneratedBy": [
            {"schema:result": dict(OUT)}, {"schema:result": dict(OUT)}]}
        out = collapse_reference_slots(doc)
        self.assertEqual(out["prov:wasGeneratedBy"][0]["schema:result"], OUT)
        self.assertEqual(out["prov:wasGeneratedBy"][1]["schema:result"], {"@id": "#out"})

    def test_less_complete_copy_elsewhere_does_not_count(self):
        doc = {"@id": "#root", "schema:hasPart": [{"@id": "#out", "@type": ["schema:Dataset"]}],
               "prov:wasGeneratedBy": [{"schema:result": dict(OUT)}]}
        out = collapse_reference_slots(doc)
        self.assertEqual(out["prov:wasGeneratedBy"][0]["schema:result"], OUT)

    def test_reference_to_root_is_collapsed(self):
        doc = {"@id": "#root", "schema:name": "Root",
               "schema:subjectOf": {"@id": "#rec", "schema:about": {"@id": "#root", "schema:name": "Root"}}}
        out = collapse_reference_slots(doc)
        self.assertEqual(out["schema:subjectOf"]["schema:about"], {"@id": "#root"})


if __name__ == "__main__":
    unittest.main()
