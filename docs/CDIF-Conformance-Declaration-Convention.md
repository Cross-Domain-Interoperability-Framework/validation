# CDIF conformance-declaration convention

How a CDIF building block declares the conformance class it defines, so that
[`detect_conformance.py`](../detect_conformance.py) can decide — from a record's
**actual content** — which profiles the record should claim in
`schema:subjectOf/dcterms:conformsTo`, reading the rules **from the building-block
sources** instead of a hardcoded table.

## Problem

A generator (the ADA loader, `ConvertFromCroissant`, DCAT/DDI converters, …)
builds a CDIF JSON-LD record and must set `dcterms:conformsTo`. Hardcoding a fixed
list over-declares: a discovery-only record that lists `data_description` then
fails (or silently misleads) because it carries no variables. `detect_conformance`
solves this by deriving the list from content, using **two signals per class**:

- **presence** — a SPARQL `ASK` testing whether the record uses the elements this
  class *introduces beyond its base*. (Not "is property X present": `prov:wasGeneratedBy`
  is core, so it can't mark provenance; the marker is the dual-typed
  `prov:Activity + schema:Action` with properties beyond `prov:used`.)
- **validity** — the class's **content** SHACL shapes raise no `sh:Violation` on
  the record. `sh:Warning` / `sh:Info` are advisory and never block (CDIF severity
  policy).

> A class is declared **iff** presence is true **and** (no content SHACL, or the
> content SHACL conforms).

Those two signals plus the profile URI are exactly what the building block that
*defines* the class knows. So they should live with that building block — not in a
central registry that must be edited every time a new class (e.g. geochem) is
added. This convention is where they live.

## The sidecar: `conformance.json`

Each **profile** building block (`_sources/profiles/cdifProfile/<name>/`) carries a
`conformance.json` next to its `bblock.json`. It is a sidecar — deliberately
*not* folded into `bblock.json` — so it never interferes with OGC building-block
metaschema validation or tooling.

Fields (full schema: [`conformance-declaration.schema.json`](./conformance-declaration.schema.json),
canonical id `https://w3id.org/cdif/schema/conformance-declaration/0.1`):

| field | required | meaning |
|-------|----------|---------|
| `conformsTo` | yes | Canonical CDIF profile URI written into `dcterms:conformsTo` when declared. Version aliasing (1.0/1.1) is the resolver map's job, not this file's. |
| `presence` | yes | SPARQL `ASK` true iff the record uses what this class adds beyond its base. The standard prefix preamble (`schema`, `prov`, `cdi`, `cdif`, `dcterms`, `dcat`, `rdf`) is prepended automatically. |
| `validityShapes` | no | Path **relative to the `_sources` root** to the class's **content** SHACL (`cdifDataType/<block>/rules.shacl`), used as the validity gate. `null`/omitted ⇒ presence-only. |
| `title`, `description` | no | Documentation. |

### Example — `cdifProvenance/conformance.json`

```json
{
  "$schema": "https://w3id.org/cdif/schema/conformance-declaration/0.1",
  "conformsTo": "https://w3id.org/cdif/provenance/1.1",
  "title": "CDIF Provenance profile",
  "description": "Marked by a dual-typed prov:Activity + schema:Action carrying properties beyond prov:used (not merely prov:wasGeneratedBy, which is core).",
  "presence": "ASK {\n  ?d prov:wasGeneratedBy ?a .\n  ?a a prov:Activity, schema:Action ; ?p ?o .\n  FILTER (?p NOT IN (rdf:type, prov:used))\n}",
  "validityShapes": "cdifDataType/cdifProvActivity/rules.shacl"
}
```

### Why content shapes, not the profile `rules.shacl`

The profile-level `rules.shacl` is **circular** for deciding declaration: it
requires the catalog record to *already declare* conformance to that profile (the
`metadataProfileProperty` requirement), so it can only validate an
already-declared record — it can't decide whether to declare. `validityShapes`
must therefore point at the building-block **content** shapes
(`cdifDataType/<block>/rules.shacl`), which test the data itself.

## How `detect_conformance` consumes it

```python
from detect_conformance import detect_conformance, apply_conformance, load_bb_conformance

uris = detect_conformance(doc, use_bb_source=True)   # read BB conformance.json sidecars
apply_conformance(doc, uris)                          # write dcterms:conformsTo (in place)
```

`load_bb_conformance(bb_dir)` globs `**/conformance.json` under the `_sources`
tree and returns entries in the same `{uri, presence, shacl}` shape as the
in-file `CONFORMANCE_CLASSES` registry, so the engine consumes either source
identically. `apply_conformance` reconciles only the CDIF-managed profile space
(URIs under `https://w3id.org/cdif/`) and **preserves** any domain profile already
present (e.g. `ada:profile/adaNGNSMS`).

CLI / env:

```bash
python detect_conformance.py record.jsonld --from-source     # read sidecars
CDIF_CONFORMANCE_FROM_SOURCE=1 python detect_conformance.py record.jsonld
```

## Migration status

The hardcoded `CONFORMANCE_CLASSES` registry in `detect_conformance.py` remains the
**default** so nothing breaks if a clone lacks the BB sources. The six current
profile classes (`core`, `discovery`, `data_description`, `data_structure`,
`provenance`, `manifest`) now **also** ship `conformance.json` sidecars, and
`--from-source` is verified to produce **identical** results to the registry across
the corpus and the Croissant conversions.

Remaining to fully retire the registry:

1. Keep adding a `conformance.json` to every new profile/conformance-class BB
   (geochem and friends) **as part of generating that building block**.
2. Once coverage is complete and downstream callers pass `use_bb_source=True`,
   flip the default and delete the in-file registry (or keep it only as a frozen
   fallback for source-less clones).

## Adding a new conformance class

1. In the building block that defines the class, add `conformance.json` with its
   `conformsTo` URI, a `presence` ASK (the elements it adds beyond its base), and
   `validityShapes` pointing at that block's content `rules.shacl` (or `null`).
2. Add the profile URI → schema/SHACL mapping to
   [`../conformance-schema-map.json`](../conformance-schema-map.json) so
   `ConformanceValidate.py --source local` can validate records that declare it.
3. Run `detect_conformance.py <example> --from-source -v` on the BB's example to
   confirm the class is detected (and only when it should be).
