#!/usr/bin/env python3
"""
CDIF JSON-LD Flattening Tool

The inverse of FrameAndValidate.py: takes a nested / compacted CDIF JSON-LD
document and produces the flattened `@graph` form -- every node a top-level entry,
cross-references by `@id` -- re-applying the CDIF namespace prefixes so the output
stays readable (schema:Dataset, cdi:InstanceVariable, ...).

Pipeline: expand -> flatten -> compact-with-CDIF-prefixes.

Note: this performs a *full* JSON-LD flatten (PyLD), so every embedded node --
including value objects like schema:GeoShape, schema:QuantitativeValue and
spdx:Checksum -- is promoted to its own `@graph` entry. That is standard
flattened JSON-LD; it is NOT the same shape the framed-tree schemas expect, so
validate the result (if needed) as a graph, not against the framed schemas.

Usage:
    python FlattenCDIF.py <input.jsonld> [-o out.json]
                          [--context CDIF-context-2026.jsonld]
"""

import json
import argparse
import sys
from pathlib import Path
from pyld import jsonld

# Resolve remote contexts (schema.org, ro/crate, ...) over HTTP.
jsonld.set_document_loader(jsonld.requests_document_loader())

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_DIR = SCRIPT_DIR.parent  # tools/ -> validation/

DEFAULT_CONTEXT = REPO_DIR / "CDIF-context-2026.jsonld"


def load_context(context_path):
    """Return a namespace-prefix-only context derived from the context file.

    The flattened CDIF `@graph` form uses *prefixed* terms (schema:Dataset,
    schema:name, cdi:InstanceVariable). We keep only the namespace bindings
    (prefix -> full-IRI namespace) and drop any bare-term authoring aliases
    (Dataset->schema:Dataset, name->schema:name, ...), so the output is stable
    and prefixed regardless of the authoring context's aliases."""
    with open(context_path, "r", encoding="utf-8") as f:
        ctx = json.load(f)
    if isinstance(ctx, dict) and "@context" in ctx:
        ctx = ctx["@context"]
    if not isinstance(ctx, dict):
        return ctx
    return {k: v for k, v in ctx.items()
            if isinstance(v, str) and (v.startswith("http://") or v.startswith("https://"))}


def flatten_cdif_document(doc_path, context_path=None):
    """Flatten a nested CDIF JSON-LD document into {@context, @graph: [...]}."""
    print(f"Loading document: {doc_path}")
    with open(doc_path, "r", encoding="utf-8") as f:
        doc = json.load(f)

    ctx = None
    if context_path:
        print(f"Loading context: {context_path}")
        ctx = load_context(context_path)

    # jsonld.flatten expands the input (resolving its own @context), groups every
    # node into a single @graph, then compacts with ctx when provided.
    print("Flattening...")
    flattened = jsonld.flatten(doc, ctx)

    # Normalize to a {@context, @graph} document with @graph always a list.
    if isinstance(flattened, list):
        flattened = {"@graph": flattened}
    graph = flattened.get("@graph", [])
    if isinstance(graph, dict):
        flattened["@graph"] = [graph]

    return flattened


def main():
    parser = argparse.ArgumentParser(
        description="CDIF JSON-LD Flattening Tool (inverse of FrameAndValidate.py)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Flatten and print
  python FlattenCDIF.py my-metadata.jsonld

  # Flatten and save
  python FlattenCDIF.py my-metadata.jsonld -o flattened.json

  # Flatten with a specific context
  python FlattenCDIF.py my-metadata.jsonld --context CDIF-context-2026.jsonld -o flattened.json
""",
    )
    parser.add_argument("input", help="Input nested/compacted JSON-LD file")
    parser.add_argument("-o", "--output", help="Write flattened output to file")
    parser.add_argument("--context", default=str(DEFAULT_CONTEXT),
                        help=f"JSON-LD context whose namespace prefixes are applied "
                             f"(default: {DEFAULT_CONTEXT.name})")
    args = parser.parse_args()

    try:
        flattened = flatten_cdif_document(args.input, args.context)
        n = len(flattened.get("@graph", []))

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(flattened, f, indent=2, ensure_ascii=False)
            print(f"Flattened output ({n} nodes) written to: {args.output}")
        else:
            print(f"\nFlattened output ({n} nodes):")
            print(json.dumps(flattened, indent=2, ensure_ascii=False))

        print("\nDone!")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
