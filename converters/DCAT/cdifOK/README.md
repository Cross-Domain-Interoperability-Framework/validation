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

Of the 67 conformant records:

- **36** have no `schema:url` or `schema:distribution`, and **20** have a
  `DataDownload` with no `contentUrl` — the source DCAT carries no resolvable
  access point.
- **8** have no usable `dcterms:modified`.
- **2** fail JSON-LD framing. One upstream file uses property keys of the form
  `https://www.w3.org/TR/vocab-dqv/#dqv:hasQualityAnnotation` — a document URL
  with a CURIE appended — which cannot be split into a namespace and a local
  name, so no prefix can be declared for it.

None of these are conversion defects; they are what the sources contain.

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
