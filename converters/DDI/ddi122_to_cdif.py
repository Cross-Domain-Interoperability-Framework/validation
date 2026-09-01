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

Coded variables (<var><catgry>) are emitted as CDIF enumerated value domains:
the valid categories become a shared skos:ConceptScheme code list referenced
(cdif:references, by @id) from a cdif:EnumerationDomain under
cdi:takesSubstantiveValuesFrom, missing categories (missing="Y") become a
SentinelValueDomain under cdi:takesSentinelValuesFrom, and the
<sumStat>/<catStat> counts become a cdif:isDescribedBy_StatisticsCollection
(cdi:Statistics split by cdi:computationBase, plus per-category
cdi:CategoryStatistics whose cdi:for points at the shared code-list concept).
When any code list is emitted the document is a flattened @graph with the
dataset first and each distinct (deduplicated) code list as a sibling node.

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
        cats = []
        for c in find_all(var, "catgry"):
            freq = None
            for cs in find_all(c, "catStat"):
                # unlabelled catStat defaults to a frequency count
                if cs.attrib.get("type", "freq") in ("freq", ""):
                    fv = txt(cs)
                    if fv:
                        freq = fv
            cats.append({
                "value": first_text(c, "catValu"),
                "label": first_text(c, "labl"),
                "text": first_text(c, "txt"),
                "freq": freq,
                "missing": c.attrib.get("missing", "").upper() == "Y",
            })
        loc = child(var, "location")
        out.append({"name": name, "id": vid, "intrvl": intrvl, "format": fmt,
                    "label": first_text(var, "labl"), "stats": stats,
                    "cats": cats, "ncat": len(cats),
                    # physical-mapping context: which distribution file this column
                    # is in, and its field width. Document order (list order) is the
                    # column position.
                    "files": var.attrib.get("files", "").strip(),
                    "width": loc.attrib.get("width") if loc is not None else None})
    return out


def _var_signature(v):
    """Identity of the InstanceVariable a <var> instance realizes: name +
    label + datatype + interval + the enumerated category set. <var> instances
    that share this signature across files are the same InstanceVariable (a DHS
    identifier column like hhid recurs in ~40 files); they collapse to one node
    referenced by each file's physical mapping."""
    cats = tuple(sorted((c["value"] or "", c["label"] or "", c["text"] or "",
                         bool(c["missing"])) for c in v["cats"]))
    return (v["name"], v["label"] or "", v["format"], v["intrvl"], cats)


def dedup_variables(variables):
    """Collapse <var> instances with the same signature into one InstanceVariable.

    Returns (unique, sig_to_id): `unique` is the list of representative var dicts
    (each tagged with the assigned @id under key 'ivid'); `sig_to_id` maps a
    signature to that @id so physical mappings can point at the shared node.
    A name carrying more than one distinct definition (e.g. hhid) is
    disambiguated with a ~N suffix.
    """
    sig_to_id, name_seen, unique = {}, {}, []
    for v in variables:
        if not v["name"]:
            continue
        sig = _var_signature(v)
        if sig in sig_to_id:
            continue
        k = name_seen.get(v["name"], 0)
        name_seen[v["name"]] = k + 1
        ivid = f"#var/{v['name']}" if k == 0 else f"#var/{v['name']}~{k + 1}"
        sig_to_id[sig] = ivid
        rep = dict(v)
        rep["ivid"] = ivid
        unique.append(rep)
    return unique, sig_to_id


def _num(s):
    """DDI stat value string -> int if integral, float otherwise, None if not numeric."""
    try:
        f = float(s)
    except (TypeError, ValueError):
        return None
    return int(f) if f.is_integer() else f


# DDI sumStat @type -> CDIF single-value statistic kind. vald/invd are handled
# separately: they combine into one 'count' statistic split by computationBase.
_SUMSTAT_KIND = {"min": "minimum", "max": "maximum", "mean": "mean",
                 "stdev": "standardDeviation", "medn": "median", "mode": "mode"}


