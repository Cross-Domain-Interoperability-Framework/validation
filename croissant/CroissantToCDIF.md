# Croissant to CDIF DataDescription Mapping

## Overview

This is the **inverse** of [`CDIFtoCroissant.md`](CDIFtoCroissant.md): it maps from
[Croissant](https://docs.mlcommons.org/croissant/docs/croissant-spec-1.1.html)
JSON-LD (version **1.1 or 1.0** — the converter accepts either on input) to the
current **CDIF** `cdif:`-namespaced schema (a profile of schema.org extended with
DDI-CDI, CSVW, PROV, and DQV).

`ConvertFromCroissant.py` emits the current CDIF shape:
`cdif:hasPhysicalMapping` (with `cdif:index` / `cdif:formats_InstanceVariable`),
single-valued `cdif:physicalDataType`, `cdi:hasIntendedDataType`, and
`cdif:hasPrimaryKey`. The legacy `cdi:hasValueDomain` / `cdi:locator` /
`cdi:hasIndex` / `cdi:ValueMapping` forms are no longer produced.

The conversion is **lossy in the Croissant→CDIF direction** because Croissant
does not carry information that CDIF requires or commonly expects:

- CDIF normally wraps a DOI as a structured `schema:identifier` `PropertyValue` —
  Croissant carries it only as `citeAs` (string) + `url`. The inverse recovers
  the DOI by regex from those.
- CDIF distinguishes `cdi:TabularTextDataSet` / `cdi:StructuredDataSet` /
  `schema:DataDownload` and may carry CSVW parsing properties. Croissant carries
  CSV semantics *implicitly* inside `cr:Transform`, so the inverse cannot
  reconstruct the CSVW block — only typed-column membership in a RecordSet.
- CDIF discovery / data-structure features (`schema:spatialCoverage`,
  `temporalCoverage`, `measurementTechnique`, the full `cdi:isStructuredBy`
  component model, PROV `wasGeneratedBy`) have no Croissant equivalents. The
  inverse leaves these absent; downstream curation is required.

The inverse handles the **lossless subset**: discovery-level dataset metadata,
distribution / file inventory (flat and archive), tabular RecordSet →
`cdi:InstanceVariable` + `cdif:hasPhysicalMapping`, and `cr:RecordSet.key` →
`cdif:hasPrimaryKey`.

> **Validation target depends on content.** A Croissant document **with** a
> `cr:RecordSet` produces a Data-Description-level CDIF document (validate against
> the DataDescription schema, which requires `schema:variableMeasured`). A
> Croissant document **without** any RecordSet produces a Discovery-level CDIF
> document (validate against the Discovery schema).

## Property Mapping: Dataset Level

### Direct mappings (schema.org shared surface)

| Croissant property | CDIF property | Notes |
|--------------------|---------------|-------|
| `name` | `schema:name` | Both required |
| `description` | `schema:description` | Required in Croissant, optional in CDIF — passed through |
| `url` | `schema:url` | Direct |
| `license` | `schema:license` | If absent or OGC `nil:missing`, output is empty |
| `datePublished` | `schema:datePublished` | Direct |
| `dateModified` | `schema:dateModified` | Direct |
| `creator` | `schema:creator` (wrapped in `@list`) | CDIF uses `@list` so authorship order is RDF-stable |
| `keywords` | `schema:keywords` | Direct (kept as array) |
| `publisher` | `schema:publisher` | Direct |
| `version` | `schema:version` | Omitted if Croissant's placeholder `"not assigned"` |
| `inLanguage` | `schema:inLanguage` | Direct |
| `sameAs` | `schema:sameAs` | Direct |
| `includedInDataCatalog` | `schema:includedInDataCatalog` | Direct (shared schema.org property) |
| `funding` | `schema:funding` | `MonetaryGrant` description / funder mapped through |

### Croissant `citeAs` and `url` → CDIF `schema:identifier`

Croissant has no structured `PropertyValue` identifier. The inverse reconstructs
one when a DOI can be detected:

1. Inspect `citeAs`, `url`, and `@id` for `10.NNNN/...` strings.
2. If found, emit a `schema:PropertyValue` with `schema:propertyID`
   (`https://registry.identifiers.org/registry/doi`), `schema:value`, and
   `schema:url` (`https://doi.org/...`).
3. Otherwise leave `schema:identifier` absent and preserve `citeAs` verbatim as
   `schema:citeAs`.

### Conformance declaration

Croissant declares conformance as a single top-level `dct:conformsTo` URI
(`http://mlcommons.org/croissant/1.1` or `/1.0`). CDIF requires a catalog record
on `schema:subjectOf`. The inverse emits the current CDIF catalog-record shape:

```json
"schema:subjectOf": {
  "@type": ["schema:Dataset"],
  "schema:additionalType": ["dcat:CatalogRecord"],
  "schema:about": {"@id": "<dataset @id>"},
  "dcterms:conformsTo": [
    {"@id": "https://w3id.org/cdif/core/1.0"},
    {"@id": "https://w3id.org/cdif/discovery/1.0"},
    {"@id": "https://w3id.org/cdif/data_description/1.0"}
  ]
}
```

The Croissant `conformsTo` is dropped (it is not part of CDIF's conformance
space) but the source is recorded in a `prov:wasDerivedFrom` block for
traceability.

## Property Mapping: Distribution / Files

### Concept correspondence

| Croissant type | CDIF type | Notes |
|----------------|-----------|-------|
| `cr:FileObject` (top-level, with `contentUrl`) | `schema:DataDownload` | Direct |
| `cr:FileObject` with `containedIn: {"@id": …}` | `schema:hasPart` item of the containing archive `DataDownload` | Grouped by `containedIn`; archive carries the components |
| `cr:FileObject` referenced by a `cr:RecordSet` field source | `schema:DataDownload` of `@type [schema:DataDownload, cdi:TabularTextDataSet]` | The attached RecordSet promotes the file to tabular type |
| `cr:FileSet` (glob-based) | _(no equivalent)_ | Dropped; emits a warning |

### Archive reconstruction

Croissant's archive idiom is "flat `FileObject` list with `containedIn`
back-references". CDIF's is "one parent `DataDownload` (`application/zip`) whose
`schema:hasPart` contains the components". The inverse pivots the structure:
groups components by `containedIn.@id`, finds the parent FileObject (the one with
the real `contentUrl`), and emits one archive `DataDownload` whose `schema:hasPart`
collects the components as `schema:MediaObject`s.

### File metadata mapping

| Croissant | CDIF | Notes |
|-----------|------|-------|
| `contentUrl` | `schema:contentUrl` | Direct; omitted if OGC `nil:inapplicable` |
| `encodingFormat` (string) | `schema:encodingFormat` (array of one) | CDIF prefers array |
| `contentSize` (string `"NNN B"`) | `schema:size` (`QuantitativeValue`) | Parsed to number + unit |
| `sha256` | `spdx:checksum` (`checksumAlgorithm_sha256`) | The nil placeholder (64 zeros) the forward converter emits is recognized and dropped |
| `md5` | `spdx:checksum` (`checksumAlgorithm_md5`) | |
| `name` | `schema:name` | Direct |
| `description` | `schema:description` | Direct |

## Property Mapping: Data Description (RecordSet/Field → variables)

### Concept correspondence

| Croissant concept | CDIF concept | Notes |
|-------------------|--------------|-------|
| `cr:RecordSet` | attaches `cdif:hasPhysicalMapping` to the source file (`cdi:TabularTextDataSet`) | One RecordSet maps to one tabular file; fields are assumed to draw from one source file |
| `cr:Field` | `cdi:InstanceVariable` (added to top-level `schema:variableMeasured`) + a `cdif:hasPhysicalMapping` entry | Field name → variable name + column |
| `cr:Field.source.extract.column` | the field's column identity | Reflected in the variable name and mapping order |
| `cr:Field.dataType` | `cdif:physicalDataType` (single value) + `cdi:hasIntendedDataType` (IRI) on the variable, and `cdif:physicalDataType` on the mapping | Reverse-mapped via the table below |
| `cr:Field.description` | `schema:description` on the InstanceVariable | Direct |
| `cr:Field.equivalentProperty` (URL) | `schema:propertyID` on the InstanceVariable | Direct |
| `cr:RecordSet.key` | `cdif:hasPrimaryKey` → `cdif:Key` / `cdif:isComposedOf` | Key field `@id`s resolved to their InstanceVariable `@id`s |

### Data type mapping (inverse)

| Croissant type | CDIF / XSD type |
|----------------|-----------------|
| `sc:Float` | `xsd:decimal` |
| `sc:Integer` | `xsd:integer` |
| `sc:Date` | `xsd:dateTime` |
| `sc:Boolean` | `xsd:boolean` |
| `sc:Text` (or any unmapped) | `xsd:string` |
| `sc:URL` | `xsd:anyURI` |

`sc:Float`'s precise width (float/double) is not recoverable; the inverse uses
`xsd:decimal` as the safe default.

### InstanceVariable + physical mapping emission

For each `cr:Field` the inverse emits a `schema:variableMeasured` entry:

```json
{
  "@id": "#<sluggified field name>",
  "@type": ["schema:PropertyValue", "cdi:InstanceVariable"],
  "schema:name": "<field name>",
  "schema:description": "<field description>",
  "schema:propertyID": "<equivalentProperty URL, if present>",
  "cdif:physicalDataType": "<xsd:type>",
  "cdi:hasIntendedDataType": {"@id": "<XMLSchema datatype IRI>"}
}
```

…and a `cdif:hasPhysicalMapping` entry on the source file's node (the `hasPart`
item, or the `DataDownload` directly for a non-archive single file):

