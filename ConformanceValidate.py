#!/usr/bin/env python3
"""
ConformanceValidate.py — discover and apply CDIF conformance validation.

Reads a CDIF JSON-LD instance document, extracts the
schema:subjectOf / dcterms:conformsTo URIs, fetches each profile's
JSON Schema (via <URI>/schema) and SHACL rules (via <URI>/shacl)
from the w3id.org/cdif redirector, validates the document against
each, and produces a consolidated report.

Each conformance URI in the instance document's catalog record drives
one validation pass; the report is sectioned per-profile so failures
are attributable to the specific profile that requires the constraint.

Usage:
    python ConformanceValidate.py instance.json
    python ConformanceValidate.py instance.json --verbose
    python ConformanceValidate.py instance.json --no-shacl
    python ConformanceValidate.py instance.json --no-schema
    python ConformanceValidate.py instance.json --cache-dir ./.conformance-cache
    python ConformanceValidate.py instance.json --frame frame.jsonld

Dependencies:
    pip install pyld jsonschema pyshacl requests
"""

import argparse
import json
import sys
import urllib.parse
from pathlib import Path

import requests
from pyld import jsonld
from jsonschema import Draft202012Validator

try:
    from pyshacl import validate as shacl_validate
    HAS_PYSHACL = True
except ImportError:
    HAS_PYSHACL = False


# Sub-paths exposed by the w3id.org/cdif/<profile>/<version>/ redirector.
# These match what the deployed .htaccess emits (commit d223ae6c upstream).
SCHEMA_SUBPATH = "/schema"
SHACL_SUBPATH = "/shacl"

# Accept headers used when content-negotiating against the bare conformance
# URI as a fallback path. The subpath form is preferred; these are only used
# if --use-accept is passed.
SCHEMA_ACCEPT = "application/schema+json"
SHACL_ACCEPT = "text/turtle"

# Default frame for JSON Schema validation: match top-level schema:Dataset.
DEFAULT_FRAME = {
    "@type": "http://schema.org/Dataset",
    "@embed": "@always",
}

# Compaction context applied after framing. Uses namespace prefixes for
# the vocabularies that the StructuredSchemas reference by prefix
# (schema, cdi, csvw, skos, dcat), and explicit term mappings (without a
# namespace prefix entry) for the other vocabularies. Mixing both forms
# avoids pyld's "Absolute IRI confused with prefix" error when a
# compacted IRI's local part happens to match a prefix term name
# (e.g. spdx:checksum colliding with the `spdx` prefix term).
CDIF_OUTPUT_CONTEXT = {
    # Namespace prefixes (safe — no CURIE-conflict risk in practice)
    "schema": "http://schema.org/",
    "cdi": "http://ddialliance.org/Specification/DDI-CDI/1.0/RDF/",
    "csvw": "http://www.w3.org/ns/csvw#",
    "dcat": "http://www.w3.org/ns/dcat#",
    "skos": "http://www.w3.org/2004/02/skos/core#",

    # Explicit term mappings — these vocabularies are NOT registered as
    # prefixes, to avoid compaction-time CURIE/IRI ambiguity. Each known
    # term is renamed below in TERM_MAPPINGS so the validator sees the
    # prefixed form the StructuredSchemas expect.
    "conformsTo": "http://purl.org/dc/terms/conformsTo",
    "wasGeneratedBy": "http://www.w3.org/ns/prov#wasGeneratedBy",
    "wasDerivedFrom": "http://www.w3.org/ns/prov#wasDerivedFrom",
    "used": "http://www.w3.org/ns/prov#used",
    "Activity": "http://www.w3.org/ns/prov#Activity",
    "hasQualityMeasurement": "http://www.w3.org/ns/dqv#hasQualityMeasurement",
    "isMeasurementOf": "http://www.w3.org/ns/dqv#isMeasurementOf",
    "QualityMeasurement": "http://www.w3.org/ns/dqv#QualityMeasurement",
    "hasGeometry": "http://www.opengis.net/ont/geosparql#hasGeometry",
    "asWKT": "http://www.opengis.net/ont/geosparql#asWKT",
    "wktLiteral": "http://www.opengis.net/ont/geosparql#wktLiteral",
    "checksum": "http://spdx.org/rdf/terms#checksum",
    "algorithm": "http://spdx.org/rdf/terms#algorithm",
    "checksumValue": "http://spdx.org/rdf/terms#checksumValue",
    "Checksum": "http://spdx.org/rdf/terms#Checksum",
    "hasBeginning": "http://www.w3.org/2006/time#hasBeginning",
    "hasEnd": "http://www.w3.org/2006/time#hasEnd",
    "inTimePosition": "http://www.w3.org/2006/time#inTimePosition",
    "hasTRS": "http://www.w3.org/2006/time#hasTRS",
    "numericPosition": "http://www.w3.org/2006/time#numericPosition",
}

