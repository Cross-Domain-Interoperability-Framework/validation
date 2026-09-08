#!/usr/bin/env python3
"""
RO-Crate to CDIF JSON-LD Converter

Converts an RO-Crate 1.2 JSON-LD document (flattened @graph) into a CDIF-compliant
nested JSON-LD document suitable for validation against CDIF schemas.

Key mappings performed:
  - Finds the root Dataset entity in @graph
  - Resolves all @id references to inline nested objects
  - Maps hasPart DataDownload items to schema:distribution
  - Creates schema:subjectOf from the RO-Crate metadata descriptor
  - Compacts output with CDIF-prefixed context (schema:, prov:, etc.)

Usage:
    python ROCrateToCDIF.py input-rocrate.jsonld -o output-cdif.json
    python ROCrateToCDIF.py input-rocrate.jsonld -o output.json --profile core
    python ROCrateToCDIF.py input-rocrate.jsonld -o output.json -v --validate
"""

import json
import argparse
import sys
from pathlib import Path
from pyld import jsonld

# Configure the requests-based document loader
jsonld.set_document_loader(jsonld.requests_document_loader())

SCRIPT_DIR = Path(__file__).parent

# CDIF profile URIs. The catalog-record's dcterms:conformsTo gets stamped
# with whichever URI the user picks via --profile. The converter does NOT
# infer the closest-matching profile from document content; the URI is a
# declarative claim that the user (or upstream tooling) is responsible for.
# Default is "core" because it is the minimal common subset — claiming only
# core is the safest assertion in the absence of a stronger signal.
CDIF_PROFILES = {
    "core": "https://w3id.org/cdif/core/1.1",
    "discovery": "https://w3id.org/cdif/discovery/1.1",
    "complete": "https://w3id.org/cdif/complete/1.1",
}

# Output context for CDIF compaction — uses prefixed namespaces
CDIF_OUTPUT_CONTEXT = {
    "schema": "http://schema.org/",
    "dcterms": "http://purl.org/dc/terms/",
    "prov": "http://www.w3.org/ns/prov#",
    "dqv": "http://www.w3.org/ns/dqv#",
    "dcat": "http://www.w3.org/ns/dcat#",
    "geosparql": "http://www.opengis.net/ont/geosparql#",
    "spdx": "http://spdx.org/rdf/terms#",
    "time": "http://www.w3.org/2006/time#",
    "sf": "http://www.opengis.net/ont/sf#",
    "cdi": "http://ddialliance.org/Specification/DDI-CDI/1.0/RDF/",
    "csvw": "http://www.w3.org/ns/csvw#",
    "nxs": "https://manual.nexusformat.org/classes/",
}

# Properties that should always be arrays per the CDIF schema
ARRAY_PROPERTIES = {
    "schema:contributor",
    "schema:distribution",
    "schema:license",
    "schema:conditionsOfAccess",
    "schema:keywords",
    "schema:additionalType",
    "schema:sameAs",
    "schema:provider",
    "schema:funding",
    "schema:variableMeasured",
    "schema:spatialCoverage",
    "schema:temporalCoverage",
    "schema:relatedLink",
    "schema:publishingPrinciples",
    "schema:encodingFormat",
    "schema:potentialAction",
    "schema:httpMethod",
    "schema:contentType",
    "schema:query-input",
    "prov:wasGeneratedBy",
    "prov:wasDerivedFrom",
    "prov:used",
    "dqv:hasQualityMeasurement",
    "dcterms:conformsTo",
    "cdi:hasPhysicalMapping",
    "cdi:uses",
}

# RO-Crate type strings that indicate DataDownload (may appear unprefixed or prefixed)
DATADOWNLOAD_TYPES = {"DataDownload", "schema:DataDownload", "http://schema.org/DataDownload"}

# Frame for extracting the root Dataset
FRAME_TEMPLATE = {
    "@type": "http://schema.org/Dataset",
    "@embed": "@always",
}


