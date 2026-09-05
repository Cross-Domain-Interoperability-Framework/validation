#!/usr/bin/env python3
"""
ConvertFromCroissant.py - Convert Croissant JSON-LD metadata to CDIF DataDescription.

Reads a Croissant (mlcommons.org/croissant 1.1 or 1.0) JSON-LD document and
produces a CDIF DataDescription JSON-LD document in the current cdif: schema.
Handles the lossless subset:
  - Discovery-level metadata (name, description, creators, license, ...)
  - Distribution / FileObject inventory (flat + archive with containedIn)
  - Tabular RecordSet / Field -> cdi:InstanceVariable + cdif:hasPhysicalMapping
  - RecordSet key -> cdif:hasPrimaryKey

See CroissantToCDIF.md for the full mapping and limitations.

Mapping summary (current CDIF cdif: schema):
  Croissant cr:FileObject              -> CDIF schema:DataDownload
  Croissant cr:FileObject (containedIn)-> CDIF schema:hasPart item of archive DataDownload
  Croissant cr:RecordSet               -> attaches cdif:hasPhysicalMapping to the source file
  Croissant cr:Field                   -> CDIF schema:variableMeasured InstanceVariable
  Croissant cr:Field.dataType          -> cdif:physicalDataType (+ cdi:hasIntendedDataType)
  Croissant equivalentProperty         -> CDIF schema:propertyID
  Croissant cr:RecordSet.key           -> CDIF cdif:hasPrimaryKey (cdif:Key/cdif:isComposedOf)
  Croissant citeAs (DOI)               -> CDIF schema:identifier PropertyValue

Usage:
    python ConvertFromCroissant.py input-croissant.json [-o output.jsonld] [-v]
"""

import datetime as _date
import json
import os
import sys
import argparse
import re
from copy import deepcopy
from pathlib import Path

# detect_conformance lives in the parent validation/ dir. It derives the
# dcterms:conformsTo set from the record's actual content (presence ASK +
# per-class content SHACL) instead of a hardcoded profile list, so the record
# claims exactly the profiles it satisfies (and auto-detects data_description /
# manifest / etc. per record).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
try:
    from detect_conformance import detect_conformance, apply_conformance
    HAS_DETECT = True
except Exception:
    HAS_DETECT = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CDIF_CONTEXT = {
    "schema": "http://schema.org/",
    "dcterms": "http://purl.org/dc/terms/",
    "dcat": "http://www.w3.org/ns/dcat#",
    "spdx": "http://spdx.org/rdf/terms#",
    "cdi": "http://ddialliance.org/Specification/DDI-CDI/1.0/RDF/",
    "cdif": "https://w3id.org/cdif/",
    "csvw": "http://www.w3.org/ns/csvw#",
    "prov": "http://www.w3.org/ns/prov#",
    "dqv": "http://www.w3.org/ns/dqv#",
}

# Current CDIF conformance URIs (subjectOf.dcterms:conformsTo). core + discovery
# are always implied by the discovery foundation; data_description is declared
# ONLY when the record actually describes variables (a Croissant RecordSet with
# fields). A record with no variableMeasured does not conform to — and must not
# claim — the data_description profile.
CDIF_CORE_DISCOVERY_CONFORMS_TO = [
    "https://w3id.org/cdif/core/1.1",
    "https://w3id.org/cdif/discovery/1.1",
]
CDIF_DATA_DESCRIPTION_CONFORMS_TO = "https://w3id.org/cdif/data_description/1.1"

# Accept either Croissant version on input; the converter is version-agnostic
# for the lossless subset it handles.
CROISSANT_SOURCE_URIS = (
    "http://mlcommons.org/croissant/1.1",
    "http://mlcommons.org/croissant/1.0",
)
CROISSANT_SOURCE_URI = CROISSANT_SOURCE_URIS[0]  # default/preferred (1.1)

# Inverse of ConvertToCroissant.py DATATYPE_MAP
DATATYPE_INVERSE = {
    "sc:Float": "xsd:decimal",
    "sc:Integer": "xsd:integer",
    "sc:Date": "xsd:dateTime",
    "sc:Boolean": "xsd:boolean",
    "sc:Text": "xsd:string",
    "sc:URL": "xsd:anyURI",
}

# xsd token -> XMLSchema datatype IRI (for cdi:hasIntendedDataType)
_XSD_IRI = {
    "xsd:decimal": "https://www.w3.org/TR/xmlschema-2/#decimal",
    "xsd:integer": "https://www.w3.org/TR/xmlschema-2/#integer",
    "xsd:dateTime": "https://www.w3.org/TR/xmlschema-2/#dateTime",
    "xsd:boolean": "https://www.w3.org/TR/xmlschema-2/#boolean",
    "xsd:string": "https://www.w3.org/TR/xmlschema-2/#string",
    "xsd:anyURI": "https://www.w3.org/TR/xmlschema-2/#anyURI",
}

# Canonical case is OGC, not ogc -- IRIs are case sensitive, and the
# lowercase form these once used named nothing at all.
OGC_NIL_INAPPLICABLE = "http://www.opengis.net/def/nil/OGC/0/inapplicable"
OGC_NIL_MISSING = "http://www.opengis.net/def/nil/OGC/0/missing"
NIL_SHA256_PLACEHOLDER = "0" * 64
# cdifd:nameProperty: schema:name on an agent needs at least 3 characters.
AGENT_NAME_MIN_LENGTH = 3
CROISSANT_VERSION_PLACEHOLDER = "not assigned"

