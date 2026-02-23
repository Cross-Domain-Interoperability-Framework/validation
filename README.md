# Files for validation of CDIF metadata

This repository contains JSON schema, JSON-LD frames, contexts, and SHACL rule sets for validating CDIF metadata documents.

## Table of Contents

- [Files](#files)
- [Quick Start](#quick-start)
- [Validation Workflow](#validation-workflow)
  - [Step 1: Frame the JSON-LD Document](#step-1-frame-the-json-ld-document)
  - [Step 2: Validate Against Schema](#step-2-validate-against-schema)
- [RO-Crate Validation](#ro-crate-validation)
  - [How the Conversion Works](#how-the-conversion-works)
  - [Validation Checks](#validation-checks)
  - [RO-Crate Usage](#ro-crate-usage)
- [Usage Examples](#usage-examples)
  - [Command Line (Recommended)](#command-line-recommended)
  - [oXygen XML Editor](#oxygen-xml-editor)
  - [Python](#python)
  - [JavaScript/Node.js](#javascriptnodejs)
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
- [DDI-CDI Resolved Schema](#ddi-cdi-resolved-schema)
- [Notes](#notes)

## Files

### Current (2026 Schema with DDI-CDI/CSVW)

| File | Description |
|------|-------------|
| `CDIF-JSONLD-schema-2026.json` | JSON Schema with DDI-CDI variable types and CSVW tabular dataset properties |
| `CDIF-frame-2026.jsonld` | JSON-LD frame for 2026 schema |
| `CDIF-context-2026.jsonld` | JSON-LD context for authoring without namespace prefixes |
| `FrameAndValidate.py` | Python script for framing and validation |
| `ConvertToROCrate.py` | Python library + CLI for converting CDIF JSON-LD to RO-Crate form |
| `ValidateROCrate.py` | Python script for RO-Crate validation (imports conversion from ConvertToROCrate) |
| `RO-Crate-relationship.md` | ADA/CDIF profile mapping to RO-Crate, with ValidateROCrate.py design notes |
| `validate-cdif.bat` | Windows batch script for oXygen XML Editor integration |

### DDI-CDI Resolved Schema

| File | Description |
|------|-------------|
| `ddi-cdi.schema_normative.json` | Full DDI-CDI normative JSON Schema (395 definitions) |
| `cls-InstanceVariable-resolved.json` | Self-contained resolved schema for DDI-CDI InstanceVariable class |
| `cls-InstanceVariable-resolved-README.md` | Documentation for the resolved schema generation process |

### Legacy (Pre-2026)

| File | Description |
|------|-------------|
| `CDIF-JSONLD-schema-schemaprefix.json` | JSON Schema for CDIF Discovery profile metadata with `schema:` prefixes |
| `CDIF-frame.jsonld` | JSON-LD frame for legacy schema |
| `CDIF-context.jsonld` | Legacy JSON-LD context |

## Quick Start

### Prerequisites

```bash
pip install PyLD jsonschema
```

### Validate a Document

```bash
# Using Python script (default: 2026 schema)
python FrameAndValidate.py my-metadata.jsonld -v

# Using Windows batch script
validate-cdif.bat my-metadata.jsonld
```

### Save Framed Output for Debugging

```bash
python FrameAndValidate.py my-metadata.jsonld -o framed.json -v
```

## Validation Workflow

CDIF metadata is expressed as JSON-LD. To validate JSON-LD documents against the JSON Schema, you need to first **frame** the document to ensure it has the correct structure. The framing process:

1. Reshapes the JSON-LD graph into a tree structure
2. Ensures properties use the expected prefixes (e.g., `schema:name`)
3. Embeds referenced nodes inline
4. Normalizes arrays and single values

### Step 1: Frame the JSON-LD Document

Use a JSON-LD processor to apply `CDIF-frame-2026.jsonld` to your metadata document.

### Step 2: Validate Against Schema

Validate the framed output against `CDIF-JSONLD-schema-2026.json`.

## RO-Crate Conversion and Validation

`ConvertToROCrate.py` and `ValidateROCrate.py` are the complement of `FrameAndValidate.py`. Where `FrameAndValidate.py` takes a flattened `@graph` and *nests* it (via JSON-LD framing) for JSON Schema validation, these tools take nested/compacted CDIF JSON-LD and *flatten* it (via JSON-LD expand + flatten) into [RO-Crate 1.1](https://www.researchobject.org/ro-crate/1.1/) form.

- **`ConvertToROCrate.py`** — Pure conversion library and standalone CLI. Can be imported as a library (`from ConvertToROCrate import convert_to_rocrate`) or run directly to convert without validation.
- **`ValidateROCrate.py`** — Validation script that imports conversion from `ConvertToROCrate` and runs 13 structural checks plus optional SHACL-based validation via `rocrate-validator`.

This confirms that CDIF metadata can be faithfully represented as a standards-compliant Research Object Crate.

### How the Conversion Works

The conversion pipeline has four stages, all handled by [pyld](https://github.com/digitalbazaar/pyld):

```
Input (nested CDIF JSON-LD)
  |
  v
1. Enrich @context
   Add missing namespace prefixes, normalize schema to http://
   (RO-Crate 1.1 uses http://schema.org/, not https://)
  |
  v
2. Expand
   Resolve all prefixed terms to full IRIs
   (e.g. schema:name -> http://schema.org/name)
  |
  v
3. Flatten
   Decompose nested objects into a flat @graph array
   with @id cross-references
  |
  v
4. Compact
   Re-compact with the RO-Crate 1.1 context
   (schema.org terms become unprefixed; CDIF-specific
   terms keep their prefixes: prov:, spdx:, cdi:, etc.)
  |
  v
5. Inject
   Add ro-crate-metadata.json descriptor entity,
   remap root Dataset @id to "./"
  |
  v
Output (RO-Crate 1.1 @graph)
```

**Namespace normalization**: CDIF documents typically use `https://schema.org/` (with `s`), but the RO-Crate 1.1 context uses `http://schema.org/` (without `s`). The script normalizes this during context enrichment so that schema.org terms compact properly. It also injects all known CDIF namespace prefixes (`prov:`, `xas:`, `nxs:`, etc.) so that prefixed terms used in the input but not declared in its `@context` still resolve correctly.

**Root Dataset detection**: The script identifies the root Dataset entity by looking for the entity whose `@type` includes `Dataset` and that has a `distribution` property. It remaps that entity's `@id` to `"./"` (as RO-Crate requires) and updates all cross-references throughout the graph.

### Validation Checks

The validator runs 13 checks against the RO-Crate 1.1 specification. Checks are classified as FAIL (must fix) or WARN (recommended).

| # | Level | Requirement |
|---|-------|-------------|
| 1 | FAIL | Top-level has `@context` |
| 2 | FAIL | Top-level has `@graph` as an array |
| 3 | FAIL | `@graph` contains metadata descriptor (`ro-crate-metadata.json` with `conformsTo`) |
| 4 | FAIL | `@graph` contains root dataset (`@id: "./"`, `@type` includes `Dataset`) |
| 5 | FAIL | Root dataset has `datePublished` (ISO 8601) |
| 6 | FAIL | All entities in `@graph` have `@id` |
| 7 | FAIL | All entities in `@graph` have `@type` |
| 8 | FAIL | No nested entities -- all cross-references use `{"@id": "..."}` |
| 9 | FAIL | No `../` in `@id` paths |
| 10 | WARN | Root dataset has `name` |
| 11 | WARN | Root dataset has `description` |
| 12 | WARN | Root dataset has `license` |
| 13 | WARN | `@context` references the RO-Crate 1.1 context URL |

### RO-Crate Usage

```bash
# Convert CDIF to RO-Crate form only (no validation)
python ConvertToROCrate.py input.jsonld -o output-rocrate.json

# Convert and print to stdout
python ConvertToROCrate.py input.jsonld

# Convert CDIF to RO-Crate form and validate
python ValidateROCrate.py input.jsonld

# Convert, validate, and save the RO-Crate output
python ValidateROCrate.py input.jsonld -o output-rocrate.json

# Validate a document already in @graph form (skip conversion)
python ValidateROCrate.py rocrate.jsonld --no-convert

# Verbose output (show details for passing checks too)
python ValidateROCrate.py input.jsonld -v

# Skip rocrate-validator SHACL checks
python ValidateROCrate.py input.jsonld --no-rocrate-validator

# Include RECOMMENDED-level checks from rocrate-validator
python ValidateROCrate.py input.jsonld --severity RECOMMENDED
```

**ConvertToROCrate.py options:**
- `-o, --output FILE` - Write the converted RO-Crate JSON-LD to a file (default: stdout)
- `-v, --verbose` - Show detailed progress output

**ValidateROCrate.py options:**
- `-o, --output FILE` - Write the converted RO-Crate JSON-LD to a file
- `--no-convert` - Skip the conversion step; validate the input document as-is
- `-v, --verbose` - Show detail messages for all checks, not just failures and warnings
- `--no-rocrate-validator` - Skip rocrate-validator SHACL-based checks
- `--severity LEVEL` - Minimum severity for rocrate-validator checks (REQUIRED, RECOMMENDED, OPTIONAL)

**Exit codes:**
- `0` - all FAIL-level checks passed (warnings are allowed)
- `1` - one or more FAIL-level checks failed, or an error occurred

**Example output:**

```
============================================================
RO-Crate 1.1 Validation Results
============================================================
  PASS  [ 1] @context present
  PASS  [ 2] @graph is an array (35 entities)
  PASS  [ 3] Metadata descriptor present with conformsTo
  PASS  [ 4] Root data entity (./) present with type Dataset
  PASS  [ 5] Root dataset has datePublished: 2025-01-27
  PASS  [ 6] All entities have @id
  PASS  [ 7] All entities have @type
  PASS  [ 8] No nested entities -- @graph is flat
  PASS  [ 9] No @id values contain '../'
  PASS  [10] Root dataset has name
  PASS  [11] Root dataset has description
  WARN  [12] Root dataset missing license (SHOULD per RO-Crate spec)
  PASS  [13] @context references RO-Crate 1.1 context

------------------------------------------------------------
Summary: 12 passed, 1 warnings, 0 failures
Result: VALID (with warnings)
```

The script requires network access on first run to fetch the RO-Crate 1.1 context from `https://w3id.org/ro/crate/1.1/context`.

## Usage Examples

### Command Line (Recommended)

The `FrameAndValidate.py` script handles the complete workflow:

```bash
# Validate with 2026 schema (default)
python FrameAndValidate.py my-metadata.jsonld -v

# Save framed output
python FrameAndValidate.py my-metadata.jsonld -o framed.json -v

# Use legacy schema
python FrameAndValidate.py my-metadata.jsonld --frame CDIF-frame.jsonld --schema CDIF-JSONLD-schema-schemaprefix.json -v
```

**Options:**
- `-v, --validate` - Validate against JSON Schema
- `-o, --output FILE` - Save framed output to file
- `--schema FILE` - Path to JSON Schema (default: CDIF-JSONLD-schema-2026.json)
- `--frame FILE` - Path to JSON-LD frame (default: CDIF-frame-2026.jsonld)

### oXygen XML Editor

The `validate-cdif.bat` script enables validation from within oXygen XML Editor.

#### Setup

1. Go to **Tools → External Tools → Configure...**
2. Click **New** and configure:

| Field | Value |
|-------|-------|
| **Name** | `CDIF Validate` |
| **Command** | Path to `validate-cdif.bat` |
| **Arguments** | `"${cf}"` |
| **Working directory** | *(leave empty)* |

#### Usage

1. Open a JSON-LD file in oXygen
2. Go to **Tools → External Tools → CDIF Validate**
3. Results appear in the oXygen console

#### Batch Script Options

```bash
validate-cdif.bat file.jsonld           # Validate with 2026 schema
validate-cdif.bat file.jsonld --framed  # Validate + save framed output
validate-cdif.bat file.jsonld --legacy  # Use pre-2026 schema
validate-cdif.bat --help                # Show help
```

### Python

```python
import json
from pyld import jsonld
import jsonschema

# Load the frame
with open('CDIF-frame-2026.jsonld') as f:
    frame = json.load(f)

# Load your JSON-LD metadata document
with open('my-metadata.jsonld') as f:
    doc = json.load(f)

# Load the schema
with open('CDIF-JSONLD-schema-2026.json') as f:
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
    const frame = JSON.parse(fs.readFileSync('CDIF-frame-2026.jsonld', 'utf8'));
    const doc = JSON.parse(fs.readFileSync(metadataPath, 'utf8'));
    const schema = JSON.parse(fs.readFileSync('CDIF-JSONLD-schema-2026.json', 'utf8'));

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

## Context Requirements

Your JSON-LD metadata documents must include a `@context` with the following namespace prefixes.

### 2026 Schema Requirements

```json
{
    "@context": {
        "schema": "http://schema.org/",
        "dcterms": "http://purl.org/dc/terms/",
        "geosparql": "http://www.opengis.net/ont/geosparql#",
        "spdx": "http://spdx.org/rdf/terms#",
        "cdi": "http://ddialliance.org/Specification/DDI-CDI/1.0/RDF/",
        "csvw": "http://www.w3.org/ns/csvw#"
    }
}
```

### Legacy Schema Requirements

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

If you prefer to author metadata without namespace prefixes (e.g., `name` instead of `schema:name`), you can use the `CDIF-context-2026.jsonld` context file. This context maps unprefixed property names to their full IRIs.

### Example Instance Without Prefixes

```json
{
    "@context": "https://your-server.org/CDIF-context-2026.jsonld",
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

1. **Unprefixed instance** references `CDIF-context-2026.jsonld`
2. **Framing** with `CDIF-frame-2026.jsonld` transforms the instance
3. The frame's context uses prefixed names, so the **output has prefixed keys**
4. **Validate** against `CDIF-JSONLD-schema-2026.json`

This means you only need one schema. The framing step normalizes all instances to the prefixed format regardless of how they were authored.

### Deploying the Context

For production use, host `CDIF-context-2026.jsonld` at a stable URL and reference it in your instances:

```json
{
    "@context": "https://your-server.org/CDIF-context-2026.jsonld",
    ...
}
```

Or embed the context directly in your instance by copying the contents of `CDIF-context-2026.jsonld`.

## Schema Structure

The schema validates CDIF Discovery profile metadata with the following required fields:

- `@id` - Resource identifier
- `@type` - Must include `schema:Dataset`
- `@context` - JSON-LD context with required prefixes
- `schema:name` - Resource name (min 5 characters)
- `schema:identifier` - Primary identifier
- `schema:dateModified` - Last modification date
- `schema:subjectOf` - Metadata about the metadata record
- Either `schema:url` or `schema:distribution` - Access information
- Either `schema:license` or `schema:conditionsOfAccess` - Usage terms

### 2026 Schema Additions

The 2026 schema adds support for:

**Variables (`schema:variableMeasured`):**
- Must have dual typing: `["schema:PropertyValue", "cdi:InstanceVariable"]`
- DDI-CDI properties: `cdi:role`, `cdi:intendedDataType`, `cdi:simpleUnitOfMeasure`

**Distributions:**
- `cdi:StructuredDataSet` - For structured formats (JSON, XML)
- `cdi:TabularTextDataSet` - For tabular text with CSVW properties:
  - `csvw:delimiter`, `csvw:header`, `csvw:headerRowCount`
  - `cdi:isDelimited` OR `cdi:isFixedWidth`
  - `cdi:hasPhysicalMapping` - Links variables to physical representation

## Troubleshooting

### Common Validation Errors

1. **Missing required property**
   - Ensure all required fields are present
   - Check that `schema:subjectOf` contains required nested fields

2. **Type mismatch**
   - Properties like `schema:spatialCoverage` and `schema:temporalCoverage` expect arrays
   - Check that `@type` values use the `schema:` prefix

3. **Invalid @type**
   - Root `@type` must include `schema:Dataset`
   - For 2026 schema, variables must include both `schema:PropertyValue` and `cdi:InstanceVariable`

4. **Framing issues**
   - Ensure your document has proper `@id` values for node references
   - Check that the `@context` is compatible with the frame

5. **dcterms:conformsTo syntax**
   - Must use object syntax: `[{"@id": "..."}]` not `["..."]`

### Debugging

To see the framed output before validation:

```bash
python FrameAndValidate.py my-metadata.jsonld -o framed.json
```

Or in Python:
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

```bash
python ShaclValidation/ShaclJSONLDContext.py <data.jsonld> <shapes.ttl>
```

Or using named arguments:

```bash
python ShaclValidation/ShaclJSONLDContext.py --data <data.jsonld> --shapes <shapes.ttl>
```

**Options:**
- `-d, --data` - Path to JSON-LD metadata file to validate
- `-s, --shapes` - Path to SHACL shapes file (TTL format)
- `-v, --verbose` - Show detailed diagnostic output including SPARQL target matches
- `-h, --help` - Show help message

#### Example: Validating Against Core SHACL

```bash
python ShaclValidation/ShaclJSONLDContext.py my-metadata.jsonld CDIF-Discovery-Core-Shapes2.ttl
```

#### Example: Validating Against Building Block Rules

To validate specific components (e.g., variableMeasured):

```bash
python ShaclValidation/ShaclJSONLDContext.py my-metadata.jsonld path/to/_sources/schemaorgProperties/variableMeasured/rules.shacl
```

#### Example: Verbose Output

To see detailed diagnostic information including SPARQL target matches:

```bash
python ShaclValidation/ShaclJSONLDContext.py -v my-metadata.jsonld CDIF-Discovery-Core-Shapes2.ttl
```

#### Script Output

The script provides validation output including:

1. **Data graph size** - Number of triples in the parsed JSON-LD
2. **Shapes graph size** - Number of triples in the SHACL rules
3. **Validation results** - Lists any constraint violations with:
   - Focus node (the node that failed validation)
   - Source shape (the SHACL shape that was violated)
   - Result message (explanation of the violation)

With `--verbose`, additional output includes:
- SPARQL target matches showing which nodes match shape targets
- Debug information from pyshacl

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

## MetadataExamples

The `MetadataExamples/` directory contains sample CDIF JSON-LD documents for testing:

| File | Technique | Description |
|------|-----------|-------------|
| `tof-htk9-f770.json` | ToF-SIMS | Time-of-flight mass spectrometry particle analysis |
| `xrd-2j0t-gq80.json` | XRD | X-ray diffraction |
| `xanes-2arx-b516.json` | XANES | X-ray absorption near-edge structure |
| `yv1f-jb20.json` | -- | General dataset |

Corresponding `*-rocrate.json` files contain the converted RO-Crate output produced by `ValidateROCrate.py`.

## DDI-CDI Resolved Schema

The `cls-InstanceVariable-resolved.json` file is a standalone JSON Schema (Draft 2020-12) for the DDI-CDI `InstanceVariable` class, derived from `ddi-cdi.schema_normative.json`. It resolves all `$ref` references into a self-contained schema suitable for use in editors like oXygen without needing the full 395-definition DDI-CDI schema.

The resolved schema applies several transformations to make the schema practical:

- **Reverse properties removed** - 767 `_OF_` reverse relationship properties stripped (use JSON-LD `@reverse` instead)
- **`catalogDetails` removed** - Catalog-level metadata omitted from all classes
- **Redundant classes omitted** - `cls-DataPoint`, `cls-Datum`, `cls-RepresentedVariable` simplified to IRI-only references
- **XSD types inlined** - Primitive types (`xsd:string`, `xsd:integer`, etc.) replaced with inline definitions
- **Patterns normalized** - `if/then/else` array patterns converted to consistent `anyOf`
- **Frequency-based `$ref` resolution** - Common definitions (>3 uses) in `$defs`; rare definitions inlined

See `cls-InstanceVariable-resolved-README.md` for full details on the generation process, circular reference analysis, and transformation rationale.

## Notes

- The 2026 schema (`CDIF-JSONLD-schema-2026.json`) is the current default and includes DDI-CDI and CSVW support.
- Legacy schema (`CDIF-JSONLD-schema-schemaprefix.json`) is still available for older documents.
- All schema.org elements require the `schema:` prefix for SHACL validation compatibility.
- The frame ensures that after framing, the output structure matches what the JSON schema expects.
- For SHACL validation, use the corresponding `.shacl` or `.ttl` files in this repository.