# Post-compaction rename: unprefixed compaction output -> prefixed term
# the StructuredSchemas expect. Mirrors the per-profile FrameAndValidate.
TERM_MAPPINGS = {
    "conformsTo": "dcterms:conformsTo",
    "Activity": "prov:Activity",
    "Checksum": "spdx:Checksum",
    "wasGeneratedBy": "prov:wasGeneratedBy",
    "wasDerivedFrom": "prov:wasDerivedFrom",
    "used": "prov:used",
    "hasQualityMeasurement": "dqv:hasQualityMeasurement",
    "isMeasurementOf": "dqv:isMeasurementOf",
    "hasGeometry": "geosparql:hasGeometry",
    "asWKT": "geosparql:asWKT",
    "checksum": "spdx:checksum",
    "algorithm": "spdx:algorithm",
    "checksumValue": "spdx:checksumValue",
    "hasBeginning": "time:hasBeginning",
    "hasEnd": "time:hasEnd",
    "inTimePosition": "time:inTimePosition",
    "hasTRS": "time:hasTRS",
    "numericPosition": "time:numericPosition",
}

# Properties the StructuredSchemas expect as arrays. Single-valued framed
# output is wrapped at the top level so cardinality constraints pass.
ARRAY_PROPERTIES = {
    "@type",
    # schema:subjectOf left intentionally OUT — profiles disagree on whether
    # it's array (codelist, conceptscheme) or single object (core, discovery).
    # Source shape passes through; per-profile validators can re-wrap.
    "schema:distribution",
    "schema:license",
    "schema:conditionsOfAccess",
    "schema:keywords",
    "schema:additionalType",
    "schema:contributor",
    "schema:provider",
    "schema:funding",
    "schema:variableMeasured",
    "schema:spatialCoverage",
    "schema:temporalCoverage",
    "schema:sameAs",
    "schema:potentialAction",
    "schema:participant",
    "schema:additionalProperty",
    # CDIF intentionally types these as arrays (per the description in
    # schemaorgProperties/additionalProperty/schema.yaml: "Multiple values
    # can specify the property at different levels of granularity").
    # Compaction unwraps single-element arrays to scalars; re-wrap here so
    # validation against the array-typed schemas sees the right shape.
    "schema:propertyID",
    "schema:alternateName",
    "schema:encodingFormat",
    "prov:wasGeneratedBy",
    "prov:wasDerivedFrom",
    "prov:used",
    "dqv:hasQualityMeasurement",
    "dcterms:conformsTo",
    "cdi:hasPhysicalMapping",
    "cdi:uses",
    "cdi:physicalDataType",
}


# ---------------------------------------------------------------------------
# Discovery — pull conformance URIs out of a CDIF instance
# ---------------------------------------------------------------------------

# Accepted forms for the CatalogRecord type tag on a subjectOf entry.
# Compaction or hand-authored docs may use the prefixed CURIE or the full IRI.
CATALOG_RECORD_TYPES = {
    "dcat:CatalogRecord",
    "http://www.w3.org/ns/dcat#CatalogRecord",
}