DOI_PATTERN = re.compile(r"\b(10\.\d{4,9}/[-._;()/:A-Z0-9]+)\b", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Helpers (style matches ConvertToCroissant.py)
# ---------------------------------------------------------------------------

def _get(obj, *keys, default=None):
    """Return the first matching key's value from *obj*."""
    if not isinstance(obj, dict):
        return default
    for k in keys:
        if k in obj:
            return obj[k]
    return default


def _as_list(val):
    if val is None:
        return []
    return val if isinstance(val, list) else [val]


def _sanitize_id(name):
    return re.sub(r"[^a-zA-Z0-9._-]", "_", str(name))


def _slug_var_id(name):
    """Sluggify a field name into a #fragment id, matching CDIF style."""
    return "#" + re.sub(r"[^a-z0-9]", "", name.lower())


# ---------------------------------------------------------------------------
# Dataset-level (discovery) field extraction
# ---------------------------------------------------------------------------

def _extract_doi(croissant):
    """Find a DOI in citeAs / url / @id. Returns (value, url) or (None, None)."""
    for key in ("citeAs", "url", "@id"):
        v = croissant.get(key)
        if isinstance(v, str):
            m = DOI_PATTERN.search(v)
            if m:
                doi_value = m.group(1)
                return doi_value, f"https://doi.org/{doi_value}"
    return None, None


def _property_id(value):
    """schema:propertyID as an IRI reference when the value names one.

    A URI or CURIE serialized as a string literal never becomes an IRI in the
    uplifted RDF, so the identifier scheme a consumer would resolve is lost.
    Free-label schemes stay strings, which the CDIF shapes allow.
    """
    if not isinstance(value, str):
        return value
    v = value.strip()
    if v.startswith(("http://", "https://", "urn:")):
        return {"@id": v}
    # A CURIE: a known-prefix token with no spaces, e.g. "schema:identifier".
    if ":" in v and " " not in v and not v.endswith(":"):
        prefix = v.split(":", 1)[0]
        if prefix and prefix.isalnum():
            return {"@id": v}
    return v


def _convert_identifier(croissant):
    """Build CDIF schema:identifier PropertyValue from Croissant citeAs/url."""
    doi_value, doi_url = _extract_doi(croissant)
    if doi_value:
        return {
            "@type": ["schema:PropertyValue"],
            "schema:propertyID": _property_id(
                "https://registry.identifiers.org/registry/doi"),
            "schema:value": doi_value,
            "schema:url": doi_url,
        }
    return None


# ---------------------------------------------------------------------------
# The mapping table
# ---------------------------------------------------------------------------
#
# converters/mappings/croissant-to-cdif.sssom.tsv decides which Croissant
# property becomes which CDIF property; this module reads it rather than
# restating it, so the table and the behaviour cannot drift apart. The generic
# machinery is in converters/sssom_engine.py.
#
# Croissant writes bare terms (`name`, `recordSet`) resolved by its @context,
# while the table keys on the IRIs those expand to (sc:name, cr:recordSet), so
# a key has to be resolved through the context before it can be looked up.

_CONVERTERS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _CONVERTERS_DIR)
import sssom_engine as _engine  # noqa: E402

_MAPPINGS = os.path.join(_CONVERTERS_DIR, "mappings")

# The Croissant context, as the specification defines it. A record carries its
# own copy, which is used when present; this is the fallback for one that does
# not, and the authority for which bare terms are Croissant's own.
CROISSANT_TERMS = {
    "citeAs": "cr:citeAs", "column": "cr:column", "data": "cr:data",
    "dataType": "cr:dataType", "examples": "cr:examples",
    "extract": "cr:extract", "field": "cr:field", "fileObject": "cr:fileObject",
    "fileProperty": "cr:fileProperty", "fileSet": "cr:fileSet",
    "format": "cr:format", "includes": "cr:includes",
    "isLiveDataset": "cr:isLiveDataset", "jsonPath": "cr:jsonPath",
    "key": "cr:key", "md5": "cr:md5", "parentField": "cr:parentField",
    "path": "cr:path", "recordSet": "cr:recordSet",
    "references": "cr:references", "regex": "cr:regex",
    "repeated": "cr:repeated", "replace": "cr:replace",
    "separator": "cr:separator", "source": "cr:source",
    "subField": "cr:subField", "transform": "cr:transform",
    "conformsTo": "dct:conformsTo",
}


def croissant_curie(key, context=None):
    """A document key as the mapping table spells it.

    A bare term is Croissant's own when the context (or the specification)
    says so, and otherwise falls to the context's @vocab, which Croissant sets
    to https://schema.org/ -- hence the sc: prefix the table keys on.
    """
    if ":" in key or key.startswith("@"):
        return key
    if isinstance(context, dict):
        bound = context.get(key)
        if isinstance(bound, dict):
            bound = bound.get("@id")
        if isinstance(bound, str) and ":" in bound:
            return bound
    if key in CROISSANT_TERMS:
        return CROISSANT_TERMS[key]
    return "sc:" + key


# --- the table's named transforms -----------------------------------------
#
# Each takes (value, source, rule, target) and returns the CDIF value, or None
# to emit nothing. Most delegate to the shapers that were already here.

def _t_text(value, src, rule, out):
    return value if value not in (None, "", []) else None


def _t_iri(value, src, rule, out):
    if isinstance(value, dict):
        return value.get("@id") or value.get("url") or None
    return value or None


def _t_idref(value, src, rule, out):
    got = _t_iri(value, src, rule, out)
    return {"@id": got} if isinstance(got, str) else (value or None)


def _t_date(value, src, rule, out):
    return _normalize_date(value) or value or None


def _t_list(value, src, rule, out):
    return _convert_keywords(src) or None


def _t_langcode(value, src, rule, out):
    got = _t_iri(value, src, rule, out)
    if not isinstance(got, str):
        return None
    tail = got.rstrip("/").rsplit("/", 1)[-1].rsplit("#", 1)[-1]
    return tail or got


def _t_identifier(value, src, rule, out):
    return _convert_identifier(src) or None


def _t_agent(value, src, rule, out):
    if rule["object_id"] == "schema:creator":
        # _convert_creators already returns CDIF's ordered form; hand back the
        # members so the arity rule does the wrapping exactly once.
        got = _convert_creators(src)
        return (got or {}).get("@list") or None
    if rule["object_id"] == "schema:publisher":
        return _convert_publisher(src) or None
    got = [_convert_agent(a) for a in _as_list(value)]
    return [a for a in got if a] or None


def _t_derived(value, src, rule, out):
    """Source datasets a record was derived from, as CDIF nodes.

    Croissant-from-CDIF records carry prov:wasDerivedFrom already, written in
    Croissant's own spelling (@type "CreativeWork", bare name/description).
    Passing that through verbatim leaves untyped nodes CDIF rejects, so it goes
    through the same shaper as sc:isBasedOn.
    """
    return _convert_is_based_on(src) or None


def _t_license(value, src, rule, out):
    """CDIF wants {"@id": ...} references, which _convert_license builds."""
    return _convert_license(src) or None


def _t_funding(value, src, rule, out):
    return _convert_funding(src) or None


def _t_accessflag(value, src, rule, out):
    """Croissant's isAccessibleForFree is a boolean; CDIF wants a statement."""
    if value is True:
        return ["unrestricted"]
    if value is False:
        return ["restricted"]
    return None


def _t_catalog(value, src, rule, out):
    """A data catalog belongs on the CDIF catalog record, not the dataset."""
    for item in _as_list(value):
        if isinstance(item, dict):
            name = item.get("name") or item.get("schema:name")
            url = item.get("url") or item.get("@id")
            node = {"@type": ["schema:DataCatalog"]}
            if name:
                node["schema:name"] = name
            if url:
                node["schema:url"] = url
            if len(node) > 1:
                return node
        elif isinstance(item, str):
            return {"@type": ["schema:DataCatalog"], "schema:name": item}
    return None


