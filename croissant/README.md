# CDIF ↔ Croissant Conversion

This directory contains converters and example output for transforming between
CDIF JSON-LD metadata and [Croissant](https://docs.mlcommons.org/croissant/docs/croissant-spec.html)
(mlcommons.org/croissant/1.0) JSON-LD, an ML-oriented dataset metadata format
developed by [MLCommons](https://mlcommons.org/working-groups/data/croissant/).

Both CDIF and Croissant build on schema.org and JSON-LD, so discovery-level metadata (name, description, creator, license, keywords, etc.) maps directly. They diverge in how they describe data structure: CDIF uses DDI-CDI `InstanceVariable` with physical mappings and CSVW table metadata; Croissant uses `RecordSet`/`Field` with extract/transform pipelines.

## Files

| File | Description |
|------|-------------|
| `ConvertToCroissant.py` | **CDIF → Croissant** converter: reads CDIF JSON-LD, produces Croissant 1.0 JSON-LD |
| `ConvertFromCroissant.py` | **Croissant → CDIF** converter (lossy inverse): reads Croissant 1.0 JSON-LD, produces CDIF DataDescription JSON-LD that validates against `CDIFDataDescriptionSchema.json` (or `CDIFDiscoverySchema.json` when the source has no `recordSet`) |
| `CDIFtoCroissant.md` | Detailed property-by-property mapping documentation (forward direction) |
| `CroissantToCDIF.md` | Detailed property-by-property mapping documentation (inverse direction) |
| `cdif_0y88-ps96-croissant.json` | Example output: 10 InstanceVariables, physicalMapping, RecordSet with 10 Fields, archive distribution |
| `tof-htk9-f770-croissant.json` | Example output: 10 mixed-type files (TIFF, BMP, CSV, PDF, YAML, ZIP), contributor roles |
| `xanes-2arx-b516-croissant.json` | Example output: archive with 2 component files, provenance pass-through |
| `xrd-2j0t-gq80-croissant.json` | Example output: archive with 2 files, hand-added variableMeasured |
| `yv1f-jb20-croissant.json` | Example output: archive with 3 files, hand-added variableMeasured |

## Usage

### CDIF → Croissant

```bash
# Convert a CDIF document to Croissant
python croissant/ConvertToCroissant.py input.jsonld -o output-croissant.json

# Verbose mode (shows conversion progress)
python croissant/ConvertToCroissant.py input.jsonld -o output-croissant.json -v

# Validate the Croissant output (requires: pip install mlcroissant)
mlcroissant validate --jsonld output-croissant.json
```

### Croissant → CDIF

```bash
# Convert a Croissant document to CDIF DataDescription
python croissant/ConvertFromCroissant.py input-croissant.json -o output.jsonld

# Validate the CDIF output (uses the existing FrameAndValidate.py)
python FrameAndValidate.py output.jsonld --frame CDIF-frame-2026.jsonld \
    -v --schema CDIFDataDescriptionSchema.json
```

The inverse converter is **lossy** by design — Croissant carries no equivalents
for `prov:wasGeneratedBy`, `dqv:hasQualityMeasurement`, `schema:spatialCoverage`,
`schema:temporalCoverage`, `schema:measurementTechnique`, the CSVW table block,
or `cdi:role`. See `CroissantToCDIF.md` for the full list of features dropped
vs. preserved. The converter:

- Reconstructs `schema:identifier` (`PropertyValue`) from a DOI found in
  Croissant's `citeAs` / `url` / `@id`
- Pivots Croissant's `cr:FileObject` + `containedIn` archive pattern into CDIF's
  `schema:DataDownload` + `schema:hasPart` pattern
- Generates `schema:variableMeasured` (`cdi:InstanceVariable`) + per-file
  `cdi:hasPhysicalMapping` entries from `cr:RecordSet` / `cr:Field`
- Emits a `schema:subjectOf` stub with the CDIF Discovery + DataDescription
  conformance URIs so the output validates against either profile
- Preserves any pass-through properties (`prov:*`, `dqv:*`, `schema:subjectOf`,
  etc.) the forward converter left in the Croissant doc verbatim, merging any
  custom prefixes from the source `@context` so framing succeeds

When the source Croissant has no `recordSet`, the output has no
`schema:variableMeasured` and only validates against the Discovery schema —
which is the appropriate profile in that case.

**Options:**
- `-o, --output FILE` — Write the Croissant JSON-LD to a file (default: stdout)
- `-v, --verbose` — Show detailed conversion progress

**Dependencies:**
```bash
pip install PyLD jsonschema          # core (also used by FrameAndValidate.py)
pip install mlcroissant              # optional, for validating Croissant output
```

## How the conversion works

The converter maps CDIF concepts to their Croissant equivalents:

- **Dataset metadata** (name, description, url, license, creator, keywords, funding) maps directly via shared schema.org properties
- **`schema:DataDownload`** becomes `cr:FileObject` with contentUrl, encodingFormat, contentSize, sha256
- **Archive distributions** (`schema:hasPart`) are inverted: CDIF says "archive hasPart [files]"; Croissant uses flat `cr:FileObject` entries with `containedIn` back-references. Component files use OGC `nil:inapplicable` for `contentUrl` (not independently downloadable). Archives without a source checksum get a nil `sha256` placeholder (64 zeros)
- **`schema:identifier`** (structured PropertyValue with DOI) maps to `citeAs` and fallback `url`
- **`cdi:TabularTextDataSet`** + `cdi:hasPhysicalMapping` generates `cr:RecordSet` with `cr:Field` entries, each with `source.extract.column` pointing to the originating CSV column
- **Data types** are mapped: `xsd:decimal` -> `sc:Float`, `xsd:string` -> `sc:Text`, `xsd:dateTime` -> `sc:Date`, etc.
- **`schema:propertyID`** and `cdi:uses` Concept map to `cr:Field.equivalentProperty`

CDIF properties with no native Croissant equivalent (`prov:wasGeneratedBy`, `dqv:hasQualityMeasurement`, `schema:spatialCoverage`, `schema:temporalCoverage`, `schema:measurementTechnique`, `schema:contributor`, `schema:subjectOf`) are **passed through verbatim** with their namespace prefixes added to the `@context`. These do not break Croissant validation -- consumers simply ignore unknown properties.

When `schema:license` is absent, the converter uses the OGC nil:missing URI as a placeholder. When `schema:version` is absent, it uses `"not assigned"` as a default.

See [`CDIFtoCroissant.md`](CDIFtoCroissant.md) for the complete property-by-property mapping, including distribution/archive handling, data structure mapping (RecordSet/Field generation from DDI-CDI), data type mapping, variable concept identification, and a full list of Croissant features not present in CDIF.

## Example Croissant output

The example files in this directory were generated from ADA (Astromat Data Alliance) metadata documents. The CDIF source files are in `MetadataExamples/` (this repo) and in the ADA test metadata collection (`testJSONMetadata/`).

| CDIF source | Croissant output | Features exercised |
|---|---|---|
| `MetadataExamples/cdif_10.60707-0y88-ps96.json` | `cdif_0y88-ps96-croissant.json` | RecordSet with 10 Fields, physicalMapping, archive distribution |
| `MetadataExamples/xanes-2arx-b516.json` | `xanes-2arx-b516-croissant.json` | Archive with 2 component files, provenance pass-through |
| `MetadataExamples/tof-htk9-f770.json` | `tof-htk9-f770-croissant.json` | 10 mixed-type files (TIFF, BMP, CSV, PDF, YAML, ZIP), contributor roles |
| `MetadataExamples/xrd-2j0t-gq80.json` | `xrd-2j0t-gq80-croissant.json` | Archive with 2 files, hand-added variableMeasured |
| `MetadataExamples/yv1f-jb20.json` | `yv1f-jb20-croissant.json` | Archive with 3 files, hand-added variableMeasured |

All five examples pass `mlcroissant validate` with zero errors. All 77 ADA test metadata files also pass validation when converted.
