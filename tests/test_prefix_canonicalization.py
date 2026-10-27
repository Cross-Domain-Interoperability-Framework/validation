"""Tests for namespace-prefix canonicalization (FrameAndValidate).

A CDIF record may alias a standard namespace under a non-canonical prefix --
most notably `dct:` instead of `dcterms:` for Dublin Core Terms. The framed-tree
JSON Schemas and ConformanceValidate's conformsTo discovery match LITERAL
prefixed keys, so `dct:conformsTo` reads as a missing `dcterms:conformsTo` even
though the RDF is identical (SHACL, which works on expanded IRIs, passes it).
`canonicalize_cdif_prefixes()` rewrites such aliases to the canonical prefix so
the pipeline is agnostic to which alias the source used.

Self-contained: stdlib unittest, no third-party deps for the unit tests; the one
end-to-end test needs pyld + the repo's CDIF-frame-2026.jsonld and is skipped if
pyld is unavailable.
"""

import copy
import json
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import FrameAndValidate as FV  # noqa: E402

DCTERMS = "http://purl.org/dc/terms/"
SCHEMA = "http://schema.org/"
CORE = "https://w3id.org/cdif/core/1.1"


def _catalog_doc(dc_prefix, extra_ctx=None):
    """A minimal Dataset + catalog-record doc whose Dublin Core prefix is
    `dc_prefix` (so the conformsTo key is `<dc_prefix>:conformsTo`)."""
    ctx = {
        "schema": SCHEMA,
        "dcat": "http://www.w3.org/ns/dcat#",
        dc_prefix: DCTERMS,
    }
    if extra_ctx:
        ctx.update(extra_ctx)
    return {
        "@context": ctx,
        "@type": ["schema:Dataset"],
        "@id": "https://ex.org/ds1",
        "schema:name": "example",
        "schema:subjectOf": {
            "@id": "https://ex.org/ds1/meta",
            "@type": ["schema:Dataset"],
            "schema:additionalType": [{"@id": "dcat:CatalogRecord"}],
            "schema:about": {"@id": "https://ex.org/ds1"},
            f"{dc_prefix}:conformsTo": [{"@id": CORE}],
        },
    }


