# Relationship of ADA/CDIF Metadata Profiles to RO-Crate

## Overview

The [adaProduct](https://github.com/usgin/metadataBuildingBlocks/tree/main/_sources/profiles/adaProfiles/adaProduct) and [CDIFcomplete](https://github.com/usgin/metadataBuildingBlocks/tree/main/_sources/profiles/cdifProfiles/CDIFcomplete) building block profiles produce JSON-LD metadata that shares a common vocabulary foundation with [RO-Crate](https://www.researchobject.org/ro-crate/) (Research Object Crate). Both systems build on [schema.org](https://schema.org) types and properties to describe datasets, files, people, and organizations. This document describes the property-level correspondences, the structural differences, and how `ValidateROCrate.py` converts ADA or CDIF metadata into a conformant `ro-crate-metadata.json`.

## What is RO-Crate?

RO-Crate is a community specification for packaging research data with structured metadata. An RO-Crate is a directory (or archive) containing a `ro-crate-metadata.json` file that describes the dataset and its constituent files using JSON-LD with schema.org vocabulary. Key characteristics:

- **Flat `@graph` structure** -- all entities (dataset, files, people, organizations) appear as top-level objects in a flat `@graph` array, cross-referenced by `@id`.
- **Metadata File Descriptor** -- a `CreativeWork` entity with `@id: "ro-crate-metadata.json"` that points to the Root Data Entity via `about`.
- **Root Data Entity** -- a `Dataset` entity (typically `@id: "./"`) describing the crate as a whole.
- **Data Entities** -- `File` (alias for `MediaObject`) and `Dataset` entities representing files and folders.
- **Contextual Entities** -- `Person`, `Organization`, `Place`, etc. entities referenced from the data entities.

See the [RO-Crate 1.2 specification](https://www.researchobject.org/ro-crate/specification/1.2/introduction.html) and [quick reference](https://www.researchobject.org/ro-crate/quick-reference) for details.

## Property Mapping: adaProduct / CDIFcomplete to RO-Crate

Both profiles and RO-Crate use schema.org as their primary vocabulary, so many properties map directly. The table below shows how metadata from the ADA/CDIF profiles corresponds to RO-Crate Root Data Entity properties.

### Root Data Entity (Dataset)

| ADA / CDIF Property | RO-Crate Property | Notes |
|---|---|---|
| `@type: ["schema:Dataset", ...]` | `@type: "Dataset"` | ADA adds `"schema:Product"`; RO-Crate requires `Dataset` |
| `schema:name` | `name` | Direct mapping |
| `schema:description` | `description` | Direct mapping |
| `schema:dateModified` | `datePublished` | RO-Crate requires `datePublished` (MUST); ADA uses `dateModified`. Use `schema:datePublished` if present, fall back to `dateModified` |
| `schema:identifier` | `identifier` | ADA uses structured `PropertyValue`; RO-Crate recommends DOI URI string |
| `schema:license` | `license` | ADA stores as array of URI strings; RO-Crate expects `{"@id": "..."}` reference to a contextual entity |
| `schema:url` | `url` | Direct mapping (landing page) |
| `schema:keywords` | `keywords` | ADA allows mixed `DefinedTerm` objects and strings; RO-Crate expects strings or `DefinedTerm` references |
| `schema:creator` | `author` | ADA uses `schema:creator` with `@list`; RO-Crate uses `author` with entity references |
| `schema:contributor` | `contributor` | ADA wraps in `schema:Role`; RO-Crate uses flat entity references |
| `schema:funding` | `funder` / `funding` | ADA uses `MonetaryGrant` with nested `funder`; RO-Crate uses contextual entity references |
| `schema:publisher` / `schema:provider` | `publisher` | Direct mapping via entity reference |
| `schema:spatialCoverage` | `spatialCoverage` | Both use `schema:Place` with `schema:geo` |
| `schema:temporalCoverage` | `temporalCoverage` | Direct mapping (ISO 8601 interval string) |
| `schema:version` | `version` | Direct mapping |
| `schema:distribution` | `hasPart` | **Structural difference** -- see below |
| `schema:subjectOf` | (metadata descriptor) | ADA/CDIF meta-metadata maps to the RO-Crate Metadata File Descriptor entity |
| `dcterms:conformsTo` | `conformsTo` | Profile declarations move to Root Data Entity `conformsTo` |
| `prov:wasGeneratedBy` | -- | ADA-specific; can be included as additional schema.org/PROV-O properties |
| `schema:variableMeasured` | -- | CDIF data description; can be included as `variableMeasured` contextual entities |

### Data Entities (Files)

| ADA / CDIF Property | RO-Crate Property | Notes |
|---|---|---|
| `@type` (e.g., `["ada:image", "schema:ImageObject"]`) | `@type: "File"` | RO-Crate uses `File` (alias for `MediaObject`); additional types can be kept |
| `schema:name` | `name` | Filename within the archive |
| `schema:description` | `description` | Direct mapping |
| `schema:encodingFormat` | `encodingFormat` | ADA stores as array; RO-Crate expects single MIME string |
| `schema:size` | `contentSize` | ADA uses structured `QuantitativeValue`; RO-Crate expects byte count string |
| `spdx:checksum` | -- | No direct RO-Crate equivalent; preserved as additional property |
| `schema:additionalType` | `additionalType` | ADA component types can be preserved |
| `componentType` | -- | ADA-specific detail; can be preserved as additional property |

### Contextual Entities (People, Organizations)

| ADA / CDIF Property | RO-Crate Property | Notes |
|---|---|---|
| `schema:Person` with `schema:name`, `schema:identifier` | `Person` with `name`, ORCID `@id` | RO-Crate prefers ORCID as `@id` rather than nested identifier |
| `schema:Organization` with `schema:name` | `Organization` with `name`, ROR `@id` | RO-Crate prefers ROR identifier as `@id` |
| `schema:Place` | `Place` | ADA instruments/labs map to contextual entities |

## Key Structural Differences

### 1. Nested vs. Flat Graph

The most significant difference is the document structure:

- **ADA/CDIF metadata** uses nested JSON-LD -- persons, organizations, files, and distributions are embedded inline within the dataset object.
- **RO-Crate** requires a **flat `@graph` array** where every entity is a top-level object referenced by `@id`.

Example -- a creator in ADA metadata:
```json
{
  "schema:creator": {
    "@list": [{
      "@type": "schema:Person",
      "schema:name": "Analytica, Maria",
      "schema:identifier": "https://orcid.org/0000-0001-2345-6789"
    }]
  }
}
```

The same creator in RO-Crate:
```json
{
  "@id": "./",
  "@type": "Dataset",
  "author": [{"@id": "https://orcid.org/0000-0001-2345-6789"}]
}
```
```json
{
  "@id": "https://orcid.org/0000-0001-2345-6789",
  "@type": "Person",
  "name": "Analytica, Maria"
}
```

### 2. Distribution vs. hasPart

ADA/CDIF metadata wraps files inside a `schema:distribution` array, which contains an archive `DataDownload` object with nested `schema:hasPart` file items. RO-Crate puts files directly as top-level `File` entities in the `@graph`, referenced from the root `Dataset` via `hasPart`:

```json
{
  "@id": "./",
  "@type": "Dataset",
  "hasPart": [
    {"@id": "ALH84001_ADA_001.tif"},
    {"@id": "ALH84001_ADA_methods.pdf"}
  ]
}
```

### 3. Prefixed vs. Unprefixed Properties

ADA/CDIF metadata uses namespace-prefixed property names (e.g., `schema:name`, `schema:description`). RO-Crate uses unprefixed schema.org terms (e.g., `name`, `description`) resolved through its own `@context`.

### 4. Metadata File Descriptor

RO-Crate requires a special `CreativeWork` entity describing the metadata file itself. ADA/CDIF metadata has an analogous `schema:subjectOf` object that describes the metadata record. The converter maps this to the RO-Crate Metadata File Descriptor.

## ValidateROCrate.py -- Converter and Validator

`ValidateROCrate.py` (in this directory) is the tool that transforms CDIF/ADA JSON-LD metadata into RO-Crate form and validates the result. It is the complement of `FrameAndValidate.py`: where `FrameAndValidate.py` takes a flattened `@graph` and *nests* it (via JSON-LD framing) for JSON Schema validation, `ValidateROCrate.py` takes nested/compacted CDIF JSON-LD and *flattens* it (via JSON-LD expand + flatten) for RO-Crate structural validation.

### Prerequisites

```bash
pip install PyLD
```

The script requires network access on first run to fetch the RO-Crate 1.1 context from `https://w3id.org/ro/crate/1.1/context`.

### Usage

```bash
# Convert a CDIF/ADA document to RO-Crate form and validate
python ValidateROCrate.py MetadataExamples/xrd-2j0t-gq80.json

# Convert, validate, and save the RO-Crate output
python ValidateROCrate.py MetadataExamples/xrd-2j0t-gq80.json -o MetadataExamples/xrd-2j0t-gq80-rocrate.json

# Validate a document already in @graph form (skip conversion)
python ValidateROCrate.py MetadataExamples/xrd-2j0t-gq80-rocrate.json --no-convert

# Verbose output (show details for passing checks too)
python ValidateROCrate.py MetadataExamples/xrd-2j0t-gq80.json -v
```

**Options:**
- `-o, --output FILE` -- Write the converted RO-Crate JSON-LD to a file
- `--no-convert` -- Skip the conversion step; validate the input document as-is
- `-v, --verbose` -- Show detail messages for all checks, not just failures and warnings

**Exit codes:**
- `0` -- all FAIL-level checks passed (warnings are allowed)
- `1` -- one or more FAIL-level checks failed, or an error occurred

### How the Conversion Works

The conversion leverages the [pyld](https://github.com/digitalbazaar/pyld) JSON-LD processor to perform standard JSON-LD operations. The key insight is that CDIF/ADA JSON-LD and RO-Crate JSON-LD represent the **same RDF graph** -- the conversion is purely a change in serialization form (nested vs. flat), not a lossy transformation.

The pipeline has five stages:

```
Input (nested CDIF/ADA JSON-LD with schema:-prefixed terms)
  |
  v
1. Enrich @context     -- merge CDIF namespace prefixes, normalize
   (_enrich_context)      schema to http:// (RO-Crate uses http://,
                          not https://)
  |
  v
2. Expand              -- resolve all prefixed terms to full IRIs
   (jsonld.expand)        e.g. schema:name -> http://schema.org/name
  |
  v
3. Flatten             -- decompose nested objects into a flat @graph
   (jsonld.flatten)       array with @id cross-references
  |
  v
4. Compact             -- re-compact with the RO-Crate 1.1 context;
   (jsonld.compact)       schema.org terms become unprefixed (name,
                          description); CDIF terms keep prefixes
                          (prov:, spdx:, cdi:, csvw:)
  |
  v
5. Inject & Remap      -- add ro-crate-metadata.json descriptor
   (convert_to_rocrate)   entity; remap root Dataset @id to "./"
  |
  v
Output (RO-Crate 1.1 @graph JSON-LD)
```

#### Stage 1: Enrich Context (`_enrich_context`)

Merges all known CDIF namespace prefixes into the input document's `@context`. This ensures that:
- Prefixed terms used in the input (e.g., `prov:Activity`, `spdx:checksum`, `cdi:InstanceVariable`) resolve to full IRIs even if the input's `@context` omits those prefixes.
- The `schema` prefix resolves to `http://schema.org/` (not `https://`), matching the RO-Crate 1.1 context. This namespace normalization is critical -- without it, schema.org terms won't compact to unprefixed form.

Supported namespaces: `schema`, `dcterms`, `prov`, `dqv`, `geosparql`, `spdx`, `cdi`, `csvw`, `time`, `ada`, `xas`, `nxs`.

#### Stage 2: Expand (`jsonld.expand`)

Standard JSON-LD expansion. All prefixed terms become full IRIs, all context-dependent shortcuts are removed. The result is an array of expanded JSON-LD objects with absolute IRI property keys.

#### Stage 3: Flatten (`jsonld.flatten`)

Standard JSON-LD flattening. Every nested object that has (or is assigned) an `@id` becomes a top-level entity in the `@graph` array. Inline references are replaced with `{"@id": "..."}` pointers. This is the key step that transforms ADA/CDIF's nested structure into RO-Crate's flat graph.

#### Stage 4: Compact (`jsonld.compact`)

Re-compacts the flattened graph using the RO-Crate 1.1 context (plus CDIF-specific namespace prefixes). After compacting:
- Schema.org terms appear unprefixed: `name`, `description`, `author`, `datePublished`, `encodingFormat`
- CDIF-specific terms retain their prefixes: `prov:wasGeneratedBy`, `spdx:checksum`, `cdi:hasPhysicalMapping`, `csvw:delimiter`
- Entity types use RO-Crate aliases: `File` (for `MediaObject`), `Dataset`, `Person`, `Organization`

#### Stage 5: Inject & Remap

Two post-processing steps that standard JSON-LD operations cannot perform:

1. **Root Dataset detection and `@id` remapping**: Finds the root `Dataset` entity (heuristic: the `Dataset` with a `distribution` property, or the first `Dataset`) and remaps its `@id` to `"./"`. All `{"@id": "old-id"}` references throughout the graph are updated via `_remap_id()`.

2. **Metadata descriptor injection**: Inserts the required RO-Crate Metadata File Descriptor entity at the start of `@graph`:
   ```json
   {
     "@id": "ro-crate-metadata.json",
     "@type": "CreativeWork",
     "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
     "about": {"@id": "./"}
   }
   ```

### Validation Checks

After conversion (or directly on `--no-convert` input), the validator runs 13 checks against the RO-Crate 1.1 specification:

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

Checks 1--9 are structural requirements (FAIL = invalid RO-Crate). Checks 10--13 are recommended properties (WARN = valid but incomplete).

The nested-entity check (#8) uses `_find_nested_entities()` which walks every property value in the graph looking for objects with `@type` or `@id` plus additional properties (as opposed to pure `{"@id": "..."}` references or `{"@value": "..."}` literals).

### Example Output

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

### Generated RO-Crate Examples

The `MetadataExamples/` directory contains ADA/CDIF JSON-LD source files and their corresponding RO-Crate conversions produced by `ValidateROCrate.py`:

| Source File | RO-Crate Output | Technique |
|---|---|---|
| `xrd-2j0t-gq80.json` | `xrd-2j0t-gq80-rocrate.json` | X-ray Diffraction |
| `tof-htk9-f770.json` | `tof-htk9-f770-rocrate.json` | ToF-SIMS |
| `xanes-2arx-b516.json` | `xanes-2arx-b516-rocrate.json` | XANES |
| `yv1f-jb20.json` | `yv1f-jb20-rocrate.json` | General dataset |
| `test_se_na2so4-testschemaorg-cdiv3.json` | `test_se_na2so4-testschemaorg-cdiv3-rocrate.json` | Test record |

To regenerate all RO-Crate outputs:

```bash
for f in MetadataExamples/*.json; do
  case "$f" in *-rocrate.json|*placeholder*|*ro-crate-metadata*) continue;; esac
  python ValidateROCrate.py "$f" -o "${f%.json}-rocrate.json"
done
```

### What is Preserved, What is Lost

| Category | Preserved in RO-Crate | Notes |
|---|---|---|
| Dataset identity and description | name, description, datePublished, license, identifier, url, version, keywords | Core overlap between schemas |
| People and organizations | author, contributor, publisher with ORCID/ROR identifiers | Flattened from nested to entity references |
| Spatial and temporal coverage | spatialCoverage, temporalCoverage | Direct mapping |
| Funding | funding with funder references | MonetaryGrant as contextual entity |
| File inventory | hasPart with File entities, MIME types, sizes | Restructured from distribution/hasPart to flat graph |
| Profile conformance | conformsTo | Moved from subjectOf to Root Data Entity |
| ADA analysis provenance | prov:wasGeneratedBy, prov:used | Preserved as additional PROV-O properties |
| ADA instrument/lab details | Contextual entities with prov:/nxs: properties | Preserved as additional linked data entities |
| CDIF variable descriptions | variableMeasured entities with cdi: properties | Preserved with DDI-CDI typing |
| CDIF physical mappings | cdi:hasPhysicalMapping on File entities | Preserved; not core RO-Crate but valid extension |
| CSV-W tabular properties | csvw:delimiter, csvw:header, etc. on File entities | Preserved; CSV-W is recognized in RO-Crate context |
| ADA componentType | -- | Domain-specific; not representable in core RO-Crate |

Because the conversion uses standard JSON-LD expand/flatten/compact operations, the underlying RDF graph is preserved losslessly. The only additions are the RO-Crate metadata descriptor entity and the `"./"` root `@id` convention. Properties from non-schema.org vocabularies (PROV-O, DDI-CDI, SPDX, CSV-W) are carried through with their namespace prefixes intact.

## References

- [RO-Crate 1.2 Specification](https://www.researchobject.org/ro-crate/specification/1.2/introduction.html)
- [RO-Crate Quick Reference](https://www.researchobject.org/ro-crate/quick-reference)
- [RO-Crate Root Data Entity](https://www.researchobject.org/ro-crate/specification/1.2/root-data-entity.html)
- [RO-Crate Data Entities](https://www.researchobject.org/ro-crate/specification/1.2/data-entities)
- [RO-Crate Metadata](https://www.researchobject.org/ro-crate/specification/1.1/metadata.html)
- [RO-Crate JSON-LD](https://www.researchobject.org/ro-crate/specification/1.1/appendix/jsonld.html)
- [CDIF Book: Schema.org Implementation](https://cross-domain-interoperability-framework.github.io/cdifbook/metadata/schemaorgimplementation.html)
- [pyld JSON-LD Processor](https://github.com/digitalbazaar/pyld)
