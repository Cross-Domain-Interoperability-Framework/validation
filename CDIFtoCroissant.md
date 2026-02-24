# CDIF to Croissant Metadata Mapping

## Overview

[Croissant](https://docs.mlcommons.org/croissant/docs/croissant-spec.html) is an ML-oriented dataset metadata format built on schema.org and JSON-LD, developed by [MLCommons](https://mlcommons.org/working-groups/data/croissant/). CDIF (Cross-Domain Interoperability Framework) is a science dataset metadata format also built on schema.org/JSON-LD, extended with DDI-CDI, CSVW, PROV, and DQV vocabularies.

Both formats describe datasets as `schema:Dataset` documents with distributions, variable/field descriptions, and agent metadata. The shared schema.org foundation provides a large overlap at the discovery metadata level. They diverge in how they describe data structure: CDIF uses DDI-CDI `InstanceVariable` with physical mappings and CSVW table metadata; Croissant uses `RecordSet`/`Field` with extract/transform pipelines.

`ConvertToCroissant.py` converts CDIF JSON-LD to Croissant 1.0 JSON-LD. CDIF properties with no native Croissant equivalent are passed through verbatim with their namespace prefixes added to the `@context`, preserving full CDIF semantics in the output.

## Usage

```bash
# Convert a CDIF document to Croissant
python ConvertToCroissant.py input.jsonld -o output.json

# Verbose mode (shows conversion progress)
python ConvertToCroissant.py input.jsonld -o output.json -v

# Validate the output (requires: pip install mlcroissant)
mlcroissant validate --jsonld output.json
```

## Namespace Context

The output uses the standard Croissant `@context` with additional CDIF namespace prefixes added as needed for pass-through properties:

| Prefix | IRI | Origin |
|--------|-----|--------|
| `sc` | `https://schema.org/` | Croissant (default vocab) |
| `cr` | `http://mlcommons.org/croissant/` | Croissant |
| `dct` | `http://purl.org/dc/terms/` | Croissant |
| `wd` | `https://www.wikidata.org/wiki/` | Croissant |
| `prov` | `http://www.w3.org/ns/prov#` | CDIF pass-through |
| `dqv` | `http://www.w3.org/ns/dqv#` | CDIF pass-through |
| `cdi` | `http://ddialliance.org/Specification/DDI-CDI/1.0/RDF/` | CDIF pass-through |
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
| `schema:dateModified` | `dateModified` | Required in CDIF (on root or subjectOf), recommended in Croissant |
| `schema:creator` | `creator` | CDIF wraps in `@list` for ordering; converter unwraps |
| `schema:keywords` | `keywords` | Direct; converter falls back to `schema:additionalType` values |
| `schema:publisher` | `publisher` | Direct match |
| `schema:version` | `version` | Direct match; defaults to `"not assigned"` when absent (Croissant recommends this property) |
| `schema:inLanguage` | `inLanguage` | Direct match |
| `schema:sameAs` | `sameAs` | Direct match |
| `schema:funding` | `funding` | Both support `MonetaryGrant`; converter maps description and funder |

### CDIF identifier to Croissant citeAs

CDIF uses a structured `schema:identifier` (a `PropertyValue` with `propertyID`, `value`, `url`) typically carrying a DOI. The converter extracts the DOI URL and maps it to:
- `citeAs` (Croissant citation property)
- `url` (fallback when `schema:url` is empty)

### Conformance declaration

The mechanisms differ structurally:

- **CDIF**: `schema:subjectOf` → `dcat:CatalogRecord` → `dcterms:conformsTo` → profile URI(s)
- **Croissant**: `dct:conformsTo: "http://mlcommons.org/croissant/1.0"` (direct top-level property)

The converter sets the Croissant `conformsTo` and passes through the CDIF `schema:subjectOf` block.

## Property Mapping: Distribution / Files

### Concept correspondence

| CDIF type | Croissant type | Relationship |
|-----------|---------------|-------------|
| `schema:DataDownload` (single file) | `cr:FileObject` | Direct: both describe a downloadable file with contentUrl, encodingFormat, name |
| `schema:DataDownload` (archive with `schema:hasPart`) | `cr:FileObject` (archive) + `cr:FileObject` per component with `containedIn` | Archive FileObject has the download URL; component FileObjects reference it via `containedIn` and use `nil:inapplicable` for `contentUrl` |
| `schema:MediaObject` / `schema:Dataset` (hasPart items) | `cr:FileObject` with `containedIn` | Individual files within an archive (not independently downloadable) |
| `schema:WebAPI` + `schema:potentialAction` | _(no equivalent)_ | Croissant has no API access pattern |

### Archive handling

CDIF expresses containment as `archive hasPart [file1, file2, ...]` (parent-to-child). The converter models this as flat `cr:FileObject` entries in the `distribution` array with `containedIn` back-references:

1. The archive itself becomes a `cr:FileObject` with the `contentUrl` (only the archive has a download URL)
2. Each `hasPart` item becomes a separate `cr:FileObject` in `distribution` with `containedIn: {"@id": "<archive-id>"}` referencing the archive
3. Component files use `contentUrl: "http://www.opengis.net/def/nil/ogc/0/inapplicable"` since they are not independently downloadable
4. If the archive has no checksum in the source, a nil placeholder (`sha256` of 64 zeros) is added to satisfy Croissant's requirement that FileObjects have `sha256` or `md5`

### File metadata mapping

| CDIF | Croissant | Notes |
|------|-----------|-------|
| `schema:contentUrl` | `contentUrl` | Direct; archive FileObject has the download URL; component FileObjects use OGC `nil:inapplicable` |
| `schema:encodingFormat` (array) | `encodingFormat` (string) | Converter takes first element |
| `schema:size` (`QuantitativeValue`) | `contentSize` (string) | Converter formats as "NNN B" |
| `spdx:checksum` (string or object) | `sha256` | Converter handles bare hex strings, `{spdx:checksumValue}` objects, and sha256 hashes embedded in `schema:description` text. Archive FileObjects without a source checksum get a nil placeholder (64 zeros) |
| `schema:name` | `name` | Direct |

## Property Mapping: Data Structure

### Concept correspondence

| CDIF concept | Croissant concept | Relationship |
|-------------|-------------------|-------------|
| `cdi:TabularTextDataSet` + CSVW properties | `cr:RecordSet` | Both describe structured tabular data. CDIF carries explicit CSVW metadata (delimiter, header, quoteChar); Croissant pushes structure into the extract/transform pipeline |
| `cdi:StructuredDataSet` (data cube) | `cr:RecordSet` with dimensional fields | Croissant lacks explicit data cube semantics |
| `cdi:InstanceVariable` / `schema:PropertyValue` | `cr:Field` | Both describe a named data element with type and description |
| `cdi:hasPhysicalMapping` + `cdi:locator`/`cdi:index` | `cr:Field.source.extract.column` | Both connect a variable definition to its physical location in a file |

### RecordSet generation

The converter generates `cr:RecordSet` entries from CDIF tabular data as follows:

1. Scan `schema:distribution` → `schema:hasPart` for items with `cdi:hasPhysicalMapping`
2. For each such file, create a RecordSet named after the file (minus extension)
3. For each mapping entry in `cdi:hasPhysicalMapping`, create a `cr:Field`:
   - `name` / `@id`: RecordSet name + column name (e.g., `data_file/46Ti_Static_1_Mean`)
   - `source.fileObject`: references the FileObject for this file
   - `source.extract.column`: the column header name from the mapping's `schema:name`
   - `dataType`: mapped from `cdi:physicalDataType` or `cdi:intendedDataType`
   - `description`: from the linked `schema:variableMeasured` InstanceVariable
   - `equivalentProperty`: from `schema:propertyID` or `cdi:uses` Concept reference

### Data type mapping

| CDIF / XSD type | Croissant type |
|----------------|---------------|
| `xsd:decimal`, `xsd:float`, `xsd:double` | `sc:Float` |
| `xsd:integer`, `xsd:int`, `xsd:long` | `sc:Integer` |
| `xsd:dateTime`, `xsd:date` | `sc:Date` |
| `xsd:boolean` | `sc:Boolean` |
| `xsd:string`, `String`, `Text` | `sc:Text` |

### Variable concept identification

Both formats support linking a variable/field to the abstract concept it measures:

| CDIF mechanism | Croissant mechanism | Notes |
|---------------|-------------------|-------|
| `schema:propertyID` (DefinedTerm or URI on PropertyValue) | `equivalentProperty` (URL) | Both identify what the variable measures; converter extracts URL |
| `cdi:InstanceVariable.uses_Concept` (inherited from DDI-CDI Concept) | `equivalentProperty` (URL) | DDI-CDI concept reference; converter extracts `@id` if it's a full URI |

### Variable relationships

| CDIF (DDI-CDI) | Croissant | Notes |
|---------------|-----------|-------|
| `AttributeComponent.qualifies` → DataStructureComponent | `cr:Field.references` → Field in another RecordSet | Both express inter-variable dependency. DDI-CDI `qualifies` is richer (metadata-about-data: quality flags, uncertainty); Croissant `references` is specifically a foreign-key join |
| `cdi:role` (`DimensionComponent`, `MeasureComponent`, `AttributeComponent`) | _(no equivalent)_ | Croissant has no variable role concept; passed through in CDIF properties |

## Properties with No Croissant Equivalent (Passed Through)

These CDIF properties are preserved verbatim in the output with their namespace prefixes:

| CDIF property | Vocabulary | What it carries |
|--------------|-----------|----------------|
| `prov:wasGeneratedBy` | W3C PROV | Activity that produced the dataset (instrument, lab, sample, date) |
| `prov:wasDerivedFrom` | W3C PROV | Source datasets this one was derived from |
| `dqv:hasQualityMeasurement` | W3C DQV | Quality metrics and measures |
| `schema:spatialCoverage` | schema.org | Geographic bounding box or named place |
| `schema:temporalCoverage` | schema.org | Time period covered by the dataset |
| `schema:measurementTechnique` | schema.org | Analytical technique (as DefinedTerm with termCode) |
| `schema:contributor` | schema.org | Contributors with roles (CDIF uses `schema:Role` wrapper) |
| `schema:subjectOf` | schema.org | CDIF metaMetadata: catalog record with `dcterms:conformsTo` profile URIs |

These properties are not part of the Croissant vocabulary but do not break `mlcroissant` validation. They are valid JSON-LD with resolvable namespace IRIs, so Croissant consumers simply ignore them while CDIF-aware tools can still read them.

## Croissant Features Not in CDIF

| Croissant concept | Purpose | CDIF gap |
|-------------------|---------|----------|
| `cr:RecordSet.key` | Primary key fields for unique record identification | No equivalent; CDIF variables don't declare key roles |
| `cr:Field.references` | Foreign key joins between RecordSets | DDI-CDI `qualifies` is the closest analog but semantically different |
| `cr:Field.subField` | Nested/hierarchical fields | CDIF variables are flat |
| `cr:Transform` (regex, delimiter, jsonQuery) | Post-extraction data transformations | No equivalent; CDIF describes data as-is |
| `cr:FileSet` (glob patterns) | Collections of homogeneous files by pattern | CDIF does not use glob-based file sets; archives are modeled as `cr:FileObject` with `containedIn` references |
| `cr:Split` | Train/validation/test data partitions | No equivalent (science data, not ML training) |
| `cr:Label`, `cr:BoundingBox`, `cr:SegmentationMask` | ML annotation types | No equivalent |
| `cr:isLiveDataset` | Continuously-updated dataset flag | No equivalent |
| `cr:data` / `cr:examples` | Inline embedded records / examples | No equivalent |

## CSVW Table Metadata (Not Converted)

CDIF `cdi:TabularTextDataSet` carries detailed CSVW properties that Croissant does not model at the RecordSet level. These are present in the CDIF source but not mapped to Croissant output:

| CSVW property | What it describes |
|--------------|-------------------|
| `csvw:delimiter` | Field separator character |
| `csvw:header` / `csvw:headerRowCount` | Whether headers are present and how many rows |
| `csvw:commentPrefix` | Character marking comment lines |
| `csvw:quoteChar` | Quote character for field values |
| `csvw:lineTerminators` | Line ending style (CRLF, LF) |
| `csvw:skipRows` / `csvw:skipColumns` | Rows/columns to skip before data |
| `csvw:skipBlankRows` / `csvw:skipInitialSpace` | Whitespace handling |
| `cdi:isDelimited` / `cdi:isFixedWidth` | Tabular format type |

Croissant handles CSV parsing details implicitly through its extract/transform pipeline rather than declaring them as dataset properties.

## Example Conversions

Five CDIF examples have been converted and validated:

| CDIF source | Croissant output | Features exercised |
|---|---|---|
| `cdif_10.60707-0y88-ps96.json` | `cdif_0y88-ps96-croissant.json` | 10 InstanceVariables, physicalMapping, RecordSet with 10 Fields, archive distribution |
| `xanes-2arx-b516.json` | `xanes-2arx-b516-croissant.json` | Archive with 2 component files, no variables, provenance pass-through |
| `tof-htk9-f770.json` | `tof-htk9-f770-croissant.json` | 10 mixed-type files (TIFF, BMP, CSV, PDF, YAML, ZIP), contributor roles |
| `xrd-2j0t-gq80.json` | `xrd-2j0t-gq80-croissant.json` | Archive with 2 files, hand-added variableMeasured (no physicalMapping) |
| `yv1f-jb20.json` | `yv1f-jb20-croissant.json` | Archive with 3 files, hand-added variableMeasured (no physicalMapping) |

All five pass `mlcroissant validate` with zero errors. All 77 ADA test metadata files also pass validation when converted.
