"""Stage-1 detection of the cdifNIAID profile (detect_conformance.py).

A dataset carrying a NIAID nde: property is declared https://w3id.org/cdif/niaid/1.0;
one without, or with nde: only on its catalog record, is not.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import detect_conformance as dc

NIAID = "https://w3id.org/cdif/niaid/1.0"
CTX = {"schema": "http://schema.org/", "dcat": "http://www.w3.org/ns/dcat#",
       "dcterms": "http://purl.org/dc/terms/", "nde": "https://discovery.biothings.io/ns/nde/"}


def record(**extra):
    doc = {"@context": CTX, "@id": "https://data.niaid.nih.gov/resources?id=x1",
           "@type": ["schema:Dataset"], "schema:name": "A dataset",
           "schema:identifier": "x1",
           "schema:subjectOf": {"@id": "https://data.niaid.nih.gov/resources?id=x1#metadata",
                                "@type": ["schema:Dataset"],
                                "schema:additionalType": [{"@id": "dcat:CatalogRecord"}]}}
    doc.update(extra)
    return doc


class NiaidConformance(unittest.TestCase):
    def detect(self, doc):
        return dc.detect_cdif_conformance(doc, do_shacl=False)

    def test_nde_property_declares_the_profile(self):
        self.assertIn(NIAID, self.detect(record(**{"nde:date": "2024-01-01"})))

    def test_without_nde_it_is_not_declared(self):
        self.assertNotIn(NIAID, self.detect(record()))

    def test_nde_on_the_catalog_record_only_does_not_count(self):
        doc = record()
        doc["schema:subjectOf"]["nde:date"] = "2024-01-01"
        self.assertNotIn(NIAID, self.detect(doc))


if __name__ == "__main__":
    unittest.main()
