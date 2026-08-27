#!/usr/bin/env python3
"""
ddi122_to_cdif.py - Convert DDI Codebook 1.2.2 (ICPSR) XML to CDIF JSON-LD.

Source-agnostic converter for DDI Codebook version 1.2.2 documents
(root <codeBook version="1.2.2">, schema
http://www.icpsr.umich.edu/DDI/Version1-2-2.xsd), such as Nesstar-published
survey metadata (DHS, MICS, PHIM, World Bank microdata catalogs).

Unlike DDI/ddi_to_cdif.py (which is hardwired to the Harvard Dataverse API and
its file-access URLs), this converter makes no repository assumptions: the
dataset identifier comes from <IDNo>, the access URL from <dataAccs><accsPlac>,
and file distributions carry the OGC nil "missing" value when the source has no
resolvable download URL (rather than fabricating one).

Profile scope is decided per content: the full study + variable + file structure
is mapped, then detect_conformance derives the declared dcterms:conformsTo from
what is actually present (typically core + discovery + data_description).

Mapping highlights (all element text is whitespace-trimmed):
  stdyDscr/citation/titlStmt/titl      -> schema:name          (NOT docDscr/titl)
  stdyDscr/.../IDNo                     -> schema:identifier    (+ @id fallback)
  stdyInfo/abstract                    -> schema:description
  citation/rspStmt/AuthEnty            -> schema:creator        (Person|Organization)
  prodStmt/producer | distStmt/distrbtr-> schema:publisher
  prodStmt/fundAg                      -> schema:funder
  method/dataColl/dataCollector        -> schema:contributor
  subject/keyword, subject/topcClas    -> schema:keywords
  sumDscr/nation, sumDscr/geogCover    -> schema:spatialCoverage
  sumDscr/collDate | sumDscr/timePrd   -> schema:temporalCoverage
  method/dataColl/collMode, sumDscr/dataKind -> schema:measurementTechnique
  dataAccs/setAvail/accsPlac[@URI]     -> schema:url
  dataAccs/useStmt/conditions|restrctn -> schema:conditionsOfAccess
  dataAccs/useStmt/citReq              -> dcterms:bibliographicCitation
  dataDscr/var                         -> schema:variableMeasured / cdi:InstanceVariable
  fileDscr                             -> schema:distribution / cdi:TabularTextDataSet
  docDscr (producer/prodDate/version)  -> schema:subjectOf catalog record

Known deferral: coded variables (<var><catgry>) carry an inline code list; these
are not yet emitted as a CDIF/DDI-CDI code list (that belongs with the codelist
profile). The variable is still mapped; its categories are counted in a note.

Usage:
    python ddi122_to_cdif.py input.xml [-o output.json] [--id IRI] [--base-uri BASE]
    python ddi122_to_cdif.py Examples/XML/MWI-PHIM-CAC-2026-v01.xml -o out.json
"""

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# detect_conformance (validation/ root) derives dcterms:conformsTo from the
# record's actual content. Best-effort: falls back to the built-in conformsTo
# when it (or its rdflib/pyshacl deps) is unavailable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
try:
    from detect_conformance import detect_conformance, apply_conformance
    _HAVE_DETECT = True
except Exception:
    _HAVE_DETECT = False

NIL_MISSING = "http://www.opengis.net/def/nil/OGC/0/missing"

# schema.org variable format -> XSD datatype.
XSD_TYPE_MAP = {"numeric": "xsd:decimal", "character": "xsd:string"}

# Tokens that mark an authoring/agent name as an organization rather than person.
ORG_HINTS = (
    "office", "ministry", "bureau", "institute", "institution", "organization",
    "organisation", "agency", "program", "programme", "commission", "department",
    "national", "statistical", "university", "council", "center", "centre",
    "division", "company", "corporation", "fund", "bank", "nations", "unicef",
    "usaid", "who", "unfpa", "government", "association", "society", "authority",
    "group", "services", "collaboration", "network", "consortium",
)


