#!/usr/bin/env python3
"""
ConformanceValidate.py — discover and apply CDIF conformance validation.

Reads a CDIF JSON-LD instance document, extracts the
schema:subjectOf / dcterms:conformsTo URIs, resolves each profile's
JSON Schema and SHACL rules, validates the document against each, and
produces a consolidated report.

Each conformance URI in the instance document's catalog record drives
one validation pass; the report is sectioned per-profile so failures
are attributable to the specific profile that requires the constraint.

Two schema sources (--source):
  * w3id   (default) — fetch <URI>/schema and <URI>/shacl from the
                       w3id.org/cdif redirector (authoritative; needs network).
  * local            — look each URI up in a JSON map file (--schema-map)
                       that points at local framed-tree schemas + SHACL
                       shapes. Works offline; useful for a web app's dev
                       mode. Defaults to conformance-schema-map.json beside
                       this script.

Input may be a single JSON-LD file or a directory (batch mode).

The validation engine is exposed as run_conformance(doc, resolver, ...)
returning a JSON-serializable results dict, so a web application can call
it directly and pick the resolver per request.

Usage:
    python ConformanceValidate.py instance.json
    python ConformanceValidate.py instance.json --verbose
    python ConformanceValidate.py instance.json --no-shacl
    python ConformanceValidate.py instance.json --source local
    python ConformanceValidate.py instance.json --source local --schema-map map.json
    python ConformanceValidate.py instance.json --cache-dir ./.conformance-cache
    python ConformanceValidate.py ./testJSONMetadata --summary
    python ConformanceValidate.py instance.json --frame frame.jsonld

Dependencies:
    pip install pyld jsonschema pyshacl requests
"""

import argparse
import glob
import json
import os
import sys
import urllib.parse
from collections import Counter
from pathlib import Path

import requests
from pyld import jsonld
from jsonschema import Draft202012Validator

try:
    from pyshacl import validate as shacl_validate
    import rdflib
    HAS_PYSHACL = True
except ImportError:
    HAS_PYSHACL = False

_SH = "http://www.w3.org/ns/shacl#"


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

# Variant spellings → canonical conformsTo URI (matched after trailing-slash
# stripping, case-insensitively).
URI_ALIASES = {
    "https://w3id.org/cdif/datadescription/1.0":
        "https://w3id.org/cdif/data_description/1.0",
}

# conformsTo URIs with these CURIE prefixes are domain-specific extension
# claims, not CDIF profiles; skip them during discovery so they don't drive
# profile validation (or trigger spurious w3id fetches).
IGNORE_PREFIXES = ("ada:",)


def normalize_uri(uri):
    """Strip a trailing slash and apply known alias rewrites. Used both for
    ignore-prefix matching and for LocalResolver map lookups so map keys and
    document URIs match regardless of trailing slash or spelling variant."""
    norm = uri.rstrip("/")
    return URI_ALIASES.get(norm.lower(), URI_ALIASES.get(norm, norm))


def is_ignored_uri(uri):
    """True if the conformsTo URI carries an ignored extension prefix."""
    return any(uri.startswith(p) for p in IGNORE_PREFIXES)


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
    # Index @graph nodes by @id so flattened documents (catalog record as a
    # separate @graph node, referenced by @id) resolve, and gather schema:subjectOf
    # from the top level AND from any @graph nodes (flattened docs put the
    # dataset -- and its subjectOf -- inside @graph rather than at the root).
    graph = doc.get("@graph")
    nodes_by_id = {}
    containers = [doc]
    if isinstance(graph, list):
        containers += [n for n in graph if isinstance(n, dict)]
        for n in graph:
            if isinstance(n, dict) and isinstance(n.get("@id"), str):
                nodes_by_id[n["@id"]] = n

    subj = []
    for c in containers:
        s = c.get("schema:subjectOf") or c.get("subjectOf")
        if s is not None:
            subj.extend(s if isinstance(s, list) else [s])
    if not subj:
        return []

    uris = []
    seen = set()
    for entry in subj:
        if not isinstance(entry, dict):
            continue
        # Resolve an @id-only reference to its node in @graph.
        if set(entry.keys()) <= {"@id"} and entry.get("@id") in nodes_by_id:
            entry = nodes_by_id[entry["@id"]]
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
    """Return a list of sh:Violation-severity result dicts; empty list = no
    violations. sh:Warning / sh:Info results are advisory and are NOT returned
    (they must not fail conformance), consistent with CDIF's severity policy.

    Runs pyshacl against the JSON-LD instance directly; pyshacl parses the
    JSON-LD into an RDF graph internally.
    """
    if not HAS_PYSHACL:
        return [{"message": "pyshacl not installed; SHACL pass skipped",
                 "skipped": True}]

    try:
        _conforms, results_graph, _txt = shacl_validate(
            json.dumps(doc),
            shacl_graph=shacl_text,
            data_graph_format="json-ld",
            shacl_graph_format="turtle",
            inference="rdfs",
            advanced=True,
        )
    except Exception as e:
        return [{"message": f"SHACL execution error: {e}"}]

    SH = rdflib.Namespace(_SH)
    errors = []
    for result in results_graph.subjects(rdflib.RDF.type, SH.ValidationResult):
        if results_graph.value(result, SH.resultSeverity) != SH.Violation:
            continue  # advisory (Warning/Info) -- does not fail conformance
        msg = results_graph.value(result, SH.resultMessage)
        focus = results_graph.value(result, SH.focusNode)
        path = results_graph.value(result, SH.resultPath)
        errors.append({
            "Message": str(msg) if msg is not None else "(no message)",
            "Focus Node": str(focus) if focus is not None else "",
            "Result Path": str(path) if path is not None else "",
            "Severity": "sh:Violation",
        })
    return errors


