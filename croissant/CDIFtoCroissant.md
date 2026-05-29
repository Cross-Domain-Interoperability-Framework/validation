# CDIF to Croissant Metadata Mapping

## Overview

[Croissant](https://docs.mlcommons.org/croissant/docs/croissant-spec-1.1.html) is an ML-oriented dataset metadata format built on schema.org and JSON-LD, developed by [MLCommons](https://mlcommons.org/working-groups/data/croissant/). CDIF (Cross-Domain Interoperability Framework) is a science dataset metadata format also built on schema.org/JSON-LD, extended with DDI-CDI, CSVW, PROV, and DQV vocabularies.

Both formats describe datasets as `schema:Dataset` documents with distributions, variable/field descriptions, and agent metadata. The shared schema.org foundation provides a large overlap at the discovery metadata level. They diverge in how they describe data structure: CDIF uses DDI-CDI `InstanceVariable` with physical mappings, keys, and (in the Data Structure profile) typed components; Croissant uses `RecordSet`/`Field` with extract/transform pipelines.

`ConvertToCroissant.py` converts CDIF JSON-LD to **Croissant 1.1** JSON-LD (`dct:conformsTo = http://mlcommons.org/croissant/1.1`). It reads the current `cdif:`-namespaced CDIF Discovery / Data Description / Data Structure schema. CDIF properties with no native Croissant equivalent are passed through verbatim with their namespace prefixes added to the `@context`, preserving full CDIF semantics in the output.

> **Schema version.** This converter targets the **current `cdif:` schema** (the `cdif:` namespace `https://w3id.org/cdif/`), in which `cdif:physicalDataType` is single-valued, physical mappings use `cdif:index` / `cdif:formats_InstanceVariable`, and datasets may declare `cdif:hasPrimaryKey`. Earlier `cdi:`-prefixed forms (`cdi:hasPhysicalMapping`, `cdi:hasValueDomain`, `cdi:locator`, `cdi:hasIndex`) are no longer read.

## Usage

```bash
# Convert a CDIF document to Croissant 1.1
python ConvertToCroissant.py input.jsonld -o output.json

# Verbose mode (shows conversion progress)
python ConvertToCroissant.py input.jsonld -o output.json -v

# Validate the output (requires: pip install mlcroissant)
python -c "import mlcroissant as mlc; mlc.Dataset(jsonld='output.json')"
```

## Namespace Context

The output uses the standard Croissant 1.1 `@context` (schema.org IRIs are `https://schema.org/`, matching the `mlcroissant` library) with additional CDIF namespace prefixes added as needed for pass-through properties:

| Prefix | IRI | Origin |
|--------|-----|--------|
| `sc` / `@vocab` | `https://schema.org/` | Croissant (default vocab) |
| `cr` | `http://mlcommons.org/croissant/` | Croissant |
| `dct` | `http://purl.org/dc/terms/` | Croissant (`conformsTo`) |
| `prov` | `http://www.w3.org/ns/prov#` | CDIF pass-through |
| `dqv` | `http://www.w3.org/ns/dqv#` | CDIF pass-through |
| `cdi` | `http://ddialliance.org/Specification/DDI-CDI/1.0/RDF/` | CDIF pass-through |
| `cdif` | `https://w3id.org/cdif/` | CDIF pass-through |
| `csvw` | `http://www.w3.org/ns/csvw#` | CDIF pass-through |
| `dcterms` | `http://purl.org/dc/terms/` | CDIF pass-through |
| `spdx` | `http://spdx.org/rdf/terms#` | CDIF pass-through |

## Property Mapping: Dataset Level

### Direct mappings (schema.org shared surface)

| CDIF property | Croissant property | Notes |
|---------------|-------------------|-------|
| `schema:name` | `name` | Both required |
| `schema:description` | `description` | Optional in CDIF, required in Croissant; converter uses name as fallback |
| `schema:url` | `url` | Both required; converter falls back to DOI URL from `schema:identifier` |
| `schema:license` | `license` | CDIF allows `schema:conditionsOfAccess` alternative; converter uses OGC `nil:missing` URI as placeholder when absent |
| `schema:datePublished` | `datePublished` | Optional in CDIF, required in Croissant |
| `schema:dateModified` | `dateModified` | Required in CDIF (root or subjectOf), recommended in Croissant |
| `schema:creator` | `creator` | CDIF wraps in `@list` for ordering; converter unwraps |
| `schema:keywords` | `keywords` | Direct; converter falls back to `schema:additionalType` values |
| `schema:publisher` | `publisher` | Direct match |
| `schema:version` | `version` | Direct; defaults to `"not assigned"` when absent |
| `schema:inLanguage` | `inLanguage` | Direct match |
| `schema:sameAs` | `sameAs` | Croissant expects a URL; when CDIF carries a `PropertyValue`/object the converter extracts its `schema:url`/`@id`/`schema:value` |
| `schema:funding` | `funding` | Both support `MonetaryGrant`; converter maps description and funder |

### CDIF identifier to Croissant citeAs

CDIF uses a structured `schema:identifier` (a `PropertyValue` with `propertyID`, `value`, `url`) typically carrying a DOI. The converter extracts the DOI URL and maps it to:
- `citeAs` (Croissant citation property)
- `url` (fallback when `schema:url` is empty)

### Conformance declaration

The mechanisms differ structurally:

- **CDIF**: `schema:subjectOf` → catalog record (`schema:Dataset` + `schema:additionalType: ["dcat:CatalogRecord"]` + `schema:about`) → `dcterms:conformsTo` → profile URIs (`https://w3id.org/cdif/{core,discovery,data_description,data_structure}/1.0`)
- **Croissant**: `conformsTo: "http://mlcommons.org/croissant/1.1"` (direct top-level property mapped to `dct:conformsTo`)

The converter sets the Croissant `conformsTo` to 1.1 and passes through the CDIF `schema:subjectOf` block.

## Property Mapping: Distribution / Files

### Concept correspondence

| CDIF type | Croissant type | Relationship |
|-----------|---------------|-------------|
| `schema:DataDownload` (single file) | `cr:FileObject` | Direct: both describe a downloadable file with contentUrl, encodingFormat, name |
| `schema:DataDownload` + `cdi:TabularTextDataSet` (carries `cdif:hasPhysicalMapping`) | `cr:FileObject` + a `cr:RecordSet` | The physical mappings drive RecordSet/Field generation |
| `schema:DataDownload` (archive with `schema:hasPart`) | `cr:FileObject` (archive) + `cr:FileObject` per component with `containedIn` | Archive FileObject has the download URL; component FileObjects reference it via `containedIn` and use `nil:inapplicable` for `contentUrl` |
| `schema:MediaObject` / `schema:Dataset` (hasPart items) | `cr:FileObject` with `containedIn` | Individual files within an archive |
| `schema:WebAPI` + `schema:potentialAction` | `cr:FileObject` (placeholder `encodingFormat`) | Croissant has no API access pattern; emitted as a FileObject so the resource is listed |

### Required-field placeholders

Croissant requires `contentUrl`, `encodingFormat`, and `sha256`/`md5` on every `cr:FileObject`. When CDIF does not supply them the converter emits valid placeholders so the output passes `mlcroissant` validation:

- **`contentUrl`** — the OGC `nil:inapplicable` URI when the resource has no usable download URL (e.g. landing-page-only or archive components).
- **`encodingFormat`** — `application/octet-stream` when absent (e.g. a WebAPI distribution).
- **`sha256`** — a nil placeholder (64 zeros) when no checksum is present (the inverse converter strips it).

### File metadata mapping

| CDIF | Croissant | Notes |
|------|-----------|-------|
| `schema:contentUrl` | `contentUrl` | Direct; placeholder when missing |
| `schema:encodingFormat` (array) | `encodingFormat` (string) | Converter takes first element; placeholder when missing |
| `schema:size` (`QuantitativeValue`) | `contentSize` (string) | Converter formats as "NNN B" |
| `spdx:checksum` (string or object) | `sha256` | Handles bare hex, `{spdx:checksumValue}` objects, and sha256 in `schema:description`; nil placeholder otherwise |
| `schema:name` | `name` | Direct |

## Property Mapping: Data Description (variables → RecordSet/Field)

### Concept correspondence

| CDIF concept | Croissant concept | Relationship |
|-------------|-------------------|-------------|
| `cdi:TabularTextDataSet` distribution + `cdif:hasPhysicalMapping` | `cr:RecordSet` | Both describe structured tabular data |
| `cdi:InstanceVariable` (item of `schema:variableMeasured`) | `cr:Field` | Both describe a named data element with type and description |
| `cdif:hasPhysicalMapping[]` entry (`cdif:index`, `cdif:formats_InstanceVariable`) | `cr:Field.source.extract.column` | Connects a variable to its physical column (ordinal `cdif:index`, link `cdif:formats_InstanceVariable`) |
| `cdif:hasPrimaryKey` → `cdif:Key` / `cdif:isComposedOf` | `cr:RecordSet.key` | The key variables map to the RecordSet's key field `@id`s |

### RecordSet generation

1. Scan `schema:distribution` (top-level tabular `cdi:TabularTextDataSet`) and `schema:hasPart` (archive components) for nodes carrying `cdif:hasPhysicalMapping`.
2. For each such file, create a `cr:RecordSet` named after the file (minus extension). **Its `@id` is made distinct from the source `cr:FileObject` `@id`** (a `_records` suffix when they would collide) — otherwise JSON-LD merges the two same-`@id` nodes and breaks Croissant processing.
3. For each `cdif:hasPhysicalMapping` entry (sorted by `cdif:index`), create a `cr:Field`:
   - `@id` / `name`: `<recordset>/<column>` (column = the linked InstanceVariable's `cdif:name`/`schema:name`)
   - `source.fileObject`: the FileObject `@id` for this file
   - `source.extract.column`: the column label
   - `dataType`: mapped from the variable's `cdi:hasIntendedDataType`, then its `cdif:physicalDataType`, then the mapping's `cdif:physicalDataType`
   - `description`: from the linked InstanceVariable (`schema:description`/`cdif:definition`)
   - `equivalentProperty`: from `schema:propertyID` or `cdif:uses`
4. If the dataset declares `cdif:hasPrimaryKey`, its composing variable `@id`s are resolved to the matching field `@id`s and emitted as `cr:RecordSet.key`.

### Data type mapping

The variable's *logical* type is preferred over the mapping's physical storage token.

| CDIF / XSD type | Croissant type |
|----------------|---------------|
| `xsd:decimal`, `xsd:float`, `xsd:double`, `Numeric`, `Decimal`, `Float`, `Double` | `sc:Float` |
| `xsd:integer`, `xsd:int`, `xsd:long`, `Integer`, `Int` | `sc:Integer` |
| `xsd:dateTime`, `xsd:date`, `Date`, `DateTime` | `sc:Date` |
| `xsd:boolean`, `Boolean` | `sc:Boolean` |
| `xsd:string`, `String`, `Text` | `sc:Text` |
| `xsd:anyURI` | `sc:URL` |

Datatype IRIs (e.g. `https://www.w3.org/TR/xmlschema-2/#decimal`) and `{"@id": …}` / `DefinedTerm` values are normalized to an `xsd:` token before lookup.

### Variable concept identification

| CDIF mechanism | Croissant mechanism | Notes |
|---------------|-------------------|-------|
| `schema:propertyID` (URI on the PropertyValue) | `equivalentProperty` (URL) | Both identify what the variable measures |
| `cdif:uses` (concept reference: URI, `{@id}`, or DefinedTerm) | `equivalentProperty` (URL) | Converter extracts the first resolvable IRI |

## Property Mapping: Data Structure profile

The CDIF **Data Structure profile** (`https://w3id.org/cdif/data_structure/1.0`) adds the full DDI-CDI structural model on each distribution via `cdi:isStructuredBy`. Croissant has no equivalent structural layer, so most of it is documented here as a conceptual crosswalk; the converter realizes the parts that map cleanly onto RecordSet/Field.

| CDIF (Data Structure profile) | Croissant | Handling |
|---|---|---|
| `cdi:isStructuredBy` → `cdi:DataStructure` / `cdi:WideDataStructure` / `cdi:LongDataStructure` / `cdi:DimensionalDataStructure` | `cr:RecordSet` (one per structured file) | The structure flavour is not represented in Croissant; the RecordSet is generated from the physical mappings, not the component list |
| `cdi:has_DataStructureComponent` → `IdentifierComponent` / `MeasureComponent` / `AttributeComponent` / `DimensionComponent` (the `cdif:role`) | _(no equivalent)_ | Croissant `cr:Field` has no role concept; component role is carried only in passed-through CDIF properties |
| `cdi:has_PrimaryKey` (DataStructure level) and dataset-level `cdif:hasPrimaryKey` | `cr:RecordSet.key` | Realized: key variables → key field `@id`s |
| `cdi:has_ForeignKey` → `cdif:ForeignKey` (references another structure/variable) | `cr:Field.references` (`{"@id": <target field>}`) | The closest analog; emitted only when the target resolves to a field in the generated RecordSets |
| `cdif:isDefinedBy_RepresentedVariable` → `cdi:RepresentedVariable` | folded into `cr:Field` | RepresentedVariable-level name/definition/type are surfaced on the field; the RepresentedVariable node itself is not reproduced |

> **`cdi:qualifies` is not a foreign key.** A variable's `cdi:qualifies` (attribute-qualifies-measure, i.e. metadata-about-data such as a quality flag) is **not** mapped to `cr:Field.references`. `references` is reserved for true foreign keys (`cdif:ForeignKey`). `cdi:qualifies` has no clean Croissant equivalent and is passed through in the CDIF properties.

## Properties with No Croissant Equivalent (Passed Through)

These CDIF properties are preserved verbatim in the output with their namespace prefixes added to the `@context`:

| CDIF property | Vocabulary | What it carries |
|--------------|-----------|----------------|
| `prov:wasGeneratedBy` | W3C PROV | Activity that produced the dataset (instrument, lab, sample, date) |
| `prov:wasDerivedFrom` | W3C PROV | Source datasets this one was derived from |
| `dqv:hasQualityMeasurement` | W3C DQV | Quality metrics and measures |
| `schema:spatialCoverage` | schema.org | Geographic bounding box or named place |
| `schema:temporalCoverage` | schema.org | Time period covered |
| `schema:measurementTechnique` | schema.org | Analytical technique (DefinedTerm) |
| `schema:contributor` | schema.org | Contributors with roles (`schema:Role` wrapper) |
| `schema:subjectOf` | schema.org | CDIF catalog record with `dcterms:conformsTo` profile URIs |
| `cdif:statistics` | CDIF/DDI-CDI | Summary statistics bundles |

These are not part of the Croissant vocabulary but do not break `mlcroissant` validation: they are valid JSON-LD with resolvable namespace IRIs, so Croissant consumers ignore them while CDIF-aware tools can still read them.

## Croissant Features Not in CDIF

| Croissant concept | Purpose | CDIF gap |
|-------------------|---------|----------|
| `cr:Field.subField` / `cr:parentField` | Nested/hierarchical fields | CDIF variables are flat |
| `cr:Field.isArray` / `cr:arrayShape` | Array-valued fields (1.1) | No direct equivalent |
| `cr:Transform` (regex, delimiter, jsonPath) | Post-extraction transformations | No equivalent; CDIF describes data as-is |
| `cr:FileSet` (glob patterns) | Collections of files by pattern | CDIF enumerates files via `hasPart` |
| `cr:Split` / `cr:Label` / `cr:BoundingBox` / `cr:SegmentationMask` | ML partitions and annotation types | No equivalent (science data, not ML training) |
| `cr:isLiveDataset` | Continuously-updated dataset flag | No equivalent |
| `cr:data` / `cr:examples` | Inline embedded records / examples | No equivalent |

## CSVW Table Metadata (Not Converted)

CDIF tabular distributions may carry CSVW parsing properties (`csvw:delimiter`, `csvw:header`, `csvw:quoteChar`, `csvw:lineTerminators`, `csvw:skipRows`, …) and `cdi:numberPattern` / `cdi:nullSequence` on physical mappings. Croissant handles CSV parsing implicitly through its extract/transform pipeline rather than declaring these as properties, so they are present in the CDIF source but not mapped to Croissant output.

## Validation

Output is validated by loading it with `mlcroissant` (which expands and validates against the declared Croissant version):

```python
import mlcroissant as mlc
mlc.Dataset(jsonld="output.json")   # raises on invalid 1.1 documents
```

Current-schema CDIF examples (Data Description and Data Structure, including a composite primary key) and the legacy archive examples all load as valid Croissant 1.1 (with only benign warnings for missing `datePublished` / non-semver `version`).
