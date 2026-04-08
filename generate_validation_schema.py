#!/usr/bin/env python3
"""Generate framed-tree validation schema from a building block profile resolved schema.

Takes a resolved profile schema (e.g., CDIFDiscoveryProfile/resolvedSchema.json) and produces
a compact, self-contained JSON Schema with $defs for repeated sub-schemas.

Usage:
    python generate_validation_schema.py <resolved_schema> [-o output.json] [-v]

Example:
    python generate_validation_schema.py path/to/CDIFDiscoveryProfile/resolvedSchema.json -o CDIFDiscoverySchema.json
    python generate_validation_schema.py path/to/CDIFcompleteProfile/resolvedSchema.json -o CDIFCompleteSchema.json
"""

import argparse
import copy
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path


# Minimum byte size for a sub-schema to be considered for extraction
MIN_EXTRACT_SIZE = 400

# Keys ignored when computing structural fingerprints (documentation-only fields)
IGNORED_KEYS = {"description", "title", "examples", "$comment"}


# ---------------------------------------------------------------------------
# 1.  allOf deep-merge
# ---------------------------------------------------------------------------

def _merge_properties(base, overlay):
    """Merge overlay properties into base, recursively for nested objects."""
    for key, val in overlay.items():
        if key not in base:
            base[key] = copy.deepcopy(val)
        else:
            if isinstance(base[key], dict) and isinstance(val, dict):
                _merge_properties(base[key], val)
            elif isinstance(base[key], list) and isinstance(val, list):
                for item in val:
                    if item not in base[key]:
                        base[key].append(copy.deepcopy(item))
            else:
                base[key] = copy.deepcopy(val)


