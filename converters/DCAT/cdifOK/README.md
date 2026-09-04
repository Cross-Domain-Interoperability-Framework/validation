# CDIF records converted from the DCAT examples

219 CDIF JSON-LD records generated from [`../dcatExamplesOK`](../dcatExamplesOK)
by [`../dcat_to_cdif.py`](../dcat_to_cdif.py), mirroring that directory's
profile subdirectories. `INDEX.json` lists every record with the sources it came
from and whether it is a fragment.

```
158 logical examples -> 219 records
   78 merged from more than one serialization
   67 conformant  (core/1.1 + discovery/1.1)
  152 -frag       (content does not meet core)

  0 JSON Schema failures   0 over-claiming   0 under-declaring
  2 records with SHACL violations
```

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

The corpus ships many examples in more than one serialization, and **45 of the
78 such pairs are not the same graph** — the `.ttl` and the `.jsonld` carry
different triples upstream. Converting each separately produced near-duplicate
records, each missing whatever the other had.

So every serialization of one logical example (same directory, same stem) is
parsed into a single RDF graph and converted once. The union is what reaches the
converter, and `INDEX.json` records how many sources each record was merged
from.

The normalization this depends on was verified rather than assumed: of the 33
pairs whose source graphs *are* isomorphic, 46 of the 53 resulting records are
byte-identical between the two routes, and the 7 that differ do so only in
blank-node labels — arbitrary identifiers carrying no meaning.

## Known remaining issues

Of the 67 conformant records, **2** still carry SHACL violations, both about
geometry: a `geoshape` that does not give a line or box as latitude-longitude
pairs, and an absent spatial coverage description. Both are what the source
contains; the converter has nothing to work from.

Where the source is silent, the record says so rather than staying quiet:

- no landing page and no distribution, or a `DataDownload` with no access URL —
  `schema:url` / `schema:contentUrl` carry the OGC `nil:missing` URI, as a
  string: both properties are declared `sh:datatype xsd:string`;
- no licence — `schema:license` carries the same URI;
- no usable `dcterms:modified` — the conversion timestamp, which is at least
  true of the serialization. Source dates carrying fractional seconds
  (`2024-05-08T04:11:24.309486`) are trimmed rather than discarded: the CDIF
  pattern accepts seconds precision and no more.

A record moving in or out of conformance changes its filename, so git shows it
as a delete plus an add rather than a modification.

## Regenerating

```bash
python dcat_to_cdif.py <input.jsonld> --output <dir>
```

The batch driver that produced this directory does three things the converter
does not: it merges serializations, re-serializes RDF sources as JSON-LD
compacted against a context binding `dcat:` (the converter matches on the
literal CURIE `dcat:Dataset`), and inlines `@graph` node references so the
converter — which walks *down* from the dataset node — can see distributions
that rdflib emitted as siblings.
