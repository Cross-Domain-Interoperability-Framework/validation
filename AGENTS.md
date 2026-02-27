# AGENTS.md - AI Agent Workflows for CDIF Validation

## Project context

This repository provides validation tools for **CDIF (Cross-Domain Interoperability Framework)** JSON-LD metadata documents describing scientific datasets. CDIF metadata uses vocabularies from schema.org, DDI-CDI, CSVW, PROV-O, and DQV.

Validation is performed at three levels:
- **JSON Schema** (structural) -- `FrameAndValidate.py` frames JSON-LD into trees, then validates against `CDIF-JSONLD-schema-2026.json`
- **SHACL** (semantic) -- `ShaclValidation/ShaclJSONLDContext.py` validates RDF graphs against SHACL shapes
- **RO-Crate** (structural) -- `ValidateROCrate.py` converts to RO-Crate and checks structural requirements
- **Batch** -- `batch_validate.py` runs both JSON Schema and SHACL validation across multiple file groups (testJSONMetadata, cdifbook examples, CDIF profiles, ADA profiles)

## Building block architecture

CDIF metadata schemas are modular, built from **building blocks** -- small, composable schema units maintained in a separate repository.

**Source location**: `USGIN/metadataBuildingBlocks/_sources/` (auto-detected by scripts or specified via `--bb-dir` / `CDIF_BB_DIR` env var).

**Directory structure** (per building block):

```
_sources/
  schemaorgProperties/
    person/
      bblock.json          # Building block metadata (name, status, version)
      schema.yaml          # YAML schema source (human-editable)
      *Schema.json         # JSON Schema (Draft 2020-12)
      rules.shacl          # SHACL validation shapes (Turtle)
      context.jsonld       # JSON-LD context mappings
      description.md       # Documentation
      example*.json        # Example instances
      examples.yaml        # Example reference metadata
      tests.yaml           # Test reference metadata
    identifier/
      ...
  cdifProperties/
    cdifMandatory/
      ...
  provProperties/
    generatedBy/
      ...
  profiles/
    cdifProfiles/
      CDIFDiscovery/       # Profile = composition of building blocks
        ...
```

**Profiles** compose building blocks via `allOf` in their schema. For example, CDIFDiscovery = cdifMandatory + cdifOptional, where cdifMandatory itself references person, organization, identifier, etc.

## Schema generators

### generate_graph_schema.py (JSON Schema)

Reads building block JSON Schemas (`*Schema.json`) and produces a single self-contained JSON Schema (`CDIF-graph-schema-2026.json`) for validating flattened JSON-LD `@graph` documents.

Key operations: resolve cross-building-block `$ref`s, transform `@type` for dispatch, assemble type dispatch chain, build composite types.

### generate_shacl_shapes.py (SHACL shapes)

Reads building block SHACL rules (`rules.shacl`) and merges them into a single composite Turtle file (`CDIF-Discovery-Core-Shapes.ttl`) for the CDIFDiscovery profile.

Key operations: parse each Turtle file with rdflib, detect named shape URIs, resolve conflicts via priority ordering (sub-building blocks win over composites, which win over profile-level copies), serialize merged graph.

## Common workflows

### Validate a metadata document

```bash
# JSON Schema validation (frames then validates)
python FrameAndValidate.py metadata.jsonld -v

# SHACL validation
python ShaclValidation/ShaclJSONLDContext.py metadata.jsonld CDIF-Discovery-Core-Shapes.ttl

# RO-Crate validation
python ValidateROCrate.py metadata.jsonld

# Batch validate all file groups (JSON Schema + SHACL)
python batch_validate.py
```

### Regenerate schemas after building block changes

```bash
# Regenerate graph schema (JSON Schema for @graph documents)
python generate_graph_schema.py

# Regenerate composite SHACL shapes
python generate_shacl_shapes.py
```

### Add or modify a building block

1. Edit source files in `_sources/` (schema.yaml, rules.shacl, etc.)
2. If adding a new building block to CDIFDiscovery:
   - Add its path to `CDIF_DISCOVERY_BLOCKS` in `generate_shacl_shapes.py`
   - Add mapping entries in `generate_graph_schema.py` if it defines a new type
3. Regenerate both schemas:
   ```bash
   python generate_graph_schema.py
   python generate_shacl_shapes.py
   ```
4. Validate example documents to verify

## Key file relationships

```
Building block _sources/
  *.Schema.json ──> generate_graph_schema.py ──> CDIF-graph-schema-2026.json
  rules.shacl   ──> generate_shacl_shapes.py ──> CDIF-Discovery-Core-Shapes.ttl

CDIF-frame-2026.jsonld + CDIF-JSONLD-schema-2026.json ──> FrameAndValidate.py
CDIF-Discovery-Core-Shapes.ttl ──> ShaclValidation/ShaclJSONLDContext.py

batch_validate.py ──> FrameAndValidate.py (JSON Schema)
                  ──> ShaclValidation/ShaclJSONLDContext.py (SHACL)
```

## Dependencies

```bash
pip install PyLD jsonschema rdflib pyshacl
```
