#!/usr/bin/env python3
"""
Generate composite SHACL shapes files for CDIF profiles by merging building
block rules.shacl files.

Reads CDIF building block SHACL rules from metadataBuildingBlocks/_sources/
and produces a single merged Turtle file with unified prefixes and
priority-based conflict resolution.

Supports two profiles:
  - discovery (default): CDIFDiscovery profile shapes
  - complete: CDIFcomplete profile (discovery + data description + provenance)

Usage:
    python generate_shacl_shapes.py [--profile PROFILE] [--bb-dir PATH] [--output PATH] [-v]

The --bb-dir defaults to the metadataBuildingBlocks/_sources/ directory
detected relative to this script or via the CDIF_BB_DIR environment variable.
"""

import argparse
import os
import sys
from datetime import date
from pathlib import Path

from rdflib import Graph, Namespace, URIRef, BNode
from rdflib.namespace import RDF, RDFS, XSD, OWL

# ---------------------------------------------------------------------------
# Namespaces
# ---------------------------------------------------------------------------

SH = Namespace("http://www.w3.org/ns/shacl#")
SCHEMA = Namespace("http://schema.org/")
CDIFD = Namespace("https://cdif.org/validation/0.1/shacl#")
DCTERMS = Namespace("http://purl.org/dc/terms/")
TIME = Namespace("http://www.w3.org/2006/time#")
PROV = Namespace("http://www.w3.org/ns/prov#")
DQV = Namespace("http://www.w3.org/ns/dqv#")
SPDX = Namespace("http://spdx.org/rdf/terms#")
CDI = Namespace("http://ddialliance.org/Specification/DDI-CDI/1.0/RDF/")
SOSO = Namespace("http://science-on-schema.org/1.2.3/validation/shacl#")

# ---------------------------------------------------------------------------
# CDIFDiscovery profile building blocks, ordered by merge priority.
# Highest priority first: sub-building blocks define authoritative shapes;
# composites and profile-level copies are lower priority.
#
# When the same named shape URI (e.g. cdifd:CDIFDefinedTermShape) appears in
# multiple files, the first file in this list wins and later copies are
# skipped.  This ensures the most specific / authoritative definition is kept.
# ---------------------------------------------------------------------------

CDIF_DISCOVERY_BLOCKS = [
    # --- Sub-building blocks (leaf components, most authoritative) ---
    "schemaorgProperties/identifier",
    "schemaorgProperties/person",
    "schemaorgProperties/organization",
    "schemaorgProperties/definedTerm",
    "schemaorgProperties/dataDownload",
    "schemaorgProperties/webAPI",
    "schemaorgProperties/spatialExtent",
    "schemaorgProperties/temporalExtent",
    "schemaorgProperties/variableMeasured",
    "schemaorgProperties/funder",
    "schemaorgProperties/agentInRole",
    "schemaorgProperties/additionalProperty",
    "schemaorgProperties/labeledLink",
    "schemaorgProperties/action",
    "provProperties/generatedBy",
    "provProperties/derivedFrom",
    "qualityProperties/qualityMeasure",
    # --- CDIF composite building blocks ---
    "cdifProperties/cdifCatalogRecord",
    # --- CDIF aggregate building blocks ---
    "cdifProperties/cdifMandatory",
    "cdifProperties/cdifOptional",
    # --- Profile level (lowest priority -- shapes here are copies) ---
    "profiles/cdifProfiles/CDIFDiscovery",
]

# ---------------------------------------------------------------------------
# CDIFcomplete profile building blocks.
# Includes everything from CDIFDiscovery plus provenance activity shapes
# (cdifProv and provActivity), data description, physical mapping, and
# long data building blocks.  cdifVariableMeasured adds the enhanced
# propertyID validation beyond the base variableMeasured shapes.
# ---------------------------------------------------------------------------

