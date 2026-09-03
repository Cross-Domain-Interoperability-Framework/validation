#!/usr/bin/env python3
"""
ddi2cdif.py -- single DDI -> CDIF entry point: sniff the flavor of an incoming
DDI file and route it to the right converter.

Recognised flavors and where they go:

  - DDI Codebook 1.2.2  ``<codeBook version="1.2.2" xmlns="http://www.icpsr.umich.edu/DDI">``
  - DDI Codebook 2.5    ``<codeBook version="2.5"   xmlns="ddi:codebook:2_5">``
        Both go to the one data-driven engine, ``ddi_sssom_to_cdif.py``; the
        version (which SSSOM worksheets to apply) is chosen from the sniff --
        a 1.x element set uses the 1.2.2 worksheets, a 2.x set the 2.5 worksheets.

  - DDI-CDI (RDF / JSON-LD)  -> a **separate branch**. The DDI-CDI model is a
        graph, not a codeBook XML tree, so it needs its own handler; that handler
        is not implemented yet, and this dispatcher raises a clear error rather
        than mis-parsing it as Codebook.

  - DDI Lifecycle 3.x  ``<DDIInstance>``  -> a different DDI product line from the
        Codebook engine; not supported.

Out of scope on purpose: **source-specific** variants such as Harvard Dataverse's
live-API enrichment (file size/checksum from the Dataverse API) live in
``ddi_to_cdif.py`` and are not dispatched here -- this front door is
source-agnostic and offline.

Usage:
    python ddi2cdif.py input.xml [-o out.json] [--id IRI] [--base-uri BASE]
    python ddi2cdif.py input.xml --print-flavor      # just report the flavor
"""
import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ddi_sssom_to_cdif import convert as _convert_codebook  # noqa: E402
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'DDI-CDI'))
from ddicdi_to_cdif import convert as _convert_ddicdi_xml  # noqa: E402


def _local(tag):
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _ns(tag):
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


def sniff_flavor(path):
    """Return the DDI flavor of `path`: 'codebook-1.2.2', 'codebook-2.5',
    'ddi-cdi', 'ddi-lifecycle-3', or 'unknown'."""
    try:
        root = ET.parse(path).getroot()
    except (ET.ParseError, UnicodeDecodeError):
        root = None
    if root is not None:
        tag, ns = _local(root.tag), _ns(root.tag)
        if tag == "codeBook":
            ver = (root.get("version") or "").strip()
            if ver.startswith("2") or "codebook:2" in ns:
                return "codebook-2.5"
            if ver.startswith("1") or "icpsr" in ns.lower():
                return "codebook-1.2.2"
            # A bare <codeBook> with no version/namespace hint: the 1.2.2 element
            # set is the safe subset (2.5 is a superset), so read it as 1.2.2.
            return "codebook-1.2.2"
        if tag in ("DDIInstance", "FragmentInstance"):
            return "ddi-lifecycle-3"
        # DDI-CDI has an XML serialisation as well as an RDF one. Its
        # instances parse as XML, so they must be recognised here; the
        # RDF check below only ever sees files that are not XML.
        if tag == "DDICDIModels" or "DDI-CDI" in ns:
            return "ddi-cdi-xml"
        return "unknown"
    # Not XML -> the only DDI flavor left is DDI-CDI (RDF / JSON-LD).
    try:
        doc = json.load(open(path, encoding="utf-8"))
    except Exception:
        return "unknown"
    blob = json.dumps(doc)
    if '"cdi:' in blob or "DDI-CDI" in blob or "ddialliance.org/Specification/DDI-CDI" in blob:
        return "ddi-cdi"
    return "unknown"