def _build_entity_index(graph):
    """Build a dict mapping @id -> entity object from the @graph array."""
    index = {}
    for entity in graph:
        eid = entity.get("@id")
        if eid:
            index[eid] = entity
    return index


def _find_root_dataset(graph):
    """Find the root Dataset entity in the @graph.

    Heuristic: look for the entity that the metadata descriptor's 'about' points to,
    or fall back to the first Dataset entity.
    """
    dataset_types = {"Dataset", "schema:Dataset",
                     "http://schema.org/Dataset", "https://schema.org/Dataset"}

    # First, find what the metadata descriptor points to
    about_id = None
    for entity in graph:
        eid = entity.get("@id", "")
        if eid in ("ro-crate-metadata.json", "ro-crate-metadata.jsonld"):
            about = entity.get("about", {})
            if isinstance(about, dict):
                about_id = about.get("@id")
            elif isinstance(about, str):
                about_id = about
            break

    # Find the referenced dataset, or first Dataset
    fallback = None
    for entity in graph:
        etype = entity.get("@type", [])
        if isinstance(etype, str):
            etype = [etype]
        if dataset_types.intersection(etype):
            if entity.get("@id") == about_id:
                return entity
            if fallback is None:
                fallback = entity

    return fallback


def _find_metadata_descriptor(graph):
    """Find the RO-Crate metadata descriptor entity."""
    for entity in graph:
        eid = entity.get("@id", "")
        if eid in ("ro-crate-metadata.json", "ro-crate-metadata.jsonld"):
            return entity
    return None


def _has_datadownload_type(entity):
    """Check if an entity has a DataDownload @type."""
    etype = entity.get("@type", [])
    if isinstance(etype, str):
        etype = [etype]
    return bool(DATADOWNLOAD_TYPES.intersection(etype))


def convert_rocrate_to_cdif(doc, profile="core", verbose=False):
    """Convert an RO-Crate document to CDIF JSON-LD.

    Steps:
    1. Expand the document to resolve all prefixes
    2. Frame around schema:Dataset to get a nested structure
    3. Compact with CDIF output context
    4. Post-process: map hasPart DataDownloads to distribution,
       create subjectOf from metadata descriptor, normalize arrays
    """
    if verbose:
        print("Step 1: Expanding document...", file=sys.stderr)
    expanded = jsonld.expand(doc)

    if verbose:
        print("Step 2: Framing around schema:Dataset...", file=sys.stderr)
    framed = jsonld.frame(expanded, FRAME_TEMPLATE)

    if verbose:
        print("Step 3: Compacting with CDIF context...", file=sys.stderr)
    compacted = jsonld.compact(framed, CDIF_OUTPUT_CONTEXT)

    # Extract main dataset from @graph if present
    result = compacted
    if "@graph" in compacted and isinstance(compacted["@graph"], list):
        dataset = _pick_main_dataset(compacted["@graph"])
        if dataset:
            result = {"@context": compacted.get("@context"), **dataset}

    if verbose:
        print("Step 4: Post-processing...", file=sys.stderr)

    # Map hasPart DataDownloads → distribution
    result = _move_downloads_to_distribution(result)

    # Create subjectOf from original @graph metadata descriptor
    # (also moves includedInDataCatalog from top-level into subjectOf)
    result = _create_subject_of(result, doc, profile)

    # Remove includedInDataCatalog from top level (belongs in subjectOf only)
    result.pop("schema:includedInDataCatalog", None)

    # Remove from top-level hasPart any items already inside distribution.hasPart
    result = _dedup_haspart_from_distribution(result)

    # Wrap any loose MediaObjects (RO-Crate puts files in hasPart without
    # typing them as DataDownload) into a synthetic DataDownload in
    # schema:distribution, so the result matches CDIF's archive-distribution
    # pattern.
    result = _wrap_loose_mediaobjects(result)

    # CDIF requires schema:dateModified; RO-Crate only requires schema:datePublished.
    # If dateModified is absent, fall back to datePublished.
    _ensure_date_modified(result)

    # Normalize: remove nulls, ensure arrays, normalize @type
    result = _normalize(result)

    return result


