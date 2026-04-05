#!/usr/bin/env python3
"""
Validate JSON-LD instances against the CDIF profiles they claim conformance to.

Reads each JSON-LD file, extracts conformsTo URIs from schema:subjectOf/dcterms:conformsTo,
maps them to profile/building-block schemas, and validates.

Usage:
    python validate_conformance.py <dir_of_jsonld_files> [--verbose] [--summary]
"""

import json
import sys
import os
import glob
import argparse
from collections import Counter
from jsonschema import Draft202012Validator


# --- Configuration ---

BB_DIR = os.path.normpath(
    "C:/Users/smrTu/OneDrive/Documents/GithubC/CDIF/metadataBuildingBlocks/_sources"
)

# Map conformsTo URIs to resolved schema paths.
# Keys are normalized (no trailing slash). Data may use trailing slashes or
# variant spellings (dataDescription vs data_description) — all handled.
PROFILE_MAP = {
    # Profiles
    "https://w3id.org/cdif/core/1.0": os.path.join(
        BB_DIR, "cdifProperties/cdifCore/resolvedSchema.json"),
    "https://w3id.org/cdif/discovery/1.0": os.path.join(
        BB_DIR, "profiles/cdifProfiles/CDIFDiscoveryProfile/resolvedSchema.json"),
    "https://w3id.org/cdif/data_description/1.0": os.path.join(
        BB_DIR, "profiles/cdifProfiles/CDIFDataDescriptionProfile/resolvedSchema.json"),
    "https://w3id.org/cdif/complete/1.0": os.path.join(
        BB_DIR, "profiles/cdifProfiles/CDIFcompleteProfile/resolvedSchema.json"),
    "https://w3id.org/cdif/xas/1.0": os.path.join(
        BB_DIR, "profiles/cdifProfiles/CDIFxasProfile/resolvedSchema.json"),

    # Building blocks (also valid conformance classes)
    "https://w3id.org/cdif/provenance/1.0": os.path.join(
        BB_DIR, "cdifProperties/cdifProvenance/resolvedSchema.json"),
    "https://w3id.org/cdif/manifest/1.0": os.path.join(
        BB_DIR, "cdifProperties/cdifArchiveDistribution/resolvedSchema.json"),
    "https://w3id.org/cdif/archive/1.0": os.path.join(
        BB_DIR, "cdifProperties/cdifArchive/resolvedSchema.json"),
    "https://w3id.org/cdif/catalogrecord/1.0": os.path.join(
        BB_DIR, "cdifProperties/cdifCatalogRecord/resolvedSchema.json"),
    "https://w3id.org/cdif/datacube/1.0": os.path.join(
        BB_DIR, "cdifProperties/cdifDataCube/resolvedSchema.json"),
    "https://w3id.org/cdif/longdata/1.0": os.path.join(
        BB_DIR, "cdifProperties/cdifLongData/resolvedSchema.json"),
    "https://w3id.org/cdif/tabulardata/1.0": os.path.join(
        BB_DIR, "cdifProperties/cdifTabularData/resolvedSchema.json"),
}

# Alias map: variant spellings → canonical URI (before normalization)
URI_ALIASES = {
    "https://w3id.org/cdif/datadescription/1.0": "https://w3id.org/cdif/data_description/1.0",
}

# Prefixes to ignore
IGNORED_PREFIXES = ["ada:"]


def normalize_uri(uri):
    """Strip trailing slash, lowercase for alias matching."""
    norm = uri.rstrip("/")
    lower = norm.lower()
    if lower in URI_ALIASES:
        return URI_ALIASES[lower]
    # Also check the original (case-preserving)
    if norm in URI_ALIASES:
        return URI_ALIASES[norm]
    return norm


def load_schema(schema_path):
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_conformsto(doc):
    subj = doc.get("schema:subjectOf", {})
    if not isinstance(subj, dict):
        return []
    conforms = subj.get("dcterms:conformsTo", [])
    if not isinstance(conforms, list):
        conforms = [conforms]
    uris = []
    for c in conforms:
        if isinstance(c, dict) and "@id" in c:
            uris.append(c["@id"])
        elif isinstance(c, str):
            uris.append(c)
    return uris


def validate_instance(doc, schema):
    validator = Draft202012Validator(schema)
    errors = []
    for error in validator.iter_errors(doc):
        path = "/".join(str(p) for p in error.absolute_path) or "(root)"
        errors.append(f"  {path}: {error.message[:200]}")
    return errors


