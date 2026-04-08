# AGENTS.md - AI Agent Workflows for CDIF Validation

## Project context

This repository provides validation tools for **CDIF (Cross-Domain Interoperability Framework)** JSON-LD metadata documents describing scientific datasets. CDIF metadata uses vocabularies from schema.org, DDI-CDI, CSVW, PROV-O, and DQV.

Validation is performed at three levels:
- **JSON Schema** (structural) -- `FrameAndValidate.py` frames JSON-LD into trees, then validates against `CDIFCompleteSchema.json` (or `CDIFDiscoverySchema.json`)
- **SHACL** (semantic) -- `ShaclValidation/ShaclJSONLDContext.py` validates RDF graphs against SHACL shapes
- **RO-Crate** (structural) -- RO-Crate conversion/validation tools have moved to the [packaging repo](https://github.com/Cross-Domain-Interoperability-Framework/packaging)
- **Batch** -- `batch_validate.py` runs both JSON Schema and SHACL validation across multiple file groups (testJSONMetadata, cdifbook examples, CDIF profiles, ADA profiles), with severity-aware reporting (violations vs warnings vs info)
- **Conformance** -- `validate_conformance.py` reads `schema:subjectOf/dcterms:conformsTo` claims from JSON-LD files and validates each file against the profile schemas it claims. Maps conformsTo URIs to building-block/profile resolved schemas. Ignores `ada:` prefixed URIs.
- **Harvesting** -- `geocodes_harvester.py` queries the EarthCube GeoCodes SPARQL endpoint for dataset records, fetches original JSON-LD from source landing pages, and optionally converts to CDIF core or discovery profile format (prefixing, @context, @type arrays, subjectOf with conformsTo, type mappings, Person name synthesis). Preserves extra properties (open-world).
- **DCAT Conversion** -- `DCAT/dcat_to_cdif.py` converts DCAT JSON-LD catalogs to CDIF schema.org format. Maps dcterms/DCAT/FOAF properties to schema.org equivalents per the CDIF DCAT implementation guide. Supports nested catalogs, qualified attributions (roles), spatial/temporal, distributions. Auto-detects core vs discovery profile. Preserves unmapped properties (open-world).

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
    variableMeasured/      # PropertyValue-based variableMeasured
    statisticalVariable/   # StatisticalVariable (separate BB)
      ...
  cdifProperties/
    cdifMandatory/         # Core required properties + @context (schema, dcterms, spdx, dcat)
    cdifOptional/          # Optional properties + @context (geosparql, prov, dqv, cdi)
    cdifVariableMeasured/  # Extends variableMeasured with DDI-CDI InstanceVariable properties
    cdifDataDescription/   # Data description level: cdi:physicalDataType requirement + distribution cdi file properties
      ...
  provProperties/
    generatedBy/
      ...
  profiles/
    cdifProfiles/
      CDIFDiscovery/       # Profile = cdifMandatory + cdifOptional + @type enum constraint
      CDIFDataDescription/ # CDIFDiscovery + cdifDataDescription + distribution data description + csvw @context
      CDIFcomplete/        # CDIFDiscovery + cdifDataDescription + cdifProv + distribution data description
        ...
```

**Profiles** compose building blocks via `allOf` in their schema. For example, CDIFDiscovery = cdifMandatory + cdifOptional + @type enum. CDIFDataDescription adds cdifDataDescription BB for data description constraints. CDIFcomplete extends CDIFDiscovery with cdifProv and cdifDataDescription.

**@context** is defined across building blocks: cdifMandatory declares schema + dcterms (required) plus spdx + dcat; cdifOptional adds geosparql, prov, dqv, cdi; CDIFDataDescription adds csvw. These merge via allOf composition.

**variableMeasured** has a layered architecture: base `variableMeasured` (schemaorgProperties) defines PropertyValue-based variables; `statisticalVariable` (schemaorgProperties) defines StatisticalVariable; `cdifVariableMeasured` (cdifProperties) extends variableMeasured with DDI-CDI properties. In cdifOptional, items are anyOf[cdifVariableMeasured, StatisticalVariable]. The `cdifDataDescription` BB adds cdi:physicalDataType requirement at the data description level.

## Schema generators

### generate_validation_schema.py (framed-tree JSON Schema)

Generates self-contained framed-tree validation schemas (`CDIFDiscoverySchema.json`, `CDIFDataDescriptionSchema.json`, `CDIFCompleteSchema.json`) from building block profile resolved schemas. Takes a resolved profile schema (e.g., `CDIFDiscovery/resolvedSchema.json`) and produces a compact JSON Schema with `$defs` for repeated sub-schemas.

Key operations:
1. Deep-merge all `allOf` entries into a flat schema (merge properties, union required, preserve conditional anyOf constraints, **preserve source `$defs`** from resolved schemas)
2. Structural fingerprinting: group repeated sub-schemas by structure (ignoring description/title/examples), extract to `$defs`
3. Nested dedup: process `$defs` smallest-first so inner types get replaced in outer types
4. Prune single-use `$defs` (inline them back), resolving chains where pruned defs reference other pruned defs
5. Semantic post-processing: consolidate equivalent defs (e.g., `measurementTechnique_type` + `serviceType_type` + `linkRelationship_type` → `nameOrDefinedTerm_type`), rename defs for clarity

Design rules:
- **No external `$ref`s** -- output is fully self-contained
- **No array-wrapper `$defs`** -- arrays stay inline to preserve per-property descriptions; only item types are deduplicated
- **No bare-scalar `$defs`** -- simple `{type: string}` or `{type: number}` properties stay inline regardless of description length
- Canonical reusable types: `nameOrDefinedTerm_type` (string | DefinedTerm), `nameOrReference_type` (string | @id-object | CreativeWork), `identifier_type` (string | PropertyValue)

```bash
python generate_validation_schema.py path/to/resolvedSchema.json -o CDIFDiscoverySchema.json -t "CDIF Discovery metadata schema" -d "description text" -v
```

### generate_graph_schema.py (flattened-graph JSON Schema)

Reads building block JSON Schemas (`*Schema.json`) and produces a single self-contained JSON Schema (`CDIF-graph-schema-2026.json`) for validating flattened JSON-LD `@graph` documents.

Key operations: resolve cross-building-block `$ref`s, transform `@type` for dispatch, assemble type dispatch chain, build composite types.

### generate_shacl_shapes.py (SHACL shapes)

Reads building block SHACL rules (`rules.shacl`) and merges them into a single composite Turtle file (`ShaclValidation/CDIF-Discovery-Shapes.ttl`) for the CDIFDiscovery profile.

Key operations: parse each Turtle file with rdflib, detect named shape URIs, resolve conflicts via priority ordering (sub-building blocks win over composites, which win over profile-level copies), serialize merged graph. Supports `--profile discovery` (64 shapes) and `--profile complete` (76 shapes).

## Common workflows

### Validate a metadata document

```bash
# JSON Schema validation (frames then validates)
python FrameAndValidate.py metadata.jsonld -v

# SHACL validation (complete profile)
python ShaclValidation/ShaclJSONLDContext.py metadata.jsonld ShaclValidation/CDIF-Complete-Shapes.ttl

# SHACL validation report (markdown)
python ShaclValidation/generate_shacl_report.py metadata.jsonld ShaclValidation/CDIF-Complete-Shapes.ttl -o report.md

# Batch validate all file groups (JSON Schema + SHACL)
python batch_validate.py
```

### Regenerate schemas after building block changes

```bash
# Regenerate framed-tree validation schemas (requires resolved schemas from BB repo)
python generate_validation_schema.py path/to/CDIFDiscovery/resolvedSchema.json \
  -o CDIFDiscoverySchema.json \
  -t "CDIF Discovery metadata schema" \
  -d "JSON schema for validating framed JSON-LD documents... Generated from CDIFDiscovery building block profile resolvedSchema.json (https://usgin.github.io/metadataBuildingBlocks/_sources/profiles/cdifProfiles/CDIFDiscovery/resolvedSchema.json)." -v

python generate_validation_schema.py path/to/CDIFcomplete/resolvedSchema.json \
  -o CDIFCompleteSchema.json \
  -t "CDIF Complete metadata schema" \
  -d "JSON schema for validating framed JSON-LD documents... Generated from CDIFcomplete building block profile resolvedSchema.json (https://usgin.github.io/metadataBuildingBlocks/_sources/profiles/cdifProfiles/CDIFcomplete/resolvedSchema.json)." -v

# Regenerate graph schema (JSON Schema for @graph documents)
python generate_graph_schema.py

# Regenerate composite SHACL shapes (both profiles)
python ShaclValidation/generate_shacl_shapes.py --profile discovery
python ShaclValidation/generate_shacl_shapes.py --profile complete
```

### Add or modify a building block

1. Edit source files in `_sources/` (schema.yaml, rules.shacl, etc.)
2. If adding a new building block to CDIFDiscovery:
   - Add its path to `CDIF_DISCOVERY_BLOCKS` in `ShaclValidation/generate_shacl_shapes.py`
   - Add mapping entries in `generate_graph_schema.py` if it defines a new type
3. Regenerate both schemas:
   ```bash
   python generate_graph_schema.py
   python ShaclValidation/generate_shacl_shapes.py
   ```
4. Validate example documents to verify

## Key file relationships

```
Building block _sources/
  resolvedSchema.json ──> generate_validation_schema.py ──> CDIFDiscoverySchema.json
                                                        ──> CDIFCompleteSchema.json
  *.Schema.json       ──> generate_graph_schema.py      ──> CDIF-graph-schema-2026.json
  rules.shacl         ──> ShaclValidation/generate_shacl_shapes.py ──> ShaclValidation/CDIF-Discovery-Shapes.ttl
                                                        ──> ShaclValidation/CDIF-Complete-Shapes.ttl

CDIF-frame-2026.jsonld + CDIFCompleteSchema.json ──> FrameAndValidate.py
ShaclValidation/CDIF-Discovery-Shapes.ttl   ──> ShaclValidation/ShaclJSONLDContext.py
ShaclValidation/CDIF-Complete-Shapes.ttl    ──> ShaclValidation/generate_shacl_report.py

batch_validate.py ──> FrameAndValidate.py (JSON Schema)
                  ──> ShaclValidation/ShaclJSONLDContext.py (SHACL)
```

## Schema conventions

- **`@type` flexibility**: All framed schema `@type` definitions use `anyOf` accepting both string and array. `FrameAndValidate.py` recursively normalizes all `@type` values to arrays after framing.
- **`spdx:Checksum` typing**: All `spdx:checksum` objects require `"@type": "spdx:Checksum"` (JSON Schema `required` + SHACL `sh:class`).
- **SHACL severity alignment**: Properties optional in JSON Schema use `sh:Warning` (not `sh:Violation`) in SHACL. Only structurally required properties use `sh:Violation`.
- **Activity name authority**: `provActivity/rules.shacl` is the sole source for `schema:name` checks on Activity nodes. Duplicates removed from `cdifProv/rules.shacl` and `action/rules.shacl`.
- **Action subtypes**: The `action` building block `@type` accepts an enum of 12 schema.org Action subtypes (Action, AssessAction, ConsumeAction, ControlAction, CreateAction, FindAction, InteractAction, MoveAction, PlayAction, SearchAction, TransferAction, UpdateAction). SHACL uses a SPARQL target with `FILTER IN` for the same set. The `webAPI` shape uses `sh:or` with all subtypes for `potentialAction`.
- **cdifOptional shape authority**: `cdifOptional/rules.shacl` is the authoritative source for `keywordsNoCommaTest` (accepts string, DefinedTerm, or IRI) and `relatedResourceProperty` (`schema:linkRelationship` accepts string, DefinedTerm, or IRI). These propagate via conflict resolution (cdifOptional wins over CDIFDiscovery).
- **additionalProperty value flexibility**: `additionalProperty/rules.shacl` allows any datatype for `schema:value` (not just `xsd:string`), since JSON-LD serializes numbers as `xsd:integer`/`xsd:decimal`. The JSON Schema also accepts `anyOf: [string, number, boolean, object]` for `schema:value`, plus `schema:unitCode` and `schema:unitText` properties.
- **`@context` layering**: `@context` is defined as a layered property across building blocks: `cdifMandatory` declares `schema` + `dcterms` (required) plus `spdx` + `dcat`; `cdifOptional` adds `geosparql`, `prov`, `dqv`, `cdi`; `CDIFDataDescription` profile adds `csvw`. These merge via allOf composition in profiles.
- **variableMeasured architecture**: `variableMeasured` items use `anyOf` in `cdifOptional` to accept either `cdifVariableMeasured` (PropertyValue with DDI-CDI extensions) or `StatisticalVariable` (separate BB). The `cdifDataDescription` BB adds `cdi:physicalDataType` requirement at the data description level (not discovery). `StatisticalVariable` is defined in its own `schemaorgProperties/statisticalVariable` building block.
- **`@type` array pattern in building blocks**: Building block `@type` definitions use `type: array` with `contains: {const: X}` and `minItems: 1` (array-only). Validation schemas use `anyOf` accepting both string and array for framing compatibility.
- **Root `@type` enum**: `cdifMandatory` constrains root `@type` items to an enum of 12 types (CreativeWork, SoftwareApplication, SoftwareSourceCode, Product, WebAPI, Dataset, DigitalDocument, Collection, ImageObject, DataCatalog, DefinedTermSet, MediaObject) with `contains: {const: schema:Dataset}` and `default: schema:Dataset`.
- **Context-aware array normalization**: `FrameAndValidate.py` wraps properties in arrays based on the enclosing `@type` context, not globally. Key context-dependent properties:
  - `schema:propertyID`: array inside `schema:variableMeasured` and `schema:additionalProperty` items; string on plain Identifiers
  - `schema:measurementTechnique`: array on `schema:Dataset` (root); scalar `anyOf[string, DefinedTerm]` inside `variableMeasured` items
  - `schema:encodingFormat`: array on `schema:DataDownload`; string on `schema:EntryPoint` (inside relatedLink/target)
  - `schema:alternateName`: array on variableMeasured and Place items; string on Person/Organization
  - `schema:contributor` inside `schema:Role`: unwrapped from single-element array to bare value (root contributor is an array of Role/Person/Org)
- **Action building block inlined `$defs`**: The `action` building block schema (`actionSchema.json`) has all sub-schemas (target_type, result_type, object_type, query-input_type) inlined directly into properties rather than using `$defs` with `$ref`. This prevents broken references when the OGC BB resolver flattens the action schema into parent schemas (e.g., webAPI potentialAction).

## Dependencies

```bash
pip install PyLD jsonschema rdflib pyshacl
```