CDIF_COMPLETE_BLOCKS = [
    # --- Sub-building blocks (leaf components, most authoritative) ---
    "schemaorgProperties/identifier",
    "schemaorgProperties/person",
    "schemaorgProperties/organization",
    "schemaorgProperties/definedTerm",
    "schemaorgProperties/dataDownload",
    "schemaorgProperties/webAPI",
    "schemaorgProperties/spatialExtent",
    "schemaorgProperties/temporalExtent",
    "schemaorgProperties/variableMeasured",
    "schemaorgProperties/funder",
    "schemaorgProperties/agentInRole",
    "schemaorgProperties/additionalProperty",
    "schemaorgProperties/labeledLink",
    "schemaorgProperties/action",
    "provProperties/generatedBy",
    "provProperties/provActivity",
    "provProperties/derivedFrom",
    "qualityProperties/qualityMeasure",
    # --- CDIF composite building blocks ---
    "cdifProperties/cdifCatalogRecord",
    "cdifProperties/cdifProv",
    # --- Data description building blocks (CDIFcomplete additions) ---
    "cdifProperties/cdifVariableMeasured",
    "cdifProperties/cdifPhysicalMapping",
    "cdifProperties/cdifDataCube",
    "cdifProperties/cdifTabularData",
    "cdifProperties/cdifLongData",
    # --- CDIF aggregate building blocks ---
    "cdifProperties/cdifMandatory",
    "cdifProperties/cdifOptional",
    # --- Profile level (lowest priority -- shapes here are copies) ---
    "profiles/cdifProfiles/CDIFDiscovery",
    "profiles/cdifProfiles/CDIFDataDescription",
    "profiles/cdifProfiles/CDIFcomplete",
]

