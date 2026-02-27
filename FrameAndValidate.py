#!/usr/bin/env python3
"""
CDIF JSON-LD Framing and Validation Script

Supports both the original schema and the 2026 schema with DDI-CDI and CSVW extensions.

Usage:
    python FrameAndValidate.py <input-document.jsonld> [--output framed.json] [--validate] [--schema schema.json] [--frame frame.jsonld]
"""

import json
import argparse
import sys
from pathlib import Path
from pyld import jsonld
import jsonschema
from jsonschema import Draft202012Validator

# Configure the requests-based document loader
jsonld.set_document_loader(jsonld.requests_document_loader())

SCRIPT_DIR = Path(__file__).parent

# Properties that should always be arrays per the CDIF schema
# Includes both original properties and 2026 DDI-CDI/CSVW additions
ARRAY_PROPERTIES = [
    # schema.org properties
    'schema:contributor',
    'schema:distribution',
    'schema:license',
    'schema:conditionsOfAccess',
    'schema:keywords',
    'schema:additionalType',
    'schema:sameAs',
    'schema:provider',
    'schema:funding',
    'schema:variableMeasured',
    'schema:spatialCoverage',
    'schema:temporalCoverage',
    'schema:relatedLink',
    'schema:publishingPrinciples',
    'schema:encodingFormat',
    'schema:potentialAction',
    'schema:httpMethod',
    'schema:contentType',
    'schema:query-input',
    # PROV properties
    'prov:wasGeneratedBy',
    'prov:wasDerivedFrom',
    'prov:used',
    # DQV properties
    'dqv:hasQualityMeasurement',
    # Dublin Core properties
    'dcterms:conformsTo',
    # DDI-CDI properties (2026)
    'cdi:hasPhysicalMapping',
    'cdi:uses',
]

# Term mappings: unprefixed -> prefixed (to match schema expectations)
TERM_MAPPINGS = {
    'conformsTo': 'dcterms:conformsTo',
    'wasGeneratedBy': 'prov:wasGeneratedBy',
    'wasDerivedFrom': 'prov:wasDerivedFrom',
    'used': 'prov:used',
    'hasQualityMeasurement': 'dqv:hasQualityMeasurement',
    'isMeasurementOf': 'dqv:isMeasurementOf',
    'hasGeometry': 'geosparql:hasGeometry',
    'asWKT': 'geosparql:asWKT',
    'checksum': 'spdx:checksum',
    'algorithm': 'spdx:algorithm',
    'checksumValue': 'spdx:checksumValue',
    'hasBeginning': 'time:hasBeginning',
    'hasEnd': 'time:hasEnd',
    'inTimePosition': 'time:inTimePosition',
    'hasTRS': 'time:hasTRS',
    'numericPosition': 'time:numericPosition'
}

# Output context for compaction - uses explicit term mappings to avoid prefix conflicts
OUTPUT_CONTEXT = {
    # Namespace prefixes
    "schema": "http://schema.org/",
    "cdi": "http://ddialliance.org/Specification/DDI-CDI/1.0/RDF/",
    "csvw": "http://www.w3.org/ns/csvw#",
    "ada": "https://ada.astromat.org/metadata/",
    "xas": "https://ada.astromat.org/metadata/xas/",
    "nxs": "https://manual.nexusformat.org/classes/",

    # Explicit term mappings for other vocabularies (avoids prefix conflicts)
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
    "hasBeginning": "http://www.w3.org/2006/time#hasBeginning",
    "hasEnd": "http://www.w3.org/2006/time#hasEnd",
    "inTimePosition": "http://www.w3.org/2006/time#inTimePosition",
    "hasTRS": "http://www.w3.org/2006/time#hasTRS",
    "numericPosition": "http://www.w3.org/2006/time#numericPosition",
    "ProperInterval": "http://www.w3.org/2006/time#ProperInterval",
    "Instant": "http://www.w3.org/2006/time#Instant",
    "TimePosition": "http://www.w3.org/2006/time#TimePosition"
}

# Frame without context - uses full IRIs
FRAME_TEMPLATE = {
    "@type": "http://schema.org/Dataset",
    "@embed": "@always"
}


def is_bare_id_reference(obj):
    """Check if an object is a bare @id reference (only has @id property)"""
    if not obj or not isinstance(obj, dict):
        return False
    keys = list(obj.keys())
    return len(keys) == 1 and keys[0] == '@id'


def remove_nulls_and_normalize(obj):
    """
    Post-process the framed output to match schema expectations:
    1. Remove null values (framing adds null for missing optional properties)
    2. Rename unprefixed terms to prefixed versions
    3. Wrap single values in arrays where schema expects arrays
    4. Convert bare @id references to strings for identifier fields
    """
    if isinstance(obj, list):
        # Filter out None values and process remaining items
        return [remove_nulls_and_normalize(item) for item in obj if item is not None]

    if isinstance(obj, dict):
        result = {}

        for key, value in obj.items():
            # Skip null values
            if value is None:
                continue

            # Skip @context - pass through unchanged
            if key == '@context':
                result[key] = value
                continue

            # Rename key if needed
            new_key = TERM_MAPPINGS.get(key, key)

            # Process value recursively
            new_value = remove_nulls_and_normalize(value)

            # Skip if value became None or empty after processing
            if new_value is None:
                continue

            # Convert bare @id references to strings for identifier fields
            if new_key == 'schema:identifier' and is_bare_id_reference(new_value):
                new_value = new_value['@id']

            # Wrap in array if schema expects array and value is not already an array
            if new_key in ARRAY_PROPERTIES and not isinstance(new_value, list):
                new_value = [new_value]

            result[new_key] = new_value

        # Context-aware wrapping for schema:propertyID:
        # Only wrap in array when inside a variableMeasured_type (cdi:InstanceVariable)
        obj_type = result.get('@type', '')
        if isinstance(obj_type, list):
            type_list = obj_type
        else:
            type_list = [obj_type] if obj_type else []
        if 'cdi:InstanceVariable' in type_list:
            pid = result.get('schema:propertyID')
            if pid is not None and not isinstance(pid, list):
                result['schema:propertyID'] = [pid]

        return result

    return obj


