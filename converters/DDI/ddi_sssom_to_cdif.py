#!/usr/bin/env python3
"""Data-driven DDI Codebook -> CDIF converter.

Unlike ddi_to_cdif.py (hand-coded), this engine reads the SSSOM mapping tables
(via converters/mappings/ddi_mappings.json) and applies them generically, so the
worksheets are the single source of truth: edit a TSV, run sync_ddi_mappings.py,
and the new mapping takes effect here with no code change.

Contexts implemented
--------------------
* dataset singletons        -- $.schema:<prop>            (and nested, e.g. $.schema:subjectOf.<prop>)
* per-variable              -- $.schema:variableMeasured[*].<leaf>   (one item per <var>)
* per-distribution          -- $.schema:distribution[*].<leaf>       (one item per <fileDscr>)

Concatenation convention (from the worksheet)
---------------------------------------------
When several DDI fields target the same scalar CDIF path, their values are joined
with newlines, each line prefixed by that mapping's `object_label` ("label: value"),
empty fields skipped. A lone contributor is placed as a plain value. List targets
(keywords, spatialCoverage) collect instead of concatenating.

Deferred (skipped with a note; see --verbose): provenance contexts
$.prov:wasGeneratedBy[*] and $.prov:wasDerivedFrom[*], and $.schema:relatedLink.
These need multi-node assembly and land in a follow-up.
"""
import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
MAPPINGS_JSON = os.path.normpath(os.path.join(HERE, "..", "mappings", "ddi_mappings.json"))

CONTEXT = {
    "schema": "http://schema.org/", "dcterms": "http://purl.org/dc/terms/",
    "dcat": "http://www.w3.org/ns/dcat#", "prov": "http://www.w3.org/ns/prov#",
    "cdi": "http://ddialliance.org/Specification/DDI-CDI/1.0/RDF/",
    "csvw": "http://www.w3.org/ns/csvw#", "spdx": "http://spdx.org/rdf/terms#",
    "cdifq": "http://crossdomaininteroperability.org/cdifq/",
    "dqv": "http://www.w3.org/ns/dqv#", "geo": "http://www.opengis.net/ont/geosparql#",
    "oa": "http://www.w3.org/ns/oa#", "bios": "https://bioschemas.org/",
}
# XSD type per DDI varFormat
XSD_TYPE = {"numeric": "xsd:decimal", "character": "xsd:string"}
# list-valued dataset targets: collect values instead of concatenating
LIST_LEAF = {"schema:keywords"}
# deferred target heads (skipped, reported)
DEFER_HEADS = ("prov:wasGeneratedBy", "prov:wasDerivedFrom", "schema:relatedLink")


def strip_ns(tag):
    return tag.split("}", 1)[-1]


def iter_local(root, name):
    for e in root.iter():
        if strip_ns(e.tag) == name:
            yield e


def text_of(elem):
    return " ".join("".join(elem.itertext()).split())


def descend(elem, parts):
    """Return the elements (or attribute-value strings) reached by a dotted
    element path relative to `elem`. A final `@attr` segment yields attributes."""
    attr = None
    if parts and "@" in parts[-1]:
        parts = list(parts)
        parts[-1], attr = parts[-1].split("@", 1)
        if parts[-1] == "":
            parts = parts[:-1]
    nodes = [elem]
    for p in parts:
        nxt = []
        for n in nodes:
            nxt += [c for c in n.iter() if c is not n and strip_ns(c.tag) == p]
        nodes = nxt
    if attr:
        return [n.get(attr) for n in nodes if n.get(attr)]
    return nodes


def values_at(elem, parts):
    out = []
    for node in descend(elem, parts):
        s = node if isinstance(node, str) else text_of(node)
        if s:
            out.append(s)
    return out


# ---- target-path parsing -------------------------------------------------

def split_target(jp):
    """('$.schema:variableMeasured[*].schema:description')
        -> (head, leaf) where head is the context container and leaf the rest.
    head is one of: 'dataset', 'variable', 'distribution', or a deferred head."""
    body = jp[2:] if jp.startswith("$.") else jp.lstrip("$")
    if body.startswith("schema:variableMeasured[*]"):
        return "variable", body[len("schema:variableMeasured[*]"):].lstrip(".")
    if body.startswith("schema:distribution[*]"):
        return "distribution", body[len("schema:distribution[*]"):].lstrip(".")
    for h in DEFER_HEADS:
        if body == h or body.startswith(h + "[*]") or body.startswith(h + "."):
            return "_defer", h
    return "dataset", body


# ---- value shaping / concatenation --------------------------------------

def concat(contribs):
    """contribs: list of (label, value). Join per the worksheet convention,
    de-duplicating identical values (so a field reachable by two paths, or a
    label repeated verbatim, collapses to one entry)."""
    parts, seen = [], set()
    for lbl, v in contribs:
        if v and v not in seen:
            seen.add(v)
            parts.append((lbl, v))
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0][1]
    return "\n".join(f"{lbl}: {v}" for lbl, v in parts)


def shape_dataset(leaf, object_id, contribs):
    """Turn gathered contributions into the value placed at a dataset leaf."""
    flat = [v for _, vs in contribs for v in (vs if isinstance(vs, list) else [vs]) if v]
    if leaf in LIST_LEAF:
        seen, out = set(), []
        for v in flat:
            if v not in seen:
                seen.add(v); out.append(v)
        return out or None
    if leaf == "schema:spatialCoverage" or object_id == "schema:spatialCoverage":
        return [{"@type": ["schema:Place"], "schema:name": v} for v in flat] or None
    if object_id == "schema:creator":
        return {"@list": [{"@type": ["schema:Person"], "schema:name": v} for v in flat]} if flat else None
    if object_id in ("schema:publisher", "schema:provider", "schema:maintainer", "schema:funder"):
        return {"@type": ["schema:Organization"], "schema:name": flat[0]} if flat else None
    # scalar string target -> concatenate with labels
    return concat([(lbl, " ".join(vs) if isinstance(vs, list) else vs) for lbl, vs in contribs])