def merge_allof(schema):
    """Flatten top-level allOf into a single merged schema.

    Collects properties (deep-merged), required arrays (unioned),
    conditional anyOf constraints (preserved in allOf), and $defs
    (merged from root and all allOf entries).
    """
    if "allOf" not in schema:
        return copy.deepcopy(schema)

    merged = {}
    all_properties = {}
    all_required = []
    top_constraints = []
    all_defs = {}

    def _collect(obj):
        if not isinstance(obj, dict):
            return

        if "allOf" in obj:
            for sub in obj["allOf"]:
                _collect(sub)
            rest = {k: v for k, v in obj.items() if k != "allOf"}
            if rest:
                _collect(rest)
            return

        if "properties" in obj:
            _merge_properties(all_properties, obj["properties"])

        if "required" in obj:
            for r in obj["required"]:
                if r not in all_required:
                    all_required.append(r)

        # Collect $defs from allOf entries and root
        if "$defs" in obj:
            for name, defn in obj["$defs"].items():
                if name not in all_defs:
                    all_defs[name] = copy.deepcopy(defn)

        # Capture standalone anyOf blocks (conditional required patterns)
        if "anyOf" in obj and "properties" not in obj and "type" not in obj:
            top_constraints.append({"anyOf": copy.deepcopy(obj["anyOf"])})

        for key in ("$schema", "type", "title", "description"):
            if key in obj and key not in merged:
                merged[key] = obj[key]

    # Collect $defs from root level (outside allOf)
    if "$defs" in schema:
        for name, defn in schema["$defs"].items():
            if name not in all_defs:
                all_defs[name] = copy.deepcopy(defn)

    for entry in schema["allOf"]:
        _collect(entry)

    if "$schema" not in merged:
        merged["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    merged["type"] = merged.get("type", "object")
    merged["properties"] = all_properties

    result_allof = []
    if all_required:
        seen = set()
        deduped = [r for r in all_required if r not in seen and not seen.add(r)]
        result_allof.append({"required": deduped})
    result_allof.extend(top_constraints)

    if result_allof:
        merged["allOf"] = result_allof

    if all_defs:
        merged["$defs"] = all_defs

    return merged


# ---------------------------------------------------------------------------
# 2.  Sub-schema fingerprinting and deduplication
# ---------------------------------------------------------------------------

def canonical_json(obj):
    """Deterministic JSON string for hashing."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False)


def _strip_docs(obj):
    """Return a copy of obj with documentation-only keys removed (recursive).

    Used for structural fingerprinting so schemas differing only in
    descriptions/titles/examples are grouped together.
    """
    if isinstance(obj, dict):
        return {k: _strip_docs(v) for k, v in obj.items()
                if k not in IGNORED_KEYS}
    if isinstance(obj, list):
        return [_strip_docs(item) for item in obj]
    return obj


def structural_fingerprint(obj):
    """MD5 of canonical JSON with doc keys stripped."""
    stripped = _strip_docs(obj)
    return hashlib.md5(canonical_json(stripped).encode()).hexdigest()


def exact_fingerprint(obj):
    """MD5 of exact canonical JSON."""
    return hashlib.md5(canonical_json(obj).encode()).hexdigest()


def _is_extractable(obj):
    """True if obj looks like a sub-schema worth extracting to $defs.

    Rejects trivially simple schemas (bare primitive types like {"type": "string"})
    even if their descriptions push them over the size threshold.  Only schemas
    with real structural content (properties, combinators, constraints beyond
    a single primitive type) are worth deduplicating.
    """
    if not isinstance(obj, dict):
        return False
    has_structure = any(k in obj for k in ("type", "anyOf", "oneOf", "allOf", "properties"))
    if not has_structure:
        return False

    # Reject bare primitives: after stripping doc-only keys, if what remains
    # is just {"type": "<primitive>"} (possibly with "format"), it is too
    # simple to warrant a $def — leave it inline.
    stripped = _strip_docs(obj)
    non_doc_keys = set(stripped.keys())
    if non_doc_keys <= {"type", "format"}:
        return False
    # Also reject {"type": "string"/"number"/"integer"/"boolean"} with only
    # simple scalar constraints (min/max, pattern, enum, const, default)
    SCALAR_KEYS = {"type", "format", "minimum", "maximum", "exclusiveMinimum",
                   "exclusiveMaximum", "minLength", "maxLength", "pattern",
                   "enum", "const", "default"}
    if non_doc_keys <= SCALAR_KEYS and stripped.get("type") in (
            "string", "number", "integer", "boolean"):
        return False

    # Reject array wrappers: {type: "array", items: ...} schemas should stay
    # inline so that per-property descriptions are preserved.  The items
    # content will be extracted separately if it repeats enough.
    if stripped.get("type") == "array" and "items" in stripped:
        array_keys = non_doc_keys - {"type", "items", "minItems", "maxItems",
                                      "uniqueItems", "contains"}
        if not array_keys:
            return False

    return len(canonical_json(obj)) >= MIN_EXTRACT_SIZE


def _get_type_name(obj):
    """Extract the primary type name from a sub-schema's @type property."""
    at_type = obj.get("properties", {}).get("@type", {})
    if not isinstance(at_type, dict):
        return None

    # Direct const
    if "const" in at_type:
        return at_type["const"]

    # anyOf with const
    if "anyOf" in at_type:
        for opt in at_type["anyOf"]:
            if isinstance(opt, dict) and "const" in opt:
                return opt["const"]

    # contains with const
    contains = at_type.get("contains", {})
    if isinstance(contains, dict) and "const" in contains:
        return contains["const"]

    # contains with enum (take first)
    if isinstance(contains, dict) and "enum" in contains:
        enums = contains["enum"]
        if enums:
            return enums[0]

    return None


def _type_to_def_name(type_name):
    """Convert a prefixed type name to a $def name.  schema:Person -> person_type"""
    short = type_name.split(":")[-1] if ":" in type_name else type_name
    if not short:
        return None
    return short[0].lower() + short[1:] + "_type"


def _path_to_def_name(path):
    """Derive a $def name from the schema path."""
    parts = path.strip("/").split("/")
    for p in reversed(parts):
        if p not in ("properties", "items", "anyOf", "oneOf", "allOf",
                      "0", "1", "2", "3", "4", "5"):
            short = p.split(":")[-1] if ":" in p else p
            if short:
                return short[0].lower() + short[1:] + "_type"
    return None


def _collision_name(path, obj):
    """Generate a more specific name when the primary name collides.

    Uses parent property context and/or distinguishing schema features
    to create a unique, readable name rather than appending _2, _3.
    """
    parts = path.strip("/").split("/")
    # Collect meaningful path segments (skip structural keywords)
    meaningful = [p.split(":")[-1] if ":" in p else p
                  for p in parts
                  if p not in ("properties", "items", "anyOf", "oneOf",
                               "allOf", "0", "1", "2", "3", "4", "5")]

    # Try parent + child combination
    if len(meaningful) >= 2:
        parent = meaningful[-2]
        child = meaningful[-1]
        name = parent[0].lower() + parent[1:] + "_" + child[0].lower() + child[1:] + "_type"
        return name

    # Try distinguishing by @type const/enum
    type_name = _get_type_name(obj)
    if type_name:
        short = type_name.split(":")[-1]
        # Include first meaningful ancestor for context
        if meaningful:
            ancestor = meaningful[0]
            return ancestor[0].lower() + ancestor[1:] + "_" + short[0].lower() + short[1:] + "_type"

    return None


def collect_sub_schemas(schema, path="", results=None):
    """Walk schema tree collecting all extractable sub-schemas."""
    if results is None:
        results = []

    if isinstance(schema, dict):
        if path and _is_extractable(schema):
            sfp = structural_fingerprint(schema)
            results.append((sfp, path, schema))

        for key, val in schema.items():
            if key == "$defs":
                continue
            child_path = f"{path}/{key}"
            if isinstance(val, dict):
                collect_sub_schemas(val, child_path, results)
            elif isinstance(val, list):
                for i, item in enumerate(val):
                    if isinstance(item, dict):
                        collect_sub_schemas(item, f"{child_path}/{i}", results)

    return results


def find_extractable_defs(schema, min_occurrences=2):
    """Find sub-schemas appearing >= min_occurrences times (by structure).

    Returns dict: def_name -> {schema, structural_fp, count, paths}
    """
    all_subs = collect_sub_schemas(schema)

    # Group by structural fingerprint
    by_sfp = defaultdict(list)
    for sfp, path, obj in all_subs:
        by_sfp[sfp].append((path, obj))

    candidates = {}
    used_names = set()

    # Process highest-count first for best naming
    sorted_groups = sorted(by_sfp.items(), key=lambda x: -len(x[1]))

    for sfp, occurrences in sorted_groups:
        if len(occurrences) < min_occurrences:
            continue

        path0, obj0 = occurrences[0]

        # Determine name
        type_name = _get_type_name(obj0)
        if type_name:
            name = _type_to_def_name(type_name)
        else:
            name = _path_to_def_name(path0)
        if not name:
            name = f"def_{sfp[:8]}"

        # Handle collisions: try contextual name before falling back to _2, _3
        if name in used_names:
            contextual = _collision_name(path0, obj0)
            if contextual and contextual not in used_names:
                name = contextual
            else:
                base_name = name
                counter = 2
                while name in used_names:
                    name = f"{base_name}_{counter}"
                    counter += 1
        used_names.add(name)

        candidates[name] = {
            "schema": copy.deepcopy(obj0),
            "structural_fp": sfp,
            "count": len(occurrences),
            "paths": [p for p, _ in occurrences],
        }

    return candidates


# ---------------------------------------------------------------------------
# 3.  Replace inline schemas with $ref
# ---------------------------------------------------------------------------

def replace_with_refs(schema, sfp_to_name):
    """Walk schema replacing sub-schemas matching structural fingerprints with $ref."""
    if isinstance(schema, dict):
        if _is_extractable(schema):
            sfp = structural_fingerprint(schema)
            if sfp in sfp_to_name:
                return {"$ref": f"#/$defs/{sfp_to_name[sfp]}"}

        result = {}
        for key, val in schema.items():
            if key == "$defs":
                result[key] = val
            elif isinstance(val, dict):
                result[key] = replace_with_refs(val, sfp_to_name)
            elif isinstance(val, list):
                result[key] = [
                    replace_with_refs(item, sfp_to_name) if isinstance(item, dict) else item
                    for item in val
                ]
            else:
                result[key] = val
        return result
    return schema


def _process_defs_recursively(defs_dict, sfp_to_name):
    """Replace refs within $defs entries themselves (nested dedup).

    Processes smallest-first so inner types get replaced in outer types.
    """
    sorted_names = sorted(defs_dict.keys(),
                          key=lambda n: len(canonical_json(defs_dict[n])))

    incremental_map = {}
    processed = {}

    for name in sorted_names:
        schema_obj = defs_dict[name]
        if incremental_map:
            schema_obj = replace_with_refs(schema_obj, incremental_map)
        processed[name] = schema_obj
        # Map the structural fp of the ORIGINAL (pre-replacement) schema
        sfp = structural_fingerprint(defs_dict[name])
        incremental_map[sfp] = name

    return processed


# ---------------------------------------------------------------------------
# 4.  Post-processing: prune redundant $defs
# ---------------------------------------------------------------------------

def _count_refs(schema, counts=None):
    """Count how many times each $def is referenced."""
    if counts is None:
        counts = defaultdict(int)
    if isinstance(schema, dict):
        if "$ref" in schema:
            ref = schema["$ref"]
            if ref.startswith("#/$defs/"):
                name = ref[len("#/$defs/"):]
                counts[name] += 1
        for key, val in schema.items():
            if key == "$defs":
                # Count refs within $defs too
                for dname, dschema in val.items():
                    _count_refs(dschema, counts)
            elif isinstance(val, dict):
                _count_refs(val, counts)
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, dict):
                        _count_refs(item, counts)
    return counts


