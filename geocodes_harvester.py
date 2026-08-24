#!/usr/bin/env python3
"""
geocodes_harvester.py - Convert ESIP Science-on-Schema.org (SOSO) records to CDIF,
and harvest them from the EarthCube GeoCodes catalog.

Two modes:

1. Generic SOSO -> CDIF (give it a file path or URL):
   Reads a SOSO schema.org Dataset record from a local file or an http(s) URL
   (extracting embedded JSON-LD from an HTML landing page if needed), converts it
   to a CDIF core/discovery record, and derives the catalog record's
   dcterms:conformsTo from the record's actual content via detect_conformance.
   Output goes to a default file (<input-stem>-cdif.json) or a path you give.

2. GeoCodes harvest (the original behavior): queries the GeoCodes Blazegraph
   SPARQL endpoint for dataset records, fetches the original JSON-LD from source
   landing pages (falling back to SPARQL CONSTRUCT), and optionally converts them
   to CDIF. The GeoCodes catalog indexes ~170K datasets whose records follow ESIP
   Science-on-Schema.org conventions.

SPARQL endpoint:
    https://graph.geocodes-aws.earthcube.org/blazegraph/namespace/geocodes_all/sparql

Usage:
    # Generic: convert a SOSO file or URL to CDIF (conformsTo from content)
    python geocodes_harvester.py path/to/soso-record.json
    python geocodes_harvester.py https://example.org/dataset -o out.json
    python geocodes_harvester.py soso.json --cdif core --static-conformance

    # Harvest from GeoCodes
    python geocodes_harvester.py --list-publishers
    python geocodes_harvester.py --count 5 --output ./examples --cdif discovery
    python geocodes_harvester.py --publisher "PANGAEA" --count 3 --output ./examples
"""

import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.parse
import urllib.error
from html.parser import HTMLParser

# The SOSO->CDIF conversion engine lives beside this file in soso/. It performs
# the schema.org->CDIF structural alignment and runs detect_conformance to set
# the catalog record's dcterms:conformsTo from the record's actual content.
_SOSO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "soso")
if _SOSO_DIR not in sys.path:
    sys.path.insert(0, _SOSO_DIR)
from ConvertFromSOSO import convert_soso_to_cdif


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SPARQL_ENDPOINT = (
    "https://graph.geocodes-aws.earthcube.org/blazegraph/"
    "namespace/geocodes_all/sparql"
)

GEOCODES_URL = "https://geocodes.earthcube.org/"

# ---------------------------------------------------------------------------
# SPARQL queries
# ---------------------------------------------------------------------------

