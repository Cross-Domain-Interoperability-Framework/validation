# Files for validation of CDIF metadata

This repository contains JSON schema, JSON-LD frames, contexts, and SHACL rule sets for validating CDIF metadata documents.

## Table of Contents

- [Files](#files)
- [Validation Workflow](#validation-workflow)
  - [Step 1: Frame the JSON-LD Document](#step-1-frame-the-json-ld-document)
  - [Step 2: Validate Against Schema](#step-2-validate-against-schema)
- [Usage Examples](#usage-examples)
  - [Python](#python)
  - [JavaScript/Node.js](#javascriptnodejs)
  - [Command Line](#command-line-using-python-script)
- [Context Requirements](#context-requirements)
- [Authoring Instances Without Prefixes](#authoring-instances-without-prefixes)
  - [Example Instance Without Prefixes](#example-instance-without-prefixes)
  - [How It Works](#how-it-works)
  - [Deploying the Context](#deploying-the-context)
- [Schema Structure](#schema-structure)
- [Troubleshooting](#troubleshooting)
  - [Common Validation Errors](#common-validation-errors)
  - [Debugging](#debugging)
- [SHACL Validation](#shacl-validation)
  - [SHACL Files](#shacl-files)
  - [Using ShaclJSONLDContext.py](#using-shacljsonldcontextpy)
  - [SHACL vs JSON Schema Validation](#shacl-vs-json-schema-validation)
- [Notes](#notes)

## Files

| File | Description |
|------|-------------|
| `CDIF-JSONLD-schema-schemaprefix.json` | JSON Schema for CDIF Discovery profile metadata with `schema:` prefixes |
| `CDIF-frame.jsonld` | JSON-LD frame to reshape metadata for schema validation |
| `CDIF-context.jsonld` | JSON-LD context for authoring instances without namespace prefixes |
| `CDIF-JSONLD-schema.json` | JSON Schema without prefixes (schema.org as default vocabulary) |

## Validation Workflow

CDIF metadata is expressed as JSON-LD. To validate JSON-LD documents against the JSON Schema, you need to first **frame** the document to ensure it has the correct structure. The framing process:

1. Reshapes the JSON-LD graph into a tree structure
2. Ensures properties use the expected prefixes (e.g., `schema:name`)
3. Embeds referenced nodes inline
4. Normalizes arrays and single values

### Step 1: Frame the JSON-LD Document

Use a JSON-LD processor to apply `CDIF-frame.jsonld` to your metadata document.

### Step 2: Validate Against Schema

Validate the framed output against `CDIF-JSONLD-schema-schemaprefix.json`.

## Usage Examples

### Python

```python
import json
from pyld import jsonld
import jsonschema

# Load the frame
with open('CDIF-frame.jsonld') as f:
    frame = json.load(f)

# Load your JSON-LD metadata document
with open('my-metadata.jsonld') as f:
    doc = json.load(f)

# Load the schema
with open('CDIF-JSONLD-schema-schemaprefix.json') as f:
    schema = json.load(f)

# Step 1: Frame the document
framed = jsonld.frame(doc, frame)

# Step 2: Validate against schema
try:
    jsonschema.validate(instance=framed, schema=schema)
    print("Validation successful!")
except jsonschema.ValidationError as e:
    print(f"Validation failed: {e.message}")
```

**Required packages:**
```bash
pip install PyLD jsonschema
```

### JavaScript/Node.js

```javascript
const jsonld = require('jsonld');
const Ajv = require('ajv');
const addFormats = require('ajv-formats');
const fs = require('fs');

async function validateCDIF(metadataPath) {
    // Load files
    const frame = JSON.parse(fs.readFileSync('CDIF-frame.jsonld', 'utf8'));
    const doc = JSON.parse(fs.readFileSync(metadataPath, 'utf8'));
    const schema = JSON.parse(fs.readFileSync('CDIF-JSONLD-schema-schemaprefix.json', 'utf8'));

    // Step 1: Frame the document
    const framed = await jsonld.frame(doc, frame);

    // Step 2: Validate against schema
    const ajv = new Ajv({ allErrors: true });
    addFormats(ajv);
    const validate = ajv.compile(schema);

    if (validate(framed)) {
        console.log('Validation successful!');
        return true;
    } else {
        console.log('Validation failed:', validate.errors);
        return false;
    }
}

validateCDIF('my-metadata.jsonld');
```

**Required packages:**
```bash
npm install jsonld ajv ajv-formats
```

### Command Line (using Python script)

Create a validation script `validate_cdif.py`:

```python
#!/usr/bin/env python3
"""Validate CDIF JSON-LD metadata against the schema."""

import json
import sys
from pyld import jsonld
import jsonschema

def validate_cdif(metadata_path, frame_path='CDIF-frame.jsonld',
                  schema_path='CDIF-JSONLD-schema-schemaprefix.json'):
    """
    Validate a CDIF metadata document.

    Args:
        metadata_path: Path to JSON-LD metadata file
        frame_path: Path to CDIF frame file
        schema_path: Path to CDIF JSON schema

    Returns:
        True if valid, False otherwise
    """
    # Load files
    with open(frame_path) as f:
        frame = json.load(f)
    with open(metadata_path) as f:
        doc = json.load(f)
    with open(schema_path) as f:
        schema = json.load(f)

    # Frame the document
    print(f"Framing {metadata_path}...")
    framed = jsonld.frame(doc, frame)

    # Validate
    print("Validating against schema...")
    try:
        jsonschema.validate(instance=framed, schema=schema)
        print("Validation PASSED")
        return True
    except jsonschema.ValidationError as e:
        print(f"Validation FAILED: {e.message}")
        print(f"  Path: {' -> '.join(str(p) for p in e.absolute_path)}")
        return False

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <metadata.jsonld>")
        sys.exit(1)

    success = validate_cdif(sys.argv[1])
    sys.exit(0 if success else 1)
```

Run with:
```bash
python validate_cdif.py my-metadata.jsonld
```

## Context Requirements

Your JSON-LD metadata documents must include a `@context` with the following namespace prefixes:

```json
{
    "@context": {
        "schema": "http://schema.org/",
        "dcterms": "http://purl.org/dc/terms/",
        "prov": "http://www.w3.org/ns/prov#",
        "dqv": "http://www.w3.org/ns/dqv#",
        "geosparql": "http://www.opengis.net/ont/geosparql#",
        "spdx": "http://spdx.org/rdf/terms#",
        "time": "http://www.w3.org/2006/time#"
    }
}
```

## Authoring Instances Without Prefixes

If you prefer to author metadata without namespace prefixes (e.g., `name` instead of `schema:name`), you can use the `CDIF-context.jsonld` context file. This context maps unprefixed property names to their full IRIs.

### Example Instance Without Prefixes

```json
{
    "@context": "https://your-server.org/CDIF-context.jsonld",
    "@type": "Dataset",
    "@id": "https://example.org/dataset/123",
    "name": "My Dataset",
    "description": "A sample dataset description",
    "identifier": "dataset-123",
    "dateModified": "2024-01-15",
    "url": "https://example.org/data/123",
    "license": "https://creativecommons.org/licenses/by/4.0/",
    "subjectOf": {
        "@type": "Dataset",
        "sdDatePublished": "2024-01-15"
    }
}
```

### How It Works

The validation workflow handles both prefixed and unprefixed instances:

1. **Unprefixed instance** references `CDIF-context.jsonld`
2. **Framing** with `CDIF-frame.jsonld` transforms the instance
3. The frame's context uses prefixed names, so the **output has prefixed keys**
4. **Validate** against `CDIF-JSONLD-schema-schemaprefix.json`

This means you only need one schema (`CDIF-JSONLD-schema-schemaprefix.json`). The framing step normalizes all instances to the prefixed format regardless of how they were authored.

### Deploying the Context

For production use, host `CDIF-context.jsonld` at a stable URL and reference it in your instances:

```json
{
    "@context": "https://your-server.org/CDIF-context.jsonld",
    ...
}
```

Or embed the context directly in your instance by copying the contents of `CDIF-context.jsonld`.

## Schema Structure

The schema validates CDIF Discovery profile metadata with the following required fields:

- `@id` - Resource identifier
- `@type` - Must include a valid schema.org type (e.g., `schema:Dataset`)
- `@context` - JSON-LD context with required prefixes
- `schema:name` - Resource name
- `schema:identifier` - Primary identifier
- `schema:dateModified` - Last modification date
- `schema:subjectOf` - Metadata about the metadata record
- Either `schema:url` or `schema:distribution` - Access information
- Either `schema:license` or `schema:conditionsOfAccess` - Usage terms

## Troubleshooting

### Common Validation Errors

1. **Missing required property**
   - Ensure all required fields are present
   - Check that `schema:subjectOf` contains required nested fields

2. **Type mismatch**
   - Properties like `schema:spatialCoverage` and `schema:temporalCoverage` expect arrays
   - Check that `@type` values use the `schema:` prefix

3. **Invalid @type**
   - Root `@type` must include one of: `schema:Dataset`, `schema:CreativeWork`, `schema:DataCatalog`, etc.

4. **Framing issues**
   - Ensure your document has proper `@id` values for node references
   - Check that the `@context` is compatible with the frame

### Debugging

To see the framed output before validation:

```python
framed = jsonld.frame(doc, frame)
print(json.dumps(framed, indent=2))
```

## SHACL Validation

In addition to JSON Schema validation, CDIF metadata can be validated using SHACL (Shapes Constraint Language) rules. SHACL validation operates on the RDF graph representation of your JSON-LD and can express constraints that JSON Schema cannot, such as:

- SPARQL-based target selection (e.g., validate only DefinedTerm nodes used in specific contexts)
- Cross-node relationship constraints
- Semantic validation using RDF inference

### SHACL Files

| File | Description |
|------|-------------|
| `CDIF-Discovery-Core-Shapes2.ttl` | Core SHACL shapes for CDIF Discovery profile |
| [Building block rules in `_sources/`](https://github.com/smrgeoinfo/OCGbuildingBlockTest/tree/master/_sources) | Modular SHACL rules for individual components |

### Using ShaclJSONLDContext.py

The `ShaclValidation/ShaclJSONLDContext.py` script validates JSON-LD instances against SHACL rules.

#### Prerequisites

Install the required Python packages:

```bash
pip install rdflib pyshacl
```

#### Usage

1. Edit the script to set the paths for your data and shapes files:

```python
# Path to your JSON-LD metadata file
theData = "path/to/your/metadata.jsonld"

# Path to SHACL shapes file
theShapes = "path/to/shapes.ttl"
```

2. Run the validation:

```bash
python ShaclValidation/ShaclJSONLDContext.py
```

#### Script Output

The script provides detailed validation output:

1. **Data graph size** - Number of triples in the parsed JSON-LD
2. **Shapes graph size** - Number of triples in the SHACL rules
3. **SPARQL target matches** - Shows which nodes match SPARQL-based shape targets
4. **Validation results** - Lists any constraint violations with:
   - Focus node (the node that failed validation)
   - Source shape (the SHACL shape that was violated)
   - Result message (explanation of the violation)

#### Example: Validating Against Core SHACL

```python
# In ShaclJSONLDContext.py, set:
theData = "path/to/my-dataset-metadata.jsonld"
theShapes = "CDIF-Discovery-Core-Shapes2.ttl"
```

#### Example: Validating Against Building Block Rules

To validate specific components (e.g., variableMeasured):

```python
theData = "path/to/my-dataset-metadata.jsonld"
theShapes = "../OCGbuildingBlockTest/_sources/schemaorgProperties/variableMeasured/rules.shacl"
```

#### Creating a Reusable Validation Script

For a more flexible command-line tool, create `shacl_validate.py`:

```python
#!/usr/bin/env python3
"""Validate JSON-LD against SHACL shapes."""

import sys
from rdflib import Graph
import pyshacl

def validate_shacl(data_path, shapes_path):
    """
    Validate a JSON-LD file against SHACL shapes.

    Args:
        data_path: Path to JSON-LD data file
        shapes_path: Path to SHACL shapes file (TTL format)

    Returns:
        True if valid, False otherwise
    """
    # Load data graph
    data_graph = Graph()
    data_graph.parse(data_path, format="json-ld")
    print(f"Loaded data graph: {len(data_graph)} triples")

    # Load shapes graph
    shapes_graph = Graph()
    shapes_graph.parse(shapes_path, format="ttl")
    print(f"Loaded shapes graph: {len(shapes_graph)} triples")

    # Validate
    conforms, report_graph, report_text = pyshacl.validate(
        data_graph,
        shacl_graph=shapes_graph,
        inference="rdfs",
        advanced=True
    )

    if conforms:
        print("\nValidation PASSED: Data conforms to SHACL shapes.")
        return True
    else:
        print("\nValidation FAILED:")
        print(report_text)
        return False

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <data.jsonld> <shapes.ttl>")
        sys.exit(1)

    success = validate_shacl(sys.argv[1], sys.argv[2])
    sys.exit(0 if success else 1)
```

Run with:
```bash
python shacl_validate.py my-metadata.jsonld CDIF-Discovery-Core-Shapes2.ttl
```

### SHACL vs JSON Schema Validation

| Aspect | JSON Schema | SHACL |
|--------|-------------|-------|
| Operates on | JSON structure | RDF graph |
| Target selection | JSON paths | Classes, predicates, SPARQL |
| Cross-references | Limited | Full graph traversal |
| Inference | None | RDFS/OWL supported |
| Best for | Structure validation | Semantic validation |

**Recommendation**: Use both validation approaches for comprehensive coverage:
1. JSON Schema for structural validation (property presence, types, formats)
2. SHACL for semantic validation (relationship constraints, vocabulary usage)

## Notes

- `CDIF-JSONLD-schema-schemaprefix.json` requires all schema.org elements to have a `schema:` prefix. This is necessary for SHACL validation compatibility.
- The frame ensures that after framing, the output structure matches what the JSON schema expects.
- For SHACL validation, use the corresponding `.shacl` files in this repository.
