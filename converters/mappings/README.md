# Converter mappings (SSSOM)

The property-level mappings each converter applies, expressed as
[SSSOM](https://mapping-commons.github.io/sssom/) (Simple Standard for Sharing
Ontological Mappings) mapping sets — one per source→target direction. Each file
is a standard SSSOM **single-file TSV**: a YAML metadata block as `#`-prefixed
header lines (mapping-set id/title, license, provider, `mapping_tool`,
`curie_map`, …) followed by a tab-separated table.

| File | Direction | Converter | Mappings |
|------|-----------|-----------|----------|
| [`cdif-to-soso.sssom.tsv`](cdif-to-soso.sssom.tsv) | CDIF → SOSO | `soso/ConvertToSOSO.py` | 17 |
| [`soso-to-cdif.sssom.tsv`](soso-to-cdif.sssom.tsv) | SOSO → CDIF | `soso/ConvertFromSOSO.py` | 14 |
| [`cdif-to-croissant.sssom.tsv`](cdif-to-croissant.sssom.tsv) | CDIF → Croissant | `croissant/ConvertToCroissant.py` | 23 |
| [`croissant-to-cdif.sssom.tsv`](croissant-to-cdif.sssom.tsv) | Croissant → CDIF | `croissant/ConvertFromCroissant.py` | 16 |
| [`dcat-to-cdif.sssom.tsv`](dcat-to-cdif.sssom.tsv) | DCAT → CDIF | `DCAT/dcat_to_cdif.py` | 20 |
| [`ddi-to-cdif.sssom.tsv`](ddi-to-cdif.sssom.tsv) | DDI Codebook 2.5 → CDIF | `DDI/ddi_to_cdif.py` | 23 |

## Columns

`subject_id` / `subject_label` (the source term), `predicate_id`, `object_id` /
`object_label` (the target term), `mapping_justification`, and a `comment`
carrying the per-mapping transform note.

## Conventions

- **Predicates** — `skos:exactMatch` for an equivalent term (typically a same
  schema.org term in a different serialization); `skos:closeMatch` for a
  structural or typed remap or a slight obligation/semantics difference;
  `skos:narrowMatch` where the target is more specific than the source (e.g. a
  physical-mapping column source).
- **`mapping_justification`** — `semapv:ManualMappingCuration` throughout: the
  mappings are **hand-authored** from each converter's mapping documentation and
  code, not machine-extracted.
- **CDIF and SOSO share the schema.org namespace**, so many `cdif↔soso` rows are
  `schema:X → schema:X` (an identity `exactMatch`); the mapping is real but its
  substance is in the `comment` (prefix stripped/added, `@vocab` vs prefixed,
  `@list` ordering) and in the mapping-set direction. Croissant uses the
  `https://schema.org/` (`sc:`) serialization; CDIF uses `http://schema.org/`
  (`schema:`) — treated as `exactMatch` of the same term.
- **`ddi:` is a minted convention** — DDI Codebook 2.5 has no CURIEs for its
  elements, so subject ids are XPath-style element paths under a `ddi:` prefix
  (e.g. `ddi:stdyDscr.citation.titlStmt.titl`; `@name` / `@intrvl` denote XML
  attributes). The underlying element namespace is `ddi:codebook:2_5`.
- **Structural transforms** the converter performs that are *not* term-to-term
  mappings — dropping/adding the `schema:subjectOf` catalog record, rewriting the
  `@context`, deriving `conformsTo` from content, emitting placeholders — have no
  TSV row; they are listed in each file's `# comment:` header block.

## Using them

The files open directly in any spreadsheet or `pandas.read_csv(sep="\t",
comment="#")`. With the SSSOM toolkit (`pip install sssom`) you can validate,
convert to RDF/OWL, or diff them:

```bash
sssom validate cdif-to-soso.sssom.tsv
sssom convert  cdif-to-soso.sssom.tsv -o cdif-to-soso.ttl
```

## Maintenance

These sets are curated by hand and reflect the converters at authoring time
(2026-08). When a converter's mappings change, update the corresponding
`.sssom.tsv`. The authoritative narrative sources are each converter's mapping
doc — `../soso/README.md` and
`../../../doc-corediscovery/documents/CDIF-Discovery-vs-SOSO-comparison.md`
(SOSO), `../croissant/CDIFtoCroissant.md` / `CroissantToCDIF.md`,
`../DCAT/README.md`, and the `DDI/ddi_to_cdif.py` source.
