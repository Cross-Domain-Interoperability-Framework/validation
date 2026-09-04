#!/usr/bin/env python3
"""
dcat_to_cdif.py - Convert DCAT JSON-LD metadata to CDIF schema.org format.

Reads a DCAT catalog or individual dataset records in JSON-LD and converts
them to CDIF-conformant schema.org JSON-LD, following the property mapping
defined in the CDIF DCAT implementation guide:
https://cross-domain-interoperability-framework.github.io/cdifbook/metadata/dcat.html

Supports:
- DCAT catalogs with nested dcat:Dataset entries (extracts and converts each)
- Individual dcat:Dataset or dcat:Distribution records
- FOAF agents (Person, Organization) to schema:Person/Organization
- prov:qualifiedAttribution to schema:contributor with roles
- Spatial/temporal coverage (dcterms:spatial/temporal)
- Distribution mapping (dcat:Distribution to schema:DataDownload)

Unmapped DCAT properties are preserved in the output (open-world assumption).

Usage:
    # Convert all datasets from a DCAT catalog
    python DCAT/dcat_to_cdif.py catalog.jsonld --output ./examples

    # Convert and validate against cdifCore
    python DCAT/dcat_to_cdif.py catalog.jsonld --output ./examples --validate

    # Convert a single dataset record
    python DCAT/dcat_to_cdif.py dataset.jsonld --output ./examples

    # List datasets in a catalog without converting
    python DCAT/dcat_to_cdif.py catalog.jsonld --list

    # Select specific datasets by index
    python DCAT/dcat_to_cdif.py catalog.jsonld --output ./examples --select 0,3,5
"""

import json
import sys
import os
import re
import argparse
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


# ---------------------------------------------------------------------------
# DCAT → schema.org property mapping
# ---------------------------------------------------------------------------

CDIF_CONTEXT = {
    "schema": "http://schema.org/",
    "dcterms": "http://purl.org/dc/terms/",
    "dcat": "http://www.w3.org/ns/dcat#",
    "prov": "http://www.w3.org/ns/prov#",
}


def _split_iri(iri):
    """(namespace, local name) for an absolute IRI, or (iri, "") if indivisible."""
    for sep in ("#", "/"):
        idx = iri.rfind(sep)
        if idx > 0 and idx < len(iri) - 1:
            local = iri[idx + 1:]
            if local and not local[0].isdigit() and ":" not in local:
                return iri[:idx + 1], local
    return iri, ""


# Conventional prefixes, so a minted one does not end up as "rdfschema" for a
# namespace the world already calls "rdfs".
_WELL_KNOWN_PREFIXES = {
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#": "rdf",
    "http://www.w3.org/2000/01/rdf-schema#": "rdfs",
    "http://www.w3.org/2002/07/owl#": "owl",
    "http://www.w3.org/2004/02/skos/core#": "skos",
    "http://www.w3.org/2001/XMLSchema#": "xsd",
    "http://xmlns.com/foaf/0.1/": "foaf",
    "http://www.w3.org/2006/vcard/ns#": "vcard",
    "http://www.w3.org/ns/adms#": "adms",
    "http://www.w3.org/ns/locn#": "locn",
    "http://www.w3.org/ns/dqv#": "dqv",
    "http://www.w3.org/2006/time#": "time",
    "http://spdx.org/rdf/terms#": "spdx",
    "http://www.opengis.net/ont/geosparql#": "geosparql",
}


# The reverse lookup, for CURIEs the source used but did not declare.
_NAMESPACE_FOR_PREFIX = {p: ns for ns, p in _WELL_KNOWN_PREFIXES.items()}
_NAMESPACE_FOR_PREFIX.update({
    "dct": "http://purl.org/dc/terms/",
    "dcterms": "http://purl.org/dc/terms/",
    "dcat": "http://www.w3.org/ns/dcat#",
    "schema": "http://schema.org/",
    "prov": "http://www.w3.org/ns/prov#",
    "dqv": "http://www.w3.org/ns/dqv#",
    "spdx": "http://spdx.org/rdf/terms#",
})


