#!/usr/bin/env python3
"""
ddi_to_cdif.py - Convert DDI Codebook 2.5 XML to CDIF DataDescription JSON-LD.

Reads a DDI Codebook 2.5 XML file (e.g., from Harvard Dataverse DDI export)
and produces a CDIF-conformant JSON-LD document at the DataDescription level.

Maps:
  - Study-level: title, abstract, authors, keywords, spatial, temporal
  - Variable-level: DDI <var> → schema:variableMeasured / cdi:InstanceVariable
  - File-level: DDI <fileDscr> → schema:DataDownload / cdi:TabularTextDataSet
  - Physical mappings: tab file headers → cdi:hasPhysicalMapping
  - Dimensions: DDI caseQnty/varQnty → cdifq:nRows/nColumns
  - File metadata: size, checksum from Dataverse API

Usage:
    python DDI/ddi_to_cdif.py input.xml --doi https://doi.org/10.7910/DVN/XXX -o output.json
    python DDI/ddi_to_cdif.py input.xml --doi https://doi.org/10.7910/DVN/XXX --fetch-headers --fetch-file-meta
"""

import xml.etree.ElementTree as ET
import json
import sys
import os
import argparse
import urllib.request


def strip_ns(tag):
    return tag.split("}")[-1] if "}" in tag else tag


def first_text(root, tag):
    for elem in root.iter():
        if strip_ns(elem.tag) == tag and elem.text and elem.text.strip():
            return elem.text.strip()
    return None


def all_text(root, tag):
    return [e.text.strip() for e in root.iter()
            if strip_ns(e.tag) == tag and e.text and e.text.strip()]


XSD_TYPE_MAP = {"numeric": "xsd:decimal", "character": "xsd:string"}


def parse_files(root):
    """Extract file descriptors from DDI <fileDscr> elements."""
    files = {}
    current_fid = None
    current_file = None
    for elem in root.iter():
        tag = strip_ns(elem.tag)
        if tag == "fileDscr":
            current_fid = elem.attrib.get("ID", "")
            current_file = {"name": "", "access_id": current_fid.lstrip("f"),
                            "rows": None, "cols": None}
            files[current_fid] = current_file
        elif tag == "fileName" and current_file is not None:
            current_file["name"] = elem.text or ""
        elif tag == "caseQnty" and current_file is not None and elem.text:
            try:
                current_file["rows"] = int(elem.text.strip())
            except ValueError:
                pass
        elif tag == "varQnty" and current_file is not None and elem.text:
            try:
                current_file["cols"] = int(elem.text.strip())
            except ValueError:
                pass
    return files


def parse_variables(root):
    """Extract variables from DDI <var> elements."""
    variables = []
    for var in root.iter():
        if strip_ns(var.tag) != "var":
            continue
        v = {"name": var.attrib.get("name", "").strip('"'),
             "id": var.attrib.get("ID", ""),
             "interval": var.attrib.get("intrvl", ""),
             "label": "", "format": "", "stats": {}, "file_id": ""}
        for child in var:
            ctag = strip_ns(child.tag)
            if ctag == "labl":
                v["label"] = (child.text or "").strip().strip('"')
            elif ctag == "varFormat":
                v["format"] = child.attrib.get("type", "")
            elif ctag == "sumStat":
                if child.text and child.text.strip() != ".":
                    v["stats"][child.attrib.get("type", "")] = child.text.strip()
            elif ctag == "location":
                v["file_id"] = child.attrib.get("fileid", "")
        variables.append(v)
    return variables


def fetch_file_meta(access_id):
    """Fetch file size and checksum from Dataverse file API."""
    url = f"https://dataverse.harvard.edu/api/files/{access_id}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CDIF-DDI-Converter/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            d = json.loads(resp.read().decode("utf-8"))
        df = d.get("data", {}).get("dataFile", {})
        cksum = df.get("checksum", {})
        return {"size": df.get("filesize"),
                "checksum_value": cksum.get("value"),
                "checksum_type": cksum.get("type")}
    except Exception:
        return {}


def fetch_tab_headers(access_id):
    """Fetch the header row from a Dataverse .tab file."""
    url = f"https://dataverse.harvard.edu/api/access/datafile/{access_id}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "CDIF-DDI-Converter/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            header_line = resp.readline().decode("utf-8").strip()
        return [c.strip('"') for c in header_line.split("\t")]
    except Exception as e:
        print(f"  WARN: Could not fetch headers for file {access_id}: {e}",
              file=sys.stderr)
        return []