```json
{
  "cdif:index": <ordinal, 1..N in field order>,
  "cdif:physicalDataType": "<xsd:type>",
  "cdif:formats_InstanceVariable": {"@id": "#<sluggified field name>"}
}
```

There is no per-mapping `cdi:locator` in the current schema; the column identity
is the variable name and the `cdif:index` ordinal.

### Primary key

`cr:RecordSet.key` (a single `{"@id": …}` or a list) is resolved to the key
fields' InstanceVariable `@id`s and emitted as a dataset-level `cdif:hasPrimaryKey`:

```json
"cdif:hasPrimaryKey": {
  "@type": ["cdif:Key"],
  "cdif:isComposedOf": [ {"@id": "#patientid"}, {"@id": "#measurename"} ]
}
```

## Data Structure profile (not reconstructed)

The inverse does **not** synthesize the CDIF Data Structure profile
(`cdi:isStructuredBy` → `DataStructure` with typed components). The structural
information is documented in [`CDIFtoCroissant.md`](CDIFtoCroissant.md), but
Croissant does not carry enough to rebuild it:

| Croissant | CDIF Data Structure target | Why not auto-generated |
|-----------|----------------------------|------------------------|
| `cr:RecordSet.key` | `cdif:hasPrimaryKey` (dataset level) | **Produced** — see above |
| `cr:Field.references` | `cdif:ForeignKey` on a `cdi:DataStructure` | A foreign key is recoverable in principle, but the full DataStructure / component graph it lives in is not; left to curation |
| _(none)_ | component roles (`IdentifierComponent` / `MeasureComponent` / `AttributeComponent` / `DimensionComponent`, i.e. `cdif:role`) | Croissant fields have no role concept |
| _(none)_ | `cdi:RepresentedVariable`, `cdi:DataStructure` flavour (Wide/Long/Dimensional) | No Croissant equivalent |

