# CLAUDE.md - Project Guide for Claude Code

## Project overview

This repository contains validation tools for **CDIF (Cross-Domain Interoperability Framework)** JSON-LD metadata documents describing scientific datasets. Validation uses JSON Schema, SHACL rules, and RO-Crate structural checks.

## Key concepts

- **CDIF** metadata is JSON-LD built on schema.org, DDI-CDI, CSVW, PROV, and DQV vocabularies.
- JSON-LD is a **graph format**; JSON Schema validates **trees**. The **framing** step (via `CDIF-frame-2026.jsonld`) reshapes graphs into trees for schema validation.
- The 2026 schema (`CDIF-JSONLD-schema-2026.json`) is the current default for framed (tree) validation.
- The graph schema (`CDIF-graph-schema-2026.json`) validates **flattened** JSON-LD with `@graph` arrays directly, without framing. Generated from building block source schemas by `generate_graph_schema.py`.

## Important files

| File | Role |
|------|------|
| `FrameAndValidate.py` | Main validation script: frames JSON-LD then validates against schema |
| `ConvertToROCrate.py` | Converts CDIF JSON-LD to RO-Crate format (library + CLI) |
| `ValidateROCrate.py` | Validates RO-Crate documents (imports conversion from ConvertToROCrate) |
| `validate-cdif.bat` | Windows batch wrapper for oXygen XML Editor integration |
| `CDIF-JSONLD-schema-2026.json` | Current JSON Schema for framed (tree) CDIF metadata |
| `CDIF-graph-schema-2026.json` | JSON Schema for flattened JSON-LD graphs (generated) |
| `generate_graph_schema.py` | Generates graph schema from building block source schemas |
| `CDIF-frame-2026.jsonld` | JSON-LD frame for 2026 schema |
| `CDIF-context-2026.jsonld` | JSON-LD context for prefix-free authoring |
| `ddi-cdi.schema_normative.json` | Full DDI-CDI normative JSON Schema (395 definitions) |
| `cls-InstanceVariable-resolved.json` | Resolved standalone schema for DDI-CDI InstanceVariable |
| `cls-InstanceVariable-resolved-README.md` | Documentation for the resolved schema generation |
| `ConvertToCroissant.py` | Converts CDIF JSON-LD to Croissant (mlcommons.org/croissant/1.0) format |
| `CDIFtoCroissant.md` | Documents the CDIF-to-Croissant mapping, converter code, and gaps |
| `CDIF-Discovery-Core-Shapes2.ttl` | SHACL shapes for semantic validation |
| `ShaclValidation/ShaclJSONLDContext.py` | SHACL validation script |

## Common commands

```bash
# Validate a CDIF document
python FrameAndValidate.py path/to/metadata.jsonld -v

# Frame and save output for debugging
python FrameAndValidate.py path/to/metadata.jsonld -o framed.json -v

# Convert CDIF to RO-Crate (standalone, no validation)
python ConvertToROCrate.py path/to/metadata.jsonld -o output-rocrate.jsonld

# Validate as RO-Crate (converts then validates)
python ValidateROCrate.py path/to/metadata.jsonld

# Convert CDIF to Croissant (ML dataset format)
python ConvertToCroissant.py path/to/metadata.jsonld -o output-croissant.json -v

# Validate Croissant output (requires: pip install mlcroissant)
mlcroissant validate --jsonld output-croissant.json

# SHACL validation
python ShaclValidation/ShaclJSONLDContext.py metadata.jsonld CDIF-Discovery-Core-Shapes2.ttl

# Windows batch (for oXygen)
validate-cdif.bat path/to/metadata.jsonld

# Regenerate the flattened graph schema from building block sources
python generate_graph_schema.py
# Or with explicit paths:
python generate_graph_schema.py --bb-dir /path/to/_sources --output CDIF-graph-schema-2026.json
```

## Dependencies

```bash
pip install PyLD jsonschema rdflib pyshacl

# Optional: for thorough SHACL-based RO-Crate validation (requires Python >= 3.10)
pip install roc-validator

# Optional: for Croissant output validation
pip install mlcroissant
```

## Flattened graph schema (generate_graph_schema.py)

`generate_graph_schema.py` reads CDIF building block source schemas and generates a single self-contained JSON Schema (`CDIF-graph-schema-2026.json`) that validates flattened JSON-LD graphs. This is the graph-based counterpart to the framed tree schema.

**Building block source location**: Auto-detected from `USGIN/metadataBuildingBlocks/_sources/` or `smrgeoinfo/OCGbuildingBlockTest/_sources/`. Override with `--bb-dir` or `CDIF_BB_DIR` env var.

