# CLAUDE.md - Project Guide for Claude Code

## Project overview

This repository contains validation tools for **CDIF (Cross-Domain Interoperability Framework)** JSON-LD metadata documents describing scientific datasets. Validation uses JSON Schema, SHACL rules, and RO-Crate structural checks.

## Key concepts

- **CDIF** metadata is JSON-LD built on schema.org, DDI-CDI, CSVW, PROV, and DQV vocabularies.
- JSON-LD is a **graph format**; JSON Schema validates **trees**. The **framing** step (via `CDIF-frame-2026.jsonld`) reshapes graphs into trees for schema validation.
- The framed (tree) schemas are split by profile: `CDIFDiscoverySchema.json` (discovery only) and `CDIFCompleteSchema.json` (discovery + data description). The original all-in-one `CDIF-JSONLD-schema-2026.json` is in `archive/`.
- The graph schema (`CDIF-graph-schema-2026.json`) validates **flattened** JSON-LD with `@graph` arrays directly, without framing. Generated from building block source schemas by `generate_graph_schema.py`.
- **`@type` flexibility**: The framed schema accepts `@type` as either a string or an array for most node types (DataDownload, PropertyValue, WebAPI, prov:Activity). JSON-LD framing may compact single-element arrays to strings; `FrameAndValidate.py` normalizes `@type` back to arrays at the root Dataset and `schema:subjectOf` levels after framing.

## Important files

| File | Role |
|------|------|
| `FrameAndValidate.py` | Main validation script: frames JSON-LD then validates against schema |
| `ConvertToROCrate.py` | Converts CDIF JSON-LD to RO-Crate format (library + CLI) |
| `ValidateROCrate.py` | Validates RO-Crate documents (imports conversion from ConvertToROCrate) |
| `validate-cdif.bat` | Windows batch wrapper for oXygen XML Editor integration |
| `batch_validate.py` | Batch validation of CDIF metadata files across multiple file groups |
| `CDIFDiscoverySchema.json` | JSON Schema for framed (tree) CDIF discovery profile metadata |
| `CDIFCompleteSchema.json` | JSON Schema for framed (tree) CDIF complete profile metadata |
| `CDIF-graph-schema-2026.json` | JSON Schema for flattened JSON-LD graphs (generated) |
| `generate_graph_schema.py` | Generates graph schema from building block source schemas |
| `CDIF-frame-2026.jsonld` | JSON-LD frame for 2026 schema |
| `CDIF-context-2026.jsonld` | JSON-LD context for prefix-free authoring |
| `ddi-cdi/ddi-cdi.schema_normative.json` | Full DDI-CDI normative JSON Schema (395 definitions) |
| `ddi-cdi/cls-InstanceVariable-resolved.json` | Resolved standalone schema for DDI-CDI InstanceVariable |
| `ddi-cdi/cls-InstanceVariable-resolved-README.md` | Documentation for the resolved schema generation |
| `ConvertToCroissant.py` | Converts CDIF JSON-LD to Croissant (mlcommons.org/croissant/1.0) format |
| `docs/CDIFtoCroissant.md` | Documents the CDIF-to-Croissant mapping, converter code, and gaps |
| `generate_shacl_shapes.py` | Generates composite SHACL shapes from building block rules.shacl files |
| `generate_shacl_report.py` | Generates markdown SHACL validation reports with severity grouping |
| `CDIF-Discovery-Core-Shapes.ttl` | Composite SHACL shapes for CDIFDiscovery profile (generated) |
| `CDIF-Complete-Shapes.ttl` | Composite SHACL shapes for CDIFcomplete profile (generated) |
| `CDIF-Discovery-Core-Shapes2.ttl` | Legacy hand-maintained SHACL shapes (superseded by generated versions) |
| `ShaclValidation/ShaclJSONLDContext.py` | SHACL validation script |
| `docs/CDIF-Provenance-Building-Blocks-Comparison.md` | Comparison of three provenance activity building blocks (cdifProv, provActivity, ddicdiProv) |

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