class CodeListRegistry:
    """Deduplicates <catgry> code lists into shared skos:ConceptScheme nodes.

    A code list is emitted once per distinct (kind, categories) signature and
    referenced by @id from every variable that uses it; the emitted nodes carry
    the discovery metadata the cdifCodelist profile requires (skos:prefLabel,
    schema:identifier, schema:dateModified, schema:license).
    """

    def __init__(self, license_val, date_modified):
        self._by_sig = {}   # signature -> (codelist_id, {notation: concept_id})
        self.nodes = []     # emitted skos:ConceptScheme nodes, in creation order
        self._license = license_val
        self._date = date_modified

    def get(self, cats, kind):
        """Return (codelist_id, {notation: concept_id}) for a category list.

        kind is 'subst' or 'sent' so substantive and sentinel lists with the
        same content never share a scheme. Returns (None, {}) for no usable
        categories.
        """
        usable = [c for c in cats if c["value"] is not None]
        if not usable:
            return None, {}
        sig = (kind, tuple(sorted((c["value"], c["label"] or "", c["text"] or "")
                                  for c in usable)))
        if sig in self._by_sig:
            return self._by_sig[sig]
        n = len(self.nodes) + 1
        clid = f"#codelist/{n}"
        concepts, idmap = [], {}
        for c in usable:
            cid = f"{clid}/{c['value']}"
            idmap[c["value"]] = cid
            node = {"@id": cid, "@type": ["skos:Concept", "cdi:Category"],
                    "skos:inScheme": [{"@id": clid}],
                    "skos:prefLabel": c["label"] or str(c["value"]),
                    "skos:notation": c["value"]}
            if c["text"]:
                node["skos:definition"] = c["text"]
            concepts.append(node)
        labels = [c["label"] for c in usable if c["label"]]
        scheme = {
            "@id": clid, "@type": ["skos:ConceptScheme"],
            "skos:prefLabel": ("; ".join(labels)[:120] if labels else f"code list {n}"),
            "schema:identifier": clid.lstrip("#"),
            "schema:dateModified": self._date,
            "schema:license": self._license,
            "skos:hasTopConcept": concepts,
        }
        self.nodes.append(scheme)
        self._by_sig[sig] = (clid, idmap)
        return clid, idmap


def _value_domains(base, cats, registry):
    """Inline substantive/sentinel value domains that reference a shared code list.

    Returns (properties, {notation: concept_id}) -- the concept-id map lets the
    statistics link each cdi:CategoryStatistics to the shared code-list concept.
    """
    props, idmap = {}, {}
    valid = [c for c in cats if not c["missing"]]
    missing = [c for c in cats if c["missing"]]
    clid, m = registry.get(valid, "subst")
    if clid:
        props["cdi:takesSubstantiveValuesFrom"] = {
            "@id": f"#{base}/valueDomain/substantive",
            "@type": ["cdif:SubstantiveValueDomain"],
            "cdif:takesValuesFrom": {
                "@id": f"#{base}/enumerationDomain",
                "@type": ["cdif:EnumerationDomain"],
                "cdif:references": {"@id": clid}}}
        idmap.update(m)
    sclid, sm = registry.get(missing, "sent")
    if sclid:
        props["cdi:takesSentinelValuesFrom"] = [{
            "@id": f"#{base}/valueDomain/sentinel",
            "@type": ["cdif:SentinelValueDomain"],
            "cdif:takesValuesFrom": {
                "@id": f"#{base}/sentinelEnumerationDomain",
                "@type": ["cdif:EnumerationDomain"],
                "cdif:references": {"@id": sclid}}}]
        idmap.update(sm)
    return props, idmap


