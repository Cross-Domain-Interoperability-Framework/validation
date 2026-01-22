#!/usr/bin/env node
/**
 * CDIF JSON-LD Framing and Validation Script
 *
 * Usage:
 *   node validate-cdif.js <input-document.jsonld> [--output framed.json]
 */

const jsonld = require('jsonld');
const Ajv2020 = require('ajv/dist/2020');
const addFormats = require('ajv-formats');
const fs = require('fs');
const path = require('path');

const scriptDir = __dirname;

async function loadJson(filePath) {
    const content = fs.readFileSync(filePath, 'utf8');
    return JSON.parse(content);
}

// Properties that should always be arrays per the CDIF schema
const ARRAY_PROPERTIES = [
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
];

// Term mappings: unprefixed -> prefixed (to match schema expectations)
const TERM_MAPPINGS = {
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
};

/**
 * Check if an object is a bare @id reference (only has @id property)
 */
function isBareIdReference(obj) {
    if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return false;
    const keys = Object.keys(obj);
    return keys.length === 1 && keys[0] === '@id';
}

/**
 * Post-process the framed output to match schema expectations:
 * 1. Rename unprefixed terms to prefixed versions
 * 2. Wrap single values in arrays where schema expects arrays
 * 3. Convert bare @id references to strings for identifier fields
 */
function postProcess(obj) {
    if (Array.isArray(obj)) {
        return obj.map(item => postProcess(item));
    }

    if (obj && typeof obj === 'object') {
        const result = {};

        for (const [key, value] of Object.entries(obj)) {
            // Skip @context
            if (key === '@context') {
                result[key] = value;
                continue;
            }

            // Rename key if needed
            const newKey = TERM_MAPPINGS[key] || key;

            // Process value recursively
            let newValue = postProcess(value);

            // Convert bare @id references to strings for identifier fields
            if (newKey === 'schema:identifier' && isBareIdReference(newValue)) {
                newValue = newValue['@id'];
            }

            // Wrap in array if schema expects array and value is not already an array
            if (ARRAY_PROPERTIES.includes(newKey) && !Array.isArray(newValue) && newValue !== undefined && newValue !== null) {
                newValue = [newValue];
            }

            result[newKey] = newValue;
        }

        return result;
    }

    return obj;
}

// Output context for compaction - uses explicit term mappings to avoid prefix conflicts
const OUTPUT_CONTEXT = {
    // schema.org as prefix (most common)
    "schema": "http://schema.org/",

    // Explicit term mappings for other vocabularies (avoids prefix conflicts)
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
};

// Frame without context - uses full IRIs
const FRAME_TEMPLATE = {
    "@type": "http://schema.org/Dataset",
    "@embed": "@always"
};

async function frameCdifDocument(docPath, options = {}) {
    console.log(`Loading document: ${docPath}`);
    const doc = await loadJson(docPath);

    // Step 1: Expand the document (resolves all prefixes to full IRIs)
    console.log('Expanding document...');
    const expanded = await jsonld.expand(doc);

    // Step 2: Frame with minimal frame (no context conflicts)
    console.log('Framing document...');
    const framed = await jsonld.frame(expanded, FRAME_TEMPLATE);

    // Step 3: Compact with our desired output context
    console.log('Compacting with output context...');
    const compacted = await jsonld.compact(framed, OUTPUT_CONTEXT);

    // Step 4: Extract main dataset from @graph if present
    let result = compacted;
    if (compacted['@graph'] && Array.isArray(compacted['@graph'])) {
        // Find the main Dataset object
        const dataset = compacted['@graph'].find(item =>
            item['@type'] &&
            (item['@type'] === 'schema:Dataset' ||
             (Array.isArray(item['@type']) && item['@type'].includes('schema:Dataset')))
        );
        if (dataset) {
            result = {
                '@context': compacted['@context'],
                ...dataset
            };
        }
    }

    // Step 5: Post-process to normalize terms and array properties
    console.log('Post-processing output...');
    result = postProcess(result);

    return result;
}

async function validateAgainstSchema(framed, schemaPath) {
    console.log(`Loading schema: ${schemaPath}`);
    const schema = await loadJson(schemaPath);

    const ajv = new Ajv2020({ allErrors: true, strict: false });
    addFormats(ajv);

    const validate = ajv.compile(schema);
    const valid = validate(framed);

    return {
        valid,
        errors: validate.errors
    };
}

async function main() {
    const args = process.argv.slice(2);

    if (args.length === 0 || args.includes('--help') || args.includes('-h')) {
        console.log(`
CDIF JSON-LD Framing and Validation Tool

Usage:
  node validate-cdif.js <input.jsonld> [options]

Options:
  --output, -o <file>    Write framed output to file
  --validate, -v         Validate against JSON Schema
  --schema <file>        Path to JSON Schema (default: CDIF-JSONLD-schema-schemaprefix.json)
  --help, -h             Show this help message

Examples:
  node validate-cdif.js my-metadata.jsonld
  node validate-cdif.js my-metadata.jsonld -o framed.json
  node validate-cdif.js my-metadata.jsonld -v
  node validate-cdif.js my-metadata.jsonld -o framed.json -v
`);
        process.exit(0);
    }

    const inputPath = args[0];

    let outputPath = null;
    let doValidate = false;
    let schemaPath = path.join(scriptDir, 'CDIF-JSONLD-schema-schemaprefix.json');

    for (let i = 1; i < args.length; i++) {
        if (args[i] === '--output' || args[i] === '-o') {
            outputPath = args[++i];
        } else if (args[i] === '--validate' || args[i] === '-v') {
            doValidate = true;
        } else if (args[i] === '--schema') {
            schemaPath = args[++i];
        }
    }

    try {
        const framed = await frameCdifDocument(inputPath);

        if (outputPath) {
            fs.writeFileSync(outputPath, JSON.stringify(framed, null, 2));
            console.log(`Framed output written to: ${outputPath}`);
        } else if (!doValidate) {
            console.log('\nFramed output:');
            console.log(JSON.stringify(framed, null, 2));
        }

        if (doValidate) {
            console.log('\nValidating against schema...');
            const result = await validateAgainstSchema(framed, schemaPath);

            if (result.valid) {
                console.log('Validation PASSED');
            } else {
                console.log('Validation FAILED');
                console.log('\nErrors:');
                for (const error of result.errors) {
                    console.log(`  - ${error.instancePath}: ${error.message}`);
                    if (error.params) {
                        console.log(`    Params: ${JSON.stringify(error.params)}`);
                    }
                }
                process.exit(1);
            }
        }

        console.log('\nDone!');

    } catch (error) {
        console.error('Error:', error.message);
        if (error.details) {
            console.error('Details:', JSON.stringify(error.details, null, 2));
        }
        process.exit(1);
    }
}

main();
