#!/usr/bin/env python3
"""detect_conformance.py — determine which CDIF conformance classes a record
should declare, from its actual content.

A generator (ada loader, ConvertFromCroissant, DCAT, DDI, ...) builds a CDIF
JSON-LD record, then calls detect_conformance() to set
schema:subjectOf/dcterms:conformsTo from what the record actually contains —
instead of hardcoding a fixed profile list (which over-declares).

Two signals per conformance class, both evaluated on the RDF graph (no framing,
so no normalization artifacts like dropped empty arrays):

  presence  — a SPARQL ASK testing whether the record uses the elements this
              class *introduces beyond its base*. (Not "is property X present":
              prov:wasGeneratedBy is core, so it can't mark cdifProv; the marker
              is the dual-typed prov:Activity+schema:Action with richer
              properties. Likewise data_description is marked by cdi:InstanceVariable
              typing, not by any schema:variableMeasured.)
  validity  — the class's CONTENT SHACL shapes raise no sh:Violation on the
              record. IMPORTANT: the gate uses building-block *content* shapes
              (cdifDataType/<block>/rules.shacl), NOT the *profile* rules.shacl.
              Profile shapes are circular for this purpose — they require the
              catalog record to already *declare* conformance to that profile
              (the metadataProfileProperty requirement), so they validate an
              already-declared record, they can't decide declaration. (sh:Warning
              / sh:Info are advisory and never block, per CDIF severity policy.)

A class is declared iff presence AND (no SHACL, or SHACL conforms).

The CONFORMANCE_CLASSES registry below is the default home for these rules, but
each rule (conformsTo URI + ASK + shapes) can also live WITH the building block
that defines the class, as a ``conformance.json`` sidecar — see
docs/CDIF-Conformance-Declaration-Convention.md. Run with ``--from-source`` (or
env ``CDIF_CONFORMANCE_FROM_SOURCE=1``) to read the rules from the BB sources via
load_bb_conformance() instead of the registry. This is how new classes (e.g.
geochem) register their own presence rule without editing this file.

Usage:
    python detect_conformance.py record.jsonld            # print declarable URIs
    python detect_conformance.py record.jsonld --no-shacl # presence only
    python detect_conformance.py record.jsonld --from-source  # read BB sidecars
    python detect_conformance.py record.jsonld --apply -o out.jsonld  # write conformsTo

Dependencies: pip install rdflib pyshacl   (pyld optional, rdflib parses JSON-LD)
"""
import argparse
import json
import os
import sys
from pathlib import Path

import rdflib

try:
    from pyshacl import validate as shacl_validate
    HAS_PYSHACL = True
except ImportError:
    HAS_PYSHACL = False

# SPARQL prefix preamble shared by every presence ASK.
PREFIXES = """
PREFIX schema: <http://schema.org/>
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX cdi: <http://ddialliance.org/Specification/DDI-CDI/1.0/RDF/>
PREFIX cdif: <https://w3id.org/cdif/>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX dcat: <http://www.w3.org/ns/dcat#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
"""