def _t_period(value, src, rule, out):
    text = value if isinstance(value, str) else None
    return text or None


def _t_passthrough(value, src, rule, out):
    return None      # handled by the passthrough pass, not by placement


def _convert_agent(agent):
    """Croissant Person/Organization -> CDIF agent (with schema: prefix)."""
    if not isinstance(agent, dict):
        return None
    out = {}
    raw_type = agent.get("@type")
    if raw_type:
        types = _as_list(raw_type)
        prefixed = []
        for t in types:
            if isinstance(t, str) and not t.startswith("schema:") and not t.startswith("http"):
                prefixed.append(f"schema:{t}")
            else:
                prefixed.append(t)
        out["@type"] = prefixed if len(prefixed) > 1 else prefixed[0]

    if agent.get("@id"):
        out["@id"] = agent["@id"]
    name = agent.get("name")
    if name:
        # The CDIF agent shapes require schema:name to be at least 3 characters
        # (cdifd:nameProperty, sh:minLength 3), and sources carry abbreviations
        # like "WB" that fall under it. Pad rather than drop: the abbreviation is
        # the only label the source gives, so losing it would be worse than
        # carrying it in a padded form.
        if isinstance(name, str) and 0 < len(name.strip()) < AGENT_NAME_MIN_LENGTH:
            name = name.strip().ljust(AGENT_NAME_MIN_LENGTH, "_")
        out["schema:name"] = name
    if "email" in agent:
        out["schema:email"] = agent["email"]
    if "affiliation" in agent:
        aff = _convert_agent(agent["affiliation"])
        if aff:
            out["schema:affiliation"] = aff
    # Preserve ORCID-like identifier
    ident = agent.get("identifier") or agent.get("@id")
    if isinstance(ident, str) and ident.startswith("http"):
        out.setdefault("schema:identifier", ident)
    return out if out.get("schema:name") else None


def _convert_creators(croissant):
    """Convert Croissant creator[] to CDIF schema:creator wrapped in @list."""
    raw = croissant.get("creator")
    if not raw:
        return None
    agents = [_convert_agent(a) for a in _as_list(raw)]
    agents = [a for a in agents if a]
    if not agents:
        return None
    return {"@list": agents}


def _convert_publisher(croissant):
    return _convert_agent(croissant.get("publisher"))


def _convert_funding(croissant):
    """Croissant funding[] -> CDIF schema:funding[]."""
    out = []
    for f in _as_list(croissant.get("funding")):
        if not isinstance(f, dict):
            continue
        item = {"@type": ["schema:MonetaryGrant"]}
        for src, dst in (("name", "schema:name"),
                         ("description", "schema:description"),
                         ("identifier", "schema:identifier")):
            if f.get(src):
                item[dst] = f[src]
        funder = f.get("funder")
        if funder:
            agent = _convert_agent(funder)
            if agent:
                item["schema:funder"] = agent
        out.append(item)
    return out or None


# The CDIF shapes accept YYYY-MM through YYYY-MM-DDThh:mm:ss with an optional
# Z/offset -- and no fractional seconds. Sources routinely carry them.
_CDIF_DATE_RE = re.compile(
    r"^[1-2][0-9]{3}-([0][1-9]|[1][0-2])"
    r"(-([0-2][0-9]|[3][0-1])"
    r"(T([0-1][0-9]|[2][0-3])(:[0-5][0-9])?"
    r"(:[0-5][0-9](Z|[+-][0-2][0-9]:[0-5][0-9])?)?)?)?$")


def _normalize_date(value):
    """Coerce a date/datetime string into the form the CDIF shapes accept.

    Drops fractional seconds first, since that is the usual offender, and falls
    back to the plain date then the year-month rather than emitting something
    that will fail validation. Returns None if nothing usable can be salvaged.
    """
    if not isinstance(value, str):
        return value
    v = value.strip()
    if _CDIF_DATE_RE.match(v):
        return v
    # "2017-11-27T17:08:04.7" -> "2017-11-27T17:08:04"
    trimmed = re.sub(r"\.\d+", "", v)
    if _CDIF_DATE_RE.match(trimmed):
        return trimmed
    for length in (10, 7):
        if _CDIF_DATE_RE.match(v[:length]):
            return v[:length]
    return None


def _convert_license(croissant):
    """Pass through the license, or state that it is missing.

    CDIF requires licence / access-conditions information for FAIR reuse, and a
    silent omission is indistinguishable from an oversight. When the source has
    none, emit the OGC nil:missing URI, which says the value is knowably absent.
    """
    lic = croissant.get("license")
    if not lic or lic == OGC_NIL_MISSING:
        return [{"@id": OGC_NIL_MISSING}]
    out = []
    for entry in (lic if isinstance(lic, list) else [lic]):
        if isinstance(entry, str):
            out.append({"@id": entry} if entry.startswith(("http://", "https://"))
                       else entry)
        elif isinstance(entry, dict):
            # Croissant states a licence as a CreativeWork with its own
            # unprefixed keys. Prefer its url -- an IRI a consumer can resolve
            # -- and fall back to the name as a label.
            url = entry.get("url") or entry.get("schema:url")
            name = entry.get("name") or entry.get("schema:name")
            if url:
                out.append({"@id": url})
            elif name:
                out.append(name)
    return out or [{"@id": OGC_NIL_MISSING}]


def _convert_keywords(croissant):
    kw = croissant.get("keywords")
    if not kw:
        return None
    return _as_list(kw)


# ---------------------------------------------------------------------------
# Distribution conversion (FileObjects -> DataDownload / archive hasPart)
# ---------------------------------------------------------------------------

def _parse_content_size(size_str):
    """Croissant contentSize 'NNN B' -> CDIF QuantitativeValue."""
    if not size_str:
        return None
    m = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([A-Za-z]+)?\s*$", str(size_str))
    if not m:
        return None
    value = float(m.group(1))
    if value.is_integer():
        value = int(value)
    unit = (m.group(2) or "B").strip()
    unit_text = {"B": "byte", "kB": "kilobyte", "KB": "kilobyte",
                 "MB": "megabyte", "GB": "gigabyte"}.get(unit, "byte")
    return {
        "@type": ["schema:QuantitativeValue"],
        "schema:value": value,
        "schema:unitText": unit_text,
    }


def _convert_checksum(fobj):
    """Croissant sha256/md5 -> CDIF spdx:checksum dict, drop nil placeholder."""
    sha = fobj.get("sha256")
    if sha and sha != NIL_SHA256_PLACEHOLDER:
        return {
            "@type": ["spdx:Checksum"],
            "spdx:checksumAlgorithm": "checksumAlgorithm_sha256",
            "spdx:checksumValue": sha,
        }
    md5 = fobj.get("md5")
    if md5:
        return {
            "@type": ["spdx:Checksum"],
            "spdx:checksumAlgorithm": "checksumAlgorithm_md5",
            "spdx:checksumValue": md5,
        }
    return None


