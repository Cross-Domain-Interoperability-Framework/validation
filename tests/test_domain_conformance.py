#!/usr/bin/env python3
"""Tests for the two-stage conformance detector in detect_conformance.py.

Stage 1 (detect_cdif_conformance) + the deprecated detect_conformance alias, and
stage 2 (detect_domain_conformance): requires-dependency resolution, exclusive
groups with priority, declared ties, and withheld reporting.

Self-contained: builds a tiny geochemBuildingBlocks-style _sources tree with
conformance.json sidecars in a temp dir and runs detection against hand-built
JSON-LD records. No network, no external fixtures.

Run:  python -m unittest tests.test_domain_conformance      (from the repo root)
      python tests/test_domain_conformance.py
"""
import json
import sys
import tempfile
import unittest
import warnings
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import detect_conformance as dc

ADA = "https://w3id.org/geochem/ada#"
G = dc.GEOCHEM_BASE + "geochemProduct/1.0"
A = dc.GEOCHEM_BASE + "adaProduct/1.0"
T_ALPHA_1 = dc.GEOCHEM_BASE + "technique/laMcicpms/1.0"
T_ALPHA_2 = dc.GEOCHEM_BASE + "technique/laQicpms/1.0"
T_BETA = dc.GEOCHEM_BASE + "technique/solutionIcpms/1.0"

CDIF_MODULES = [
    "https://w3id.org/cdif/core/1.1",
    "https://w3id.org/cdif/discovery/1.1",
    "https://w3id.org/cdif/data_description/1.1",
    "https://w3id.org/cdif/data_structure/1.1",
    "https://w3id.org/cdif/provenance/1.1",
]


def _ask(body):
    return f"PREFIX ada: <{ADA}>\nASK {{ {body} }}"


def _doc(types=None, component_types=None, named_components=True, conforms=None):
    d = {
        "@context": {"schema": "http://schema.org/", "ada": ADA,
                     "dcterms": "http://purl.org/dc/terms/"},
        "@id": "https://example.org/rec",
        "@type": ["schema:Dataset"] + list(types or []),
        "schema:name": "A record",
        "schema:identifier": "rec-1",
    }
    parts = []
    for i, ct in enumerate(component_types or []):
        node = {"@id": f"https://example.org/c{i}",
                "ada:componentType": {"@id": ct}}
        if named_components:
            node["schema:name"] = f"component {i}"
        parts.append(node)
    if parts:
        d["schema:hasPart"] = parts
    if conforms is not None:
        d["schema:subjectOf"] = {
            "@id": "https://example.org/rec/cat",
            "@type": ["schema:Dataset"],
            "schema:additionalType": [{"@id": "dcat:CatalogRecord"}],
            "dcterms:conformsTo": [{"@id": u} for u in conforms],
        }
    return d


def _write_sidecar(root, folder, **fields):
    p = root / "profiles" / folder
    p.mkdir(parents=True, exist_ok=True)
    (p / "conformance.json").write_text(json.dumps(fields), encoding="utf-8")