def strip_ns(tag):
    return tag.split("}")[-1] if "}" in tag else tag


def txt(elem):
    """Whitespace-collapsed text of an element (Nesstar output is indented)."""
    if elem is None or elem.text is None:
        return ""
    return " ".join(elem.text.split()).strip('"')


def find(scope, tag):
    """First descendant of `scope` with local name `tag` (None if absent)."""
    if scope is None:
        return None
    for e in scope.iter():
        if strip_ns(e.tag) == tag:
            return e
    return None


def find_all(scope, tag):
    if scope is None:
        return []
    return [e for e in scope.iter() if strip_ns(e.tag) == tag]


def first_text(scope, tag):
    return txt(find(scope, tag))


def all_texts(scope, tag):
    seen, out = set(), []
    for e in find_all(scope, tag):
        t = txt(e)
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def child(scope, tag):
    """First *direct child* with local name `tag`."""
    if scope is None:
        return None
    for e in list(scope):
        if strip_ns(e.tag) == tag:
            return e
    return None


def is_org(name):
    low = name.lower()
    return any(h in low for h in ORG_HINTS)


def agent_node(name, affiliation=None):
    node = {"@type": ["schema:Organization" if is_org(name) else "schema:Person"],
            "schema:name": name}
    if affiliation and affiliation.strip():
        node["schema:affiliation"] = {"@type": ["schema:Organization"],
                                      "schema:name": affiliation.strip()}
    return node


# ---------------------------------------------------------------------------
# Study-level extraction (scoped to stdyDscr)
# ---------------------------------------------------------------------------

def parse_creators(stdy):
    out = []
    for e in find_all(child(stdy, "citation"), "AuthEnty"):
        name = txt(e)
        if name:
            out.append(agent_node(name, e.attrib.get("affiliation")))
    return out


def parse_funders(stdy):
    out = []
    for e in find_all(stdy, "fundAg"):
        name = txt(e)
        if name:
            out.append({"@type": ["schema:Organization"], "schema:name": name})
    return out


def parse_contributors(stdy):
    out = []
    for e in find_all(stdy, "dataCollector"):
        name = txt(e)
        if name:
            out.append(agent_node(name, e.attrib.get("affiliation")))
    return out


def parse_publisher(stdy):
    # Prefer an explicit distributor; else the producer.
    for tag in ("distrbtr", "producer"):
        e = find(stdy, tag)
        if e is not None and txt(e):
            return {"@type": ["schema:Organization"], "schema:name": txt(e)}
    return None


def parse_spatial(stdy):
    out = []
    for e in find_all(stdy, "nation"):
        name = txt(e)
        if name:
            place = {"@type": ["schema:Place"], "schema:name": name}
            out.append(place)
    for e in find_all(stdy, "geogCover"):
        name = txt(e)
        if name:
            out.append({"@type": ["schema:Place"], "schema:name": name})
    return out


def _dates_by_event(elems):
    """Return (start, end) date strings from collDate/timePrd elements."""
    starts, ends, singles = [], [], []
    for e in elems:
        d = e.attrib.get("date") or txt(e)
        if not d:
            continue
        ev = e.attrib.get("event", "single")
        (starts if ev == "start" else ends if ev == "end" else singles).append(d)
    return starts, ends, singles


def parse_temporal(stdy):
    for tag in ("collDate", "timePrd"):
        elems = find_all(stdy, tag)
        if not elems:
            continue
        starts, ends, singles = _dates_by_event(elems)
        if starts and ends:
            return [f"{starts[0]}/{ends[0]}"]
        if singles:
            return singles[:1]
        picked = starts or ends
        if picked:
            return picked[:1]
    return None


def _date_of(elem):
    if elem is None:
        return None
    return elem.attrib.get("date") or (txt(elem) or None)


