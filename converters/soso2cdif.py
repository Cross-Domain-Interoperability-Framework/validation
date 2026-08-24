#!/usr/bin/env python3
"""soso2cdif.py — convert an ESIP Science-on-Schema.org (SOSO) record to CDIF.

Reads a SOSO schema.org Dataset from a local file path or an http(s) URL
(extracting embedded JSON-LD from an HTML landing page when the response is not
JSON), converts it to a CDIF core/discovery record, and derives the catalog
record's dcterms:conformsTo from the record's actual content via
detect_conformance. Output is written to a default file (<input-stem>-cdif.json)
or to a path given with -o (a file, or a directory to write the default name
into).

The SOSO->CDIF conversion is done by the ConvertFromSOSO engine in
validation/soso/; this script is the file/URL front-end for it.

Usage:
    python soso2cdif.py path/to/soso-record.json
    python soso2cdif.py https://example.org/dataset -o out.json
    python soso2cdif.py soso.json --cdif core --static-conformance
"""

import argparse
import json
import os
import re
import sys
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

# The ConvertFromSOSO engine lives in validation/soso/ (sibling of converters/).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "soso"))
from ConvertFromSOSO import convert_soso_to_cdif


class _LDJsonExtractor(HTMLParser):
    """Collect the text of every <script type="application/ld+json"> block."""

    def __init__(self):
        super().__init__()
        self._in = False
        self._buf = []
        self.blocks = []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("type", "").strip() == "application/ld+json":
            self._in, self._buf = True, []

    def handle_endtag(self, tag):
        if tag == "script" and self._in:
            self._in = False
            self.blocks.append("".join(self._buf))

    def handle_data(self, data):
        if self._in:
            self._buf.append(data)


def _find_dataset(obj):
    """Return a schema.org Dataset node from a parsed JSON-LD value (root node,
    an @graph, or a list), preserving an outer @context if the node lacks one."""
    if isinstance(obj, dict):
        graph = obj.get("@graph")
        if isinstance(graph, list):
            ds = _find_dataset(graph)
            if isinstance(ds, dict):
                if "@context" not in ds and "@context" in obj:
                    ds = {"@context": obj["@context"], **ds}
                return ds
        t = obj.get("@type")
        t = t if isinstance(t, list) else [t]
        if any(str(x).endswith("Dataset") for x in t if x):
            return obj
        return None
    if isinstance(obj, list):
        for item in obj:
            ds = _find_dataset(item)
            if ds is not None:
                return ds
    return None


def extract_dataset_jsonld(html):
    """Return the first schema.org Dataset from embedded ld+json in an HTML page."""
    parser = _LDJsonExtractor()
    parser.feed(html)
    for block in parser.blocks:
        try:
            data = json.loads(block)
        except Exception:
            continue
        ds = _find_dataset(data)
        if ds is not None:
            return ds
    return None


def load_soso(source, verbose=False):
    """Load a SOSO JSON-LD document from a local file path or an http(s) URL.
    For a URL, fetch it; if the body is HTML, extract the embedded JSON-LD."""
    if re.match(r"(?i)^https?://", source):
        if verbose:
            print(f"Fetching {source} ...", file=sys.stderr)
        req = urllib.request.Request(source, headers={
            "Accept": "application/ld+json, application/json;q=0.9, text/html;q=0.8",
            "User-Agent": "soso2cdif"})
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
    omitted / '.' (``<stem>-cdif.json`` in the current directory)."""
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


def convert(source, output=None, profile="discovery", detect=True, verbose=False):
    """Read ``source`` (file path or URL), convert to CDIF, write it, return path."""
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
        description="Convert an ESIP Science-on-Schema.org (SOSO) Dataset record "
                    "(file path or URL) to CDIF core/discovery JSON-LD.")
    parser.add_argument("input", help="SOSO JSON-LD file path or http(s) URL")
    parser.add_argument("-o", "--output",
                        help="Output CDIF file, or a directory (default: "
                             "<input-stem>-cdif.json in the current directory)")
    parser.add_argument("--cdif", choices=["core", "discovery"], default="discovery",
                        help="Target CDIF profile (default: discovery)")
    parser.add_argument("--static-conformance", action="store_true",
                        help="Use the profile-default conformsTo instead of "
                             "deriving it from content via detect_conformance")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    try:
        convert(args.input, output=args.output, profile=args.cdif,
                detect=not args.static_conformance, verbose=args.verbose)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
