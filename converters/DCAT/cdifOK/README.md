# CDIF records converted from the DCAT examples

239 CDIF JSON-LD records generated from [`../dcatExamplesOK`](../dcatExamplesOK)
by [`../build_corpus.py`](../build_corpus.py), which drives
[`../dcat_to_cdif.py`](../dcat_to_cdif.py) and mirrors that directory's profile
subdirectories. `INDEX.json` lists every record with the sources it came from
and whether it is a fragment.

```
157 logical examples -> 239 records
   79 merged from more than one serialization
   90 conformant  (core/1.1 + discovery/1.1)
  149 -frag       (content does not meet core)

  0 conformant records failing JSON Schema
  0 conformant records with a SHACL Violation
  0 source properties that reach no record
```

All three zeroes are checked by the rebuild — see **Regenerating** below.

## `-frag`

A record is named `-frag` when its content does not meet CDIF core, and it
declares **no** `dcterms:conformsTo` at all rather than claiming a profile it
does not satisfy.

That is most of the corpus, and it is a property of the sources rather than of
the conversion: many DCAT-AP specification examples are single-feature
fragments. The HVD example, in full, is a `dct:title`, a `dct:description`, an
`applicableLegislation` and an `hvdCategory` — no identifier, distribution,
publisher, licence or modification date. No converter can invent those.

The fragments are still useful as conversion examples; they are simply not
conformant CDIF records and should not be mistaken for them.

## Merging

The corpus ships many examples in more than one serialization, and **48 of the
79 such groups are not the same graph** — the `.ttl` and the `.jsonld` carry
different triples upstream. Converting each separately produced near-duplicate
records, each missing whatever the other had.

So every serialization of one logical example (same directory, same stem) is
parsed into a single RDF graph and converted once. The union is what reaches the
converter, and `INDEX.json` records how many sources each record was merged
from.

## Node references

Real DCAT barely nests. A dataset says

```json
"dcat:distribution": { "@id": "https://…/dataset/1T2p3o4B-dist-SHP" }
```

and the distribution is a **sibling** node — always so after an RDF round-trip,
which hoists every node to the top level. The converter is handed an index of
the whole document and resolves these before mapping. Without it, 123 of these
records lost their distributions, and the DCAT-US bounding box and
`adms:contactPoint` shapers could never fire at all.

A reference whose node is not in the document is kept as a `DataDownload`
carrying that identifier: the source asserts the distribution exists, and
saying nothing would assert that it does not.

## Where the source is silent

The record says so rather than staying quiet:

- no landing page and no distribution, or a `DataDownload` with no access URL —
  `schema:url` / `schema:contentUrl` carry the OGC `nil:missing` URI, as a
  string: both properties are declared `sh:datatype xsd:string`;
- no licence — `schema:license` carries the same URI;
- an agent with an IRI and no name — `schema:name` carries the same URI. CDIF
  requires a name and DCAT routinely gives only an ORCID or a ROR;
- no usable `dcterms:modified` — the conversion timestamp, which is at least
  true of the serialization. Source dates carrying fractional seconds
  (`2024-05-08T04:11:24.309486`) are trimmed rather than discarded: the CDIF
  pattern accepts seconds precision and no more.

A record moving in or out of conformance changes its filename, so git shows it
as a delete plus an add rather than a modification.

## Known remaining issues

One source, `11-dcat-us-1.1-pod/real-world/missing-catalog.data.json`, cannot
be read at all: its `@context` names a relative IRI with no scheme
(`project-open-data.cio.gov/v1.1/schema`), so nothing can resolve it. One other
group parses but describes no `dcat:Dataset`.

## SHACL

All **90 conformant records are clean of SHACL Violations**. All 149 fragments
carry two, and both are what makes them fragments: no `dcterms:conformsTo` on
the catalog record, and no identifier for the documented resource.

Getting there fixed two things the shapes caught that JSON Schema did not:

- **20 records had a `@id` that was not an IRI** — an rdflib blank-node label,
  or (in two) the local filesystem path of whoever ran the build, because
  rdflib resolves a relative IRI against the file it is reading. Sources are
  now parsed with a stable `publicID`, and a dataset the source gives no
  identifier for is minted a reproducible one under that base rather than
  carrying a label that changes on every parse. Both defects predate this
  regeneration.
- **11 records claimed `schema:WebAPI` without meeting its shape**, which
  requires `schema:termsOfService` and at least one typed
  `schema:potentialAction`. A `dcat:accessService` is now the distribution's
  `potentialAction` — a `schema:SearchAction` whose `EntryPoint` carries a
  `urlTemplate`, which is both what the shape wants and what the property
  means — rather than a nested `WebAPI` that asserted a service and then
  failed to describe one.

Note the two `schema:EntryPoint` positions differ: an Action's target requires
`schema:urlTemplate`, a `relatedLink`'s requires `schema:url`.

The remaining output is **Warnings**, which are advisory and reflect the
sources: "At least one creator is recommended" (673), "Keywords are
recommended for discovery" (533), and a request for identifiers for the
specifications and datatypes used (388). No converter can invent those.

## Regenerating

```bash
python build_corpus.py
```

Rebuilds this directory and verifies two invariants on every run — both of
which caught real bugs while the converter was being made table-driven — and a
third on request:

- **loss** — every predicate asserted on a `dcat:Dataset` in the source graph
  is accounted for in the output: mapped through
  [`../mappings/dcat-to-cdif.sssom.tsv`](../mappings/dcat-to-cdif.sssom.tsv),
  rewritten by
  [`../mappings/dcat-aliases.sssom.tsv`](../mappings/dcat-aliases.sssom.tsv),
  or preserved verbatim. Comparison is on IRIs, resolving each record's own
  `@context`, because the converter mints a prefix for any vocabulary it passes
  through — HealthDCAT-AP arrives as `health:analytics`, not as the source IRI.
- **schema** — every conformant record validates against the CoreDiscovery
  profile. Fragments are expected to fail and are counted separately; a
  *non*-fragment that fails means conformance was detected for content the
  schema rejects.
- **SHACL** (`--shacl`, opt-in) — every conformant record against the
  CoreDiscovery shapes. Opt-in because it is slow and needs pyshacl plus
  `metadataBuildingBlocks` beside this repo: the composite's own `rules.shacl`
  is **not self-contained**, so the bundle has to be assembled by following the
  `$ref` graph first. `build_corpus.py` shells out to that repo's
  `tools/validate_shacl.py --emit-shapes` and caches the result (20 files, ~1300
  triples). Running pyshacl against the composite's file alone instead errors on
  `cdifd:descriptionProperty`.

`--check` verifies the directory on disk without writing, and `--limit N`
converts the first N groups for a quick pass.
