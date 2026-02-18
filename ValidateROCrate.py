#!/usr/bin/env python3
"""
RO-Crate Conformance Validator for CDIF JSON-LD

Transforms CDIF JSON-LD (compacted/nested) into RO-Crate form (flattened @graph)
and validates against RO-Crate 1.1 structural requirements.

This is the inverse of FrameAndValidate.py: instead of framing @graph into a
nested tree, it expands+flattens into @graph and validates RO-Crate constraints.

Usage:
    # Convert CDIF to RO-Crate form and validate
    python ValidateROCrate.py input.jsonld

    # Just validate (already in @graph form)
    python ValidateROCrate.py input.jsonld --no-convert

    # Convert and save the RO-Crate output
    python ValidateROCrate.py input.jsonld -o output-rocrate.jsonld

    # Verbose output
    python ValidateROCrate.py input.jsonld -v
"""

import json
import argparse
import sys
from pyld import jsonld

# Configure the requests-based document loader
jsonld.set_document_loader(jsonld.requests_document_loader())

# RO-Crate-compatible context: unprefixed schema.org terms + CDIF namespaces
ROCRATE_CONTEXT = [
    "https://w3id.org/ro/crate/1.1/context",
    {
        "dcterms": "http://purl.org/dc/terms/",
        "prov": "http://www.w3.org/ns/prov#",
        "dqv": "http://www.w3.org/ns/dqv#",
        "geosparql": "http://www.opengis.net/ont/geosparql#",
        "spdx": "http://spdx.org/rdf/terms#",
        "cdi": "http://ddialliance.org/Specification/DDI-CDI/1.0/RDF/",
        "csvw": "http://www.w3.org/ns/csvw#",
        "time": "http://www.w3.org/2006/time#"
    }
]

ROCRATE_CONFORMSTO_URI = "https://w3id.org/ro/crate/1.1"
ROCRATE_CONTEXT_URI = "https://w3id.org/ro/crate/1.1/context"
METADATA_DESCRIPTOR_ID = "ro-crate-metadata.json"
ROOT_DATASET_ID = "./"

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
    4. Compact with RO-Crate-compatible context
    5. Inject metadata descriptor + remap root Dataset @id to "./"
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
# Validation
# ---------------------------------------------------------------------------

PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"