class CanonicalizePrefixes(unittest.TestCase):
    def test_dct_only_rewritten_to_dcterms(self):
        doc = _catalog_doc("dct")
        out = FV.canonicalize_cdif_prefixes(doc)
        ctx = out["@context"]
        self.assertIn("dcterms", ctx)
        self.assertNotIn("dct", ctx)
        self.assertEqual(ctx["dcterms"], DCTERMS)
        so = out["schema:subjectOf"]
        self.assertIn("dcterms:conformsTo", so)
        self.assertNotIn("dct:conformsTo", so)
        self.assertEqual(so["dcterms:conformsTo"], [{"@id": CORE}])

    def test_dct_and_dcterms_collapse_to_dcterms(self):
        doc = _catalog_doc("dct", extra_ctx={"dcterms": DCTERMS})
        out = FV.canonicalize_cdif_prefixes(doc)
        ctx = out["@context"]
        self.assertIn("dcterms", ctx)
        self.assertNotIn("dct", ctx)
        self.assertIn("dcterms:conformsTo", out["schema:subjectOf"])

    def test_dcterms_only_is_unchanged(self):
        doc = _catalog_doc("dcterms")
        out = FV.canonicalize_cdif_prefixes(doc)
        # No rename needed -> same object returned (identity), untouched content.
        self.assertIs(out, doc)
        self.assertIn("dcterms:conformsTo", out["schema:subjectOf"])

    def test_extension_prefix_untouched(self):
        # `cr:` (Croissant) is not a canonical CDIF namespace -> left alone.
        doc = {
            "@context": {"schema": SCHEMA, "cr": "http://mlcommons.org/croissant/"},
            "@type": ["schema:Dataset"],
            "cr:something": "x",
        }
        out = FV.canonicalize_cdif_prefixes(doc)
        self.assertIs(out, doc)
        self.assertIn("cr", out["@context"])
        self.assertIn("cr:something", out)

    def test_https_schema_variant_untouched(self):
        # https://schema.org/ is a DIFFERENT IRI than the canonical http form;
        # canonicalization must NOT rewrite it (that is the SOSO lint's job).
        doc = {
            "@context": {"sc": "https://schema.org/"},
            "@type": ["sc:Dataset"],
            "sc:name": "x",
        }
        out = FV.canonicalize_cdif_prefixes(doc)
        self.assertIs(out, doc)
        self.assertIn("sc:name", out)

    def test_sdo_alias_for_schema_rewritten(self):
        # A non-canonical alias for the canonical http schema.org IRI IS rewritten.
        doc = {
            "@context": {"sdo": SCHEMA},
            "@type": ["sdo:Dataset"],
            "sdo:name": "x",
        }
        out = FV.canonicalize_cdif_prefixes(doc)
        self.assertIn("schema", out["@context"])
        self.assertNotIn("sdo", out["@context"])
        self.assertIn("schema:name", out)
        self.assertEqual(out["@type"], ["schema:Dataset"])

    def test_full_iri_id_values_preserved(self):
        doc = _catalog_doc("dct")
        out = FV.canonicalize_cdif_prefixes(doc)
        # @id full IRIs are not CURIEs and must be untouched.
        self.assertEqual(out["@id"], "https://ex.org/ds1")
        self.assertEqual(
            out["schema:subjectOf"]["dcterms:conformsTo"], [{"@id": CORE}]
        )

    def test_type_curie_rewritten(self):
        doc = {
            "@context": {"dct": DCTERMS},
            "@type": ["dct:Standard"],
            "@id": "https://ex.org/x",
        }
        out = FV.canonicalize_cdif_prefixes(doc)
        self.assertEqual(out["@type"], ["dcterms:Standard"])

    def test_input_not_mutated(self):
        doc = _catalog_doc("dct")
        before = copy.deepcopy(doc)
        FV.canonicalize_cdif_prefixes(doc)
        self.assertEqual(doc, before)

    def test_non_dict_context_returned_unchanged(self):
        doc = {"@context": "https://example.org/context.jsonld", "dct:x": 1}
        self.assertIs(FV.canonicalize_cdif_prefixes(doc), doc)

    def test_nested_context_left_alone(self):
        # Only the top-level @context drives renaming; a nested @context is
        # passed through unchanged.
        nested = {"foo": DCTERMS}
        doc = {
            "@context": {"schema": SCHEMA, "dct": DCTERMS},
            "@type": ["schema:Dataset"],
            "schema:subjectOf": {"@context": nested, "dct:conformsTo": [{"@id": CORE}]},
        }
        out = FV.canonicalize_cdif_prefixes(doc)
        self.assertEqual(out["schema:subjectOf"]["@context"], nested)
        # the key still gets swapped (top-level rename applies everywhere)
        self.assertIn("dcterms:conformsTo", out["schema:subjectOf"])


@unittest.skipUnless(
    (REPO / "CDIF-frame-2026.jsonld").exists(), "CDIF frame not present"
)
class FrameEndToEnd(unittest.TestCase):
    """A dct-only record must frame with dcterms:conformsTo on the catalog
    record -- the exact failure that motivated this (SlavaAIStudioCDIF.json)."""

    def test_dct_only_frames_to_dcterms_conformsto(self):
        try:
            import pyld  # noqa: F401
        except ImportError:
            self.skipTest("pyld not installed")
        frame = json.loads(
            (REPO / "CDIF-frame-2026.jsonld").read_text(encoding="utf-8")
        )
        framed = FV.frame_cdif(_catalog_doc("dct"), frame)
        blob = json.dumps(framed)
        self.assertNotIn("dct:conformsTo", blob)
        so = framed.get("schema:subjectOf")
        so = so[0] if isinstance(so, list) else so
        self.assertIsInstance(so, dict)
        self.assertIn("dcterms:conformsTo", so)


if __name__ == "__main__":
    unittest.main()