**Schema structure**:
- Root: dispatches objects, arrays, or `{@context, @graph}` documents
- `root-object`: nested if/then/else chain dispatching by `@type` (24 type branches, most specific first)
- `root-graph`: validates `@context` prefixes + `@graph` array of nodes
- `id-reference`: shared `{@id: string}` definition for cross-node references
- 24 type definitions: `type-Dataset`, `type-Person`, `type-Organization`, `type-HowTo`, `type-Claim`, etc.

**Key transformations from source schemas**:
1. External `$ref`s between building blocks resolved to `#/$defs/type-X` references
2. Properties referencing other building block types get `anyOf [type-ref, id-reference]` alternatives
3. `@type` modified for dispatch disambiguation (e.g., metaMetadata becomes `dcat:CatalogRecord`, identifier adds `cdi:Identifier`)
4. `@context` stripped from non-root types (goes on root-graph wrapper only)
5. Composite types assembled: type-Dataset merges mandatory + optional, type-StructuredDataSet/TabularTextDataSet/LongStructureDataSet compose dataDownload + CDI extensions
6. type-Activity built from cdifProv building block (extended provenance with schema.org Action properties), requiring multi-typed `@type: ["schema:Action", "prov:Activity"]`, merging base generatedBy properties (`prov:used`) with extended properties (`schema:agent`, `schema:instrument`, `schema:actionProcess`, etc.)

**Type dispatch order** (most specific first): `cdi:StructuredDataSet`, `cdi:TabularTextDataSet`, `cdi:LongStructureDataSet`, `cdi:InstanceVariable`, `cdi:Identifier`, `dcat:CatalogRecord`, `schema:Dataset`, `schema:Person`, `schema:Organization`, `schema:PropertyValue`, `schema:DefinedTerm`, `schema:CreativeWork`, `schema:DataDownload`, `schema:MediaObject`, `schema:WebAPI`, `schema:Action`, `schema:HowTo`, `schema:Place`, `time:ProperInterval`, `schema:MonetaryGrant`, `schema:Role`, `prov:Activity`, `dqv:QualityMeasurement`, `schema:Claim`.

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

## ConvertToROCrate.py / ValidateROCrate.py architecture

Conversion and validation are split into two modules:
- **`ConvertToROCrate.py`** — pure conversion library + standalone CLI. Can be imported (`from ConvertToROCrate import convert_to_rocrate`) or run directly.
- **`ValidateROCrate.py`** — validation-only script that imports conversion from `ConvertToROCrate`. CLI unchanged.

**Conversion pipeline** (in `ConvertToROCrate.py`, uses `pyld`):
1. Enrich input `@context` with CDIF namespace prefixes (forces `schema` to `http://` for RO-Crate compatibility)
2. Expand (resolve all prefixes to full IRIs)
3. Flatten (produce `@graph` with flat entities and `@id` references)
4. Compact with RO-Crate 1.1 context
5. Inject `ro-crate-metadata.json` descriptor entity, remap root Dataset `@id` to `"./"`

**Current validation** (in `ValidateROCrate.py`): 13 hand-coded structural checks (context present, `@graph` is flat array, metadata descriptor with `conformsTo`, root Dataset with `datePublished`/`name`/`description`/`license`, all entities have `@id` and `@type`, no nested entities, no `../` in IDs, context references RO-Crate 1.1).

### rocrate-validator integration

The `rocrate-validator` library provides thorough SHACL-based RO-Crate validation alongside the existing custom structural checks.

- **PyPI package**: `roc-validator` (`pip install roc-validator`), requires Python >= 3.10
- **Import name**: `rocrate_validator` (underscore)
- **Key API**: `rocrate_validator.services.validate_metadata_as_dict(metadata_dict, settings)` validates an in-memory dict without needing files on disk
- **Settings**: `rocrate_validator.services.ValidationSettings(rocrate_uri='.', profile_identifier='ro-crate-1.1', requirement_severity=models.Severity.REQUIRED)`
- **Severity levels**: `rocrate_validator.models.Severity` enum: `OPTIONAL`, `RECOMMENDED`, `REQUIRED`
- **Result object**: `ValidationResult` with `.has_issues()`, `.passed()`, `.get_issues()` methods
- **Issue objects**: `CheckIssue` with `.message`, `.severity`, `.check.identifier`, `.violatingEntity`, `.violatingProperty`
- **Import should be optional** with graceful fallback when library is not installed
- Runs after the existing 13 custom structural checks, printing results in a matching format
- CLI flags: `--no-rocrate-validator` to skip, `--severity` to control minimum level (REQUIRED, RECOMMENDED, OPTIONAL)

## ConvertToCroissant.py (CDIF to Croissant)