class StageOneAliasTest(unittest.TestCase):
    def test_new_name_detects_core_and_discovery(self):
        uris = dc.detect_cdif_conformance(_doc(), do_shacl=False)
        self.assertIn("https://w3id.org/cdif/core/1.1", uris)
        self.assertIn("https://w3id.org/cdif/discovery/1.1", uris)

    def test_deprecated_alias_still_works_and_warns(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            uris = dc.detect_conformance(_doc(), do_shacl=False)
        self.assertIn("https://w3id.org/cdif/core/1.1", uris)
        self.assertTrue(any(issubclass(w.category, DeprecationWarning)
                            for w in caught),
                        "alias should emit a DeprecationWarning")


class _DomainBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _chain_sidecars(self, alpha_priorities=(2, 1), include_beta=False):
        # geochemProduct <- adaProduct <- technique(s)
        _write_sidecar(self.root, "geochemProduct", conformsTo=G,
                       presence=_ask("?d a ada:GeochemProduct"),
                       requires=CDIF_MODULES)
        _write_sidecar(self.root, "adaProduct", conformsTo=A,
                       presence=_ask("?d a ada:AdaProduct"), requires=[G])
        _write_sidecar(self.root, "tAlpha1", conformsTo=T_ALPHA_1,
                       presence=_ask("?c ada:componentType ada:TypeAlpha"),
                       requires=[A], exclusiveGroup="technique",
                       priority=alpha_priorities[0])
        _write_sidecar(self.root, "tAlpha2", conformsTo=T_ALPHA_2,
                       presence=_ask("?c ada:componentType ada:TypeAlpha"),
                       requires=[A], exclusiveGroup="technique",
                       priority=alpha_priorities[1])
        if include_beta:
            _write_sidecar(self.root, "tBeta", conformsTo=T_BETA,
                           presence=_ask("?c ada:componentType ada:TypeBeta"),
                           requires=[A], exclusiveGroup="technique", priority=5)


class RequiresTest(_DomainBase):
    def test_chain_resolves_to_fixpoint(self):
        self._chain_sidecars(alpha_priorities=(2, 1))
        doc = _doc(types=["ada:GeochemProduct", "ada:AdaProduct"],
                   component_types=["ada:TypeAlpha"])
        r = dc.detect_domain_conformance(doc, CDIF_MODULES, bb_dir=self.root,
                                         do_shacl=False)
        # G then A then the higher-priority technique, in order.
        self.assertEqual(r.declared, [G, A, T_ALPHA_1])
        self.assertEqual(r.withheld, [])
        self.assertEqual(r.ties, [])
        self.assertTrue(r.clean)

    def test_unsatisfied_requires_is_withheld_not_dropped(self):
        self._chain_sidecars()
        # Technique presence holds (TypeAlpha) but adaProduct presence does NOT
        # (no ada:AdaProduct type), so requires [A] can never be satisfied.
        doc = _doc(types=["ada:GeochemProduct"],
                   component_types=["ada:TypeAlpha"])
        r = dc.detect_domain_conformance(doc, CDIF_MODULES, bb_dir=self.root,
                                         do_shacl=False)
        self.assertEqual(r.declared, [G])          # only geochemProduct
        self.assertFalse(r.ok)                      # withheld => not ok
        withheld_uris = {w["uri"] for w in r.withheld}
        self.assertEqual(withheld_uris, {T_ALPHA_1, T_ALPHA_2})
        for w in r.withheld:
            self.assertEqual(w["reason"], "unsatisfied requires")
            self.assertIn(A, w["detail"])

    def test_missing_cdif_module_blocks_geochemproduct(self):
        self._chain_sidecars()
        doc = _doc(types=["ada:GeochemProduct"])
        # prior_uris missing data_structure -> geochemProduct requires unmet.
        prior = [u for u in CDIF_MODULES if "data_structure" not in u]
        r = dc.detect_domain_conformance(doc, prior, bb_dir=self.root,
                                         do_shacl=False)
        self.assertEqual(r.declared, [])
        self.assertEqual([w["uri"] for w in r.withheld], [G])
        self.assertEqual(r.withheld[0]["reason"], "unsatisfied requires")


class ExclusiveGroupTest(_DomainBase):
    def test_highest_priority_wins_loser_not_withheld(self):
        self._chain_sidecars(alpha_priorities=(3, 1))
        doc = _doc(types=["ada:GeochemProduct", "ada:AdaProduct"],
                   component_types=["ada:TypeAlpha"])
        r = dc.detect_domain_conformance(doc, CDIF_MODULES, bb_dir=self.root,
                                         do_shacl=False)
        self.assertIn(T_ALPHA_1, r.declared)        # priority 3 wins
        self.assertNotIn(T_ALPHA_2, r.declared)     # excluded
        # The excluded sibling is NOT a failure and NOT a tie.
        self.assertEqual(r.withheld, [])
        self.assertEqual(r.ties, [])

    def test_more_specific_across_groups(self):
        # Beta technique (its own componentType) declared alongside the Alpha
        # winner only when its presence holds.
        self._chain_sidecars(alpha_priorities=(3, 1), include_beta=True)
        doc = _doc(types=["ada:GeochemProduct", "ada:AdaProduct"],
                   component_types=["ada:TypeAlpha", "ada:TypeBeta"])
        r = dc.detect_domain_conformance(doc, CDIF_MODULES, bb_dir=self.root,
                                         do_shacl=False)
        # All three techniques share one exclusiveGroup "technique"; beta has the
        # highest priority (5), so it wins the whole group.
        self.assertIn(T_BETA, r.declared)
        self.assertNotIn(T_ALPHA_1, r.declared)
        self.assertNotIn(T_ALPHA_2, r.declared)


class TieTest(_DomainBase):
    def test_equal_priority_is_a_declared_tie(self):
        self._chain_sidecars(alpha_priorities=(1, 1))   # equal -> honest tie
        doc = _doc(types=["ada:GeochemProduct", "ada:AdaProduct"],
                   component_types=["ada:TypeAlpha"])
        r = dc.detect_domain_conformance(doc, CDIF_MODULES, bb_dir=self.root,
                                         do_shacl=False)
        self.assertEqual(r.declared, [G, A])            # no technique declared
        self.assertEqual(r.withheld, [])                # a tie is not a failure
        self.assertEqual(len(r.ties), 1)
        tie = r.ties[0]
        self.assertEqual(tie["group"], "technique")
        self.assertEqual(tie["priority"], 1)
        self.assertEqual(set(tie["candidates"]), {T_ALPHA_1, T_ALPHA_2})
        self.assertTrue(r.ok)          # ok (nothing withheld)
        self.assertFalse(r.clean)      # not clean (a tie was reported)


@unittest.skipUnless(dc.HAS_PYSHACL, "pyshacl not installed")
class ValidityGateTest(_DomainBase):
    SHAPES = (
        "@prefix sh: <http://www.w3.org/ns/shacl#> .\n"
        "@prefix schema: <http://schema.org/> .\n"
        f"@prefix ada: <{ADA}> .\n"
        "<urn:shape:component> a sh:NodeShape ;\n"
        "  sh:targetSubjectsOf ada:componentType ;\n"
        "  sh:property [ sh:path schema:name ; sh:minCount 1 ;\n"
        "               sh:severity sh:Violation ] .\n"
    )

    def _sidecars_with_validity(self):
        (self.root / "shapes").mkdir(parents=True, exist_ok=True)
        (self.root / "shapes" / "component.ttl").write_text(self.SHAPES,
                                                            encoding="utf-8")
        _write_sidecar(self.root, "geochemProduct", conformsTo=G,
                       presence=_ask("?d a ada:GeochemProduct"),
                       requires=CDIF_MODULES)
        _write_sidecar(self.root, "adaProduct", conformsTo=A,
                       presence=_ask("?d a ada:AdaProduct"), requires=[G])
        _write_sidecar(self.root, "tAlpha", conformsTo=T_ALPHA_1,
                       presence=_ask("?c ada:componentType ada:TypeAlpha"),
                       requires=[A], exclusiveGroup="technique", priority=1,
                       validityShapes="shapes/component.ttl")

    def test_validity_violation_withholds(self):
        self._sidecars_with_validity()
        # component has NO schema:name -> content SHACL violation.
        doc = _doc(types=["ada:GeochemProduct", "ada:AdaProduct"],
                   component_types=["ada:TypeAlpha"], named_components=False)
        r = dc.detect_domain_conformance(doc, CDIF_MODULES, bb_dir=self.root,
                                         do_shacl=True)
        self.assertNotIn(T_ALPHA_1, r.declared)
        self.assertEqual([w["uri"] for w in r.withheld], [T_ALPHA_1])
        self.assertEqual(r.withheld[0]["reason"], "validity gate failed")
        self.assertFalse(r.ok)

    def test_validity_pass_declares(self):
        self._sidecars_with_validity()
        doc = _doc(types=["ada:GeochemProduct", "ada:AdaProduct"],
                   component_types=["ada:TypeAlpha"], named_components=True)
        r = dc.detect_domain_conformance(doc, CDIF_MODULES, bb_dir=self.root,
                                         do_shacl=True)
        self.assertIn(T_ALPHA_1, r.declared)
        self.assertTrue(r.clean)


class ApplyConformanceTest(_DomainBase):
    def test_two_stage_apply_orders_cdif_then_domain_and_preserves(self):
        doc = _doc(conforms=["ada:profile/legacy"])  # a pre-existing domain-ish claim
        # Stage 1 writes CDIF; stage 2 appends geochem, both preserving others.
        dc.apply_conformance(doc, CDIF_MODULES)
        dc.apply_conformance(doc, [G, A], manage_prefix=dc.GEOCHEM_BASE,
                             append=True)
        got = [e["@id"] for e in doc["schema:subjectOf"]["dcterms:conformsTo"]]
        # CDIF first, preserved legacy claim kept, geochem appended last.
        self.assertEqual(got[:5], CDIF_MODULES)
        self.assertIn("ada:profile/legacy", got)
        self.assertEqual(got[-2:], [G, A])

    def test_stage2_apply_leaves_cdif_entries_alone(self):
        doc = _doc(conforms=[])   # has an (empty) catalog record for apply to fill
        dc.apply_conformance(doc, CDIF_MODULES)
        before = list(doc["schema:subjectOf"]["dcterms:conformsTo"])
        dc.apply_conformance(doc, [G], manage_prefix=dc.GEOCHEM_BASE, append=True)
        after = [e["@id"] for e in doc["schema:subjectOf"]["dcterms:conformsTo"]]
        self.assertEqual(after[:len(before)], [e["@id"] for e in before])
        self.assertEqual(after[-1], G)


class PresenceBuilderTest(unittest.TestCase):
    ADA_NS = "https://ada.astromat.org/metadata/"

    def _ctx(self):
        return {"schema": "http://schema.org/", "ada": self.ADA_NS}

    def _matches(self, doc, ask):
        g = dc._to_graph(doc)
        return bool(g.query(dc.PREFIXES + ask).askAnswer)

    def test_property_iri_and_structure(self):
        ask = dc.build_component_presence_ask(["ada:SEMImageMap"])
        self.assertIn("<https://ada.astromat.org/metadata/componentType>", ask)
        self.assertIn('"ada:SEMImageMap"', ask)   # a STRING literal, not <IRI>
        self.assertNotIn("<ada:SEMImageMap>", ask)

    def test_matches_literal_value_under_haspart(self):
        ask = dc.build_component_presence_ask(["ada:SEMImageMap", "ada:SEMImageTabular"])
        doc = {"@context": self._ctx(), "@id": "https://ex/r",
               "@type": ["schema:Dataset"],
               "schema:distribution": [{"@id": "https://ex/d",
                   "@type": ["schema:DataDownload", "schema:Collection"],
                   "schema:hasPart": [{"@id": "https://ex/c",
                       "ada:componentType": "ada:SEMImageMap"}]}]}
        self.assertTrue(self._matches(doc, ask))

    def test_path_agnostic_matches_on_monolithic_distribution(self):
        # componentType on the distribution itself (no hasPart) — gBB #136.
        ask = dc.build_component_presence_ask(["ada:SEMImageMap"])
        doc = {"@context": self._ctx(), "@id": "https://ex/r",
               "@type": ["schema:Dataset"],
               "schema:distribution": [{"@id": "https://ex/d",
                   "@type": ["schema:DataDownload"],
                   "ada:componentType": "ada:SEMImageMap"}]}
        self.assertTrue(self._matches(doc, ask))

    def test_no_match_on_other_value(self):
        ask = dc.build_component_presence_ask(["ada:SEMImageMap"])
        doc = {"@context": self._ctx(), "@id": "https://ex/r",
               "@type": ["schema:Dataset"],
               "schema:distribution": [{"@id": "https://ex/d",
                   "ada:componentType": "ada:XRFTabular"}]}
        self.assertFalse(self._matches(doc, ask))

    def test_literal_discipline_iri_value_does_not_match(self):
        # If componentType were (wrongly) an @id node, the literal ASK must NOT
        # match — the PR#141 failure mode, guarded.
        ask = dc.build_component_presence_ask(["ada:SEMImageMap"])
        doc = {"@context": self._ctx(), "@id": "https://ex/r",
               "@type": ["schema:Dataset"],
               "schema:distribution": [{"@id": "https://ex/d",
                   "ada:componentType": {"@id": "ada:SEMImageMap"}}]}
        self.assertFalse(self._matches(doc, ask))

    def test_empty_list_raises(self):
        with self.assertRaises(ValueError):
            dc.build_component_presence_ask([])

    def test_special_characters_are_escaped(self):
        ask = dc.build_component_presence_ask(['ada:weird"name'])
        self.assertIn(r'"ada:weird\"name"', ask)


if __name__ == "__main__":
    unittest.main(verbosity=2)
