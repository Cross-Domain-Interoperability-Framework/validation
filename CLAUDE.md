# CLAUDE.md - Project Guide for Claude Code

## Project overview

This repository contains validation tools for **CDIF (Cross-Domain Interoperability Framework)** JSON-LD metadata documents describing scientific datasets. Validation uses JSON Schema, SHACL rules, and RO-Crate structural checks.

## Key concepts

- **CDIF** metadata is JSON-LD built on schema.org, DDI-CDI, CSVW, PROV, and DQV vocabularies.
- JSON-LD is a **graph format**; JSON Schema validates **trees**. The **framing** step (via `CDIF-frame-2026.jsonld`) reshapes graphs into trees for schema validation.
- The 2026 schema (`CDIF-JSONLD-schema-2026.json`) is the current default.

## Important files

| File | Role |
|------|------|
| `FrameAndValidate.py` | Main validation script: frames JSON-LD then validates against schema |
| `ValidateROCrate.py` | Converts CDIF JSON-LD to RO-Crate format and validates |
| `validate-cdif.bat` | Windows batch wrapper for oXygen XML Editor integration |
| `CDIF-JSONLD-schema-2026.json` | Current JSON Schema for CDIF metadata |
| `CDIF-frame-2026.jsonld` | JSON-LD frame for 2026 schema |
| `CDIF-context-2026.jsonld` | JSON-LD context for prefix-free authoring |
| `ddi-cdi.schema_normative.json` | Full DDI-CDI normative JSON Schema (395 definitions) |
| `cls-InstanceVariable-resolved.json` | Resolved standalone schema for DDI-CDI InstanceVariable |
| `cls-InstanceVariable-resolved-README.md` | Documentation for the resolved schema generation |
| `CDIF-Discovery-Core-Shapes2.ttl` | SHACL shapes for semantic validation |
| `ShaclValidation/ShaclJSONLDContext.py` | SHACL validation script |

## Common commands

```bash
# Validate a CDIF document
python FrameAndValidate.py path/to/metadata.jsonld -v

# Frame and save output for debugging
python FrameAndValidate.py path/to/metadata.jsonld -o framed.json -v

# Validate as RO-Crate
python ValidateROCrate.py path/to/metadata.jsonld

# SHACL validation
python ShaclValidation/ShaclJSONLDContext.py metadata.jsonld CDIF-Discovery-Core-Shapes2.ttl

# Windows batch (for oXygen)
validate-cdif.bat path/to/metadata.jsonld
```

## Dependencies

```bash
pip install PyLD jsonschema rdflib pyshacl
```

## DDI-CDI resolved schema

The `cls-InstanceVariable-resolved.json` was generated from `ddi-cdi.schema_normative.json` with these transformations:

1. Remove `_OF_` reverse relationship properties (767 removed; use JSON-LD `@reverse` instead)
2. Remove `catalogDetails` property and `dt-CatalogDetails` type from all classes
3. Omit `cls-DataPoint`, `cls-Datum`, `cls-RepresentedVariable` (simplified to IRI references)
4. Inline XSD primitive types (`xsd:string`, `xsd:integer`, `xsd:boolean`, `xsd:date`, `xsd:anyURI`, `xsd:language`)
5. Normalize `if/then/else` array patterns to `anyOf`
6. Definitions used >3 times go in `$defs`; others inlined; circular refs marked with `"$comment": "circular-ref"`

The DDI-CDI schema has pervasive circular dependencies (293 of 395 definitions). Removing reverse properties eliminates ~60%; the remaining ~123 are forward compositional cycles inherent to the data model.

## Extending the CDIF schema

When adding new properties:

1. Add to `CDIF-JSONLD-schema-2026.json` in appropriate `$defs` section
2. Add framing instructions to `CDIF-frame-2026.jsonld`
3. Add term mapping to `CDIF-context-2026.jsonld` (for prefix-free authoring)
4. If property should be array, add to `ARRAY_PROPERTIES` in `FrameAndValidate.py`
5. Update SHACL shapes if semantic constraints needed

## Test documents

- `MetadataExamples/` - Sample CDIF metadata files
- `../integrationPublic/exampleMetadata/CDIF2026/` - 2026 schema examples
