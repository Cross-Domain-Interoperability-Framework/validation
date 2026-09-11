# DCAT to CDIF Conversion

Tools for converting [DCAT](https://www.w3.org/TR/vocab-dcat-3/) metadata to CDIF-conformant [schema.org](http://schema.org/) JSON-LD.

## Background

Many institutional and government data catalogs publish metadata using the W3C DCAT vocabulary (often serialized as JSON-LD with Dublin Core and FOAF terms). CDIF uses schema.org as its primary vocabulary. The property mappings between DCAT and schema.org are documented in the [CDIF DCAT implementation guide](https://cross-domain-interoperability-framework.github.io/cdifbook/metadata/dcat/), which draws on the W3C DXWG group's alignment work.

This converter enables DCAT catalog records to be consumed by CDIF-aware tools by translating DCAT/Dublin Core properties to their schema.org equivalents while preserving any unmapped properties (open-world assumption).

## Example corpora

| Directory | What |
|---|---|
| [`dcat-examples/`](dcat-examples/) | 783 upstream files — DCAT-AP, its extensions and national derivatives, DCAT-US 3.0 and 1.1/POD, CKAN fixtures. Mixed purpose: catalogs, data services, vocabularies, SHACL shapes, fragments. |
| [`dcatExamplesOK/`](dcatExamplesOK/) | The 238 of those that actually **describe a `dcat:Dataset`**, selected structurally (rdflib for RDF; POD JSON matched on its `dataset` array). |
| [`cdifOK/`](cdifOK/) | 239 CDIF records converted from them by [`build_corpus.py`](build_corpus.py). 90 conformant, 149 named `-frag`. |

Each has a `README.md` and an `INDEX.json` recording provenance.

**`-frag`** marks a record whose content does not meet CDIF core. It declares **no**
`dcterms:conformsTo` rather than claiming a profile it does not satisfy. That is most of
the corpus, and it is a property of the sources: many DCAT-AP specification examples are
single-feature fragments carrying a title, a description and one extension property.

**Merging.** The corpus ships many examples in more than one serialization, and 45 of the
78 such pairs are **not the same graph** — the `.ttl` and `.jsonld` carry different
triples upstream. All serializations of one logical example are parsed into a single
graph and converted once, so the converter sees the union.

## What the converter does when the source is silent

CDIF requires things DCAT does not. Rather than omit them — silence being
indistinguishable from an oversight — the record says the value is knowably absent:

| Missing | Emitted |
|---|---|
| no landing page **and** no distribution; a `DataDownload` with no access URL | `schema:url` / `schema:contentUrl` = the OGC `nil:missing` URI, **as a string** (both are declared `sh:datatype xsd:string`) |
| no licence | `schema:license` = the same URI |
| no usable `dcterms:modified` | the conversion timestamp |

Dates are **normalized**, not merely defaulted: the CDIF pattern accepts seconds
precision and no fractional part, so `2024-05-08T04:11:24.309486` is trimmed to
`2024-05-08T04:11:24` rather than discarded.

`dcterms:conformsTo` comes from `detect_conformance` alone. When detection finds nothing,
the declaration is **removed** rather than falling back to a built-in claim — the
fallback exists only for `--static-conformance` and for when `detect_conformance` cannot
be imported.

Passed-through properties (open world, deliberately preserved) get a **prefix declared**
in the record's `@context`. An absolute IRI as a JSON-LD key does not frame — the part
before the first colon is read as a prefix — and a CURIE whose prefix the record never
declares fails the same way, in `@type` and `@id` positions as readily as in keys.

## The mapping process

### The SSSOM table is the source of truth

The crosswalk lives in [`../mappings/dcat-to-cdif.sssom.tsv`](../mappings/dcat-to-cdif.sssom.tsv)
(an [SSSOM](https://mapping-commons.github.io/sssom/) mapping set), and the
converter **reads** it at import rather than restating it in code, so the table
and the behaviour cannot drift apart. Its metadata header is the sidecar
[`dcat-to-cdif.sssom.yml`](../mappings/dcat-to-cdif.sssom.yml) (external-metadata
/ MIDS layout: a bare `.tsv` of rows + a `.yml` of `curie_map`, provenance, and
the `transform` vocabulary).

Coverage is deliberately exhaustive: **every property the DCAT specification
defines** — the union of the editor's draft (`w3c.github.io/dxwg/dcat/`) and the
RDF vocabulary (`w3.org/ns/dcat.ttl`), which disagree — **plus every property
observed in `dcatExamplesOK`**. A row that has no CDIF target is kept anyway
(blank object, `transform=passthrough`) so the full source inventory is visible
for review; unmapped values are still preserved in the output (open world).

### Two extension columns beyond stock SSSOM carry the work

- **`subject_class`** — DCAT is a graph, not a tree, so the same property means
  different things by class: `dcterms:title` on a `dcat:Dataset` is the record's
  `schema:name`; on a `dcat:Distribution` it names the distribution.
- **`transform`** — names the *shaper* the converter applies to the value
  (empty = a plain copy). Plus **`object_json_path`**, the JSONPath where the
  value lands (`$.schema:name`, `$.schema:provider.schema:address.*`, …).

The `transform` vocabulary (authoritatively described in the `.yml` `comment:`):
`text` / `iri` / `idref` / `date` / `langcode` / `list` / `bytes` /
`mediatype` (scalar coercions); `agent`, `vcard`, `place`, `bbox`, `period`,
`distribution`, `service`, `generatedby`, `attribution`, `checksum`,
`measurement`, `concept`, `theme`, `relatedlink`, `identifier`, `describe`,
`prefixedtext` (structural shapers); and the sentinels `passthrough` (copy
verbatim, open world), `catalog-walk` (descend, don't map) and `<name>-part`
(consumed by the shaper of that name on the parent — e.g. `vcard-part`,
`period-part`). Row order is precedence: for a scalar target the first row to
fill it wins (how "`dcterms:identifier`, else `adms:identifier`" is expressed
without conditional code); array targets accumulate.

### Source IRIs are normalized first

Variant/typo IRIs are rewritten before mapping, through
[`../mappings/dcat-aliases.sssom.tsv`](../mappings/dcat-aliases.sssom.tsv). Most
come from official context documents, not careless records: the Project Open
Data v1.1 context sets `"@vocab": "dcat#"`, so every term it doesn't define
expands into the DCAT namespace (`dcat:title` → `dcterms:title`); DCAT-US 3.0
uses a transposed host (`data.resources.gov` vs `resources.data.gov`); and a
handful are plain case/namespace slips (`downloadUrl`, `dcterms:mediaType`).

### Checked against the W3C schema.org alignment

The schema.org targets are cross-checked against **DCAT 3 Appendix B (Alignment
with Schema.org)**, cited via `see_also` in the sidecar. Most match exactly;
where CDIF deliberately diverges it is documented in the row/`.yml` comments —
the relation family (`dcterms:relation`, versioning, `references`, …) routes to
`schema:relatedLink` with a `schema:linkRelationship` (preserving the relation
semantics and generalizing the target to any `schema:CreativeWork`) rather than
W3C's `schema:isRelatedTo`; `dcat:contactPoint` → `schema:provider`;
`prov:wasGeneratedBy` is kept (DCAT-native) rather than inverted to
`schema:result`; `dcat:endpointURL` lands in a WebAPI `schema:potentialAction`;
and `dcterms:accrualPeriodicity` stays a passthrough (`schema:repeatFrequency`
is a poor semantic fit).

## How the converter works

[`dcat_to_cdif.py`](dcat_to_cdif.py) is a table-driven pipeline:

1. **At import** — `_load_tables()` reads the two SSSOM files into `RULES` (the
   mapping rows, in table order) and `ALIASES` (the IRI-normalization map).
2. **`find_datasets()`** walks the input JSON-LD to any depth (handling
   catalog-of-catalogs) and collects every `dcat:Dataset` node.
3. **`convert_dcat_to_cdif(ds, …, graph)`** converts one dataset:
   1. `_apply_aliases` rewrites variant source IRIs (see above).
   2. `_resolve` replaces `{@id}` references against the whole document, so a
      shaper sees the node it names — real DCAT barely nests, and rdflib merges
      hoist nodes to the top level, so values arrive as references.
   3. **`_apply_table`** runs the root-level rows in table order: each row's
      `transform` shaper produces a value that `_place` writes at the row's
      `object_id`, respecting `_TARGET_ARITY` (which targets are arrays that
      accumulate vs. single values where the first row wins).
   4. **CDIF-required, DCAT-silent** fields are then filled — `schema:name`
      falls back to `"Untitled"`, `schema:dateModified` to `datePublished` then
      to conversion time, `schema:url`/`contentUrl`/`license` to the OGC
      `nil:missing` URI — and dates are normalized to the CDIF pattern.
   5. The `schema:subjectOf` `dcat:CatalogRecord` is added (CDIF's own record
      about the dataset; its `dcterms:conformsTo` is derived, not copied).
   6. **`_apply_nested`** runs the deep-path rows *after* the catalog record
      exists (e.g. `$.schema:provider.schema:address.*`), building only the
      containers it can build unambiguously (`_NESTABLE_PARENTS`).
   7. **Unmapped** source properties pass through verbatim, each with its prefix
      declared in `@context` (an undeclared CURIE or absolute-IRI key won't
      frame — in key, `@type`, or `@id` position).
   8. **`detect_conformance` / `apply_conformance`** derive `dcterms:conformsTo`
      from the record's *content* (`--static-conformance` opts out; a stub is
      used only when `detect_conformance` can't be imported).

Shapers worth calling out: **`agent`** (FOAF → `schema:Person`/`Organization`),
**`vcard`** (a contact → a `schema:provider` Organization/Person carrying a
`schema:contactPoint` and a `schema:PostalAddress`), **`place`**/**`bbox`**
(spatial → `schema:Place`/GeoShape), **`period`** (temporal → an ISO 8601
interval, reading `dcat:`/`schema:startDate`+`endDate` or `dcterms:start`+`end`),
**`service`** (a `dcat:DataService` distribution → a `schema:WebAPI` whose
endpoint becomes a `schema:potentialAction` EntryPoint), **`generatedby`**
(`prov:wasGeneratedBy` → a `cdifProvActivity`: dual-typed
`["schema:Action","prov:Activity"]`, mapping the PROV terms to their schema.org
equivalents and populating the shape-required `prov:used` from the activity's
inputs; an activity with no usable input stays a plain `prov:Activity`), and
**`relatedlink`** / **`attribution`** (the relation family and
`prov:qualifiedAttribution` → role-tagged links / contributors).

### `build_corpus.py` — the regression harness

[`build_corpus.py`](build_corpus.py) rebuilds `cdifOK/` from `dcatExamplesOK/`:
it groups sources by directory + stem, **merges every serialization of one
logical example into a single rdflib graph** (many `.ttl`/`.jsonld` pairs differ
upstream), and converts once so the converter sees the union. On every run it
verifies, and reports zero for both: **no source predicate reaches no record**
(coverage — nothing silently dropped) and **every conformant record validates**
against its declared CDIF profile. `--check` verifies without writing; plain
run regenerates the corpus. Run it after any change to the table or the code.

## Usage

### List datasets in a DCAT catalog

```bash
python DCAT/dcat_to_cdif.py catalog.jsonld --list
```

### Convert all datasets

```bash
python DCAT/dcat_to_cdif.py catalog.jsonld \
  --output ./examples \
  --catalog-name "My Data Catalog" \
  --catalog-url "https://example.org/catalog"
```

### Convert specific records by index

```bash
python DCAT/dcat_to_cdif.py catalog.jsonld \
  --output ./examples \
  --select 0,3,5,10
```

### Convert and validate against CDIF schema

```bash
python DCAT/dcat_to_cdif.py catalog.jsonld \
  --output ./examples \
  --validate --verbose
```

### Example: PSDI Resource Catalogue

The [PSDI](https://www.psdi.ac.uk/) (Physical Sciences Data Infrastructure) publishes a DCAT catalog at `https://metadata.psdi.ac.uk/psdi-dcat.jsonld` with 41 dataset records describing materials science databases (Cambridge Structural Database, AFLOW, Chemotion, OPTIMADE providers, etc.).

```bash
# Download the catalog
curl -o psdi-dcat.jsonld https://metadata.psdi.ac.uk/psdi-dcat.jsonld

# List available datasets
python DCAT/dcat_to_cdif.py psdi-dcat.jsonld --list

# Convert 5 records to CDIF Core
python DCAT/dcat_to_cdif.py psdi-dcat.jsonld \
  --output ./examples \
  --select 0,1,3,5,10 \
  --catalog-name "PSDI Resource Catalogue" \
  --catalog-url "https://metadata.psdi.ac.uk/" \
  --validate
```

## Output Format

Each converted record is a CDIF-conformant JSON-LD file with:

- `@context` declaring `schema`, `dcterms`, `dcat`, `prov` and whatever other
  prefixes the mapped/passed-through values need
- `@type: ["schema:Dataset"]`
- `schema:` (and `prov:`/`dcterms:`) property names for all mapped properties
- a `schema:subjectOf` `dcat:CatalogRecord` carrying `dcterms:conformsTo`
- unmapped DCAT properties preserved verbatim with their original prefixes

The `dcterms:conformsTo` set is **derived from the record's content** by
`detect_conformance` — e.g. `core/1.1` plus `discovery/1.1` when the record has
spatial/temporal coverage or other discovery-level content, and further profiles
(`data_description`, `provenance`, …) when the content warrants. Detection finding
nothing means the declaration is **omitted**, not defaulted (the built-in claim
applies only under `--static-conformance`, or when `detect_conformance` cannot be
imported). See [`../../detect_conformance.py`](../../detect_conformance.py).

## Requirements

- Python 3.8+
- `rdflib` — to parse non-JSON-LD serializations (`.ttl`/`.rdf`/`.xml`) and to
  merge them in `build_corpus.py`. `dcat_to_cdif.py` itself ingests JSON-LD.
- `jsonschema` — optional, for `--validate` and the `build_corpus.py` schema check.
- `detect_conformance.py` (repo root) — imported for content-derived `conformsTo`.

## Known limitations

- `dcat:contactPoint` maps to `schema:provider` (CDIF's closest slot); the vcard
  contact is shaped to a `schema:Person`/`Organization` with a
  `schema:contactPoint` (email/url/telephone) and a `schema:PostalAddress`.
  This diverges from W3C's direct `schema:contactPoint` — a deliberate choice.
- Spatial coverage supports `dcat:bbox`, DCAT-US bounding-box coordinates and
  named places, but not every geometry type.
- Temporal coverage reads `dcat:`/`schema:startDate`+`endDate` and
  `dcterms:start`+`end`; unusual temporal extents may need review.
- Provenance: a `prov:wasGeneratedBy` activity is shaped into a `cdifProvActivity`
  only when it has a resource for the shape-required `prov:used` (a `prov:used`
  value or an input entity); an activity carrying only agent/time stays a plain
  `prov:Activity` reference rather than being forced (or fabricated) into one.
- Catalog-of-catalogs inputs are traversed recursively; every `dcat:Dataset` at
  any depth is found and converted.