def _is_catalog_record(entry):
    """True if a schema:subjectOf entry is tagged as a dcat:CatalogRecord
    via schema:additionalType. Accepts string, list-of-strings, or
    {"@id": ...} object forms, and either the CURIE or full IRI.
    """
    at = entry.get("schema:additionalType") or entry.get("additionalType")
    if at is None:
        return False
    if not isinstance(at, list):
        at = [at]
    for v in at:
        if isinstance(v, dict):
            v = v.get("@id")
        if isinstance(v, str) and v in CATALOG_RECORD_TYPES:
            return True
    return False


def extract_conforms_to(doc):
    """Return the list of dcterms:conformsTo URIs inside schema:subjectOf
    entries that are tagged schema:additionalType=dcat:CatalogRecord.

    schema:subjectOf may be a single object or an array of objects (the
    catalog-record convention). Entries lacking the CatalogRecord type
    tag are skipped — conformsTo on a non-catalog-record subjectOf
    (e.g. a related publication) should not drive profile validation.
    Each surviving entry may carry dcterms:conformsTo as a string, an
    {"@id": ...} object, or an array of those. Returns a deduplicated,
    order-preserving list of URI strings.
    """
    subj = doc.get("schema:subjectOf") or doc.get("subjectOf")
    if subj is None:
        return []
    if isinstance(subj, dict):
        subj = [subj]

    uris = []
    seen = set()
    for entry in subj:
        if not isinstance(entry, dict):
            continue
        if not _is_catalog_record(entry):
            continue
        ct = entry.get("dcterms:conformsTo") or entry.get("conformsTo")
        if ct is None:
            continue
        if not isinstance(ct, list):
            ct = [ct]
        for item in ct:
            if isinstance(item, dict):
                uri = item.get("@id")
            elif isinstance(item, str):
                uri = item
            else:
                uri = None
            if uri and uri not in seen:
                seen.add(uri)
                uris.append(uri)
    return uris


# ---------------------------------------------------------------------------
# Fetching — pull schema/SHACL from the w3id redirector, with optional cache
# ---------------------------------------------------------------------------

def _fetch_text(url, accept, cache_dir, verbose):
    """GET url with the given Accept header, returning response text.

    If cache_dir is set, look up by URI-quoted key first and write back
    after a successful fetch. Cache is per (url, accept) implicitly,
    since the URLs differ for schema vs SHACL.
    """
    if cache_dir:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_key = urllib.parse.quote(url, safe="")
        cache_path = cache_dir / cache_key
        if cache_path.exists():
            if verbose:
                print(f"  CACHE HIT: {url}", file=sys.stderr)
            return cache_path.read_text(encoding="utf-8")

    if verbose:
        print(f"  GET {url} (Accept: {accept})", file=sys.stderr)
    r = requests.get(url, headers={"Accept": accept},
                     allow_redirects=True, timeout=30)
    r.raise_for_status()
    text = r.text

    if cache_dir:
        cache_path.write_text(text, encoding="utf-8")
    return text


def fetch_schema(uri, cache_dir=None, verbose=False, use_accept=False):
    """Fetch JSON Schema for a conformance URI.

    Default path: <URI>/schema with Accept: application/schema+json.
    If use_accept=True: hit the bare URI with Accept: application/schema+json
    instead (content negotiation, the w3id.org rules will redirect).
    """
    url = uri.rstrip("/") if use_accept else uri.rstrip("/") + SCHEMA_SUBPATH
    text = _fetch_text(url, SCHEMA_ACCEPT, cache_dir, verbose)
    return json.loads(text)


def fetch_shacl(uri, cache_dir=None, verbose=False, use_accept=False):
    """Fetch SHACL rules text for a conformance URI.

    Default path: <URI>/shacl with Accept: text/turtle.
    Returns the raw Turtle text (which pyshacl parses).
    """
    url = uri.rstrip("/") if use_accept else uri.rstrip("/") + SHACL_SUBPATH
    return _fetch_text(url, SHACL_ACCEPT, cache_dir, verbose)