def _file_object_basic(fobj, is_archive_component=False):
    """Copy the common DataDownload/MediaObject fields from a cr:FileObject."""
    out = {}
    if fobj.get("@id"):
        out["@id"] = fobj["@id"]

    name = fobj.get("name")
    if name:
        out["schema:name"] = name

    desc = fobj.get("description")
    if desc:
        out["schema:description"] = desc

    enc = fobj.get("encodingFormat")
    if enc:
        out["schema:encodingFormat"] = [enc] if isinstance(enc, str) else enc

    content_url = fobj.get("contentUrl")
    if content_url and content_url != OGC_NIL_INAPPLICABLE:
        out["schema:contentUrl"] = content_url
    elif not is_archive_component:
        # Top-level FileObject without a usable URL: keep placeholder
        if content_url == OGC_NIL_INAPPLICABLE:
            out["schema:contentUrl"] = content_url

    size = _parse_content_size(fobj.get("contentSize"))
    if size:
        out["schema:size"] = size

    cksum = _convert_checksum(fobj)
    if cksum:
        out["spdx:checksum"] = cksum

    # A DataDownload is a MediaObject, so these carry unchanged. They were
    # being dropped: a file's language, its own modification date, and who
    # made it are not the dataset's, and there is nowhere else for them to go.
    lang = fobj.get("inLanguage")
    if lang:
        out["schema:inLanguage"] = lang

    modified = fobj.get("dateModified")
    if modified:
        out["schema:dateModified"] = modified

    creator = fobj.get("creator")
    if creator:
        agents = [_convert_agent(a) or a for a in _as_list(creator)
                  if isinstance(a, (dict, str))]
        # A bare {"@id": ...} survives as a reference rather than being
        # discarded for having no name -- the node it points at is usually
        # described elsewhere in the graph.
        agents = [a for a in agents if a]
        if agents:
            out["schema:creator"] = agents

    return out


def _mark_tabular(node, fobj):
    """A cdi:TabularTextDataSet must declare a physical layout (cdi:isDelimited
    OR cdi:isFixedWidth). Croissant tabular sources are delimited text, so set
    cdi:isDelimited and a csvw:delimiter inferred from encodingFormat (tab for
    TSV, comma otherwise)."""
    if "cdi:TabularTextDataSet" not in (node.get("@type") or []):
        return node
    node.setdefault("cdi:isDelimited", True)
    enc = " ".join(_as_list(fobj.get("encodingFormat") or [])).lower()
    node.setdefault("csvw:delimiter", "\t" if ("tsv" in enc or "tab" in enc) else ",")
    return node


def _convert_distribution(croissant, record_sets_by_file, verbose=False):
    """Convert cr:FileObject inventory into CDIF schema:distribution[].

    Pivots Croissant's flat-with-containedIn pattern into CDIF's
    archive-hasPart pattern.

    Returns the CDIF distribution list. Also returns a mapping
    ``file_id -> distribution_part_ref`` so RecordSet→hasPhysicalMapping can
    attach to the right CDIF node.
    """
    raw = _as_list(croissant.get("distribution", []))
    file_objs = [d for d in raw if isinstance(d, dict)
                 and "FileObject" in str(d.get("@type", ""))]

    # cr:FileSet entries (a glob of files, e.g. Hugging Face parquet shards)
    # become CDIF schema:DataDownload nodes too (handled below), so RecordSet
    # fields whose source is a fileSet still anchor their cdif:hasPhysicalMapping.
    file_sets = [d for d in raw if isinstance(d, dict)
                 and "FileSet" in str(d.get("@type", ""))]
    fo_by_id = {d.get("@id"): d for d in file_objs}
    # A FileObject that exists only as a FileSet's containedIn host (e.g. the HF
    # "repo" tree) need not be emitted as its own distribution; its contentUrl
    # is inherited by the FileSet DataDownload instead.
    fileset_parent_ids = set()
    for fs in file_sets:
        ci = fs.get("containedIn")
        pid = ci.get("@id") if isinstance(ci, dict) else (ci if isinstance(ci, str) else None)
        if pid:
            fileset_parent_ids.add(pid)

    # Group by containedIn parent id (or None for stand-alone files)
    parents = {}  # parent_id -> parent FileObject dict
    children_of = {}  # parent_id -> list of FileObject children
    standalone = []  # FileObjects without a containedIn

    for fo in file_objs:
        contained_in = fo.get("containedIn")
        parent_id = None
        if isinstance(contained_in, dict):
            parent_id = contained_in.get("@id")
        elif isinstance(contained_in, str):
            parent_id = contained_in

        if parent_id:
            children_of.setdefault(parent_id, []).append(fo)
        else:
            # candidate parent OR true standalone
            standalone.append(fo)

    # parents are standalone FileObjects whose @id appears as a containedIn target
    parent_ids = set(children_of.keys())
    real_archives = [fo for fo in standalone if fo.get("@id") in parent_ids]
    plain_files = [fo for fo in standalone
                   if fo.get("@id") not in parent_ids
                   and fo.get("@id") not in fileset_parent_ids]

    cdif_distribution = []
    # node_for_file_id: file @id -> CDIF node (DataDownload or hasPart MediaObject)
    # that owns the cdif:hasPhysicalMapping for fields referencing that file.
    node_for_file_id = {}

    # 1) Stand-alone (non-archive) DataDownloads
    for fo in plain_files:
        dd = _file_object_basic(fo)
        types = ["schema:DataDownload"]
        if fo.get("@id") in record_sets_by_file:
            types.append("cdi:TabularTextDataSet")
        dd["@type"] = types
        _mark_tabular(dd, fo)
        cdif_distribution.append(dd)
        node_for_file_id[fo.get("@id")] = dd

    # 2) Archives + their contained parts
    for archive_fo in real_archives:
        archive_dd = _file_object_basic(archive_fo)
        archive_dd["@type"] = ["schema:DataDownload"]
        # Drop the nil placeholder sha
        # (already handled by _convert_checksum)
        parts = []
        for child in children_of.get(archive_fo.get("@id"), []):
            part = _file_object_basic(child, is_archive_component=True)
            child_types = ["schema:MediaObject"]
            if child.get("@id") in record_sets_by_file:
                child_types.append("cdi:TabularTextDataSet")
            part["@type"] = child_types
            _mark_tabular(part, child)
            parts.append(part)
            node_for_file_id[child.get("@id")] = part

        if parts:
            archive_dd["schema:hasPart"] = parts
        # Ensure encodingFormat application/zip is set for the archive
        ef = archive_dd.get("schema:encodingFormat")
        if not ef:
            archive_dd["schema:encodingFormat"] = ["application/zip"]
        cdif_distribution.append(archive_dd)

    # 3) Orphan children (parent not found among standalone files): keep as
    # bare DataDownloads with a warning.
    for parent_id, children in children_of.items():
        if any(fo.get("@id") == parent_id for fo in real_archives):
            continue
        if verbose:
            print(f"  WARN: containedIn refers to unknown @id {parent_id!r}; "
                  f"emitting {len(children)} child file(s) as standalone")
        for child in children:
            dd = _file_object_basic(child)
            dd["@type"] = ["schema:DataDownload"]
            cdif_distribution.append(dd)
            node_for_file_id[child.get("@id")] = dd

    # 4) FileSets -> standalone DataDownloads. A FileSet carries no contentUrl
    # of its own, so inherit the containedIn parent FileObject's URL; record the
    # selection glob in the description for traceability.
    for fs in file_sets:
        dd = _file_object_basic(fs)
        dd["@type"] = ["schema:DataDownload"]
        if "schema:contentUrl" not in dd:
            ci = fs.get("containedIn")
            pid = ci.get("@id") if isinstance(ci, dict) else (ci if isinstance(ci, str) else None)
            parent = fo_by_id.get(pid) if pid else None
            purl = parent.get("contentUrl") if isinstance(parent, dict) else None
            if purl and purl != OGC_NIL_INAPPLICABLE:
                dd["schema:contentUrl"] = purl
        inc = fs.get("includes")
        if inc:
            glob = inc if isinstance(inc, str) else ", ".join(_as_list(inc))
            note = f"File set; includes: {glob}"
            dd["schema:description"] = (
                f"{dd['schema:description']} ({note})" if dd.get("schema:description") else note)
        cdif_distribution.append(dd)
        node_for_file_id[fs.get("@id")] = dd

    return cdif_distribution, node_for_file_id


