#!/usr/bin/env python3
"""
ConvertToCroissant.py - Convert CDIF JSON-LD metadata to Croissant format.

Reads a CDIF metadata document and produces a Croissant (mlcommons.org/croissant/1.0)
JSON-LD document suitable for ML dataset discovery and loading.

Mapping summary:
  CDIF schema:DataDownload        → cr:FileObject
  CDIF archive DataDownload       → cr:FileSet with cr:includes of cr:FileObject per component
  CDIF schema:variableMeasured    → cr:RecordSet + cr:Field (when physicalMapping present)
  CDIF cdi:hasPhysicalMapping     → cr:Field.source.extract.column
  CDIF schema:propertyID / uses   → cr:Field.equivalentProperty
  CDIF cdi:role (Attribute)       → cr:Field.references (qualifies → FK analogy)

Usage:
    python ConvertToCroissant.py input.jsonld [-o output.json] [-v]
"""

import json
import sys
import argparse
import re
from copy import deepcopy


# ---------------------------------------------------------------------------
# Croissant JSON-LD context (spec Appendix 1)
# ---------------------------------------------------------------------------

CROISSANT_CONTEXT = {
    "@language": "en",
    "@vocab": "http://schema.org/",
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
    "separator": "cr:separator",
    "source": "cr:source",
    "subField": "cr:subField",
    "transform": "cr:transform",
}

CROISSANT_CONFORMS_TO = "http://mlcommons.org/croissant/1.0"