def _statistics_collection(base, var_id, stats, cats, idmap):
    """cdif:isDescribedBy_StatisticsCollection from <sumStat> and <catStat>."""
    has = []
    vald, invd = _num(stats.get("vald")), _num(stats.get("invd"))
    if vald is not None or invd is not None:
        entries = []
        if vald is not None:
            entries.append({"cdi:computationBase": "ValidOnly", "cdi:content": vald,
                            "cdi:typeOfNumericValue": "decimal"})
        if invd is not None:
            entries.append({"cdi:computationBase": "MissingOnly", "cdi:content": invd,
                            "cdi:typeOfNumericValue": "decimal"})
        if vald is not None and invd is not None:
            entries.append({"cdi:computationBase": "Total", "cdi:content": vald + invd,
                            "cdi:typeOfNumericValue": "decimal"})
        has.append({"@id": f"#{base}/stats/count", "@type": ["cdi:Statistics"],
                    "cdi:typeOfStatistic": "count", "cdi:statistic": entries})
    for sk, kind in _SUMSTAT_KIND.items():
        val = _num(stats.get(sk))
        if val is not None:
            has.append({"@id": f"#{base}/stats/{kind}", "@type": ["cdi:Statistics"],
                        "cdi:typeOfStatistic": kind,
                        "cdi:statistic": [{"cdi:computationBase": "ValidOnly",
                                           "cdi:content": val,
                                           "cdi:typeOfNumericValue": "decimal"}]})
    cat_entries = []
    for c in cats:
        f = _num(c["freq"])
        if f is None or c["value"] is None:
            continue
        concept_id = idmap.get(c["value"], f"#{base}/code/{c['value']}")
        cat_entries.append({
            "@type": ["cdi:CategoryStatistics"],
            "cdi:for": {"@id": concept_id},
            "cdi:typeOfStatistic": "frequency",
            "cdi:statistic": [{
                "cdi:computationBase": "MissingOnly" if c["missing"] else "ValidOnly",
                "cdi:content": f, "cdi:typeOfNumericValue": "decimal"}],
        })
    if cat_entries:
        total = sum(e["cdi:statistic"][0]["cdi:content"] for e in cat_entries)
        has.append({"@id": f"#{base}/stats/frequencies", "@type": ["cdi:Statistics"],
                    "cdi:typeOfStatistic": "frequency",
                    "cdi:statistic": [{"cdi:computationBase": "Total",
                                       "cdi:content": total,
                                       "cdi:typeOfNumericValue": "decimal"}],
                    "cdif:has_CategoryStatistics": cat_entries})
    if not has:
        return None
    return {"@id": f"#{base}/statistics", "@type": ["cdi:StatisticsCollection"],
            "cdif:indexedBy": [{"@id": var_id}], "cdif:has_Statistics": has}


def build_variables(unique, registry):
    """Build one InstanceVariable per deduplicated variable (see dedup_variables).
    `unique` items carry their assigned @id under 'ivid'."""
    out = []
    for v in unique:
        if not v["name"]:
            continue
        var_id = v["ivid"]
        base = var_id.lstrip("#")   # e.g. "var/hhid" -> child @ids "#var/hhid/..."
        vm = {"@type": ["schema:PropertyValue", "cdi:InstanceVariable"],
              "@id": var_id, "schema:name": v["name"]}
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
        # Enumerated value domain(s) referencing a shared code list, and the
        # per-variable statistics from <sumStat> / <catStat>.
        vdoms, idmap = _value_domains(base, v["cats"], registry)
        vm.update(vdoms)
        coll = _statistics_collection(base, var_id, v["stats"], v["cats"], idmap)
        if coll is not None:
            vm["cdif:isDescribedBy_StatisticsCollection"] = coll
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


