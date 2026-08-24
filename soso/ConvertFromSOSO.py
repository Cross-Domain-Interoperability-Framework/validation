#!/usr/bin/env python3
"""ConvertFromSOSO.py — ESIP Science-on-Schema.org JSON-LD -> CDIF core+discovery.

Converts an ESIP Science-on-Schema.org (SOSO) ``schema:Dataset`` record (bare
schema.org terms via ``@vocab``) into a CDIF Discovery-profile JSON-LD document
(``schema:``-prefixed, with the required ``schema:subjectOf`` catalog record that
declares ``dcterms:conformsTo`` the CDIF core/discovery profiles).

Both are schema.org profiles, so this is structural alignment plus supplying the
CDIF-required scaffolding SOSO does not carry:

  * property names prefixed with ``schema:`` (unknown names -> ``unk:``);
    ``@type`` values normalized to arrays with the ``schema:`` prefix.
  * ``@context`` rewritten to CDIF prefix declarations
    (``schema``/``dcterms``/``dcat``/``prov``, canonical ``http://schema.org/``),
    preserving any extra prefixes the source used.
  * CDIF-required fields ensured where derivable: ``@id`` (from ``url``),
    ``schema:identifier`` (from ``@id``), ``schema:dateModified`` (falls back to
    ``datePublished``/``dateCreated``). Fields that cannot be derived (e.g.
    ``license`` when the source has none) are reported, not fabricated.
  * ``schema:creator`` wrapped in a JSON-LD ``@list`` (author order); ``author``
    folded into ``creator``; Person names synthesized from given/family names.
  * a ``schema:subjectOf`` catalog record is added, typed ``schema:Dataset`` +
    ``dcat:CatalogRecord`` (additionalType), pointing at the dataset ``@id`` via
    ``schema:about`` and declaring ``dcterms:conformsTo`` core/1.1 (+ discovery/1.1).

This is the inverse of ConvertToSOSO.py. It reuses the SOSO->CDIF logic
originally written for geocodes_harvester.py.

Mapping reference: doc-corediscovery/documents/CDIF-Discovery-vs-SOSO-comparison.md
and ESIPFed/science-on-schema.org issue #283.

Usage:
    python ConvertFromSOSO.py input-soso.json -o output-cdif.json [-v]
                              [--profile core|discovery] [--source "Publisher"]
"""

import argparse
import copy
import json
import sys

CDIF_CONTEXT = {
    "schema": "http://schema.org/",
    "dcterms": "http://purl.org/dc/terms/",
    "dcat": "http://www.w3.org/ns/dcat#",
    "prov": "http://www.w3.org/ns/prov#",
}

UNKNOWN_NS = "https://ex.org/unknown/"
UNKNOWN_PREFIX = "unk"

CORE_URI = "https://w3id.org/cdif/core/1.1"
DISCOVERY_URI = "https://w3id.org/cdif/discovery/1.1"

# schema.org property names to prefix with schema:
SCHEMA_PROPS = {
    "name", "description", "identifier", "url", "sameAs", "version",
    "dateModified", "datePublished", "dateCreated", "license", "keywords",
    "creator", "author", "publisher", "provider", "funder", "funding",
    "distribution", "spatialCoverage", "temporalCoverage", "variableMeasured",
    "measurementTechnique", "measurementMethod", "citation",
    "isAccessibleForFree", "inLanguage", "includedInDataCatalog",
    "additionalType", "alternateName", "abstract", "encodingFormat",
    "contentUrl", "contentSize", "about", "givenName", "familyName",
    "affiliation", "email", "telephone", "contactPoint", "contactType",
    "address", "geo", "latitude", "longitude", "box", "polygon", "elevation",
    "additionalProperty", "propertyID", "value", "unitText", "unitCode",
    "minValue", "maxValue", "isBasedOn", "hasPart", "isPartOf", "mainEntity",
    "subjectOf", "creativeWorkStatus", "thumbnailUrl", "audience", "size",
    "conditionsOfAccess", "comment", "roleName", "contributor",
    "locationCreated", "fileFormat", "usageInfo", "potentialAction",
    "sdDatePublished", "maintainer", "serviceType", "termsOfService",
    "urlTemplate", "httpMethod", "relatedLink", "temporal", "spatial",
    "addressCountry", "addressLocality", "addressRegion", "availableLanguage",
    "caption", "commentCount", "disambiguatingDescription", "image",
    "inDefinedTermSet", "termCode", "parentOrganization", "postalCode",
    "streetAddress",
    # schema.org Action / provenance properties (open-world pass-through so
    # provenance content beyond core+discovery round-trips as schema:, not unk:)
    "agent", "object", "result", "instrument", "participant", "location",
    "startTime", "endTime", "actionStatus", "actionProcess", "error", "target",
    "step", "position", "startDate", "endDate", "category",
}