def resolve_dates(stdy, docd):
    """Return (date_modified, date_published) from the best available DDI dates.

    Publication date: prodDate, else distDate, else a dated <version>.
    Modified date: the publication date, else deposit date, else the
    data-collection end date (a reasonable proxy for content date).
    """
    prod = _date_of(find(stdy, "prodDate")) or _date_of(find(docd, "prodDate"))
    dist = _date_of(find(stdy, "distDate"))
    dep = _date_of(find(stdy, "depDate"))
    ver_date = next((v.attrib["date"] for v in find_all(stdy, "version")
                     if v.attrib.get("date")), None)
    _, ends, singles = _dates_by_event(find_all(stdy, "collDate"))
    coll_end = (ends or singles or [None])[0]

    published = prod or dist or ver_date
    modified = published or dep or coll_end
    # Truncate full datetimes (e.g. NADA's "2026-03-18T04:00:00.000Z") to a
    # plain date; the CDIF date pattern accepts YYYY-MM[-DD[Thh:mm[:ss]]] but
    # not fractional seconds.
    return _date_only(modified), _date_only(published)


def _date_only(value):
    return value.split("T", 1)[0] if value and "T" in value else value


def parse_measurement_technique(stdy):
    out = []
    for tag in ("collMode", "dataKind"):
        for t in all_texts(stdy, tag):
            if t not in out:
                out.append(t)
    return out


def parse_access(stdy):
    """Return (url, conditionsOfAccess list, bibliographicCitation)."""
    dataaccs = find(stdy, "dataAccs")
    url = None
    accsplac = find(dataaccs, "accsPlac")
    if accsplac is not None:
        uri = accsplac.attrib.get("URI")
        if uri and uri.strip():
            url = uri.strip()
    conditions = []
    for tag in ("conditions", "restrctn"):
        for t in all_texts(dataaccs, tag):
            conditions.append(t)
    cit = first_text(dataaccs, "citReq") or None
    return url, conditions, cit


# ---------------------------------------------------------------------------
# Variables and files
# ---------------------------------------------------------------------------

def parse_variables(root):
    out = []
    for var in find_all(root, "var"):
        name = var.attrib.get("name", "").strip().strip('"')
        vid = var.attrib.get("ID", "")
        intrvl = var.attrib.get("intrvl", "")
        fmt_elem = child(var, "varFormat")
        fmt = fmt_elem.attrib.get("type", "") if fmt_elem is not None else ""
        stats = {}
        for s in find_all(var, "sumStat"):
            val = txt(s)
            if val and val != ".":
                stats[s.attrib.get("type", "")] = val
        ncat = len(find_all(var, "catgry"))
        out.append({"name": name, "id": vid, "intrvl": intrvl, "format": fmt,
                    "label": first_text(var, "labl"), "stats": stats,
                    "ncat": ncat})
    return out


def build_variables(variables):
    out = []
    for v in variables:
        if not v["name"]:
            continue
        vm = {"@type": ["schema:PropertyValue", "cdi:InstanceVariable"],
              "@id": f"#{v['id'] or v['name']}", "schema:name": v["name"]}
        if v["label"]:
            vm["schema:description"] = v["label"]
        vm["cdi:intendedDataType"] = XSD_TYPE_MAP.get(v["format"], "xsd:string")
        if v["intrvl"] == "contin":
            vm["cdi:role"] = "MeasureComponent"
        elif v["intrvl"] == "discrete":
            vm["cdi:role"] = "AttributeComponent"
        for sk, jk in (("min", "schema:minValue"), ("max", "schema:maxValue")):
            if sk in v["stats"]:
                try:
                    vm[jk] = float(v["stats"][sk])
                except ValueError:
                    pass
        out.append(vm)
    return out


def parse_files(root):
    out = []
    for fd in find_all(root, "fileDscr"):
        name = first_text(fd, "fileName")
        dim = find(fd, "dimensns")
        rows = cols = None
        if dim is not None:
            try:
                rows = int(first_text(dim, "caseQnty"))
            except (ValueError, TypeError):
                pass
            try:
                cols = int(first_text(dim, "varQnty"))
            except (ValueError, TypeError):
                pass
        out.append({"id": fd.attrib.get("ID", ""), "name": name,
                    "rows": rows, "cols": cols,
                    "fileType": first_text(fd, "fileType")})
    return out


