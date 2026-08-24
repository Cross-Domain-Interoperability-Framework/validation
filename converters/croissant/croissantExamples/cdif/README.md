# CDIF outputs converted from Dataverse Croissant exports

Generated 2026-05-27 from the 26 Croissant docs in `..\` (the parent
`c:\tmp\croissant202605\`) using
`C:\GithubC\CDIF\validation\croissant\ConvertFromCroissant.py`.

Source: Dataverse dev instance at `https://dataverse.dev1.codata.org`, official
`croissant` exporter (MLCommons Croissant 1.0). Fetched and saved earlier in the
same session.

## Validation results

All 26 outputs validate against one of the CDIF profile schemas. None failed
validation entirely.

| Profile | Pass count | Datasets with `cr:RecordSet` in source? |
|---|---|---|
| **CDIFDataDescriptionSchema.json** | **17** | yes — Croissant `recordSet` produced `schema:variableMeasured` + `cdi:hasPhysicalMapping` |
| **CDIFDiscoverySchema.json** | **9** | no — no Croissant fields, so CDIF DataDescription's required `schema:variableMeasured` is missing; the doc still validates as a CDIF Discovery doc |

DataDescription (17): 6TYU3O, DASWFN, X1NGOC, RIB64Q, SPJJDT, T6XJID, GAFUDD,
6QKC3J, BXSHPO, ON7W1G, KRKCNG, 9DGDFN, FN88ZU, GDTLFP, 22JJOI, LBSTAY, XHP7WN.

Discovery-only (9): C2G6XB, KQI5SN, 2TQRHJ, 8MODGT, 4ZSKVU, ZTZH3N, BNPFWG,
SAFMQU, XAJSJ1.

## Contents

- `*.cdif.jsonld` — 26 converted CDIF JSON-LD documents (one per source).
  Filename format `YYYY-MM-DD_<DOI-suffix>_<sluggified-name>.cdif.jsonld`.
- `_validation_results.json` — per-file result of running each output through
  `FrameAndValidate.py` against both DataDescription and Discovery schemas.

## Reproducing

```bash
# Convert one file
python C:/GithubC/CDIF/validation/croissant/ConvertFromCroissant.py \
    "C:/tmp/croissant202605/<file>.croissant.jsonld" \
    -o "C:/tmp/croissant202605/cdif/<file>.cdif.jsonld"

# Validate (use the conda interpreter that has pyld + jsonschema)
C:/Users/smrTu/miniconda3/python.exe \
    C:/GithubC/CDIF/validation/FrameAndValidate.py \
    "C:/tmp/croissant202605/cdif/<file>.cdif.jsonld" \
    --frame C:/GithubC/CDIF/validation/CDIF-frame-2026.jsonld \
    -v --schema C:/GithubC/CDIF/validation/CDIFDataDescriptionSchema.json
```

## Caveats

- The conversion is **lossy** — see `C:\GithubC\CDIF\validation\croissant\CroissantToCDIF.md`
  for the full list of features Croissant doesn't carry (PROV, DQV, CSVW table
  block, spatial/temporal coverage, measurement technique, `cdi:role`).
- The `subjectOf` block is a **stub** with both Discovery and DataDescription
  conformance URIs. Real catalog-record fields (`schema:maintainer`,
  `schema:about`, `schema:sdDatePublished`) are filled in only as much as the
  Croissant source supports — typically `sdDatePublished` from `dateModified`.
- `schema:identifier` is reconstructed from a DOI found by regex in the
  Croissant `citeAs` / `url` / `@id`. For the Dataverse exports here every
  dataset has a `doi:10.5072/FK2/…` so this succeeds for all 26.
- `cdi:physicalDataType` is mapped from `cr:Field.dataType` via an
  approximate inverse: `sc:Float` → `xsd:decimal` (the original `xsd:float` /
  `xsd:double` distinction is not recoverable from Croissant).
- The 9 Discovery-only outputs simply have no `schema:variableMeasured` block.
  The CDIF Discovery profile is the right validation target for those.

## Source manifest

The parent folder's `_manifest.json` lists all 27 source datasets with
`createdAt`, DOI, and name. (One Croissant doc — `FK2/GHXTXR` "Random dataset to
explore" — was deleted earlier in the session at the user's request, so this
folder has 26 of those 27 converted.)
