#!/usr/bin/env python3
"""
geocodes_harvester.py - Harvest dataset metadata from the EarthCube GeoCodes catalog.

Queries the GeoCodes Blazegraph SPARQL endpoint for dataset records, fetches
the original JSON-LD from source landing pages (falling back to SPARQL CONSTRUCT
if no embedded JSON-LD is found), and optionally converts them to CDIF profile
format.

The GeoCodes catalog indexes ~170K datasets harvested from data providers via
the Gleaner crawler.  Records follow ESIP Science-on-Schema.org conventions.

SPARQL endpoint:
    https://graph.geocodes-aws.earthcube.org/blazegraph/namespace/geocodes_all/sparql

Usage:
    # List available publishers
    python geocodes_harvester.py --list-publishers

    # Harvest 5 random records from diverse publishers
    python geocodes_harvester.py --count 5 --output ./examples

    # Harvest and convert to CDIF Discovery profile
    python geocodes_harvester.py --count 5 --output ./examples --cdif discovery

    # Harvest from a specific publisher
    python geocodes_harvester.py --publisher "PANGAEA" --count 3 --output ./examples
"""

import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.parse
import urllib.error
from html.parser import HTMLParser


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SPARQL_ENDPOINT = (
    "https://graph.geocodes-aws.earthcube.org/blazegraph/"
    "namespace/geocodes_all/sparql"
)

GEOCODES_URL = "https://geocodes.earthcube.org/"

CDIF_CONTEXT = {
    "schema": "http://schema.org/",
    "dcterms": "http://purl.org/dc/terms/",
    "dcat": "http://www.w3.org/ns/dcat#",
    "prov": "http://www.w3.org/ns/prov#",
}

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
    "locationCreated", "fileFormat", "usageinfo", "potentialAction",
    "sdDatePublished", "maintainer",
    # Properties found in NCEI, Copernicus, Kaggle records
    "addressCountry", "addressLocality", "addressRegion", "availableLanguage",
    "caption", "commentCount", "dayOfWeek", "disambiguatingDescription",
    "discussionUrl", "faxNumber", "hoursAvailable", "image",
    "inDefinedTermSet", "interactionStatistic", "interactionType",
    "parentOrganization", "postalCode", "requiresSubscription",
    "streetAddress", "userInteractionCount",
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
    "InteractionCounter", "OpeningHoursSpecification",
}


# ---------------------------------------------------------------------------
# SPARQL queries
# ---------------------------------------------------------------------------

