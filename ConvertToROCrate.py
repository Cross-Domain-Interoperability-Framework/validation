#!/usr/bin/env python3
"""
CDIF JSON-LD to RO-Crate Converter

Converts CDIF JSON-LD (compacted/nested) into RO-Crate 1.1 form (flattened @graph).

This module can be used as a library (import convert_to_rocrate) or as a standalone
CLI tool for conversion without validation.

Usage:
    # Convert CDIF to RO-Crate form
    python ConvertToROCrate.py input.jsonld -o output-rocrate.jsonld

    # Print converted RO-Crate to stdout
    python ConvertToROCrate.py input.jsonld

    # Verbose output
    python ConvertToROCrate.py input.jsonld -o output.jsonld -v
"""

import json
import argparse
import sys
from pyld import jsonld

# Configure the requests-based document loader
jsonld.set_document_loader(jsonld.requests_document_loader())

# RO-Crate-compatible context: RO-Crate 1.1 base (schema.org terms) plus
# CDIF namespace prefixes AND explicit term mappings so that compaction
# produces unprefixed property names (required by rocrate-validator).
ROCRATE_CONTEXT = [
    "https://w3id.org/ro/crate/1.1/context",
    {
        # --- Namespace prefixes ---
        "dcterms": "http://purl.org/dc/terms/",
        "prov": "http://www.w3.org/ns/prov#",
        "dqv": "http://www.w3.org/ns/dqv#",
        "geosparql": "http://www.opengis.net/ont/geosparql#",
        "spdx": "http://spdx.org/rdf/terms#",
        "cdi": "http://ddialliance.org/Specification/DDI-CDI/1.0/RDF/",
        "csvw": "http://www.w3.org/ns/csvw#",
        "time": "http://www.w3.org/2006/time#",
        "ada": "https://ada.astromat.org/metadata/",
        "xas": "https://ada.astromat.org/metadata/xas/",
        "nxs": "https://manual.nexusformat.org/classes/",

        # --- PROV term mappings ---
        "wasGeneratedBy": {"@id": "prov:wasGeneratedBy", "@container": "@set"},
        "wasDerivedFrom": {"@id": "prov:wasDerivedFrom", "@container": "@set"},
        "used": {"@id": "prov:used", "@container": "@set"},
        "Activity": "prov:Activity",

        # --- SPDX term mappings ---
        "checksum": "spdx:checksum",
        "algorithm": "spdx:algorithm",
        "checksumValue": "spdx:checksumValue",

        # --- DQV term mappings ---
        "hasQualityMeasurement": {"@id": "dqv:hasQualityMeasurement",
                                  "@container": "@set"},
        "isMeasurementOf": "dqv:isMeasurementOf",
        "QualityMeasurement": "dqv:QualityMeasurement",

        # --- GeoSPARQL term mappings ---
        "hasGeometry": "geosparql:hasGeometry",
        "asWKT": "geosparql:asWKT",
        "crs": "geosparql:crs",
        "wktLiteral": "geosparql:wktLiteral",

        # --- OWL-Time term mappings ---
        "ProperInterval": "time:ProperInterval",
        "Instant": "time:Instant",
        "TimePosition": "time:TimePosition",
        "intervalStartedBy": {"@id": "time:intervalStartedBy", "@type": "@id"},
        "intervalFinishedBy": {"@id": "time:intervalFinishedBy", "@type": "@id"},
        "hasBeginning": "time:hasBeginning",
        "hasEnd": "time:hasEnd",
        "inTimePosition": "time:inTimePosition",
        "hasTRS": {"@id": "time:hasTRS", "@type": "@id"},
        "numericPosition": "time:numericPosition",

        # --- DDI-CDI term mappings ---
        "InstanceVariable": "cdi:InstanceVariable",
        "StructuredDataSet": "cdi:StructuredDataSet",
        "TabularTextDataSet": "cdi:TabularTextDataSet",
        "intendedDataType": "cdi:intendedDataType",
        "role": "cdi:role",
        "describedUnitOfMeasure": "cdi:describedUnitOfMeasure",
        "simpleUnitOfMeasure": "cdi:simpleUnitOfMeasure",
        "unitOfMeasureKind": "cdi:unitOfMeasureKind",
        "uses": {"@id": "cdi:uses", "@container": "@set"},
        "characterSet": "cdi:characterSet",
        "fileSize": "cdi:fileSize",
        "fileSizeUofM": "cdi:fileSizeUofM",
        "hasPhysicalMapping": {"@id": "cdi:hasPhysicalMapping",
                               "@container": "@set"},
        "decimalPositions": "cdi:decimalPositions",
        "defaultValue": "cdi:defaultValue",
        "format": "cdi:format",
        "isRequired": "cdi:isRequired",
        "maximumLength": "cdi:maximumLength",
        "minimumLength": "cdi:minimumLength",
        "nullSequence": "cdi:nullSequence",
        "physicalDataType": "cdi:physicalDataType",
        "scale": "cdi:scale",
        "index": "cdi:index",
        "locator": "cdi:locator",
        "formats_InstanceVariable": {"@id": "cdi:formats_InstanceVariable",
                                     "@type": "@id"},
        "arrayBase": "cdi:arrayBase",
        "escapeCharacter": "cdi:escapeCharacter",
        "headerIsCaseSensitive": "cdi:headerIsCaseSensitive",
        "isDelimited": "cdi:isDelimited",
        "isFixedWidth": "cdi:isFixedWidth",
        "treatConsecutiveDelimitersAsOne":
            "cdi:treatConsecutiveDelimitersAsOne",
        "defaultDecimalSeparator": "cdi:defaultDecimalSeparator",
        "defaultDigitalGroupSeparator": "cdi:defaultDigitalGroupSeparator",
        "displayLabel": "cdi:displayLabel",
        "length": "cdi:length",

        # --- CSVW term mappings ---
        "commentPrefix": "csvw:commentPrefix",
        "delimiter": "csvw:delimiter",
        "header": "csvw:header",
        "headerRowCount": "csvw:headerRowCount",
        "lineTerminators": "csvw:lineTerminators",
        "quoteChar": "csvw:quoteChar",
        "skipBlankRows": "csvw:skipBlankRows",
        "skipColumns": "csvw:skipColumns",
        "skipInitialSpace": "csvw:skipInitialSpace",
        "skipRows": "csvw:skipRows",
        "tableDirection": "csvw:tableDirection",
        "textDirection": "csvw:textDirection",
        "trim": "csvw:trim",
    }
]