def _inline_ref(schema, defs):
    """Replace a single $ref with its inline definition (recurses into $defs too)."""
    if isinstance(schema, dict):
        if "$ref" in schema and schema["$ref"].startswith("#/$defs/"):
            name = schema["$ref"][len("#/$defs/"):]
            if name in defs:
                return copy.deepcopy(defs[name])
        result = {}
        for key, val in schema.items():
            if isinstance(val, dict):
                result[key] = _inline_ref(val, defs)
            elif isinstance(val, list):
                result[key] = [
                    _inline_ref(item, defs) if isinstance(item, dict) else item
                    for item in val
                ]
            else:
                result[key] = val
        return result
    return schema


def prune_single_use_defs(schema):
    """Inline $defs that are only referenced once (not worth the indirection).

    Iterates until stable because inlining a def that was referenced from
    inside another def may leave that other def's ref count unchanged while
    removing the target — so we must also inline *within* $defs entries.
    """
    result = copy.deepcopy(schema)

    while True:
        defs = result.get("$defs", {})
        if not defs:
            break

        counts = _count_refs(result)
        single_use = {name for name, count in counts.items() if count <= 1}
        if not single_use:
            break

        single_defs = {name: defs[name] for name in single_use if name in defs}
        if not single_defs:
            break

        # First resolve refs *within* the single-use defs themselves so that
        # when they get inlined into their parent, all nested refs are resolved.
        changed = True
        while changed:
            changed = False
            for name in list(single_defs):
                replaced = _inline_ref(single_defs[name], single_defs)
                if replaced != single_defs[name]:
                    single_defs[name] = replaced
                    changed = True

        # Inline in main schema body
        result = _inline_ref(result, single_defs)

        # Remove pruned defs
        if "$defs" in result:
            result["$defs"] = {
                k: v for k, v in result["$defs"].items()
                if k not in single_use
            }
            if not result["$defs"]:
                del result["$defs"]

    return result