# schema.org type names
SCHEMA_TYPES = {
    "Person", "Organization", "Place", "GeoShape", "GeoCoordinates",
    "PropertyValue", "CreativeWork", "DataDownload", "DataCatalog",
    "ContactPoint", "MonetaryGrant", "FundingAgency", "ResearchProject",
    "DigitalDocument", "Dataset", "Role", "DefinedTerm", "QuantitativeValue",
    "PostalAddress", "ImageObject", "WebAPI", "SearchAction", "EntryPoint",
    "Action", "Collection", "MediaObject", "SoftwareApplication",
    "SoftwareSourceCode", "Product", "DefinedTermSet",
}


def _prefix_keys(obj, depth=0, assumed=None, unknown=None):
    """Recursively prefix unprefixed property names: schema.org names -> schema:,
    everything else unprefixed -> unk: (https://ex.org/unknown/)."""
    if depth > 25:
        return obj
    if isinstance(obj, list):
        return [_prefix_keys(i, depth + 1, assumed, unknown) for i in obj]
    if not isinstance(obj, dict):
        return obj
    if assumed is None:
        assumed = set()
    if unknown is None:
        unknown = set()
    result = {}
    for key, value in obj.items():
        if key == "@context":
            result[key] = value  # prefix declarations are not properties
            continue
        new_key = key
        if not key.startswith("@") and ":" not in key and not key.startswith("http"):
            if key in SCHEMA_PROPS:
                new_key = "schema:" + key
            elif key in SCHEMA_TYPES:
                new_key = "schema:" + key
                assumed.add(key)
            else:
                new_key = UNKNOWN_PREFIX + ":" + key
                unknown.add(key)
        result[new_key] = _prefix_keys(value, depth + 1, assumed, unknown)
    return result


def _fix_types(obj):
    """Recursively normalize @type to arrays with the schema: prefix."""
    if isinstance(obj, list):
        return [_fix_types(i) for i in obj]
    if not isinstance(obj, dict):
        return obj
    if "@type" in obj:
        types = obj["@type"] if isinstance(obj["@type"], list) else [obj["@type"]]
        type_map = {
            "FundingAgency": "schema:Organization",
            "schema:FundingAgency": "schema:Organization",
            "sc:Dataset": "schema:Dataset",
            "cr:FileObject": "schema:DataDownload",
            "Grant": "schema:MonetaryGrant",
        }
        normalized = []
        for t in types:
            if t in type_map:
                normalized.append(type_map[t])
            elif t in SCHEMA_TYPES:
                normalized.append("schema:" + t)
            elif ":" not in str(t) and not str(t).startswith("http"):
                normalized.append(UNKNOWN_PREFIX + ":" + t)
            else:
                normalized.append(t)
        obj["@type"] = normalized
    for k, v in obj.items():
        if k != "@type":
            obj[k] = _fix_types(v)
    return obj


