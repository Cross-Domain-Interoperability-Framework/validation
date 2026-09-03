#!/usr/bin/env python3
"""
ddi_to_cdif.py - Harvard Dataverse DDI Codebook 2.5 -> CDIF, with live enrichment.

SCOPE: a **source-specific** tool. The base conversion is done by the
source-agnostic engine (``ddi_sssom_to_cdif.py``); this module adds only what
the offline engine cannot -- live Dataverse-API lookups:

  --fetch-file-meta   file size and checksum from /api/files/<id>
  --fetch-headers     the .tab header row from /api/access/datafile/<id>,
                      turned into cdif:hasPhysicalMapping entries

It used to carry its own copy of the whole conversion -- study, variables,
files, distributions -- ~180 lines duplicating the engine, and it had drifted:
it emitted the superseded cdif/*/1.0 conformance URIs, and cdif:physicalDataType
where the building blocks declare cdif:physicalDataType. A property rename had
to be applied here separately from the engine, which is how the duplication
made itself felt. Delegating removes that class of drift: anything wrong with
the base conversion is now wrong in exactly one place.

Still deliberately outside the ddi2cdif.py flavor dispatcher, which is offline
and source-agnostic while these options reach the network.

Usage:
    python DDI/ddi_to_cdif.py input.xml --doi https://doi.org/10.7910/DVN/XXX -o out.json
    python DDI/ddi_to_cdif.py input.xml --doi ... --fetch-headers --fetch-file-meta
"""

import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ddi_sssom_to_cdif import convert as convert_codebook  # noqa: E402

DATAVERSE = "https://dataverse.harvard.edu"
# Dataverse download URLs the engine emits from <fileDscr URI>, e.g.
# https://dataverse.harvard.edu/api/access/datafile/1234567
ACCESS_ID = re.compile(r"/api/access/datafile/(\d+)")


def fetch_file_meta(access_id):
    """File size and checksum from the Dataverse file API."""
    url = "%s/api/files/%s" % (DATAVERSE, access_id)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CDIF-DDI-Converter/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            d = json.loads(resp.read().decode("utf-8"))
        df = d.get("data", {}).get("dataFile", {})
        cksum = df.get("checksum", {})
        return {"size": df.get("filesize"),
                "checksum_value": cksum.get("value"),
                "checksum_type": cksum.get("type")}
    except Exception as exc:
        print("  WARN: file metadata for %s: %s" % (access_id, exc), file=sys.stderr)
        return {}


def fetch_tab_headers(access_id):
    """The header row of a Dataverse .tab file."""
    url = "%s/api/access/datafile/%s" % (DATAVERSE, access_id)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CDIF-DDI-Converter/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            header_line = resp.readline().decode("utf-8").strip()
        return [c.strip('"') for c in header_line.split("\t")]
    except Exception as exc:
        print("  WARN: headers for %s: %s" % (access_id, exc), file=sys.stderr)
        return []


def _variable_index(doc):
    """{variable name: (@id, physical data type)} from the converted document."""
    index = {}
    for var in (doc.get("schema:variableMeasured") or []):
        if not isinstance(var, dict):
            continue
        name = var.get("schema:name")
        if isinstance(name, str):
            index[name] = (var.get("@id"),
                           var.get("cdif:physicalDataType") or "xsd:string")
    return index


def _access_id(dist):
    """The Dataverse file id a distribution points at, if any."""
    for key in ("schema:contentUrl", "schema:url"):
        value = dist.get(key)
        if isinstance(value, str):
            m = ACCESS_ID.search(value)
            if m:
                return m.group(1)
    return None


def enrich(doc, fetch_file_meta_flag=False, fetch_headers_flag=False):
    """Add Dataverse-only detail to an already-converted document, in place.

    Returns the notes describing what was added.
    """
    variables = _variable_index(doc)
    notes = []
    for dist in (doc.get("schema:distribution") or []):
        if not isinstance(dist, dict):
            continue
        access_id = _access_id(dist)
        if not access_id:
            continue

        if fetch_file_meta_flag:
            meta = fetch_file_meta(access_id)
            if meta.get("size"):
                dist["schema:contentSize"] = str(meta["size"])
            if meta.get("checksum_value"):
                dist["spdx:checksum"] = {
                    "@type": ["spdx:Checksum"],
                    "spdx:algorithm": meta.get("checksum_type", "MD5"),
                    "spdx:checksumValue": meta["checksum_value"]}
                notes.append("file size/checksum from the Dataverse API")

        if fetch_headers_flag:
            columns = fetch_tab_headers(access_id)
            if columns:
                mappings = []
                for idx, col in enumerate(columns):
                    vid, dtype = variables.get(col, (None, "xsd:string"))
                    m = {"cdif:index": idx, "schema:name": col,
                         "cdif:physicalDataType": dtype}
                    if vid:
                        m["cdif:formats_InstanceVariable"] = {"@id": vid}
                    mappings.append(m)
                dist["cdif:hasPhysicalMapping"] = mappings
                notes.append("physical mappings for %s (%d columns)"
                             % (dist.get("schema:name", access_id), len(columns)))
    return sorted(set(notes))


def convert(xml_path, doi_url=None, do_fetch_headers=False, do_fetch_file_meta=False,
            detect=True, verbose=False):
    """Convert with the shared engine, then apply Dataverse enrichment."""
    doc = convert_codebook(xml_path, doi_url=doi_url, version="25",
                           detect=detect, verbose=verbose)
    for note in enrich(doc, fetch_file_meta_flag=do_fetch_file_meta,
                       fetch_headers_flag=do_fetch_headers):
        print("  + %s" % note, file=sys.stderr)
    return doc


def main():
    p = argparse.ArgumentParser(
        description="Harvard Dataverse DDI Codebook 2.5 -> CDIF, with live enrichment")
    p.add_argument("input", help="Input DDI XML file")
    p.add_argument("--doi", help="DOI URL for the dataset (else derived from the XML)")
    p.add_argument("-o", "--output", help="Output JSON file (default: stdout)")
    p.add_argument("--fetch-headers", action="store_true",
                   help="Fetch tab file headers for physical mappings")
    p.add_argument("--fetch-file-meta", action="store_true",
                   help="Fetch file size/checksum from the Dataverse API")
    p.add_argument("--static-conformance", action="store_true",
                   help="Use the engine's built-in conformsTo instead of deriving "
                        "it from content via detect_conformance")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    doc = convert(args.input, args.doi,
                  do_fetch_headers=args.fetch_headers,
                  do_fetch_file_meta=args.fetch_file_meta,
                  detect=not args.static_conformance,
                  verbose=args.verbose)

    output = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print("Written: %s" % args.output, file=sys.stderr)
    else:
        sys.stdout.write(output)


if __name__ == "__main__":
    main()