# SHACL validation (discovery profile)
python ShaclValidation/ShaclJSONLDContext.py metadata.jsonld CDIF-Discovery-Core-Shapes.ttl

# SHACL validation (complete profile)
python ShaclValidation/ShaclJSONLDContext.py metadata.jsonld CDIF-Complete-Shapes.ttl

# Generate a markdown SHACL validation report
python generate_shacl_report.py metadata.jsonld CDIF-Complete-Shapes.ttl -o report.md

# Batch validate all file groups (testJSONMetadata, cdifbook, cdifProfiles, adaProfiles)
python batch_validate.py

# Windows batch (for oXygen)
validate-cdif.bat path/to/metadata.jsonld

# Regenerate the flattened graph schema from building block sources
python generate_graph_schema.py
# Or with explicit paths:
python generate_graph_schema.py --bb-dir /path/to/_sources --output CDIF-graph-schema-2026.json

# Regenerate composite SHACL shapes (discovery profile, default)
python generate_shacl_shapes.py --profile discovery
# Regenerate composite SHACL shapes (complete profile)
python generate_shacl_shapes.py --profile complete
# Or with explicit paths:
python generate_shacl_shapes.py --bb-dir /path/to/_sources --output CDIF-Discovery-Core-Shapes.ttl
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
3. `@type` modified for dispatch disambiguation (e.g., cdifCatalogRecord becomes `dcat:CatalogRecord`, identifier adds `cdi:Identifier`)
4. `@context` stripped from non-root types (goes on root-graph wrapper only)
5. Composite types assembled: type-Dataset merges mandatory + optional, type-StructuredDataSet/TabularTextDataSet/LongStructureDataSet compose dataDownload + CDI extensions
6. type-Activity built from cdifProv building block (extended provenance with schema.org Action properties), requiring multi-typed `@type: ["schema:Action", "prov:Activity"]`, merging base generatedBy properties (`prov:used`) with extended properties (`schema:agent`, `schema:actionProcess`, etc.). Instruments are nested within `prov:used` items via `schema:instrument` sub-key (instruments are `prov:Entity` subclasses).

**Type dispatch order** (most specific first): `cdi:StructuredDataSet`, `cdi:TabularTextDataSet`, `cdi:LongStructureDataSet`, `cdi:InstanceVariable`, `cdi:Identifier`, `dcat:CatalogRecord`, `schema:Dataset`, `schema:Person`, `schema:Organization`, `schema:PropertyValue`, `schema:DefinedTerm`, `schema:CreativeWork`, `schema:DataDownload`, `schema:MediaObject`, `schema:WebAPI`, `schema:Action`, `schema:HowTo`, `schema:Place`, `time:ProperInterval`, `schema:MonetaryGrant`, `schema:Role`, `prov:Activity`, `dqv:QualityMeasurement`, `schema:Claim`.

## Composite SHACL shapes (generate_shacl_shapes.py)

`generate_shacl_shapes.py` reads CDIF building block `rules.shacl` files and merges them into a single composite Turtle file. Supports two profiles via `--profile`:

- **discovery** (default) → `CDIF-Discovery-Core-Shapes.ttl` — 64 shapes for the CDIFDiscovery profile
- **complete** → `CDIF-Complete-Shapes.ttl` — 76 shapes for the CDIFcomplete profile (discovery + data description + provenance)

**Building block source location**: Same auto-detection as `generate_graph_schema.py` — tries `BuildingBlockSubmodule/_sources/`, `../metadataBuildingBlocks/_sources/`, OneDrive paths. Override with `--bb-dir` or `CDIF_BB_DIR` env var.

**Discovery building blocks included** (22 rule sets, 21 unique after deduplication):
- Sub-building blocks: identifier, person, organization, definedTerm, dataDownload, webAPI, spatialExtent, temporalExtent, variableMeasured, funder, agentInRole, additionalProperty, labeledLink, action, generatedBy, derivedFrom, qualityMeasure
- CDIF composites: cdifCatalogRecord
- CDIF aggregates: cdifMandatory, cdifOptional
- Profile level: CDIFDiscovery