def _convert_is_based_on(croissant, verbose=False):
    """Map Croissant isBasedOn source(s) to prov:wasDerivedFrom entries.

    isBasedOn names the resource(s) this dataset was derived from — that is
    derivation provenance, which in CDIF is prov:wasDerivedFrom (a CreativeWork
    reference), not a distribution."""
    out = []
    for src in _as_list(croissant.get("isBasedOn", [])):
        if isinstance(src, str):
            out.append({"@id": src})
            continue
        if not isinstance(src, dict):
            continue
        entry = {"@type": ["schema:CreativeWork"]}
        if src.get("@id"):
            entry["@id"] = src["@id"]
        if src.get("name"):
            entry["schema:name"] = src["name"]
        if src.get("description"):
            entry["schema:description"] = src["description"]
        url = src.get("contentUrl") or src.get("url")
        if url:
            entry["schema:url"] = url
        enc = src.get("encodingFormat")
        if enc:
            entry["schema:encodingFormat"] = [enc] if isinstance(enc, str) else enc
        out.append(entry)
    if verbose and out:
        print(f"  isBasedOn -> prov:wasDerivedFrom: {len(out)} source(s)")
    return out


def _download_to_resource_part(dd):
    """A CDIF DataDownload as a Manifest resourcePartItem.

    For a Croissant FileObject that no RecordSet draws data from. It is not a
    distribution of this dataset -- a distribution is another downloadable
    form of the SAME content, and a Dutch translation is not another encoding
    of a CSV. It is a member of the package: independently accessible, at its
    own address, differing in content and format from its siblings. That is
    what schema:hasPart on the Dataset means, and the Manifest profile says
    such a part "may carry its own schema:distribution".

    So the node splits in two. What the resource IS -- name, description,
    language, modification date, author -- stays on the part. How you GET it
    -- URL, format, checksum, size -- becomes the part's own distribution.

    Typed schema:CreativeWork: it is in the profile's enumeration, it is true
    of everything a package can hold, and the alternative is inferring Article
    or TextDigitalDocument from a media type, which is a guess.
    """
    part = {"@type": ["schema:CreativeWork"]}
    # Only an absolute IRI. Croissant @ids are frequently bare filenames
    # ("croissant_acid_rain_final.json"), and a part carrying one fails the
    # "must be a resolvable URL" shape -- the relatedLink form this replaces
    # never hit that because it built a fresh node with no @id at all. The
    # part is still reachable through its distribution's contentUrl.
    part_id = dd.get("@id")
    if isinstance(part_id, str) and "://" in part_id:
        part["@id"] = part_id
    for key in ("schema:name", "schema:description", "schema:inLanguage",
                "schema:dateModified", "schema:creator"):
        if dd.get(key):
            part[key] = dd[key]

    access = {"@type": ["schema:DataDownload"]}
    for key in ("schema:contentUrl", "schema:encodingFormat", "spdx:checksum",
                "schema:size"):
        if dd.get(key):
            access[key] = dd[key]
    if len(access) > 1:
        part["schema:distribution"] = [access]

    # A part is a package member because it is independently accessible, so it
    # has to say where. The content URL is that address; without a schema:url
    # the part is an assertion that something exists somewhere.
    url = dd.get("schema:contentUrl")
    if isinstance(url, str) and url.startswith("http"):
        part["schema:url"] = url
    return part


def _has_data_part(dd):
    """True if this distribution node (or any of its archive hasPart items) is
    a data file — i.e. carries cdif:hasPhysicalMapping."""
    if "cdif:hasPhysicalMapping" in dd:
        return True
    return any(isinstance(p, dict) and "cdif:hasPhysicalMapping" in p
               for p in _as_list(dd.get("schema:hasPart", [])))


# ---------------------------------------------------------------------------
# RecordSet / Field -> variableMeasured + hasPhysicalMapping
# ---------------------------------------------------------------------------

def _field_source_file_id(field):
    """Return the @id of the FileObject or FileSet this Field draws from.

    Croissant field sources reference either a single ``fileObject`` (the
    CSV shape Kaggle/OpenML emit) or a ``fileSet`` (a glob of files, e.g.
    Hugging Face's parquet shards). Both anchor the field's physical mapping."""
    src = field.get("source")
    if not isinstance(src, dict):
        return None
    for key in ("fileObject", "fileSet"):
        ref = src.get(key)
        if isinstance(ref, dict):
            return ref.get("@id")
        if isinstance(ref, str):
            return ref
    return None


def _field_extract_column(field):
    """Return the column header name from source.extract.column, if any."""
    src = field.get("source")
    if not isinstance(src, dict):
        return None
    extract = src.get("extract")
    if isinstance(extract, dict):
        return extract.get("column")
    return None


