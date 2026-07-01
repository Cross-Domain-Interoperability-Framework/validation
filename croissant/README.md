# CDIF ↔ Croissant Conversion

This directory contains converters, crosswalk docs, and an example corpus for
transforming between CDIF JSON-LD metadata and
[Croissant](https://docs.mlcommons.org/croissant/docs/croissant-spec-1.1.html)
**1.1** JSON-LD (`http://mlcommons.org/croissant/1.1`), an ML-oriented dataset
metadata format developed by [MLCommons](https://mlcommons.org/working-groups/data/croissant/).

Both CDIF and Croissant build on schema.org and JSON-LD, so discovery-level
metadata (name, description, creator, license, keywords, …) maps directly. They
diverge in how they describe data structure: CDIF uses DDI-CDI `cdi:InstanceVariable`
with `cdif:`-namespaced physical mappings, keys, and (in the Data Structure
profile) typed components; Croissant uses `RecordSet`/`Field` with extract pipelines.

> **Schema versions.** The converters target **Croissant 1.1** and the current
> **`cdif:` CDIF schema** (`https://w3id.org/cdif/`): `cdif:hasPhysicalMapping`,
> single-valued `cdif:physicalDataType`, `cdif:index`, `cdif:formats_InstanceVariable`,
> `cdif:uses`, `cdif:hasPrimaryKey`. The Croissant→CDIF inverse accepts Croissant
> **1.0 or 1.1** on input. Legacy `cdi:hasPhysicalMapping` / `cdi:hasValueDomain`
> / `cdi:locator` / `cdi:hasIndex` forms are no longer produced or read.

## Files

| File | Description |
|------|-------------|
| `ConvertToCroissant.py` | **CDIF → Croissant 1.1** converter: reads current-`cdif:` CDIF JSON-LD, produces Croissant 1.1 |
| `ConvertFromCroissant.py` | **Croissant → CDIF** inverse (lossy): reads Croissant 1.0/1.1, produces current-`cdif:` CDIF that validates against the DataDescription schema (or the Discovery schema when the source has no `recordSet`) |
| `CDIFtoCroissant.md` | Property-by-property mapping (forward), incl. the full Data Structure profile crosswalk |
| `CroissantToCDIF.md` | Property-by-property mapping (inverse) |
| `croissantExamples/` | Example corpus (see below) |

## Usage

### CDIF → Croissant 1.1

```bash
python croissant/ConvertToCroissant.py input.jsonld -o output-croissant.json [-v]

# Validate the Croissant 1.1 output (requires: pip install mlcroissant)
python -c "import mlcroissant as mlc; mlc.Dataset(jsonld='output-croissant.json')"
```

### Croissant → CDIF

```bash
python croissant/ConvertFromCroissant.py input-croissant.json -o output.jsonld [-v]

# Validate the CDIF output against the appropriate current profile schema, e.g.
# (using the published release-repo FrameAndValidate + StructuredSchema):
python <profile-datadescription>/FrameAndValidate.py output.jsonld --validate \
  --schema cdifDataDescriptionStructuredSchema.json --frame cdifDataDescription-frame.jsonld
```

The inverse is **lossy** by design — Croissant carries no equivalents for
`prov:wasGeneratedBy`, `dqv:hasQualityMeasurement`, `schema:spatialCoverage`,
`schema:temporalCoverage`, `schema:measurementTechnique`, the CSVW table block,
or the Data Structure component roles. See `CroissantToCDIF.md` for the full
list. The converter:

- Reconstructs `schema:identifier` from a DOI in Croissant's `citeAs` / `url` /
  `@id` (as a `PropertyValue`), or from a plain `identifier` /
  `https://schema.org/identifier` value (bare string, `PropertyValue`, or list)
  when no DOI is present
- Pivots Croissant's `cr:FileObject` + `containedIn` archive pattern into CDIF's
  `schema:DataDownload` + `schema:hasPart`
- **Splits the distribution by whether a `RecordSet` describes it**: FileObjects
  that no `RecordSet` draws data from become `schema:relatedLink`
  (`LinkRole` → `EntryPoint`, `linkRelationship: "related"`) rather than
  `schema:distribution` — *but only when the dataset has at least one described
  data file*; if no FileObject has a RecordSet, the file(s) stay as distribution
  (an undescribed file is still the data, not a related resource)
- Maps Croissant `isBasedOn` sources → `prov:wasDerivedFrom`
  (`schema:CreativeWork` entries, or bare `@id` references for string sources)
- Generates `schema:variableMeasured` (`cdi:InstanceVariable`) + per-file
  `cdif:hasPhysicalMapping` entries (`cdif:index`, `cdif:formats_InstanceVariable`,
  `cdif:physicalDataType`) from `cr:RecordSet` / `cr:Field`
- Maps `cr:RecordSet.key` → `cdif:hasPrimaryKey` (`cdif:Key` / `cdif:isComposedOf`)
- Emits the current `schema:subjectOf` catalog-record shape
  (`schema:additionalType: ["dcat:CatalogRecord"]` + `schema:about` +
  `dcterms:conformsTo` to `https://w3id.org/cdif/{core,discovery,data_description}/1.0`)
- Preserves pass-through properties verbatim, merging custom `@context` prefixes

When the source Croissant has no `recordSet`, the output has no
`schema:variableMeasured` and validates against the **Discovery** schema (the
appropriate profile in that case).

**Dependencies:**
```bash
pip install PyLD jsonschema      # core (also used by FrameAndValidate.py)
pip install mlcroissant          # optional, for validating Croissant output
```

## How the forward conversion works

- **Dataset metadata** (name, description, url, license, creator, keywords,
  funding) maps directly via shared schema.org properties. `schema:sameAs`
  carrying a `PropertyValue` is reduced to its URL (Croissant expects a URL).
- **`schema:DataDownload`** → `cr:FileObject`. Croissant requires `contentUrl`,
  `encodingFormat`, and `sha256`/`md5` on every FileObject; when CDIF lacks them
  the converter emits valid placeholders (OGC `nil:inapplicable` URL,
  `application/octet-stream`, nil-zero `sha256` — the inverse strips the nil sha).
- **Archive distributions** (`schema:hasPart`) invert to flat `cr:FileObject`
  entries with `containedIn` back-references.
- **`cdi:TabularTextDataSet` + `cdif:hasPhysicalMapping`** → `cr:RecordSet` with
  `cr:Field` entries (`source.extract.column`). The RecordSet `@id` is kept
  distinct from the source FileObject `@id` (else JSON-LD merges the nodes).
- **`cdif:hasPrimaryKey`** → `cr:RecordSet.key`.
- **Data types** map with the variable's logical type preferred over the
  mapping's storage token (`xsd:decimal`/`Numeric` → `sc:Float`, etc.).
- **`schema:propertyID` / `cdif:uses`** → `cr:Field.equivalentProperty`.
- **`cdi:qualifies`** is *not* mapped to `cr:Field.references` (it is
  metadata-about-data, not a foreign key; the true FK analog is `cdif:ForeignKey`).

CDIF properties with no Croissant equivalent (`prov:*`, `dqv:*`,
`schema:spatialCoverage/temporalCoverage/measurementTechnique`,
`schema:contributor`, `schema:subjectOf`, `cdif:statistics`) are passed through
verbatim with their prefixes added to `@context`; Croissant consumers ignore them.

See [`CDIFtoCroissant.md`](CDIFtoCroissant.md) for the complete mapping including
the Data Structure profile (`cdi:isStructuredBy`, component roles, PrimaryKey /
ForeignKey, RepresentedVariable).

## Example corpus (`croissantExamples/`)

- **`*.croissant.jsonld`** — ~26 Croissant exports harvested from the Dataverse
  dev instance (`https://dataverse.dev1.codata.org`), dated 2025-11 … 2026-03.
- **`cdif/*.cdif.jsonld`** — the Croissant→CDIF conversions of those exports
  (with `cdif/README.md` and `cdif/_manifest.json` describing provenance).
- **`<name>-croissant.json`** — five CDIF→Croissant converter-output examples
  generated from ADA metadata in `../MetadataExamples/` / `../testJSONMetadata/`.
- **`minority-report-BI0104-croissant.json`** — a "semantic Croissant" export from
  the CODATA [minority-report](https://github.com/codata/the-minority-report) HIPS
  corpus (1 described CSV + 20 auxiliary files + 2 `isBasedOn` sources), with its
  `cdif/minority-report-BI0104-cdif.json` conversion. Exercises the
  `isBasedOn` → `prov:wasDerivedFrom` and non-RecordSet → `schema:relatedLink`
  mappings above.

## Test corpus note

The CDIF test corpus in `../MetadataExamples/` and `../testJSONMetadata/` has
been migrated to the current `cdif:` schema (see
`../tools/migrate_corpus_cdi_to_cdif.py`). All 84 files validate against the
current Discovery / DataDescription schema, so they are valid current-schema
inputs for `ConvertToCroissant.py`.