def sparql_query(query, accept="application/sparql-results+json"):
    """POST a SPARQL query to the GeoCodes endpoint."""
    data = query.encode("utf-8")
    req = urllib.request.Request(
        SPARQL_ENDPOINT,
        data=data,
        headers={
            "Content-Type": "application/sparql-query",
            "Accept": accept,
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def list_publishers(limit=50):
    """Return a list of (publisher_name, count) tuples."""
    q = """
    PREFIX schema: <https://schema.org/>
    SELECT ?pubname (COUNT(DISTINCT ?s) AS ?cnt)
    WHERE {
      ?s schema:publisher/schema:name ?pubname .
    }
    GROUP BY ?pubname
    ORDER BY DESC(?cnt)
    LIMIT """ + str(limit)
    result = json.loads(sparql_query(q))
    return [
        (b["pubname"]["value"], int(b["cnt"]["value"]))
        for b in result["results"]["bindings"]
    ]


def find_datasets(count=10, publisher=None):
    """Find dataset graph URIs with metadata.

    Returns list of dicts with keys: graph, name, publisher, url.
    If publisher is given, filters to that publisher.
    Otherwise selects one sample per publisher for diversity.
    """
    if publisher:
        q = f"""
        PREFIX schema: <https://schema.org/>
        SELECT ?g ?name ?url WHERE {{
          GRAPH ?g {{
            ?s a schema:Dataset .
            ?s schema:name ?name .
            ?s schema:publisher/schema:name "{publisher}" .
            OPTIONAL {{ ?s schema:url ?url }}
          }}
        }}
        LIMIT {count}
        """
    else:
        # One sample per publisher for diversity
        q = f"""
        PREFIX schema: <https://schema.org/>
        SELECT ?pubname (SAMPLE(?g) AS ?sg) (SAMPLE(?name) AS ?sname)
               (SAMPLE(?url) AS ?surl)
        WHERE {{
          GRAPH ?g {{
            ?s a schema:Dataset .
            ?s schema:name ?name .
            ?s schema:publisher/schema:name ?pubname .
            OPTIONAL {{ ?s schema:url ?url }}
          }}
        }}
        GROUP BY ?pubname
        LIMIT {count}
        """

    result = json.loads(sparql_query(q))
    datasets = []
    for b in result["results"]["bindings"]:
        if publisher:
            datasets.append({
                "graph": b["g"]["value"],
                "name": b["name"]["value"],
                "publisher": publisher,
                "url": b.get("url", {}).get("value", ""),
            })
        else:
            datasets.append({
                "graph": b["sg"]["value"],
                "name": b["sname"]["value"],
                "publisher": b["pubname"]["value"],
                "url": b.get("surl", {}).get("value", ""),
            })
    return datasets


def fetch_sparql_jsonld(graph_uri):
    """Fetch all triples for a graph via SPARQL CONSTRUCT, returned as JSON-LD."""
    q = f"CONSTRUCT {{?s ?p ?o}} WHERE {{ GRAPH <{graph_uri}> {{ ?s ?p ?o }} }}"
    return sparql_query(q, accept="application/ld+json")


# ---------------------------------------------------------------------------
# Landing page JSON-LD extraction
# ---------------------------------------------------------------------------

class JsonLdExtractor(HTMLParser):
    """Extract JSON-LD script blocks from HTML."""

    def __init__(self):
        super().__init__()
        self._in_jsonld = False
        self._buf = []
        self.blocks = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            attr_dict = dict(attrs)
            if attr_dict.get("type", "").lower() == "application/ld+json":
                self._in_jsonld = True
                self._buf = []

    def handle_data(self, data):
        if self._in_jsonld:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._in_jsonld:
            self._in_jsonld = False
            text = "".join(self._buf)
            try:
                self.blocks.append(json.loads(text))
            except json.JSONDecodeError:
                pass


def fetch_landing_page(url, max_redirects=5):
    """Fetch HTML from a URL, following redirects."""
    for _ in range(max_redirects):
        req = urllib.request.Request(url, headers={
            "User-Agent": "CDIF-GeoCodes-Harvester/1.0",
            "Accept": "text/html",
        })
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                if resp.status in (301, 302, 303, 307, 308):
                    url = resp.headers.get("Location", url)
                    continue
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                url = e.headers.get("Location", url)
                continue
            raise
    return None


def _is_dataset_type(typ):
    if not typ:
        return False
    types = typ if isinstance(typ, list) else [typ]
    return any(
        t in ("Dataset", "sc:Dataset", "schema:Dataset",
              "https://schema.org/Dataset", "http://schema.org/Dataset")
        for t in types
    )


def extract_dataset_jsonld(html):
    """Extract the Dataset JSON-LD block from HTML."""
    parser = JsonLdExtractor()
    parser.feed(html)
    for block in parser.blocks:
        if _is_dataset_type(block.get("@type")):
            return block
        if "@graph" in block:
            for node in block["@graph"]:
                if _is_dataset_type(node.get("@type")):
                    ctx = block.get("@context")
                    if ctx:
                        node["@context"] = ctx
                    return node
    return None


def harvest_record(dataset_info, verbose=False):
    """Harvest a single dataset record.

    Tries the landing page first for original JSON-LD; falls back to SPARQL.
    Returns (jsonld_dict, source) where source is 'landing_page' or 'sparql'.
    """
    url = dataset_info.get("url", "")

    # Try landing page first
    if url and url.startswith("http"):
        try:
            if verbose:
                print(f"  Fetching landing page: {url}")
            html = fetch_landing_page(url)
            if html:
                dataset = extract_dataset_jsonld(html)
                if dataset:
                    return dataset, "landing_page"
                if verbose:
                    print("  No JSON-LD found on landing page, falling back to SPARQL")
        except Exception as e:
            if verbose:
                print(f"  Landing page failed ({e}), falling back to SPARQL")

    # Fall back to SPARQL CONSTRUCT
    if verbose:
        print(f"  Fetching via SPARQL CONSTRUCT: {dataset_info['graph']}")
    raw = fetch_sparql_jsonld(dataset_info["graph"])
    # SPARQL returns expanded JSON-LD — return as-is (array of nodes)
    return json.loads(raw), "sparql"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def load_soso(source, verbose=False):
    """Load a SOSO JSON-LD document from a local file path or an http(s) URL.
    For a URL, fetch it; if the body is HTML, extract the embedded JSON-LD."""
    if re.match(r"(?i)^https?://", source):
        if verbose:
            print(f"Fetching {source} ...", file=sys.stderr)
        req = urllib.request.Request(source, headers={
            "Accept": "application/ld+json, application/json;q=0.9, text/html;q=0.8",
            "User-Agent": "cdif-soso-converter"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        if body.lstrip()[:1] in ("{", "["):
            return json.loads(body)
        doc = extract_dataset_jsonld(body)
        if doc is None:
            raise ValueError(f"No embedded JSON-LD Dataset found at {source}")
        return doc
    with open(source, encoding="utf-8") as f:
        return json.load(f)


def cdif_output_path(source, output):
    """Resolve the CDIF output file path. ``output`` may be a file path (used
    as-is), an existing directory (``<stem>-cdif.json`` written inside), or
    omitted / '.' (``<stem>-cdif.json`` in the current directory). ``stem`` comes
    from the input file name, or the last URL path segment."""
    if re.match(r"(?i)^https?://", source):
        base = source.rstrip("/").split("/")[-1] or "soso"
        stem = os.path.splitext(re.sub(r"[^A-Za-z0-9._-]", "-", base))[0] or "soso"
    else:
        stem = os.path.splitext(os.path.basename(source))[0]
    name = f"{stem}-cdif.json"
    if not output or output == ".":
        return name
    if os.path.isdir(output):
        return os.path.join(output, name)
    return output


def convert_file_or_url(source, output=None, profile="discovery",
                        detect=True, verbose=False):
    """Generic SOSO -> CDIF: read ``source`` (file path or URL), convert to a
    CDIF ``profile`` record (conformsTo derived from content unless
    ``detect`` is False), write it, and return the output path."""
    soso = load_soso(source, verbose=verbose)
    cdif, changes = convert_soso_to_cdif(soso, profile=profile, verbose=verbose,
                                         detect=detect)
    outpath = cdif_output_path(source, output)
    parent = os.path.dirname(outpath)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(outpath, "w", encoding="utf-8") as f:
        json.dump(cdif, f, indent=2, ensure_ascii=False)
        f.write("\n")
    subj = cdif.get("schema:subjectOf")
    ct = subj.get("dcterms:conformsTo", []) if isinstance(subj, dict) else []
    conf = ", ".join(c.get("@id", "") for c in ct if isinstance(c, dict))
    print(f"Wrote CDIF ({profile} profile): {outpath}")
    print(f"  conformsTo: {conf}")
    if verbose:
        for c in changes:
            print(f"  {c}", file=sys.stderr)
    return outpath


def main():
    parser = argparse.ArgumentParser(
        description="Convert ESIP Science-on-Schema.org records to CDIF (from a "
                    "file/URL), or harvest them from the GeoCodes catalog.")
    parser.add_argument("input", nargs="?",
                        help="SOSO JSON-LD file path or URL to convert to CDIF. "
                             "If given, runs the generic converter; omit to "
                             "harvest from GeoCodes.")
    parser.add_argument("--list-publishers", action="store_true",
                        help="List available GeoCodes publishers and exit")
    parser.add_argument("--publisher", "-p", type=str, default=None,
                        help="Filter to a specific publisher name (harvest mode)")
    parser.add_argument("--count", "-n", type=int, default=5,
                        help="Number of records to harvest (default: 5)")
    parser.add_argument("--output", "-o", type=str, default=".",
                        help="Output path: CDIF file (generic mode) or directory "
                             "(harvest mode)")
    parser.add_argument("--cdif", type=str, choices=["core", "discovery"],
                        default=None,
                        help="Target CDIF profile (default: discovery in generic "
                             "mode; harvest converts only when given)")
    parser.add_argument("--static-conformance", action="store_true",
                        help="Use the profile-default conformsTo instead of "
                             "deriving it from content via detect_conformance")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    # Generic mode: SOSO file/URL -> CDIF.
    if args.input:
        try:
            convert_file_or_url(args.input, output=args.output,
                                profile=args.cdif or "discovery",
                                detect=not args.static_conformance,
                                verbose=args.verbose)
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        return 0

    if args.list_publishers:
        print(f"{'Publisher':50s} {'Datasets':>10s}")
        print("-" * 62)
        for name, count in list_publishers():
            print(f"{name:50s} {count:10d}")
        return 0

    # Find datasets
    print(f"Querying GeoCodes for {args.count} dataset(s)...")
    datasets = find_datasets(count=args.count, publisher=args.publisher)
    if not datasets:
        print("No datasets found.")
        return 1
    print(f"Found {len(datasets)} dataset(s)")

    os.makedirs(args.output, exist_ok=True)

    # Harvest each
    for i, ds in enumerate(datasets):
        pub = ds["publisher"][:30]
        name = ds["name"][:60]
        print(f"\n[{i+1}/{len(datasets)}] {pub}: {name}")

        try:
            record, source = harvest_record(ds, verbose=args.verbose)
        except Exception as e:
            print(f"  ERROR: {e}")
            continue

        if source == "sparql":
            # SPARQL returns expanded form — not ideal for examples
            print(f"  Harvested via SPARQL (expanded JSON-LD, may have blank node issues)")
        else:
            print(f"  Harvested from landing page")

        # Convert if requested (same engine as the generic mode)
        if args.cdif and isinstance(record, dict):
            record, _ = convert_soso_to_cdif(
                record, profile=args.cdif, source_label=pub,
                detect=not args.static_conformance, verbose=args.verbose)
            print(f"  Converted to CDIF {args.cdif} profile")

        # Write output
        safe_pub = re.sub(r"[^a-zA-Z0-9]", "-", pub).strip("-").lower()[:20]
        filename = f"GeoCodes-{safe_pub}-{i:02d}.jsonld"
        outpath = os.path.join(args.output, filename)
        with open(outpath, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, ensure_ascii=False)
        print(f"  Written: {outpath}")

    print(f"\nDone. {len(datasets)} record(s) harvested.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