# ---------------------------------------------------------------------------
# Schema resolvers — pluggable backends for fetching schema/SHACL artifacts
# ---------------------------------------------------------------------------

# Default local map file, looked up beside this script when --source local is
# used without an explicit --schema-map.
DEFAULT_MAP_NAME = "conformance-schema-map.json"


class W3idResolver:
    """Resolve schema/SHACL by fetching <URI>/schema and <URI>/shacl from the
    w3id.org/cdif redirector. Authoritative; requires network access."""

    def __init__(self, cache_dir=None, use_accept=False, verbose=False):
        self.cache_dir = cache_dir
        self.use_accept = use_accept
        self.verbose = verbose

    def schema(self, uri):
        return fetch_schema(uri, self.cache_dir, self.verbose, self.use_accept)

    def shacl(self, uri):
        return fetch_shacl(uri, self.cache_dir, self.verbose, self.use_accept)


class LocalResolver:
    """Resolve schema/SHACL from local files listed in a JSON map.

    Map format — keys are conformsTo URIs (trailing-slash/alias-insensitive),
    values are objects with a required "schema" path and an optional "shacl"
    path, both relative to the map file's directory:

        {
          "https://w3id.org/cdif/discovery/1.0": {
            "schema": "CDIFDiscoverySchema.json",
            "shacl":  "ShaclValidation/CDIF-Discovery-Shapes.ttl"
          }
        }

    Returns None for a URI with no mapping (the engine reports it as
    no_schema / no_shacl rather than an error), so a partial map is fine.
    """

    def __init__(self, map_path, verbose=False):
        self.map_path = Path(map_path).resolve()
        self.base = self.map_path.parent
        self.verbose = verbose
        raw = json.loads(self.map_path.read_text(encoding="utf-8"))
        # Skip "_"-prefixed metadata keys (e.g. "_comment").
        self.map = {normalize_uri(k): v for k, v in raw.items()
                    if not k.startswith("_")}

    def _entry(self, uri):
        return self.map.get(normalize_uri(uri))

    def schema(self, uri):
        entry = self._entry(uri)
        if not entry or not entry.get("schema"):
            return None
        path = (self.base / entry["schema"]).resolve()
        if self.verbose:
            print(f"  LOCAL schema: {path}", file=sys.stderr)
        return json.loads(path.read_text(encoding="utf-8"))

    def shacl(self, uri):
        entry = self._entry(uri)
        if not entry or not entry.get("shacl"):
            return None
        path = (self.base / entry["shacl"]).resolve()
        if self.verbose:
            print(f"  LOCAL shacl:  {path}", file=sys.stderr)
        return path.read_text(encoding="utf-8")