Converts CDIF JSON-LD metadata to [Croissant](https://docs.mlcommons.org/croissant/docs/croissant-spec.html) (mlcommons.org/croissant/1.0) JSON-LD for ML dataset discovery and loading. See `CDIFtoCroissant.md` for the full mapping documentation.

**Key mappings:**
- `schema:DataDownload` → `cr:FileObject`; archive `hasPart` items become FileObjects with `containedIn`
- `schema:variableMeasured` + `cdi:hasPhysicalMapping` → `cr:RecordSet` + `cr:Field` with `source.extract.column`
- `schema:propertyID` / `cdi:uses` → `cr:Field.equivalentProperty`
- CDIF-only properties (`prov:wasGeneratedBy`, `dqv:hasQualityMeasurement`, `schema:spatialCoverage`, etc.) are passed through verbatim with namespace prefixes added to `@context`
- Missing `schema:license` gets OGC `nil:missing` placeholder

**Data type mapping:** `xsd:decimal`→`sc:Float`, `String`→`sc:Text`, `xsd:dateTime`→`sc:Date`, `xsd:integer`→`sc:Integer`, `xsd:boolean`→`sc:Boolean`

## Test documents

- `MetadataExamples/` - Sample CDIF metadata files
  - `nwis-water-quality-longdata.json` — NWIS water quality long data example using `cdi:LongStructureDataSet` with 20 CSV column variables (DescriptorComponent, ReferenceValueComponent, DimensionComponent, AttributeComponent roles) and 5 MeasureComponent domain variables. Validates against graph schema; framed schema validation has expected failures (no LongStructureDataSet branch in framed schema yet).
  - `prov-ocean-temp-example.json` — Extended provenance example demonstrating `cdifProv` building block features: action chaining (QC activity → compilation activity via `schema:object`/`schema:result`), multi-typed activities (`["schema:Action", "prov:Activity"]`), agents with Role wrappers, inline `schema:HowTo` methodology via `schema:actionProcess` with 3 steps, diverse instruments (DefinedTerm, CreativeWork, strings), facility location (WHOI — `schema:location` is where the activity was performed, not spatial coverage of the data), and backward-compatible `prov:used`.
- `BuildingBlockSubmodule/_sources/cdifProperties/cdifProv/exampleCdifProv.json` — Single-node building block example: soil chemistry analysis activity (`["schema:Action", "prov:Activity"]`) with agent (Person with ORCID), instrument (DefinedTerm ICP-MS with `schema:alternateName` for specific model and `schema:additionalProperty` detection limit), `prov:used` array (vocab URI, sample description string, CreativeWork EPA Method 6200), action chaining (`schema:object`/`schema:result`), `schema:actionProcess` HowTo with 2 steps, facility location (Nevada Bureau of Mines), and temporal bounds. Companion `rules.shacl` provides SHACL validation shapes.
- `../integrationPublic/exampleMetadata/CDIF2026/` - 2026 schema examples
- `../integrationPublic/LongData/` - Long data CSV and older (pre-2026) long data metadata examples

## Known issues

### `schema:actionProcess` — in schema.org but not in the RDF export

The property `schema:actionProcess` (domain: `schema:Action`, range: `schema:HowTo`) was added to schema.org via [PR #3692](https://github.com/schemaorg/schemaorg/issues/3692), merged 2024-10-22. It is listed on the [schema.org website](https://schema.org/actionProcess) as of V29.4, but has **not yet appeared** in the downloadable RDF vocabulary files ([schemaorg-current-https.jsonld](https://schema.org/version/latest/schemaorg-current-https.jsonld) and the `-all-` variant). This is a lag in the RDF export, not a missing property.

The [ODIS provenance recommendations](https://github.com/iodepo/odis-arch/blob/414-update-provenance-recommendations/book/thematics/provenance/common-provenance-cases.md) use `actionProcess` to link Actions to HowTo methodologies with ordered HowToStep arrays.

### `prov:wasGeneratedBy` has no schema.org equivalent

There is no schema.org property that maps to `prov:wasGeneratedBy` (linking an Entity to the Activity that produced it). Schema.org has `schema:result` (Action→Entity, forward direction) but nothing in the reverse direction. CDIF retains `prov:wasGeneratedBy` from PROV-O for this purpose.

**CDIF provenance chain pattern**: `Dataset --prov:wasGeneratedBy--> {"@type": ["schema:Action", "prov:Activity"]} --schema:actionProcess--> schema:HowTo`. Activity nodes are multi-typed to get both PROV linkage and schema.org Action properties (`agent`, `instrument`, `object`, `result`, `startTime`, `endTime`, `actionStatus`, `location`, `participant`).