def _ensure_date_modified(result):
    """If schema:dateModified is missing but schema:datePublished is present,
    copy datePublished into dateModified. CDIF requires dateModified; RO-Crate
    only requires datePublished, so this lets RO-Crate-sourced documents pass
    CDIF validation without dropping the original datePublished."""
    if not isinstance(result, dict):
        return
    if result.get("schema:dateModified"):
        return
    pub = result.get("schema:datePublished")
    if pub:
        result["schema:dateModified"] = pub


def _pick_main_dataset(graph):
    """From a framed @graph, pick the main dataset entity."""
    # Prefer the one with distribution or hasPart
    for item in graph:
        if item.get("schema:distribution") or item.get("schema:hasPart"):
            return item
    # Fallback: first with schema:url, or just first
    for item in graph:
        if item.get("schema:url"):
            return item
    return graph[0] if graph else None


def _move_downloads_to_distribution(result):
    """Move DataDownload items from schema:hasPart to schema:distribution.

    In RO-Crate, files are listed in hasPart. In CDIF, DataDownload items
    belong in schema:distribution. Non-DataDownload items stay in hasPart.
    """
    has_part = result.get("schema:hasPart")
    if not has_part:
        return result

    if isinstance(has_part, dict):
        has_part = [has_part]

    downloads = []
    remaining = []

    for item in has_part:
        if isinstance(item, dict):
            etype = item.get("@type", [])
            if isinstance(etype, str):
                etype = [etype]
            if DATADOWNLOAD_TYPES.intersection(etype):
                downloads.append(item)
            else:
                remaining.append(item)
        else:
            remaining.append(item)

    if downloads:
        # Get existing distributions
        existing = result.get("schema:distribution", [])
        if isinstance(existing, dict):
            existing = [existing]
        elif existing is None:
            existing = []

        # Merge, deduplicating by @id
        all_dists = existing + downloads
        seen_ids = set()
        deduped = []
        for d in all_dists:
            did = d.get("@id") if isinstance(d, dict) else None
            if did and did in seen_ids:
                continue
            if did:
                seen_ids.add(did)
            deduped.append(d)

        result["schema:distribution"] = deduped

        if remaining:
            result["schema:hasPart"] = remaining
        else:
            del result["schema:hasPart"]

    return result


def _wrap_loose_mediaobjects(result):
    """Wrap loose MediaObject entries in schema:hasPart into a synthetic
    DataDownload added to schema:distribution.

    RO-Crate files appear in hasPart as schema:MediaObject (no DataDownload
    type) when the source crate doesn't model an explicit archive. CDIF's
    archive-distribution pattern expects them inside a DataDownload's
    schema:hasPart. This function rebuilds that structure.

    Behavior:
    - Find MediaObject entries in top-level schema:hasPart that are NOT also
      typed DataDownload.
    - If none, do nothing.
    - Otherwise create one synthetic DataDownload:
        @id: <root @id>#distribution (or "#distribution" if root has no @id)
        @type: ["schema:DataDownload"]
        schema:hasPart: the loose MediaObjects
        schema:contentUrl: the single MediaObject's @id, if exactly one
                           loose MediaObject is being wrapped
                           (multi-file archive: omitted — unknown URL)
    - Append the synthetic DataDownload to schema:distribution.
    - Remove the wrapped MediaObjects from top-level schema:hasPart.
    """
    if not isinstance(result, dict):
        return result

    has_part = result.get("schema:hasPart")
    if not has_part:
        return result
    if isinstance(has_part, dict):
        has_part = [has_part]

    media_types = {"schema:MediaObject", "MediaObject",
                   "http://schema.org/MediaObject"}

    loose = []
    keep = []
    for item in has_part:
        if not isinstance(item, dict):
            keep.append(item)
            continue
        etype = item.get("@type", [])
        if isinstance(etype, str):
            etype = [etype]
        is_media = bool(media_types.intersection(etype))
        is_download = bool(DATADOWNLOAD_TYPES.intersection(etype))
        if is_media and not is_download:
            loose.append(item)
        else:
            keep.append(item)

    if not loose:
        return result

    # Build the synthetic DataDownload
    root_id = result.get("@id", "")
    synthetic_id = (root_id + "#distribution") if root_id else "#distribution"
    synthetic = {
        "@id": synthetic_id,
        "@type": ["schema:DataDownload"],
        "schema:hasPart": loose,
    }
    if len(loose) == 1:
        single_id = loose[0].get("@id")
        if single_id:
            synthetic["schema:contentUrl"] = single_id

    # Append to existing distribution(s)
    existing = result.get("schema:distribution", [])
    if isinstance(existing, dict):
        existing = [existing]
    elif existing is None:
        existing = []
    result["schema:distribution"] = existing + [synthetic]

    # Strip wrapped MediaObjects from top-level hasPart
    if keep:
        result["schema:hasPart"] = keep
    else:
        result.pop("schema:hasPart", None)

    return result


