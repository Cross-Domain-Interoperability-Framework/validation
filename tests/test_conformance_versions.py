"""CDIF 2.0 and the 1.1 records published before it.

Detection declares the 2.0 URIs (metadataBuildingBlocks d27f362, 2026-11-15). A
record published as 1.1 is still valid against the 1.1 release schemas w3id
serves, so its 1.1 claim must count as a claim to the same conformance class:
consistent, and listed as outdated, not reported as over- and under-claiming.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ConformanceValidate as cv  # noqa: E402
import detect_conformance as dc  # noqa: E402

CORE_2, CORE_11, CORE_10 = ("https://w3id.org/cdif/core/2.0", "https://w3id.org/cdif/core/1.1",
                            "https://w3id.org/cdif/core/1.0")
DISC_2, DISC_11 = "https://w3id.org/cdif/discovery/2.0", "https://w3id.org/cdif/discovery/1.1"


def record(declared):
    return {
        "@context": {"schema": "http://schema.org/", "dcterms": "http://purl.org/dc/terms/",
                     "dcat": "http://www.w3.org/ns/dcat#"},
        "@id": "https://example.org/rec",
        "@type": ["schema:Dataset"],
        "schema:name": "A record",
        "schema:identifier": "rec-1",
        "schema:subjectOf": {
            "@id": "https://example.org/rec#meta",
            "@type": ["schema:Dataset"],
            "schema:additionalType": [{"@id": "dcat:CatalogRecord"}],
            "schema:about": {"@id": "https://example.org/rec"},
            "dcterms:conformsTo": [{"@id": u} for u in declared],
        },
    }


class CurrentUriTest(unittest.TestCase):
    def test_registry_declares_2_0(self):
        uris = {c["uri"] for c in dc.CONFORMANCE_CLASSES}
        self.assertIn(CORE_2, uris)
        self.assertIn(DISC_2, uris)
        self.assertNotIn(CORE_11, uris)
        self.assertIn("https://w3id.org/cdif/niaid/1.0", uris)  # its own series

    def test_replaced_versions_map_to_current(self):
        self.assertEqual(dc.current_uri(CORE_11), CORE_2)
        self.assertEqual(dc.current_uri(CORE_10), CORE_2)
        self.assertEqual(dc.current_uri(CORE_11 + "/"), CORE_2)
        self.assertEqual(dc.current_uri(CORE_2), CORE_2)

    def test_other_uris_unchanged(self):
        other = "https://w3id.org/geochem/metadata/profiles/adaProduct/1.0"
        self.assertEqual(dc.current_uri(other), other)

    def test_detection_writes_2_0(self):
        uris = dc.detect_cdif_conformance(record([]), do_shacl=False)
        self.assertIn(CORE_2, uris)


class ConsistencyAcrossVersionsTest(unittest.TestCase):
    def test_1_1_claim_is_consistent_and_outdated(self):
        check = cv.conformance_consistency(record([CORE_11]), [CORE_11])
        self.assertEqual(check["status"], "consistent", check)
        self.assertEqual(check["overclaimed"], [])
        self.assertEqual(check["undeclared"], [])
        self.assertEqual(check["outdated"], [CORE_11])

    def test_2_0_claim_is_consistent_not_outdated(self):
        check = cv.conformance_consistency(record([CORE_2]), [CORE_2])
        self.assertEqual(check["status"], "consistent", check)
        self.assertEqual(check["outdated"], [])

    def test_1_1_overclaim_still_caught(self):
        # discovery/1.1 claimed, but the record has no discovery content
        check = cv.conformance_consistency(record([CORE_11, DISC_11]), [CORE_11, DISC_11])
        self.assertEqual(check["status"], "inconsistent", check)
        self.assertEqual(check["overclaimed"], [DISC_2])


if __name__ == "__main__":
    unittest.main()
