# Croissant to CDIF DataDescription Mapping

## Overview

This is the **inverse** of [`CDIFtoCroissant.md`](CDIFtoCroissant.md): it maps from
[Croissant](https://docs.mlcommons.org/croissant/docs/croissant-spec.html) 1.0
JSON-LD to **CDIF DataDescription** JSON-LD (a profile of schema.org extended with
DDI-CDI, CSVW, PROV, and DQV).

The conversion is **lossy in the Croissant→CDIF direction** because Croissant
does not carry information that CDIF requires or commonly expects:

- CDIF normally wraps a DOI as a structured `schema:identifier` `PropertyValue` —
  Croissant carries it only as `citeAs` (string) + `url`. The inverse recovers
  the DOI by regex from those.
- CDIF DataDescription distinguishes `cdi:TabularTextDataSet` /
  `cdi:StructuredDataSet` / `schema:DataDownload` types and may carry CSVW
  parsing properties (delimiter, header, quoteChar, …). Croissant carries CSV
  semantics *implicitly* inside `cr:Transform`, so the inverse cannot reconstruct
  the CSVW block — only typed-column membership in a RecordSet is recoverable.
- CDIF discovery profile fields (`schema:spatialCoverage`, `temporalCoverage`,
  `measurementTechnique`, `subjectOf` catalog record, PROV `wasGeneratedBy`)
  have no Croissant equivalents. The inverse leaves these absent; downstream
  curation is required to populate them.

The inverse script `ConvertFromCroissant.py` handles the **lossless subset**:
discovery-level dataset metadata, distribution / file inventory (flat and
archive), and tabular RecordSet → `cdi:InstanceVariable` + `cdi:hasPhysicalMapping`.

## Property Mapping: Dataset Level

### Direct mappings (schema.org shared surface)

| Croissant property | CDIF property | Notes |
|--------------------|---------------|-------|
| `name` | `schema:name` | Both required |
| `description` | `schema:description` | Required in Croissant, optional in CDIF — passed through |
| `url` | `schema:url` | Direct |
| `license` | `schema:license` | If absent or set to OGC `nil:missing`, output is empty |
| `datePublished` | `schema:datePublished` | Direct |
| `dateModified` | `schema:dateModified` | Direct |
| `creator` | `schema:creator` (wrapped in `@list` to preserve order) | CDIF convention is to use `@list` so authorship order is RDF-stable |
| `keywords` | `schema:keywords` | Direct (kept as array) |
| `publisher` | `schema:publisher` | Direct |
| `version` | `schema:version` | Omitted if Croissant's placeholder `"not assigned"` |
| `inLanguage` | `schema:inLanguage` | Direct |
| `sameAs` | `schema:sameAs` | Direct |
| `funding` | `schema:funding` | `MonetaryGrant` description / funder mapped through |

### Croissant `citeAs` and `url` → CDIF `schema:identifier`

Croissant has no structured `PropertyValue` identifier. The inverse reconstructs
one when a DOI can be detected:

1. Inspect `citeAs` and `url` for `https://doi.org/10.NNNN/...` or bare `10.NNNN/...` strings.
2. If found, emit:
   ```json
   "schema:identifier": {
     "@type": "schema:PropertyValue",
     "schema:propertyID": "https://registry.identifiers.org/registry/doi",
     "schema:value": "10.NNNN/...",
     "schema:url": "https://doi.org/10.NNNN/..."
   }
   ```
3. Otherwise leave `schema:identifier` absent and preserve `citeAs` verbatim as
   `schema:citeAs` (pass-through).

### Conformance declaration

Croissant declares conformance as a single top-level `dct:conformsTo` URI
(`http://mlcommons.org/croissant/1.0`). CDIF DataDescription requires a
`schema:subjectOf` → `dcat:CatalogRecord` with `dcterms:conformsTo` listing the
DataDescription profile URI(s).

The inverse emits a stub `subjectOf` block:

```json
"schema:subjectOf": {
  "@type": "dcat:CatalogRecord",
  "dcterms:conformsTo": [
    {"@id": "https://w3id.org/cdif/profiles/discovery"},
    {"@id": "https://w3id.org/cdif/profiles/datadescription"}
  ]
}
```

The Croissant `conformsTo: http://mlcommons.org/croissant/1.0` is dropped (it is
not part of CDIF's conformance space) but the source URL is preserved in a
`prov:wasDerivedFrom` block for round-trip traceability.

### Croissant `includedInDataCatalog` → CDIF

Mapped to `schema:includedInDataCatalog` directly (a shared schema.org property,
no transformation needed).

## Property Mapping: Distribution / Files

### Concept correspondence

| Croissant type | CDIF type | Notes |
|----------------|-----------|-------|
| `cr:FileObject` (top-level, with `contentUrl`) | `schema:DataDownload` | Direct |
| `cr:FileObject` with `containedIn: {"@id": ...}` | `schema:hasPart` item of the containing DataDownload | Group by `containedIn`; emit one `DataDownload` whose `schema:hasPart` collects all components |
| `cr:FileObject` referenced by a `cr:RecordSet.field.source.fileObject` | `schema:DataDownload` of `@type [schema:DataDownload, cdi:TabularTextDataSet]` | The presence of an attached RecordSet promotes the file to tabular type |
| `cr:FileSet` (glob-based collection) | _(no equivalent in CDIF)_ | Dropped; emits a warning |

### Archive reconstruction

Croissant's archive idiom is "flat `FileObject` list with `containedIn`
back-references". CDIF's archive idiom is the opposite — "one parent
`DataDownload` of `encodingFormat: application/zip` whose `schema:hasPart`
contains the components". The inverse pivots the structure:

1. Scan all top-level `cr:FileObject` for a `containedIn` reference.
2. Group components by their `containedIn.@id` value.
3. For each group, find the parent `cr:FileObject` (the one with the real
   `contentUrl`) and emit one `schema:DataDownload` of
   `@type [schema:DataDownload]`, `schema:encodingFormat: application/zip`, with
   `schema:hasPart` populated from the components.
4. Each component becomes a `schema:MediaObject` inside `hasPart`, carrying
   `schema:name`, `schema:encodingFormat`, `schema:contentSize`, and (when
   present) `spdx:checksum`.

If a component's parent FileObject has the OGC `nil:inapplicable` URL the
inverse omits `contentUrl` on the component (consistent with CDIF: only the
archive carries a download URL).

### File metadata mapping

| Croissant | CDIF | Notes |
|-----------|------|-------|
| `contentUrl` | `schema:contentUrl` | Direct; omitted if OGC `nil:inapplicable` |
| `encodingFormat` (string) | `schema:encodingFormat` (array of one string) | CDIF prefers array |
| `contentSize` (string `"NNN B"`) | `schema:size` (`QuantitativeValue`) | Parsed: number + unit (B/kB/MB/GB) — emitted as `{@type: QuantitativeValue, schema:value: N, schema:unitText: "byte"}` |
| `sha256` | `spdx:checksum` (as `{spdx:checksumAlgorithm: "checksumAlgorithm_sha256", spdx:checksumValue: ...}`) | The nil-placeholder hash of `0`×64 from the archive case is recognized and dropped |
| `md5` | `spdx:checksum` (as `{spdx:checksumAlgorithm: "checksumAlgorithm_md5", spdx:checksumValue: ...}`) | |
| `name` | `schema:name` | Direct |
| `description` | `schema:description` | Direct |

## Property Mapping: Data Structure

### Concept correspondence

| Croissant concept | CDIF concept | Notes |
|-------------------|--------------|-------|
| `cr:RecordSet` | `cdi:TabularTextDataSet` (or `cdi:StructuredDataSet` if non-tabular) attached to the source `DataDownload` via the `hasPart` entry | One RecordSet maps to one tabular part; the inverse assumes all `cr:Field.source.fileObject` in a RecordSet refer to the same file |
| `cr:Field` | `cdi:InstanceVariable` (added to top-level `schema:variableMeasured`) + a `cdi:hasPhysicalMapping` entry on the file | Field name → variable name + column name |
| `cr:Field.source.extract.column` | `cdi:locator` (column header) on the physicalMapping entry | Direct |
| `cr:Field.dataType` | `cdi:intendedDataType` / `cdi:physicalDataType` on the InstanceVariable's value domain | Reverse-mapped: `sc:Float`→`xsd:decimal`, `sc:Integer`→`xsd:integer`, … (see table below) |
| `cr:Field.description` | `schema:description` on the InstanceVariable | Direct |
| `cr:Field.equivalentProperty` (URL) | `schema:propertyID` (URL string) on the InstanceVariable | Direct |

### Data type mapping (inverse)

| Croissant type | CDIF / XSD type |
|----------------|-----------------|
| `sc:Float` | `xsd:decimal` |
| `sc:Integer` | `xsd:integer` |
| `sc:Date` | `xsd:dateTime` |
| `sc:Boolean` | `xsd:boolean` |
| `sc:Text` (or any unmapped) | `xsd:string` |
| `sc:URL` | `xsd:anyURI` |

`sc:Float`'s precise width (float/double) is not recoverable from Croissant —
the inverse picks `xsd:decimal` as the safe default. If the original CDIF
distinction matters, downstream curation is required.

### InstanceVariable emission

For each `cr:Field` the inverse emits an entry under top-level
`schema:variableMeasured`:

```json
{
  "@id": "#<sluggified field name>",
  "@type": ["schema:PropertyValue", "cdi:InstanceVariable"],
  "schema:name": "<field name>",
  "schema:description": "<field description>",
  "schema:propertyID": "<equivalentProperty URL, if present>",
  "cdi:hasValueDomain": {
    "@type": ["cdi:ValueDomain", "cdif:SubstantiveValueDomain"],
    "cdi:physicalDataType": "<xsd:type from datatype map>"
  }
}
```

And on the source file's `hasPart` entry (or directly on the `DataDownload`
when it's a non-archive single file) the inverse appends a
`cdi:hasPhysicalMapping` entry:

```json
{
  "@type": ["cdi:PhysicalMapping", "cdi:ValueMapping"],
  "cdi:hasIndex": <ordinal>,
  "cdi:locator": "<column header from source.extract.column>",
  "cdi:isDefinedBy_InstanceVariable": {"@id": "#<sluggified field name>"}
}
```

Field ordering follows the order Croissant lists fields in (Croissant has no
explicit `cdi:hasIndex` equivalent — index is assigned 1..N in document order).

### Variable concept identification

Croissant's `equivalentProperty` is mapped to `schema:propertyID` (the CDIF
shape that the forward converter generates from). The inverse does NOT
populate `cdi:uses_Concept` — that requires a SKOS concept scheme reference
that Croissant does not carry.

## Croissant Properties with No CDIF Equivalent (Dropped)

These Croissant constructs are not preserved in CDIF output. A warning is
printed when any of them is encountered.

| Croissant | What it carried | Why dropped |
|-----------|-----------------|-------------|
| `cr:RecordSet.key` | Primary key field declaration | CDIF DataDescription has no equivalent at the variable level |
| `cr:Field.references` | Foreign-key join to another RecordSet | DDI-CDI `qualifies` is a closer match but semantically narrower; not auto-generated |
| `cr:Field.subField` | Nested fields | CDIF variables are flat |
| `cr:Field.repeated` | Repeated/list-valued field | No equivalent in CDIF InstanceVariable |
| `cr:Transform` (regex, separator, delimiter, jsonQuery) | Post-extraction transforms | CDIF describes data as-is; transforms cannot be roundtripped to CSVW because target shape is unknown |
| `cr:Split` | Train/validation/test partition | ML-only concept |
| `cr:Label`, `cr:BoundingBox`, `cr:SegmentationMask` | ML annotation types | Not part of science-data metadata |
| `cr:isLiveDataset` | Continuously-updated dataset flag | No equivalent |
| `cr:data` / `cr:examples` | Inline records / examples | No equivalent |
| `cr:FileSet` (glob patterns) | Files matched by pattern | CDIF requires explicit `hasPart` enumeration |

## CDIF Features Not Produced (Required Curation)

These CDIF DataDescription / Discovery features cannot be derived from Croissant
input and are left absent in the inverse output:

| CDIF property | Reason |
|---------------|--------|
| `schema:measurementTechnique` | Croissant has no equivalent. Add a `DefinedTerm` after conversion. |
| `schema:spatialCoverage` | Croissant has no spatial extent block. |
| `schema:temporalCoverage` | Croissant has no temporal coverage. |
| `prov:wasGeneratedBy` | Croissant has no PROV activity block. |
| `prov:wasDerivedFrom` | Populated by the inverse with the source Croissant URL only (for traceability), not the science-data lineage. |
| `dqv:hasQualityMeasurement` | Croissant has no DQV equivalent. |
| `schema:subjectOf` → catalog record details | Only the `dcterms:conformsTo` stub is emitted; `sdDatePublished`, `maintainer`, `about` etc. must be added. |
| CSVW table block (`csvw:delimiter`, `csvw:header`, …) | Croissant carries CSV semantics implicitly via Transform; the parse parameters are not in the source. |
| `cdi:role` (`Dimension`/`Measure`/`Attribute`) on components | Croissant fields have no role concept. |
| `cdi:uses_Concept` (SKOS concept reference) | Croissant has only `equivalentProperty` URL; the concept scheme is unknown. |

## Pass-through Properties

If the input Croissant document carries any of the CDIF pass-through properties
the forward converter preserves verbatim (`prov:wasGeneratedBy`,
`dqv:hasQualityMeasurement`, `schema:spatialCoverage`, `schema:temporalCoverage`,
`schema:measurementTechnique`, `schema:contributor`, `schema:subjectOf`), they
are copied directly into the CDIF output (this is how the inverse round-trips
the forward converter's pass-throughs).

## Limitations

- **Single RecordSet → single file assumption.** Each Croissant RecordSet is
  assumed to draw all its fields from one source `FileObject`. If a RecordSet's
  fields point at multiple files, the inverse warns and uses the first file as
  the canonical source.
- **No FileSet support.** Glob-based file collections are reported and dropped.
- **No transform pipeline introspection.** `cr:Transform` blocks are ignored.
- **DataType resolution is approximate.** `sc:Float` becomes `xsd:decimal`;
  the original width (`xsd:float` / `xsd:double`) is not preserved.

## Round-tripping

A CDIF document that has been converted to Croissant and then back will not be
byte-identical to the original. Properties not in Croissant's vocabulary
(unless preserved as pass-through during forward conversion) will be missing.
Round-tripping is intended for CDIF→Croissant→CDIF integrity testing of the
**discovery and tabular subset**, not for general lossless transport.
