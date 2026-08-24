#!/usr/bin/env python3
"""ConvertToSOSO.py — CDIF core+discovery JSON-LD -> ESIP Science-on-Schema.org.

Converts a CDIF Discovery-profile record (``schema:``-prefixed, framed tree, with
a ``schema:subjectOf`` catalog record) into an ESIP Science-on-Schema.org (SOSO)
v1.3 ``schema:Dataset`` JSON-LD document.

CDIF Discovery and SOSO are both schema.org profiles, so this is mostly a
structural alignment rather than a vocabulary translation:

  * ``@context`` -> SOSO style (``{"@vocab": "http://schema.org/"}`` plus any
    non-schema prefixes the document still needs). SOSO's canonical namespace is
    ``http://schema.org/`` (its SHACL rejects the ``https://`` variant).
  * ``schema:`` prefixes are stripped from property names and ``@type`` values,
    because SOSO uses bare schema.org terms via ``@vocab``. Non-schema prefixes
    (``dcterms:``, ``prov:``, ``dqv:``, ``geosparql:``, ``spdx:``, ``time:``,
    ``cdi:``) are kept.
  * the CDIF catalog record (``schema:subjectOf`` tagged ``dcat:CatalogRecord``
    with ``dcterms:conformsTo``) is dropped — SOSO has no metadata-conformance
    mechanism, and its ``subjectOf`` means something else (links to alternative
    metadata records). See CDIF-Discovery-vs-SOSO-comparison.md, Discussion §2/§11.
  * CDIF-only properties (``dateModified``, ``conditionsOfAccess``,
    ``relatedLink``, ``measurementTechnique``, ``dqv:hasQualityMeasurement`` …)
    are passed through unchanged — SOSO is open-world and does not reject extras.
  * warnings are emitted for SOSO-required fields that CDIF leaves optional
    (``description``, ``version``, ``url``, ``license``) so the caller knows where
    the result may still fall short of SOSO's (stricter-than-its-guide) SHACL.
    Values are never fabricated.

Mapping reference: doc-corediscovery/documents/CDIF-Discovery-vs-SOSO-comparison.md
and ESIPFed/science-on-schema.org issue #283.

Usage:
    python ConvertToSOSO.py input-cdif.json -o output-soso.json [-v]
"""

import argparse
import copy
import json
import sys

SCHEMA_PREFIX = "schema:"
SOSO_VOCAB = "http://schema.org/"

# Namespaces kept (with their prefix) in the SOSO output when the document still
# uses them — SOSO is open-world, so CDIF's extensions ride along untouched.
KEEP_NAMESPACES = {
    "dcterms": "http://purl.org/dc/terms/",
    "dcat": "http://www.w3.org/ns/dcat#",
    "prov": "http://www.w3.org/ns/prov#",
    "dqv": "http://www.w3.org/ns/dqv#",
    "spdx": "http://spdx.org/rdf/terms#",
    "geosparql": "http://www.opengis.net/ont/geosparql#",
    "time": "http://www.w3.org/2006/time#",
    "cdi": "http://ddialliance.org/Specification/DDI-CDI/1.0/RDF/",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "csvw": "http://www.w3.org/ns/csvw#",
}

# schema.org properties SOSO requires (guide + SHACL). Used only to warn when a
# converted record is missing one — never to invent a value.
SOSO_REQUIRED = ["name", "description", "url", "version", "identifier", "license"]


def _is_catalog_record(node):
    """True if a subjectOf entry is a CDIF catalog record (additionalType
    dcat:CatalogRecord, in either prefixed or full-IRI form)."""
    if not isinstance(node, dict):
        return False
    at = node.get("schema:additionalType") or node.get("additionalType")
    if at is None:
        return False
    at = at if isinstance(at, list) else [at]
    for v in at:
        if isinstance(v, dict):
            v = v.get("@id")
        if isinstance(v, str) and v in (
                "dcat:CatalogRecord", "http://www.w3.org/ns/dcat#CatalogRecord"):
            return True
    return False