def build_resolver(source, schema_map=None, cache_dir=None,
                   use_accept=False, verbose=False):
    """Construct the schema resolver selected by `source` ('w3id' or
    'local'). For 'local', falls back to DEFAULT_MAP_NAME beside this script
    when schema_map is not given."""
    if source == "local":
        map_path = schema_map or str(Path(__file__).resolve().parent
                                     / DEFAULT_MAP_NAME)
        if not Path(map_path).exists():
            raise FileNotFoundError(
                f"Local schema map not found: {map_path} "
                f"(pass --schema-map or create {DEFAULT_MAP_NAME})")
        return LocalResolver(map_path, verbose=verbose)
    return W3idResolver(cache_dir=cache_dir, use_accept=use_accept,
                        verbose=verbose)


# ---------------------------------------------------------------------------
# Validation engine — pure function, returns JSON-serializable results
# ---------------------------------------------------------------------------

def run_conformance(doc, resolver, do_schema=True, do_shacl=True,
                    frame=None, verbose=False):
    """Validate one CDIF JSON-LD document against every profile it claims.

    Discovers conformsTo URIs from the catalog record, frames the document
    once (for JSON Schema), then validates against each profile's schema and
    SHACL via `resolver`. Returns:

        {
          "conformsTo": [uri, ...],          # discovered, ignored-prefix filtered
          "profiles": [
            {"uri": uri,
             "schema": {"status": <s>, "errors": [...]},
             "shacl":  {"status": <s>, "errors": [...]}},
            ...
          ],
          "total_violations": int,
        }

    status values: passed | failed | skipped | no_schema | no_shacl |
    not_installed | error. The function never prints and never exits — it is
    safe to import and call from a web application.
    """
    uris = [u for u in extract_conforms_to(doc) if not is_ignored_uri(u)]

    framed = None
    frame_error = None
    if do_schema and uris:
        try:
            framed = frame_doc(doc, frame or DEFAULT_FRAME)
        except Exception as e:
            frame_error = f"Framing error: {e}"

    result = {"conformsTo": uris, "profiles": [], "total_violations": 0}

    for uri in uris:
        if verbose:
            print(f"\nResolving artifacts for {uri}...", file=sys.stderr)

        # --- JSON Schema pass ---
        if not do_schema:
            schema_res = {"status": "skipped", "errors": []}
        elif frame_error:
            schema_res = {"status": "error",
                          "errors": [{"path": "/", "message": frame_error,
                                      "validator": "frame"}]}
        else:
            try:
                schema = resolver.schema(uri)
                if schema is None:
                    schema_res = {"status": "no_schema", "errors": []}
                else:
                    errs = validate_with_jsonschema(framed, schema)
                    schema_res = {"status": "passed" if not errs else "failed",
                                  "errors": errs}
            except Exception as e:
                schema_res = {"status": "error",
                              "errors": [{"path": "/", "message":
                                          f"Schema resolve/validate error: {e}",
                                          "validator": "resolve"}]}

        # --- SHACL pass ---
        if not do_shacl:
            shacl_res = {"status": "skipped", "errors": []}
        elif not HAS_PYSHACL:
            shacl_res = {"status": "not_installed", "errors": []}
        else:
            try:
                shacl_text = resolver.shacl(uri)
                if shacl_text is None:
                    shacl_res = {"status": "no_shacl", "errors": []}
                else:
                    errs = validate_with_shacl(doc, shacl_text)
                    real = [e for e in errs if not e.get("skipped")]
                    shacl_res = {"status": "passed" if not real else "failed",
                                 "errors": real}
            except Exception as e:
                shacl_res = {"status": "error",
                             "errors": [{"message":
                                         f"SHACL resolve/validate error: {e}"}]}

        result["profiles"].append({"uri": uri, "schema": schema_res,
                                   "shacl": shacl_res})
        result["total_violations"] += (len(schema_res["errors"])
                                       + len(shacl_res["errors"]))

    return result


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def short_uri(uri):
    """Compact a conformsTo URI for table/line display."""
    return uri.split("/cdif/", 1)[-1] if "/cdif/" in uri else uri


def _profile_violations(prof):
    return len(prof["schema"]["errors"]) + len(prof["shacl"]["errors"])