def build_distributions(files):
    """Map <fileDscr> to plain schema:DataDownload.

    The distributions are NOT typed cdi:TabularTextDataSet: DDI 1.2.2 gives no
    resolvable download URL and no column-to-variable physical mapping, so
    claiming the tabular data-structure profile (which then requires
    cdi:hasPhysicalMapping and cdi:isDelimited) would be over-claiming. Row and
    column counts are kept as descriptive additionalProperty values instead.
    """
    out = []
    for fi in files:
        dist = {"@type": ["schema:DataDownload"],
                "schema:name": fi["name"] or fi["id"] or "data file",
                "schema:contentUrl": NIL_MISSING}
        if fi["fileType"]:
            dist["schema:description"] = f"Source file type: {fi['fileType']}"
        props = []
        if fi["rows"] is not None:
            props.append({"@type": ["schema:PropertyValue"],
                          "schema:name": "row count", "schema:value": fi["rows"]})
        if fi["cols"] is not None:
            props.append({"@type": ["schema:PropertyValue"],
                          "schema:name": "column count", "schema:value": fi["cols"]})
        if props:
            dist["schema:additionalProperty"] = props
        out.append(dist)
    return out


# ---------------------------------------------------------------------------
# Document assembly
# ---------------------------------------------------------------------------

def convert(xml_path, explicit_id=None, base_uri="urn:ddi", detect=True,
            source_desc="DDI Codebook 1.2.2 (ICPSR)"):
    root = ET.parse(xml_path).getroot()
    stdy = find(root, "stdyDscr")
    docd = find(root, "docDscr")
    cite = child(stdy, "citation")
    cite = cite if cite is not None else stdy

    id_no = first_text(cite, "IDNo") \
        or first_text(root, "IDNo") or Path(xml_path).stem

    access_url, conditions, citation = parse_access(stdy)
    dataset_id = (explicit_id or access_url
                  or f"{base_uri}:{id_no}")

    doc = {"@context": {
        "schema": "http://schema.org/", "dcterms": "http://purl.org/dc/terms/",
        "dcat": "http://www.w3.org/ns/dcat#",
        "cdi": "http://ddialliance.org/Specification/DDI-CDI/1.0/RDF/",
    }, "@id": dataset_id, "@type": ["schema:Dataset"]}

    # Title / description — scoped to the STUDY description.
    doc["schema:name"] = first_text(cite, "titl") or id_no
    alt = first_text(cite, "altTitl")
    if alt:
        doc["schema:alternateName"] = alt
    abstract = first_text(stdy, "abstract")
    if abstract:
        doc["schema:description"] = abstract

    doc["schema:identifier"] = {"@type": ["schema:PropertyValue"],
                                "schema:value": id_no}
    if access_url:
        doc["schema:url"] = access_url

    # Dates: prefer a real production/dissemination date; fall back through
    # version date, distribution/deposit date, then the data-collection end.
    date_modified, date_published = resolve_dates(stdy, docd)
    doc["schema:dateModified"] = date_modified or "1900-01-01"
    if date_published:
        doc["schema:datePublished"] = date_published

    version = first_text(stdy, "version")
    if version:
        doc["schema:version"] = version

    keywords = all_texts(stdy, "keyword") + all_texts(stdy, "topcClas")
    if keywords:
        doc["schema:keywords"] = keywords

    creators = parse_creators(stdy)
    if creators:
        doc["schema:creator"] = {"@list": creators}
    publisher = parse_publisher(stdy)
    if publisher:
        doc["schema:publisher"] = publisher
    funders = parse_funders(stdy)
    if funders:
        doc["schema:funder"] = funders
    contributors = parse_contributors(stdy)
    if contributors:
        doc["schema:contributor"] = contributors

    spatial = parse_spatial(stdy)
    if spatial:
        doc["schema:spatialCoverage"] = spatial
    temporal = parse_temporal(stdy)
    if temporal:
        doc["schema:temporalCoverage"] = temporal
    technique = parse_measurement_technique(stdy)
    if technique:
        doc["schema:measurementTechnique"] = technique

    # Access rights: conditionsOfAccess when stated, else honest nil placeholder.
    if conditions:
        doc["schema:conditionsOfAccess"] = conditions
    else:
        doc["schema:license"] = [NIL_MISSING]
    if citation:
        doc["dcterms:bibliographicCitation"] = citation

    variables = parse_variables(root)
    coded_vars = sum(1 for v in variables if v["ncat"] > 0)
    cdif_vars = build_variables(variables)
    if cdif_vars:
        doc["schema:variableMeasured"] = cdif_vars

    distributions = build_distributions(parse_files(root))
    if distributions:
        doc["schema:distribution"] = distributions

    doc["schema:subjectOf"] = build_catalog_record(
        docd, dataset_id, doc["schema:name"], id_no, coded_vars,
        len(cdif_vars), len(distributions), source_desc)

    if detect and _HAVE_DETECT:
        try:
            uris = detect_conformance(doc)
            if uris:
                apply_conformance(doc, uris)
        except Exception:
            pass

    return doc