# ---------------------------------------------------------------------------
# 5.  Semantic post-processing
# ---------------------------------------------------------------------------

# $def renames: old_name -> new_name
_DEF_RENAMES = {
    "conditionsOfAccess_type": "nameOrReference_type",
}

# $defs that should be consolidated into a single canonical $def.
# Maps old_def_name -> canonical_def_name.  The canonical def is injected
# if it does not already exist.  All $refs to old names are rewritten.
_DEF_CONSOLIDATIONS = {
    "measurementTechnique_type":   "nameOrDefinedTerm_type",
    "measurementTechnique_type_2": "nameOrDefinedTerm_type",
    "serviceType_type":            "nameOrDefinedTerm_type",
    "linkRelationship_type":       "nameOrDefinedTerm_type",
    "identifier_type_2":           "identifier_type",
}

# Canonical $def schemas injected when referenced by _DEF_CONSOLIDATIONS.
# Only used if the canonical def was not already extracted by the dedup engine.
_INJECTED_DEFS = {
    "nameOrDefinedTerm_type": {
        "anyOf": [
            {"type": "string"},
            {"$ref": "#/$defs/definedTerm_type"},
        ]
    },
    "identifier_type": {
        "anyOf": [
            {"type": "string"},
            {"$ref": "#/$defs/propertyValue_type"},
        ]
    },
}


