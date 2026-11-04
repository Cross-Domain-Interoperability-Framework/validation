"""CDIF-frame-2026.jsonld must not drop data.

In JSON-LD framing, the properties listed under a node act as a filter: a node
with none of them does not match, and comes out null. The frame once listed
schema:identifier under schema:funder, so a funder with only a name vanished and a
valid record failed its schema; publishers, providers, catalogs, creators and
prov:used nodes went the same way. Nested nodes therefore list no properties.

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
KEYWORD_OK = {"@embed", "@type"}


def record():
    """Agents and links carrying only a name: valid, and what the old frame lost."""
    org = lambda name: {"@type": ["schema:Organization"], "schema:name": name}
    return {
        "@context": {"schema": "http://schema.org/", "dcterms": "http://purl.org/dc/terms/",
                     "dcat": "http://www.w3.org/ns/dcat#", "prov": "http://www.w3.org/ns/prov#"},
        "@id": "https://example.org/dataset",
        "@type": ["schema:Dataset"],
        "schema:name": "Example",
        "schema:creator": {"@list": [{"@type": ["schema:Person"], "schema:name": "A Person"}]},
        "schema:publisher": org("A Publisher"),
        "schema:provider": [org("A Provider")],
        "schema:funding": [{"@type": ["schema:MonetaryGrant"], "schema:funder": org("A Funder")}],
        "prov:wasGeneratedBy": [{"@type": ["schema:Action", "prov:Activity"],
                                 "prov:used": [{"@type": ["schema:Thing"], "schema:name": "A Thing Used"}]}],
        "schema:subjectOf": {
            "@id": "https://example.org/dataset#record",
            "@type": ["schema:Dataset"],
            "schema:additionalType": [{"@id": "dcat:CatalogRecord"}],
            "schema:about": {"@id": "https://example.org/dataset"},
            "schema:maintainer": org("A Maintainer"),
            "schema:includedInDataCatalog": {"@type": ["schema:DataCatalog"], "schema:name": "A Catalog"},
        },
    }


class FrameShape(unittest.TestCase):
    def test_nested_nodes_list_no_properties(self):
        """A property listed below the top level would filter nodes again."""
        def check(node, path):
            for key, value in node.items():
                if key.startswith("@"):
                    continue
                self.assertLessEqual(set(value) - KEYWORD_OK, set(),
                                     f"{path}/{key} lists properties, which filter nodes")

        for key, value in FRAME.items():
            if not key.startswith("@") and key != "schema:subjectOf":
                check(value, key)


@unittest.skipUnless(HAVE_PYLD, "pyld not installed")
class NameOnlyNodesSurvive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.framed = FV.frame_cdif(record(), FRAME)

    def text(self):
        return json.dumps(self.framed, ensure_ascii=False)

    def test_every_name_survives(self):
        for name in ("A Person", "A Publisher", "A Provider", "A Funder", "A Thing Used",
                     "A Maintainer", "A Catalog"):
            self.assertIn(name, self.text())

    def test_funder_keeps_its_place(self):
        grant = self.framed["schema:funding"][0]
        self.assertEqual(grant["schema:funder"]["schema:name"], "A Funder")


if __name__ == "__main__":
    unittest.main()
