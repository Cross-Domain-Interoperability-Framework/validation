# CDIF converters

Scripts that convert metadata **to or from** CDIF JSON-LD. Each format lives in
its own sub-directory with its converter(s), a README, and (where useful) mapping
docs and examples. All of these are ordinary command-line tools — most also
expose their conversion as an importable function.

| Path | Direction | Format |
|------|-----------|--------|
| [`soso2cdif.py`](soso2cdif.py) | SOSO (file **or URL**) → CDIF | Science-on-Schema.org |
| [`soso/ConvertToSOSO.py`](soso/ConvertToSOSO.py) | CDIF core+discovery → SOSO | Science-on-Schema.org |
| [`soso/ConvertFromSOSO.py`](soso/ConvertFromSOSO.py) | SOSO → CDIF core+discovery | Science-on-Schema.org |
| [`croissant/ConvertToCroissant.py`](croissant/ConvertToCroissant.py) | CDIF → Croissant 1.1 | MLCommons Croissant |
| [`croissant/ConvertFromCroissant.py`](croissant/ConvertFromCroissant.py) | Croissant → CDIF | MLCommons Croissant |
| [`DCAT/dcat_to_cdif.py`](DCAT/dcat_to_cdif.py) | DCAT → CDIF | W3C DCAT |
| [`DDI/ddi_to_cdif.py`](DDI/ddi_to_cdif.py) | DDI Codebook 2.5 → CDIF | DDI Codebook XML |

Related, but **not** in `converters/`: `../geocodes_harvester.py` harvests SOSO
records from the EarthCube GeoCodes SPARQL catalog and converts them to CDIF —
it's a network harvester, not a general file converter. For converting a SOSO
file or URL you already have, use `soso2cdif.py`.

## The "detect conformance" convention (for `format → CDIF` converters)

A CDIF record declares which profiles it conforms to in a `schema:subjectOf`
catalog record via `dcterms:conformsTo`. Rather than hard-coding a profile list,
a converter should set that from the record's **actual content**: the
[`detect_conformance.py`](../detect_conformance.py) module (at the repo root)
tests, per CDIF class, a presence SPARQL `ASK` (the elements the class introduces
beyond its base) gated by a content-SHACL validity check, and
`apply_conformance()` writes the detected `cdif:` URIs into
`subjectOf/dcterms:conformsTo` (preserving any non-`cdif:` domain claims).
`detect_conformance` has a remote-SHACL fallback, so it works without a local
building-blocks checkout.

All four `format → CDIF` converters — **`ConvertFromSOSO.py`**,
**`ConvertFromCroissant.py`**, **`dcat_to_cdif.py`**, and **`ddi_to_cdif.py`** —
run `detect_conformance` by default and write the detected `conformsTo` into the
catalog record. Each takes a **`--static-conformance`** flag that skips detection
and keeps the converter's built-in default instead (and detection degrades to
the built-in default automatically if `detect_conformance` or its deps are
unavailable). For example, the DDI converter's output carries `cdi:InstanceVariable`
variables, so detection adds `data_description` to the declared profiles.

## Why framing / structure matters