PROFILES = {
    "discovery": {
        "blocks": CDIF_DISCOVERY_BLOCKS,
        "label": "CDIF Discovery Profile",
        "default_output": "CDIF-Discovery-Core-Shapes.ttl",
    },
    "complete": {
        "blocks": CDIF_COMPLETE_BLOCKS,
        "label": "CDIF Complete Profile",
        "default_output": "CDIF-Complete-Shapes.ttl",
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def find_bb_dir():
    """Find the building blocks _sources directory."""
    # Try environment variable first
    env = os.environ.get("CDIF_BB_DIR")
    if env and Path(env).is_dir():
        return Path(env)

    # Try common relative locations from the script directory
    script_dir = Path(__file__).resolve().parent
    candidates = [
        script_dir / "BuildingBlockSubmodule" / "_sources",
        script_dir.parent / "metadataBuildingBlocks" / "_sources",
        # Windows OneDrive paths
        Path.home() / "OneDrive" / "Documents" / "GithubC" / "USGIN"
            / "metadataBuildingBlocks" / "_sources",
        Path.home() / "OneDrive" / "Documents" / "GithubC" / "smrgeoinfo"
            / "OCGbuildingBlockTest" / "_sources",
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return None


def find_named_shapes(graph):
    """Return all named (non-blank) shape URIs defined in a graph.

    A named shape is a URIRef that appears as the subject of an
    ``rdf:type sh:NodeShape`` or ``rdf:type sh:PropertyShape`` triple.
    """
    shapes = set()
    for s in graph.subjects(RDF.type, SH.NodeShape):
        if isinstance(s, URIRef):
            shapes.add(s)
    for s in graph.subjects(RDF.type, SH.PropertyShape):
        if isinstance(s, URIRef):
            shapes.add(s)
    return shapes


def extract_cbd(graph, subject):
    """Extract the Concise Bounded Description of *subject*.

    Returns all triples where *subject* is the subject, plus recursively
    all triples reachable through blank-node objects.  Named URI objects
    are **not** followed (their definitions are handled separately).
    """
    triples = set()
    visited = set()

    def follow(node):
        if node in visited:
            return
        visited.add(node)
        for s, p, o in graph.triples((node, None, None)):
            triples.add((s, p, o))
            if isinstance(o, BNode):
                follow(o)

    follow(subject)
    return triples


def short_name(uri):
    """Abbreviate a CDIFD or SOSO URI for display."""
    s = str(uri)
    prefix = "https://cdif.org/validation/0.1/shacl#"
    if s.startswith(prefix):
        return "cdifd:" + s[len(prefix):]
    soso_prefix = "http://science-on-schema.org/1.2.3/validation/shacl#"
    if s.startswith(soso_prefix):
        return "soso:" + s[len(soso_prefix):]
    return s


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------

def merge_shapes(bb_dir, blocks, verbose=False):
    """Merge building block rules.shacl files with priority-based conflict
    resolution.  The first file to define a named shape wins; later
    duplicates are skipped with a warning.
    """
    merged = Graph()
    claimed = {}        # shape URI -> source file (relative path)
    file_count = 0
    shape_count = 0
    conflict_count = 0
    triple_count = 0

    for block in blocks:
        shacl_path = bb_dir / block / "rules.shacl"
        if not shacl_path.exists():
            if verbose:
                print(f"  SKIP (not found): {block}/rules.shacl")
            continue

        tmp = Graph()
        try:
            tmp.parse(str(shacl_path), format="turtle")
        except Exception as exc:
            print(f"  ERROR parsing {block}/rules.shacl: {exc}",
                  file=sys.stderr)
            continue

        file_count += 1
        rel = block + "/rules.shacl"

        if verbose:
            print(f"  {rel}  ({len(tmp)} triples)")

        # Identify named shapes in this file
        file_shapes = find_named_shapes(tmp)
        new_shapes = set()
        skip_shapes = set()

        for shape in file_shapes:
            if shape in claimed:
                skip_shapes.add(shape)
                conflict_count += 1
                if verbose:
                    print(f"    CONFLICT: {short_name(shape)}  "
                          f"(kept from {claimed[shape]})")
            else:
                new_shapes.add(shape)
                claimed[shape] = rel
                shape_count += 1

        # Collect triples for new shapes (CBD includes blank-node trees)
        triples_to_add = set()
        for shape in new_shapes:
            triples_to_add |= extract_cbd(tmp, shape)

        added = 0
        for triple in triples_to_add:
            merged.add(triple)
            added += 1
        triple_count += added

        if verbose and new_shapes:
            print(f"    Added {len(new_shapes)} shapes ({added} triples)")

    stats = {
        "files": file_count,
        "shapes": shape_count,
        "conflicts": conflict_count,
        "triples": triple_count,
    }
    return merged, claimed, stats


def bind_prefixes(graph):
    """Bind standard prefixes for clean Turtle serialization."""
    graph.bind("sh", SH)
    graph.bind("schema", SCHEMA)
    graph.bind("cdifd", CDIFD)
    graph.bind("xsd", XSD)
    graph.bind("rdf", RDF)
    graph.bind("rdfs", RDFS)
    graph.bind("dcterms", DCTERMS)
    graph.bind("time", TIME)
    graph.bind("prov", PROV)
    graph.bind("dqv", DQV)
    graph.bind("owl", OWL)
    graph.bind("spdx", SPDX)
    graph.bind("cdi", CDI)
    graph.bind("soso", SOSO)


def make_header(stats, bb_dir, profile_label="CDIF Discovery Profile",
                profile_name="discovery"):
    """Return a Turtle comment block for the file header."""
    today = date.today().isoformat()
    return (
        f"# {profile_label} -- Composite SHACL Shapes\n"
        f"# Generated by generate_shacl_shapes.py --profile {profile_name} "
        f"from {stats['files']} building block rules.shacl files\n"
        f"# Date: {today}\n"
        f"# Source: {bb_dir}\n"
        f"# Shapes: {stats['shapes']} | "
        f"Conflicts resolved: {stats['conflicts']} | "
        f"Triples: {stats['triples']}\n"
        f"#\n"
        f"# DO NOT EDIT -- regenerate with: "
        f"python generate_shacl_shapes.py --profile {profile_name}\n"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate composite SHACL shapes from CDIF building blocks"
    )
    parser.add_argument(
        "--profile", "-p",
        choices=list(PROFILES.keys()),
        default="discovery",
        help="Profile to generate shapes for (default: discovery)",
    )
    parser.add_argument(
        "--bb-dir",
        type=Path,
        default=None,
        help="Path to building blocks _sources/ directory "
             "(default: auto-detect or CDIF_BB_DIR env var)",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        help="Output Turtle file (default: profile-specific filename)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Print detailed merge progress",
    )
    args = parser.parse_args()

    # Resolve profile
    profile = PROFILES[args.profile]
    blocks = profile["blocks"]
    output = args.output or Path(profile["default_output"])

    # Resolve building blocks directory
    bb_dir = args.bb_dir or find_bb_dir()
    if not bb_dir or not bb_dir.is_dir():
        print(
            "ERROR: Cannot find building blocks _sources/ directory.\n"
            "Use --bb-dir or set CDIF_BB_DIR environment variable.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Profile: {profile['label']}")
    print(f"Building blocks: {bb_dir}")
    print(f"Output: {output}")
    print(f"Merging {len(blocks)} building block rule sets...\n")

    # Merge
    merged, claimed, stats = merge_shapes(
        bb_dir, blocks, verbose=args.verbose
    )

    # Bind prefixes and serialize
    bind_prefixes(merged)
    turtle_str = merged.serialize(format="turtle")
    header = make_header(stats, bb_dir,
                         profile_label=profile["label"],
                         profile_name=args.profile)

    with open(output, "w", encoding="utf-8") as f:
        f.write(header)
        f.write("\n")
        f.write(turtle_str)

    # Summary
    print(f"\nDone: {stats['shapes']} shapes from {stats['files']} files "
          f"({stats['triples']} triples)")
    if stats["conflicts"]:
        print(f"  {stats['conflicts']} conflicts resolved "
              f"(higher-priority version kept)")
    print(f"  Written to {output}")


if __name__ == "__main__":
    main()
