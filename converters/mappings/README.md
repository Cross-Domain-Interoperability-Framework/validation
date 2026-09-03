# Converter mappings (SSSOM)

The property-level mappings each converter applies, expressed as
[SSSOM](https://mapping-commons.github.io/sssom/) (Simple Standard for Sharing
Ontological Mappings) mapping sets — one per source→target direction.

SSSOM defines two ways to carry the mapping-set metadata (id/title, license,
provider, `mapping_tool`, `curie_map`, …), and both are used here:

- **Embedded** (single-file) — the five converter sets (`cdif↔soso`,
  `cdif↔croissant`, `dcat→cdif`) are standard SSSOM single-file TSVs: a YAML
  metadata block as `#`-prefixed header lines followed by the tab-separated table.
- **External** (sidecar pair) — the three DDI worksheets follow the
  [MIDS](https://github.com/tdwg/mids/tree/main/source/mappings) convention: a
  bare `<name>.sssom.tsv` (column header + rows only) paired with a
  `<name>.sssom.yml` sidecar holding the metadata as plain YAML. The sidecar is
  valid standalone SSSOM YAML the toolkit can read directly, and the TSV opens in
  a spreadsheet with no `#` rows to skip. `sync_ddi_mappings.py` keeps the pair in
  step (regenerating the sidecar's `curie_map` from the prefixes the table uses),
  and migrates a worksheet still carrying an embedded header on first run.

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

## Why not just generate the converters from SSSOM?

A natural question: if the mappings are captured as SSSOM, why are the converters
hand-written Python rather than *generated from* (or *driven by*) these tables?
Because **an SSSOM table is a flat list of term-to-term correspondences** —
`subject_id → predicate → object_id`, plus (via our extension) a JSONPath for
where the value lands. That is exactly the right shape for the **simple 1:1
property renames** (`schema:name` here → `schema:name` there, `dct:title` →
`schema:name`, an XDI header key → a glossary concept). It is *not* expressive
enough for the structural work these conversions actually require:

- **reference resolution** — DDI-CDI is a flat graph of objects linked by
  `ddiReference`; the converter must index every object and walk those links to
  reassemble a tree;
- **reified associations** — `X_has_Y` / `X_isDefinedBy_Y` objects that must be
  traversed and collapsed into a nested CDIF property;
- **value-domain / structure reshaping** — turning a verbose DDI-CDI value domain
  + `CodeList`/`Code`/`Category` into a `skos:ConceptScheme`, or a
  `WideDataStructure` + components into `cdif:isStructuredBy`;
- **synthesis with no source term** — the `schema:subjectOf` catalog record,
  `dcterms:conformsTo` derived from content, `@context` rewrites, nil placeholders.

None of those are term-to-term rows, so a purely declarative mapping either can't
express them or needs a Turing-complete mapping language bolted on. The realistic
pattern is therefore a **hybrid**: SSSOM captures (and can drive) the flat 1:1
renames, while hand-written code does the graph traversal and structural
assembly. The SSSOM set stays the human-readable, curatable, tool-checkable record
of the *term alignments* (each row carrying its predicate and justification), and
the structural transforms are recorded in each set's `comment:` metadata (the
`.yml` sidecar for the DDI sets, the `#` header block for the others) instead
of as rows. Updating a table documents an intended change; it does **not**
regenerate a converter — the code is edited in step, and the table updated to match.

**Precedent — the XAS → CDIF profile work.** That effort built the same transform
two ways (see [`../../../XAS-CDIF/release/xasToCdifWorkflows.md`](../../../XAS-CDIF/release/xasToCdifWorkflows.md)).
The original design was a **declarative RML mapping executed by a Java tool**
(`rmlmapper`), packaged as an HTTP service
([`cdif-xas`](https://github.com/smrgeoinfo/cdif-xas)). A later **Python emitter
keyed off SSSOM crosswalks** ([`cdifnexmetadata`](https://github.com/usgin/cdifnexmetadata))
turned out to be **easier to build and maintain**: a new input format becomes a
*parser* rather than a new pipeline, and a new technique a *crosswalk edit* rather
than a code change, while the SSSOM crosswalk still "licenses" each mapping (its
predicate and confidence travel with the value). The converters here follow that
same hybrid philosophy — SSSOM for the alignments, Python for the structure.

## Columns

`subject_id` / `subject_label` (the source term), `predicate_id`, `object_id` /
`object_label` (the target term), `object_json_path`, `mapping_justification`,
a `comment` carrying the per-mapping transform note, and `author_id` /
`reviewer_id` (who authored / reviewed the mapping).

### `mapping_justification` vs `author_id` / `reviewer_id`

These answer different questions and should not be conflated:

- **`mapping_justification`** is a [SEMAPV](https://mapping-commons.github.io/semapv/)
  term describing *how* the correspondence was determined, **not who made it**.
  `semapv:ManualMappingCuration` = "established by a curator through manual
  inspection" — the correct value for a hand-assigned mapping (its siblings are
  `semapv:LexicalMatching`, `semapv:LogicalReasoning`, `semapv:UnspecifiedMatching`, …).
- **`author_id`** / **`reviewer_id`** record *who* authored and reviewed the
  mapping — the SSSOM provenance slots for attribution. This is where a
  human-curated mapping is distinguished from a tool-suggested one.

**Convention here:** every current mapping is attributed to the human curator
(`author_id` = `reviewer_id` = **`https://w3id.org/cdif/agents/SMR`**, a
placeholder). A tool-suggested mapping awaiting review would carry the tool as
`author_id` (e.g. `https://w3id.org/cdif/agents/claude`) with an empty
`reviewer_id` until a curator vets it and stamps their own id. Unmapped candidate
rows (no `object_id`) leave both empty — no mapping has been authored yet.

Replace the `SMR` placeholder with the curator's ORCID once available, e.g.:

```bash
sed -i 's#https://w3id.org/cdif/agents/SMR#https://orcid.org/0000-0000-0000-0000#g' \
    converters/mappings/ddi*-to-cdif.sssom.tsv
```

`object_json_path` is a **non-standard extension column** (declared in each set's
`extension_definitions` metadata — the `.yml` sidecar for the DDI sets): a JSONPath *locator* for where the
target term's value lands in the target JSON-LD document — e.g. `$.schema:name`
(dataset root), `$.schema:variableMeasured[*].cdif:role` (a variable item),
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
  TSV row; they are listed in each set's `comment:` metadata (the `.yml` sidecar
  for the DDI sets, the `#` header block for the others).

- **Targets outside the CDIF profiles are deliberate, and JSON-LD is open-world.**
  A mapping target need not be a property some CDIF profile declares: the profiles
  constrain what they define, they do not close the record, and no CDIF schema seals
  `additionalProperties` at these levels. Several rows map to real vocabulary terms
  that carry information the profiles have no slot for, and converted records
  therefore carry them:

  | property | from | appears in |
  |---|---|---|
  | `schema:isPartOf` | `ddi-common`, `ddi25` | the series a study belongs to |
  | `bios:computationalTool` | `ddi-common` | analysis software named in the method description |
  | `schema:dateCreated` | `ddi-common`, `ddi25` | study creation date, distinct from `datePublished` |
  | `dcterms:bibliographicCitation` | `ddi-common`, `ddi25` | the citation string the producer supplies |
  | `schema:copyrightNotice` | `ddi-common`, `ddi25` | rights text that is not a licence URI |

  All are bound in the emitted `@context` (`bios:` → `https://bioschemas.org/`), so
  they expand to real IRIs rather than dangling CURIEs. A validator will not object
  to them; a *profile-driven viewer* may mark them as outside the declared profiles,
  which is a statement about profile coverage, not a defect.

  This is distinct from a **wrong-prefix** target, which is a defect: `cdi:role`
  where the blocks declare `cdif:role`, or `cdi:hasPhysicalMapping` where only
  `cdif:hasPhysicalMapping` exists, expand to IRIs that denote nothing. When adding
  a row, check the local name against the building blocks under both prefixes
  before choosing one.

## Using them

The files open directly in any spreadsheet or `pandas.read_csv(sep="\t",
comment="#")` (harmless for the DDI tables — they carry no `#` rows). With the
SSSOM toolkit (`pip install sssom`) you can validate, convert to RDF/OWL, or diff
them:

```bash
# embedded (single-file) sets — metadata read from the '#' header
sssom validate cdif-to-soso.sssom.tsv
sssom convert  cdif-to-soso.sssom.tsv -o cdif-to-soso.ttl

# external (DDI) sets — point the toolkit at the .yml sidecar as the metadata file
sssom parse ddi25-to-cdif.sssom.tsv -m ddi25-to-cdif.sssom.yml -o ddi25-to-cdif.parsed.tsv
```

## Maintenance

These sets are curated by hand and reflect the converters at authoring time
(2026-08). When a converter's mappings change, update the corresponding
`.sssom.tsv`. The authoritative narrative sources are each converter's mapping
doc — `../soso/README.md` and
`../../../doc-corediscovery/documents/CDIF-Discovery-vs-SOSO-comparison.md`
(SOSO), `../croissant/CDIFtoCroissant.md` / `CroissantToCDIF.md`,
`../DCAT/README.md`, and the `DDI/ddi_to_cdif.py` source.