# ---------------------------------------------------------------------------
# Validation passes
# ---------------------------------------------------------------------------

def _normalize(obj, parent=None):
    """Drop nulls; rename unprefixed terms (TERM_MAPPINGS) on dict keys
    AND on @type values; ensure ARRAY_PROPERTIES are arrays; @type
    always an array.

    Context-aware unwrap: schema:contributor is an array at the dataset
    level but a single object inside a schema:Role wrapper. After the
    array-wrap pass, walk back and unwrap single-element arrays where
    the parent's @type indicates a scalar-expecting context.
    """
    if isinstance(obj, list):
        out = [_normalize(v, parent) for v in obj if v is not None]
        # @type values: compaction emits bare terms ("Activity"); rewrite
        # them to the prefixed form ("prov:Activity") that the schemas want.
        if parent == "@type":
            out = [TERM_MAPPINGS.get(v, v) if isinstance(v, str) else v
                   for v in out]
        return out
    if isinstance(obj, dict):
        result = {}
        for k, v in obj.items():
            if v is None:
                continue
            new_key = TERM_MAPPINGS.get(k, k)
            nv = _normalize(v, new_key)
            if nv is None:
                continue
            if new_key == "@type":
                if isinstance(nv, str):
                    nv = [TERM_MAPPINGS.get(nv, nv)]
                elif isinstance(nv, list):
                    nv = [TERM_MAPPINGS.get(t, t) if isinstance(t, str) else t
                          for t in nv]
            # schema:propertyID is contextual: an array inside
            # schema:additionalProperty items (per CDIF additionalProperty
            # schema's "Multiple values can specify the property at different
            # levels of granularity") but a single string inside
            # schema:identifier (per the schemaorgProperties/identifier
            # schema). Skip the array-wrap in identifier context.
            skip_wrap = (parent == "schema:identifier"
                         and new_key == "schema:propertyID")
            if (not skip_wrap and new_key in ARRAY_PROPERTIES
                    and not isinstance(nv, list)):
                nv = [nv]
            result[new_key] = nv

        # Context-aware unwrap: properties that are array at the dataset
        # level but scalar inside specific nested wrappers.
        at = result.get("@type", [])
        if isinstance(at, str):
            at = [at]

        # schema:Role wrapper: nested schema:contributor expects single
        # Person/Organization (agentInRole schema is single-valued there).
        if "schema:Role" in at:
            inner = result.get("schema:contributor")
            if isinstance(inner, list) and len(inner) == 1:
                result["schema:contributor"] = inner[0]

        # Inner instrument-component pattern: nodes typed
        # [schema:Thing, schema:Product] (XAS hasPart items, sample,
        # source, monochromator, etc.) carry schema:additionalType as a
        # single const string per the XAS schemas — not the array form
        # used on the root Dataset.
        if "schema:Thing" in at and "schema:Product" in at:
            inner = result.get("schema:additionalType")
            if isinstance(inner, list) and len(inner) == 1:
                result["schema:additionalType"] = inner[0]

        return result
    if isinstance(obj, str) and parent == "@type":
        return TERM_MAPPINGS.get(obj, obj)
    return obj