def _collect_ids(obj):
    """Recursively collect all @id values from a nested structure."""
    ids = set()
    if isinstance(obj, dict):
        if "@id" in obj:
            ids.add(obj["@id"])
        for v in obj.values():
            ids.update(_collect_ids(v))
    elif isinstance(obj, list):
        for item in obj:
            ids.update(_collect_ids(item))
    return ids


def _dedup_haspart_from_distribution(result):
    """Remove top-level hasPart items that already appear inside distribution.hasPart.

    When an RO-Crate is flattened, archive component files end up both in the root
    Dataset's hasPart and inside the DataDownload's hasPart. After framing back to
    CDIF, both locations get populated. This removes the duplicates from the top level.
    Also removes the subjectOf/catalog record entity from hasPart if present.
    """
    has_part = result.get("schema:hasPart")
    if not has_part:
        return result

    if isinstance(has_part, dict):
        has_part = [has_part]

    # Collect @ids of all items nested inside distribution hasPart
    dist_child_ids = set()
    distributions = result.get("schema:distribution", [])
    if isinstance(distributions, dict):
        distributions = [distributions]
    for dist in distributions:
        if isinstance(dist, dict):
            dist_parts = dist.get("schema:hasPart", [])
            if isinstance(dist_parts, dict):
                dist_parts = [dist_parts]
            for part in dist_parts:
                if isinstance(part, dict) and "@id" in part:
                    dist_child_ids.add(part["@id"])

    # Also collect @id of subjectOf (catalog record shouldn't be in hasPart)
    subject_of = result.get("schema:subjectOf")
    if isinstance(subject_of, dict) and "@id" in subject_of:
        dist_child_ids.add(subject_of["@id"])

    # Also exclude the DataDownload distribution itself from hasPart
    for dist in distributions:
        if isinstance(dist, dict) and "@id" in dist:
            dist_child_ids.add(dist["@id"])

    # Filter top-level hasPart
    filtered = []
    for item in has_part:
        item_id = item.get("@id") if isinstance(item, dict) else None
        if item_id and item_id in dist_child_ids:
            continue
        filtered.append(item)

    if filtered:
        result["schema:hasPart"] = filtered
    elif "schema:hasPart" in result:
        del result["schema:hasPart"]

    return result