def _prefix_for(context, namespace):
    """A prefix bound to `namespace` in `context`, reusing or minting one."""
    for prefix, value in context.items():
        if value == namespace:
            return prefix
    known = _WELL_KNOWN_PREFIXES.get(namespace)
    if known and known not in context:
        context[known] = namespace
        return known
    # Derive something readable from the last meaningful path segment.
    stem = namespace.rstrip("#/").rsplit("/", 1)[-1]
    base = "".join(ch for ch in stem if ch.isalnum()).lower() or "ext"
    if base[0].isdigit():
        base = "x" + base
    prefix, n = base, 1
    while prefix in context:
        n += 1
        prefix = "%s%d" % (base, n)
    context[prefix] = namespace
    return prefix


def _prefix_keys(key, value, context, depth=0):
    """(key, value) with every absolute-IRI property key turned into a CURIE.

    An absolute IRI as a JSON-LD property key breaks framing: the part before
    the first colon is read as a prefix. Minting a prefix keeps the term -- these
    are real vocabulary properties from DCAT-AP extensions -- rather than
    dropping content to make the record parse.
    """
    if key.startswith(("http://", "https://")):
        ns, local = _split_iri(key)
        if local:
            key = "%s:%s" % (_prefix_for(context, ns), local)
    elif ":" in key and not key.startswith("@"):
        # A CURIE whose prefix the record does not declare is worse than an
        # absolute IRI: jsonld cannot resolve "skos" and raises "Absolute IRI
        # confused with prefix", so the record does not frame and never reaches
        # validation. Declare the namespace when we know it.
        prefix = key.split(":", 1)[0]
        if prefix and prefix not in context:
            ns = _NAMESPACE_FOR_PREFIX.get(prefix)
            if ns:
                context[prefix] = ns
    if depth < 12:
        if isinstance(value, dict):
            out = {}
            for k2, v2 in value.items():
                nk, nv = _prefix_keys(k2, v2, context, depth + 1)
                out[nk] = nv
            value = out
        elif isinstance(value, list):
            value = [_prefix_keys("x", item, context, depth + 1)[1]
                     for item in value]
    return key, value


def _get_str(val):
    """Extract a string value from a JSON-LD value (plain, @value, or @id).

    Returns None for a dict carrying neither, rather than str(val). The old
    fallback turned the `{}` defaults that callers pass in -- dist.get(k, {}) --
    into the literal string "{}", which is truthy, so it sailed through the
    `if url:` guards and was written out as a value. 163 distributions across
    108 records ended up with "schema:contentUrl": "{}".
    """
    if val is None:
        return None
    if isinstance(val, dict):
        for key in ("@value", "@id"):
            if key in val:
                return str(val[key])
        return None
    if isinstance(val, (list, tuple)):
        for item in val:
            got = _get_str(item)
            if got:
                return got
        return None
    return str(val)


# ---------------------------------------------------------------------------
# Dataset discovery
# ---------------------------------------------------------------------------

def find_datasets(obj, results=None):
    """Recursively find all dcat:Dataset nodes in a JSON-LD structure."""
    if results is None:
        results = []
    if isinstance(obj, dict):
        t = obj.get("@type", "")
        if isinstance(t, list):
            if "dcat:Dataset" in t:
                results.append(obj)
        elif t == "dcat:Dataset":
            results.append(obj)
        for v in obj.values():
            find_datasets(v, results)
    elif isinstance(obj, list):
        for item in obj:
            find_datasets(item, results)
    return results


# ---------------------------------------------------------------------------
# Agent conversion
# ---------------------------------------------------------------------------