def set_path(container, leaf, value):
    """Place value at a (possibly nested, colon-keyed) leaf path on a dict."""
    if value is None or leaf == "":
        return
    keys = leaf.split(".")
    d = container
    for k in keys[:-1]:
        k = k.replace("[*]", "")
        d = d.setdefault(k, {})
    d[keys[-1].replace("[*]", "")] = value


# ---- conversion ----------------------------------------------------------

def load_mappings(version):
    allm = json.load(open(MAPPINGS_JSON, encoding="utf-8"))
    merged = {}
    merged.update(allm.get("ddi-common-to-cdif", {}))
    merged.update(allm.get(f"ddi{version}-to-cdif", {}))
    # strip the CURIE prefix from each subject -> dotted DDI path
    out = {}
    for subj, m in merged.items():
        path = subj.split(":", 1)[1] if ":" in subj else subj
        out[path] = m
    return out


def gather(elem, subj_paths, mapping, anchor_len=0):
    """For a set of DDI paths sharing one target, collect (label, values)."""
    contribs = []
    for path in subj_paths:
        parts = path.split(".")[anchor_len:]
        vals = values_at(elem, parts)
        contribs.append((mapping[path]["object_label"] or parts[-1], vals))
    return contribs


def convert(xml_path, doi_url, version, detect=True, verbose=False):
    root = ET.parse(xml_path).getroot()
    maps = load_mappings(version)

    # bucket mapped paths by context/target
    ds_by_leaf, var_by_leaf, dist_by_leaf, deferred = {}, {}, {}, []
    for path, m in maps.items():
        if not m["object_id"].strip():
            continue
        ctx, leaf = split_target(m["object_json_path"])
        if ctx == "_defer":
            deferred.append(path); continue
        bucket = {"dataset": ds_by_leaf, "variable": var_by_leaf, "distribution": dist_by_leaf}[ctx]
        bucket.setdefault((leaf, m["object_id"]), []).append(path)

    doc = {"@context": CONTEXT, "@id": doi_url, "@type": ["schema:Dataset"]}

    # dataset singletons
    for (leaf, oid), paths in ds_by_leaf.items():
        contribs = gather(root, paths, maps)
        val = shape_dataset(leaf, oid, contribs)
        if val is not None:
            set_path(doc, leaf, val)
    doc.setdefault("@id", doi_url)
    doc["schema:identifier"] = doc.get("schema:identifier", doi_url)
    doc["schema:url"] = doi_url

    # per-variable
    vitems = []
    for var in iter_local(root, "var"):
        item = {"@type": ["schema:PropertyValue", "cdi:InstanceVariable"]}
        nm = var.get("name") or (values_at(var, ["labl"]) or [""])[0]
        if nm:
            item["@id"] = "#" + nm.replace(" ", "_")
        for (leaf, oid), paths in var_by_leaf.items():
            contribs = gather(var, paths, maps, anchor_len=2)  # drop dataDscr.var
            if oid == "cdi:role":
                fmt = var.get("intrvl", "")
                item["cdi:role"] = {"contin": "MeasureComponent",
                                    "discrete": "AttributeComponent"}.get(fmt) or None
                if item["cdi:role"] is None:
                    del item["cdi:role"]
                continue
            if oid == "cdi:intendedDataType":
                vf = (values_at(var, ["varFormat"]) or [""])
                item["cdi:intendedDataType"] = XSD_TYPE.get(var.get("intrvl", ""), "xsd:string")
                continue
            val = shape_dataset(leaf, oid, contribs)
            if val is not None:
                set_path(item, leaf, val)
        vitems.append(item)
    if vitems:
        doc["schema:variableMeasured"] = vitems

    # per-distribution
    ditems = []
    for fd in iter_local(root, "fileDscr"):
        item = {"@type": ["schema:DataDownload", "cdi:TabularTextDataSet"]}
        for (leaf, oid), paths in dist_by_leaf.items():
            contribs = gather(fd, paths, maps, anchor_len=1)  # drop fileDscr
            val = shape_dataset(leaf, oid, contribs)
            if val is not None:
                set_path(item, leaf, val)
        ditems.append(item)
    if ditems:
        doc["schema:distribution"] = ditems

    if verbose and deferred:
        print(f"  [deferred] {len(deferred)} provenance/relatedLink mapping(s) not yet "
              f"applied: {sorted(deferred)[:4]}...", file=sys.stderr)

    if detect:
        try:
            sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..")))
            from detect_conformance import detect_conformance, apply_conformance
            uris = detect_conformance(doc)
            apply_conformance(doc, uris)
        except Exception as e:
            if verbose:
                print(f"  (conformance detection skipped: {e})", file=sys.stderr)
    return doc


def main():
    ap = argparse.ArgumentParser(description="Data-driven DDI Codebook -> CDIF converter")
    ap.add_argument("xml")
    ap.add_argument("--doi", required=True, help="dataset DOI/landing-page URL (@id)")
    ap.add_argument("--version", choices=["25", "122"], default="25",
                    help="DDI Codebook version of the input (default 25)")
    ap.add_argument("-o", "--output")
    ap.add_argument("--no-detect", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    doc = convert(a.xml, a.doi, a.version, detect=not a.no_detect, verbose=a.verbose)
    out = a.output or (os.path.splitext(a.xml)[0] + "-cdif.json")
    json.dump(doc, open(out, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