def build_distributions(files, variables, sig_to_id):
    """Map each <fileDscr> to a delimited tabular schema:DataDownload whose
    cdif:hasPhysicalMapping lists its columns.

    DDI scopes each <var> to one file via the `files` attribute, and the vars
    appear in column order; <location> carries only a field width (no byte
    offsets), so the layout is treated as delimited rather than fixed-width.
    DDI states no explicit column->variable link, so each column's
    cdif:formats_InstanceVariable is recovered from the var's identity: it
    points at the deduplicated InstanceVariable (sig_to_id) the column realizes.
    """
    by_file = {}
    for v in variables:
        if v["name"]:
            by_file.setdefault(v["files"], []).append(v)  # preserves column order
    out = []
    for fi in files:
        cols = by_file.get(fi["id"], [])
        dtype = ["schema:DataDownload"] + (["cdi:TabularTextDataSet"] if cols else [])
        dist = {"@type": dtype,
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
        if cols:
            # assume delimited (no fixed-width offsets are present in DDI)
            dist["cdi:isDelimited"] = True
            mappings = []
            for idx, v in enumerate(cols):
                m = {"@type": ["cdif:PhysicalMapping"], "cdif:index": idx,
                     "cdif:physicalDataType": XSD_TYPE_MAP.get(v["format"], "xsd:string")}
                ivid = sig_to_id.get(_var_signature(v))
                if ivid:
                    m["cdif:formats_InstanceVariable"] = {"@id": ivid}
                mappings.append(m)
            dist["cdif:hasPhysicalMapping"] = mappings
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
        "cdif": "https://w3id.org/cdif/",
        "skos": "http://www.w3.org/2004/02/skos/core#",
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
    # Collapse <var> instances that realize the same InstanceVariable (same
    # name+datatype+enumeration) across files into one node; each file's column
    # points back at it via a physical mapping.
    unique_vars, sig_to_id = dedup_variables(variables)
    coded_vars = sum(1 for v in unique_vars if v["ncat"] > 0)
    # Shared, deduplicated <catgry> code lists become sibling @graph nodes;
    # they inherit the dataset's license and modification date.
    registry = CodeListRegistry(doc.get("schema:license") or [NIL_MISSING],
                                doc.get("schema:dateModified") or "1900-01-01")
    cdif_vars = build_variables(unique_vars, registry)
    if cdif_vars:
        doc["schema:variableMeasured"] = cdif_vars

    distributions = build_distributions(parse_files(root), variables, sig_to_id)
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

    # When coded variables produced shared code lists, emit a flattened @graph
    # with the dataset first and each distinct code list as a sibling node.
    if registry.nodes:
        context = doc.pop("@context")
        return {"@context": context, "@graph": [doc] + registry.nodes}
    return doc


def build_catalog_record(docd, dataset_id, name, id_no, coded_vars,
                         nvars, ndists, source_desc="DDI Codebook 1.2.2 (ICPSR)"):
    sd_date = None
    if docd is not None:
        pd = find(docd, "prodDate")
        if pd is not None:
            sd_date = _date_only(pd.attrib.get("date") or txt(pd))
    doc_producer = first_text(docd, "producer") if docd is not None else None

    coded_note = (f" {coded_vars} variable(s) carry a DDI code list "
                  f"(<catgry>), emitted as CDIF enumerated value domains "
                  f"(cdi:takesSubstantiveValuesFrom -> cdif:EnumerationDomain -> "
                  f"cdif:references a shared skos:ConceptScheme code list; "
                  f"missing categories -> cdi:takesSentinelValuesFrom) with "
                  f"category and summary statistics "
                  f"(cdif:isDescribedBy_StatisticsCollection). Distinct code "
                  f"lists are deduplicated into sibling @graph nodes.") \
        if coded_vars else ""
    note = (
        f"Metadata harvested from a {source_desc} document "
        f"(IDNo {id_no}) and converted to CDIF by the CDIF DDI converter. Study "
        f"citation/title, abstract, agents, spatial/temporal coverage, and "
        f"access conditions mapped to discovery properties; DDI <var> elements "
        f"deduplicated (by name + datatype + enumeration) to {nvars} "
        f"schema:variableMeasured / cdi:InstanceVariable node(s); {ndists} "
        f"<fileDscr> mapped to schema:distribution (schema:DataDownload, treated "
        f"as delimited cdi:TabularTextDataSet; contentUrl set to the OGC nil "
        f"'missing' value where the source provides no resolvable download URL) "
        f"with cdif:hasPhysicalMapping columns whose cdif:formats_InstanceVariable "
        f"links each column (by the DDI `files` attribute + var identity) to its "
        f"shared InstanceVariable.{coded_note}"
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
        # With coded variables the document is a {@graph:[dataset, ...codelists]}
        # wrapper; count from the dataset node in that case.
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