def frame_doc(doc, frame):
    """Frame the document around schema:Dataset, compact with the CDIF
    output context, and normalize array/null shape. Returns the picked
    dataset (skipping catalog-record entities that share the Dataset
    type), in the prefixed form the StructuredSchemas validate against.
    """
    expanded = jsonld.expand(doc)
    framed = jsonld.frame(expanded, frame)
    compacted = jsonld.compact(framed, CDIF_OUTPUT_CONTEXT)

    # Augment the @context with the namespace prefixes the StructuredSchemas
    # require to be declared (dcterms, prov, dqv, spdx, time, geosparql).
    # Compaction with explicit term mappings produced unprefixed keys for
    # those vocabs in the body; declaring the prefixes here keeps the
    # output @context shape that the schemas check.
    ctx = compacted.get("@context")
    if isinstance(ctx, dict):
        ctx.setdefault("dcterms", "http://purl.org/dc/terms/")
        ctx.setdefault("prov", "http://www.w3.org/ns/prov#")
        ctx.setdefault("dqv", "http://www.w3.org/ns/dqv#")
        ctx.setdefault("spdx", "http://spdx.org/rdf/terms#")
        ctx.setdefault("time", "http://www.w3.org/2006/time#")
        ctx.setdefault("geosparql", "http://www.opengis.net/ont/geosparql#")

    if "@graph" in compacted and isinstance(compacted["@graph"], list):
        picked = None
        for item in compacted["@graph"]:
            at = item.get("schema:additionalType") or item.get("additionalType", [])
            if isinstance(at, str):
                at = [at]
            if "dcat:CatalogRecord" in at:
                continue
            picked = item
            break
        if picked is None and compacted["@graph"]:
            picked = compacted["@graph"][0]
        if picked is not None:
            result = {"@context": compacted.get("@context"), **picked}
        else:
            result = compacted
    else:
        result = compacted

    return _normalize(result)


def validate_with_jsonschema(framed, schema):
    """Return a list of {path, message, validator} dicts for each violation."""
    validator = Draft202012Validator(schema)
    errors = []
    for err in validator.iter_errors(framed):
        path = "/" + "/".join(str(p) for p in err.absolute_path) if err.absolute_path else "/"
        errors.append({
            "path": path,
            "message": err.message,
            "validator": err.validator,
        })
    return errors


def validate_with_shacl(doc, shacl_text):
    """Return a list of violation dicts; empty list = conforms.

    Runs pyshacl against the JSON-LD instance directly; pyshacl
    parses the JSON-LD into an RDF graph internally.
    """
    if not HAS_PYSHACL:
        return [{"message": "pyshacl not installed; SHACL pass skipped",
                 "skipped": True}]

    try:
        conforms, _results_graph, results_text = shacl_validate(
            json.dumps(doc),
            shacl_graph=shacl_text,
            data_graph_format="json-ld",
            shacl_graph_format="turtle",
            inference="rdfs",
            advanced=True,
        )
    except Exception as e:
        return [{"message": f"SHACL execution error: {e}"}]

    if conforms:
        return []

    # Parse the textual report into per-violation entries. pyshacl emits
    # multi-line entries separated by blank lines.
    errors = []
    current = {}
    for raw in results_text.splitlines():
        line = raw.strip()
        if not line:
            if current:
                errors.append(current)
                current = {}
            continue
        if ":" in line:
            k, v = line.split(":", 1)
            current[k.strip()] = v.strip()
    if current:
        errors.append(current)
    return errors


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_profile_section(uri, schema_errors, shacl_errors, verbose):
    print(f"\n{'='*70}")
    print(f"Profile: {uri}")
    print(f"{'='*70}")

    if schema_errors is None:
        print("\n  JSON Schema: skipped (--no-schema)")
    elif schema_errors == []:
        print("\n  JSON Schema: PASSED")
    else:
        print(f"\n  JSON Schema: {len(schema_errors)} violation(s)")
        for e in schema_errors:
            print(f"    - {e['path']}: {e['message']}")

    if shacl_errors is None:
        print("\n  SHACL: skipped (--no-shacl)")
    elif shacl_errors == []:
        print("\n  SHACL: PASSED")
    else:
        # Filter out pyshacl-skipped entries
        real = [e for e in shacl_errors if not e.get("skipped")]
        skipped = [e for e in shacl_errors if e.get("skipped")]
        if skipped:
            for e in skipped:
                print(f"\n  SHACL: SKIPPED ({e['message']})")
        if real:
            print(f"\n  SHACL: {len(real)} violation(s)")
            for e in real:
                msg = e.get("Message") or e.get("message") or "(no message)"
                path = e.get("Result Path") or ""
                focus = e.get("Focus Node") or ""
                line = f"    - {msg}"
                extras = []
                if path:
                    extras.append(f"path={path}")
                if focus:
                    extras.append(f"focus={focus}")
                if extras:
                    line += f"  [{', '.join(extras)}]"
                print(line)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Validate a CDIF JSON-LD instance against the conformance "
                    "URIs declared in its schema:subjectOf catalog record.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