# Interim registry. Each entry mirrors what would live with the building block
# that defines the class: the conformsTo URI, a presence ASK (elements the class
# introduces beyond its base), and the per-class SHACL shapes (relative to the
# BB _sources dir) used as the validity gate. shacl=None => presence-only.
CONFORMANCE_CLASSES = [
    {
        "uri": "https://w3id.org/cdif/core/1.1",
        # A described dataset: a schema:Dataset (not the catalog record) with a
        # name and an identifier.
        "presence": """ASK {
            ?d a schema:Dataset ; schema:name ?n ; schema:identifier ?i .
            FILTER NOT EXISTS { ?d schema:additionalType dcat:CatalogRecord }
        }""",
        "shacl": None,  # baseline; structural validity is the JSON Schema's job
    },
    {
        "uri": "https://w3id.org/cdif/discovery/1.1",
        # Discovery is the baseline discoverable-dataset profile: any core record
        # is discovery-conformant (the module adds optional enrichment, no new
        # requirements). Declared alongside core.
        "presence": """ASK {
            ?d a schema:Dataset ; schema:name ?n ; schema:identifier ?i .
            FILTER NOT EXISTS { ?d schema:additionalType dcat:CatalogRecord }
        }""",
        "shacl": None,  # cdifDiscovery is a thin wrapper (no rules.shacl)
    },
    {
        "uri": "https://w3id.org/cdif/data_description/1.1",
        # Marked by DDI-CDI InstanceVariable-typed variables (not just any
        # schema:variableMeasured, which is discovery-level PropertyValue).
        "presence": """ASK {
            ?d schema:variableMeasured ?v . ?v a cdi:InstanceVariable .
        }""",
        "shacl": "cdifDataType/cdifInstanceVariable/rules.shacl",
    },
    {
        "uri": "https://w3id.org/cdif/data_structure/1.1",
        # Marked by an explicit data-structure description (cdif:isStructuredBy
        # to a DataStructure node).
        "presence": """ASK {
            { ?x cdif:isStructuredBy ?s }
            UNION { ?n a cdi:LongDataStructure }
            UNION { ?n a cdi:WideDataStructure }
            UNION { ?n a cdi:DimensionalDataStructure }
        }""",
        "shacl": "cdifDataType/cdifDataStructureComponent/rules.shacl",
    },
    {
        "uri": "https://w3id.org/cdif/provenance/1.1",
        # NOT merely prov:wasGeneratedBy (that minimal prov:Activity + prov:used
        # is declared in cdifCore). The cdifProv class is marked by a dual-typed
        # prov:Activity + schema:Action carrying properties beyond prov:used.
        "presence": """ASK {
            ?d prov:wasGeneratedBy ?a .
            ?a a prov:Activity, schema:Action ; ?p ?o .
            FILTER (?p NOT IN (rdf:type, prov:used))
        }""",
        "shacl": "cdifDataType/cdifProvActivity/rules.shacl",
    },
    {
        "uri": "https://w3id.org/cdif/manifest/1.1",
        # Marked by an archive distribution: a DataDownload with hasPart files.
        "presence": """ASK {
            ?d schema:distribution ?dd . ?dd schema:hasPart ?p .
        }""",
        "shacl": None,  # cdifArchiveDistribution has no content rules.shacl yet
    },
]


def _find_bb_dir(explicit=None):
    """Locate the building-block _sources dir for SHACL resolution."""
    if explicit:
        return Path(explicit)
    env = os.environ.get("CDIF_BB_DIR")
    if env and Path(env).is_dir():
        return Path(env)
    here = Path(__file__).resolve().parent
    for c in [here / "BuildingBlockSubmodule" / "_sources",
              here.parent / "metadataBuildingBlocks" / "_sources"]:
        if c.is_dir():
            return c
    return None


def _to_graph(doc):
    """Parse a CDIF JSON-LD dict into an rdflib Graph (expanded triples)."""
    g = rdflib.Graph()
    g.parse(data=json.dumps(doc), format="json-ld")
    return g


def load_bb_conformance(bb_dir):
    """Read per-building-block conformance declarations from a BB _sources tree.

    Scans for ``conformance.json`` sidecars (one per profile building block; see
    docs/CDIF-Conformance-Declaration-Convention.md) and returns class entries in
    the SAME shape as the CONFORMANCE_CLASSES registry — ``{uri, presence, shacl}``
    — so detect_conformance() can consume either source. ``validityShapes`` paths
    are relative to ``bb_dir`` (the _sources root), exactly as the registry's
    ``shacl`` paths are. Returns [] if no sidecars are found.

    This is the migration path away from the hardcoded registry: once every
    profile BB carries a sidecar, detect_conformance can read its rules from the
    building blocks that define them (run with ``use_bb_source=True`` or
    ``CDIF_CONFORMANCE_FROM_SOURCE=1``)."""
    classes = []
    root = Path(bb_dir)
    if not root.is_dir():
        return classes
    for path in sorted(root.glob("**/conformance.json")):
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        uri, ask = d.get("conformsTo"), d.get("presence")
        if not uri or not ask:
            continue
        classes.append({"uri": uri, "presence": ask,
                        "shacl": d.get("validityShapes")})
    return classes


