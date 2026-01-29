# CDIF Validation Project - Agent Guide

## Project Overview

This repository contains validation tools for **CDIF (Cross-Domain Interoperability Framework)** JSON-LD metadata documents describing scientific datasets. The validation approach uses both JSON Schema and SHACL rules.

## Key Concepts

### What is CDIF?
CDIF is a metadata framework for scientific dataset discovery, built on:
- **schema.org** - Core vocabulary for dataset metadata
- **DDI-CDI** - Data Documentation Initiative for variable/data structure description
- **CSVW** - W3C CSV on the Web for tabular data format specification
- **PROV** - W3C Provenance ontology for data lineage
- **DQV** - Data Quality Vocabulary for quality measurements

### Why Framing is Required
CDIF metadata is expressed as JSON-LD, which can represent data as graphs. JSON Schema validates tree structures, not graphs. The **framing** step reshapes the JSON-LD graph into a tree structure that JSON Schema can validate.

## File Structure

| File | Purpose |
|------|---------|
| `CDIF-JSONLD-schema-2026.json` | **Current** JSON Schema with DDI-CDI/CSVW support |
| `CDIF-frame-2026.jsonld` | **Current** JSON-LD frame for 2026 schema |
| `CDIF-context-2026.jsonld` | Context for authoring without prefixes |
| `FrameAndValidate.py` | Main validation script (Python) |
| `validate-cdif.bat` | Windows batch script for oXygen integration |
| `ShaclValidation/ShaclJSONLDContext.py` | SHACL validation script |
| `CDIF-Discovery-Core-Shapes2.ttl` | SHACL shapes for semantic validation |
| `CDIF-JSONLD-schema-schemaprefix.json` | Legacy schema (pre-2026) |
| `CDIF-frame.jsonld` | Legacy frame (pre-2026) |

## Validation Workflow

```
┌─────────────────┐     ┌─────────────┐     ┌──────────────┐     ┌────────────┐
│  JSON-LD Input  │────▶│   Expand    │────▶│    Frame     │────▶│  Validate  │
│  (graph format) │     │  (resolve   │     │  (reshape to │     │  (against  │
│                 │     │   prefixes) │     │   tree)      │     │   schema)  │
└─────────────────┘     └─────────────┘     └──────────────┘     └────────────┘
```

## Common Tasks

### Validate a Document (Command Line)
```bash
# Using Python script (default: 2026 schema)
python FrameAndValidate.py path/to/metadata.jsonld -v

# Using Windows batch script
validate-cdif.bat path/to/metadata.jsonld
```

### Frame and Save Output (for debugging)
```bash
python FrameAndValidate.py path/to/metadata.jsonld -o framed.json

# Or with batch script
validate-cdif.bat path/to/metadata.jsonld --framed
```

### Use Legacy Schema
```bash
python FrameAndValidate.py metadata.jsonld --frame CDIF-frame.jsonld --schema CDIF-JSONLD-schema-schemaprefix.json -v

# Or with batch script
validate-cdif.bat metadata.jsonld --legacy
```

### SHACL Validation
```bash
python ShaclValidation/ShaclJSONLDContext.py metadata.jsonld CDIF-Discovery-Core-Shapes2.ttl
```

## oXygen XML Editor Integration

The `validate-cdif.bat` script enables validation from within oXygen XML Editor.

### Setup
1. Go to **Tools → External Tools → Configure...**
2. Create a new tool with these settings:

| Field | Value |
|-------|-------|
| **Name** | `CDIF Validate` |
| **Command** | `C:\Users\smrTu\OneDrive\Documents\GithubC\CDIF\validation\validate-cdif.bat` |
| **Arguments** | `"${cf}"` |
| **Working directory** | *(leave empty)* |

### Usage in oXygen
1. Open a JSON-LD file
2. Go to **Tools → External Tools → CDIF Validate**
3. Results appear in the oXygen console

### Batch Script Options
```
validate-cdif.bat file.jsonld           # Validate with 2026 schema
validate-cdif.bat file.jsonld --framed  # Validate + save framed output
validate-cdif.bat file.jsonld --legacy  # Use pre-2026 schema
validate-cdif.bat --help                # Show help
```

## Schema Structure (2026)

### Required Properties
- `@id` - Resource identifier (URI)
- `@type` - Must include `schema:Dataset`
- `@context` - Must include `schema`, `dcterms`, `geosparql`, `spdx`, `cdi`, `csvw` prefixes
- `schema:name` - Dataset name (min 5 chars)
- `schema:identifier` - Primary identifier
- `schema:dateModified` - Last modification date
- `schema:subjectOf` - Metadata about the metadata record
- Either `schema:url` OR `schema:distribution` - Access information
- Either `schema:license` OR `schema:conditionsOfAccess` - Usage terms

### Key Type Definitions

#### Distribution (Physical Dataset)
Distributions can be:
1. `schema:WebAPI` - For API access
2. `schema:DataDownload` + `cdi:StructuredDataSet` - For structured formats (JSON, XML)
3. `schema:DataDownload` + `cdi:TabularTextDataSet` - For tabular text (CSV, TSV, fixed-width)

TabularTextDataSet uses CSVW properties:
- `csvw:delimiter`, `csvw:header`, `csvw:headerRowCount`
- `cdi:isDelimited` OR `cdi:isFixedWidth` (mutually exclusive)
- `cdi:hasPhysicalMapping` - Links variables to physical representation

#### Variables (variableMeasured)
Must have dual typing: `["schema:PropertyValue", "cdi:InstanceVariable"]`

Required properties:
- `schema:name` - Variable name (min 5 chars)
- `schema:description` - Variable description (min 10 chars)
- `@type` - Must contain both types above

Optional DDI-CDI properties:
- `cdi:role` - DimensionComponent, MeasureComponent, or AttributeComponent
- `cdi:intendedDataType` - Expected data type
- `cdi:simpleUnitOfMeasure` - Unit of measurement

## Common Validation Errors

### "None is not of type 'array'"
The framing added `null` for a missing optional property. The post-processing should remove these, but if you see this error, check that `remove_nulls_and_normalize()` is being called.

### "is not valid under any of the given schemas"
Usually means a type constraint failed. Check:
- `@type` arrays contain required types
- `dcterms:conformsTo` uses object syntax: `[{"@id": "..."}]` not `["..."]`

### Missing required property
Check that the source document has the property. Common missing: `schema:subjectOf`, `schema:dateModified`.

## Dependencies

```bash
pip install PyLD jsonschema rdflib pyshacl
```

## Test Documents

Example documents are in:
- `../integrationPublic/exampleMetadata/CDIF2026/` - 2026 schema examples
- `DataExamples/` - Various test cases
- `schemaExamples/` - Schema fragment examples

## Extending the Schema

When adding new properties:

1. Add to `CDIF-JSONLD-schema-2026.json` in appropriate `$defs` section
2. Add framing instructions to `CDIF-frame-2026.jsonld`
3. Add term mapping to `CDIF-context-2026.jsonld` (for prefix-free authoring)
4. If property should be array, add to `ARRAY_PROPERTIES` in `FrameAndValidate.py`
5. Update SHACL shapes if semantic constraints needed

## Related Repositories

- Example metadata: `../integrationPublic/exampleMetadata/`
- SHACL building blocks: See README.md for link to `_sources` repository