def _field_equivalent_property(field):
    eq = field.get("equivalentProperty")
    if isinstance(eq, str) and eq.startswith("http"):
        return eq
    if isinstance(eq, dict):
        return eq.get("@id")
    return None


def _index_record_sets(croissant):
    """Build a map: source-file-@id -> list of (recordset, [fields])."""
    out = {}  # file_id -> list of (rs_dict, [field_dicts])
    for rs in _as_list(croissant.get("recordSet", [])):
        if not isinstance(rs, dict):
            continue
        fields = _as_list(rs.get("field", []))
        # Group fields by their source file. The common case is one file per
        # RecordSet, but we handle multi-source defensively.
        by_file = {}
        for fld in fields:
            if not isinstance(fld, dict):
                continue
            fid = _field_source_file_id(fld)
            by_file.setdefault(fid, []).append(fld)

        for fid, flds in by_file.items():
            out.setdefault(fid, []).append((rs, flds))
    return out


def _convert_fields_to_cdif(record_sets_by_file, node_for_file_id, verbose=False):
    """For each file with attached fields, build (variableMeasured[], per-file
    hasPhysicalMapping[]). Returns:
      (vars_list, mappings_by_file_id)
    """
    variables = []
    seen_var_ids = set()
    mappings_by_file_id = {}
    field_ref_to_var_id = {}   # Croissant field @id/name -> CDIF variable @id

    for fid, rs_groups in record_sets_by_file.items():
        if fid is None:
            if verbose:
                print("  WARN: RecordSet fields with no source.fileObject — "
                      "skipping (no CDIF anchor)")
            continue
        if fid not in node_for_file_id:
            if verbose:
                print(f"  WARN: RecordSet references unknown FileObject "
                      f"{fid!r}; skipping its fields")
            continue

        mappings = []
        # Concatenate all field groups (one per RecordSet for this file)
        all_fields = [f for _rs, flds in rs_groups for f in flds]

        for ordinal, fld in enumerate(all_fields, start=1):
            fname = fld.get("name") or f"field_{ordinal}"
            var_id = _slug_var_id(fname)
            if var_id in seen_var_ids:
                var_id = f"{var_id}_{ordinal}"
            seen_var_ids.add(var_id)
            # Record both the field name and its @id so a RecordSet.key that
            # references either can be resolved back to this variable.
            field_ref_to_var_id[fname] = var_id
            if fld.get("@id"):
                field_ref_to_var_id[fld["@id"]] = var_id

            var_node = {
                "@id": var_id,
                "@type": ["schema:PropertyValue", "cdi:InstanceVariable"],
                "schema:name": fname,
            }
            desc = fld.get("description")
            if desc:
                var_node["schema:description"] = desc

            eq = _field_equivalent_property(fld)
            if eq:
                var_node["schema:propertyID"] = _property_id(eq)

            # Croissant dataType -> current cdif: shape: a single-valued
            # cdif:physicalDataType (xsd token) on the variable, plus the
            # intended-type IRI. No cdi:ValueDomain wrapper.
            dtype = fld.get("dataType")
            if dtype:
                if isinstance(dtype, list):
                    dtype = dtype[0] if dtype else None
                xsd_type = DATATYPE_INVERSE.get(dtype, "xsd:string")
                var_node["cdif:physicalDataType"] = xsd_type
                var_node["cdi:hasIntendedDataType"] = {
                    "@id": _XSD_IRI.get(xsd_type, "https://www.w3.org/TR/xmlschema-2/#string")
                }

            variables.append(var_node)

            # Current physical-mapping shape: cdif:index (column ordinal),
            # cdif:physicalDataType (storage token), cdif:formats_InstanceVariable
            # (link to the variable). No cdi:locator / cdi:ValueMapping type.
            mapping = {
                "cdif:index": ordinal,
                "cdif:formats_InstanceVariable": {"@id": var_id},
            }
            if dtype:
                mapping["cdif:physicalDataType"] = DATATYPE_INVERSE.get(dtype, "xsd:string")
            mappings.append(mapping)

        if mappings:
            mappings_by_file_id[fid] = mappings

    return variables, mappings_by_file_id, field_ref_to_var_id


def _convert_primary_key(croissant, field_ref_to_var_id):
    """Croissant cr:RecordSet.key -> CDIF cdif:hasPrimaryKey.

    Emits a cdif:Key whose cdif:isComposedOf is the ordered list of the key
    fields' InstanceVariable @ids. Returns None if no resolvable key."""
    refs = []
    for rs in _as_list(croissant.get("recordSet", [])):
        if not isinstance(rs, dict):
            continue
        for k in _as_list(rs.get("key")):
            ref = k.get("@id") if isinstance(k, dict) else k
            if not ref:
                continue
            var_id = field_ref_to_var_id.get(ref)
            if not var_id:
                # key may reference "recordset/field"; try the trailing segment
                var_id = field_ref_to_var_id.get(str(ref).split("/")[-1])
            if var_id:
                refs.append({"@id": var_id})
    if not refs:
        return None
    return {"@type": ["cdif:Key"], "cdif:isComposedOf": refs}


# ---------------------------------------------------------------------------
# Main conversion
# ---------------------------------------------------------------------------

# Built once: reading and indexing the table on every record would be waste.
def _t_structural(value, source, rule, target):
    """Placed by a builder, not by the table pass.

    The row still carries the real target -- it is the mapping, and the only
    written record of where the value lands. What it cannot do is place it:
    `sc:includedInDataCatalog` is legal only inside `schema:subjectOf`, and the
    catalog record does not exist yet when the root pass runs. Naming the
    transform keeps the row from reading as an unimplemented mapping.
    """
    return None


def _t_agent_part(value, source, rule, target):
    """A property of an agent, not of the dataset.

    The row exists to document the agent sub-mapping -- sc:name, sc:url,
    sc:email and friends on a Person or Organization. The values are shaped by
    `_convert_agent` when the agent itself is converted, so there is nothing
    for the row to place, and it deliberately places nothing. Naming the
    transform rather than leaving the cell blank is what keeps the row from
    looking like an unfinished mapping.
    """
    return None


def _t_passthrough(value, source, rule, target):
    """Croissant property CDIF has no term for; keep it verbatim.

    Placing nothing is the point: a row that consumes nothing leaves the key
    for the converter's passthrough loop, which copies it and merges its
    prefix into the output @context. JSON-LD is open-world, so an unmapped
    property in its own namespace stays valid and stays readable.
    """
    return None