def validate_rocrate(doc, verbose=False):
    """
    Validate a document against RO-Crate 1.1 structural requirements.

    Returns a list of (level, check_number, description, detail) tuples.
    """
    results = []

    def add(level, num, desc, detail=""):
        results.append((level, num, desc, detail))

    # --- Check 1: @context exists ---
    has_context = "@context" in doc
    if has_context:
        add(PASS, 1, "@context present")
    else:
        add(FAIL, 1, "@context missing")

    # --- Check 2: @graph array ---
    graph = doc.get("@graph")
    has_graph = isinstance(graph, list)
    if has_graph:
        add(PASS, 2, f"@graph is an array ({len(graph)} entities)")
    elif graph is not None:
        add(FAIL, 2, "@graph exists but is not an array")
        graph = [graph] if isinstance(graph, dict) else []
    else:
        add(FAIL, 2, "@graph missing")
        graph = []

    # Build lookup
    entities_by_id = {}
    for entity in graph:
        eid = entity.get("@id")
        if eid:
            entities_by_id[eid] = entity

    # --- Check 3: Metadata Descriptor ---
    descriptor = entities_by_id.get(METADATA_DESCRIPTOR_ID)
    if descriptor:
        conforms = descriptor.get("conformsTo", descriptor.get("dcterms:conformsTo"))
        has_conforms = False
        if isinstance(conforms, dict) and conforms.get("@id") == ROCRATE_CONFORMSTO_URI:
            has_conforms = True
        elif isinstance(conforms, list):
            has_conforms = any(
                isinstance(c, dict) and c.get("@id") == ROCRATE_CONFORMSTO_URI
                for c in conforms
            )
        elif isinstance(conforms, str) and conforms == ROCRATE_CONFORMSTO_URI:
            has_conforms = True

        if has_conforms:
            add(PASS, 3, "Metadata descriptor present with conformsTo")
        else:
            add(FAIL, 3, "Metadata descriptor exists but missing/wrong conformsTo",
                f"Expected conformsTo @id: {ROCRATE_CONFORMSTO_URI}")
    else:
        add(FAIL, 3, "Metadata descriptor (ro-crate-metadata.json) not found in @graph")

    # --- Check 4: Root Data Entity ---
    root = entities_by_id.get(ROOT_DATASET_ID)
    if root:
        root_type = root.get("@type", [])
        if isinstance(root_type, str):
            root_type = [root_type]
        if "Dataset" in root_type or "schema:Dataset" in root_type:
            add(PASS, 4, "Root data entity (./) present with type Dataset")
        else:
            add(FAIL, 4, "Root entity (./) exists but @type does not include Dataset",
                f"Found @type: {root_type}")
    else:
        add(FAIL, 4, 'Root data entity (@id: "./") not found in @graph')

    # --- Check 5: Root datePublished ---
    if root:
        date_pub = root.get("datePublished", root.get("schema:datePublished"))
        if date_pub:
            add(PASS, 5, f"Root dataset has datePublished: {date_pub}")
        else:
            add(FAIL, 5, "Root dataset missing datePublished (MUST per RO-Crate spec)")
    else:
        add(FAIL, 5, "Cannot check datePublished --root dataset not found")

    # --- Check 6: All entities have @id ---
    missing_id = []
    for i, entity in enumerate(graph):
        if "@id" not in entity:
            missing_id.append(i)
    if missing_id:
        add(FAIL, 6, f"{len(missing_id)} entities missing @id",
            f"Entity indices: {missing_id}")
    else:
        add(PASS, 6, "All entities have @id")

    # --- Check 7: All entities have @type ---
    missing_type = []
    for i, entity in enumerate(graph):
        if "@type" not in entity:
            missing_type.append((i, entity.get("@id", "?")))
    if missing_type:
        ids = [f"{idx} ({eid})" for idx, eid in missing_type]
        add(FAIL, 7, f"{len(missing_type)} entities missing @type",
            f"Entities: {', '.join(ids)}")
    else:
        add(PASS, 7, "All entities have @type")

    # --- Check 8: No nested entities (flatness) ---
    nested = _find_nested_entities(graph)
    if nested:
        add(FAIL, 8, f"{len(nested)} nested entities found (should be flat @id refs)",
            "; ".join(nested[:5]) + ("..." if len(nested) > 5 else ""))
    else:
        add(PASS, 8, "No nested entities -- @graph is flat")

    # --- Check 9: No ../ in @id paths ---
    bad_ids = []
    for entity in graph:
        eid = entity.get("@id", "")
        if "../" in eid:
            bad_ids.append(eid)
    if bad_ids:
        add(FAIL, 9, f"{len(bad_ids)} @id values contain '../'",
            ", ".join(bad_ids))
    else:
        add(PASS, 9, "No @id values contain '../'")

    # --- Check 10: Root has name (SHOULD) ---
    if root:
        name = root.get("name", root.get("schema:name"))
        if name:
            add(PASS, 10, f"Root dataset has name")
        else:
            add(WARN, 10, "Root dataset missing name (SHOULD per RO-Crate spec)")
    else:
        add(WARN, 10, "Cannot check name --root dataset not found")

    # --- Check 11: Root has description (SHOULD) ---
    if root:
        desc = root.get("description", root.get("schema:description"))
        if desc:
            add(PASS, 11, "Root dataset has description")
        else:
            add(WARN, 11, "Root dataset missing description (SHOULD per RO-Crate spec)")
    else:
        add(WARN, 11, "Cannot check description --root dataset not found")

    # --- Check 12: Root has license (SHOULD) ---
    if root:
        lic = root.get("license", root.get("schema:license"))
        if lic:
            add(PASS, 12, "Root dataset has license")
        else:
            add(WARN, 12, "Root dataset missing license (SHOULD per RO-Crate spec)")
    else:
        add(WARN, 12, "Cannot check license --root dataset not found")

    # --- Check 13: @context references RO-Crate 1.1 context (SHOULD) ---
    if has_context:
        ctx = doc["@context"]
        has_rocrate_ctx = _context_references_rocrate(ctx)
        if has_rocrate_ctx:
            add(PASS, 13, "@context references RO-Crate 1.1 context")
        else:
            add(WARN, 13, "@context does not reference RO-Crate 1.1 context",
                f"Expected: {ROCRATE_CONTEXT_URI}")
    else:
        add(WARN, 13, "Cannot check @context reference --@context missing")

    return results