ROCRATE_CONFORMSTO_URI = "https://w3id.org/ro/crate/1.1"
ROCRATE_CONTEXT_URI = "https://w3id.org/ro/crate/1.1/context"
METADATA_DESCRIPTOR_ID = "ro-crate-metadata.json"
ROOT_DATASET_ID = "./"
DEFAULT_LICENSE_ID = "http://www.opengis.net/def/nil/OGC/0/missing"

# Entity @types that are RO-Crate "Data Entities" (must be in root's hasPart)
ROCRATE_DATA_TYPES = {"Dataset", "File", "MediaObject", "DataDownload"}

# All CDIF-relevant namespace prefixes. Merged into the input document's
# @context before expansion so that prefixed terms like prov:Activity or
# xas:AnalysisEvent resolve to full IRIs even when the input omits them.
# NOTE: schema MUST be http:// (not https://) to match the RO-Crate 1.1 context.
CDIF_NAMESPACES = {
    "schema": "http://schema.org/",
    "dcterms": "http://purl.org/dc/terms/",
    "prov": "http://www.w3.org/ns/prov#",
    "dqv": "http://www.w3.org/ns/dqv#",
    "geosparql": "http://www.opengis.net/ont/geosparql#",
    "spdx": "http://spdx.org/rdf/terms#",
    "cdi": "http://ddialliance.org/Specification/DDI-CDI/1.0/RDF/",
    "csvw": "http://www.w3.org/ns/csvw#",
    "time": "http://www.w3.org/2006/time#",
    "ada": "https://ada.astromat.org/metadata/",
    "xas": "https://ada.astromat.org/metadata/xas/",
    "nxs": "https://manual.nexusformat.org/classes/",
}