CROISSANT_TO_CDIF = _engine.MappingSet(
    os.path.join(_MAPPINGS, "croissant-to-cdif.sssom.tsv"),
    os.path.join(_MAPPINGS, "croissant-aliases.sssom.tsv"),
    transforms={
        "structural": _t_structural, "agent-part": _t_agent_part, "passthrough": _t_passthrough,
        "": _t_text, "text": _t_text, "iri": _t_iri, "idref": _t_idref,
        "date": _t_date, "list": _t_list, "langcode": _t_langcode,
        "identifier": _t_identifier, "license": _t_license,
        "derived": _t_derived, "agent": _t_agent, "funding": _t_funding,
        "accessflag": _t_accessflag, "catalog": _t_catalog, "period": _t_period,
    },
    # How CDIF wants each target shaped. Its own schema decides this, not the
    # Croissant correspondence, so it lives here rather than in the table.
    arity={
        "schema:license": "array",
        "schema:conditionsOfAccess": "array",
        "schema:keywords": "array",
        "schema:contributor": "array",
        "schema:distribution": "array",
        "schema:variableMeasured": "array",
        "schema:relatedLink": "array",
        "schema:alternateName": "array",
        "schema:sameAs": "array",
        "prov:wasGeneratedBy": "array",
        "prov:wasDerivedFrom": "array",
        "schema:creator": "ordered",
    },
)

# Source properties the table claims for the dataset, so the passthrough pass
# knows what has already been dealt with.
DATASET_CLASSES = ("sc:Dataset",)