def _extract_persons(obj):
    """Recursively pull Person/Org objects out of @list / Role wrappers."""
    if not obj:
        return []
    if isinstance(obj, list):
        return [p for item in obj for p in _extract_persons(item)]
    if not isinstance(obj, dict):
        return []
    if "@list" in obj:
        return _extract_persons(obj["@list"])
    types = obj.get("@type") or []
    types = types if isinstance(types, list) else [types]
    if any("Role" in str(t) for t in types):
        return _extract_persons(obj.get("schema:author")
                                or obj.get("schema:creator") or [])
    return [obj]


def _ensure_array(val):
    if val is None:
        return None
    return val if isinstance(val, list) else [val]


def _pick_dataset(soso):
    """Return the SOSO Dataset node (root, or the Dataset in an @graph)."""
    graph = soso.get("@graph")
    if isinstance(graph, list):
        for node in graph:
            if isinstance(node, dict):
                t = node.get("@type")
                t = t if isinstance(t, list) else [t]
                if any(str(x).endswith("Dataset") for x in t if x):
                    return node, soso.get("@context")
        for node in graph:
            if isinstance(node, dict):
                return node, soso.get("@context")
    return soso, None


def convert_soso_to_cdif(soso, profile="discovery", source_label=None,
                         verbose=False):
    """Convert a SOSO Dataset record (dict) to a CDIF core/discovery record.

    Returns (cdif_dict, changes_list). Never mutates the input.
    """
    node, wrap_ctx = _pick_dataset(soso)
    doc = copy.deepcopy(node)
    if wrap_ctx is not None and "@context" not in doc:
        doc["@context"] = wrap_ctx
    changes = []

    # 1. Prefix property names.
    assumed, unknown = set(), set()
    doc = _prefix_keys(doc, assumed=assumed, unknown=unknown)
    changes.append("Property names prefixed with schema:")
    if unknown:
        changes.append(f"Unknown properties assigned to unk: ({', '.join(sorted(unknown))})")

    # 2. @context — CDIF prefixes + preserved extras.
    orig = node.get("@context", {})
    extra = {}
    items = orig if isinstance(orig, list) else [orig]
    for item in items:
        if isinstance(item, dict):
            for k, v in item.items():
                if k not in ("@vocab", "@language", "schema", "dcterms",
                             "dcat", "prov") and isinstance(v, str):
                    extra[k] = v
    ctx = {**CDIF_CONTEXT, **extra}
    if unknown:
        ctx[UNKNOWN_PREFIX] = UNKNOWN_NS
    doc["@context"] = ctx
    changes.append("@context set to CDIF prefix declarations")

    # 3. Normalize types.
    doc = _fix_types(doc)
    changes.append("@type values normalized to arrays with schema:")

    # 4. @id from url.
    if "@id" not in doc and doc.get("schema:url"):
        url = doc["schema:url"]
        doc["@id"] = url[0] if isinstance(url, list) else url
        changes.append("@id set from schema:url")

    # 5. dateModified fallback.
    if "schema:dateModified" not in doc:
        for fb in ("schema:datePublished", "schema:dateCreated"):
            if fb in doc:
                doc["schema:dateModified"] = doc[fb]
                changes.append(f"schema:dateModified set from {fb}")
                break

    # 6. identifier (single value).
    if "schema:identifier" not in doc and str(doc.get("@id", "")).startswith("http"):
        doc["schema:identifier"] = doc["@id"]
        changes.append("schema:identifier added from @id")
    elif isinstance(doc.get("schema:identifier"), list):
        doc["schema:identifier"] = doc["schema:identifier"][0]

    # 6b. description as string.
    if isinstance(doc.get("schema:description"), list):
        doc["schema:description"] = doc["schema:description"][0] \
            if doc["schema:description"] else ""

    # 7. license as array.
    if "schema:license" in doc and not isinstance(doc["schema:license"], list):
        doc["schema:license"] = [doc["schema:license"]]

    # 8. distributions.
    if "schema:distribution" in doc:
        dists = _ensure_array(doc["schema:distribution"])
        doc["schema:distribution"] = dists
        for dist in dists:
            if not isinstance(dist, dict):
                continue
            enc = dist.get("schema:encodingFormat")
            if enc and not isinstance(enc, list):
                dist["schema:encodingFormat"] = [enc]
            if "@type" not in dist:
                dist["@type"] = ["schema:DataDownload"]
            if "schema:contentUrl" not in dist and "schema:url" in dist:
                dist["schema:contentUrl"] = dist["schema:url"]
        changes.append("Distributions normalized")

    # 9. creator -> @list; author folds into creator.
    if "schema:creator" in doc:
        persons = _extract_persons(doc["schema:creator"])
        if persons:
            doc["schema:creator"] = {"@list": persons}
            changes.append("schema:creator wrapped in @list")
    if "schema:author" in doc and "schema:creator" not in doc:
        persons = _extract_persons(doc["schema:author"])
        doc["schema:creator"] = {"@list": persons}
        del doc["schema:author"]
        changes.append("schema:author converted to schema:creator")

    # 9b. agent fixes: Person name synthesis, sameAs arrays.
    def _fix_agents(obj):
        if isinstance(obj, list):
            for i in obj:
                _fix_agents(i)
        elif isinstance(obj, dict):
            types = obj.get("@type", [])
            types = types if isinstance(types, list) else [types]
            if any("Person" in str(t) for t in types) and "schema:name" not in obj:
                given = obj.get("schema:givenName", "")
                family = obj.get("schema:familyName", "")
                if family and given:
                    obj["schema:name"] = f"{family}, {given}"
                elif family or given:
                    obj["schema:name"] = family or given
            if "schema:sameAs" in obj and not isinstance(obj["schema:sameAs"], list):
                obj["schema:sameAs"] = [obj["schema:sameAs"]]
            for v in obj.values():
                _fix_agents(v)
    _fix_agents(doc)

    # 10. scalar-to-array fixes.
    for prop in ("schema:sameAs", "schema:additionalType",
                 "schema:conditionsOfAccess", "schema:provider",
                 "schema:keywords"):
        if prop in doc and not isinstance(doc[prop], list):
            if prop == "schema:keywords" and isinstance(doc[prop], str):
                doc[prop] = [k.strip() for k in doc[prop].split(",") if k.strip()]
                changes.append("schema:keywords split into array")
            else:
                doc[prop] = [doc[prop]]

    # 11. contributor as array.
    if "schema:contributor" in doc:
        val = doc["schema:contributor"]
        if isinstance(val, dict):
            doc["schema:contributor"] = val["@list"] if "@list" in val else [val]
        elif not isinstance(val, list):
            doc["schema:contributor"] = [val]

    # 12. funding: array + identifier as PropertyValue.
    if "schema:funding" in doc:
        doc["schema:funding"] = _ensure_array(doc["schema:funding"])
        for f in doc["schema:funding"]:
            if isinstance(f, dict) and isinstance(f.get("schema:identifier"), str):
                f["schema:identifier"] = {"@type": ["schema:PropertyValue"],
                                          "schema:value": f["schema:identifier"]}

    # 13. Discovery-specific fixes.
    if profile == "discovery":
        for prop in ("schema:spatialCoverage", "schema:temporalCoverage",
                     "schema:measurementTechnique"):
            if prop in doc and not isinstance(doc[prop], list):
                doc[prop] = [doc[prop]]
        if isinstance(doc.get("schema:spatialCoverage"), list):
            fixed = []
            for sc in doc["schema:spatialCoverage"]:
                if isinstance(sc, str):
                    sc = {"@type": ["schema:Place"], "schema:name": sc}
                if isinstance(sc, dict):
                    geo = sc.get("schema:geo")
                    if isinstance(geo, list) and geo:
                        sc["schema:geo"] = geo[0]
                    geo = sc.get("schema:geo")
                    if isinstance(geo, dict):
                        for c in ("schema:latitude", "schema:longitude"):
                            if isinstance(geo.get(c), str):
                                try:
                                    geo[c] = float(geo[c])
                                except ValueError:
                                    pass
                    if [k for k in sc if k != "@type"]:
                        fixed.append(sc)
            if fixed:
                doc["schema:spatialCoverage"] = fixed
            else:
                doc.pop("schema:spatialCoverage", None)
        if isinstance(doc.get("schema:variableMeasured"), list):
            for v in doc["schema:variableMeasured"]:
                if isinstance(v, dict):
                    for k in ("schema:propertyID", "schema:alternateName"):
                        if k in v and not isinstance(v[k], list):
                            v[k] = [v[k]]

    # 14. Build the CDIF catalog record (subjectOf/conformsTo).
    dataset_id = doc.get("@id") or ""
    if isinstance(dataset_id, list):
        dataset_id = dataset_id[0] if dataset_id else ""
    conforms = [{"@id": CORE_URI}]
    if profile == "discovery":
        conforms.append({"@id": DISCOVERY_URI})
    label = source_label
    if not label:
        pub = doc.get("schema:publisher")
        if isinstance(pub, dict):
            label = pub.get("schema:name")
        label = label or "unknown source"
    record = {
        "@type": ["schema:Dataset"],
        "schema:additionalType": ["dcat:CatalogRecord"],
        "@id": (dataset_id + "#metadata") if dataset_id else "urn:cdif:metadata",
        "schema:name": f"Metadata record for: {(doc.get('schema:name') or 'dataset')[:120]}",
        "schema:about": {"@id": dataset_id},
        "dcterms:conformsTo": conforms,
        "schema:description": (
            f"CDIF {profile} metadata converted from an ESIP "
            f"Science-on-Schema.org record ({label})."),
    }
    if not doc.get("schema:subjectOf"):
        doc["schema:subjectOf"] = record
        changes.append(f"Added CDIF catalog record (conformsTo {profile})")

    # Report SOSO/CDIF gaps that could not be filled from the source.
    if "schema:dateModified" not in doc:
        changes.append("WARNING: CDIF requires schema:dateModified; none derivable "
                       "from the SOSO record.")
    if "schema:license" not in doc and "schema:conditionsOfAccess" not in doc:
        changes.append("WARNING: CDIF requires license OR conditionsOfAccess; "
                       "neither present in the SOSO record.")
    if "schema:url" not in doc and "schema:distribution" not in doc:
        changes.append("WARNING: CDIF requires url OR distribution; neither "
                       "present in the SOSO record.")

    if verbose:
        for c in changes:
            tag = "WARNING" if c.startswith("WARNING") else "change"
            print(f"  {tag}: {c.replace('WARNING: ', '')}", file=sys.stderr)

    return doc, changes


def main():
    parser = argparse.ArgumentParser(
        description="Convert an ESIP Science-on-Schema.org (SOSO) Dataset "
                    "JSON-LD record to CDIF core+discovery JSON-LD.")
    parser.add_argument("input", help="Input SOSO JSON-LD file")
    parser.add_argument("-o", "--output", help="Output CDIF JSON-LD file "
                        "(default: stdout)")
    parser.add_argument("--profile", choices=["core", "discovery"],
                        default="discovery",
                        help="Target CDIF profile (default: discovery)")
    parser.add_argument("--source", help="Source/publisher label for the "
                        "catalog record (default: derived from schema:publisher)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Print conversion notes/warnings to stderr")
    args = parser.parse_args()

    with open(args.input, encoding="utf-8") as f:
        soso = json.load(f)

    cdif, changes = convert_soso_to_cdif(soso, profile=args.profile,
                                         source_label=args.source,
                                         verbose=args.verbose)

    text = json.dumps(cdif, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text + "\n")
        warns = sum(1 for c in changes if c.startswith("WARNING"))
        print(f"Wrote {args.output}  ({warns} warning(s))", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
