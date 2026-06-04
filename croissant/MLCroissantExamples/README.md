# MLCroissantExamples

Real-world [Croissant](https://docs.mlcommons.org/croissant/) ML-dataset metadata
instances harvested from live public endpoints, for testing CDIF's Croissant
converters (`croissant/ConvertFromCroissant.py`, `croissant/ConvertToCroissant.py`)
against metadata that was *not* produced by CDIF tooling.

**Harvested:** 2026-06-04 · **14 instances** · sources: Hugging Face, OpenML, Kaggle.

These are the responses from each source's Croissant endpoint (raw Croissant
JSON-LD; the Kaggle responses are re-indented for readability, content unchanged).
The Hugging Face instances are additionally enriched with `dateModified`/`dateCreated`
harvested from the HF dataset API (HF's Croissant payload omits dates) — see
[`enrich_hf_dates.py`](enrich_hf_dates.py). They are third-party dataset *metadata*
(not the datasets themselves); each carries its own `license`/`citeAs` and is
reproduced here only as validation input.

## Inventory

| File | Source | Dataset | Croissant | dist / recordSet | Notes |
|------|--------|---------|-----------|------------------|-------|
| `hf-mnist.json` | Hugging Face | `ylecun/mnist` | 1.1 | 2 / 2 | Image classification |
| `hf-cifar10.json` | Hugging Face | `uoft-cs/cifar10` | 1.0 | 2 / 2 | Image classification |
| `hf-imdb.json` | Hugging Face | `stanfordnlp/imdb` | 1.0 | 2 / 2 | Text sentiment |
| `hf-squad.json` | Hugging Face | `rajpurkar/squad` | 1.1 | 2 / 2 | Question answering |
| `hf-glue.json` | Hugging Face | `nyu-mll/glue` | 1.0 | 13 / 24 | Multi-config benchmark (largest) |
| `hf-gsm8k.json` | Hugging Face | `openai/gsm8k` | 1.1 | 3 / 4 | Math word problems |
| `hf-awesome-chatgpt-prompts.json` | Hugging Face | `fka/awesome-chatgpt-prompts` | 1.1 | 2 / 2 | Prompt collection |
| `openml-iris.json` | OpenML | id 61 (iris) | 1.0 | 1 / 2 | Classic tabular |
| `openml-adult.json` | OpenML | id 1590 (adult) | 1.0 | 1 / 10 | Census tabular (many fields) |
| `openml-mnist784.json` | OpenML | id 554 (mnist_784) | 1.0 | 1 / 1 | Image-as-tabular |
| `kaggle-world-happiness.json` | Kaggle | `unsdsn/world-happiness` | 1.0 | 6 / 5 | Multi-file tabular |
| `kaggle-creditcardfraud.json` | Kaggle | `mlg-ulb/creditcardfraud` | 1.0 | 2 / 1 | Fraud detection tabular |
| `kaggle-wine-reviews.json` | Kaggle | `zynicide/wine-reviews` | 1.0 | 4 / 2 | Text + tabular |
| `kaggle-netflix-shows.json` | Kaggle | `shivamb/netflix-shows` | 1.0 | 2 / 1 | Catalog |

Mix of Croissant **1.0 and 1.1**, spanning image / text / QA / benchmark / math /
tabular / catalog, with structural variety (1–13 distributions, 1–24 record sets).
Hugging Face emits a mix of 1.0 and 1.1; OpenML and Kaggle both emit 1.0.

## How they were retrieved

**Hugging Face** — every dataset exposes a Croissant endpoint. Use the
**namespaced** id (`<owner>/<name>`); bare legacy aliases like `mnist` return 401.

```bash
curl -sL "https://huggingface.co/api/datasets/<owner>/<name>/croissant" -o out.json
```

HF Croissant omits dates; [`enrich_hf_dates.py`](enrich_hf_dates.py) backfills
`dateModified`/`dateCreated` from the HF dataset API (`/api/datasets/<id>`,
fields `lastModified`/`createdAt`) so the converted CDIF satisfies discovery's
required `schema:dateModified`.

**OpenML** — Croissant is auto-generated per dataset and stored at a derived path
(dataset id zero-padded to 8 digits, split 4/4):

```bash
# dataset 61 -> 00000061 -> 0000/0061
curl -sL "https://data.openml.org/datasets/0000/0061/dataset_61_croissant.json" -o out.json
```

(The OpenML website "Croissant" download button and the API-advertised URL resolve
to this same file. The `/croissant/<id>` web paths return the SPA HTML, not JSON.)

**Kaggle** — per-dataset Croissant, behind an authenticated Kaggle API token
(`~/.kaggle/kaggle.json`, basic-auth `username:key`). Served as
`application/octet-stream` but is JSON. Not every dataset has one (e.g. older
`uciml/iris` 404s).

```bash
curl -sL -u "$USER:$KEY" \
  "https://www.kaggle.com/datasets/<owner>/<slug>/croissant/download" -o out.json
```

## Sources not harvested

- **Google Dataset Search** — an *index/UI* over datasets whose pages embed
  schema.org / Croissant metadata; it has no per-dataset JSON download endpoint of
  its own. The instances it surfaces are the same HF / Kaggle / OpenML records (often
  linked via `sameAs`), so harvesting it adds discovery breadth but not new metadata
  shapes beyond the above.
