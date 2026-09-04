# DCAT examples that describe a dcat:Dataset

238 metadata records selected from [`../dcat-examples`](../dcat-examples), kept
because each one actually **describes a `dcat:Dataset`**. The parent directory
holds 783 files of mixed purpose — catalogs, data services, vocabularies, SHACL
shapes, fragments — which makes it awkward to draw dataset examples from.

`INDEX.json` lists every file with how many `dcat:Dataset` subjects it holds and
how it was detected.

| profile | files |
| --- | ---: |
| `10-dcat-us-3.0` | 101 |
| `01-dcat-ap` | 60 |
| `07-national-profiles` | 49 |
| `11-dcat-us-1.1-pod` | 9 |
| `05-mldcat-ap-3.1.0` | 8 |
| `03-mobilitydcat-ap-1.1.0` | 5 |
| `04-healthdcat-ap` | 4 |
| `02-geodcat-ap` | 2 |

The profile subdirectories are preserved. DCAT-AP and DCAT-US differ enough that
which profile an example came from is part of what makes it useful, and
flattening 238 files would lose that.

## How they were selected

The test is structural, not textual. A file mentioning the string
`dcat:Dataset` in a comment does not qualify; one that uses a different prefix
binding for the same IRI does.

- **RDF** (`.ttl`, `.rdf`, `.xml`, `.jsonld`) — parsed with rdflib, kept when
  some subject has `rdf:type dcat:Dataset`.
- **Project Open Data JSON** (`11-dcat-us-1.1-pod`) — not RDF. A POD catalog is
  a plain object with a `dataset` array whose entries carry
  `"@type": "dcat:Dataset"`. Parsing these as JSON-LD yields nothing, because
  the POD context is not embedded, so they are matched structurally instead.

Of the 768 candidate files: 238 qualified, 514 parsed cleanly but describe no
dataset, and 16 could not be parsed (malformed dates such as `01-01-1981`, an
`xsd:duration` of `1440.0`, a few invalid URIs).

Two sources contributed nothing, both checked rather than assumed:

- **`12-ckan-crosswalk`** — its `catalog.json` entries are properly shaped
  (title, identifier, distribution, landingPage, publisher) but carry **no
  `@type` at all**, so they describe datasets without declaring the class.
- **`_filtered-out`** — all 450 files were scanned, not skipped. None contains a
  `dcat:Dataset` subject, consistent with it holding vocabularies, shapes and
  catalog-only records.

## Provenance and licensing

These are verbatim copies. Per the upstream note in
[`../dcat-examples/_filtered-out/README.md`](../dcat-examples/_filtered-out/README.md),
the material is public-domain or openly licensed by its upstream — EUPL / CC-BY
for the SEMIC material, 17 USC §105 / CC0 for the US material, AGPL for the CKAN
fixtures. **Original licence files were not copied; check upstream before
redistributing.**
