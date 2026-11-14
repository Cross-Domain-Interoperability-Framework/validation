"""Tests for main-entity selection in a framed @graph (FrameAndValidate).

When a record's root and one of its schema:hasPart members are both typed
schema:Dataset, framing hoists both to the @graph. The picker must still choose
the record's root -- the node carrying a schema:subjectOf catalog record -- and
never a part. Before the fix (CDIF-validation issue #20) a part that sorted
first and carried a schema:url won the url heuristic, so run_conformance
validated the part and a correct record failed core.

Self-contained: stdlib unittest, no third-party deps. The picker operates on an
already-framed @graph (plain dicts), so no pyld is needed.
"""

import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import FrameAndValidate as FV  # noqa: E402

DCAT_IRI = "http://www.w3.org/ns/dcat#CatalogRecord"
FRAME = {"@type": "schema:Dataset"}


def _catalog_record(rid, about):
    return {
        "@id": rid,
        "@type": "schema:Dataset",
        "schema:additionalType": {"@id": DCAT_IRI},
        "schema:about": {"@id": about},
    }


class IsCatalogRecord(unittest.TestCase):
    def test_compact_string(self):
        self.assertTrue(FV._is_catalog_record(
            {"schema:additionalType": "dcat:CatalogRecord"}))

    def test_compact_string_in_list(self):
        self.assertTrue(FV._is_catalog_record(
            {"schema:additionalType": ["dcat:CatalogRecord"]}))

    def test_id_object_full_iri(self):
        # The IRI-lint normalization emits the {@id} full-IRI form; matching only
        # the compact string let this through as an ordinary candidate (issue #20).
        self.assertTrue(FV._is_catalog_record(
            {"schema:additionalType": {"@id": DCAT_IRI}}))

    def test_id_object_compact(self):
        self.assertTrue(FV._is_catalog_record(
            {"schema:additionalType": {"@id": "dcat:CatalogRecord"}}))

    def test_free_label_is_not_catalog_record(self):
        self.assertFalse(FV._is_catalog_record(
            {"schema:additionalType": "EC Bundled Object"}))

    def test_absent_additional_type(self):
        self.assertFalse(FV._is_catalog_record({"@type": "schema:Dataset"}))


class HasCatalogRecordSubjectOf(unittest.TestCase):
    def test_subjectof_catalog_record(self):
        node = {"schema:subjectOf": _catalog_record("urn:rec", "urn:ds")}
        self.assertTrue(FV._has_catalog_record_subjectof(node))

    def test_bare_subjectof_without_catalog_record(self):
        # subjectOf pointing at something that is not a catalog record does not
        # mark the root.
        node = {"schema:subjectOf": {"@id": "urn:article",
                                     "@type": "schema:CreativeWork"}}
        self.assertFalse(FV._has_catalog_record_subjectof(node))

    def test_no_subjectof(self):
        self.assertFalse(FV._has_catalog_record_subjectof(
            {"@type": "schema:Dataset"}))


class PickMainEntity(unittest.TestCase):
    def test_root_chosen_over_haspart_dataset(self):
        # The exact issue #20 shape: root is [CreativeWork, Product, Dataset]
        # with a subjectOf catalog record and a Dataset part; the part sorts
        # first and carries a url. The root must win.
        part = {"@id": "_:b11", "@type": "schema:Dataset",
                "schema:url": "https://ex.org/standards/bhvo2"}
        root = {
            "@id": "ark:/collection",
            "@type": ["schema:CreativeWork", "schema:Product", "schema:Dataset"],
            "schema:url": "ark:/collection",
            "schema:hasPart": [{"@id": "_:b11"}],
            "schema:subjectOf": _catalog_record("urn:rec", "ark:/collection"),
        }
        catrec = _catalog_record("urn:rec", "ark:/collection")
        graph = [part, root, catrec]
        picked = FV.pick_main_entity(graph, FRAME)
        self.assertEqual(picked.get("@id"), "ark:/collection")

    def test_id_form_catalog_record_excluded(self):
        # A catalog record whose additionalType is the {@id} IRI form must not be
        # selected as the main entity.
        ds = {"@id": "urn:ds", "@type": "schema:Dataset",
              "schema:url": "https://ex.org/ds",
              "schema:subjectOf": _catalog_record("urn:rec", "urn:ds")}
        catrec = _catalog_record("urn:rec", "urn:ds")
        picked = FV.pick_main_entity([catrec, ds], FRAME)
        self.assertEqual(picked.get("@id"), "urn:ds")

    def test_package_aggregate_not_lost_to_its_parts(self):
        # Documented behavior guard: an aggregate with no distribution of its own
        # whose parts carry the distributions must still be chosen over a part.
        aggregate = {"@id": "urn:agg", "@type": "schema:Dataset",
                     "schema:hasPart": [{"@id": "_:p1"}, {"@id": "_:p2"}]}
        p1 = {"@id": "_:p1", "@type": "schema:Dataset",
              "schema:distribution": {"@id": "_:d1"}}
        p2 = {"@id": "_:p2", "@type": "schema:Dataset",
              "schema:distribution": {"@id": "_:d2"}}
        picked = FV.pick_main_entity([p1, p2, aggregate], FRAME)
        self.assertEqual(picked.get("@id"), "urn:agg")


if __name__ == "__main__":
    unittest.main()