def convert(xml_path, doi_url, do_fetch_headers=False, do_fetch_file_meta=False):
    tree = ET.parse(xml_path)
    root = tree.getroot()
    files = parse_files(root)
    variables = parse_variables(root)
    changes = []

    doc = {"@context": {
        "schema": "http://schema.org/", "dcterms": "http://purl.org/dc/terms/",
        "dcat": "http://www.w3.org/ns/dcat#", "prov": "http://www.w3.org/ns/prov#",
        "cdi": "http://ddialliance.org/Specification/DDI-CDI/1.0/RDF/",
        "csvw": "http://www.w3.org/ns/csvw#", "spdx": "http://spdx.org/rdf/terms#",
        "cdifq": "http://crossdomaininteroperability.org/cdifq/",
    }, "@id": doi_url, "@type": ["schema:Dataset"]}

    doc["schema:name"] = first_text(root, "titl") or "Untitled"
    abstract = first_text(root, "abstract")
    if abstract:
        doc["schema:description"] = abstract
    doc["schema:identifier"] = doi_url
    doc["schema:dateModified"] = (first_text(root, "depDate")
                                   or first_text(root, "distDate") or "2025-01-01")
    pub = first_text(root, "distDate")
    if pub:
        doc["schema:datePublished"] = pub

    kw = list(set(all_text(root, "keyword") + all_text(root, "topcClas")))
    if kw:
        doc["schema:keywords"] = kw

    authors = all_text(root, "AuthEnty")
    if authors:
        doc["schema:creator"] = {
            "@list": [{"@type": ["schema:Person"], "schema:name": a} for a in authors]}

    distrib = first_text(root, "distrbtr")
    if distrib:
        doc["schema:publisher"] = {"@type": ["schema:Organization"], "schema:name": distrib}

    conditions = first_text(root, "restrctn")
    if conditions:
        doc["schema:conditionsOfAccess"] = [conditions]
    else:
        doc["schema:license"] = ["https://creativecommons.org/licenses/by/4.0/"]

    doc["schema:url"] = doi_url

    nations = all_text(root, "nation")
    if nations:
        doc["schema:spatialCoverage"] = [
            {"@type": ["schema:Place"], "schema:name": n} for n in nations]

    time_periods = [(tp.attrib.get("event", ""), tp.attrib.get("date"))
                    for tp in root.iter() if strip_ns(tp.tag) == "timePrd"
                    and tp.attrib.get("date")]
    if len(time_periods) >= 2:
        starts = [d for e, d in time_periods if e == "start"]
        ends = [d for e, d in time_periods if e in ("end", "single")]
        if starts and ends:
            doc["schema:temporalCoverage"] = [f"{starts[0]}/{ends[0]}"]
    elif time_periods:
        doc["schema:temporalCoverage"] = [time_periods[0][1]]

    coll_modes = all_text(root, "collMode")
    if coll_modes:
        doc["schema:measurementTechnique"] = coll_modes

    # --- Variables ---
    var_id_map = {}
    var_type_map = {}
    cdif_vars = []
    for v in variables:
        xsd_type = XSD_TYPE_MAP.get(v["format"], "xsd:string")
        vm = {"@type": ["schema:PropertyValue", "cdi:InstanceVariable"],
              "@id": f"#{v['id']}" if v["id"] else f"#{v['name']}",
              "schema:name": v["name"]}
        if v["label"]:
            vm["schema:description"] = v["label"]
        vm["cdi:intendedDataType"] = xsd_type
        if v["interval"] == "contin":
            vm["cdi:role"] = "MeasureComponent"
        elif v["interval"] == "discrete":
            vm["cdi:role"] = "AttributeComponent"
        for sk, jk in [("min", "schema:minValue"), ("max", "schema:maxValue")]:
            if sk in v["stats"]:
                try:
                    vm[jk] = float(v["stats"][sk])
                except ValueError:
                    pass
        cdif_vars.append(vm)
        var_id_map[v["name"]] = vm["@id"]
        var_type_map[v["name"]] = xsd_type

    if cdif_vars:
        doc["schema:variableMeasured"] = cdif_vars

    # --- Distributions ---
    distributions = []
    for fid, fi in files.items():
        aid = fi["access_id"]
        url = f"https://dataverse.harvard.edu/api/access/datafile/{aid}"
        dist = {"@type": ["schema:DataDownload", "cdi:TabularTextDataSet"],
                "schema:name": fi["name"], "schema:contentUrl": url,
                "schema:encodingFormat": ["text/tab-separated-values"],
                "csvw:delimiter": "\t", "csvw:header": True, "csvw:headerRowCount": 1}

        if fi["rows"] is not None:
            dist["cdifq:nRows"] = fi["rows"]
        if fi["cols"] is not None:
            dist["cdifq:nColumns"] = fi["cols"]

        if do_fetch_file_meta:
            meta = fetch_file_meta(aid)
            if meta.get("size"):
                dist["schema:contentSize"] = str(meta["size"])
            if meta.get("checksum_value"):
                dist["spdx:checksum"] = {
                    "@type": ["spdx:Checksum"],
                    "spdx:algorithm": meta.get("checksum_type", "MD5"),
                    "spdx:checksumValue": meta["checksum_value"]}
            changes.append("file size/checksum from Dataverse API")

        if do_fetch_headers:
            columns = fetch_tab_headers(aid)
            if columns:
                mappings = []
                for idx, col in enumerate(columns):
                    m = {"cdi:index": idx, "schema:name": col,
                         "cdi:physicalDataType": var_type_map.get(col, "xsd:string")}
                    vid = var_id_map.get(col)
                    if vid:
                        m["cdi:formats_InstanceVariable"] = {"@id": vid}
                    mappings.append(m)
                dist["cdi:hasPhysicalMapping"] = mappings
                changes.append(f"physical mappings from {fi['name']} ({len(columns)} cols)")

        distributions.append(dist)

    if distributions:
        doc["schema:distribution"] = distributions

    # --- subjectOf ---
    change_text = "; ".join(sorted(set(changes))) + ". " if changes else ""
    doc["schema:subjectOf"] = {
        "@type": ["schema:Dataset"],
        "schema:additionalType": ["dcat:CatalogRecord"],
        "@id": doi_url + "#metadata",
        "schema:name": f"Metadata record for: {doc['schema:name'][:120]}",
        "schema:about": {"@id": doi_url},
        "dcterms:conformsTo": [
            {"@id": "https://w3id.org/cdif/core/1.0"},
            {"@id": "https://w3id.org/cdif/discovery/1.0"},
            {"@id": "https://w3id.org/cdif/data_description/1.0"}],
        "schema:includedInDataCatalog": {
            "@type": ["schema:DataCatalog"],
            "schema:name": "Harvard Dataverse",
            "schema:url": "https://dataverse.harvard.edu/"},
        "schema:description": (
            f"Metadata harvested from Harvard Dataverse DDI Codebook 2.5 export "
            f"({doi_url.replace('https://doi.org/', 'doi:')}, "
            f"/api/datasets/export?exporter=ddi). "
            f"Converted to CDIF DataDescription profile by ddi_to_cdif.py. "
            f"DDI <var> mapped to variableMeasured/cdi:InstanceVariable "
            f"(varFormat to intendedDataType, intrvl to role, sumStat to minValue/maxValue). "
            f"DDI dimensns (caseQnty/varQnty) mapped to cdifq:nRows/nColumns. "
            f"{change_text}"
            f"Distributions typed as cdi:TabularTextDataSet with CSVW properties.")}

    return doc


def main():
    parser = argparse.ArgumentParser(
        description="Convert DDI Codebook 2.5 XML to CDIF DataDescription JSON-LD")
    parser.add_argument("input", help="Input DDI XML file")
    parser.add_argument("--doi", required=True, help="DOI URL for the dataset")
    parser.add_argument("-o", "--output", help="Output JSON file (default: stdout)")
    parser.add_argument("--fetch-headers", action="store_true",
                        help="Fetch tab file headers for physical mappings")
    parser.add_argument("--fetch-file-meta", action="store_true",
                        help="Fetch file size/checksum from Dataverse API")
    args = parser.parse_args()

    doc = convert(args.input, args.doi,
                  do_fetch_headers=args.fetch_headers,
                  do_fetch_file_meta=args.fetch_file_meta)

    output = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        vm = doc.get("schema:variableMeasured", [])
        dist = doc.get("schema:distribution", [])
        print(f"Written: {args.output} ({len(vm)} vars, {len(dist)} dists)")
    else:
        print(output)


if __name__ == "__main__":
    main()
