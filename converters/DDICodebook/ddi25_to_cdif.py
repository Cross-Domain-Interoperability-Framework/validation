#!/usr/bin/env python3
"""
ddi25_to_cdif.py - Convert DDI Codebook 2.5 XML to CDIF JSON-LD (source-agnostic).

DDI Codebook 2.5 (root ``<codeBook version="2.5">``, namespace
``ddi:codebook:2_5``, schema
http://www.ddialliance.org/Specification/DDI-Codebook/2.5/XMLSchema/codebook.xsd;
see also the 2.6 documentation at
https://docs.ddialliance.org/DDI-Codebook/2.6/xmlschema/) shares the Codebook
element vocabulary with DDI 1.2.2 — the same study/citation, sumDscr, method,
dataAccs, ``var`` and ``fileDscr`` element names. This converter therefore
**reuses the extraction engine of** ``../DDI/ddi122_to_cdif.py`` verbatim
(namespaces are stripped, so ``ddi:codebook:2_5`` is handled transparently) and
only supplies the 2.5 source label for the catalog-record note.

Like its 1.2.2 sibling it is source-agnostic (identifier from ``IDNo``, access
URL from ``dataAccs/accsPlac``, ``nil:missing`` for absent download URLs) and
decides profile scope per content via ``detect_conformance``. Full-datetime
production dates (e.g. NADA's ``2026-03-18T04:00:00.000Z``) are truncated to a
plain date by the shared engine.

Coded variables (``<var><catgry>`` code lists) are emitted as CDIF enumerated
value domains (skos:ConceptScheme under a cdif:EnumerationDomain) with category
and summary statistics — see the 1.2.2 converter engine.

Usage:
    python ddi25_to_cdif.py input.xml [-o output.json] [--id IRI] [--base-uri BASE]
    python ddi25_to_cdif.py Examples/XML/MWI_2019_MICS_v01_M.xml -o out.json
"""
import argparse
import json
import sys
from pathlib import Path

# Reuse the DDI-Codebook extraction engine from the 1.2.2 converter.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "DDI"))
from ddi122_to_cdif import convert  # noqa: E402

SOURCE_DESC = "DDI Codebook 2.5"


def main():
    ap = argparse.ArgumentParser(
        description="Convert DDI Codebook 2.5 XML to CDIF JSON-LD")
    ap.add_argument("input", help="Input DDI Codebook 2.5 XML file")
    ap.add_argument("-o", "--output", help="Output JSON file (default: stdout)")
    ap.add_argument("--id", dest="explicit_id",
                    help="Explicit dataset IRI for @id (overrides auto-derived)")
    ap.add_argument("--base-uri", default="urn:ddi",
                    help="Base for minting @id from IDNo when no access URL is "
                         "present (default: urn:ddi)")
    ap.add_argument("--static-conformance", action="store_true",
                    help="Keep the built-in conformsTo instead of deriving it "
                         "from content via detect_conformance")
    args = ap.parse_args()

    doc = convert(args.input, explicit_id=args.explicit_id,
                  base_uri=args.base_uri, detect=not args.static_conformance,
                  source_desc=SOURCE_DESC)

    out = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
        # Coded variables produce a {@graph:[dataset, ...codelists]} wrapper.
        ds = doc["@graph"][0] if "@graph" in doc else doc
        ncl = len(doc["@graph"]) - 1 if "@graph" in doc else 0
        nv = len(ds.get("schema:variableMeasured", []))
        nd = len(ds.get("schema:distribution", []))
        extra = f", {ncl} code lists" if ncl else ""
        print(f"Written: {args.output} ({nv} vars, {nd} dists{extra})")
    else:
        print(out)


if __name__ == "__main__":
    main()
