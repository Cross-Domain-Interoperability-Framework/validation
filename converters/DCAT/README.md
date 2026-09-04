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

## Property mapping

The mappings are in [`../mappings/dcat-to-cdif.sssom.tsv`](../mappings/dcat-to-cdif.sssom.tsv),
and the converter **reads** that table rather than restating it, so the two
cannot drift apart. It covers every property the DCAT specification defines --
the union of the editor's draft and the RDF vocabulary, which disagree -- plus
every property found in `dcatExamplesOK`.

Source IRIs that are not the IRI the publisher meant are rewritten first,
through [`../mappings/dcat-aliases.sssom.tsv`](../mappings/dcat-aliases.sssom.tsv).
Most come from official context documents rather than careless records: the
Project Open Data v1.1 context sets `"@vocab": "dcat#"`, so every term it does
not itself define expands into the DCAT namespace.

Two columns beyond stock SSSOM carry the work: `subject_class`, because DCAT is
a graph and `dcterms:title` means one thing on a Dataset and another on a
Distribution; and `transform`, naming the shaper to apply. Both are documented
in [`../mappings/dcat-to-cdif.sssom.yml`](../mappings/dcat-to-cdif.sssom.yml).

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

- `@context` declaring `schema`, `dcterms`, `dcat`, `prov` prefixes
- `@type: ["schema:Dataset"]`
- `schema:` prefixed property names for all mapped properties
- `schema:subjectOf` with `dcat:CatalogRecord`, `dcterms:conformsTo` (core/1.0 and/or discovery/1.0), and documentation of all mappings applied
- Unmapped DCAT properties preserved with their original prefixes

The profile (`core` or `discovery`) is auto-detected based on whether the record has spatial or temporal coverage. Records with `dcterms:spatial` or `dcterms:temporal` get `discovery/1.0` conformance; others get `core/1.0` only.

## Requirements

- Python 3.8+
- `pyyaml` (for catalog parsing)
- `jsonschema` (optional, for `--validate`)

## Known Limitations

- `dcat:contactPoint` with vcard properties is mapped to `schema:provider` (closest schema.org equivalent); the vcard structure is simplified to name + email
- Spatial coverage conversion supports `dcat:bbox` (WKT) and named places but not all geometry types
- Temporal coverage assumes `dcat:startDate`/`dcat:endDate` pattern; complex temporal extents may need manual review
- Nested catalog structures (catalog-of-catalogs) are traversed recursively to find all `dcat:Dataset` nodes at any depth
