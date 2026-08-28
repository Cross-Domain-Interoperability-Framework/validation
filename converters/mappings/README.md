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
| [`ddi-common-to-cdif.sssom.tsv`](ddi-common-to-cdif.sssom.tsv) | DDI Codebook (2.5 ∩ 1.2.2 common core) → CDIF | all three DDI converters | 202 (26 mapped) |
| [`ddi25-to-cdif.sssom.tsv`](ddi25-to-cdif.sssom.tsv) | DDI Codebook 2.5 *extras* → CDIF | `DDI/ddi_to_cdif.py`, `DDICodebook/ddi25_to_cdif.py` | 137 (10 mapped) |
| [`ddi122-to-cdif.sssom.tsv`](ddi122-to-cdif.sssom.tsv) | DDI Codebook 1.2.2 *extras* → CDIF | `DDI/ddi122_to_cdif.py` | 7 (0 mapped) |

Sets are keyed by **source vocabulary → target**, so the two DDI 2.5 converters
(the Harvard-Dataverse `ddi_to_cdif.py` and the source-agnostic
`DDICodebook/ddi25_to_cdif.py`) share one set.

### The three DDI sets are comprehensive *worksheets*, factored common + version-specific

Unlike the five converter-mapping sets above (which list only the property
correspondences a converter applies), the DDI sets enumerate **every
literal-valued element** the DDI Codebook XML Schema defines under the four main
description branches (`stdyDscr`, `fileDscr`, `dataDscr`, `docDscr`) — whether or
not CDIF has a target for it. Rows that *do* map carry a `predicate_id` +
`object_id` + `object_json_path`; rows that **don't** are left with those cells
blank and a `comment` of `unmapped literal field (no CDIF target) - for review`,
so the full source field inventory is visible for crosswalk review. The field
list is derived directly from the schemas (`codebook.xsd` for 2.5;
ICPSR `Version1-2-2.xsd` for 1.2.2).

**DDI 1.2.2 is almost a strict subset of 2.5**: of its 206 literal fields, 199
share the identical XPath with 2.5; only 7 (deeper self-recursion of
`othId`/`catgry`) are unique to it, while 136 fields (chiefly the `nCube`
aggregate-cube branch) are unique to 2.5. So the shared **199** fields are
factored once into `ddi-common-to-cdif.sssom.tsv` (subject prefix **`ddicb:`**,
version-neutral), and each version set holds only that version's extras
(prefix **`ddi:`** for 2.5, **`ddi122:`** for 1.2.2). To reconstruct a complete
single-version crosswalk, compose the common set with the version extras:

```bash
sssom merge ddi-common-to-cdif.sssom.tsv ddi25-to-cdif.sssom.tsv   # full DDI 2.5
sssom merge ddi-common-to-cdif.sssom.tsv ddi122-to-cdif.sssom.tsv  # full DDI 1.2.2
```

(`sssom merge` unions the rows and `curie_map`s; the sets carry no conflicting
paths. Since these are plain TSVs, `pandas.concat` of the two tables read with
`comment="#"` is an equivalent fallback if the toolkit isn't installed.)

Universal qualifier attributes (`abbr`/`affiliation`/`role`/`URI`/date on many
elements, and the `GLOBALS` attribute group) are **omitted** to keep the
worksheets legible — the handful of data-bearing attributes that *do* map (e.g.
`var/@name`, `var/@intrvl` via `varFormat/@type`) are included explicitly.
Because the unmapped rows have empty `predicate_id`/`object_id`, `sssom validate`
will flag them — that is expected for these worksheets, not an error.

## Columns

`subject_id` / `subject_label` (the source term), `predicate_id`, `object_id` /
`object_label` (the target term), `object_json_path`, `mapping_justification`,
and a `comment` carrying the per-mapping transform note.

`object_json_path` is a **non-standard extension column** (declared in each
file's `extension_definitions` header): a JSONPath *locator* for where the
target term's value lands in the target JSON-LD document — e.g. `$.schema:name`
(dataset root), `$.schema:variableMeasured[*].cdi:role` (a variable item),
`$.schema:distribution[*].schema:contentUrl` (a distribution item),
`$.schema:subjectOf.dcterms:conformsTo` (the catalog record). It complements
`object_id` (which stays the resolvable term IRI so the file remains valid SSSOM)
by showing *placement*, parallel to the XPath/JSONPath in `subject_id`. It is
left blank where the target is a separate node/document (e.g. a code-list
`skos:ConceptScheme`) rather than a location in the dataset tree.

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
- **`ddicb:` / `ddi:` / `ddi122:` are minted conventions** — DDI Codebook has no
  CURIEs for its elements, so subject ids are XPath-style element paths under a
  minted prefix (e.g. `ddicb:stdyDscr.citation.titlStmt.titl`; `@name` denotes an
  XML attribute, and `varFormat@type` an attribute on a nested element).
  `ddicb:` is the version-neutral prefix for elements common to both versions;
  `ddi:` marks elements specific to DDI Codebook 2.5, `ddi122:` those specific to
  1.2.2. All three resolve under `https://ddialliance.org/Specification/DDI-Codebook/…`.
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
