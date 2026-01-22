#!/usr/bin/env python3
"""
CDIF JSON-LD Framing and Validation Script

Usage:
    python FrameAndValidate.py <input-document.jsonld> [--output framed.json] [--validate] [--schema schema.json]
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
ARRAY_PROPERTIES = [
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
    'schema:propertyID',
    'prov:wasGeneratedBy',
    'prov:wasDerivedFrom',
    'prov:used',
    'dqv:hasQualityMeasurement',
    'dcterms:conformsTo'
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
    # schema.org as prefix (most common)
    "schema": "http://schema.org/",

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


def post_process(obj):
    """
    Post-process the framed output to match schema expectations:
    1. Rename unprefixed terms to prefixed versions
    2. Wrap single values in arrays where schema expects arrays
    3. Convert bare @id references to strings for identifier fields
    """
    if isinstance(obj, list):
        return [post_process(item) for item in obj]

    if isinstance(obj, dict):
        result = {}

        for key, value in obj.items():
            # Skip @context
            if key == '@context':
                result[key] = value
                continue

            # Rename key if needed
            new_key = TERM_MAPPINGS.get(key, key)

            # Process value recursively
            new_value = post_process(value)

            # Convert bare @id references to strings for identifier fields
            if new_key == 'schema:identifier' and is_bare_id_reference(new_value):
                new_value = new_value['@id']

            # Wrap in array if schema expects array and value is not already an array
            if new_key in ARRAY_PROPERTIES and not isinstance(new_value, list) and new_value is not None:
                new_value = [new_value]

            result[new_key] = new_value

        return result

    return obj


def frame_cdif_document(doc_path):
    """Frame a CDIF JSON-LD document using three-step approach"""
    print(f"Loading document: {doc_path}")
    with open(doc_path, 'r', encoding='utf-8') as f:
        doc = json.load(f)

    # Step 1: Expand the document (resolves all prefixes to full IRIs)
    print("Expanding document...")
    expanded = jsonld.expand(doc)

    # Step 2: Frame with minimal frame (no context conflicts)
    print("Framing document...")
    framed = jsonld.frame(expanded, FRAME_TEMPLATE)

    # Step 3: Compact with our desired output context
    print("Compacting with output context...")
    compacted = jsonld.compact(framed, OUTPUT_CONTEXT)

    # Step 4: Extract main dataset from @graph if present
    result = compacted
    if '@graph' in compacted and isinstance(compacted['@graph'], list):
        # Find the main Dataset object
        dataset = None
        for item in compacted['@graph']:
            item_type = item.get('@type')
            if item_type == 'schema:Dataset' or (isinstance(item_type, list) and 'schema:Dataset' in item_type):
                dataset = item
                break
        if dataset:
            result = {'@context': compacted.get('@context'), **dataset}

    # Step 5: Post-process to normalize terms and array properties
    print("Post-processing output...")
    result = post_process(result)

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
  python FrameAndValidate.py my-metadata.jsonld
  python FrameAndValidate.py my-metadata.jsonld -o framed.json
  python FrameAndValidate.py my-metadata.jsonld -v
  python FrameAndValidate.py my-metadata.jsonld -o framed.json -v
"""
    )
    parser.add_argument('input', help='Input JSON-LD file to process')
    parser.add_argument('-o', '--output', help='Write framed output to file')
    parser.add_argument('-v', '--validate', action='store_true', help='Validate against JSON Schema')
    parser.add_argument('--schema', default=str(SCRIPT_DIR / 'CDIF-JSONLD-schema-schemaprefix.json'),
                        help='Path to JSON Schema (default: CDIF-JSONLD-schema-schemaprefix.json)')

    args = parser.parse_args()

    try:
        framed = frame_cdif_document(args.input)

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
        sys.exit(1)


if __name__ == '__main__':
    main()