def _enrich_context(doc):
    """
    Return a copy of doc with CDIF_NAMESPACES merged into its @context.
    CDIF_NAMESPACES wins on conflict (e.g., forces schema to http://).
    This ensures all prefixed terms expand to full IRIs and that the
    schema.org namespace matches the RO-Crate context (http:// not https://).
    """
    doc = dict(doc)  # shallow copy
    ctx = doc.get("@context")

    if ctx is None:
        doc["@context"] = dict(CDIF_NAMESPACES)
    elif isinstance(ctx, dict):
        merged = dict(ctx)
        merged.update(CDIF_NAMESPACES)  # our namespaces win (force http:// for schema)
        doc["@context"] = merged
    elif isinstance(ctx, list):
        # Prepend a context object that can be overridden, then append ours to win
        new_ctx = []
        for item in ctx:
            new_ctx.append(item)
        new_ctx.append(dict(CDIF_NAMESPACES))
        doc["@context"] = new_ctx
    elif isinstance(ctx, str):
        doc["@context"] = [ctx, dict(CDIF_NAMESPACES)]

    return doc


def convert_to_rocrate(doc):
    """
    Convert a CDIF JSON-LD document (compacted/nested) to RO-Crate form.

    Steps:
    1. Enrich context with CDIF namespaces (so all prefixed terms resolve)
    2. Expand (resolve all prefixes to full IRIs)
    3. Flatten (produce @graph with flat entities, @id references)
    4. Compact with RO-Crate-compatible context (including CDIF term mappings)
    5. Inject metadata descriptor + remap root Dataset @id to "./"
    6. Post-process: unwrap @list, ensure license, ensure hasPart
    """
    # Step 0: Enrich input context
    doc = _enrich_context(doc)

    # Step 1: Expand
    expanded = jsonld.expand(doc)

    # Step 2: Flatten
    flattened = jsonld.flatten(expanded)

    # Step 3: Compact with RO-Crate context
    compacted = jsonld.compact(flattened, ROCRATE_CONTEXT)

    # Ensure @graph is a list
    graph = compacted.get("@graph", [])
    if isinstance(graph, dict):
        graph = [graph]

    # Step 4: Find root Dataset, remap its @id to "./"
    root_id = None
    root_idx = None
    dataset_types = {"Dataset", "schema:Dataset", "http://schema.org/Dataset",
                     "https://schema.org/Dataset"}
    dist_keys = {"distribution", "schema:distribution",
                 "http://schema.org/distribution", "https://schema.org/distribution"}
    for i, entity in enumerate(graph):
        entity_type = entity.get("@type", [])
        if isinstance(entity_type, str):
            entity_type = [entity_type]
        if dataset_types.intersection(entity_type):
            # Heuristic: the root Dataset has distribution or is the "biggest" one.
            # Pick the first entity with distribution, or fall back to first Dataset.
            if root_idx is None:
                root_idx = i
                root_id = entity.get("@id")
            if dist_keys.intersection(entity.keys()):
                root_idx = i
                root_id = entity.get("@id")
                break

    if root_id is not None and root_id != ROOT_DATASET_ID:
        old_id = root_id
        # Remap all references to the old root @id
        graph = _remap_id(graph, old_id, ROOT_DATASET_ID)

    # Inject metadata descriptor
    descriptor = {
        "@id": METADATA_DESCRIPTOR_ID,
        "@type": "CreativeWork",
        "conformsTo": {"@id": ROCRATE_CONFORMSTO_URI},
        "about": {"@id": ROOT_DATASET_ID}
    }
    graph.insert(0, descriptor)

    # Step 6: Post-process for RO-Crate compliance
    graph = _unwrap_lists(graph)
    _ensure_license(graph)
    _ensure_haspart(graph)

    result = {
        "@context": ROCRATE_CONTEXT,
        "@graph": graph
    }
    return result


def _remap_id(graph, old_id, new_id):
    """Remap all occurrences of old_id to new_id throughout the @graph."""
    def _remap_value(val):
        if isinstance(val, str):
            return new_id if val == old_id else val
        if isinstance(val, dict):
            return _remap_obj(val)
        if isinstance(val, list):
            return [_remap_value(item) for item in val]
        return val

    def _remap_obj(obj):
        result = {}
        for k, v in obj.items():
            if k == "@id" and v == old_id:
                result[k] = new_id
            else:
                result[k] = _remap_value(v)
        return result

    return [_remap_obj(entity) for entity in graph]


