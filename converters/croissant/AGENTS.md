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
| `../mappings/{croissant-to-cdif,cdif-to-croissant}.sssom.tsv` | **The mappings themselves.** Edit these, not the Python |
| `../mappings/croissant-aliases.sssom.tsv` | Wild spelling variants → the term the table keys on |
| `../sssom_engine.py` | Shared table applier (DCAT and DDI use it too) |
| `croissantExamples/` | Source Croissant exports (`*-croissant.json` / `*.croissant.jsonld`) |
| `croissantExamples/cdif/` | Their CDIF conversions (`*-cdif.json` / `*.cdif.jsonld`) + `_manifest.json` |
| `MLCroissantExamples/` | 14 HF/Kaggle/OpenML Croissant sources — the inverse-converter regression corpus |

## Both converters are table-driven — edit the TSV, not the Python

`ConvertToCroissant.py` and `ConvertFromCroissant.py` state no property
correspondence in code. Each reads its SSSOM table through
`converters/sssom_engine.py`. **A change to what maps where belongs in the TSV.**
Touch the Python only when the *shape* is wrong, and then only by adding or
fixing a named transform.

Two extension columns beyond stock SSSOM:

- **`subject_class`** — the class the property sits on, because `sc:name` on a
  Dataset, a FileObject and a Field are three different mappings and a flat
  table cannot say so. A row with the wrong `subject_class` is silently inert:
  it will never be selected, and nothing reports it.
- **`transform`** — names a shaper in the converter's transform dict. An unknown
  name is skipped and the source property falls through to passthrough, so a
  typo here loses a mapping without an error.

**Row order is precedence, and arity decides whether that matters.** For a
scalar target the first row to fill it wins — that is how "prefer X, else Y" is
written. Array targets accumulate. Getting arity backwards keeps only the first
source and looks like correct output; it cost a silent drop of `dcat:theme`
across 72 records in the DCAT converter before it was caught.

The engine has a third arity, **`asis`**, for shapers that have already decided
their shape — Croissant's `sameAs` is one URL or a list of them, and the scalar
unwrap would keep only the first.

### `target_key`: the output key is not always the target term

Going to CDIF the row's `object_id` and the document key agree
(`sc:name` → `schema:name`). Going to Croissant they do not: the target term is
`sc:name` but the document key is the bare `name` its `@context` resolves. So
`MappingSet.target_key()` prefers the row's `object_json_path` when it is a
single bare segment, and falls back to `object_id`. A new row in the forward
table needs its `object_json_path` filled or it will write a CURIE key that no
Croissant reader looks for.

### The forward direction's loss is declared, not discovered

CDIF → Croissant drops provenance, extents, and most CDIF qualifiers. Those
properties still get a row — no target, `transform: unmapped` — so the loss is
on the record. This makes the real invariant checkable: **every CDIF property
either reaches the output or has a row saying it does not.** A property in
neither category means the table has a gap. When you add a CDIF property to the
profiles, add its row here too, even if the row only says "Croissant cannot
carry this".

Croissant's required fields (name, description, url, licence, datePublished,
creator, version) have fallbacks and warnings in `convert_cdif_to_croissant`.
Those are the converter deciding what to do about silence, not correspondences —
leave them in the Python.

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
  python ../../tools/FrameAndValidate.py _t.json -v --frame ../../CDIF-frame-2026.jsonld \
    --schema ../../CDIFDataDescriptionSchema.json | grep -Eo 'Validation (PASSED|FAILED)'
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
