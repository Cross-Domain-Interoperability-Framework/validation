#!/usr/bin/env python3
"""
ConvertToCroissant.py - Convert CDIF JSON-LD metadata to Croissant format.

Reads a CDIF metadata document and produces a Croissant (mlcommons.org/croissant/1.1)
JSON-LD document suitable for ML dataset discovery and loading.

Mapping summary (current CDIF DataDescription / DataStructure schema, cdif: namespace):
  CDIF schema:DataDownload         → cr:FileObject
  CDIF archive DataDownload        → cr:FileObject (archive) + cr:FileObject per
                                     component with containedIn
  CDIF schema:variableMeasured     → cr:RecordSet + cr:Field (when physicalMapping present)
  CDIF cdif:hasPhysicalMapping     → cr:Field.source.extract.column (via cdif:index +
                                     cdif:formats_InstanceVariable)
  CDIF cdif:physicalDataType /     → cr:Field.dataType
       cdi:hasIntendedDataType
  CDIF schema:propertyID / cdif:uses → cr:Field.equivalentProperty
  CDIF cdif:hasPrimaryKey          → cr:RecordSet.key
  CDIF cdi:qualifies / ForeignKey  → cr:Field.references (FK analogy)

Usage:
    python ConvertToCroissant.py input.jsonld [-o output.json] [-v]
"""

import json
import os
import sys
import argparse
import re
from copy import deepcopy


# ---------------------------------------------------------------------------
# Croissant JSON-LD context (spec Appendix 1)
# ---------------------------------------------------------------------------

CROISSANT_CONTEXT = {
    "@language": "en",
    "@vocab": "https://schema.org/",
    "sc": "https://schema.org/",
    "cr": "http://mlcommons.org/croissant/",
    "rai": "http://mlcommons.org/croissant/RAI/",
    "dct": "http://purl.org/dc/terms/",
    "wd": "https://www.wikidata.org/wiki/",
    "citeAs": "cr:citeAs",
    "column": "cr:column",
    "conformsTo": "dct:conformsTo",
    "data": {"@id": "cr:data", "@type": "@json"},
    "dataType": {"@id": "cr:dataType", "@type": "@vocab"},
    "examples": {"@id": "cr:examples", "@type": "@json"},
    "extract": "cr:extract",
    "field": "cr:field",
    "fileProperty": "cr:fileProperty",
    "fileObject": "cr:fileObject",
    "fileSet": "cr:fileSet",
    "format": "cr:format",
    "includes": "cr:includes",
    "isLiveDataset": "cr:isLiveDataset",
    "jsonPath": "cr:jsonPath",
    "key": "cr:key",
    "md5": "cr:md5",
    "parentField": "cr:parentField",
    "path": "cr:path",
    "recordSet": "cr:recordSet",
    "references": "cr:references",
    "regex": "cr:regex",
    "repeated": "cr:repeated",
    "replace": "cr:replace",
    "samplingRate": "cr:samplingRate",
    "separator": "cr:separator",
    "source": "cr:source",
    "subField": "cr:subField",
    "transform": "cr:transform",
}

CROISSANT_CONFORMS_TO = "http://mlcommons.org/croissant/1.1"

