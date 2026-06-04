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

**13/14 fully pass** discovery **and** data_description; **14/14 pass discovery**. The
single remaining failure is a genuine *source-completeness* gap, not a conversion defect.

| file | src | vars | discovery/1.1 | data_description/1.1 | missing required |
|------|-----|------|---------------|----------------------|------------------|
| hf-mnist | hf | 3 | **PASS** | **PASS** | — |
| hf-cifar10 | hf | 3 | **PASS** | **PASS** | — |
| hf-imdb | hf | 3 | **PASS** | **PASS** | — |
| hf-squad | hf | 5 | **PASS** | **PASS** | — |
| hf-glue | hf | 58 | **PASS** | **PASS** | — |
| hf-gsm8k | hf | 6 | **PASS** | **PASS** | — |
| hf-awesome-chatgpt-prompts | hf | 6 | **PASS** | **PASS** | — |
| kaggle-creditcardfraud | kaggle | 31 | **PASS** | **PASS** | — |
| kaggle-netflix-shows | kaggle | 12 | **PASS** | **PASS** | — |
| kaggle-wine-reviews | kaggle | 25 | **PASS** | **PASS** | — |
| kaggle-world-happiness | kaggle | 55 | **PASS** | **PASS** | — |
| openml-adult | openml | 15 | **PASS** | **PASS** | — |
| openml-iris | openml | 5 | **PASS** | **PASS** | — |
| openml-mnist784 | openml | 0 | **PASS** | FAIL(1) | variableMeasured |

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
4. **1.1 conformance** — emits `core`/`discovery`/`data_description` **`1.1`** URIs.

Plus, at the **harvest layer** (not the converter): the HF instances were enriched with
`dateModified`/`dateCreated` from the HF dataset API, since HF's Croissant payload omits
dates — see [`../enrich_hf_dates.py`](../enrich_hf_dates.py). This took the 7 HF files
from failing-on-dateModified to fully passing.

## Remaining failure — source-completeness, not a converter bug

- **`openml-mnist784` `schema:variableMeasured`.** Its *source* Croissant record set has
  **0 `field`s** (OpenML didn't enumerate the 784 pixel columns), so there is nothing to
  convert into variables. data_description requires `variableMeasured`. This is a
  source-side gap — the converter has nothing to work with.

## Bottom line

The two real converter limitations from the first pass are fixed — **`cr:FileSet`
extraction** (HF now retains variables, e.g. glue 0 → 58) and the **missing-identifier**
failure (landing-page-URL fallback) — and the HF date gap is closed at the harvest layer.
Result: **14/14 pass discovery, 13/14 pass data_description**, across all three sources and
both Croissant versions. The one residual failure is purely *what the source metadata
doesn't carry* (OpenML's mnist_784 omits field definitions), not a conversion defect.