For each dcterms:conformsTo URI in the document, this tool:
  1. Fetches the JSON Schema at <URI>/schema
  2. Fetches the SHACL rules at <URI>/shacl
  3. Validates the document against both
  4. Prints a per-profile pass/fail report

Default subpaths follow the w3id.org/cdif redirect conventions
(commit d223ae6c on perma-id/w3id.org master).

Examples:
  python ConformanceValidate.py myrecord.jsonld
  python ConformanceValidate.py myrecord.jsonld --verbose --cache-dir .cache
  python ConformanceValidate.py myrecord.jsonld --no-shacl
""")
    parser.add_argument("input", help="Input JSON-LD file")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--no-schema", action="store_true",
                        help="Skip JSON Schema validation pass")
    parser.add_argument("--no-shacl", action="store_true",
                        help="Skip SHACL validation pass")
    parser.add_argument("--frame",
                        help="Custom JSON-LD frame (default: minimal "
                             "schema:Dataset frame)")
    parser.add_argument("--cache-dir",
                        help="Directory for caching fetched schema/SHACL files "
                             "between runs")
    parser.add_argument("--use-accept", action="store_true",
                        help="Use Accept-header content negotiation on the "
                             "bare conformance URI instead of /schema and "
                             "/shacl sub-paths")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        doc = json.load(f)

    # Discover conformance URIs from the raw document.
    uris = extract_conforms_to(doc)
    if not uris:
        print("ERROR: No dcterms:conformsTo URIs found in schema:subjectOf.",
              file=sys.stderr)
        print("       The instance must include a catalog record with at "
              "least one conformsTo URI.", file=sys.stderr)
        sys.exit(2)

    if args.verbose:
        print(f"Discovered {len(uris)} conformance URI(s):", file=sys.stderr)
        for u in uris:
            print(f"  - {u}", file=sys.stderr)

    # Frame once for JSON Schema validation (StructuredSchemas expect
    # the nested form). SHACL validation operates on the unframed doc.
    if args.frame:
        with open(args.frame, "r", encoding="utf-8") as f:
            frame = json.load(f)
    else:
        frame = DEFAULT_FRAME

    framed = frame_doc(doc, frame) if not args.no_schema else None

    total_failures = 0
    total_skipped_profiles = 0

    for uri in uris:
        if args.verbose:
            print(f"\nFetching artifacts for {uri}...", file=sys.stderr)

        # --- JSON Schema pass ---
        if args.no_schema:
            schema_errors = None
        else:
            try:
                schema = fetch_schema(uri, args.cache_dir, args.verbose,
                                       args.use_accept)
                schema_errors = validate_with_jsonschema(framed, schema)
            except Exception as e:
                schema_errors = [{"path": "/", "message":
                                  f"Schema fetch/validate error: {e}",
                                  "validator": "fetch"}]

        # --- SHACL pass ---
        if args.no_shacl:
            shacl_errors = None
        else:
            try:
                shacl_text = fetch_shacl(uri, args.cache_dir, args.verbose,
                                         args.use_accept)
                shacl_errors = validate_with_shacl(doc, shacl_text)
            except Exception as e:
                shacl_errors = [{"message":
                                 f"SHACL fetch/validate error: {e}"}]

        print_profile_section(uri, schema_errors, shacl_errors, args.verbose)

        if schema_errors:
            total_failures += len(schema_errors)
        if shacl_errors:
            real = [e for e in shacl_errors if not e.get("skipped")]
            total_failures += len(real)

    print(f"\n{'='*70}")
    print(f"Summary: {len(uris)} profile(s) checked, "
          f"{total_failures} total violation(s)")
    print(f"{'='*70}")

    sys.exit(0 if total_failures == 0 else 1)


if __name__ == "__main__":
    main()