## Croissant Properties with No CDIF Equivalent (Dropped)

A warning is printed when any of these is encountered.

| Croissant | What it carried | Why dropped |
|-----------|-----------------|-------------|
| `cr:Field.subField` / `cr:parentField` | Nested fields | CDIF variables are flat |
| `cr:Field.isArray` / `cr:arrayShape` | Array-valued field (1.1) | No equivalent in `cdi:InstanceVariable` |
| `cr:Transform` (regex, separator, delimiter, jsonPath) | Post-extraction transforms | CDIF describes data as-is |
| `cr:Split` | Train/validation/test partition | ML-only concept |
| `cr:Label`, `cr:BoundingBox`, `cr:SegmentationMask` | ML annotation types | Not part of science-data metadata |
| `cr:isLiveDataset` | Continuously-updated flag | No equivalent |
| `cr:data` / `cr:examples` | Inline records / examples | No equivalent |
| `cr:FileSet` (glob patterns) | Files matched by pattern | CDIF requires explicit `hasPart` enumeration |

## CDIF Features Not Produced (Required Curation)

| CDIF property | Reason |
|---------------|--------|
| `schema:measurementTechnique` | Croissant has no equivalent. Add a `DefinedTerm` after conversion. |
| `schema:spatialCoverage` / `schema:temporalCoverage` | No Croissant spatial/temporal block. |
| `prov:wasGeneratedBy` | No Croissant PROV activity block. |
| `prov:wasDerivedFrom` | Populated only with the source Croissant reference (traceability), not science-data lineage. |
| `dqv:hasQualityMeasurement` | No Croissant DQV equivalent. |
| CSVW table block (`csvw:delimiter`, `csvw:header`, …) | Croissant carries CSV semantics implicitly via Transform. |
| `cdi:isStructuredBy` + component roles | Croissant fields have no role/structure concept. |
| `cdif:uses` (concept reference) | Croissant has only `equivalentProperty` URL → emitted as `schema:propertyID`; a SKOS concept scheme is unknown. |

## Pass-through Properties

If the input Croissant document carries CDIF pass-through properties (the forward
converter preserves these verbatim: `prov:wasGeneratedBy`, `prov:wasDerivedFrom`,
`dqv:hasQualityMeasurement`, `schema:spatialCoverage`, `schema:temporalCoverage`,
`schema:measurementTechnique`, `schema:contributor`, `schema:subjectOf`), they are
copied directly into the CDIF output — this is how the inverse round-trips the
forward converter's pass-throughs.

## Round-tripping

A CDIF document converted to Croissant 1.1 and back is **not** byte-identical to
the original. Properties outside Croissant's vocabulary (unless preserved as
pass-through) are lost, and the Data Structure profile is not reconstructed.
Round-tripping is intended for CDIF→Croissant→CDIF integrity testing of the
**discovery and tabular subset** (which validates against the current Discovery /
DataDescription schemas), not for general lossless transport.
