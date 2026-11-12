"""Framing must not hand an anonymous node an @id the schema then accepts.

pyld labels every node it frames, so an inline prov:used entity the source left
without @id came out as {"@id": "_:b22", ...} and passed the core rule that a
prov:used object must carry @id. frame_cdif now drops a blank-node label that
occurs only once (it links nothing); labels used more than once are references
and stay.

Skipped if pyld is unavailable.
"""

import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

try:
    import FrameAndValidate as FV
    HAVE_PYLD = True
except ImportError:
    HAVE_PYLD = False

FRAME = json.loads((REPO / "CDIF-frame-2026.jsonld").read_text(encoding="utf-8"))
CTX = {"schema": "http://schema.org/", "prov": "http://www.w3.org/ns/prov#",
       "dcterms": "http://purl.org/dc/terms/"}


def used_items(framed):
    acts = framed.get("prov:wasGeneratedBy", [])
    acts = acts if isinstance(acts, list) else [acts]
    items = []
    for a in acts:
        u = a.get("prov:used", [])
        items.extend(u if isinstance(u, list) else [u])
    return items


@unittest.skipUnless(HAVE_PYLD, "pyld not installed")
class BlankNodeIdTest(unittest.TestCase):
    def frame(self, used):
        # The catalog record is itself a schema:Dataset whose schema:about points
        # back at the record, as in ADA records. Both match the frame, so pyld
        # frames the dataset (and its prov:used node) twice, sees the label used
        # twice and keeps it; once the main entity is picked it occurs only once.
        doc = {"@context": CTX, "@id": "https://example.org/dataset",
               "@type": ["schema:Dataset"], "schema:name": "Example",
               "prov:wasGeneratedBy": [{"@type": ["schema:Action", "prov:Activity"],
                                        "prov:used": used}],
               "schema:subjectOf": {"@id": "https://example.org/record",
                                    "@type": ["schema:Dataset"],
                                    "schema:about": {"@id": "https://example.org/dataset"}}}
        return FV.frame_cdif(doc, FRAME)

    def test_anonymous_entity_gets_no_id(self):
        items = used_items(self.frame([{"@type": ["prov:Entity"], "schema:name": "An instrument"}]))
        self.assertEqual(len(items), 1)
        self.assertNotIn("@id", items[0])

    def test_real_id_is_kept(self):
        items = used_items(self.frame([{"@id": "https://example.org/thing", "schema:name": "A thing"}]))
        self.assertEqual(items[0].get("@id"), "https://example.org/thing")

    def test_shared_blank_node_keeps_its_label(self):
        # The same source blank node referenced twice: the label links the two
        # occurrences, so both must keep it.
        out = json.dumps(FV.prune_unreferenced_blank_ids(
            {"a": {"@id": "_:x", "schema:name": "n"}, "b": {"@id": "_:x"}, "c": {"@id": "_:y"}}))
        self.assertEqual(out.count('"_:x"'), 2)
        self.assertNotIn('"_:y"', out)


if __name__ == "__main__":
    unittest.main()