def _rename_refs(obj, old_ref, new_ref):
    """Recursively rename $ref strings throughout a schema."""
    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            if k == "$ref" and v == old_ref:
                result[k] = new_ref
            elif isinstance(v, (dict, list)):
                result[k] = _rename_refs(v, old_ref, new_ref)
            else:
                result[k] = v
        return result
    if isinstance(obj, list):
        return [_rename_refs(item, old_ref, new_ref)
                if isinstance(item, (dict, list)) else item
                for item in obj]
    return obj


def _replace_ref_with_inline(obj, target_ref, inline_schema):
    """Replace every {$ref: target_ref} with a copy of inline_schema."""
    if isinstance(obj, dict):
        if "$ref" in obj and obj["$ref"] == target_ref and len(obj) == 1:
            return copy.deepcopy(inline_schema)
        return {k: _replace_ref_with_inline(v, target_ref, inline_schema)
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [_replace_ref_with_inline(item, target_ref, inline_schema)
                for item in obj]
    return obj


def _postprocess_defs(schema, verbose=False):
    """Apply semantic renames and unwrap trivial array-wrapper $defs."""
    defs = schema.get("$defs", {})
    if not defs:
        return schema

    result = copy.deepcopy(schema)
    result_defs = result["$defs"]

    # 1. Consolidate $defs: rewrite refs from old names to canonical name,
    #    inject the canonical $def, and remove the old ones.
    #    Array-wrapper defs (type:array with items.$ref) get their refs
    #    replaced with an inline array wrapping the canonical $ref.
    injected = set()
    for old_name, canonical_name in _DEF_CONSOLIDATIONS.items():
        if old_name not in result_defs:
            continue
        old_def = result_defs[old_name]
        old_ref = f"#/$defs/{old_name}"
        canonical_ref = f"#/$defs/{canonical_name}"

        # Detect if old def is an array wrapper
        is_array_wrapper = (old_def.get("type") == "array"
                            and isinstance(old_def.get("items"), dict))

        if is_array_wrapper:
            # Replace $ref to old with inline array of canonical
            inline = {"type": "array", "items": {"$ref": canonical_ref}}
            result = _replace_ref_with_inline(result, old_ref, inline)
            if verbose:
                print(f"  Consolidated array $def: {old_name} -> inline "
                      f"array of {canonical_name}", file=sys.stderr)
        else:
            # Simple ref rename
            result = _rename_refs(result, old_ref, canonical_ref)
            if verbose:
                print(f"  Consolidated $def: {old_name} -> {canonical_name}",
                      file=sys.stderr)

        # Remove old def
        result_defs = result.get("$defs", {})
        result_defs.pop(old_name, None)

        # Inject canonical def if not yet present
        if canonical_name not in result_defs and canonical_name not in injected:
            if canonical_name in _INJECTED_DEFS:
                result_defs[canonical_name] = copy.deepcopy(
                    _INJECTED_DEFS[canonical_name])
                injected.add(canonical_name)
                if verbose:
                    print(f"  Injected $def: {canonical_name}", file=sys.stderr)

    # 2. Rename $defs
    result_defs = result.get("$defs", {})
    for old_name, new_name in _DEF_RENAMES.items():
        if old_name not in result_defs:
            continue
        result_defs[new_name] = result_defs.pop(old_name)
        old_ref = f"#/$defs/{old_name}"
        new_ref = f"#/$defs/{new_name}"
        result = _rename_refs(result, old_ref, new_ref)
        result_defs = result.get("$defs", {})
        if verbose:
            print(f"  Renamed $def: {old_name} -> {new_name}", file=sys.stderr)

    # Re-sort $defs
    if "$defs" in result:
        result["$defs"] = dict(sorted(result["$defs"].items()))

    return result




def generate_validation_schema(resolved_path, verbose=False, title=None,
                               description=None):
    """Generate a compact validation schema from a resolved profile schema."""

    with open(resolved_path, "r", encoding="utf-8") as f:
        resolved = json.load(f)

    if verbose:
        total_size = len(json.dumps(resolved))
        print(f"Loaded: {resolved_path}", file=sys.stderr)
        print(f"  Input size: {total_size:,} bytes", file=sys.stderr)

    # Step 1: Merge allOf into flat schema
    merged = merge_allof(resolved)
    if verbose:
        n_props = len(merged.get("properties", {}))
        print(f"  Merged properties: {n_props}", file=sys.stderr)

    # Step 2: Find repeated sub-schemas (structural dedup)
    candidates = find_extractable_defs(merged, min_occurrences=2)
    if verbose:
        print(f"  Extractable $defs: {len(candidates)}", file=sys.stderr)
        for name, info in sorted(candidates.items(), key=lambda x: -x[1]["count"]):
            size = len(canonical_json(info["schema"]))
            print(f"    {name}: {info['count']}x, ~{size:,} bytes", file=sys.stderr)

    # Step 3: Build $defs with nested dedup
    raw_defs = {name: info["schema"] for name, info in candidates.items()}
    sfp_to_name = {info["structural_fp"]: name for name, info in candidates.items()}

    processed_defs = _process_defs_recursively(raw_defs, sfp_to_name)

    # Step 4: Replace inline schemas with $refs
    compacted = replace_with_refs(merged, sfp_to_name)

    # Step 5: Attach $defs (merge source $defs preserved from merge_allof
    # with any newly extracted $defs from dedup)
    source_defs = compacted.get("$defs", {})
    all_defs = {}
    all_defs.update(source_defs)
    all_defs.update(processed_defs)  # extracted defs take precedence
    if all_defs:
        compacted["$defs"] = dict(sorted(all_defs.items()))

    # Step 6: Prune single-use $defs (inline them back)
    compacted = prune_single_use_defs(compacted)

    # Step 7: Semantic post-processing (renames and structural simplifications)
    compacted = _postprocess_defs(compacted, verbose)

    compacted.setdefault("$schema", "https://json-schema.org/draft/2020-12/schema")

    # Step 8: Set root metadata (title, description with provenance)
    if title:
        compacted["title"] = title
    if description:
        compacted["description"] = description

    if verbose:
        out_size = len(json.dumps(compacted, indent=4))
        n_defs = len(compacted.get("$defs", {}))
        savings = total_size - out_size
        pct = savings * 100 // total_size if total_size else 0
        print(f"  Output: {out_size:,} bytes ({pct}% smaller), {n_defs} $defs",
              file=sys.stderr)

    return compacted


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate framed-tree validation schema from resolved BB profile schema."
    )
    parser.add_argument(
        "resolved_schema", type=Path,
        help="Path to resolved profile schema (e.g., CDIFDiscoveryProfile/resolvedSchema.json)",
    )
    parser.add_argument("-o", "--output", type=Path, help="Output file (default: stdout)")
    parser.add_argument("-t", "--title", help="Schema title (overrides source title)")
    parser.add_argument("-d", "--description", help="Schema description (overrides source)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show progress on stderr")
    args = parser.parse_args()

    if not args.resolved_schema.exists():
        print(f"Error: {args.resolved_schema} not found", file=sys.stderr)
        sys.exit(1)

    result = generate_validation_schema(args.resolved_schema, verbose=args.verbose,
                                        title=args.title, description=args.description)
    output_json = json.dumps(result, indent=4, ensure_ascii=False) + "\n"

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_json)
        if args.verbose:
            print(f"Wrote: {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(output_json)


if __name__ == "__main__":
    main()
