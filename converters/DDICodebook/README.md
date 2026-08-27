# DDI Codebook 2.5 → CDIF

[`ddi25_to_cdif.py`](ddi25_to_cdif.py) converts **DDI Codebook 2.5** XML
(root `<codeBook version="2.5">`, namespace `ddi:codebook:2_5`,
[schema](http://www.ddialliance.org/Specification/DDI-Codebook/2.5/XMLSchema/codebook.xsd);
[2.6 docs](https://docs.ddialliance.org/DDI-Codebook/2.6/xmlschema/)) to CDIF
JSON-LD — e.g. NADA-published survey catalogs (DHS, MICS, World Bank microdata).

```bash
python ddi25_to_cdif.py Examples/XML/MWI_2019_MICS_v01_M.xml -o out.json
python ddi25_to_cdif.py input.xml --id https://catalog.example/dataset/123
```

## It reuses the DDI 1.2.2 engine

DDI Codebook 2.5 shares the Codebook element vocabulary with DDI 1.2.2 — the same
`stdyDscr`/`citation`, `sumDscr`, `method`, `dataAccs`, `var`, and `fileDscr`
element names. This converter is therefore a **thin wrapper around
[`../DDI/ddi122_to_cdif.py`](../DDI/ddi122_to_cdif.py)**: namespaces are stripped,
so `ddi:codebook:2_5` is handled transparently, and only the source label on the
catalog-record note differs (`"DDI Codebook 2.5"`). See that converter's README
for the full element→CDIF mapping. It is likewise **source-agnostic** (identifier
from `IDNo`, access URL from `dataAccs/accsPlac`, `nil:missing` for absent
download URLs) and decides profile scope per content via
[`detect_conformance`](../../detect_conformance.py).

The shared engine truncates full-datetime production dates (NADA emits
`2026-03-18T04:00:00.000Z`) to a plain date, which the CDIF date pattern accepts.

**Known deferral:** coded variables (`<var><catgry>` code lists) are not yet
emitted as CDIF / DDI-CDI code lists — the same as the 1.2.2 converter.

## Schema availability (a caution)

Getting the official XSDs to verify these mappings was uneven, and worth flagging
for anyone who wants to reproduce the comparison:

- **DDI Codebook 2.5** — `codebook.xsd` is publicly downloadable from the DDI
  Alliance and is self-contained (apart from `xml`/`xhtml`/`dcterms` imports).
- **DDI 1.2.2 (ICPSR)** — the canonical
  `http://www.icpsr.umich.edu/DDI/Version1-2-2.xsd` is **not reliably
  accessible**: the host answers HTTP 403 behind a Cloudflare challenge, and the
  schema is **not** published in the DDI Alliance GitHub repos (which cover the
  2.x line only). The copy used here had to be sourced from a **third-party
  mirror** bundled with the CESSDA Metadata Validator
  ([`cessda/cessda.cmv.console`](https://github.com/cessda/cessda.cmv.console),
  `src/main/resources/schemas/nesstar/Version1-2-2.xsd`).

An element-level diff of the two XSDs confirms **DDI 2.5 is a strict superset of
1.2.2**: all 166 of 1.2.2's element names are present in 2.5 unchanged (none
removed or renamed), and 2.5 adds 84 — notably `nCube`/`nCubeGrp` aggregate
(cube) data and the `codeList*` controlled-vocabulary machinery. That superset
relationship is exactly why this 2.5 converter can reuse the 1.2.2 extraction
engine unchanged; the unmapped 84 (above all `nCube`) are the natural place for a
future codebook-specific enhancement — their best-guess CDIF targets are catalogued
in **[ddi25-additions-cdif-mapping.md](ddi25-additions-cdif-mapping.md)**.

## Validation status (2 example files)

`Examples/XML/` holds the two v2.5 inputs; they convert to `Examples/cdif/`:

| File | vars | files | conformsTo |
|------|-----:|------:|------------|
| `MWI_2019_MICS_v01_M` | 1942 | 8 | core + discovery + data_description |
| `MWI_2024_DHS_v01_M` | 2679 | 53 | core + discovery + data_description |

- **JSON Schema** (`CDIFDiscoverySchema.json` + `CDIFDataDescriptionSchema.json`
  via `../../tools/FrameAndValidate.py`): **2/2 pass** both.
- **SHACL** (`../../ShaclValidation/CDIF-Discovery-Shapes.ttl`): **0 violations**;
  warnings are advisory (per-variable `propertyID`/physical data type, contacts).
