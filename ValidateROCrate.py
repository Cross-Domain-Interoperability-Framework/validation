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

    # Skip rocrate-validator SHACL checks
    python ValidateROCrate.py input.jsonld --no-rocrate-validator

    # Include RECOMMENDED-level checks from rocrate-validator
    python ValidateROCrate.py input.jsonld --severity RECOMMENDED
"""

import json
import argparse
import sys

from ConvertToROCrate import (
    convert_to_rocrate,
    ROCRATE_CONFORMSTO_URI,
    ROCRATE_CONTEXT_URI,
    METADATA_DESCRIPTOR_ID,
    ROOT_DATASET_ID,
)

# Optional: rocrate-validator for thorough SHACL-based validation
# Install with: pip install roc-validator
try:
    from rocrate_validator import services as roc_services
    from rocrate_validator.models import Severity as RocSeverity
    HAS_ROC_VALIDATOR = True
except ImportError:
    HAS_ROC_VALIDATOR = False


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


# ---------------------------------------------------------------------------
# rocrate-validator integration
# ---------------------------------------------------------------------------

# Map rocrate-validator severity to our PASS/WARN/FAIL levels
_ROC_SEVERITY_MAP = {}
if HAS_ROC_VALIDATOR:
    _ROC_SEVERITY_MAP = {
        RocSeverity.REQUIRED: FAIL,
        RocSeverity.RECOMMENDED: WARN,
        RocSeverity.OPTIONAL: WARN,
    }


def validate_with_rocrate_validator(rocrate_dict, severity="REQUIRED"):
    """
    Run rocrate-validator (SHACL-based) on an in-memory RO-Crate dict.

    Args:
        rocrate_dict: The RO-Crate JSON-LD document as a Python dict.
        severity: Minimum severity to check: "REQUIRED", "RECOMMENDED", or
                  "OPTIONAL". Default "REQUIRED".

    Returns:
        The ValidationResult object, or None if rocrate-validator is not installed.
    """
    if not HAS_ROC_VALIDATOR:
        return None

    sev = getattr(RocSeverity, severity.upper(), RocSeverity.REQUIRED)
    settings = roc_services.ValidationSettings(
        rocrate_uri=".",
        profile_identifier="ro-crate-1.1",
        requirement_severity=sev,
        abort_on_first=False,
    )
    return roc_services.validate_metadata_as_dict(rocrate_dict, settings)


def print_rocrate_validator_results(result, verbose=False):
    """
    Print results from rocrate-validator in a format matching our built-in checks.

    Returns True if validation passed (no REQUIRED-level issues).
    """
    issues = result.get_issues()
    if not issues and result.passed():
        print(f"\n{'='*60}")
        print("rocrate-validator (SHACL) Results")
        print(f"{'='*60}")
        n_checks = len(result.executed_checks) if hasattr(result, 'executed_checks') else 0
        print(f"  PASS  All checks passed ({n_checks} checks executed)")
        print(f"\n{'-'*60}")
        print("Result: VALID")
        return True

    # Group issues by severity
    required_issues = []
    other_issues = []
    for issue in issues:
        if issue.severity == RocSeverity.REQUIRED:
            required_issues.append(issue)
        else:
            other_issues.append(issue)

    print(f"\n{'='*60}")
    print("rocrate-validator (SHACL) Results")
    print(f"{'='*60}")

    for i, issue in enumerate(issues, 1):
        level = _ROC_SEVERITY_MAP.get(issue.severity, WARN)
        marker = f"  {level}"
        check_id = issue.check.identifier if hasattr(issue, 'check') and issue.check else "?"
        print(f"{marker}  [{i:2d}] [{issue.severity.name}] {issue.message}")
        if verbose or level != PASS:
            if hasattr(issue, 'violatingEntity') and issue.violatingEntity:
                print(f"              Entity: {issue.violatingEntity}")
            if hasattr(issue, 'violatingProperty') and issue.violatingProperty:
                print(f"              Property: {issue.violatingProperty}")
            print(f"              Check: {check_id}")

    print(f"\n{'-'*60}")
    print(f"Summary: {len(required_issues)} failures, {len(other_issues)} warnings")

    if not required_issues:
        if other_issues:
            print("Result: VALID (with warnings)")
        else:
            print("Result: VALID")
        return True
    else:
        print("Result: INVALID")
        return False


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

  # Skip rocrate-validator SHACL checks
  python ValidateROCrate.py input.jsonld --no-rocrate-validator

  # Include RECOMMENDED-level checks from rocrate-validator
  python ValidateROCrate.py input.jsonld --severity RECOMMENDED
"""
    )
    parser.add_argument('input', help='Input JSON-LD file to process')
    parser.add_argument('-o', '--output', help='Write RO-Crate output to file')
    parser.add_argument('--no-convert', action='store_true',
                        help='Skip conversion --validate input as-is')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Show detailed output including PASS details')
    parser.add_argument('--no-rocrate-validator', action='store_true',
                        help='Skip rocrate-validator SHACL-based checks')
    parser.add_argument('--severity', choices=['REQUIRED', 'RECOMMENDED', 'OPTIONAL'],
                        default='REQUIRED',
                        help='Minimum severity for rocrate-validator checks (default: REQUIRED)')

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

        # --- Built-in structural checks ---
        print("\nValidating against RO-Crate 1.1 requirements...")
        results = validate_rocrate(rocrate, verbose=args.verbose)
        builtin_valid = print_results(results, verbose=args.verbose)

        # --- rocrate-validator SHACL checks ---
        roc_valid = True
        if not args.no_rocrate_validator:
            if not HAS_ROC_VALIDATOR:
                print(f"\n{'='*60}")
                print("rocrate-validator (SHACL) Results")
                print(f"{'='*60}")
                print("  SKIP  rocrate-validator not installed")
                print("        Install with: pip install roc-validator")
                print(f"{'-'*60}")
            else:
                print(f"\nRunning rocrate-validator (severity >= {args.severity})...")
                roc_result = validate_with_rocrate_validator(rocrate, args.severity)
                roc_valid = print_rocrate_validator_results(
                    roc_result, verbose=args.verbose)

        # --- Overall result ---
        overall = builtin_valid and roc_valid
        print(f"\n{'='*60}")
        print(f"Overall: {'VALID' if overall else 'INVALID'}")
        print(f"{'='*60}")

        if not overall:
            sys.exit(1)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