def _context_references_rocrate(ctx):
    """Check if the @context includes the RO-Crate 1.1 context URI."""
    if isinstance(ctx, str):
        return ROCRATE_CONTEXT_URI in ctx
    if isinstance(ctx, list):
        return any(
            isinstance(item, str) and ROCRATE_CONTEXT_URI in item
            for item in ctx
        )
    return False


def _find_nested_entities(graph):
    """
    Find properties in @graph entities that contain nested objects
    (objects with @type but not just @id references).
    Returns a list of descriptions like "entity X, property Y".
    """
    nested = []
    for entity in graph:
        eid = entity.get("@id", "?")
        for key, value in entity.items():
            if key.startswith("@"):
                continue
            _check_nested(eid, key, value, nested)
    return nested


def _check_nested(entity_id, prop, value, nested):
    """Recursively check for nested entities in a property value."""
    if isinstance(value, dict):
        # A dict with only @id is a valid reference
        keys = set(value.keys())
        if keys == {"@id"}:
            return
        # A dict with @type (and other properties) is a nested entity
        if "@type" in value:
            nested.append(f"{entity_id} -> {prop}")
            return
        # A dict with @id plus other keys is also nested
        if "@id" in value and len(keys) > 1:
            nested.append(f"{entity_id} -> {prop}")
            return
        # A bare @value dict is fine (JSON-LD literal)
        if "@value" in value:
            return
        # A bare @list is fine
        if "@list" in value:
            _check_nested(entity_id, prop, value["@list"], nested)
            return
        # Other dicts with multiple properties but no @id/@type --could be
        # structured values; flag if they look entity-like
        if len(keys) > 1 and not keys.issubset({"@value", "@language", "@type"}):
            nested.append(f"{entity_id} -> {prop}")
    elif isinstance(value, list):
        for item in value:
            _check_nested(entity_id, prop, item, nested)


def print_results(results, verbose=False):
    """Print validation results."""
    fails = [r for r in results if r[0] == FAIL]
    warns = [r for r in results if r[0] == WARN]
    passes = [r for r in results if r[0] == PASS]

    print(f"\n{'='*60}")
    print(f"RO-Crate 1.1 Validation Results")
    print(f"{'='*60}")

    for level, num, desc, detail in results:
        if level == PASS:
            marker = f"  PASS"
        elif level == WARN:
            marker = f"  WARN"
        else:
            marker = f"  FAIL"

        print(f"{marker}  [{num:2d}] {desc}")
        if detail and (verbose or level != PASS):
            print(f"              {detail}")

    print(f"\n{'-'*60}")
    print(f"Summary: {len(passes)} passed, {len(warns)} warnings, {len(fails)} failures")

    if not fails:
        if warns:
            print("Result: VALID (with warnings)")
        else:
            print("Result: VALID")
    else:
        print("Result: INVALID")

    return len(fails) == 0


def main():
    parser = argparse.ArgumentParser(
        description='RO-Crate Conformance Validator for CDIF JSON-LD',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Convert CDIF to RO-Crate form and validate
  python ValidateROCrate.py input.jsonld

  # Just validate (already in @graph form)
  python ValidateROCrate.py input.jsonld --no-convert

  # Convert and save the RO-Crate output
  python ValidateROCrate.py input.jsonld -o output-rocrate.jsonld

  # Verbose output
  python ValidateROCrate.py input.jsonld -v
"""
    )
    parser.add_argument('input', help='Input JSON-LD file to process')
    parser.add_argument('-o', '--output', help='Write RO-Crate output to file')
    parser.add_argument('--no-convert', action='store_true',
                        help='Skip conversion --validate input as-is')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Show detailed output including PASS details')

    args = parser.parse_args()

    try:
        print(f"Loading: {args.input}")
        with open(args.input, 'r', encoding='utf-8') as f:
            doc = json.load(f)

        if args.no_convert:
            print("Skipping conversion (--no-convert)")
            rocrate = doc
        else:
            print("Converting CDIF JSON-LD to RO-Crate form...")
            print("  Expanding...")
            print("  Flattening...")
            print("  Compacting with RO-Crate context...")
            print("  Injecting metadata descriptor + remapping root @id...")
            rocrate = convert_to_rocrate(doc)
            print("Conversion complete.")

        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(rocrate, f, indent=2)
            print(f"RO-Crate output written to: {args.output}")

        print("\nValidating against RO-Crate 1.1 requirements...")
        results = validate_rocrate(rocrate, verbose=args.verbose)
        valid = print_results(results, verbose=args.verbose)

        if not valid:
            sys.exit(1)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