**Complete profile additions**: cdifProv, provActivity, cdifVariableMeasured, cdifPhysicalMapping, cdifDataCube, cdifTabularData, cdifLongData, CDIFDataDescription, CDIFcomplete.

**SOSO namespace-check shapes**: The cdifMandatory rules include 3 shapes from SOSO (Science on Schema.org) that detect incorrect schema.org namespace variants (`https://` instead of `http://`, missing trailing slash). These use the `soso:` prefix (`http://science-on-schema.org/1.2.3/validation/shacl#`).

**Conflict resolution**: When the same named shape URI (e.g., `cdifd:CDIFDefinedTermShape`) appears in multiple files, the script uses priority ordering — sub-building blocks (most specific) win over composites, which win over aggregates, which win over profile-level copies. Conflicts are logged with `--verbose`.

**Key conflicts resolved**:
- `cdifd:CDIFDefinedTermShape` — definedTerm (SPARQLTarget) wins over spatialExtent and agentInRole (targetClass copies)
- `cdifd:nameProperty` — person version wins over organization and cdifMandatory copies
- `cdifd:CDIFCatalogRecordShape` — cdifCatalogRecord wins over cdifMandatory and CDIFDiscovery copies
- `cdifd:CDIFDatasetMandatoryShape` — cdifMandatory wins over CDIFDiscovery profile copy

**Adding new building blocks**: Add the building block path to `CDIF_DISCOVERY_BLOCKS` (or `CDIF_COMPLETE_BLOCKS` for complete profile) in `generate_shacl_shapes.py`, then rerun the script.

## SHACL validation report (generate_shacl_report.py)

`generate_shacl_report.py` runs pyshacl validation and produces a structured markdown report. Issues are grouped by severity (Violation → Warning → Info), then by message. Each issue shows the focus node with its `@type` and `schema:name` for context.

```bash
# Generate report to file
python generate_shacl_report.py metadata.jsonld CDIF-Complete-Shapes.ttl -o report.md

# Print report to stdout
python generate_shacl_report.py metadata.jsonld CDIF-Discovery-Core-Shapes.ttl

# Named arguments
python generate_shacl_report.py -d metadata.jsonld -s CDIF-Complete-Shapes.ttl -o report.md -v
```

**Report structure**:
- Header with date, file paths, triple counts, conformance status, total issues
- Summary table by severity
- Detail sections for each severity level, with issues grouped by message and each showing the focus node description and constraint path

## DDI-CDI resolved schema

The `ddi-cdi/cls-InstanceVariable-resolved.json` was generated from `ddi-cdi/ddi-cdi.schema_normative.json` with these transformations:

1. Remove `_OF_` reverse relationship properties (767 removed; use JSON-LD `@reverse` instead)
2. Remove `catalogDetails` property and `dt-CatalogDetails` type from all classes
3. Omit `cls-DataPoint`, `cls-Datum`, `cls-RepresentedVariable` (simplified to IRI references)
4. Inline XSD primitive types (`xsd:string`, `xsd:integer`, `xsd:boolean`, `xsd:date`, `xsd:anyURI`, `xsd:language`)
5. Normalize `if/then/else` array patterns to `anyOf`
6. Definitions used >3 times go in `$defs`; others inlined; circular refs marked with `"$comment": "circular-ref"`

The DDI-CDI schema has pervasive circular dependencies (293 of 395 definitions). Removing reverse properties eliminates ~60%; the remaining ~123 are forward compositional cycles inherent to the data model.

## Extending the CDIF schema

When adding new properties:

1. Add to `CDIFCompleteSchema.json` (and `CDIFDiscoverySchema.json` if applicable) in appropriate `$defs` section
2. Add framing instructions to `CDIF-frame-2026.jsonld`
3. Add term mapping to `CDIF-context-2026.jsonld` (for prefix-free authoring)
4. If property should be array, add to `ARRAY_PROPERTIES` in `FrameAndValidate.py`
5. Update SHACL shapes if semantic constraints needed

## JSON-LD frame structure (CDIF-frame-2026.jsonld)

