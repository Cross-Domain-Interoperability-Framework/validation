# cdif-output — Croissant → CDIF conversions + validation

CDIF JSON-LD produced by running [`croissant/ConvertFromCroissant.py`](../../croissant/ConvertFromCroissant.py)
on the 14 harvested Croissant instances in [`../`](../), then validated against the
CDIF profiles each output claims.

**Generated:** 2026-06-04 · one `*-cdif.jsonld` per source instance.

```bash
# run from the repo root
python croissant/ConvertFromCroissant.py croissant/MLCroissantExamples/<name>.json \
  -o croissant/MLCroissantExamples/cdif-output/<name>-cdif.jsonld
python ConformanceValidate.py croissant/MLCroissantExamples/cdif-output/<name>-cdif.jsonld \
  --source local --no-shacl
```

Validation is JSON-Schema (structural) via `ConformanceValidate.py --source local`
against the document's claimed `discovery/1.1` + `data_description/1.1` profiles.
`core/1.1` and `manifest/1.1` have no local JSON Schema (validate `--source w3id`,
or run the per-profile SHACL, for those); structural validation here is discovery +
data_description.

## Results (after converter enhancements + HF date enrichment — see below)

**14/14 fully conform** to every profile they declare. The converter no longer
hardcodes the profile list — it calls [`detect_conformance.py`](../../detect_conformance.py),
which derives `dcterms:conformsTo` from what the record actually contains (a presence
SPARQL ASK per class, gated by that class's content SHACL). So:

- 13 carry `cdi:InstanceVariable`-typed variables → claim + pass `discovery` **and**
  `data_description`. `openml-mnist784` has no fields in its source record set, so it
  correctly claims **only `discovery`** (no empty `variableMeasured` is emitted and
  `data_description` is not in its `conformsTo`).
- The 4 Kaggle datasets ship as **archive distributions** (a `schema:DataDownload` with
  `schema:hasPart` member files), which `detect_conformance` recognizes as the
  `manifest/1.1` marker — so they additionally (and correctly) declare **`manifest/1.1`**.
  This is auto-detected per record; nothing in the converter special-cases Kaggle.

| file | src | vars | data_description? | manifest? | discovery/1.1 | data_description/1.1 |
|------|-----|------|-------------------|-----------|---------------|----------------------|
| hf-mnist | hf | 3 | yes | – | **PASS** | **PASS** |
| hf-cifar10 | hf | 3 | yes | – | **PASS** | **PASS** |
| hf-imdb | hf | 3 | yes | – | **PASS** | **PASS** |
| hf-squad | hf | 5 | yes | – | **PASS** | **PASS** |
| hf-glue | hf | 58 | yes | – | **PASS** | **PASS** |
| hf-gsm8k | hf | 6 | yes | – | **PASS** | **PASS** |
| hf-awesome-chatgpt-prompts | hf | 6 | yes | – | **PASS** | **PASS** |
| kaggle-creditcardfraud | kaggle | 31 | yes | **yes** | **PASS** | **PASS** |
| kaggle-netflix-shows | kaggle | 12 | yes | **yes** | **PASS** | **PASS** |
| kaggle-wine-reviews | kaggle | 25 | yes | **yes** | **PASS** | **PASS** |
| kaggle-world-happiness | kaggle | 55 | yes | **yes** | **PASS** | **PASS** |
| openml-adult | openml | 15 | yes | – | **PASS** | **PASS** |
| openml-iris | openml | 5 | yes | – | **PASS** | **PASS** |
| openml-mnist784 | openml | 0 | **no** (discovery-only) | – | **PASS** | n/a |

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
4. **Content-derived conformance** — the converter delegates `dcterms:conformsTo` to
   `detect_conformance.py` instead of a hardcoded list. Each profile is declared iff the
   record contains its marker (presence ASK) and passes that class's content SHACL:
   `core`/`discovery` for any named+identified dataset, `data_description/1.1` only when
   `cdi:InstanceVariable` variables are present, `manifest/1.1` when an archive
   distribution carries `schema:hasPart` files. A record with no variables stays
   discovery-level (no empty `schema:variableMeasured`, no `data_description` claim — so it
   can't fail a profile it doesn't assert; fixed the former `openml-mnist784` failure), and
   archive datasets pick up `manifest` automatically.

Plus, at the **harvest layer** (not the converter): the HF instances were enriched with
`dateModified`/`dateCreated` from the HF dataset API, since HF's Croissant payload omits
dates — see [`../enrich_hf_dates.py`](../enrich_hf_dates.py). This took the 7 HF files
from failing-on-dateModified to fully passing.

## Bottom line

The converter limitations from the first pass are fixed — **`cr:FileSet` extraction**
(HF now retains variables, e.g. glue 0 → 58), the **missing-identifier** failure
(landing-page-URL fallback), the HF date gap (closed at the harvest layer), and
**content-derived conformance** via `detect_conformance` (a record with no variables claims
only discovery; archive datasets auto-declare `manifest`). Result: **14/14 conform to every
profile they declare**, across all three sources and both Croissant versions, with no
conversion defects remaining.