def convert(croissant, verbose=False):
    """Convert a Croissant JSON-LD dict to a CDIF DataDescription JSON-LD dict."""

    # Sanity check — accept Croissant 1.0 or 1.1
    src_conforms = croissant.get("conformsTo")
    if src_conforms not in CROISSANT_SOURCE_URIS and verbose:
        print(f"  NOTE: input conformsTo is {src_conforms!r}; "
              f"expected one of {CROISSANT_SOURCE_URIS!r}")

    # Merge any prefix declarations from the source Croissant @context that
    # CDIF_CONTEXT doesn't already cover (needed when pass-through properties
    # like prov:wasGeneratedBy reference IRIs under custom prefixes).
    ctx = deepcopy(CDIF_CONTEXT)
    src_ctx = croissant.get("@context")
    if isinstance(src_ctx, dict):
        for k, v in src_ctx.items():
            if k.startswith("@"):
                continue
            if k in ctx:
                continue
            # Only carry simple "prefix": "IRI" mappings (the kind needed for
            # IRI compaction). Skip complex term objects from Croissant.
            if isinstance(v, str) and v.startswith(("http://", "https://")):
                ctx[k] = v

    out = {
        "@context": ctx,
        "@type": ["schema:Dataset"],
    }

    # Root @id: prefer DOI URL, then source @id, then a synthetic placeholder.
    _doi_value, _doi_url = _extract_doi(croissant)
    if _doi_url:
        out["@id"] = _doi_url
    elif croissant.get("@id"):
        out["@id"] = croissant["@id"]
    elif croissant.get("url"):
        out["@id"] = croissant["url"]
    else:
        out["@id"] = "_:dataset"

    # ---- Dataset-level fields, from the mapping table --------------------
    # croissant-to-cdif.sssom.tsv decides these. The blocks that follow only
    # handle what a table cannot say: what to do when the source is silent
    # about something CDIF requires.
    _src_ctx = croissant.get("@context") if isinstance(croissant.get("@context"), dict) else None
    _changes = []
    _consumed = CROISSANT_TO_CDIF.apply(
        croissant, out, DATASET_CLASSES, _changes,
        curie_of=lambda k: croissant_curie(k, _src_ctx))

    # A DOI is often only available inside citeAs, which the table cannot
    # reach: it is parsed out of prose, not mapped from a property.
    if "schema:identifier" not in out:
        _ident = _convert_identifier(croissant)
        if _ident:
            out["schema:identifier"] = _ident

    # CDIF asks for a licence and a silent omission cannot be told from an
    # oversight, so say it is knowably absent.
    if not out.get("schema:license"):
        _lic = _convert_license(croissant)
        if _lic:
            out["schema:license"] = _lic

    # Fallback dateModified: CDIF discovery requires it; when the source omits
    # dateModified, fall back to datePublished, then dateCreated, and finally to
    # the conversion date. That last step does fabricate a value -- a deliberate
    # choice, since an absent dateModified fails validation outright and the
    # conversion date is at least true of this serialization.
    if "schema:dateModified" not in out:
        for alt in ("datePublished", "dateCreated"):
            if croissant.get(alt):
                out["schema:dateModified"] = croissant[alt]
                if verbose:
                    print(f"  FALLBACK: schema:dateModified <- {alt}")
                break
        else:
            out["schema:dateModified"] = _date.date.today().isoformat()
            if verbose:
                print("  FALLBACK: schema:dateModified <- conversion date "
                      f"({out['schema:dateModified']}); source carried no date")

    # Whatever the date came from -- source, fallback or conversion date --
    # it has to match the shape's pattern to be worth emitting.
    if "schema:dateModified" in out:
        fixed = _normalize_date(out["schema:dateModified"])
        if fixed != out["schema:dateModified"] and verbose:
            print(f"  NORMALIZED: schema:dateModified {out['schema:dateModified']!r}"
                  f" -> {fixed!r}")
        if fixed:
            out["schema:dateModified"] = fixed
        else:
            out["schema:dateModified"] = _date.date.today().isoformat()

    version = croissant.get("version")
    if version and version != CROISSANT_VERSION_PLACEHOLDER:
        out["schema:version"] = version

    # Plain schema:identifier value: some producers emit `identifier` (or the
    # expanded `https://schema.org/identifier` key) carrying a bare string/code
    # or a PropertyValue rather than a DOI in citeAs.
    if "schema:identifier" not in out:
        for _k in ("identifier", "https://schema.org/identifier",
                   "http://schema.org/identifier"):
            _v = croissant.get(_k)
            if isinstance(_v, str) and _v.strip():
                out["schema:identifier"] = _v
                if verbose:
                    print(f"  schema:identifier <- {_k} = {_v!r}")
                break
            if isinstance(_v, (dict, list)):
                out["schema:identifier"] = _v
                break

    # Fallback identifier (prototype): CDIF discovery requires schema:identifier,
    # but most HF/Kaggle/OpenML records expose no DOI. Use the dataset's
    # landing-page URL (or @id) as a stable identifier so the record is usable;
    # a curator can replace it with a DOI later.
    if "schema:identifier" not in out:
        fallback_id = croissant.get("url") or croissant.get("@id")
        if isinstance(fallback_id, str) and fallback_id.startswith("http"):
            out["schema:identifier"] = fallback_id
            if verbose:
                print(f"  FALLBACK: schema:identifier <- {fallback_id} (no DOI in source)")

    # ---- Distribution + RecordSet ----------------------------------------
    record_sets_by_file = _index_record_sets(croissant)
    cdif_distribution, node_for_file_id = _convert_distribution(
        croissant, record_sets_by_file, verbose=verbose)

    variables, mappings_by_file, field_ref_to_var_id = _convert_fields_to_cdif(
        record_sets_by_file, node_for_file_id, verbose=verbose)

    # Attach hasPhysicalMapping arrays to the right nodes (current cdif: name)
    for fid, mappings in mappings_by_file.items():
        node = node_for_file_id.get(fid)
        if node is not None:
            node["cdif:hasPhysicalMapping"] = mappings

    # A FileObject that no RecordSet draws data from is not a distribution of
    # this dataset — a distribution is another downloadable form of the same
    # content — but it is still a member of the package, independently
    # accessible at its own address. That is Dataset-level schema:hasPart.
    #
    # BUT only split when the dataset actually has at least one described data
    # file: if NO file has a RecordSet, the file(s) are still the data (just
    # undescribed) and stay as distribution.
    if cdif_distribution:
        data_file_ids = set(record_sets_by_file.keys())
        has_data = bool(data_file_ids) or any(_has_data_part(dd)
                                              for dd in cdif_distribution)
        data_dist, parts = [], []
        for dd in cdif_distribution:
            is_data = _has_data_part(dd) or dd.get("@id") in data_file_ids
            (data_dist if (is_data or not has_data) else parts).append(dd)
        if data_dist:
            out["schema:distribution"] = data_dist
        if parts:
            out["schema:hasPart"] = [_download_to_resource_part(dd) for dd in parts]
        if verbose:
            print(f"  distribution split: {len(data_dist)} data distribution(s), "
                  f"{len(parts)} package member(s) -> schema:hasPart")
    if variables:
        out["schema:variableMeasured"] = variables

    # RecordSet primary key -> cdif:hasPrimaryKey
    primary_key = _convert_primary_key(croissant, field_ref_to_var_id)
    if primary_key:
        out["cdif:hasPrimaryKey"] = primary_key

    # ---- Pass-through properties (preserved by the forward converter) ----
    PASS_THROUGH = [
        "prov:wasGeneratedBy",
        "prov:wasDerivedFrom",
        "dqv:hasQualityMeasurement",
        "schema:spatialCoverage",
        "schema:temporalCoverage",
        "schema:measurementTechnique",
        "schema:contributor",
        "schema:subjectOf",
    ]
    for key in PASS_THROUGH:
        if key in croissant:
            out[key] = croissant[key]

    # ---- Conformance stub (CDIF subjectOf / CatalogRecord) ---------------
    # @type includes schema:Dataset so the CDIF frame keeps the block
    # (CDIF-frame-2026.jsonld filters subjectOf on @type: schema:Dataset).
    if "schema:subjectOf" not in out:
        # Current CDIF catalog-record shape: a schema:Dataset bearing
        # schema:additionalType "dcat:CatalogRecord", schema:about pointing at
        # the described dataset, and dcterms:conformsTo profile URIs.
        # dcterms:conformsTo is derived from the record's actual content by
        # detect_conformance (presence ASK + per-class content SHACL), so the
        # record claims exactly the profiles it satisfies — e.g. data_description
        # only when InstanceVariable-typed variables are present, manifest when an
        # archive distribution carries hasPart files.
        subject_of = {
            "@type": ["schema:Dataset"],
            "schema:additionalType": [{"@id": "dcat:CatalogRecord"}],
            "schema:about": {"@id": out["@id"]},
        }
        # The metadata record needs its own URI: SHACL's
        # metadataIdentifierProperty asks for it, and a blank node cannot be
        # cited or dereferenced from outside the file. Same convention as the
        # building-block examples -- the resource IRI with "/metadata" appended
        # -- and only when there is an absolute IRI to derive it from.
        dataset_id = out.get("@id", "")
        if dataset_id.startswith(("http://", "https://", "urn:")):
            subject_of["@id"] = dataset_id.rstrip("/") + "/metadata"
        date_modified = croissant.get("dateModified")
        if date_modified:
            subject_of["schema:sdDatePublished"] = date_modified
        # The catalog a dataset sits in describes the metadata record, not the
        # dataset, and schema:includedInDataCatalog is legal only here. The
        # source's own node is reshaped: Croissant writes it with sc: types and
        # bare name/url keys, which are not CDIF terms.
        _catalog = _t_catalog(croissant.get("includedInDataCatalog"),
                              croissant, {}, out)
        if _catalog:
            subject_of["schema:includedInDataCatalog"] = _catalog
        out["schema:subjectOf"] = subject_of

        if HAS_DETECT:
            uris = detect_conformance(out, verbose=verbose)
            apply_conformance(out, uris)
        else:
            # Fallback when detect_conformance / rdflib is unavailable: the prior
            # heuristic (core + discovery, plus data_description iff variables).
            conforms = list(CDIF_CORE_DISCOVERY_CONFORMS_TO)
            if variables:
                conforms.append(CDIF_DATA_DESCRIPTION_CONFORMS_TO)
            subject_of["dcterms:conformsTo"] = [{"@id": uri} for uri in conforms]
        if verbose:
            got = [c.get("@id") for c in
                   out["schema:subjectOf"].get("dcterms:conformsTo", [])]
            print(f"  conformsTo: {got}")
    # ---- Traceability: where did this come from --------------------------
    out.setdefault("prov:wasDerivedFrom", []).append(
        {"@id": CROISSANT_SOURCE_URI,
         "schema:description": "Converted from Croissant 1.0 JSON-LD"}
    )

    if verbose:
        print(f"  distribution: {len(cdif_distribution)} entr(ies)")
        print(f"  variableMeasured: {len(variables)} InstanceVariable(s)")
        attached_files = sum(1 for n in node_for_file_id.values()
                             if "cdif:hasPhysicalMapping" in n)
        print(f"  cdif:hasPhysicalMapping attached to {attached_files} file(s)")

    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Convert Croissant JSON-LD to CDIF DataDescription JSON-LD.")
    parser.add_argument("input", help="Path to Croissant JSON-LD input")
    parser.add_argument("-o", "--output", default=None,
                        help="Output path (default: stdout)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Print conversion details")
    args = parser.parse_args(argv)

    with open(args.input, "r", encoding="utf-8") as f:
        croissant = json.load(f)

    if args.verbose:
        print(f"Reading: {args.input}")
        print(f"  source name: {croissant.get('name')!r}")

    cdif = convert(croissant, verbose=args.verbose)

    text = json.dumps(cdif, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text)
        if args.verbose:
            print(f"Wrote: {args.output}")
    else:
        sys.stdout.write(text)
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()