def sparql_query(query, accept="application/sparql-results+json"):
    """POST a SPARQL query to the GeoCodes endpoint."""
    data = query.encode("utf-8")
    req = urllib.request.Request(
        SPARQL_ENDPOINT,
        data=data,
        headers={
            "Content-Type": "application/sparql-query",
            "Accept": accept,
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def list_publishers(limit=50):
    """Return a list of (publisher_name, count) tuples."""
    q = """
    PREFIX schema: <https://schema.org/>
    SELECT ?pubname (COUNT(DISTINCT ?s) AS ?cnt)
    WHERE {
      ?s schema:publisher/schema:name ?pubname .
    }
    GROUP BY ?pubname
    ORDER BY DESC(?cnt)
    LIMIT """ + str(limit)
    result = json.loads(sparql_query(q))
    return [
        (b["pubname"]["value"], int(b["cnt"]["value"]))
        for b in result["results"]["bindings"]
    ]


def find_datasets(count=10, publisher=None):
    """Find dataset graph URIs with metadata.

    Returns list of dicts with keys: graph, name, publisher, url.
    If publisher is given, filters to that publisher.
    Otherwise selects one sample per publisher for diversity.
    """
    if publisher:
        q = f"""
        PREFIX schema: <https://schema.org/>
        SELECT ?g ?name ?url WHERE {{
          GRAPH ?g {{
            ?s a schema:Dataset .
            ?s schema:name ?name .
            ?s schema:publisher/schema:name "{publisher}" .
            OPTIONAL {{ ?s schema:url ?url }}
          }}
        }}
        LIMIT {count}
        """
    else:
        # One sample per publisher for diversity
        q = f"""
        PREFIX schema: <https://schema.org/>
        SELECT ?pubname (SAMPLE(?g) AS ?sg) (SAMPLE(?name) AS ?sname)
               (SAMPLE(?url) AS ?surl)
        WHERE {{
          GRAPH ?g {{
            ?s a schema:Dataset .
            ?s schema:name ?name .
            ?s schema:publisher/schema:name ?pubname .
            OPTIONAL {{ ?s schema:url ?url }}
          }}
        }}
        GROUP BY ?pubname
        LIMIT {count}
        """

    result = json.loads(sparql_query(q))
    datasets = []
    for b in result["results"]["bindings"]:
        if publisher:
            datasets.append({
                "graph": b["g"]["value"],
                "name": b["name"]["value"],
                "publisher": publisher,
                "url": b.get("url", {}).get("value", ""),
            })
        else:
            datasets.append({
                "graph": b["sg"]["value"],
                "name": b["sname"]["value"],
                "publisher": b["pubname"]["value"],
                "url": b.get("surl", {}).get("value", ""),
            })
    return datasets


def fetch_sparql_jsonld(graph_uri):
    """Fetch all triples for a graph via SPARQL CONSTRUCT, returned as JSON-LD."""
    q = f"CONSTRUCT {{?s ?p ?o}} WHERE {{ GRAPH <{graph_uri}> {{ ?s ?p ?o }} }}"
    return sparql_query(q, accept="application/ld+json")


# ---------------------------------------------------------------------------
# Landing page JSON-LD extraction
# ---------------------------------------------------------------------------

class JsonLdExtractor(HTMLParser):
    """Extract JSON-LD script blocks from HTML."""

    def __init__(self):
        super().__init__()
        self._in_jsonld = False
        self._buf = []
        self.blocks = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            attr_dict = dict(attrs)
            if attr_dict.get("type", "").lower() == "application/ld+json":
                self._in_jsonld = True
                self._buf = []

    def handle_data(self, data):
        if self._in_jsonld:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._in_jsonld:
            self._in_jsonld = False
            text = "".join(self._buf)
            try:
                self.blocks.append(json.loads(text))
            except json.JSONDecodeError:
                pass


def fetch_landing_page(url, max_redirects=5):
    """Fetch HTML from a URL, following redirects."""
    for _ in range(max_redirects):
        req = urllib.request.Request(url, headers={
            "User-Agent": "CDIF-GeoCodes-Harvester/1.0",
            "Accept": "text/html",
        })
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                if resp.status in (301, 302, 303, 307, 308):
                    url = resp.headers.get("Location", url)
                    continue
                return resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                url = e.headers.get("Location", url)
                continue
            raise
    return None


def _is_dataset_type(typ):
    if not typ:
        return False
    types = typ if isinstance(typ, list) else [typ]
    return any(
        t in ("Dataset", "sc:Dataset", "schema:Dataset",
              "https://schema.org/Dataset", "http://schema.org/Dataset")
        for t in types
    )


def extract_dataset_jsonld(html):
    """Extract the Dataset JSON-LD block from HTML."""
    parser = JsonLdExtractor()
    parser.feed(html)
    for block in parser.blocks:
        if _is_dataset_type(block.get("@type")):
            return block
        if "@graph" in block:
            for node in block["@graph"]:
                if _is_dataset_type(node.get("@type")):
                    ctx = block.get("@context")
                    if ctx:
                        node["@context"] = ctx
                    return node
    return None


def harvest_record(dataset_info, verbose=False):
    """Harvest a single dataset record.

    Tries the landing page first for original JSON-LD; falls back to SPARQL.
    Returns (jsonld_dict, source) where source is 'landing_page' or 'sparql'.
    """
    url = dataset_info.get("url", "")

    # Try landing page first
    if url and url.startswith("http"):
        try:
            if verbose:
                print(f"  Fetching landing page: {url}")
            html = fetch_landing_page(url)
            if html:
                dataset = extract_dataset_jsonld(html)
                if dataset:
                    return dataset, "landing_page"
                if verbose:
                    print("  No JSON-LD found on landing page, falling back to SPARQL")
        except Exception as e:
            if verbose:
                print(f"  Landing page failed ({e}), falling back to SPARQL")

    # Fall back to SPARQL CONSTRUCT
    if verbose:
        print(f"  Fetching via SPARQL CONSTRUCT: {dataset_info['graph']}")
    raw = fetch_sparql_jsonld(dataset_info["graph"])
    # SPARQL returns expanded JSON-LD — return as-is (array of nodes)
    return json.loads(raw), "sparql"


# ---------------------------------------------------------------------------
# CDIF conversion
# ---------------------------------------------------------------------------

UNKNOWN_NS = "https://ex.org/unknown/"
UNKNOWN_PREFIX = "unk"


def _prefix_keys(obj, depth=0, assumed_schema_keys=None, unknown_keys=None):
    """Recursively prefix unprefixed property names.

    Known schema.org properties get ``schema:``.  Unprefixed keys that match
    schema.org class or property names (in SCHEMA_PROPS or SCHEMA_TYPES) are
    assumed to be schema.org and prefixed with ``schema:``, tracked in
    *assumed_schema_keys*.  Any remaining unprefixed key is assigned to the
    ``unk:`` (https://ex.org/unknown/) namespace.  *unknown_keys* collects
    these truly unknown names.
    """
    if depth > 20:
        return obj
    if isinstance(obj, list):
        return [_prefix_keys(item, depth + 1, assumed_schema_keys, unknown_keys)
                for item in obj]
    if not isinstance(obj, dict):
        return obj
    if assumed_schema_keys is None:
        assumed_schema_keys = set()
    if unknown_keys is None:
        unknown_keys = set()
    result = {}
    for key, value in obj.items():
        new_key = key
        if not key.startswith("@") and ":" not in key and not key.startswith("http"):
            if key in SCHEMA_PROPS:
                new_key = "schema:" + key
            elif key in SCHEMA_TYPES:
                # Type name used as property — unusual but assume schema.org
                new_key = "schema:" + key
                assumed_schema_keys.add(key)
            else:
                new_key = UNKNOWN_PREFIX + ":" + key
                unknown_keys.add(key)
        result[new_key] = _prefix_keys(value, depth + 1,
                                       assumed_schema_keys, unknown_keys)
    return result


def _fix_types(obj):
    """Recursively normalize @type to arrays with schema: prefix."""
    if isinstance(obj, list):
        return [_fix_types(item) for item in obj]
    if not isinstance(obj, dict):
        return obj
    if "@type" in obj:
        types = obj["@type"] if isinstance(obj["@type"], list) else [obj["@type"]]
        # Normalize types: prefix schema.org types, map known aliases
        _TYPE_MAP = {
            "FundingAgency": "schema:Organization",
            "schema:FundingAgency": "schema:Organization",
            "sc:Dataset": "schema:Dataset",
            "cr:FileObject": "schema:DataDownload",
            "Grant": "schema:MonetaryGrant",
        }
        normalized = []
        for t in types:
            if t in _TYPE_MAP:
                normalized.append(_TYPE_MAP[t])
            elif t in SCHEMA_TYPES:
                normalized.append("schema:" + t)
            elif ":" not in t and not t.startswith("http"):
                # Unprefixed type not in schema.org — assign to unk:
                normalized.append(UNKNOWN_PREFIX + ":" + t)
            else:
                normalized.append(t)
        types = normalized
        obj["@type"] = types
    for k, v in obj.items():
        if k != "@type":
            obj[k] = _fix_types(v)
    return obj


def _extract_persons(obj):
    """Recursively extract Person/Org objects from @list/Role wrappers."""
    if not obj:
        return []
    if isinstance(obj, list):
        return [p for item in obj for p in _extract_persons(item)]
    if not isinstance(obj, dict):
        return []
    if "@list" in obj:
        return _extract_persons(obj["@list"])
    if obj.get("@type") and any("Role" in str(t) for t in
                                 (obj["@type"] if isinstance(obj["@type"], list)
                                  else [obj["@type"]])):
        return _extract_persons(
            obj.get("schema:author") or obj.get("schema:creator") or [])
    return [obj]


def _ensure_array(val):
    if val is None:
        return None
    return val if isinstance(val, list) else [val]


def convert_to_cdif(doc, publisher_label, profile="core"):
    """Convert a schema.org JSON-LD record to CDIF profile format.

    Args:
        doc: The JSON-LD dict (with @vocab-style or unprefixed properties).
        publisher_label: Name of the source publisher for the subjectOf note.
        profile: 'core' or 'discovery'.

    Returns:
        Converted dict.
    """
    changes = []

    # 1. Prefix property names — known schema.org props get schema:,
    #    unknown unprefixed props get unk: (https://ex.org/unknown/)
    assumed_schema_keys = set()
    unknown_keys = set()
    doc = _prefix_keys(doc, assumed_schema_keys=assumed_schema_keys,
                       unknown_keys=unknown_keys)
    changes.append("Property names prefixed with schema: namespace")
    if assumed_schema_keys:
        changes.append(
            f"Unprefixed properties assumed to be schema.org based on "
            f"matching schema.org class/property names and prefixed with "
            f"schema: ({', '.join(sorted(assumed_schema_keys))})"
        )
    if unknown_keys:
        changes.append(
            f"Unprefixed properties with no matching schema.org name "
            f"assigned to unk: namespace ({UNKNOWN_NS}): "
            f"{', '.join(sorted(unknown_keys))}"
        )

    # 2. Fix @context — set CDIF required prefixes, preserve any extras
    orig_ctx = doc.get("@context", {})
    extra = {}
    if isinstance(orig_ctx, dict):
        for k, v in orig_ctx.items():
            if k not in ("@vocab", "@language", "schema", "dcterms", "dcat", "prov") \
               and isinstance(v, str):
                extra[k] = v
    elif isinstance(orig_ctx, list):
        for item in orig_ctx:
            if isinstance(item, dict):
                for k, v in item.items():
                    if k not in ("@vocab", "@language", "schema", "dcterms", "dcat", "prov") \
                       and isinstance(v, str):
                        extra[k] = v
    ctx = {**CDIF_CONTEXT, **extra}
    if unknown_keys:
        ctx[UNKNOWN_PREFIX] = UNKNOWN_NS
    doc["@context"] = ctx
    changes.append("@context set to CDIF prefix declarations (extra prefixes preserved)")

    # 3. Normalize types
    doc = _fix_types(doc)
    changes.append("@type values normalized to arrays with schema: prefix")

    # 4. Ensure @id
    if "@id" not in doc:
        url = doc.get("schema:url")
        if url:
            doc["@id"] = url
            changes.append("@id set from schema:url")

    # 5. Ensure dateModified
    if "schema:dateModified" not in doc:
        for fallback in ("schema:datePublished", "schema:dateCreated"):
            if fallback in doc:
                doc["schema:dateModified"] = doc[fallback]
                changes.append(f"schema:dateModified set from {fallback}")
                break

    # 6. Ensure identifier (single value, not array)
    if "schema:identifier" not in doc and doc.get("@id", "").startswith("http"):
        doc["schema:identifier"] = doc["@id"]
        changes.append("schema:identifier added from @id")
    elif isinstance(doc.get("schema:identifier"), list):
        doc["schema:identifier"] = doc["schema:identifier"][0]
        changes.append("schema:identifier unwrapped from array")

    # 6b. Ensure description is string, not array
    if isinstance(doc.get("schema:description"), list):
        doc["schema:description"] = doc["schema:description"][0] \
            if doc["schema:description"] else ""
        changes.append("schema:description unwrapped from array")

    # 7. license as array
    if "schema:license" in doc and not isinstance(doc["schema:license"], list):
        doc["schema:license"] = [doc["schema:license"]]
        changes.append("schema:license wrapped in array")

    # 8. Fix distributions
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
            # schema:url on a DataDownload → schema:contentUrl
            if "schema:contentUrl" not in dist and "schema:url" in dist:
                dist["schema:contentUrl"] = dist["schema:url"]
        changes.append("Distributions normalized")

    # 9. Fix creator
    if "schema:creator" in doc:
        persons = _extract_persons(doc["schema:creator"])
        if persons:
            doc["schema:creator"] = {"@list": persons}
            changes.append("schema:creator wrapped in @list")

    # 9b. Fix agent objects (Person/Org) for CDIF conformance:
    #     - Ensure Person has schema:name (synthesize from givenName/familyName)
    #     - Ensure schema:sameAs is array where present
    #     - Remove empty spatialCoverage entries
    def _fix_agents(obj):
        if isinstance(obj, list):
            for item in obj:
                _fix_agents(item)
        elif isinstance(obj, dict):
            types = obj.get("@type", [])
            if not isinstance(types, list):
                types = [types]

            # Person: ensure schema:name exists
            if any("Person" in str(t) for t in types):
                if "schema:name" not in obj:
                    given = obj.get("schema:givenName", "")
                    family = obj.get("schema:familyName", "")
                    if family and given:
                        obj["schema:name"] = f"{family}, {given}"
                    elif family:
                        obj["schema:name"] = family
                    elif given:
                        obj["schema:name"] = given

            # sameAs must be array on any object that has it
            if "schema:sameAs" in obj and not isinstance(obj["schema:sameAs"], list):
                obj["schema:sameAs"] = [obj["schema:sameAs"]]

            for v in obj.values():
                _fix_agents(v)

    _fix_agents(doc)
    changes.append("Agent objects fixed (Person name synthesis, sameAs arrays)")

    if "schema:author" in doc and "schema:creator" not in doc:
        persons = _extract_persons(doc["schema:author"])
        doc["schema:creator"] = {"@list": persons}
        del doc["schema:author"]
        changes.append("schema:author converted to schema:creator")

    # 10. Scalar-to-array fixes for properties the schema expects as arrays
    for prop in ("schema:sameAs", "schema:additionalType",
                 "schema:conditionsOfAccess", "schema:provider",
                 "schema:keywords"):
        if prop in doc and not isinstance(doc[prop], list):
            # keywords: split comma-separated strings
            if prop == "schema:keywords" and isinstance(doc[prop], str):
                doc[prop] = [k.strip() for k in doc[prop].split(",") if k.strip()]
            else:
                doc[prop] = [doc[prop]]

    # 11. Fix contributor to array (not @list — schema expects array)
    if "schema:contributor" in doc:
        val = doc["schema:contributor"]
        if isinstance(val, dict):
            if "@list" in val:
                doc["schema:contributor"] = val["@list"]
            else:
                doc["schema:contributor"] = [val]
        elif not isinstance(val, list):
            doc["schema:contributor"] = [val]

    # 12. Fix funding: ensure array, fix types
    if "schema:funding" in doc:
        if not isinstance(doc["schema:funding"], list):
            doc["schema:funding"] = [doc["schema:funding"]]
        for f in doc["schema:funding"]:
            if isinstance(f, dict):
                # identifier must be object, not string
                ident = f.get("schema:identifier")
                if isinstance(ident, str):
                    f["schema:identifier"] = {
                        "@type": ["schema:PropertyValue"],
                        "schema:value": ident,
                    }

    # 13. Discovery-specific fixes
    if profile == "discovery":
        for prop in ("schema:spatialCoverage", "schema:temporalCoverage",
                     "schema:measurementTechnique"):
            if prop in doc and not isinstance(doc[prop], list):
                doc[prop] = [doc[prop]]

        if isinstance(doc.get("schema:spatialCoverage"), list):
            fixed_sc = []
            for sc in doc["schema:spatialCoverage"]:
                if isinstance(sc, str):
                    sc = {"@type": ["schema:Place"], "schema:name": sc}
                if isinstance(sc, dict):
                    # geo must be single object, not array
                    geo = sc.get("schema:geo")
                    if isinstance(geo, list):
                        if len(geo) >= 1:
                            sc["schema:geo"] = geo[0]
                        else:
                            del sc["schema:geo"]
                            geo = None
                    # Fix GeoCoordinates lat/lon to numbers
                    geo = sc.get("schema:geo")
                    if isinstance(geo, dict):
                        for coord in ("schema:latitude", "schema:longitude"):
                            val = geo.get(coord)
                            if isinstance(val, str):
                                try:
                                    geo[coord] = float(val)
                                except ValueError:
                                    pass
                # Skip empty Place objects (no geo, no name)
                useful_keys = [k for k in sc.keys()
                               if k not in ("@type",)]
                if useful_keys:
                    fixed_sc.append(sc)
            doc["schema:spatialCoverage"] = fixed_sc
            if not fixed_sc:
                del doc["schema:spatialCoverage"]

        if isinstance(doc.get("schema:variableMeasured"), list):
            for v in doc["schema:variableMeasured"]:
                if isinstance(v, dict):
                    for k in ("schema:propertyID", "schema:alternateName"):
                        if k in v and not isinstance(v[k], list):
                            v[k] = [v[k]]

    # 12. Build subjectOf
    dataset_id = doc.get("@id") or doc.get("schema:url") or ""
    conformsTo = [{"@id": "https://w3id.org/cdif/core/1.0"}]
    if profile == "discovery":
        conformsTo.append({"@id": "https://w3id.org/cdif/discovery/1.0"})

    doc["schema:subjectOf"] = {
        "@type": ["schema:Dataset"],
        "schema:additionalType": ["dcat:CatalogRecord"],
        "@id": (dataset_id + "#metadata") if dataset_id else "#metadata",
        "schema:name": (
            f"Metadata record for: "
            f"{(doc.get('schema:name') or 'dataset')[:120]}"
        ),
        "schema:about": {"@id": dataset_id},
        "dcterms:conformsTo": conformsTo,
        "schema:includedInDataCatalog": {
            "@type": ["schema:DataCatalog"],
            "schema:name": publisher_label,
            "schema:url": doc.get("schema:url") or dataset_id or "",
        },
        "schema:description": (
            f"Metadata harvested from {publisher_label} by Claude Code. "
            f"Converted to CDIF {profile} profile: {'; '.join(changes)}."
        ),
    }

    return doc


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Harvest dataset metadata from the EarthCube GeoCodes catalog")
    parser.add_argument("--list-publishers", action="store_true",
                        help="List available publishers and exit")
    parser.add_argument("--publisher", "-p", type=str, default=None,
                        help="Filter to a specific publisher name")
    parser.add_argument("--count", "-n", type=int, default=5,
                        help="Number of records to harvest (default: 5)")
    parser.add_argument("--output", "-o", type=str, default=".",
                        help="Output directory for JSON-LD files")
    parser.add_argument("--cdif", type=str, choices=["core", "discovery"],
                        default=None,
                        help="Convert to CDIF profile format (core or discovery)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    if args.list_publishers:
        print(f"{'Publisher':50s} {'Datasets':>10s}")
        print("-" * 62)
        for name, count in list_publishers():
            print(f"{name:50s} {count:10d}")
        return 0

    # Find datasets
    print(f"Querying GeoCodes for {args.count} dataset(s)...")
    datasets = find_datasets(count=args.count, publisher=args.publisher)
    if not datasets:
        print("No datasets found.")
        return 1
    print(f"Found {len(datasets)} dataset(s)")

    os.makedirs(args.output, exist_ok=True)

    # Harvest each
    for i, ds in enumerate(datasets):
        pub = ds["publisher"][:30]
        name = ds["name"][:60]
        print(f"\n[{i+1}/{len(datasets)}] {pub}: {name}")

        try:
            record, source = harvest_record(ds, verbose=args.verbose)
        except Exception as e:
            print(f"  ERROR: {e}")
            continue

        if source == "sparql":
            # SPARQL returns expanded form — not ideal for examples
            print(f"  Harvested via SPARQL (expanded JSON-LD, may have blank node issues)")
        else:
            print(f"  Harvested from landing page")

        # Convert if requested
        if args.cdif and isinstance(record, dict):
            record = convert_to_cdif(record, pub, profile=args.cdif)
            print(f"  Converted to CDIF {args.cdif} profile")

        # Write output
        safe_pub = re.sub(r"[^a-zA-Z0-9]", "-", pub).strip("-").lower()[:20]
        filename = f"GeoCodes-{safe_pub}-{i:02d}.jsonld"
        outpath = os.path.join(args.output, filename)
        with open(outpath, "w", encoding="utf-8") as f:
            json.dump(record, f, indent=2, ensure_ascii=False)
        print(f"  Written: {outpath}")

    print(f"\nDone. {len(datasets)} record(s) harvested.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