def print_profile_section(prof):
    """Print one per-profile section for single-file mode."""
    print(f"\n{'='*70}")
    print(f"Profile: {prof['uri']}")
    print(f"{'='*70}")

    s = prof["schema"]
    if s["status"] == "skipped":
        print("\n  JSON Schema: skipped (--no-schema)")
    elif s["status"] == "no_schema":
        print("\n  JSON Schema: no schema mapped for this URI")
    elif s["status"] == "passed":
        print("\n  JSON Schema: PASSED")
    elif s["status"] == "error":
        print("\n  JSON Schema: ERROR")
        for e in s["errors"]:
            print(f"    - {e.get('path','/')}: {e['message']}")
    else:
        print(f"\n  JSON Schema: {len(s['errors'])} violation(s)")
        for e in s["errors"]:
            print(f"    - {e['path']}: {e['message']}")

    sh = prof["shacl"]
    if sh["status"] == "skipped":
        print("\n  SHACL: skipped (--no-shacl)")
    elif sh["status"] == "not_installed":
        print("\n  SHACL: skipped (pyshacl not installed)")
    elif sh["status"] == "no_shacl":
        print("\n  SHACL: no shapes mapped for this URI")
    elif sh["status"] == "passed":
        print("\n  SHACL: PASSED")
    elif sh["status"] == "error":
        print("\n  SHACL: ERROR")
        for e in sh["errors"]:
            print(f"    - {e.get('message','(no message)')}")
    else:
        print(f"\n  SHACL: {len(sh['errors'])} violation(s)")
        for e in sh["errors"]:
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


def report_single(result):
    """Print the full per-profile report for one document; return exit code."""
    for prof in result["profiles"]:
        print_profile_section(prof)

    print(f"\n{'='*70}")
    print(f"Summary: {len(result['profiles'])} profile(s) checked, "
          f"{result['total_violations']} total violation(s)")
    print(f"{'='*70}")
    return 0 if result["total_violations"] == 0 else 1


# ---------------------------------------------------------------------------
# Batch mode
# ---------------------------------------------------------------------------

def run_batch(directory, resolver, do_schema, do_shacl, frame,
              summary=False, verbose=False):
    """Validate every *.json / *.jsonld file in `directory`, printing a
    per-file line plus an aggregate summary. Returns an exit code."""
    files = sorted(glob.glob(os.path.join(directory, "*.json")) +
                   glob.glob(os.path.join(directory, "*.jsonld")))
    if not files:
        print(f"No JSON/JSONLD files found in {directory}")
        return 1

    profile_stats = {}                 # uri -> {pass, fail, sample_errors}
    error_patterns = Counter()         # (profile, path, msg) -> count
    file_count = 0
    all_pass_count = 0

    for filepath in files:
        filename = os.path.basename(filepath)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                doc = json.load(f)
        except Exception as e:
            print(f"ERROR reading {filename}: {e}")
            continue

        result = run_conformance(doc, resolver, do_schema, do_shacl,
                                 frame, verbose=False)
        if not result["profiles"]:
            if not summary:
                print(f"SKIP  {filename} (no conformsTo)")
            continue

        file_count += 1
        file_pass = result["total_violations"] == 0
        if file_pass:
            all_pass_count += 1

        statuses = []
        for prof in result["profiles"]:
            uri = prof["uri"]
            short = short_uri(uri)
            viol = _profile_violations(prof)
            stats = profile_stats.setdefault(
                uri, {"pass": 0, "fail": 0, "sample_errors": []})
            if (prof["schema"]["status"] == "no_schema"
                    and prof["shacl"]["status"] in ("no_shacl", "skipped",
                                                    "not_installed")):
                statuses.append(f"{short}:NO_SCHEMA")
                continue
            if viol:
                stats["fail"] += 1
                statuses.append(f"{short}:{viol}err")
                for e in (prof["schema"]["errors"]):
                    error_patterns[(short, e.get("path", "/"),
                                    e.get("message", "")[:80])] += 1
                for e in (prof["shacl"]["errors"]):
                    error_patterns[(short, e.get("Result Path", "") or "(shacl)",
                                    (e.get("Message") or e.get("message")
                                     or "")[:80])] += 1
                if len(stats["sample_errors"]) < 3:
                    stats["sample_errors"].append((filename, prof))
            else:
                stats["pass"] += 1
                statuses.append(f"{short}:PASS")

        if not summary:
            label = "PASS" if file_pass else "FAIL"
            print(f"{label}  {filename}  [{', '.join(statuses)}]")
            if verbose and not file_pass:
                for prof in result["profiles"]:
                    if _profile_violations(prof):
                        print_profile_section(prof)

    print(f"\n{'='*70}")
    print("PROFILE VALIDATION SUMMARY")
    print(f"{'='*70}")
    for uri in sorted(profile_stats.keys()):
        r = profile_stats[uri]
        total = r["pass"] + r["fail"]
        pct = r["pass"] / total * 100 if total else 0
        print(f"  {short_uri(uri):35s}  {r['pass']:3d} pass  {r['fail']:3d} fail"
              f"  ({pct:.0f}% of {total})")

    print(f"\nFiles: {file_count} validated, {all_pass_count} all-pass, "
          f"{file_count - all_pass_count} with failures")

    print(f"\n{'='*70}")
    print("DISTINCT ERROR PATTERNS (across all files and profiles)")
    print(f"{'='*70}")
    for (profile, path, msg), count in error_patterns.most_common(20):
        print(f"  ({count:3d}x) [{profile}] {path}: {msg}...")

    return 0 if all_pass_count == file_count else 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Validate a CDIF JSON-LD instance (or a directory of them) "
                    "against the conformance URIs declared in its "
                    "schema:subjectOf catalog record.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
