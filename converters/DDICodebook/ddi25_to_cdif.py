#!/usr/bin/env python3
"""
ddi25_to_cdif.py - Convert DDI Codebook 2.5 XML to CDIF JSON-LD (source-agnostic).

DDI Codebook 2.5 (root ``<codeBook version="2.5">``, namespace
``ddi:codebook:2_5``, schema
http://www.ddialliance.org/Specification/DDI-Codebook/2.5/XMLSchema/codebook.xsd;
see also the 2.6 documentation at
https://docs.ddialliance.org/DDI-Codebook/2.6/xmlschema/) shares the Codebook
element vocabulary with DDI 1.2.2 — the same study/citation, sumDscr, method,
dataAccs, ``var`` and ``fileDscr`` element names.

**This is a thin convenience wrapper.** 2.5 and 1.2.2 are handled by the one
data-driven engine, ``../DDI/ddi_sssom_to_cdif.py``, which applies the full SSSOM
crosswalk and delegates the structured value-domain / statistics / code-list /
contributor / catalog-record / physical-mapping construction to
``../DDI/ddi122_to_cdif.py``. This shim just calls that engine with
``version="25"`` (namespaces are stripped, so ``ddi:codebook:2_5`` is handled
transparently) and keeps a 2.5-named entry point for the DDICodebook directory.
Running ``python ../DDI/ddi_sssom_to_cdif.py <file> --version 25`` is equivalent.

Like its 1.2.2 sibling it is source-agnostic: the ``@id`` is the access URL
(``dataAccs/accsPlac/@URI``) when present, else a urn minted from ``IDNo`` (or
pass ``--id``); profile scope is decided per content via ``detect_conformance``.

Usage:
    python ddi25_to_cdif.py input.xml [-o output.json] [--id IRI] [--base-uri BASE]
    python ddi25_to_cdif.py Examples/XML/MWI_2019_MICS_v01_M.xml -o out.json
"""
import argparse
import json
import sys
from pathlib import Path

# The single DDI -> CDIF engine lives in the sibling DDI directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "DDI"))
from ddi_sssom_to_cdif import convert  # noqa: E402


def main():
    ap = argparse.ArgumentParser(
        description="Convert DDI Codebook 2.5 XML to CDIF JSON-LD "
                    "(wrapper over the data-driven engine, --version 25)")
    ap.add_argument("input", help="Input DDI Codebook 2.5 XML file")
    ap.add_argument("-o", "--output", help="Output JSON file (default: stdout)")
    ap.add_argument("--id", dest="explicit_id",
                    help="Explicit dataset IRI for @id (overrides auto-derived)")
    ap.add_argument("--base-uri", default="urn:ddi",
                    help="Base for minting @id from IDNo when no access URL is "
                         "present (default: urn:ddi)")
    ap.add_argument("--static-conformance", action="store_true",
                    help="Skip content-derived conformsTo (detect_conformance)")
    args = ap.parse_args()

    doc = convert(args.input, args.explicit_id, "25",
                  detect=not args.static_conformance, base_uri=args.base_uri)

    # Write exactly as ddi_sssom_to_cdif.py's own main() does, so this shim and
    # the engine produce byte-identical files.
    if args.output:
        json.dump(doc, open(args.output, "w", encoding="utf-8"),
                  indent=2, ensure_ascii=False)
        # Coded variables produce a {@graph:[dataset, ...codelists]} wrapper.
        ds = doc["@graph"][0] if "@graph" in doc else doc
        ncl = len(doc["@graph"]) - 1 if "@graph" in doc else 0
        nv = len(ds.get("schema:variableMeasured", []))
        nd = len(ds.get("schema:distribution", []))
        extra = f", {ncl} code lists" if ncl else ""
        print(f"Written: {args.output} ({nv} vars, {nd} dists{extra})")
    else:
        print(json.dumps(doc, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