def _pick_dataset(cdif):
    """Return the root dataset node from a CDIF document. If the document is a
    flattened graph, pick the schema:Dataset that is not a catalog record."""
    graph = cdif.get("@graph")
    if isinstance(graph, list):
        for node in graph:
            if not isinstance(node, dict):
                continue
            t = node.get("@type")
            t = t if isinstance(t, list) else [t]
            is_dataset = any(str(x).endswith("Dataset") for x in t if x)
            if is_dataset and not _is_catalog_record(node):
                return node
        for node in graph:
            if isinstance(node, dict):
                return node
    return cdif


def _embed(node, nodes_by_id, on_path):
    """Recursively inline ``{"@id": X}`` references from a flattened graph into a
    tree. ``on_path`` holds the @ids currently being embedded so a back-reference
    (e.g. a catalog record's ``schema:about`` pointing at the dataset) is left as
    a bare reference instead of recursing forever."""
    if isinstance(node, dict):
        if (set(node.keys()) == {"@id"} and node["@id"] in nodes_by_id
                and node["@id"] not in on_path):
            return _embed(nodes_by_id[node["@id"]], nodes_by_id, on_path)
        nid = node.get("@id")
        nxt = on_path | ({nid} if isinstance(nid, str) else set())
        return {k: _embed(v, nodes_by_id, nxt) for k, v in node.items()}
    if isinstance(node, list):
        return [_embed(x, nodes_by_id, on_path) for x in node]
    return node


def _resolve_dataset(cdif):
    """Return the dataset as an embedded tree — inlining @id references when the
    input is a flattened @graph, or returning the framed root as-is."""
    root = _pick_dataset(cdif)
    graph = cdif.get("@graph")
    if isinstance(graph, list):
        nodes_by_id = {n["@id"]: n for n in graph
                       if isinstance(n, dict) and isinstance(n.get("@id"), str)}
        seed = {root["@id"]} if isinstance(root.get("@id"), str) else set()
        return _embed(root, nodes_by_id, seed)
    return copy.deepcopy(root)


def _strip_key(key):
    """schema:name -> name; @-keywords and other prefixes are left unchanged."""
    if isinstance(key, str) and key.startswith(SCHEMA_PREFIX):
        return key[len(SCHEMA_PREFIX):]
    return key


def _strip_value_prefix(val):
    """Strip a leading schema: from a bare type/enum string value."""
    if isinstance(val, str) and val.startswith(SCHEMA_PREFIX):
        return val[len(SCHEMA_PREFIX):]
    return val


def _strip_schema(obj):
    """Recursively drop the schema: prefix from keys and from @type values;
    leave non-schema prefixes (dcterms:, prov:, cdi:, …) intact."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            nk = _strip_key(k)
            if nk == "@type":
                if isinstance(v, list):
                    v = [_strip_value_prefix(x) for x in v]
                else:
                    v = _strip_value_prefix(v)
                out[nk] = _strip_schema(v)
            else:
                out[nk] = _strip_schema(v)
        return out
    if isinstance(obj, list):
        return [_strip_schema(x) for x in obj]
    return obj


def _used_prefixes(obj, found):
    """Collect the set of non-schema namespace prefixes still used as key
    prefixes or @type/@id CURIE values anywhere in the (stripped) document."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and ":" in k and not k.startswith("@"):
                found.add(k.split(":", 1)[0])
            if k in ("@type",):
                vals = v if isinstance(v, list) else [v]
                for x in vals:
                    if isinstance(x, str) and ":" in x and not x.startswith("http"):
                        found.add(x.split(":", 1)[0])
            _used_prefixes(v, found)
    elif isinstance(obj, list):
        for x in obj:
            _used_prefixes(x, found)