def sniff_source(path):
    """Best-effort *producer* of a DDI file -- a second axis below the schema
    flavor: 'dataverse', 'nada', or 'generic'. Both a Dataverse and a NADA export
    are valid Codebook 2.5; what separates them is producer convention, and the
    reliable signals are the producer's own *branding/namespacing*, NOT the
    generic structural conventions (fileDscr ID style, empty accsPlac) that
    overlap across producers -- so those are deliberately not used here.

      dataverse -> <distrbtr>...Dataverse, note types DVN:/VDC:/DATAVERSE:,
                   or a dataverse.harvard.edu file URL / <fileDscr URI=...dataverse>
      nada      -> names itself in <software>NADA</software>
      generic   -> anything else (incl. Nesstar 1.2.2 exports)
    """
    try:
        blob = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return "generic"
    if (re.search(r'<distrbtr[^>]*>[^<]*Dataverse', blob)
            or re.search(r'<notes[^>]*type="(?:DVN|VDC|DATAVERSE):', blob)
            or re.search(r'<fileDscr[^>]*URI="https?://[^"]*dataverse', blob)
            or 'dataverse.harvard.edu/api/access/datafile/' in blob):
        return "dataverse"
    if re.search(r'<software[^>]*>\s*NADA\b', blob):
        return "nada"
    return "generic"


_CODEBOOK_VERSION = {"codebook-1.2.2": "122", "codebook-2.5": "25"}


def convert(path, explicit_id=None, base_uri="urn:ddi", detect=True):
    """Sniff `path` and convert it, dispatching to the engine that fits its
    flavor. XML DDI-CDI goes to ddicdi_to_cdif.py; NotImplementedError is raised
    for the branches with no handler (RDF/JSON-LD DDI-CDI, Lifecycle 3.x), and
    ValueError when the flavor cannot be determined."""
    flavor = sniff_flavor(path)
    if flavor in _CODEBOOK_VERSION:
        return _convert_codebook(path, explicit_id, _CODEBOOK_VERSION[flavor],
                                 detect=detect, base_uri=base_uri)
    if flavor == "ddi-cdi-xml":
        return _convert_ddicdi_xml(path, explicit_id, base_uri="urn:ddi-cdi",
                                   detect=detect)
    if flavor == "ddi-cdi":
        raise NotImplementedError(
            "DDI-CDI in its RDF / JSON-LD serialisation detected. The XML "
            "serialisation is handled by DDI-CDI/ddicdi_to_cdif.py, which this "
            "dispatcher routes to; the RDF form needs a graph-based reader that "
            "is not implemented yet.")
    if flavor == "ddi-lifecycle-3":
        raise NotImplementedError(
            "DDI Lifecycle 3.x (<DDIInstance>) detected -- a different DDI "
            "product line from the Codebook engine; not supported.")
    raise ValueError(f"Could not determine a supported DDI flavor for {path!r}.")


def main():
    ap = argparse.ArgumentParser(
        description="Sniff a DDI file's flavor and convert it to CDIF JSON-LD")
    ap.add_argument("input")
    ap.add_argument("-o", "--output")
    ap.add_argument("--id", dest="explicit_id",
                    help="Explicit dataset @id (overrides the auto-derived one)")
    ap.add_argument("--base-uri", default="urn:ddi",
                    help="Base for minting @id from IDNo when no access URL is "
                         "present (default: urn:ddi)")
    ap.add_argument("--static-conformance", action="store_true",
                    help="Skip content-derived conformsTo (detect_conformance)")
    ap.add_argument("--print-flavor", action="store_true",
                    help="Only report the detected flavor, do not convert")
    ap.add_argument("--print-source", action="store_true",
                    help="Only report the detected producer (dataverse/nada/generic)")
    a = ap.parse_args()

    flavor = sniff_flavor(a.input)
    source = sniff_source(a.input)
    if a.print_flavor:
        print(flavor)
        return
    if a.print_source:
        print(source)
        return
    try:
        doc = convert(a.input, a.explicit_id, a.base_uri,
                      detect=not a.static_conformance)
    except (NotImplementedError, ValueError) as e:
        print(f"ddi2cdif: {e}", file=sys.stderr)
        sys.exit(2)
    if source == "dataverse":
        print("ddi2cdif: Dataverse export detected -- per-file download URLs are "
              "read from <fileDscr URI=...>. For live file size/checksum "
              "enrichment, use ddi_to_cdif.py --fetch-file-meta.", file=sys.stderr)
    if a.output:
        json.dump(doc, open(a.output, "w", encoding="utf-8"),
                  indent=2, ensure_ascii=False)
        ds = doc["@graph"][0] if "@graph" in doc else doc
        print(f"wrote {a.output} [{flavor}/{source}] "
              f"({len(ds.get('schema:variableMeasured', []))} vars, "
              f"{len(ds.get('schema:distribution', []))} dists)")
    else:
        print(json.dumps(doc, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
