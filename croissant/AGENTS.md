# AGENTS.md — CDIF ↔ Croissant conversion

Scope-specific guide for `croissant/`. For repo-wide context see the root
[`AGENTS.md`](../AGENTS.md); for the human-facing overview see [`README.md`](README.md).

## What lives here

| File | Role |
|------|------|
| `ConvertToCroissant.py` | CDIF → Croissant 1.1 (forward) |
| `ConvertFromCroissant.py` | Croissant 1.0/1.1 → CDIF (inverse, lossy) |
| `CDIFtoCroissant.md` | Forward property mapping (incl. Data Structure profile crosswalk) |
| `CroissantToCDIF.md` | Inverse property mapping |
| `croissantExamples/` | Source Croissant exports (`*-croissant.json` / `*.croissant.jsonld`) |
| `croissantExamples/cdif/` | Their CDIF conversions (`*-cdif.json` / `*.cdif.jsonld`) + `_manifest.json` |
| `MLCroissantExamples/` | 14 HF/Kaggle/OpenML Croissant sources — the inverse-converter regression corpus |

## Target versions (do not drift)

- **Croissant 1.1** (`http://mlcommons.org/croissant/1.1`) on output; inverse
  reads **1.0 or 1.1**.
- Current **`cdif:` schema** (`https://w3id.org/cdif/`): `cdif:hasPhysicalMapping`,
  single-valued `cdif:physicalDataType`, `cdif:index`, `cdif:formats_InstanceVariable`,
  `cdif:uses`, `cdif:hasPrimaryKey`. Legacy `cdi:hasPhysicalMapping` /
  `cdi:hasValueDomain` / `cdi:locator` / `cdi:hasIndex` are neither produced nor read.

## Inverse converter (`ConvertFromCroissant.py`) — key invariants

- **conformsTo is content-derived**, not hardcoded: `detect_conformance.apply_conformance`
  sets `schema:subjectOf/dcterms:conformsTo` from what the output actually contains
  (so a variable-less dataset drops `data_description`, a Kaggle archive gains
  `manifest/1.1`). Do **not** reintroduce a static core/discovery heuristic.
- **`schema:identifier` is required by core.** It is resolved in priority order:
  DOI (via `_convert_identifier` from `citeAs`/`url`/`@id`) → plain `identifier` /
  `https://schema.org/identifier` / `http://schema.org/identifier` value → landing-page
  URL fallback. A missing identifier makes the output fail validation.
- **Distribution split** (`_has_data_part` / `_download_to_related_link`): a FileObject
  no `RecordSet` draws from → `schema:relatedLink`. **Guard:** only demote when the
  dataset has ≥1 described data file (`has_data`); with no RecordSets at all, keep every
  file as `schema:distribution`. Regression witness: `openml-mnist784` (no RecordSet)
  must stay 1 distribution / 0 relatedLink and validate against **Discovery**, not
  DataDescription.
- **`isBasedOn` → `prov:wasDerivedFrom`** (`_convert_is_based_on`): object sources become
  `schema:CreativeWork`, string sources become `{"@id": …}`. The converter also appends a
  provenance stub `{"@id": <croissant-source-uri>, ...}` — so the array is normally the
  mapped sources **plus** one stub.
- **Lossy by design.** Croissant has no equivalent for `prov:wasGeneratedBy`,
  `dqv:hasQualityMeasurement`, `schema:spatialCoverage/temporalCoverage`,
  `schema:measurementTechnique`, CSVW table blocks, or Data Structure component roles.
  Pass-through prefixes are merged into `@context` so anything hand-carried survives framing.
- `cdi:qualifies` is **not** a foreign key — never map it to `cr:Field.references`.

## Verifying a change

The inverse converter must not regress the 14-file corpus. Convert each and validate
against its correct profile schema (DataDescription, or Discovery when the source has no
`recordSet`):

```bash
cd croissant
for f in MLCroissantExamples/*.json; do
  python ConvertFromCroissant.py "$f" -o _t.json 2>/dev/null
  python ../tools/FrameAndValidate.py _t.json -v --frame ../CDIF-frame-2026.jsonld \
    --schema ../CDIFDataDescriptionSchema.json | grep -Eo 'Validation (PASSED|FAILED)'
done; rm -f _t.json
```

Expected: 13/14 pass DataDescription; `openml-mnist784` passes **Discovery** only
(it has no RecordSet).

Forward output is validated with `mlcroissant`:

```bash
python -c "import mlcroissant as mlc; mlc.Dataset(jsonld='output-croissant.json')"
```

## Naming / placement convention

Croissant sources → `croissantExamples/<name>-croissant.json`; their CDIF conversions →
`croissantExamples/cdif/<name>-cdif.json`. Keep the pair names in sync.