def convert_agent(agent):
    """Convert a FOAF/DCAT agent to schema:Person or schema:Organization."""
    if isinstance(agent, list):
        for item in agent:
            got = convert_agent(item)
            if got:
                return got
        return None
    if not isinstance(agent, dict):
        if isinstance(agent, str) and agent.startswith("http"):
            return {"@id": agent}
        return None
    # rdflib compacts an RDF collection to {"@list": [...]}. Taking that dict at
    # face value emitted {"@list": [...]} where an Organization belonged.
    if "@list" in agent:
        return convert_agent(agent["@list"])

    t = agent.get("@type", "")
    result = {}

    # Determine type
    if isinstance(t, list):
        t = " ".join(t)
    if "Person" in t:
        result["@type"] = ["schema:Person"]
    else:
        result["@type"] = ["schema:Organization"]

    # Name
    for name_key in ("foaf:name", "rdfs:label", "schema:name", "vcard:fn"):
        name = agent.get(name_key)
        if name:
            result["schema:name"] = _get_str(name)
            break

    # Identifier / @id
    aid = agent.get("@id")
    if aid and aid.startswith("http"):
        result["@id"] = aid

    # Email
    mbox = agent.get("foaf:mbox")
    if mbox:
        email = _get_str(mbox).replace("mailto:", "")
        result["schema:contactPoint"] = {
            "@type": ["schema:ContactPoint"],
            "schema:email": email,
        }

    # Homepage
    homepage = agent.get("foaf:homepage")
    if homepage:
        result["schema:url"] = _get_str(homepage)

    return result if result.get("schema:name") or result.get("@id") else None


def convert_qualified_attribution(attr):
    """Convert prov:qualifiedAttribution to schema:contributor with role."""
    if not isinstance(attr, dict):
        return None

    agent = attr.get("prov:agent")
    role = attr.get("dcat:hadRole")

    converted_agent = convert_agent(agent) if isinstance(agent, dict) else None
    if not converted_agent and isinstance(agent, str):
        converted_agent = {"@id": agent}

    if not converted_agent:
        return None

    role_name = None
    if isinstance(role, dict):
        role_name = _get_str(role.get("skos:prefLabel") or role.get("rdfs:label")
                             or role.get("@id"))
    elif role:
        role_name = _get_str(role)

    if role_name:
        return {
            "@type": ["schema:Role"],
            "schema:roleName": role_name,
            "schema:contributor": converted_agent,
        }
    return converted_agent


# ---------------------------------------------------------------------------
# Distribution conversion
# ---------------------------------------------------------------------------

def convert_distribution(dist):
    """Convert a dcat:Distribution to schema:DataDownload."""
    if not isinstance(dist, dict):
        return None

    result = {"@type": ["schema:DataDownload"]}

    # Content URL
    download = dist.get("dcat:downloadURL", {})
    access = dist.get("dcat:accessURL", {})
    url = _get_str(download) or _get_str(access)
    if url:
        result["schema:contentUrl"] = url

    # Encoding format
    media = dist.get("dcat:mediaType") or dist.get("dcterms:format")
    if media:
        result["schema:encodingFormat"] = [_get_str(media)]

    # Name / title
    title = dist.get("dcterms:title")
    if title:
        result["schema:name"] = _get_str(title)

    # Description
    desc = dist.get("dcterms:description")
    if desc:
        result["schema:description"] = _get_str(desc)

    # Byte size
    size = dist.get("dcat:byteSize")
    if size:
        result["schema:contentSize"] = _get_str(size)

    # ConformsTo
    conforms = dist.get("dcterms:conformsTo")
    if conforms:
        if isinstance(conforms, dict):
            result["dcterms:conformsTo"] = [{"@id": conforms.get("@id", _get_str(conforms))}]
        elif isinstance(conforms, str):
            result["dcterms:conformsTo"] = [{"@id": conforms}]

    return result


# ---------------------------------------------------------------------------
# Spatial / temporal coverage
# ---------------------------------------------------------------------------

def convert_spatial(spatial):
    """Convert dcterms:spatial to schema:spatialCoverage."""
    if not isinstance(spatial, dict):
        if isinstance(spatial, str):
            return {"@type": ["schema:Place"], "schema:name": spatial}
        return None

    place = {"@type": ["schema:Place"]}

    # Name / label
    label = spatial.get("rdfs:label") or spatial.get("locn:geographicName")
    if label:
        place["schema:name"] = _get_str(label)

    # Bounding box (WKT)
    bbox = spatial.get("dcat:bbox")
    if bbox:
        wkt = _get_str(bbox)
        place["schema:geo"] = {
            "@type": ["schema:GeoShape"],
            "schema:box": wkt,
        }

    # Point geometry
    geom = spatial.get("locn:geometry")
    if geom and not bbox:
        place["schema:geo"] = {
            "@type": ["schema:GeoShape"],
            "schema:polygon": _get_str(geom),
        }

    return place if len(place) > 1 else None


