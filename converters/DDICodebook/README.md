# DDI Codebook 2.5 → CDIF

[`ddi25_to_cdif.py`](ddi25_to_cdif.py) converts **DDI Codebook 2.5** XML to CDIF
JSON-LD, source-agnostically (no repository assumptions). Typical inputs are
NADA-published survey catalogs — DHS, MICS, World Bank / national microdata.

- **Root / version:** `<codeBook version="2.5">`
- **Namespace:** `ddi:codebook:2_5`
- **Schema:** [`codebook.xsd`](http://www.ddialliance.org/Specification/DDI-Codebook/2.5/XMLSchema/codebook.xsd)
  ([2.6 documentation](https://docs.ddialliance.org/DDI-Codebook/2.6/xmlschema/))

```bash
python ddi25_to_cdif.py Examples/XML/MWI_2019_MICS_v01_M.xml -o out.json
python ddi25_to_cdif.py input.xml --id https://catalog.example/dataset/123
python ddi25_to_cdif.py input.xml --base-uri urn:mycat   # mint @id from IDNo
```

Profile scope is decided **per content** via
[`detect_conformance`](../../detect_conformance.py): the example files resolve to
**core + discovery + data_description**.

## Relationship to DDI 1.2.2

DDI Codebook is a **single version line** (1.0 → 1.2.2 → 2.0 → … → 2.5 → 2.6).
2.5 is a formally-namespaced, *extended* evolution of the 1.x Codebook — but at
the element level it is a **strict superset** of DDI 1.2.2. An element-name diff
of the two XSDs (`Version1-2-2.xsd` vs `codebook.xsd`):

| | distinct element names |
|---|---|
| DDI 1.2.2 | 166 |
| DDI 2.5 | 250 |
| shared | **166** |
| only in 1.2.2 (removed / renamed) | **0** |
| only in 2.5 (added) | **84** |

**Every one of 1.2.2's 166 elements is present in 2.5 unchanged** — nothing was
removed or renamed. The two also share the same document skeleton
(`docDscr` / `stdyDscr` / `dataDscr` / `fileDscr`; `citation` / `titlStmt` /
`sumDscr` / `method` / `dataAccs`; `var` / `labl` / `varFormat` / `sumStat` /
`catgry`). The only serialization difference relevant to a reader is the
namespace (`ddi:codebook:2_5` vs the ICPSR `http://www.icpsr.umich.edu/DDI`),
which this converter neutralizes by stripping namespaces.

**Consequence — this converter is a thin wrapper.** Because 2.5 ⊇ 1.2.2, the
extraction engine written for 1.2.2 finds every element it looks for in a 2.5
document. `ddi25_to_cdif.py` therefore imports and reuses
[`../DDI/ddi122_to_cdif.py`](../DDI/ddi122_to_cdif.py) verbatim and only supplies
the 2.5 source label (`"DDI Codebook 2.5"`) for the catalog-record note. **The
full element → CDIF mapping is documented once, in
[`../DDI/README.md`](../DDI/README.md)** — it applies identically here.

The shared engine also handles the one 2.5-flavoured quirk seen in the wild:
NADA emits full-datetime production dates (`2026-03-18T04:00:00.000Z`), which it
truncates to a plain date (the CDIF date pattern rejects fractional seconds).

### The 84 elements 2.5 adds

These are real capabilities neither converter maps today — most are additive
discovery/quality/provenance detail, but a few reflect model differences (above
all **`nCube`**, aggregate *cube* data — a different data structure from the
`var`/`fileDscr` microdata both converters assume, and thus **silently dropped**).
Their best-guess CDIF targets are catalogued in
**[`ddi25-additions-cdif-mapping.md`](ddi25-additions-cdif-mapping.md)**. The
highest-value follow-ups are `nCube` → the CDIF **DataStructure — Dimensional
Data** profile, and the `codeList*` / `<catgry>` code lists → the **codelist /
conceptscheme** profiles.

## The analyzed-sample convention (geochem building blocks)

When the "sample" a dataset describes is mapped, it should follow the CDIF
geochemistry building-block pattern: **the analyzed sample is the `schema:object`
of the `prov:wasGeneratedBy` activity, and the sample's descriptive
classification is carried in `schema:additionalType` on that object node** — not
in a loose `schema:additionalProperty`. In geochem this looks like:

```jsonc
"prov:wasGeneratedBy": [{
  "@type": ["schema:Action", "prov:Activity"],
  "schema:object": [{
    "@type": ["schema:Thing", "https://w3id.org/isample/vocabulary/materialsampleobjecttype/materialsample"],
    "schema:additionalType": ["MaterialSample"],   // sample-type classification
    "schema:identifier": ["OREX-803034-0"]
  }]
}]
```

For DDI survey data the analogue is the **analyzed population / unit of
analysis** — `universe`, `unitType`, `cohort`, `participant`, and the sampling
frame. When these are eventually mapped they should populate
`prov:wasGeneratedBy` → `schema:object` (with the population/sample class as
`schema:additionalType`), rather than the placeholder `additionalProperty`
targets currently noted in the mapping table. (The sampling *design* numbers —
`sampleSize`, `sampleSizeFormula`, `targetSampleSize` — remain properties of the
collection activity / dataset, not of the sample object.)

## Known deferrals

- **`nCube` dimensional data** and the other 83 additions — see the mapping doc.
- **Coded variables** (`<var><catgry>` inline code lists) are not yet emitted as
  CDIF / DDI-CDI code lists — the same deferral as the 1.2.2 converter.

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

## Schema availability (a caution)

Getting the official XSDs to verify these mappings was uneven, and worth flagging
for anyone reproducing the comparison:

- **DDI Codebook 2.5** — `codebook.xsd` is publicly downloadable from the DDI
  Alliance and self-contained (apart from `xml`/`xhtml`/`dcterms` imports); a copy
  also ships locally under `ddi-toolkit/specifications/codebook_2.5/`.
- **DDI 1.2.2 (ICPSR)** — the canonical
  `http://www.icpsr.umich.edu/DDI/Version1-2-2.xsd` is **not reliably
  accessible**: the host answers HTTP 403 behind a Cloudflare challenge, and the
  schema is **not** in the DDI Alliance GitHub repos (which cover the 2.x line
  only). The copy used for the diff had to be sourced from a **third-party
  mirror** bundled with the CESSDA Metadata Validator
  ([`cessda/cessda.cmv.console`](https://github.com/cessda/cessda.cmv.console),
  `src/main/resources/schemas/nesstar/Version1-2-2.xsd`).