The frame reshapes flattened JSON-LD graphs into nested trees rooted at `schema:Dataset`. Most top-level properties use simple `"@embed": "@always"` directives. The `prov:wasGeneratedBy` section is the most complex, embedding the full activity structure:

- **`prov:used`** -- embeds items, including the `schema:instrument` sub-key pattern (with `schema:identifier`, `schema:additionalProperty`, and `schema:hasPart` for hierarchical instruments)
- **`schema:agent`** -- embeds with `schema:identifier`, `schema:contactPoint`, `schema:affiliation`
- **`schema:participant`** -- embeds with `schema:contributor`
- **`schema:instrument`** -- top-level embed for backward compatibility with older examples
- **`schema:actionProcess`** -- embeds with `schema:step` for HowTo methodology
- **`schema:location`**, **`schema:object`**, **`schema:result`**, **`schema:identifier`**, **`schema:additionalProperty`** -- simple embeds
- **`prov:generated`**, **`prov:wasAssociatedWith`** (with identifier/contactPoint/affiliation), **`prov:atLocation`**, **`prov:wasInformedBy`** -- PROV-O property embeds for provActivity building block

Other notable frame sections: `schema:distribution` embeds `schema:hasPart` for archive sub-files with physical mappings, `schema:creator`/`schema:contributor` embed affiliations and identifiers, and `schema:subjectOf` filters on `@type: schema:Dataset` for metadata-about-metadata records.

## ConvertToROCrate.py / ValidateROCrate.py architecture

Conversion and validation are split into two modules:
- **`ConvertToROCrate.py`** -- pure conversion library + standalone CLI. Can be imported (`from ConvertToROCrate import convert_to_rocrate`) or run directly.
- **`ValidateROCrate.py`** -- validation-only script that imports conversion from `ConvertToROCrate`. CLI unchanged.

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

