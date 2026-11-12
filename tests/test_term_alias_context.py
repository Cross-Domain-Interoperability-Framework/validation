"""Tests that a document's term aliases do not leak into the framed output.

A JSON-LD document may define short term aliases in its @context, for example
"prefLabel": "skos:prefLabel" (CDIF_Activities.json, the CDIF provenance activity
vocabulary, does). That is valid JSON-LD: the RDF is the same as writing
skos:prefLabel. frame_cdif() merges the document's context into a custom frame's
context so domain prefixes compact. Until 2026-11 it copied EVERY string-valued
entry, aliases included, so compaction wrote "prefLabel" back out and the
StructuredSchemas, which require the literal key "skos:prefLabel", rejected the
document. Only prefixes (an IRI ending in a JSON-LD gen-delim) are copied now.

Needs pyld; skipped if it is unavailable.
"""

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import FrameAndValidate as FV  # noqa: E402

try:
    import pyld  # noqa: F401
    HAVE_PYLD = True
except ImportError:
    HAVE_PYLD = False

SKOS = "http://www.w3.org/2004/02/skos/core#"
EX = "https://example.org/vocab/"

FRAME = {
    "@context": {"skos": SKOS},
    "@type": "skos:ConceptScheme",
    "@embed": "@always",
}


def _doc():
    return {
        "@context": {
            "skos": SKOS,
            "ex": EX,
            "prefLabel": "skos:prefLabel",
            "definition": {"@id": "skos:definition"},
            "hasTopConcept": {"@id": "skos:hasTopConcept", "@type": "@id"},
        },
        "@graph": [
            {"@id": "ex:scheme", "@type": "skos:ConceptScheme",
             "prefLabel": {"@value": "A scheme", "@language": "en"},
             "hasTopConcept": "ex:a"},
            {"@id": "ex:a", "@type": "skos:Concept",
             "prefLabel": {"@value": "A", "@language": "en"}},
        ],
    }


@unittest.skipUnless(HAVE_PYLD, "pyld not installed")
class TermAliasContextTest(unittest.TestCase):

    def test_alias_not_copied_into_output(self):
        out = FV.frame_cdif(_doc(), FRAME)
        self.assertIn("skos:prefLabel", out)
        self.assertNotIn("prefLabel", out)
        self.assertNotIn("prefLabel", out.get("@context", {}))

    def test_prefix_still_copied(self):
        out = FV.frame_cdif(_doc(), FRAME)
        # The document's own namespace prefix is still available for compaction.
        self.assertEqual(out.get("@context", {}).get("ex"), EX)
        self.assertEqual(out["@id"], "ex:scheme")

    def test_gen_delims(self):
        for iri in ("https://example.org/", "http://example.org/ns#", "urn:x:"):
            self.assertTrue(iri.endswith(FV.GEN_DELIMS), iri)
        for alias in ("skos:prefLabel", "http://schema.org/name"):
            self.assertFalse(alias.endswith(FV.GEN_DELIMS), alias)


if __name__ == "__main__":
    unittest.main()