def _create_subject_of(result, original_doc, profile):
    """Create schema:subjectOf from the RO-Crate metadata descriptor.

    The RO-Crate metadata descriptor (ro-crate-metadata.json) is a CreativeWork
    that describes the dataset. In CDIF, this maps to schema:subjectOf — a
    catalog record about the dataset.
    """
    # Don't overwrite if subjectOf already exists
    if result.get("schema:subjectOf"):
        return result

    # Get the dataset @id from the result
    dataset_id = result.get("@id", "./")

    # Look for metadata from the original RO-Crate document
    descriptor = None
    included_in_catalog = None

    if "@graph" in original_doc:
        graph = original_doc["@graph"]
        entity_index = _build_entity_index(graph)

        # Find the metadata descriptor
        descriptor = _find_metadata_descriptor(graph)

        # Find the root dataset to extract includedInDataCatalog
        root = _find_root_dataset(graph)
        if root:
            catalog_ref = root.get("includedInDataCatalog")
            if isinstance(catalog_ref, dict) and "@id" in catalog_ref:
                catalog_entity = entity_index.get(catalog_ref["@id"])
                if catalog_entity:
                    cat_url = catalog_entity.get("url", catalog_entity.get("schema:url", ""))
                    cat_name = catalog_entity.get("name", catalog_entity.get("schema:name", ""))
                    # Use URL as @id if available (avoids blank node IDs)
                    cat_id = cat_url or catalog_entity.get("@id", "")
                    included_in_catalog = {
                        "@id": cat_id,
                        "@type": "schema:DataCatalog",
                        "schema:name": cat_name,
                    }
                    if cat_url:
                        included_in_catalog["schema:url"] = cat_url
            elif isinstance(catalog_ref, dict):
                # Inline catalog object
                cat_url = catalog_ref.get("url", catalog_ref.get("schema:url", ""))
                cat_name = catalog_ref.get("name", catalog_ref.get("schema:name", ""))
                cat_id = cat_url or catalog_ref.get("@id", "")
                included_in_catalog = {
                    "@id": cat_id,
                    "@type": "schema:DataCatalog",
                    "schema:name": cat_name,
                }
                if cat_url:
                    included_in_catalog["schema:url"] = cat_url

    # Also check the compacted result for includedInDataCatalog
    if not included_in_catalog and result.get("schema:includedInDataCatalog"):
        cat = result["schema:includedInDataCatalog"]
        included_in_catalog = {
            "@id": cat.get("@id", ""),
            "@type": "schema:DataCatalog",
            "schema:name": cat.get("schema:name", ""),
        }
        if cat.get("schema:url"):
            included_in_catalog["schema:url"] = cat["schema:url"]
        # Remove from top-level (it belongs in subjectOf)
        del result["schema:includedInDataCatalog"]

    # Build the profile conformsTo URI
    profile_uri = CDIF_PROFILES.get(profile, CDIF_PROFILES["core"])

    # Construct subjectOf
    subject_of = {
        "@type": ["schema:Dataset"],
        "schema:additionalType": ["dcat:CatalogRecord"],
        "@id": descriptor.get("@id", "ro-crate-metadata.json") if descriptor else "ro-crate-metadata.json",
        "schema:about": {"@id": dataset_id},
        "dcterms:conformsTo": [{"@id": profile_uri}],
    }

    if included_in_catalog:
        subject_of["schema:includedInDataCatalog"] = included_in_catalog

    result["schema:subjectOf"] = subject_of

    return result


def _normalize(obj):
    """Post-process: remove nulls, normalize @type to array, ensure array properties."""
    if isinstance(obj, list):
        return [_normalize(item) for item in obj if item is not None]

    if isinstance(obj, dict):
        result = {}
        for key, value in obj.items():
            if value is None:
                continue
            if key == "@context":
                result[key] = value
                continue

            new_value = _normalize(value)
            if new_value is None:
                continue

            # @type should always be an array
            if key == "@type" and isinstance(new_value, str):
                new_value = [new_value]

            # Wrap single values where schema expects arrays
            if key in ARRAY_PROPERTIES and not isinstance(new_value, list):
                new_value = [new_value]

            result[key] = new_value
        return result

    return obj


def _load_schema(schema_path):
    """Load a JSON Schema from a local path or URL."""
    if schema_path.startswith(("http://", "https://")):
        import urllib.request
        print(f"Fetching schema: {schema_path}", file=sys.stderr)
        with urllib.request.urlopen(schema_path) as resp:
            return json.loads(resp.read().decode("utf-8"))
    else:
        print(f"Loading schema: {schema_path}", file=sys.stderr)
        with open(schema_path, "r", encoding="utf-8") as f:
            return json.load(f)


def validate_against_schema(framed, schema_path):
    """Validate framed document against JSON Schema."""
    from jsonschema import Draft202012Validator

    schema = _load_schema(schema_path)

    validator = Draft202012Validator(schema)
    errors = list(validator.iter_errors(framed))

    return {"valid": len(errors) == 0, "errors": errors}


