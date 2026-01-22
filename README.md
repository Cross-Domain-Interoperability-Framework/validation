# Files for validation of CDIF metadata

This repository contains JSON schema, JSON-LD frames, contexts, and SHACL rule sets for validating CDIF metadata documents.

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

## Notes

- `CDIF-JSONLD-schema-schemaprefix.json` requires all schema.org elements to have a `schema:` prefix. This is necessary for SHACL validation compatibility.
- The frame ensures that after framing, the output structure matches what the JSON schema expects.
- For SHACL validation, use the corresponding `.shacl` files in this repository.