def short_uri(uri):
    if "/cdif/" in uri:
        return uri.split("/cdif/")[-1]
    return uri


def main():
    parser = argparse.ArgumentParser(
        description="Validate JSON-LD against claimed CDIF profiles")
    parser.add_argument("directory", help="Directory containing JSON-LD files")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show per-file error details")
    parser.add_argument("--summary", "-s", action="store_true",
                        help="Show only summary")
    args = parser.parse_args()

    # Load schemas
    schemas = {}
    for uri, path in PROFILE_MAP.items():
        if os.path.exists(path):
            schemas[uri] = load_schema(path)
        else:
            print(f"WARNING: Schema not found: {path}", file=sys.stderr)

    # Find files
    files = sorted(glob.glob(os.path.join(args.directory, "*.json")) +
                   glob.glob(os.path.join(args.directory, "*.jsonld")))
    if not files:
        print(f"No JSON/JSONLD files found in {args.directory}")
        return 1

    # Track results
    profile_stats = {}  # uri -> {pass, fail, errors}
    error_patterns = Counter()  # (profile, path_prefix) -> count
    file_count = 0
    all_pass_count = 0

    for filepath in files:
        filename = os.path.basename(filepath)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                doc = json.load(f)
        except Exception as e:
            print(f"ERROR reading {filename}: {e}")
            continue

        claimed_uris = extract_conformsto(doc)
        if not claimed_uris:
            if not args.summary:
                print(f"SKIP  {filename} (no conformsTo)")
            continue

        file_count += 1
        file_pass = True
        statuses = []

        for raw_uri in claimed_uris:
            norm = normalize_uri(raw_uri)

            if any(norm.startswith(p.rstrip("/")) for p in IGNORED_PREFIXES):
                continue

            if norm not in schemas:
                statuses.append(f"{short_uri(norm)}:NO_SCHEMA")
                continue

            errors = validate_instance(doc, schemas[norm])

            if norm not in profile_stats:
                profile_stats[norm] = {"pass": 0, "fail": 0, "sample_errors": []}

            if errors:
                profile_stats[norm]["fail"] += 1
                file_pass = False
                statuses.append(f"{short_uri(norm)}:{len(errors)}err")
                # Track error patterns
                for e in errors:
                    # Extract path portion for grouping
                    parts = e.strip().split(":", 1)
                    path_part = parts[0].strip() if len(parts) > 1 else "(root)"
                    msg_start = parts[1].strip()[:80] if len(parts) > 1 else e[:80]
                    error_patterns[(short_uri(norm), path_part, msg_start)] += 1
                if len(profile_stats[norm]["sample_errors"]) < 3:
                    profile_stats[norm]["sample_errors"].append((filename, errors))
            else:
                profile_stats[norm]["pass"] += 1
                statuses.append(f"{short_uri(norm)}:PASS")

        if file_pass:
            all_pass_count += 1

        if not args.summary:
            label = "PASS" if file_pass else "FAIL"
            print(f"{label}  {filename}  [{', '.join(statuses)}]")
            if args.verbose and not file_pass:
                for raw_uri in claimed_uris:
                    norm = normalize_uri(raw_uri)
                    if norm not in schemas:
                        continue
                    errs = validate_instance(doc, schemas[norm])
                    if errs:
                        print(f"  -- {short_uri(norm)} --")
                        for e in errs[:3]:
                            print(f"  {e}")
                        if len(errs) > 3:
                            print(f"  ... and {len(errs) - 3} more")

    # Summary
    print(f"\n{'='*70}")
    print("PROFILE VALIDATION SUMMARY")
    print(f"{'='*70}")
    for uri in sorted(profile_stats.keys()):
        r = profile_stats[uri]
        total = r["pass"] + r["fail"]
        pct = r["pass"] / total * 100 if total else 0
        print(f"  {short_uri(uri):35s}  {r['pass']:3d} pass  {r['fail']:3d} fail  ({pct:.0f}% of {total})")

    print(f"\nFiles: {file_count} validated, {all_pass_count} all-pass, "
          f"{file_count - all_pass_count} with failures")

    # Common error patterns
    print(f"\n{'='*70}")
    print("DISTINCT ERROR PATTERNS (across all files and profiles)")
    print(f"{'='*70}")
    for (profile, path, msg), count in error_patterns.most_common(20):
        print(f"  ({count:3d}x) [{profile}] {path}: {msg}...")

    return 0 if all_pass_count == file_count else 1


if __name__ == "__main__":
    sys.exit(main())