def main():
    parser = argparse.ArgumentParser(
        description="Convert RO-Crate JSON-LD to CDIF JSON-LD",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Convert RO-Crate to CDIF and save
  python ROCrateToCDIF.py my-rocrate.jsonld -o cdif-output.json

  # Convert with verbose output
  python ROCrateToCDIF.py my-rocrate.jsonld -o cdif-output.json -v

  # Convert and validate against CDIF Complete schema
  python ROCrateToCDIF.py my-rocrate.jsonld -o cdif-output.json -v --validate

  # Convert targeting CDIF Discovery profile
  python ROCrateToCDIF.py my-rocrate.jsonld -o cdif-output.json --profile discovery
""",
    )
    parser.add_argument("input", help="Input RO-Crate JSON-LD file")
    parser.add_argument("-o", "--output", help="Write CDIF output to file")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show progress")
    parser.add_argument(
        "--profile",
        choices=["core", "discovery", "complete"],
        default="core",
        help="CDIF profile asserted in subjectOf/dcterms:conformsTo "
             "(default: core — the minimal common subset; use --profile to "
             "assert a richer profile)",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate output against CDIF schema",
    )
    parser.add_argument(
        "--schema",
        default=None,
        help="Path to JSON Schema for validation (default: auto-select based on profile)",
    )

    args = parser.parse_args()

    try:
        if args.verbose:
            print(f"Loading: {args.input}", file=sys.stderr)
        with open(args.input, "r", encoding="utf-8") as f:
            doc = json.load(f)

        cdif = convert_rocrate_to_cdif(doc, profile=args.profile, verbose=args.verbose)

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(cdif, f, indent=2)
            if args.verbose:
                print(f"CDIF output written to: {args.output}", file=sys.stderr)
        elif not args.validate:
            print(json.dumps(cdif, indent=2))

        if args.validate:
            if args.schema:
                schema_path = args.schema
            else:
                # Per-profile schema lookup. The validation repo holds the
                # Discovery and Complete validation schemas; the canonical
                # cdifCore schema lives in the profile-core release repo
                # (no CDIFCoreSchema.json in the validation repo today).
                validation_dir = SCRIPT_DIR / ".." / ".." / "validation"
                profile_core_dir = SCRIPT_DIR / ".." / ".." / "profile-core"
                schema_filenames = {
                    "core": "cdifCoreStructuredSchema.json",
                    "discovery": "CDIFDiscoverySchema.json",
                    "complete": "CDIFCompleteSchema.json",
                }
                filename = schema_filenames[args.profile]
                # core: prefer sibling profile-core; others: validation repo
                if args.profile == "core":
                    candidate_dirs = [profile_core_dir, validation_dir]
                else:
                    candidate_dirs = [validation_dir]
                schema_path = None
                for d in candidate_dirs:
                    p = (d / filename).resolve()
                    if p.exists():
                        schema_path = str(p)
                        break
                if schema_path is None:
                    # Last resort: fetch from the validation repo on GitHub.
                    # For --profile core this will likely 404; pass --schema
                    # explicitly in that case.
                    schema_path = (
                        "https://raw.githubusercontent.com/"
                        "Cross-Domain-Interoperability-Framework/validation/"
                        f"refs/heads/main/{filename}"
                    )
                    if args.verbose:
                        print(f"Local schema not found, fetching from GitHub", file=sys.stderr)

            result = validate_against_schema(cdif, schema_path)
            if result["valid"]:
                print("Validation PASSED", file=sys.stderr)
            else:
                print("Validation FAILED", file=sys.stderr)
                for error in result["errors"]:
                    path = (
                        "/" + "/".join(str(p) for p in error.absolute_path)
                        if error.absolute_path
                        else "/"
                    )
                    print(f"  - {path}: {error.message}", file=sys.stderr)
                sys.exit(1)

        if args.verbose:
            print("Done!", file=sys.stderr)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