def detect_conformance(doc, bb_dir=None, do_shacl=True, verbose=False,
                       use_bb_source=None):
    """Return the list of CDIF conformsTo URIs the record should declare,
    based on its content (presence ASK) and well-formedness (per-class SHACL).

    By default the rules come from the hardcoded CONFORMANCE_CLASSES registry.
    Set ``use_bb_source=True`` (or env ``CDIF_CONFORMANCE_FROM_SOURCE=1``) to read
    them instead from the building blocks' ``conformance.json`` sidecars via
    load_bb_conformance() — the eventual source of truth. Falls back to the
    registry if no sidecars are found."""
    if use_bb_source is None:
        use_bb_source = os.environ.get("CDIF_CONFORMANCE_FROM_SOURCE") == "1"
    graph = _to_graph(doc)
    bb = _find_bb_dir(bb_dir) if (do_shacl or use_bb_source) else None
    classes = CONFORMANCE_CLASSES
    if use_bb_source and bb is not None:
        src = load_bb_conformance(bb)
        if src:
            classes = src
            if verbose:
                print(f"  using {len(src)} source-declared conformance "
                      f"class(es) from {bb}", file=sys.stderr)
    declared = []
    for cls in classes:
        present = bool(graph.query(PREFIXES + cls["presence"]).askAnswer)
        if verbose:
            print(f"  presence {cls['uri'].split('/cdif/')[-1]:18} {present}",
                  file=sys.stderr)
        if not present:
            continue
        if do_shacl and cls["shacl"] and HAS_PYSHACL and bb is not None:
            shapes_path = bb / cls["shacl"]
            if shapes_path.is_file():
                _conforms, results_graph, _t = shacl_validate(
                    graph, shacl_graph=str(shapes_path),
                    shacl_graph_format="turtle", inference="rdfs",
                    advanced=True)
                # Only sh:Violation blocks declaration; sh:Warning / sh:Info are
                # advisory (consistent with CDIF's severity policy).
                sh = rdflib.Namespace("http://www.w3.org/ns/shacl#")
                violations = list(results_graph.triples(
                    (None, sh.resultSeverity, sh.Violation)))
                if violations:
                    if verbose:
                        print(f"    -> {len(violations)} SHACL violation(s); "
                              f"not declaring", file=sys.stderr)
                    continue
        declared.append(cls["uri"])
    return declared


# CDIF profile URIs all live under this base. apply_conformance manages exactly
# this space and leaves any other conformsTo entries (e.g. a domain-specific
# profile) untouched.
CDIF_BASE = "https://w3id.org/cdif/"


def apply_conformance(doc, uris, manage_prefix=CDIF_BASE):
    """Set schema:subjectOf.dcterms:conformsTo to the detected URIs (in place).

    Only the CDIF-managed profile space (URIs under ``manage_prefix``) is
    replaced; any existing conformsTo entries outside that space — e.g. a
    project/domain profile such as ``ada:profile/...`` — are preserved (appended
    after the detected CDIF URIs)."""
    subj = doc.get("schema:subjectOf")
    if not isinstance(subj, dict):
        return doc
    preserved = []
    existing = subj.get("dcterms:conformsTo")
    if isinstance(existing, list):
        for entry in existing:
            ref = entry.get("@id") if isinstance(entry, dict) else entry
            if isinstance(ref, str) and not ref.startswith(manage_prefix):
                preserved.append(entry)
    subj["dcterms:conformsTo"] = [{"@id": u} for u in uris] + preserved
    return doc


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("input", help="CDIF JSON-LD record")
    p.add_argument("--no-shacl", action="store_true",
                   help="presence-only (skip the SHACL validity gate)")
    p.add_argument("--bb-dir", help="building-block _sources dir (for SHACL)")
    p.add_argument("--from-source", action="store_true",
                   help="read conformance rules from BB conformance.json sidecars "
                        "instead of the hardcoded registry")
    p.add_argument("--apply", action="store_true",
                   help="write detected conformsTo into the record")
    p.add_argument("-o", "--output", help="output path (with --apply)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    doc = json.load(open(args.input, encoding="utf-8"))
    uris = detect_conformance(doc, bb_dir=args.bb_dir,
                              do_shacl=not args.no_shacl, verbose=args.verbose,
                              use_bb_source=args.from_source or None)
    print("Declarable conformance classes:")
    for u in uris:
        print(f"  {u}")
    if args.apply:
        apply_conformance(doc, uris)
        out = args.output or args.input
        json.dump(doc, open(out, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
        open(out, "a", encoding="utf-8").write("\n")
        print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