Converts CDIF JSON-LD metadata to [Croissant](https://docs.mlcommons.org/croissant/docs/croissant-spec.html) (mlcommons.org/croissant/1.0) JSON-LD for ML dataset discovery and loading. See `docs/CDIFtoCroissant.md` for the full mapping documentation.

**Key mappings:**
- `schema:DataDownload` → `cr:FileObject`; archive `hasPart` items become FileObjects with `containedIn`
- `schema:variableMeasured` + `cdi:hasPhysicalMapping` → `cr:RecordSet` + `cr:Field` with `source.extract.column`
- `schema:propertyID` / `cdi:uses` → `cr:Field.equivalentProperty`
- CDIF-only properties (`prov:wasGeneratedBy`, `dqv:hasQualityMeasurement`, `schema:spatialCoverage`, etc.) are passed through verbatim with namespace prefixes added to `@context`
- Missing `schema:license` gets OGC `nil:missing` placeholder

**Data type mapping:** `xsd:decimal`→`sc:Float`, `String`→`sc:Text`, `xsd:dateTime`→`sc:Date`, `xsd:integer`→`sc:Integer`, `xsd:boolean`→`sc:Boolean`

## Test documents

- `MetadataExamples/` - Sample CDIF metadata files
  - `nwis-water-quality-longdata.json` -- NWIS water quality long data example using `cdi:LongStructureDataSet` with 20 CSV column variables (DescriptorComponent, ReferenceValueComponent, DimensionComponent, AttributeComponent roles) and 5 MeasureComponent domain variables. Validates against graph schema; framed schema validation has expected failures (no LongStructureDataSet branch in framed schema yet).
  - `prov-ocean-temp-example.json` -- Extended provenance example demonstrating `cdifProv` building block features: action chaining (QC activity → compilation activity via `schema:object`/`schema:result`), multi-typed activities (`["schema:Action", "prov:Activity"]`), agents with Role wrappers, inline `schema:HowTo` methodology via `schema:actionProcess` with 3 steps, diverse instruments (DefinedTerm, CreativeWork, strings), facility location (WHOI -- `schema:location` is where the activity was performed, not spatial coverage of the data), and backward-compatible `prov:used`.
- `BuildingBlockSubmodule/_sources/cdifProperties/cdifProv/exampleCdifProv.json` -- Single-node building block example: soil chemistry analysis activity (`["schema:Action", "prov:Activity"]`) with agent (Person with ORCID), `prov:used` array containing instrument wrapper (`schema:instrument` sub-key with DefinedTerm ICP-MS, `schema:alternateName` for specific model, `schema:additionalProperty` detection limit), vocab URI, sample description string, and CreativeWork EPA Method 6200. Action chaining (`schema:object`/`schema:result`), `schema:actionProcess` HowTo with 2 steps, facility location (Nevada Bureau of Mines), and temporal bounds. Companion `rules.shacl` provides SHACL validation shapes.
- `BuildingBlockSubmodule/_sources/ddiProperties/ddicdiProv/exampleDdicdiProv.json` -- Multi-node `@graph` document: same soil chemistry analysis scenario expressed in DDI-CDI vocabulary. Contains 8 graph nodes: `cdi:Activity` with `entityUsed`/`entityProduced` References and `has_Step` refs, 2 `cdi:Step` nodes with `script` (CommandCode/CommandFile) and `receives`/`produces` Parameter refs, 3 `cdi:Parameter` nodes with `entityBound` References, `cdi:ProcessingAgent` with ORCID identifier and `performs`/`operatesOn` links, `cdi:ProductionEnvironment` for the lab facility. Companion `rules.shacl` provides SHACL validation shapes.
- `BuildingBlockSubmodule/_sources/provProperties/provActivity/exampleProvActivity.json` -- Single-node building block example: same soil chemistry analysis scenario expressed in PROV-O vocabulary. `@type: ["prov:Activity"]` (single-typed, no `schema:Action`), `prov:used` array containing instrument wrapper (`schema:instrument` sub-key with DefinedTerm ICP-MS), vocab URI, sample description string, and CreativeWork EPA Method 6200. `prov:generated` output reference, `prov:wasAssociatedWith` agent (Person with ORCID), `prov:wasInformedBy` activity chain, `prov:startedAtTime`/`prov:endedAtTime` temporal bounds, `prov:atLocation` facility (Nevada Bureau of Mines), `schema:actionStatus`, `schema:actionProcess` HowTo with 2 steps. Companion `rules.shacl` provides SHACL validation shapes.
- `testJSONMetadata/` - 77 ADA metadata test files. The `schema:subjectOf` catalog record uses `@type: ["schema:Dataset"]` with `schema:additionalType: ["dcat:CatalogRecord"]` (updated from the previous `@type: "dcat:CatalogRecord"` pattern). Context includes `dcat`, `xas`, and `nxs` prefixes.
- `../integrationPublic/exampleMetadata/CDIF2026/` - 2026 schema examples
- `../integrationPublic/LongData/` - Long data CSV and older (pre-2026) long data metadata examples

## Known issues

### `schema:actionProcess` -- in schema.org but not in the RDF export

The property `schema:actionProcess` (domain: `schema:Action`, range: `schema:HowTo`) was added to schema.org via [PR #3692](https://github.com/schemaorg/schemaorg/issues/3692), merged 2024-10-22. It is listed on the [schema.org website](https://schema.org/actionProcess) as of V29.4, but has **not yet appeared** in the downloadable RDF vocabulary files ([schemaorg-current-https.jsonld](https://schema.org/version/latest/schemaorg-current-https.jsonld) and the `-all-` variant). This is a lag in the RDF export, not a missing property.

The [ODIS provenance recommendations](https://github.com/iodepo/odis-arch/blob/414-update-provenance-recommendations/book/thematics/provenance/common-provenance-cases.md) use `actionProcess` to link Actions to HowTo methodologies with ordered HowToStep arrays.

### `prov:wasGeneratedBy` has no schema.org equivalent

There is no schema.org property that maps to `prov:wasGeneratedBy` (linking an Entity to the Activity that produced it). Schema.org has `schema:result` (Action→Entity, forward direction) but nothing in the reverse direction. CDIF retains `prov:wasGeneratedBy` from PROV-O for this purpose.

**CDIF provenance chain pattern**: `Dataset --prov:wasGeneratedBy--> {"@type": ["schema:Action", "prov:Activity"]} --schema:actionProcess--> schema:HowTo`. Activity nodes are multi-typed to get both PROV linkage and schema.org Action properties (`agent`, `object`, `result`, `startTime`, `endTime`, `actionStatus`, `location`, `participant`). Instruments are nested within `prov:used` items via a `schema:instrument` sub-key, since instruments are `prov:Entity` subclasses that are "used" by an activity.

## Provenance building blocks comparison

`docs/CDIF-Provenance-Building-Blocks-Comparison.md` documents and compares the three building blocks for describing activities (the value of `prov:wasGeneratedBy`):

- **cdifProv** (schema.org-first) -- dual-typed `["schema:Action", "prov:Activity"]`, uses schema.org properties (`agent`, `object`, `result`, `startTime`, `location`, `actionProcess`). Primary CDIF recommendation, aligned with [ODIS provenance recommendations](https://github.com/iodepo/odis-arch/blob/414-update-provenance-recommendations/book/thematics/provenance/common-provenance-cases.md).
- **provActivity** (PROV-O-first) -- single-typed `["prov:Activity"]`, uses PROV-O properties (`wasAssociatedWith`, `generated`, `startedAtTime`, `atLocation`, `wasInformedBy`) with schema.org fallbacks for gaps.
- **ddicdiProv** (DDI-CDI native) -- `cdi:Activity` with separate graph nodes for Steps, Parameters, ProcessingAgent, ProductionEnvironment. Multi-node `@graph` serialization.

The comparison includes property mappings, benefits/challenges, usage recommendations, and links to resolved schemas and examples on GitHub. All three share a common soil chemistry analysis scenario for direct comparison.

## ddicdiProv building block (DDI-CDI native provenance)

Located at `BuildingBlockSubmodule/_sources/ddiProperties/ddicdiProv/`. Implements the same provenance concepts as `cdifProv` (activities, agents, inputs/outputs, steps, instruments) but using **DDI-CDI vocabulary** natively, for communities already using that standard. Based on the BBeuster EU-SoGreen-Prov example pattern.

**Files:**

| File | Role |
|------|------|
| `bblock.json` | Building block metadata |
| `schema.yaml` | YAML schema source (human-editable) |
| `ddicdiProvSchema.json` | JSON Schema (Draft 2020-12) |
| `resolvedSchema.json` | Fully resolved schema (all `$ref` inlined, circular refs marked with `$comment`) |
| `rules.shacl` | SHACL validation shapes (Activity, Step, ProcessingAgent) |
| `exampleDdicdiProv.json` | Example `@graph` document (soil chemistry scenario) |
| `examples.yaml` | Example reference metadata |

**Key differences from cdifProv:**

| Aspect | cdifProv | ddicdiProv |
|--------|----------|------------|
| Activity type | `["schema:Action", "prov:Activity"]` | `cdi:Activity` |
| Inputs/outputs | `prov:used`, `schema:result` | `cdi:entityUsed`, `cdi:entityProduced` (References) |
| Agent | `schema:agent` (inline Person/Org) | Separate `cdi:ProcessingAgent` node with `cdi:performs` |
| Methodology | `schema:actionProcess` → HowTo/Steps | `cdi:has_Step` → separate Step nodes with `cdi:script` (CommandCode) |
| Data flow | Not explicit | `cdi:receives`/`cdi:produces` → Parameter nodes |
| Temporal bounds | `schema:startTime`/`endTime` | Not expressible (DDI-CDI gap) |
| Location | `schema:location` | Not expressible (DDI-CDI gap) |
| Status | `schema:actionStatus` | Not expressible (DDI-CDI gap) |
| Serialization | Single-node tree | Multi-node `@graph` document |

**Schema `$defs`** (15 definitions): `id-reference`, `ObjectName`, `LabelForDisplay`, `LanguageString`, `Identifier`, `InternationalRegistrationDataIdentifier`, `NonDdiIdentifier`, `Reference`, `Step`, `CommandCode`, `Command`, `CommandFile`, `ControlledVocabularyEntry`, `Parameter`, `ProcessingAgent`, `ProductionEnvironment`.

**Schema pattern for graph links**: Properties referencing other graph nodes use `anyOf [inline-typed-object, id-reference]` -- e.g., `cdi:has_Step` accepts either an inline Step object or an `{"@id": "..."}` reference. Self-referencing properties (`cdi:hasSubActivity`, `cdi:performs`) use `$ref: "#"` to point back to the root Activity schema.

**DDI-CDI provenance chain pattern**: `Dataset --prov:wasGeneratedBy--> cdi:Activity --cdi:has_Step--> cdi:Step --cdi:receives/cdi:produces--> cdi:Parameter`. Agent linkage is inverted: `cdi:ProcessingAgent --cdi:performs--> cdi:Activity`.

## provActivity building block (PROV-O native provenance)

Located at `BuildingBlockSubmodule/_sources/provProperties/provActivity/`. Implements the same provenance concepts as `cdifProv` and `ddicdiProv` (activities, agents, inputs/outputs, methodology, temporal bounds) but using **W3C PROV-O vocabulary** as the primary vocabulary, with schema.org fallbacks only where PROV-O has no equivalent property.

**Files:**

| File | Role |
|------|------|
| `bblock.json` | Building block metadata |
| `schema.yaml` | YAML schema source (human-editable) |
| `provActivitySchema.json` | JSON Schema (Draft 2020-12) |
| `rules.shacl` | SHACL validation shapes (Activity, HowTo, HowToStep) |
| `exampleProvActivity.json` | Example single-node document (soil chemistry scenario) |
| `examples.yaml` | Example reference metadata |

**Schema composition**: Extends `generatedBy` via `allOf` (same pattern as cdifProv). The base provides `@type` containing `prov:Activity` and `prov:used`. provActivity adds all remaining PROV-O and schema.org fallback properties on top.

**Property vocabulary mapping** (PROV-O first, schema.org fallback):

| Concept | provActivity property | cdifProv equivalent | Notes |
|---------|----------------------|---------------------|-------|
| Activity type | `prov:Activity` (single) | `["schema:Action", "prov:Activity"]` (dual) | No schema:Action needed |
| Name | `schema:name` | `schema:name` | schema.org fallback (no PROV equivalent) |
| Description | `schema:description` | `schema:description` | schema.org fallback |
| Inputs | `prov:used` | `prov:used` | Same (from generatedBy base) |
| Outputs | `prov:generated` | `schema:result` | PROV-O native (inverse of wasGeneratedBy) |
| Agent | `prov:wasAssociatedWith` | `schema:agent` | PROV-O native |
| Start time | `prov:startedAtTime` | `schema:startTime` | PROV-O native (xsd:dateTime) |
| End time | `prov:endedAtTime` | `schema:endTime` | PROV-O native (xsd:dateTime) |
| Location | `prov:atLocation` | `schema:location` | PROV-O expanded term |
| Activity chain | `prov:wasInformedBy` | `schema:object`/`schema:result` | PROV-O native (Activity->Activity) |
| Start trigger | `prov:wasStartedBy` | -- | PROV-O expanded term (Entity triggers Activity) |
| End trigger | `prov:wasEndedBy` | -- | PROV-O expanded term |
| Instrument | nested in `prov:used` via `schema:instrument` sub-key | nested in `prov:used` via `schema:instrument` sub-key | Instruments are `prov:Entity` subclasses within `prov:used` |
| Status | `schema:actionStatus` | `schema:actionStatus` | schema.org fallback |
| Methodology | `schema:actionProcess` | `schema:actionProcess` | schema.org fallback (PROV `hadPlan` is qualified-only) |
| Error | `schema:error` | `schema:error` | schema.org fallback |

**Schema `$defs`**: External refs to `Person`, `Organization`, `AgentInRole`, `Instrument`, `DefinedTerm`, `LabeledLink`, `SpatialExtent` (via `../../schemaorgProperties/*/schema.yaml`). Local definitions for `HowTo` and `HowToStep` (same as cdifProv).

**SHACL shapes** (3 shapes, same severity pattern as cdifProv):
- `provActivityShape` -- SPARQL-targeted on `prov:Activity` nodes (standalone or via `prov:wasGeneratedBy`). Required: `prov:used` (minCount 1), `schema:name` (minCount 1, minLength 5). Warning: `schema:description`, `prov:wasAssociatedWith`, `prov:startedAtTime`, `prov:endedAtTime`. Info: `prov:generated`, `prov:wasInformedBy`, `prov:atLocation`, `schema:instrument`, `schema:actionStatus`, `schema:actionProcess`.
- `provActivityHowToShape` -- targetClass `schema:HowTo`. Required: `schema:name`. Warning: `schema:step`.
- `provActivityHowToStepShape` -- targetClass `schema:HowToStep`. Required: `schema:name`. Warning: `schema:position`.

**Qualified pattern deferred**: PROV-O qualified influences (`prov:qualifiedAssociation`, `prov:qualifiedUsage`, `prov:qualifiedGeneration`, etc.) are not included to keep complexity parallel with cdifProv and ddicdiProv.

**PROV-O provenance chain pattern**: `Dataset --prov:wasGeneratedBy--> prov:Activity --schema:actionProcess--> schema:HowTo`. Activity chain: `prov:Activity --prov:wasInformedBy--> prov:Activity`.

## Instrument building block (generic instrument)

Located at `BuildingBlockSubmodule/_sources/schemaorgProperties/instrument/`. Defines a generic instrument or instrument system using `schema:Thing` as the base type, with optional `schema:Product` or domain-specific typing. Supports hierarchical instrument systems via `schema:hasPart` for sub-components.

**Files:**

| File | Role |
|------|------|
| `bblock.json` | Building block metadata |
| `schema.yaml` | YAML schema source |
| `instrumentSchema.json` | JSON Schema (Draft 2020-12) |
| `exampleInstrument.json` | Example ICP-MS system with sub-components |
| `examples.yaml` | Example reference metadata |

**Key properties**: `@type` (must include `schema:Thing`), `schema:name` (required), `schema:identifier`, `schema:description`, `schema:alternateName` (specific make/model), `schema:additionalType` (domain-specific type URIs), `schema:additionalProperty` (detection limits, calibration info, etc.), `schema:hasPart` (recursive sub-components or `@id` references).

**Schema `$defs`**: `Identifier` (via `../identifier/schema.yaml`), `AdditionalProperty` (via `../additionalProperty/schema.yaml`).

**Instrument nesting pattern**: Instruments are not top-level Activity properties. Instead, they are nested within `prov:used` items via a `schema:instrument` sub-key, reflecting that instruments are `prov:Entity` subclasses that are "used" by an activity. Both `cdifProv` and `provActivity` building blocks include an `Instrument` $def referencing this building block. Example:

```json
"prov:used": [
    {
        "schema:instrument": {
            "@type": ["schema:Thing", "schema:Product"],
            "schema:name": "ICP-MS Analytical System",
            "schema:hasPart": [
                {"@type": ["schema:Thing"], "schema:name": "autosampler"},
                {"@type": ["schema:Thing"], "schema:name": "spray chamber"}
            ]
        }
    },
    "https://vocab.example.org/method/LAB02",
    "Sample description string"
]
```

**XAS instrument extensions**: The `xasInstrument` building block (`xasProperties/xasInstrument/`) extends the generic instrument with required `wd:Q3099911` (scientific instrument) `schema:additionalType` and adds `schema:hasPart` referencing the generic instrument for sub-components. XAS profile schemas (`xasRequired`, `xasOptional`) validate that `prov:used` contains an instrument wrapper with specific NXsource and NXmonochromator sub-components in `schema:hasPart`.

**`schema:object` replaces `schema:mainEntity`**: In xasGeneratedBy (and xasRequired/xasOptional profiles), `schema:mainEntity` has been renamed to `schema:object` for the sample being analyzed, per Ocean Info Hub recommendation. `schema:object` is the standard schema.org Action property for the input entity.