def convert_cdif_to_soso(cdif, verbose=False, https=False):
    """Convert a CDIF core+discovery record (dict) to a SOSO Dataset (dict).

    Returns (soso_dict, warnings_list). Never mutates the input.

    ``https``: emit the schema.org namespace as ``https://schema.org/`` instead of
    the default ``http://schema.org/``. SOSO's guide states ``http://schema.org/``
    is canonical (and its namespace-check shapes flag ``https://``), but SOSO's
    *own* v1.3 requirement shapes are written against ``https://schema.org/`` and
    only validate data in that namespace — so ``--https`` is offered for callers
    who want the output to be exercised by SOSO's SHACL (Google accepts both).
    """
    vocab = "https://schema.org/" if https else SOSO_VOCAB
    warnings = []
    dataset = _resolve_dataset(cdif)
    if not isinstance(dataset, dict):
        raise ValueError("Could not locate a dataset node in the CDIF document.")

    # Drop the CDIF catalog record(s) — no SOSO equivalent.
    subj = dataset.get("schema:subjectOf") or dataset.get("subjectOf")
    if subj is not None:
        entries = subj if isinstance(subj, list) else [subj]
        kept = [e for e in entries if not _is_catalog_record(e)]
        dataset.pop("schema:subjectOf", None)
        dataset.pop("subjectOf", None)
        if kept:
            # Non-catalog subjectOf (rare) is preserved.
            dataset["schema:subjectOf"] = kept if len(kept) > 1 else kept[0]
        if len(kept) < len(entries):
            warnings.append("Dropped CDIF catalog record (subjectOf/conformsTo) "
                            "— SOSO has no metadata-conformance mechanism.")

    # Strip schema: prefixes from keys and @type values.
    soso = _strip_schema(dataset)

    # Normalize the root @type to the bare SOSO form, keeping any extra types.
    t = soso.get("@type")
    if isinstance(t, list):
        soso["@type"] = t[0] if len(t) == 1 else t
    if not soso.get("@type"):
        soso["@type"] = "Dataset"

    # Build the SOSO @context: @vocab for schema.org + any surviving prefixes.
    prefixes = set()
    _used_prefixes(soso, prefixes)
    context = {"@vocab": vocab}
    for p in sorted(prefixes):
        if p in KEEP_NAMESPACES:
            context[p] = KEEP_NAMESPACES[p]
    soso["@context"] = context
    # Put @context / @id / @type first for readability.
    ordered = {}
    for key in ("@context", "@id", "@type"):
        if key in soso:
            ordered[key] = soso.pop(key)
    ordered.update(soso)
    soso = ordered

    # Warn about SOSO-required fields the record lacks (never fabricate).
    for req in SOSO_REQUIRED:
        if req not in soso:
            if req == "url" and "distribution" in soso:
                warnings.append("SOSO requires schema:url (exactly 1); CDIF record "
                                "has distribution but no landing-page url.")
            elif req == "license" and "conditionsOfAccess" in soso:
                warnings.append("SOSO requires schema:license; CDIF record has "
                                "conditionsOfAccess but no license.")
            else:
                warnings.append(f"SOSO requires schema:{req}; not present in the "
                                f"CDIF record.")

    if verbose:
        for w in warnings:
            print(f"  WARNING: {w}", file=sys.stderr)

    return soso, warnings


def main():
    parser = argparse.ArgumentParser(
        description="Convert a CDIF core+discovery JSON-LD record to ESIP "
                    "Science-on-Schema.org (SOSO) v1.3 Dataset JSON-LD.")
    parser.add_argument("input", help="Input CDIF JSON-LD file")
    parser.add_argument("-o", "--output", help="Output SOSO JSON-LD file "
                        "(default: stdout)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Print conversion warnings to stderr")
    parser.add_argument("--https", action="store_true",
                        help="Emit https://schema.org/ instead of the default "
                             "http://schema.org/ (see note re: SOSO v1.3 SHACL)")
    args = parser.parse_args()

    with open(args.input, encoding="utf-8") as f:
        cdif = json.load(f)

    soso, warnings = convert_cdif_to_soso(cdif, verbose=args.verbose,
                                          https=args.https)

    text = json.dumps(soso, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"Wrote {args.output}  ({len(warnings)} warning(s))",
              file=sys.stderr)
    else:
        print(text)

    return 0


if __name__ == "__main__":
    sys.exit(main())