# Map CDIF / XSD data types → Croissant types (resolved via @vocab)
DATATYPE_MAP = {
    "xsd:decimal": "Float",
    "xsd:float": "Float",
    "xsd:double": "Float",
    "xsd:integer": "Integer",
    "xsd:int": "Integer",
    "xsd:long": "Integer",
    "xsd:DateTime": "Date",
    "xsd:dateTime": "Date",
    "xsd:date": "Date",
    "xsd:boolean": "Boolean",
    "xsd:string": "Text",
    "String": "Text",
    "string": "Text",
    "Text": "Text",
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
        return "Text"
    return DATATYPE_MAP.get(cdif_type, "Text")


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
    ``cdi:hasPhysicalMapping``; these feed RecordSet generation.
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
            cr_dist = _convert_simple_distribution(
                dist, di, cr_dist, content_url, enc)

    return cr_dist, tabular_files


def _convert_archive_distribution(dist, di, cr_dist, tabular_files,
                                  content_url, verbose):
    """Handle archive (zip) distribution with hasPart.

    Produces a cr:FileSet for the archive with component files nested
    inside via cr:includes.  Each component is typed as both cr:FileObject
    and sc:MediaObject, with no contentUrl (the archive FileSet owns the
    download URL).
    """
    has_parts = _as_list(_get(dist, "schema:hasPart"))
    nil_url = _is_nil_url(content_url)

    archive_name = _get(dist, "schema:name") or f"archive-{di}.zip"
    archive_id = _sanitize_id(archive_name)
    archive_sha = _extract_sha256(dist)

    # Build the FileSet object for the archive
    archive_obj = {
        "@type": ["cr:FileSet", "DataDownload"],
        "@id": archive_id,
        "name": archive_name,
        "encodingFormat": "application/zip",
    }
    if not nil_url:
        archive_obj["contentUrl"] = content_url

    desc = _get(dist, "schema:description")
    if desc:
        archive_obj["description"] = desc
    if archive_sha:
        archive_obj["sha256"] = archive_sha

    # Component files — nested inside the FileSet via "includes"
    includes = []
    for pi, part in enumerate(has_parts):
        if not isinstance(part, dict):
            continue

        part_name = _get(part, "schema:name", default=f"file-{di}-{pi}")
        part_id = _sanitize_id(part_name)

        part_enc = _get(part, "schema:encodingFormat", default="")
        if isinstance(part_enc, list):
            part_enc = part_enc[0] if part_enc else ""

        fobj = {
            "@type": ["cr:FileObject", "MediaObject"],
            "@id": part_id,
            "name": part_name,
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

        includes.append(fobj)

        # Track tabular files with physical mapping for RecordSet generation
        if _get(part, "cdi:hasPhysicalMapping"):
            tabular_files.append((part_id, part))
            if verbose:
                print(f"  Tabular file with physical mapping: {part_name}")

    if includes:
        archive_obj["includes"] = includes

    cr_dist.append(archive_obj)
    return cr_dist, tabular_files


def _convert_simple_distribution(dist, di, cr_dist, content_url, enc):
    """Handle a non-archive DataDownload."""
    dist_name = _get(dist, "schema:name")
    if not dist_name and content_url and not _is_nil_url(content_url):
        dist_name = content_url.rsplit("/", 1)[-1] or f"file-{di}"
    if not dist_name:
        dist_name = f"file-{di}"

    fobj = {
        "@type": "cr:FileObject",
        "@id": _sanitize_id(dist_name),
        "name": dist_name,
    }
    if content_url and not _is_nil_url(content_url):
        fobj["contentUrl"] = content_url
    if enc:
        fobj["encodingFormat"] = enc

    desc = _get(dist, "schema:description")
    if desc:
        fobj["description"] = desc

    cr_dist.append(fobj)
    return cr_dist


# ---------------------------------------------------------------------------
# RecordSet / Field conversion
# ---------------------------------------------------------------------------

def _build_variable_index(cdif):
    """Map variable @id → variable object from schema:variableMeasured."""
    variables = _as_list(_get(cdif, "schema:variableMeasured", default=[]))
    return {v["@id"]: v for v in variables
            if isinstance(v, dict) and v.get("@id")}


def _extract_equivalent_property(var_obj):
    """Pull an equivalentProperty URL from propertyID or cdi:uses."""
    # schema:propertyID
    for pid in _as_list(_get(var_obj, "schema:propertyID", default=[])):
        if isinstance(pid, dict):
            uri = _get(pid, "@id", "schema:url")
            if uri and uri != "missing" and uri.startswith("http"):
                return uri
        elif isinstance(pid, str) and pid != "missing" and pid.startswith("http"):
            return pid

    # cdi:uses (Concept reference)
    uses = _get(var_obj, "cdi:uses")
    if isinstance(uses, dict):
        uid = uses.get("@id")
        if uid and not uid.startswith("#"):
            return uid
    return None


def _convert_record_sets(tabular_files, var_index, verbose=False):
    """Build Croissant RecordSets from tabular files + physicalMappings."""
    record_sets = []

    for file_id, part_obj in tabular_files:
        mappings = _as_list(_get(part_obj, "cdi:hasPhysicalMapping", default=[]))
        part_name = _get(part_obj, "schema:name", default=file_id)
        rs_name = re.sub(r"\.[^.]+$", "", part_name)   # strip extension
        rs_id = _sanitize_id(rs_name)

        # Sort mappings by cdi:index so fields come out in column order
        mappings = sorted(mappings,
                          key=lambda m: m.get("cdi:index", 0)
                          if isinstance(m, dict) else 0)

        fields = []
        for mapping in mappings:
            if not isinstance(mapping, dict):
                continue

            # Resolve the linked InstanceVariable
            var_ref = _get(mapping, "cdi:formats_InstanceVariable")
            var_id = var_ref.get("@id") if isinstance(var_ref, dict) else var_ref
            var_obj = var_index.get(var_id, {}) if var_id else {}

            # Column name from mapping (= physical column header)
            col_name = _get(mapping, "schema:name", default="")
            var_name = _get(var_obj, "schema:name", default=col_name)
            field_label = col_name or var_name or f"col_{mapping.get('cdi:index', 0)}"
            field_id = f"{rs_id}/{_sanitize_id(field_label)}"

            # Data type
            phys_type = _get(mapping, "cdi:physicalDataType")
            intended = _get(var_obj, "cdi:intendedDataType")
            cr_dtype = _map_datatype(intended or phys_type)

            field = {
                "@type": "cr:Field",
                "@id": field_id,
                "name": field_id,
                "dataType": cr_dtype,
                "source": {
                    "fileObject": {"@id": file_id},
                    "extract": {"column": col_name or field_label},
                },
            }

            desc = _get(var_obj, "schema:description")
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

        desc = _get(part_obj, "schema:description")
        if desc and desc not in ("", "default description"):
            cleaned = re.sub(r"sha256:\w+\s*;\s*", "", desc).strip()
            if cleaned:
                rs["description"] = cleaned

        record_sets.append(rs)
        if verbose:
            print(f"  RecordSet '{rs_name}' with {len(fields)} fields")

    return record_sets


# ---------------------------------------------------------------------------
# Main conversion
# ---------------------------------------------------------------------------

def convert_cdif_to_croissant(cdif, verbose=False):
    """Convert a CDIF JSON-LD dict to a Croissant JSON-LD dict.

    Returns (croissant_dict, warnings_list).
    """
    warnings = []
    cr = {}

    # -- context & conformsTo -------------------------------------------
    cr["@context"] = deepcopy(CROISSANT_CONTEXT)
    cr["@type"] = "Dataset"
    cr["conformsTo"] = CROISSANT_CONFORMS_TO

    # -- discovery metadata ---------------------------------------------
    name = _get(cdif, "schema:name")
    if name:
        cr["name"] = name
    else:
        warnings.append("Missing schema:name (required by Croissant)")

    desc = _get(cdif, "schema:description")
    if desc:
        cr["description"] = desc
    else:
        cr["description"] = name or "No description available"
        warnings.append("Missing schema:description (required by Croissant); "
                        "using name as fallback")

    url = _get(cdif, "schema:url")
    ident_url = _extract_identifier_url(cdif)
    if url and url != "":
        cr["url"] = url
    elif ident_url:
        cr["url"] = ident_url
    else:
        warnings.append("Missing url (required by Croissant)")

    lic = _extract_license(cdif)
    if lic:
        cr["license"] = lic
    else:
        cr["license"] = "http://www.opengis.net/def/nil/OGC/0/missing"
        warnings.append("Missing license; using OGC nil:missing placeholder")

    dp = _get(cdif, "schema:datePublished")
    if dp:
        cr["datePublished"] = dp
    else:
        warnings.append("Missing datePublished (required by Croissant)")

    creators = _extract_creators(cdif)
    if creators:
        cr["creator"] = creators
    else:
        warnings.append("Missing creator (required by Croissant)")

    # citeAs from DOI / identifier
    if ident_url:
        cr["citeAs"] = ident_url

    # recommended properties
    ver = _get(cdif, "schema:version")
    if ver:
        cr["version"] = str(ver)

    dm = _extract_date_modified(cdif)
    if dm:
        cr["dateModified"] = dm

    kw = _extract_keywords(cdif)
    if kw:
        cr["keywords"] = kw

    lang = _get(cdif, "schema:inLanguage")
    if lang:
        cr["inLanguage"] = lang

    same = _get(cdif, "schema:sameAs")
    if same:
        cr["sameAs"] = same

    # publisher
    pub = _get(cdif, "schema:publisher")
    if pub:
        p = _convert_agent(pub) if isinstance(pub, dict) else None
        if p:
            cr["publisher"] = p

    # funding (Croissant recommends it and schema.org supports it)
    funding = _get(cdif, "schema:funding")
    if funding:
        cr_funding = []
        for f in _as_list(funding):
            if isinstance(f, dict):
                fd = {}
                fd_desc = _get(f, "schema:description")
                if fd_desc:
                    fd["description"] = fd_desc
                fd_name = _get(f, "schema:name")
                if fd_name:
                    fd["name"] = fd_name
                funder = _get(f, "schema:funder")
                if funder:
                    fa = _convert_agent(funder) if isinstance(funder, dict) else None
                    if fa:
                        fd["funder"] = fa
                if fd:
                    fd["@type"] = "MonetaryGrant"
                    cr_funding.append(fd)
        if cr_funding:
            cr["funding"] = cr_funding

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
        rsets = _convert_record_sets(tabular_files, var_index, verbose=verbose)
        if rsets:
            cr["recordSet"] = rsets
    elif var_index and not tabular_files:
        warnings.append("variableMeasured present but no distribution has "
                        "cdi:hasPhysicalMapping; cannot generate RecordSets")

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
