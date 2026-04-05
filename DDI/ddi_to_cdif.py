#!/usr/bin/env python3
"""Convert DDI Codebook 2.5 XML to CDIF DataDescription JSON-LD."""
import xml.etree.ElementTree as ET
import json
import sys
import os
import re

def strip_ns(tag):
    return tag.split('}')[-1] if '}' in tag else tag

def iter_tag(root, tag):
    for elem in root.iter():
        if strip_ns(elem.tag) == tag:
            yield elem

def first_text(root, tag):
    for elem in iter_tag(root, tag):
        if elem.text and elem.text.strip():
            return elem.text.strip()
    return None

def all_text(root, tag):
    return [e.text.strip() for e in iter_tag(root, tag) if e.text and e.text.strip()]

def convert_ddi_to_cdif(xml_path, dataset_doi=None):
    tree = ET.parse(xml_path)
    root = tree.getroot()

    doc = {
        "@context": {
            "schema": "http://schema.org/",
            "dcterms": "http://purl.org/dc/terms/",
            "dcat": "http://www.w3.org/ns/dcat#",
            "prov": "http://www.w3.org/ns/prov#",
            "cdi": "http://ddialliance.org/Specification/DDI-CDI/1.0/RDF/",
            "csvw": "http://www.w3.org/ns/csvw#",
            "spdx": "http://spdx.org/rdf/terms#",
        }
    }

    # --- Identity ---
    doi_text = None
    for idno in iter_tag(root, 'IDNo'):
        if idno.text and 'doi' in (idno.attrib.get('agency', '') + idno.text).lower():
            doi_text = idno.text.strip()
            break
    if not doi_text:
        doi_text = first_text(root, 'IDNo')

    dataset_id = dataset_doi or (f"https://doi.org/{doi_text}" if doi_text else f"urn:ddi:{os.path.basename(xml_path)}")
    doc["@id"] = dataset_id
    doc["@type"] = ["schema:Dataset"]

    # --- Basic metadata ---
    title = first_text(root, 'titl')
    doc["schema:name"] = title or "Untitled"

    abstract = first_text(root, 'abstract')
    if abstract:
        doc["schema:description"] = abstract

    doc["schema:identifier"] = dataset_id
    doc["schema:dateModified"] = first_text(root, 'depDate') or first_text(root, 'distDate') or "2025-01-01"

    pub_date = first_text(root, 'distDate')
    if pub_date:
        doc["schema:datePublished"] = pub_date

    # --- Keywords ---
    keywords = all_text(root, 'keyword')
    topc = all_text(root, 'topcClas')
    all_kw = keywords + topc
    if all_kw:
        doc["schema:keywords"] = list(set(all_kw))

    # --- Creator ---
    authors = all_text(root, 'AuthEnty')
    if authors:
        doc["schema:creator"] = {
            "@list": [{"@type": ["schema:Person"], "schema:name": a} for a in authors]
        }

    # --- Publisher / distributor ---
    distrib = first_text(root, 'distrbtr')
    if distrib:
        doc["schema:publisher"] = {"@type": ["schema:Organization"], "schema:name": distrib}

    # --- License ---
    conditions = first_text(root, 'restrctn')
    if conditions:
        doc["schema:conditionsOfAccess"] = [conditions]
    else:
        doc["schema:license"] = ["https://creativecommons.org/licenses/by/4.0/"]

    # --- URL ---
    holdings = None
    for h in iter_tag(root, 'holdings'):
        uri = h.attrib.get('URI')
        if uri:
            holdings = uri
            break
    if holdings:
        doc["schema:url"] = holdings

    # --- Spatial coverage ---
    nations = all_text(root, 'nation')
    geog = first_text(root, 'geogCover')
    if nations or geog:
        places = []
        for n in nations:
            places.append({"@type": ["schema:Place"], "schema:name": n})
        if geog and geog not in nations:
            places.append({"@type": ["schema:Place"], "schema:name": geog})
        doc["schema:spatialCoverage"] = places

    # --- Temporal coverage ---
    time_periods = []
    for tp in iter_tag(root, 'timePrd'):
        date = tp.attrib.get('date')
        event = tp.attrib.get('event', '')
        if date:
            time_periods.append((event, date))
    if len(time_periods) >= 2:
        starts = [d for e, d in time_periods if e == 'start']
        ends = [d for e, d in time_periods if e in ('end', 'single')]
        if starts and ends:
            doc["schema:temporalCoverage"] = [f"{starts[0]}/{ends[0]}"]
        else:
            doc["schema:temporalCoverage"] = [time_periods[0][1]]
    elif time_periods:
        doc["schema:temporalCoverage"] = [time_periods[0][1]]

    # --- Files / distributions ---
    distributions = []
    file_map = {}  # file ID -> distribution info
    for fd in iter_tag(root, 'fileDscr'):
        fid = fd.attrib.get('ID', '')
        uri = fd.attrib.get('URI', '')
        fname = ''
        ftype = ''
        for ft in fd:
            if strip_ns(ft.tag) == 'fileTxt':
                for sub in ft:
                    if strip_ns(sub.tag) == 'fileName':
                        fname = sub.text or ''
                    elif strip_ns(sub.tag) == 'fileType':
                        ftype = sub.text or ''
        dist = {
            "@type": ["schema:DataDownload"],
            "schema:name": fname,
        }
        if uri:
            dist["schema:contentUrl"] = uri
        if ftype:
            dist["schema:encodingFormat"] = [ftype]
        distributions.append(dist)
        file_map[fid] = fname

    if distributions:
        doc["schema:distribution"] = distributions

    # --- Variables (the key DataDescription content) ---
    variables = []
    for var in iter_tag(root, 'var'):
        name = var.attrib.get('name', '')
        vid = var.attrib.get('ID', '')
        intrvl = var.attrib.get('intrvl', '')

        labl = ''
        fmt_type = ''
        stats = {}
        file_id = ''

        for child in var:
            ctag = strip_ns(child.tag)
            if ctag == 'labl':
                labl = (child.text or '').strip()
            elif ctag == 'varFormat':
                fmt_type = child.attrib.get('type', '')
            elif ctag == 'sumStat':
                stype = child.attrib.get('type', '')
                if child.text and child.text.strip() != '.':
                    stats[stype] = child.text.strip()
            elif ctag == 'location':
                file_id = child.attrib.get('fileid', '')

        # Map DDI types to XSD types
        xsd_type_map = {
            'numeric': 'xsd:decimal',
            'character': 'xsd:string',
        }
        xsd_type = xsd_type_map.get(fmt_type, 'xsd:string')

        vm = {
            "@type": ["schema:PropertyValue", "cdi:InstanceVariable"],
            "@id": f"#{vid}" if vid else f"#{name}",
            "schema:name": name,
        }
        if labl:
            vm["schema:description"] = labl
        if xsd_type:
            vm["cdi:intendedDataType"] = xsd_type

        # Role: discrete → DimensionComponent or AttributeComponent, contin → MeasureComponent
        if intrvl == 'contin':
            vm["cdi:role"] = "MeasureComponent"
        elif intrvl == 'discrete':
            vm["cdi:role"] = "AttributeComponent"

        # Summary statistics as min/max
        if 'min' in stats:
            try:
                vm["schema:minValue"] = float(stats['min'])
            except ValueError:
                pass
        if 'max' in stats:
            try:
                vm["schema:maxValue"] = float(stats['max'])
            except ValueError:
                pass

        variables.append(vm)

    if variables:
        doc["schema:variableMeasured"] = variables

    # --- Measurement technique ---
    coll_modes = all_text(root, 'collMode')
    if coll_modes:
        doc["schema:measurementTechnique"] = coll_modes

    # --- subjectOf ---
    doc["schema:subjectOf"] = {
        "@type": ["schema:Dataset"],
        "schema:additionalType": ["dcat:CatalogRecord"],
        "@id": dataset_id + "#metadata" if dataset_id else "#metadata",
        "schema:name": f"Metadata record for: {doc['schema:name'][:120]}",
        "schema:about": {"@id": dataset_id},
        "dcterms:conformsTo": [
            {"@id": "https://w3id.org/cdif/core/1.0"},
            {"@id": "https://w3id.org/cdif/discovery/1.0"},
            {"@id": "https://w3id.org/cdif/data_description/1.0"},
        ],
        "schema:description": (
            f"Converted from DDI Codebook 2.5 to CDIF DataDescription profile by Claude Code. "
            f"Variable descriptions mapped from DDI <var> elements to schema:variableMeasured "
            f"with cdi:InstanceVariable extensions. DDI varFormat mapped to cdi:intendedDataType, "
            f"DDI intrvl mapped to cdi:role (contin->MeasureComponent, discrete->AttributeComponent). "
            f"Summary statistics (min/max) preserved."
        ),
    }

    return doc


if __name__ == "__main__":
    for xml_file, doi, outname in [
        ("C:/Users/smrTu/AppData/Local/Temp/ddi_harvest/cost-of-cash.xml",
         "https://doi.org/10.7910/DVN/CAKWNE", "ddi-cost-of-cash-datadesc.json"),
        ("C:/Users/smrTu/AppData/Local/Temp/ddi_harvest/expert-party-space.xml",
         "https://doi.org/10.7910/DVN/EZNWPA", "ddi-expert-party-space-datadesc.json"),
    ]:
        doc = convert_ddi_to_cdif(xml_file, dataset_doi=doi)
        outdir = "C:/Users/smrTu/OneDrive/Documents/GithubC/CDIF/datadescription/examples"
        outpath = os.path.join(outdir, outname)
        with open(outpath, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2, ensure_ascii=False)

        vm = doc.get("schema:variableMeasured", [])
        print(f"OK {outname}: {len(vm)} variables")