CDIF is JSON-LD built on schema.org (plus DDI-CDI, PROV, DQV, …). The JSON
Schemas validate a **framed tree** rooted at `schema:Dataset` with `schema:`-
prefixed property names and a required `subjectOf` catalog record. The other
formats differ in shape — SOSO uses bare schema.org terms via `@vocab` and has no
catalog record; Croissant nests `RecordSet`/`Field`; DCAT and DDI use their own
vocabularies. Each converter reconciles those structural differences (see each
format's README / mapping doc for the property-by-property detail).

---

## soso2cdif.py — SOSO file/URL → CDIF

The front-end for the SOSO→CDIF engine. Reads a SOSO `schema:Dataset` from a
**local file path or an http(s) URL** (extracting embedded `application/ld+json`
from an HTML landing page when the response isn't JSON), converts it via
`soso/ConvertFromSOSO.py`, derives `conformsTo` from content, and writes
`<input-stem>-cdif.json` (or the `-o` path — a file or a directory).

```bash
python soso2cdif.py path/to/soso.json                  # -> soso-cdif.json
python soso2cdif.py https://example.org/dataset -o out.json
python soso2cdif.py soso.json --cdif core --static-conformance
```

## soso/ — CDIF ↔ Science-on-Schema.org

Both are schema.org profiles, so conversion is structural alignment, not
vocabulary translation. `ConvertToSOSO.py` reshapes the `@context` to SOSO style,
strips `schema:` prefixes, drops the CDIF catalog record (SOSO has no equivalent),
passes CDIF-only properties through open-world, and warns on SOSO-required gaps
(`--https` emits `https://schema.org/`). `ConvertFromSOSO.py` prefixes names,
rewrites the `@context`, ensures CDIF-required fields where derivable, wraps
creators in a JSON-LD `@list`, and **adds** the required catalog record — with
`conformsTo` from `detect_conformance`. Mapping detail:
[`soso/README.md`](soso/README.md) and the property-by-property comparison in
`../../doc-corediscovery/documents/CDIF-Discovery-vs-SOSO-comparison.md`
(ESIP issue #283).

## croissant/ — CDIF ↔ MLCommons Croissant

`ConvertToCroissant.py` converts CDIF to Croissant 1.1 for ML dataset discovery
(`DataDownload` → `cr:FileObject`; `variableMeasured` + physical mapping →
`cr:RecordSet`/`cr:Field`; CDIF-only properties passed through). The lossy inverse
`ConvertFromCroissant.py` converts Croissant (1.0 or 1.1) back to CDIF
DataDescription/Discovery and sets `conformsTo` via `detect_conformance`. Mapping
docs: [`croissant/CDIFtoCroissant.md`](croissant/CDIFtoCroissant.md) (forward) and
[`croissant/CroissantToCDIF.md`](croissant/CroissantToCDIF.md) (inverse).

## DCAT/ — DCAT → CDIF

`dcat_to_cdif.py` converts a DCAT JSON-LD catalog or dataset to CDIF schema.org
form, mapping DCAT / Dublin Core properties to their schema.org equivalents per
the CDIF DCAT implementation guide. It can list the datasets in a catalog,
convert a selection, and optionally validate the output against the CDIF core
schema. See [`DCAT/README.md`](DCAT/README.md).

## DDI/ — DDI Codebook 2.5 → CDIF

`ddi_to_cdif.py` converts DDI Codebook 2.5 XML (e.g., a Harvard Dataverse DDI
export) to CDIF DataDescription JSON-LD: study-level metadata → the dataset;
`<var>` → `schema:variableMeasured` (`cdi:InstanceVariable`); `<fileDscr>` →
`schema:DataDownload` (`cdi:TabularTextDataSet`) with CSVW properties; tab-file
headers → physical mappings. `--doi` is required; `--fetch-headers` /
`--fetch-file-meta` pull column headers and size/checksum from the Dataverse API.

---

## Validating converter output

```bash
# CDIF output -> a CDIF profile schema (frame first)
python ../tools/FrameAndValidate.py out.json -v \
    --schema ../CDIFDiscoverySchema.json --frame ../CDIF-frame-2026.jsonld

# SOSO output -> SOSO v1.3 SHACL (use ConvertToSOSO --https so the shapes target it)
#   soso_common_v1.3.0.ttl from the ESIP science-on-schema.org repo

# Croissant output -> mlcroissant
mlcroissant validate --jsonld out-croissant.json
```

## Layout

```
converters/
├── README.md                 this file
├── soso2cdif.py              SOSO file/URL -> CDIF (front-end for soso/)
├── soso/                     CDIF <-> Science-on-Schema.org (+ README, examples)
├── croissant/                CDIF <-> MLCommons Croissant (+ mapping docs, examples)
├── DCAT/                     DCAT -> CDIF (+ README)
├── DDI/                      DDI Codebook 2.5 -> CDIF
└── mappings/                 SSSOM tables documenting each converter's mappings
```

## Mappings (SSSOM)

[`mappings/`](mappings/) holds an [SSSOM](https://mapping-commons.github.io/sssom/)
mapping set for each direction (`cdif→soso`, `soso→cdif`, `cdif→croissant`,
`croissant→cdif`, `dcat→cdif`, `ddi→cdif`) — the property-level correspondences
each converter applies, hand-authored from the mapping docs and code. See
[`mappings/README.md`](mappings/README.md).
