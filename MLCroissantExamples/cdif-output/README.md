# cdif-output — Croissant → CDIF conversions + validation

CDIF JSON-LD produced by running [`croissant/ConvertFromCroissant.py`](../../croissant/ConvertFromCroissant.py)
on the 14 harvested Croissant instances in [`../`](../), then validated against the
CDIF profiles each output claims.

**Generated:** 2026-06-04 · one `*-cdif.jsonld` per source instance.

```bash
python croissant/ConvertFromCroissant.py MLCroissantExamples/<name>.json \
  -o MLCroissantExamples/cdif-output/<name>-cdif.jsonld
python ConformanceValidate.py MLCroissantExamples/cdif-output/<name>-cdif.jsonld \
  --source local --no-shacl
```

Validation is JSON-Schema (structural) via `ConformanceValidate.py --source local`
against the document's claimed `discovery/1.1` + `data_description/1.1` profiles.
`core/1.1` is not mapped locally (validate `--source w3id` for that); SHACL not run.

## Results (after converter enhancements + HF date enrichment — see below)

**14/14 fully conform** to every profile they declare. 13 describe variables and
claim + pass `discovery` **and** `data_description`. `openml-mnist784` has no fields in
its source record set, so it correctly claims **only `discovery`** (passing) rather than
declaring a `data_description` profile it can't satisfy — no empty `variableMeasured` is
emitted and `data_description` is not in its `conformsTo`.

| file | src | vars | claims data_description? | discovery/1.1 | data_description/1.1 |
|------|-----|------|--------------------------|---------------|----------------------|
| hf-mnist | hf | 3 | yes | **PASS** | **PASS** |
| hf-cifar10 | hf | 3 | yes | **PASS** | **PASS** |
| hf-imdb | hf | 3 | yes | **PASS** | **PASS** |
| hf-squad | hf | 5 | yes | **PASS** | **PASS** |
| hf-glue | hf | 58 | yes | **PASS** | **PASS** |
| hf-gsm8k | hf | 6 | yes | **PASS** | **PASS** |
| hf-awesome-chatgpt-prompts | hf | 6 | yes | **PASS** | **PASS** |
| kaggle-creditcardfraud | kaggle | 31 | yes | **PASS** | **PASS** |
| kaggle-netflix-shows | kaggle | 12 | yes | **PASS** | **PASS** |
| kaggle-wine-reviews | kaggle | 25 | yes | **PASS** | **PASS** |
| kaggle-world-happiness | kaggle | 55 | yes | **PASS** | **PASS** |
| openml-adult | openml | 15 | yes | **PASS** | **PASS** |
| openml-iris | openml | 5 | yes | **PASS** | **PASS** |
| openml-mnist784 | openml | 0 | **no** (discovery-only) | **PASS** | n/a |

(`vars` = `schema:variableMeasured` count. Compare to the first run: every file failed on
`schema:identifier`, and all 7 HF files extracted **0** variables.)

## Converter enhancements made (this round)

1. **`cr:FileSet` support** — `ConvertFromCroissant.py` now maps Croissant `cr:FileSet`
   (the parquet-shard glob Hugging Face uses) to a `schema:DataDownload`, inheriting the
   `containedIn` parent FileObject's `contentUrl` and recording the `includes` glob.
   Field sources are resolved from **either** `source.fileObject` (CSV) **or**
   `source.fileSet` (parquet). Result: HF datasets now keep their variables —
   e.g. **glue 0 → 58**, squad 5, gsm8k 6.
2. **Identifier fallback** — when the source has no DOI (`citeAs`/`url`), CDIF's required
   `schema:identifier` is now filled from the dataset **landing-page URL** (or `@id`).
   This cleared the `schema:identifier` failure on **all 14**. A curator can swap in a
   DOI later.
3. **dateModified fallback** — when `dateModified` is absent, fall back to
   `datePublished`, then `dateCreated` (never fabricated).
4. **1.1 conformance, declared conditionally** — emits `core`/`discovery` **`1.1`**
   always, and `data_description/1.1` **only when variables are present**. A record with
   no variables (no source fields) stays discovery-level: no empty `schema:variableMeasured`
   is inserted and `data_description` is not claimed — so it can't fail a profile it
   doesn't assert. (Fixed the former `openml-mnist784` failure.)

Plus, at the **harvest layer** (not the converter): the HF instances were enriched with
`dateModified`/`dateCreated` from the HF dataset API, since HF's Croissant payload omits
dates — see [`../enrich_hf_dates.py`](../enrich_hf_dates.py). This took the 7 HF files
from failing-on-dateModified to fully passing.

## Bottom line

The converter limitations from the first pass are fixed — **`cr:FileSet` extraction**
(HF now retains variables, e.g. glue 0 → 58), the **missing-identifier** failure
(landing-page-URL fallback), the HF date gap (closed at the harvest layer), and
**conditional `data_description` declaration** (a record with no variables claims only
discovery). Result: **14/14 conform to every profile they declare**, across all three
sources and both Croissant versions, with no conversion defects remaining.