For each dcterms:conformsTo URI in the document, this tool:
  1. Resolves the JSON Schema (w3id <URI>/schema, or a local map entry)
  2. Resolves the SHACL rules (w3id <URI>/shacl, or a local map entry)
  3. Validates the document against both
  4. Prints a per-profile (single file) or aggregate (directory) report

Schema sources (--source):
  w3id   fetch from the w3id.org/cdif redirector (default; needs network)
  local  look up local schemas via --schema-map (default:
         conformance-schema-map.json beside this script)

Examples:
  python ConformanceValidate.py myrecord.jsonld
  python ConformanceValidate.py myrecord.jsonld --source local
  python ConformanceValidate.py myrecord.jsonld --verbose --cache-dir .cache
  python ConformanceValidate.py ./testJSONMetadata --source local --summary
""")
    parser.add_argument("input", help="Input JSON-LD file or directory")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--source", choices=["w3id", "local"], default="w3id",
                        help="Schema source: w3id redirector (default) or "
                             "local map file")
    parser.add_argument("--schema-map",
                        help="Path to the local URI->schema/SHACL JSON map "
                             "(used with --source local; default: "
                             f"{DEFAULT_MAP_NAME} beside this script)")
    parser.add_argument("--no-schema", action="store_true",
                        help="Skip JSON Schema validation pass")
    parser.add_argument("--no-shacl", action="store_true",
                        help="Skip SHACL validation pass")
    parser.add_argument("--summary", "-s", action="store_true",
                        help="Directory mode: print only the aggregate summary")
    parser.add_argument("--frame",
                        help="Custom JSON-LD frame (default: minimal "
                             "schema:Dataset frame)")
    parser.add_argument("--cache-dir",
                        help="Directory for caching fetched schema/SHACL files "
                             "between runs (w3id source only)")
    parser.add_argument("--use-accept", action="store_true",
                        help="Use Accept-header content negotiation on the "
                             "bare conformance URI instead of /schema and "
                             "/shacl sub-paths (w3id source only)")
    args = parser.parse_args()

    try:
        resolver = build_resolver(args.source, args.schema_map,
                                  args.cache_dir, args.use_accept, args.verbose)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)

    frame = None
    if args.frame:
        with open(args.frame, "r", encoding="utf-8") as f:
            frame = json.load(f)

    do_schema = not args.no_schema
    do_shacl = not args.no_shacl

    # Directory -> batch mode; file -> single-document report.
    if os.path.isdir(args.input):
        sys.exit(run_batch(args.input, resolver, do_schema, do_shacl, frame,
                           summary=args.summary, verbose=args.verbose))

    with open(args.input, "r", encoding="utf-8") as f:
        doc = json.load(f)

    if args.verbose:
        discovered = [u for u in extract_conforms_to(doc)
                      if not is_ignored_uri(u)]
        print(f"Discovered {len(discovered)} conformance URI(s):",
              file=sys.stderr)
        for u in discovered:
            print(f"  - {u}", file=sys.stderr)

    result = run_conformance(doc, resolver, do_schema, do_shacl, frame,
                             verbose=args.verbose)
    if not result["profiles"]:
        print("ERROR: No dcterms:conformsTo URIs found in schema:subjectOf.",
              file=sys.stderr)
        print("       The instance must include a catalog record with at "
              "least one conformsTo URI.", file=sys.stderr)
        sys.exit(2)

    sys.exit(report_single(result))


if __name__ == "__main__":
    main()