# ---------------------------------------------------------------------------
# RO-Crate post-processing (fix issues that compaction alone cannot handle)
# ---------------------------------------------------------------------------

def _unwrap_lists(graph):
    """Replace {@list: [...]} wrappers with plain arrays throughout @graph.

    RO-Crate requires flat @id references, not JSON-LD @list containers.
    """
    for entity in graph:
        for key in list(entity.keys()):
            if key.startswith("@"):
                continue
            entity[key] = _unwrap_list_value(entity[key])
    return graph


def _unwrap_list_value(val):
    """Recursively unwrap @list to plain value or array."""
    if isinstance(val, dict):
        if "@list" in val and len(val) == 1:
            inner = val["@list"]
            if isinstance(inner, list):
                unwrapped = [_unwrap_list_value(v) for v in inner]
                return unwrapped[0] if len(unwrapped) == 1 else unwrapped
            return inner
        return val
    if isinstance(val, list):
        return [_unwrap_list_value(v) for v in val]
    return val


def _ensure_license(graph):
    """Add default license to root Dataset if missing."""
    for entity in graph:
        if entity.get("@id") == ROOT_DATASET_ID:
            if "license" not in entity:
                entity["license"] = {"@id": DEFAULT_LICENSE_ID}
            break


def _ensure_haspart(graph):
    """Ensure all Data Entities in @graph are in root's hasPart."""
    root = None
    for entity in graph:
        if entity.get("@id") == ROOT_DATASET_ID:
            root = entity
            break
    if root is None:
        return

    # Collect existing hasPart @id references
    has_part = root.get("hasPart", [])
    if isinstance(has_part, dict):
        has_part = [has_part]
    existing = set()
    for ref in has_part:
        if isinstance(ref, dict) and "@id" in ref:
            existing.add(ref["@id"])
        elif isinstance(ref, str):
            existing.add(ref)

    # Find Data Entities not already referenced
    new_refs = []
    for entity in graph:
        eid = entity.get("@id")
        if not eid or eid in (ROOT_DATASET_ID, METADATA_DESCRIPTOR_ID):
            continue
        if eid in existing:
            continue
        etype = entity.get("@type", [])
        if isinstance(etype, str):
            etype = [etype]
        if ROCRATE_DATA_TYPES.intersection(etype):
            new_refs.append({"@id": eid})

    if new_refs:
        root["hasPart"] = has_part + new_refs


def main():
    parser = argparse.ArgumentParser(
        description='Convert CDIF JSON-LD to RO-Crate 1.1 form',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Convert CDIF to RO-Crate form and write to file
  python ConvertToROCrate.py input.jsonld -o output-rocrate.jsonld

  # Convert and print to stdout
  python ConvertToROCrate.py input.jsonld

  # Verbose output
  python ConvertToROCrate.py input.jsonld -o output.jsonld -v
"""
    )
    parser.add_argument('input', help='Input JSON-LD file to convert')
    parser.add_argument('-o', '--output', help='Write RO-Crate output to file (default: stdout)')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Show detailed progress output')

    args = parser.parse_args()

    try:
        if args.verbose:
            print(f"Loading: {args.input}", file=sys.stderr)
        with open(args.input, 'r', encoding='utf-8') as f:
            doc = json.load(f)

        if args.verbose:
            print("Converting CDIF JSON-LD to RO-Crate form...", file=sys.stderr)
            print("  Expanding...", file=sys.stderr)
            print("  Flattening...", file=sys.stderr)
            print("  Compacting with RO-Crate context...", file=sys.stderr)
            print("  Injecting metadata descriptor + remapping root @id...", file=sys.stderr)

        rocrate = convert_to_rocrate(doc)

        if args.verbose:
            print("Conversion complete.", file=sys.stderr)

        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(rocrate, f, indent=2)
            if args.verbose:
                print(f"RO-Crate output written to: {args.output}", file=sys.stderr)
        else:
            json.dump(rocrate, sys.stdout, indent=2)
            print()  # trailing newline

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