def build_catalog_record(docd, dataset_id, name, id_no, coded_vars,
                         nvars, ndists, source_desc="DDI Codebook 1.2.2 (ICPSR)"):
    sd_date = None
    if docd is not None:
        pd = find(docd, "prodDate")
        if pd is not None:
            sd_date = _date_only(pd.attrib.get("date") or txt(pd))
    doc_producer = first_text(docd, "producer") if docd is not None else None

    coded_note = (f" {coded_vars} variable(s) carry an inline DDI code list "
                  f"(<catgry>); these categories are not yet emitted as a CDIF "
                  f"code list.") if coded_vars else ""
    note = (
        f"Metadata harvested from a {source_desc} document "
        f"(IDNo {id_no}) and converted to CDIF by the CDIF DDI converter. Study "
        f"citation/title, abstract, agents, spatial/temporal coverage, and "
        f"access conditions mapped to discovery properties; {nvars} DDI <var> "
        f"mapped to schema:variableMeasured / cdi:InstanceVariable; {ndists} "
        f"<fileDscr> mapped to schema:distribution (schema:DataDownload; "
        f"contentUrl set to the OGC nil 'missing' value where the source "
        f"provides no resolvable download URL).{coded_note}"
    )
    rec = {
        "@type": ["schema:Dataset"],
        # IRI reference (not the bare string "dcat:CatalogRecord"): the current
        # CDIF discovery SHACL excludes catalog-record nodes from the dataset
        # mandatory shape by matching the dcat:CatalogRecord *IRI*.
        "schema:additionalType": [{"@id": "dcat:CatalogRecord"}],
        "@id": dataset_id + "#cdif-catalog-record",
        "schema:name": f"Metadata record for: {name[:120]}",
        "schema:about": {"@id": dataset_id},
        "schema:description": note,
        "dcterms:conformsTo": [
            {"@id": "https://w3id.org/cdif/core/1.1"},
            {"@id": "https://w3id.org/cdif/discovery/1.1"},
            {"@id": "https://w3id.org/cdif/data_description/1.1"}],
    }
    if sd_date:
        rec["schema:sdDatePublished"] = sd_date
    if doc_producer:
        rec["schema:maintainer"] = {"@type": ["schema:Organization"],
                                    "schema:name": doc_producer}
    return rec


def main():
    ap = argparse.ArgumentParser(
        description="Convert DDI Codebook 1.2.2 (ICPSR) XML to CDIF JSON-LD")
    ap.add_argument("input", help="Input DDI 1.2.2 XML file")
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
                  base_uri=args.base_uri, detect=not args.static_conformance)

    out = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
        nv = len(doc.get("schema:variableMeasured", []))
        nd = len(doc.get("schema:distribution", []))
        print(f"Written: {args.output} ({nv} vars, {nd} dists)")
    else:
        print(out)


if __name__ == "__main__":
    main()