# Map CDIF / XSD data types → Croissant sc: types
DATATYPE_MAP = {
    "xsd:decimal": "sc:Float",
    "xsd:float": "sc:Float",
    "xsd:double": "sc:Float",
    "xsd:integer": "sc:Integer",
    "xsd:int": "sc:Integer",
    "xsd:long": "sc:Integer",
    "xsd:DateTime": "sc:Date",
    "xsd:dateTime": "sc:Date",
    "xsd:date": "sc:Date",
    "xsd:boolean": "sc:Boolean",
    "xsd:string": "sc:Text",
    "xsd:anyURI": "sc:URL",
    "String": "sc:Text",
    "string": "sc:Text",
    "Text": "sc:Text",
    # Physical-mapping storage tokens (cdif:physicalDataType on a mapping)
    "Numeric": "sc:Float",
    "Decimal": "sc:Float",
    "Float": "sc:Float",
    "Double": "sc:Float",
    "Integer": "sc:Integer",
    "Int": "sc:Integer",
    "Boolean": "sc:Boolean",
    "Date": "sc:Date",
    "DateTime": "sc:Date",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get(obj, *keys, default=None):
    """Return the first matching key's value from *obj*."""
    for k in keys:
        if k in obj:
            return obj[k]
    return default


def _as_list(val):
    """Wrap a scalar in a list; pass lists through."""
    if val is None:
        return []
    return val if isinstance(val, list) else [val]


def _sanitize_id(name):
    """Make a string safe for use as a JSON-LD @id fragment."""
    return re.sub(r"[^a-zA-Z0-9._-]", "_", name)


# ---------------------------------------------------------------------------
# Identifier / DOI extraction
# ---------------------------------------------------------------------------

def _extract_identifier_url(cdif):
    """Pull a DOI URL (or other identifier URL) from CDIF schema:identifier."""
    ident = _get(cdif, "schema:identifier")
    if ident is None:
        return None
    if isinstance(ident, str):
        return ident if ident.startswith("http") else None
    if isinstance(ident, dict):
        url = _get(ident, "schema:url", "url")
        if url and url.startswith("http"):
            return url
        val = _get(ident, "schema:value", "value")
        if isinstance(val, str) and val.startswith("10."):
            return f"https://doi.org/{val}"
    return None


# ---------------------------------------------------------------------------
# Creator / contributor extraction
# ---------------------------------------------------------------------------

def _convert_agent(agent):
    """Convert a CDIF Person/Organization to a Croissant agent dict."""
    if not isinstance(agent, dict):
        return None
    out = {}
    raw_type = _get(agent, "@type")
    if raw_type:
        types = _as_list(raw_type)
        for t in types:
            if t in ("schema:Person", "schema:Organization"):
                out["@type"] = t.replace("schema:", "")
                break
        if "@type" not in out:
            out["@type"] = types[0].replace("schema:", "")

    name = _get(agent, "schema:name")
    if name:
        out["name"] = name

    ident = _get(agent, "schema:identifier")
    if isinstance(ident, str) and ident.startswith("http"):
        out["@id"] = ident
    elif agent.get("@id") and str(agent["@id"]).startswith("http"):
        out["@id"] = agent["@id"]

    return out if out.get("name") else None


def _extract_creators(cdif):
    """Extract creator list, unwrapping @list if present."""
    raw = _get(cdif, "schema:creator")
    if not raw:
        return []
    if isinstance(raw, dict) and "@list" in raw:
        raw = raw["@list"]
    agents = _as_list(raw)
    return [a for a in (map(_convert_agent, agents)) if a]


# ---------------------------------------------------------------------------
# Other discovery-level helpers
# ---------------------------------------------------------------------------

def _extract_keywords(cdif):
    """Return a flat list of keyword strings."""
    kw = _get(cdif, "schema:keywords")
    if kw:
        result = []
        for k in _as_list(kw):
            if isinstance(k, dict):
                n = _get(k, "schema:name", "name")
                if n:
                    result.append(n)
            elif k:
                result.append(str(k))
        return result
    # Fall back: additionalType as keywords
    at = _get(cdif, "schema:additionalType")
    return _as_list(at) if at else []


def _extract_date_modified(cdif):
    dm = _get(cdif, "schema:dateModified")
    if dm:
        return dm
    subj = _get(cdif, "schema:subjectOf")
    if isinstance(subj, dict):
        return _get(subj, "schema:dateModified")
    return None


def _extract_license(cdif):
    lic = _get(cdif, "schema:license")
    if lic:
        for v in _as_list(lic):
            if v and v != "missing":
                return v
    coa = _get(cdif, "schema:conditionsOfAccess")
    if coa:
        return coa
    return None


def _format_size(size_obj):
    """Convert CDIF QuantitativeValue → Croissant 'NNN B' string."""
    if not isinstance(size_obj, dict):
        return None
    val = _get(size_obj, "schema:value", "value")
    if val is None:
        return None
    unit = _get(size_obj, "schema:unitText", "unitText", default="byte")
    abbr = {"byte": "B", "bytes": "B", "kilobyte": "kB", "megabyte": "MB",
            "gigabyte": "GB"}.get(unit, unit)
    return f"{val} {abbr}"


def _map_datatype(cdif_type):
    if not cdif_type:
        return "sc:Text"
    return DATATYPE_MAP.get(cdif_type, "sc:Text")


# ---------------------------------------------------------------------------
# Distribution conversion
# ---------------------------------------------------------------------------

def _is_nil_url(url):
    return not url or url == "" or "withheld" in url


def _extract_sha256(obj):
    """Extract a SHA-256 hash from CDIF metadata.

    Handles three patterns:
      1. spdx:checksum as bare hex string
      2. spdx:checksum as object with spdx:checksumValue
      3. sha256 hash embedded in schema:description text
    """
    cksum = _get(obj, "spdx:checksum")
    if isinstance(cksum, str) and len(cksum) == 64:
        return cksum
    if isinstance(cksum, dict):
        val = _get(cksum, "spdx:checksumValue")
        if val and isinstance(val, str):
            return val

    # Fall back: extract sha256:XXXX from description
    desc = _get(obj, "schema:description", default="")
    if isinstance(desc, str):
        m = re.search(r"sha256:([0-9a-fA-F]{64})", desc)
        if m:
            return m.group(1)
    return None


def _convert_distribution(cdif, verbose=False):
    """Convert CDIF distribution → (cr_distribution, tabular_files).

    *tabular_files* is a list of (file_id, hasPart_obj) for parts that carry
    ``cdif:hasPhysicalMapping``; these feed RecordSet generation.
    """
    dists = _as_list(_get(cdif, "schema:distribution", default=[]))
    cr_dist = []
    tabular_files = []

    for di, dist in enumerate(dists):
        if not isinstance(dist, dict):
            continue

        enc = _get(dist, "schema:encodingFormat", default="")
        if isinstance(enc, list):
            enc = enc[0] if enc else ""
        content_url = _get(dist, "schema:contentUrl", default="")
        has_parts = _get(dist, "schema:hasPart")

        if enc == "application/zip" and has_parts:
            cr_dist, tabular_files = _convert_archive_distribution(
                dist, di, cr_dist, tabular_files, content_url, verbose)
        else:
            cr_dist, dist_id = _convert_simple_distribution(
                dist, di, cr_dist, content_url, enc)
            # A non-archive DataDownload that carries physical mappings (a
            # cdi:TabularTextDataSet) feeds RecordSet generation too.
            if _get(dist, "cdif:hasPhysicalMapping"):
                tabular_files.append((dist_id, dist))
                if verbose:
                    print(f"  Tabular file with physical mapping: "
                          f"{_get(dist, 'schema:name') or dist_id}")

    return cr_dist, tabular_files


def _convert_archive_distribution(dist, di, cr_dist, tabular_files,
                                  content_url, verbose):
    """Handle archive (zip) distribution with hasPart.

    The archive itself becomes a cr:FileObject with the real contentUrl.
    Each component file becomes a separate cr:FileObject in distribution
    with containedIn referencing the archive and contentUrl set to
    OGC nil:inapplicable (component files are not independently
    downloadable).
    """
    has_parts = _as_list(_get(dist, "schema:hasPart"))
    nil_url = _is_nil_url(content_url)

    archive_name = _get(dist, "schema:name") or f"archive-{di}.zip"
    archive_id = _sanitize_id(archive_name)
    archive_sha = _extract_sha256(dist)

    # Archive FileObject
    archive_obj = {
        "@type": "cr:FileObject",
        "@id": archive_id,
        "name": archive_name,
        "encodingFormat": "application/zip",
        "contentUrl": (content_url if not nil_url
                       else "http://www.opengis.net/def/nil/ogc/0/inapplicable"),
    }
    desc = _get(dist, "schema:description")
    if desc:
        archive_obj["description"] = desc
    if archive_sha:
        archive_obj["sha256"] = archive_sha
    else:
        archive_obj["sha256"] = "0" * 64  # nil placeholder - archive checksum not available
    cr_dist.append(archive_obj)

    # Component files -- flat in distribution with containedIn back-reference
    for pi, part in enumerate(has_parts):
        if not isinstance(part, dict):
            continue

        part_name = _get(part, "schema:name", default=f"file-{di}-{pi}")
        part_id = _sanitize_id(part_name)

        part_enc = _get(part, "schema:encodingFormat", default="")
        if isinstance(part_enc, list):
            part_enc = part_enc[0] if part_enc else ""

        fobj = {
            "@type": "cr:FileObject",
            "@id": part_id,
            "name": part_name,
            "contentUrl": "http://www.opengis.net/def/nil/ogc/0/inapplicable",
            "containedIn": {"@id": archive_id},
        }
        if part_enc:
            fobj["encodingFormat"] = part_enc

        part_desc = _get(part, "schema:description")
        if part_desc and part_desc not in ("", "default description"):
            # Strip inline checksums from description text
            cleaned = re.sub(r"sha256:[0-9a-fA-F]+\s*;\s*", "", part_desc).strip()
            if cleaned:
                fobj["description"] = cleaned

        size_str = _format_size(_get(part, "schema:size"))
        if size_str:
            fobj["contentSize"] = size_str

        sha = _extract_sha256(part)
        if sha:
            fobj["sha256"] = sha

        cr_dist.append(fobj)

        # Track tabular files with physical mapping for RecordSet generation
        if _get(part, "cdif:hasPhysicalMapping"):
            tabular_files.append((part_id, part))
            if verbose:
                print(f"  Tabular file with physical mapping: {part_name}")

    return cr_dist, tabular_files


def _convert_simple_distribution(dist, di, cr_dist, content_url, enc):
    """Handle a non-archive DataDownload."""
    dist_name = _get(dist, "schema:name")
    if not dist_name and content_url and not _is_nil_url(content_url):
        dist_name = content_url.rsplit("/", 1)[-1] or f"file-{di}"
    if not dist_name:
        dist_name = f"file-{di}"

    dist_id = _sanitize_id(dist_name)
    fobj = {
        "@type": "cr:FileObject",
        "@id": dist_id,
        "name": dist_name,
        # Croissant requires a contentUrl on every FileObject. Use the real URL
        # when present, otherwise the OGC nil:inapplicable URI as a valid-URL
        # placeholder (the resource is described but not directly downloadable).
        "contentUrl": (content_url if content_url and not _is_nil_url(content_url)
                       else "http://www.opengis.net/def/nil/ogc/0/inapplicable"),
        # encodingFormat is mandatory on a Croissant FileObject. Fall back to a
        # generic media type when CDIF doesn't supply one (e.g. a WebAPI/EntryPoint
        # distribution that carries no encodingFormat).
        "encodingFormat": enc or "application/octet-stream",
    }

    desc = _get(dist, "schema:description")
    if desc:
        fobj["description"] = desc

    # Croissant requires sha256 or md5 on every FileObject. Use the real
    # checksum when present, otherwise a nil placeholder (the inverse strips it).
    sha = _extract_sha256(dist)
    fobj["sha256"] = sha if sha else "0" * 64

    cr_dist.append(fobj)
    return cr_dist, dist_id


# ---------------------------------------------------------------------------
# RecordSet / Field conversion
# ---------------------------------------------------------------------------

def _build_variable_index(cdif):
    """Map variable @id → variable object from schema:variableMeasured."""
    variables = _as_list(_get(cdif, "schema:variableMeasured", default=[]))
    return {v["@id"]: v for v in variables
            if isinstance(v, dict) and v.get("@id")}


def _extract_equivalent_property(var_obj):
    """Pull an equivalentProperty URL from schema:propertyID or cdif:uses."""
    # schema:propertyID
    for pid in _as_list(_get(var_obj, "schema:propertyID", default=[])):
        if isinstance(pid, dict):
            uri = _get(pid, "@id", "schema:url")
            if uri and uri != "missing" and uri.startswith("http"):
                return uri
        elif isinstance(pid, str) and pid != "missing" and pid.startswith("http"):
            return pid

    # cdif:uses (concept reference) -- may be a URI string, a {@id} object, or
    # a DefinedTerm; take the first resolvable IRI.
    for use in _as_list(_get(var_obj, "cdif:uses", default=[])):
        if isinstance(use, dict):
            uid = _get(use, "@id", "schema:identifier")
            if uid and isinstance(uid, str) and uid.startswith("http"):
                return uid
        elif isinstance(use, str) and use.startswith("http"):
            return use
    return None


def _datatype_token(val):
    """Normalize a cdif:physicalDataType / cdi:hasIntendedDataType value (string,
    {@id} reference, or DefinedTerm) to a token for DATATYPE_MAP lookup."""
    ref = None
    if isinstance(val, str):
        ref = val
    elif isinstance(val, dict):
        # @id reference (e.g. https://www.w3.org/TR/xmlschema-2/#decimal) or
        # DefinedTerm with schema:identifier/name
        ref = _get(val, "@id", "schema:identifier", "schema:name")
    if not isinstance(ref, str):
        return None
    # Already a usable token (xsd:..., a storage word like "Numeric", etc.)
    if ref in DATATYPE_MAP or ":" not in ref:
        return ref
    if ref.startswith("xsd:"):
        return ref
    # A datatype IRI (XMLSchema #fragment or last path segment) -> xsd: token
    frag = re.split(r"[#/]", ref.rstrip("/"))[-1]
    return f"xsd:{frag}" if frag else ref


def _var_name(var_obj, default=""):
    """Best human/column name of an InstanceVariable (cdif:name, then schema:name)."""
    nm = _get(var_obj, "cdif:name", "schema:name")
    if isinstance(nm, list):
        nm = nm[0] if nm else None
    return nm or default


def _convert_record_sets(tabular_files, var_index, cdif, verbose=False):
    """Build Croissant RecordSets from tabular files + physical mappings.

    Reads the current CDIF DataDescription shape:
      cdif:hasPhysicalMapping[] with cdif:index, cdif:formats_InstanceVariable,
      cdif:physicalDataType; InstanceVariable carries cdi:hasIntendedDataType.
    Emits cr:RecordSet.key from the dataset-level cdif:hasPrimaryKey and
    cr:Field.references from a variable's cdi:qualifies (FK analogy).
    """
    record_sets = []

    # Dataset-level primary key: cdif:hasPrimaryKey -> cdif:Key -> cdif:isComposedOf
    pk = _get(cdif, "cdif:hasPrimaryKey")
    pk_var_ids = []
    if isinstance(pk, dict):
        for c in _as_list(_get(pk, "cdif:isComposedOf", default=[])):
            cid = c.get("@id") if isinstance(c, dict) else c
            if cid:
                pk_var_ids.append(cid)

    for file_id, part_obj in tabular_files:
        mappings = _as_list(_get(part_obj, "cdif:hasPhysicalMapping", default=[]))
        part_name = _get(part_obj, "schema:name", default=file_id)
        rs_name = re.sub(r"\.[^.]+$", "", part_name)   # strip extension
        rs_id = _sanitize_id(rs_name)
        # The RecordSet @id must differ from the source FileObject @id, or
        # JSON-LD merges the two same-@id nodes (a FileObject that also carries
        # cr:field), which breaks Croissant processing. This collides when the
        # file name has no extension to strip.
        if rs_id == file_id:
            rs_id = f"{rs_id}_records"

        # Sort mappings by cdif:index so fields come out in column order
        mappings = sorted(mappings,
                          key=lambda m: m.get("cdif:index", 0)
                          if isinstance(m, dict) else 0)

        fields = []
        var_id_to_field_id = {}   # for key/references resolution
        for mapping in mappings:
            if not isinstance(mapping, dict):
                continue

            # Resolve the linked InstanceVariable
            var_ref = _get(mapping, "cdif:formats_InstanceVariable")
            var_id = var_ref.get("@id") if isinstance(var_ref, dict) else var_ref
            var_obj = var_index.get(var_id, {}) if var_id else {}

            # Column header = the variable's name (current schema has no per-
            # mapping column label; the variable name is the column identity).
            var_name = _var_name(var_obj)
            field_label = var_name or f"col_{mapping.get('cdif:index', 0)}"
            field_id = f"{rs_id}/{_sanitize_id(field_label)}"
            if var_id:
                var_id_to_field_id[var_id] = field_id

            # Data type. Prefer the variable's logical type (intended, then its
            # own cdif:physicalDataType) over the mapping's physical storage
            # token. All are single-valued in the current schema.
            intended = _datatype_token(
                _get(var_obj, "cdi:hasIntendedDataType", "cdi:intendedDataType"))
            var_phys = _datatype_token(_get(var_obj, "cdif:physicalDataType"))
            map_phys = _datatype_token(_get(mapping, "cdif:physicalDataType"))
            cr_dtype = _map_datatype(intended or var_phys or map_phys)

            field = {
                "@type": "cr:Field",
                "@id": field_id,
                "name": field_id,
                "dataType": cr_dtype,
                "source": {
                    "fileObject": {"@id": file_id},
                    "extract": {"column": field_label},
                },
            }

            desc = _get(var_obj, "schema:description", "cdif:definition")
            if isinstance(desc, list):
                desc = desc[0] if desc else None
            if desc:
                field["description"] = desc

            equiv = _extract_equivalent_property(var_obj)
            if equiv:
                field["equivalentProperty"] = equiv

            fields.append(field)

        if not fields:
            continue

        rs = {
            "@type": "cr:RecordSet",
            "@id": rs_id,
            "name": rs_name,
            "field": fields,
        }

        # Primary key -> cr:RecordSet.key (only keys whose variables are in this file)
        key_field_ids = [var_id_to_field_id[v] for v in pk_var_ids
                         if v in var_id_to_field_id]
        if key_field_ids:
            rs["key"] = ([{"@id": fid} for fid in key_field_ids]
                         if len(key_field_ids) > 1 else {"@id": key_field_ids[0]})

        desc = _get(part_obj, "schema:description")
        if desc and desc not in ("", "default description"):
            cleaned = re.sub(r"sha256:\w+\s*;\s*", "", desc).strip()
            if cleaned:
                rs["description"] = cleaned

        record_sets.append(rs)
        if verbose:
            print(f"  RecordSet '{rs_name}' with {len(fields)} fields"
                  + (f", key={key_field_ids}" if key_field_ids else ""))

    return record_sets


# ---------------------------------------------------------------------------
# Main conversion
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# The mapping table
# ---------------------------------------------------------------------------
#
# converters/mappings/cdif-to-croissant.sssom.tsv decides which CDIF property
# becomes which Croissant property; this module reads it rather than restating
# it. The generic machinery is converters/sssom_engine.py.
#
# This direction is lossy and the table says where: 38 of its rows carry no
# target and transform `unmapped`, because Croissant has no vocabulary for
# them. Those rows exist so the loss is visible rather than discovered.

_CONVERTERS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _CONVERTERS_DIR not in sys.path:
    sys.path.insert(0, _CONVERTERS_DIR)
import sssom_engine as _engine  # noqa: E402

_MAPPINGS = os.path.join(_CONVERTERS_DIR, "mappings")


# --- the table's named transforms -----------------------------------------
#
# (value, source, rule, target) -> the Croissant value, or None to emit
# nothing. Most delegate to shapers that were already here.

def _x_text(value, cdif, rule, cr):
    got = _get(cdif, rule["subject_id"])
    if isinstance(got, list):
        got = got[0] if got else None
    if isinstance(got, dict):
        got = got.get("@value") or got.get("@id") or got.get("schema:name")
    return got if got not in (None, "", []) else None


def _x_iri(value, cdif, rule, cr):
    for item in _as_list(value):
        if isinstance(item, dict):
            got = item.get("@id") or item.get("schema:url")
        else:
            got = item
        if isinstance(got, str) and got:
            return got
    return None


def _x_date(value, cdif, rule, cr):
    return _x_text(value, cdif, rule, cr)


def _x_identifier(value, cdif, rule, cr):
    got = _extract_identifier_url(cdif)
    return got or _x_text(value, cdif, rule, cr)


def _x_agent(value, cdif, rule, cr):
    if rule["object_id"] == "sc:creator":
        return _extract_creators(cdif) or None
    got = [_convert_agent(a) for a in _as_list(value)]
    return [a for a in got if a] or None


def _x_keywords(value, cdif, rule, cr):
    return _extract_keywords(cdif) or None


def _x_license(value, cdif, rule, cr):
    return _extract_license(cdif) or None


def _x_catalog(value, cdif, rule, cr):
    """A CDIF DataCatalog node in Croissant's spelling.

    Read from either place: CDIF puts it on the catalog record, but records
    made before ConvertFromCroissant was corrected carry it at the root.
    """
    got = value
    if got is None:
        subject = cdif.get("schema:subjectOf") or {}
        if isinstance(subject, list):
            subject = subject[0] if subject else {}
        got = subject.get("schema:includedInDataCatalog") if isinstance(subject, dict) else None
    for item in _as_list(got):
        if isinstance(item, str):
            return {"@type": "sc:DataCatalog", "name": item}
        if isinstance(item, dict):
            node = {"@type": "sc:DataCatalog"}
            name = _get(item, "schema:name", "name")
            url = _get(item, "schema:url", "url", "@id")
            if name:
                node["name"] = name
            if url:
                node["url"] = url
            if len(node) > 1:
                return node
    return None


def _x_version(value, cdif, rule, cr):
    """Croissant declares version a string; CDIF allows a number."""
    got = _x_text(value, cdif, rule, cr)
    return str(got) if got not in (None, "") else None


def _x_sameas(value, cdif, rule, cr):
    """Croissant expects URLs; CDIF may carry a PropertyValue or a node."""
    urls = []
    for item in _as_list(value):
        if isinstance(item, str):
            urls.append(item)
        elif isinstance(item, dict):
            got = _get(item, "schema:url", "@id", "schema:value")
            if got:
                urls.append(got)
    if not urls:
        return None
    # Croissant takes one or many; a single value is written plain, which is
    # what its own examples do.
    return urls if len(urls) > 1 else urls[0]


def _x_funding(value, cdif, rule, cr):
    """A CDIF MonetaryGrant as the grant node Croissant carries."""
    out = []
    for item in _as_list(value):
        if not isinstance(item, dict):
            continue
        node = {}
        desc = _get(item, "schema:description")
        if desc:
            node["description"] = desc
        name = _get(item, "schema:name")
        if name:
            node["name"] = name
        funder = _get(item, "schema:funder")
        if isinstance(funder, dict):
            agent = _convert_agent(funder)
            if agent:
                node["funder"] = agent
        # A CDIF identifier may be a PropertyValue node. Croissant has no
        # shape for one, and copying it in would put CDIF's vocabulary inside
        # a Croissant document, so only a plain value travels.
        ident = _get(item, "schema:identifier")
        if isinstance(ident, dict):
            ident = _get(ident, "schema:value", "@id", "schema:name")
        if isinstance(ident, str) and ident:
            node["identifier"] = ident
        if node:
            node.setdefault("@type", "MonetaryGrant")
            out.append(node)
    return out or None


def _x_accessflag(value, cdif, rule, cr):
    """CDIF states access conditions in prose; Croissant asks a yes/no.

    Anything that names a restriction is not free access. This is the lossy
    half of a lossy pair -- the prose itself has nowhere to go.
    """
    text = " ".join(str(v) for v in _as_list(value)).lower()
    if not text:
        return None
    restricted = ("restrict", "non-public", "embargo", "closed", "licence required",
                  "license required", "authenticat", "registration")
    return not any(word in text for word in restricted)


def _x_unmapped(value, cdif, rule, cr):
    """A CDIF property Croissant has no vocabulary for.

    Returns nothing on purpose. The row exists so the table records the loss;
    without it a reader would have to infer that absence meant "not mapped"
    rather than "not present".
    """
    return None


CDIF_TO_CROISSANT = _engine.MappingSet(
    os.path.join(_MAPPINGS, "cdif-to-croissant.sssom.tsv"),
    transforms={
        "": _x_text, "text": _x_text, "iri": _x_iri, "date": _x_date,
        "identifier": _x_identifier, "agent": _x_agent, "keywords": _x_keywords,
        "funding": _x_funding, "accessflag": _x_accessflag,
        "sameas": _x_sameas, "license": _x_license, "catalog": _x_catalog,
        "versiontext": _x_version,
        "unmapped": _x_unmapped,
    },
    # Croissant's own arity. Its creator is a plain list -- it has no ordered
    # form, which is where CDIF's @list ordering is lost.
    arity={
        "creator": "array",
        "keywords": "array",
        "funding": "array",
        "sameAs": "asis",
        "distribution": "array",
        "recordSet": "array",
    },
)

DATASET_CLASSES = ("schema:Dataset",)


def convert_cdif_to_croissant(cdif, verbose=False):
    """Convert a CDIF JSON-LD dict to a Croissant JSON-LD dict.

    Returns (croissant_dict, warnings_list).
    """
    warnings = []
    cr = {}

    # -- context & conformsTo -------------------------------------------
    cr["@context"] = deepcopy(CROISSANT_CONTEXT)
    cr["@type"] = "sc:Dataset"
    cr["conformsTo"] = CROISSANT_CONFORMS_TO

    # -- discovery metadata, from the mapping table ----------------------
    # cdif-to-croissant.sssom.tsv decides these. It also records, in its 38
    # `unmapped` rows, everything Croissant has no vocabulary for -- so what
    # this conversion loses is written down rather than discovered.
    _changes = []
    CDIF_TO_CROISSANT.apply(cdif, cr, DATASET_CLASSES, _changes)

    # -- what Croissant requires and CDIF does not guarantee ---------------
    # Not correspondences: the converter deciding what to do about silence.
    name = _get(cdif, "schema:name")
    if not cr.get("name"):
        warnings.append("Missing schema:name (required by Croissant)")
    if not cr.get("description"):
        cr["description"] = name or "No description available"
        warnings.append("Missing schema:description (required by Croissant); "
                        "using name as fallback")
    ident_url = _extract_identifier_url(cdif)
    if not cr.get("url"):
        if ident_url:
            cr["url"] = ident_url
        else:
            warnings.append("Missing url (required by Croissant)")
    if not cr.get("license"):
        cr["license"] = "http://www.opengis.net/def/nil/OGC/0/missing"
        warnings.append("Missing license; using OGC nil:missing placeholder")
    if not cr.get("datePublished"):
        warnings.append("Missing datePublished (required by Croissant)")
    if not cr.get("creator"):
        warnings.append("Missing creator (required by Croissant)")
    if ident_url and not cr.get("citeAs"):
        cr["citeAs"] = ident_url
    if not cr.get("version"):
        cr["version"] = "not assigned"
    if not cr.get("dateModified"):
        _dm = _extract_date_modified(cdif)
        if _dm:
            cr["dateModified"] = _dm

    # -- distribution ---------------------------------------------------
    if verbose:
        print("Converting distribution...")
    cr_dist, tabular_files = _convert_distribution(cdif, verbose=verbose)
    if cr_dist:
        cr["distribution"] = cr_dist
    else:
        warnings.append("No distribution converted")

    # -- recordSet (from variableMeasured + physicalMapping) ------------
    var_index = _build_variable_index(cdif)

    if tabular_files and var_index:
        if verbose:
            print("Building RecordSets from physical mappings...")
        rsets = _convert_record_sets(tabular_files, var_index, cdif, verbose=verbose)
        if rsets:
            cr["recordSet"] = rsets
    elif var_index and not tabular_files:
        warnings.append("variableMeasured present but no distribution has "
                        "cdif:hasPhysicalMapping; cannot generate RecordSets")

    # -- pass through CDIF properties with no native Croissant mapping ---
    # These are preserved verbatim so the Croissant document retains the
    # full CDIF semantics.  The necessary namespace prefixes are added to
    # the @context so they resolve as proper RDF.
    _PASSTHROUGH_PROPS = [
        "prov:wasGeneratedBy",
        "prov:wasDerivedFrom",
        "dqv:hasQualityMeasurement",
        "schema:spatialCoverage",
        "schema:temporalCoverage",
        "schema:measurementTechnique",
        "schema:contributor",
        "schema:subjectOf",
    ]
    # Namespace prefixes needed for pass-through properties
    _PASSTHROUGH_PREFIXES = {
        "prov":   "http://www.w3.org/ns/prov#",
        "dqv":    "http://www.w3.org/ns/dqv#",
        "dcterms": "http://purl.org/dc/terms/",
        "spdx":   "http://spdx.org/rdf/terms#",
        "cdi":    "http://ddialliance.org/Specification/DDI-CDI/1.0/RDF/",
        "cdif":   "https://w3id.org/cdif/",
        "csvw":   "http://www.w3.org/ns/csvw#",
    }

    passed = []
    for prop in _PASSTHROUGH_PROPS:
        val = _get(cdif, prop)
        if val is not None:
            cr[prop] = val
            passed.append(prop)

    # Also pass through any remaining prefixed properties from the input
    # that we haven't already handled (best-effort preservation)
    _HANDLED_PREFIXES = {
        "schema:name", "schema:description", "schema:url", "schema:license",
        "schema:conditionsOfAccess", "schema:datePublished", "schema:creator",
        "schema:identifier", "schema:version", "schema:dateModified",
        "schema:keywords", "schema:inLanguage", "schema:sameAs",
        "schema:publisher", "schema:funding", "schema:distribution",
        "schema:variableMeasured", "schema:additionalType",
        "cdif:hasPrimaryKey",
    }
    _HANDLED_PREFIXES.update(_PASSTHROUGH_PROPS)
    _HANDLED_PREFIXES.update({"@schema", "@context", "@id", "@type"})

    for key, val in cdif.items():
        if key not in _HANDLED_PREFIXES and ":" in key and not key.startswith("@"):
            cr[key] = val
            passed.append(key)

    # Extend @context with CDIF namespace prefixes if any were used
    if passed:
        # Collect which prefixes are actually needed
        needed_prefixes = set()
        for prop in passed:
            prefix = prop.split(":")[0] if ":" in prop else None
            if prefix and prefix in _PASSTHROUGH_PREFIXES:
                needed_prefixes.add(prefix)
        # Also scan the input @context for prefixes we should carry forward
        src_ctx = cdif.get("@context", {})
        if isinstance(src_ctx, dict):
            for pfx in needed_prefixes:
                if pfx not in cr["@context"]:
                    iri = _PASSTHROUGH_PREFIXES.get(pfx) or src_ctx.get(pfx)
                    if iri:
                        cr["@context"][pfx] = iri

        if verbose:
            print(f"  Passed through CDIF properties: {', '.join(passed)}")

    return cr, warnings


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Convert CDIF JSON-LD metadata to Croissant format")
    parser.add_argument("input", help="Input CDIF JSON-LD file")
    parser.add_argument("-o", "--output",
                        help="Output Croissant JSON file (default: stdout)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Print conversion progress and warnings")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        cdif = json.load(f)

    if args.verbose:
        print(f"Input: {args.input}")

    croissant, warnings = convert_cdif_to_croissant(cdif, verbose=args.verbose)

    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)

    output_json = json.dumps(croissant, indent=2, ensure_ascii=False)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_json + "\n")
        if args.verbose:
            print(f"Written: {args.output}")
    else:
        print(output_json)


if __name__ == "__main__":
    main()