def convert_temporal(temporal):
    """Convert dcterms:temporal to schema:temporalCoverage string."""
    if not isinstance(temporal, dict):
        return _get_str(temporal) if temporal else None

    start = temporal.get("dcat:startDate") or temporal.get("schema:startDate")
    end = temporal.get("dcat:endDate") or temporal.get("schema:endDate")

    if start and end:
        return f"{_get_str(start)}/{_get_str(end)}"
    elif start:
        return f"{_get_str(start)}/.."
    elif end:
        return f"../{_get_str(end)}"
    return None


# ---------------------------------------------------------------------------
# Main conversion
# ---------------------------------------------------------------------------

def convert_dcat_to_cdif(ds, catalog_name="", catalog_url="", profile="core",
                         detect=True):
    """Convert a dcat:Dataset to CDIF schema.org JSON-LD.

    Args:
        ds: The dcat:Dataset dict.
        catalog_name: Name of the source catalog (for subjectOf).
        catalog_url: URL of the source catalog.
        profile: 'core' or 'discovery'.

    Returns:
        Converted dict.
    """
    changes = []
    doc = {"@context": dict(CDIF_CONTEXT)}

    # @id
    dsid = ds.get("@id", "")
    # Expand known prefixes
    for prefix in ("psdiDcat:", "dcat:"):
        if dsid.startswith(prefix):
            dsid = f"http://metadata.psdi.ac.uk/psdi-dcat/{dsid[len(prefix):]}"
    doc["@id"] = dsid
    doc["@type"] = ["schema:Dataset"]

    # --- Mapped properties ---

    # dcterms:title → schema:name
    title = ds.get("dcterms:title")
    doc["schema:name"] = _get_str(title) if title else "Untitled"
    changes.append("dcterms:title to schema:name")

    # dcterms:description → schema:description
    desc = ds.get("dcterms:description")
    if desc:
        doc["schema:description"] = _get_str(desc)
        changes.append("dcterms:description to schema:description")

    # dcterms:identifier → schema:identifier
    ident = ds.get("dcterms:identifier")
    if ident:
        doc["schema:identifier"] = _get_str(ident)

    # dcterms:modified → schema:dateModified
    modified = ds.get("dcterms:modified")
    if modified:
        doc["schema:dateModified"] = _get_str(modified)
        changes.append("dcterms:modified to schema:dateModified")

    # dcterms:issued → schema:datePublished
    issued = ds.get("dcterms:issued")
    if issued:
        val = _get_str(issued)
        doc["schema:datePublished"] = val
        if "schema:dateModified" not in doc:
            doc["schema:dateModified"] = val
            changes.append("dcterms:issued to schema:dateModified (no dcterms:modified)")

    if "schema:dateModified" not in doc:
        doc["schema:dateModified"] = "2025-01-01"
        changes.append("schema:dateModified set to placeholder (no date in source)")

    # dcat:landingPage → schema:url
    landing = ds.get("dcat:landingPage", {})
    lurl = landing.get("@id") if isinstance(landing, dict) else _get_str(landing)
    if lurl:
        doc["schema:url"] = lurl
        changes.append("dcat:landingPage to schema:url")

    # dcterms:license → schema:license
    lic = ds.get("dcterms:license")
    if lic:
        lic_val = lic.get("@id", _get_str(lic)) if isinstance(lic, dict) else _get_str(lic)
        doc["schema:license"] = [lic_val]
        changes.append("dcterms:license to schema:license")

    # dcterms:accessRights → schema:conditionsOfAccess
    access_rights = ds.get("dcterms:accessRights")
    if access_rights:
        ar_val = (access_rights.get("@id", _get_str(access_rights))
                  if isinstance(access_rights, dict) else _get_str(access_rights))
        doc["schema:conditionsOfAccess"] = [ar_val]
        changes.append("dcterms:accessRights to schema:conditionsOfAccess")

    # dcat:keyword → schema:keywords
    keywords = ds.get("dcat:keyword", [])
    if not isinstance(keywords, list):
        keywords = [keywords]
    if keywords:
        doc["schema:keywords"] = [_get_str(k) for k in keywords if k]
        changes.append("dcat:keyword to schema:keywords")

    # dcterms:creator → schema:creator
    creator = ds.get("dcterms:creator")
    if creator:
        creators = creator if isinstance(creator, list) else [creator]
        converted = [convert_agent(c) for c in creators]
        converted = [c for c in converted if c]
        if converted:
            doc["schema:creator"] = {"@list": converted}
            changes.append("dcterms:creator to schema:creator")

    # dcterms:publisher / dcat:publisher → schema:publisher
    pub = ds.get("dcterms:publisher") or ds.get("dcat:publisher")
    if pub:
        p = convert_agent(pub)
        if p:
            doc["schema:publisher"] = p
            changes.append("dcterms:publisher to schema:publisher")

    # prov:qualifiedAttribution → schema:contributor
    attrs = ds.get("prov:qualifiedAttribution", [])
    if not isinstance(attrs, list):
        attrs = [attrs]
    contributors = [convert_qualified_attribution(a) for a in attrs]
    contributors = [c for c in contributors if c]
    if contributors:
        doc["schema:contributor"] = contributors
        changes.append("prov:qualifiedAttribution to schema:contributor")

    # dcat:contactPoint → schema:provider (best available mapping)
    contact = ds.get("dcat:contactPoint")
    if contact and isinstance(contact, dict):
        # vcard:Kind → simple contact
        fn = contact.get("vcard:fn") or contact.get("vcard:hasName")
        email = contact.get("vcard:hasEmail")
        if fn or email:
            provider = {"@type": ["schema:Organization"]}
            if fn:
                provider["schema:name"] = _get_str(fn)
            if email:
                email_str = _get_str(email).replace("mailto:", "")
                provider["schema:contactPoint"] = {
                    "@type": ["schema:ContactPoint"],
                    "schema:email": email_str,
                }
            if provider.get("schema:name"):
                doc.setdefault("schema:provider", []).append(provider)
            changes.append("dcat:contactPoint to schema:provider")

    # dcat:Distribution → schema:distribution (DataDownload)
    dists = ds.get("dcat:Distribution", ds.get("dcat:distribution", []))
    if not isinstance(dists, list):
        dists = [dists]
    converted_dists = [convert_distribution(dd) for dd in dists if isinstance(dd, dict)]
    converted_dists = [dd for dd in converted_dists if dd]
    if converted_dists:
        doc["schema:distribution"] = converted_dists
        changes.append("dcat:Distribution to schema:DataDownload")

    # dcterms:spatial → schema:spatialCoverage
    spatial = ds.get("dcterms:spatial")
    if spatial:
        items = spatial if isinstance(spatial, list) else [spatial]
        converted_sc = [convert_spatial(s) for s in items]
        converted_sc = [s for s in converted_sc if s]
        if converted_sc:
            doc["schema:spatialCoverage"] = converted_sc
            changes.append("dcterms:spatial to schema:spatialCoverage")

    # dcterms:temporal → schema:temporalCoverage
    temporal = ds.get("dcterms:temporal")
    if temporal:
        items = temporal if isinstance(temporal, list) else [temporal]
        converted_tc = [convert_temporal(t) for t in items]
        converted_tc = [t for t in converted_tc if t]
        if converted_tc:
            doc["schema:temporalCoverage"] = converted_tc
            changes.append("dcterms:temporal to schema:temporalCoverage")

    # dcat:version → schema:version
    ver = ds.get("dcat:version") or ds.get("owl:versionInfo")
    if ver:
        doc["schema:version"] = _get_str(ver)

    # --- Preserve unmapped DCAT properties (open world) ---
    _MAPPED_KEYS = {
        "@context", "@type", "@id",
        "dcterms:title", "dcterms:description", "dcterms:identifier",
        "dcterms:modified", "dcterms:issued", "dcterms:license",
        "dcterms:accessRights", "dcterms:creator", "dcterms:publisher",
        "dcterms:spatial", "dcterms:temporal",
        "dcat:landingPage", "dcat:keyword", "dcat:Distribution",
        "dcat:distribution", "dcat:contactPoint", "dcat:publisher",
        "dcat:version", "prov:qualifiedAttribution",
        "rdfs:label", "owl:versionInfo",
    }
    for k, v in ds.items():
        if k in _MAPPED_KEYS or k in doc:
            continue
        # Rewrite absolute-IRI keys at EVERY depth, not just this one. The
        # passed-through value carries whole sub-objects (qualifiedRelation,
        # provenance, sample), and their nested keys break framing just as
        # readily as a top-level one.
        key, value = _prefix_keys(k, v, doc["@context"])
        doc[key] = value

    # --- Determine profile ---
    has_spatial = "schema:spatialCoverage" in doc
    has_temporal = "schema:temporalCoverage" in doc
    has_variables = "schema:variableMeasured" in doc
    actual_profile = ("discovery" if (has_spatial or has_temporal or has_variables)
                      else profile)

    # CDIF requires licence / access-conditions information for FAIR reuse, and
    # a silent omission cannot be told from an oversight. Say it is knowably
    # absent instead.
    if not doc.get("schema:license"):
        doc["schema:license"] = [{"@id": "http://www.opengis.net/def/nil/OGC/0/missing"}]

    # --- subjectOf ---
    # 1.1 is the current series. These are only the fallback: detect_conformance
    # overrides them below from the record's actual content.
    conformsTo = [{"@id": "https://w3id.org/cdif/core/1.1"}]
    if actual_profile == "discovery":
        conformsTo.append({"@id": "https://w3id.org/cdif/discovery/1.1"})

    doc["schema:subjectOf"] = {
        "@type": ["schema:Dataset"],
        "schema:additionalType": [{"@id": "dcat:CatalogRecord"}],
        "@id": (dsid + "#metadata") if dsid else "#metadata",
        "schema:name": f"Metadata record for: {doc['schema:name'][:120]}",
        "schema:about": {"@id": dsid},
        "dcterms:conformsTo": conformsTo,
        "schema:includedInDataCatalog": {
            "@type": ["schema:DataCatalog"],
            "schema:name": catalog_name or "Unknown Catalog",
            "schema:url": catalog_url or "",
        },
        "schema:description": (
            f"Converted from DCAT to CDIF {actual_profile} profile by "
            f"dcat_to_cdif.py. Mappings applied: {'; '.join(changes)}. "
            f"Unmapped DCAT properties preserved (open world)."
        ),
    }

    # Derive dcterms:conformsTo from the record's actual content (overrides the
    # built-in default), preserving any non-cdif domain claims.
    if detect and _HAVE_DETECT:
        try:
            uris = detect_conformance(doc)
        except Exception as exc:
            # Was a bare `pass`, which hid a broken detection as a record that
            # simply kept the fallback conformsTo -- indistinguishable from a
            # record whose content genuinely matched nothing.
            print(f"  WARNING: detect_conformance failed ({exc}); keeping the "
                  "fallback conformsTo", file=sys.stderr)
        else:
            if uris:
                apply_conformance(doc, uris)
            else:
                # Nothing detected: the content does not meet even core. Keeping
                # the built-in claim here is what made fragments look conformant,
                # so drop it -- a record that conforms to nothing declares
                # nothing, and the caller can tell the two apart.
                doc["schema:subjectOf"].pop("dcterms:conformsTo", None)

    return doc


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Convert DCAT JSON-LD to CDIF schema.org format")
    parser.add_argument("input", help="Input DCAT JSON-LD file")
    parser.add_argument("--output", "-o", type=str, default=".",
                        help="Output directory (default: current dir)")
    parser.add_argument("--catalog-name", type=str, default="",
                        help="Name of the source catalog")
    parser.add_argument("--catalog-url", type=str, default="",
                        help="URL of the source catalog")
    parser.add_argument("--profile", type=str, choices=["core", "discovery"],
                        default="core",
                        help="Target CDIF profile (default: core; auto-upgrades to discovery if spatial/temporal present)")
    parser.add_argument("--list", action="store_true",
                        help="List datasets without converting")
    parser.add_argument("--select", type=str, default=None,
                        help="Comma-separated indices to convert (default: all)")
    parser.add_argument("--validate", action="store_true",
                        help="Validate output against CDIF schema")
    parser.add_argument("--static-conformance", action="store_true",
                        help="Use the built-in conformsTo instead of deriving it "
                             "from content via detect_conformance")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    # Load input
    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Find datasets
    if isinstance(data, dict) and data.get("@type") == "dcat:Dataset":
        datasets = [data]
    else:
        datasets = find_datasets(data)

    if not datasets:
        print("No dcat:Dataset records found.")
        return 1

    print(f"Found {len(datasets)} dcat:Dataset record(s)")

    if args.list:
        for i, ds in enumerate(datasets):
            title = _get_str(ds.get("dcterms:title", ds.get("@id", "?")))
            print(f"  [{i}] {title[:70]}")
        return 0

    # Select
    if args.select:
        indices = [int(x.strip()) for x in args.select.split(",")]
    else:
        indices = list(range(len(datasets)))

    os.makedirs(args.output, exist_ok=True)

    # Convert
    for i in indices:
        if i >= len(datasets):
            print(f"  [{i}] SKIP (out of range)")
            continue

        ds = datasets[i]
        title = _get_str(ds.get("dcterms:title", "unknown"))

        converted = convert_dcat_to_cdif(
            ds,
            catalog_name=args.catalog_name,
            catalog_url=args.catalog_url,
            profile=args.profile,
            detect=not args.static_conformance,
        )

        # Derive filename
        safe = re.sub(r"[^a-z0-9-]", "", title[:40].lower().replace(" ", "-"))
        filename = f"dcat-{safe}.jsonld"
        outpath = os.path.join(args.output, filename)

        with open(outpath, "w", encoding="utf-8") as f:
            json.dump(converted, f, indent=2, ensure_ascii=False)

        profile_used = "discovery" if "https://w3id.org/cdif/discovery/1.1" in str(
            converted.get("schema:subjectOf", {}).get("dcterms:conformsTo", [])
        ) else "core"
        print(f"  [{i}] {profile_used:9s} {filename}: {title[:50]}")

    # Validate if requested
    if args.validate:
        try:
            from jsonschema import Draft202012Validator

            bb_dir = os.environ.get(
                "CDIF_BB_DIR",
                os.path.join(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "..", "metadataBuildingBlocks", "_sources",
                ),
            )
            core_schema = json.load(open(
                os.path.join(bb_dir, "cdifProperties/cdifCore/resolvedSchema.json"),
                encoding="utf-8",
            ))

            print("\nValidation:")
            for i in indices:
                if i >= len(datasets):
                    continue
                title = _get_str(datasets[i].get("dcterms:title", "unknown"))
                safe = re.sub(r"[^a-z0-9-]", "", title[:40].lower().replace(" ", "-"))
                outpath = os.path.join(args.output, f"dcat-{safe}.jsonld")
                if os.path.exists(outpath):
                    doc = json.load(open(outpath, encoding="utf-8"))
                    errors = list(Draft202012Validator(core_schema).iter_errors(doc))
                    status = "PASS" if not errors else f"FAIL({len(errors)})"
                    print(f"  {status:8s} dcat-{safe}.jsonld")
                    if args.verbose:
                        for e in errors[:3]:
                            p = "/".join(str(x) for x in e.absolute_path) or "(root)"
                            print(f"           {p}: {e.message[:120]}")
        except ImportError:
            print("  (jsonschema not installed, skipping validation)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
