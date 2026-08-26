#!/usr/bin/env python3
"""
normalize_catalogrecord_type.py - migrate CDIF records to the IRI form of the
CatalogRecord type tag.

The CDIF convention (building blocks, framed + graph JSON Schemas, and discovery
SHACL) requires the CatalogRecord type marker on a schema:subjectOf node to be an
**IRI reference**:

    "schema:additionalType": [{"@id": "dcat:CatalogRecord"}]

Older records serialize it as a bare string, `"dcat:CatalogRecord"`, which the
current shapes flag (the dataset mandatory shape no longer excludes such a node,
producing spurious violations) and which the complete/graph JSON Schemas reject.

This tool rewrites the string form to the IRI form in place. It only touches
`schema:additionalType` / `additionalType` values equal to `dcat:CatalogRecord`
(or its full IRI `http://www.w3.org/ns/dcat#CatalogRecord`); every other
additionalType value — free-label strings, DefinedTerm objects, other IRIs — is
left untouched. It is idempotent (values already in `{"@id": ...}` form are
skipped).

Usage:
    python normalize_catalogrecord_type.py [PATH ...]        # dry-run (report only)
    python normalize_catalogrecord_type.py [PATH ...] --apply # write changes

PATH may be a file or a directory (searched recursively for *.json). With no
PATH, a default set of record locations in this repo is used.
"""
import argparse
import json
import sys
from pathlib import Path

CR_STRINGS = {"dcat:CatalogRecord", "http://www.w3.org/ns/dcat#CatalogRecord"}
AT_KEYS = ("schema:additionalType", "additionalType")

# Default record locations (relative to this script) when no PATH is given.
DEFAULT_TARGETS = [
    "testJSONMetadata",
    "MetadataExamples",
    "converters",
]


def _normalize_at_value(value):
    """Rewrite dcat:CatalogRecord string(s) in an additionalType value to the
    {"@id": ...} form. Returns (new_value, changed). Preserves list vs scalar."""
    items = value if isinstance(value, list) else [value]
    out, changed = [], False
    for it in items:
        if isinstance(it, str) and it in CR_STRINGS:
            out.append({"@id": it})
            changed = True
        else:
            out.append(it)
    if not changed:
        return value, False
    if not isinstance(value, list):
        return (out[0] if len(out) == 1 else out), True
    return out, True


def normalize(node):
    """Recursively normalize a JSON structure in place. Returns True if changed."""
    changed = False
    if isinstance(node, dict):
        for key in list(node.keys()):
            if key in AT_KEYS:
                new_val, c = _normalize_at_value(node[key])
                if c:
                    node[key] = new_val
                    changed = True
            if normalize(node[key]):
                changed = True
    elif isinstance(node, list):
        for item in node:
            if normalize(item):
                changed = True
    return changed


def iter_json_files(paths, script_dir):
    for p in paths:
        path = Path(p)
        if not path.is_absolute():
            path = script_dir / path
        if path.is_dir():
            yield from sorted(path.rglob("*.json"))
        elif path.is_file() and path.suffix == ".json":
            yield path


def main():
    script_dir = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", default=DEFAULT_TARGETS,
                    help="files or directories to normalize (default: repo record dirs)")
    ap.add_argument("--apply", action="store_true",
                    help="write changes (default: dry-run, report only)")
    args = ap.parse_args()

    changed_files = 0
    scanned = 0
    for f in iter_json_files(args.paths, script_dir):
        scanned += 1
        try:
            text = f.read_text(encoding="utf-8")
            doc = json.loads(text)
        except (ValueError, OSError):
            continue  # not JSON we can parse; skip quietly
        if normalize(doc):
            changed_files += 1
            rel = f.relative_to(script_dir) if f.is_relative_to(script_dir) else f
            if args.apply:
                f.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                             encoding="utf-8")
                print(f"  fixed  {rel}")
            else:
                print(f"  would fix  {rel}")

    verb = "Fixed" if args.apply else "Would fix"
    print(f"{verb} {changed_files} file(s) (scanned {scanned}).")
    if changed_files and not args.apply:
        print("Re-run with --apply to write changes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