def frame_cdif_document(doc_path, frame_path=None):
    """Frame a CDIF JSON-LD document using three-step approach"""
    print(f"Loading document: {doc_path}")
    with open(doc_path, 'r', encoding='utf-8') as f:
        doc = json.load(f)

    # Load custom frame if provided, otherwise use minimal frame template
    if frame_path:
        print(f"Loading frame: {frame_path}")
        with open(frame_path, 'r', encoding='utf-8') as f:
            frame = json.load(f)
    else:
        frame = FRAME_TEMPLATE

    # Step 1: Expand the document (resolves all prefixes to full IRIs)
    print("Expanding document...")
    expanded = jsonld.expand(doc)

    # Step 2: Frame the document
    print("Framing document...")
    framed = jsonld.frame(expanded, frame)

    # Step 3: Compact with our desired output context (if using template frame)
    if not frame_path:
        print("Compacting with output context...")
        framed = jsonld.compact(framed, OUTPUT_CONTEXT)

    # Step 4: Extract main dataset from @graph if present
    result = framed
    if '@graph' in framed and isinstance(framed['@graph'], list):
        # Find the main Dataset object - the one with schema:distribution or schema:url
        dataset = None
        for item in framed['@graph']:
            # Check if this item has distribution (indicates it's the main dataset, not metadata record)
            if item.get('schema:distribution') is not None:
                dataset = item
                break
            # Fallback: check for schema:url
            if item.get('schema:url') is not None and dataset is None:
                dataset = item

        if dataset:
            result = {'@context': framed.get('@context'), **dataset}

    # Step 5: Post-process to remove nulls, normalize terms and array properties
    print("Post-processing output...")
    result = remove_nulls_and_normalize(result)

    # Step 6: Normalize @type to array at root and subjectOf levels
    # (schema requires arrays there, but framing compacts single-element arrays to strings)
    if isinstance(result.get('@type'), str):
        result['@type'] = [result['@type']]
    so = result.get('schema:subjectOf')
    if isinstance(so, dict) and isinstance(so.get('@type'), str):
        so['@type'] = [so['@type']]

    return result


def validate_against_schema(framed, schema_path):
    """Validate framed document against JSON Schema"""
    print(f"Loading schema: {schema_path}")
    with open(schema_path, 'r', encoding='utf-8') as f:
        schema = json.load(f)

    # Use Draft 2020-12 validator
    validator = Draft202012Validator(schema)
    errors = list(validator.iter_errors(framed))

    return {
        'valid': len(errors) == 0,
        'errors': errors
    }


def main():
    parser = argparse.ArgumentParser(
        description='CDIF JSON-LD Framing and Validation Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Frame and print output
  python FrameAndValidate.py my-metadata.jsonld

  # Frame with custom frame and save output
  python FrameAndValidate.py my-metadata.jsonld --frame CDIF-frame-2026.jsonld -o framed.json

  # Validate against 2026 schema
  python FrameAndValidate.py my-metadata.jsonld --frame CDIF-frame-2026.jsonld -v --schema CDIF-JSONLD-schema-2026.json

  # Full workflow with 2026 files
  python FrameAndValidate.py my-metadata.jsonld --frame CDIF-frame-2026.jsonld -o framed.json -v --schema CDIF-JSONLD-schema-2026.json
"""
    )
    parser.add_argument('input', help='Input JSON-LD file to process')
    parser.add_argument('-o', '--output', help='Write framed output to file')
    parser.add_argument('-v', '--validate', action='store_true', help='Validate against JSON Schema')
    parser.add_argument('--schema', default=str(SCRIPT_DIR / 'CDIF-JSONLD-schema-2026.json'),
                        help='Path to JSON Schema (default: CDIF-JSONLD-schema-2026.json)')
    parser.add_argument('--frame', default=str(SCRIPT_DIR / 'CDIF-frame-2026.jsonld'),
                        help='Path to JSON-LD frame (default: CDIF-frame-2026.jsonld)')

    args = parser.parse_args()

    try:
        framed = frame_cdif_document(args.input, args.frame)

        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(framed, f, indent=2)
            print(f"Framed output written to: {args.output}")
        elif not args.validate:
            print("\nFramed output:")
            print(json.dumps(framed, indent=2))

        if args.validate:
            print("\nValidating against schema...")
            result = validate_against_schema(framed, args.schema)

            if result['valid']:
                print("Validation PASSED")
            else:
                print("Validation FAILED")
                print("\nErrors:")
                for error in result['errors']:
                    path = '/'.join(str(p) for p in error.absolute_path) if error.absolute_path else '/'
                    print(f"  - /{path}: {error.message}")
                sys.exit(1)

        print("\nDone!")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
