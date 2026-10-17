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
canonical id `https://w3id.org/cdif/schema/conformance-declaration/0.2` — a
backward-compatible superset of `0.1`; a stage-1 CDIF-module sidecar that still
declares `0.1` is a valid `0.2` sidecar):

| field | required | stage | meaning |
|-------|----------|-------|---------|
| `conformsTo` | yes | 1 & 2 | Canonical profile URI written into `dcterms:conformsTo` when declared. Version aliasing (1.0/1.1) is the resolver map's job, not this file's. |
| `presence` | yes | 1 & 2 | SPARQL `ASK` true iff the record uses what this class adds beyond its base. The standard prefix preamble (`schema`, `prov`, `cdi`, `cdif`, `dcterms`, `dcat`, `rdf`, `dqv`) is prepended automatically. |
| `validityShapes` | no | 1 & 2 | Path **relative to the `_sources` root** to the class's **content** SHACL (`cdifDataType/<block>/rules.shacl`), used as the validity gate. `null`/omitted ⇒ presence-only. |
| `requires` | no | 2 | Array of `conformsTo` URIs that must **already** be declared (by stage 1 or an earlier stage-2 class) before this class is eligible. |
| `exclusiveGroup` | no | 2 | Classes sharing a group name are mutually exclusive alternatives (the technique profiles). |
| `priority` | no | 2 | Within an `exclusiveGroup`, higher wins (most specific). **Equal top priority is a declared tie** — reported, not resolved. Default 0. |
| `title`, `description` | no | 1 & 2 | Documentation. |

The `requires` / `exclusiveGroup` / `priority` fields are the **stage-2** additions
(0.2); stage 1 (the CDIF modules) never reads them. See
[Stage 2 — domain profiles](#stage-2--domain-profiles) below.

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
from detect_conformance import detect_cdif_conformance, apply_conformance, load_bb_conformance

uris = detect_cdif_conformance(doc, use_bb_source=True)  # read BB conformance.json sidecars
apply_conformance(doc, uris)                             # write dcterms:conformsTo (in place)
```

> The function was renamed `detect_conformance` → **`detect_cdif_conformance`**
> (stage 1). `detect_conformance` remains as a **deprecated alias** so existing
> callers (the converters, `ConformanceValidate.py`, `tools/FrameAndValidate.py`)
> keep working.

`load_bb_conformance(bb_dir)` globs `**/conformance.json` under the `_sources`
tree and returns entries in the same `{uri, presence, shacl, requires,
exclusiveGroup, priority}` shape as the in-file `CONFORMANCE_CLASSES` registry, so
the engine consumes either source identically (stage 1 ignores the stage-2
fields). `apply_conformance` reconciles only the profile space under its
`manage_prefix` (stage 1: `https://w3id.org/cdif/`) and **preserves** any claim
outside it (e.g. `ada:profile/adaNGNSMS`).

CLI / env:

```bash
python detect_conformance.py record.jsonld --from-source     # read sidecars
CDIF_CONFORMANCE_FROM_SOURCE=1 python detect_conformance.py record.jsonld
```

## Stage 2 — domain profiles

Stage 1 answers "which CDIF modules?" — six independent yes/no classes. **Domain
profiles** (geochem / ADA / technique) are different in three ways that the
stage-1 engine cannot express, which is why they get a second pass
(`detect_domain_conformance(doc, prior_uris, bb_dir, manage_prefix=…)`):

1. **They depend on each other.** `geochemProduct` needs the five CDIF modules;
   `adaProduct` needs `geochemProduct`; a technique profile needs `adaProduct`.
   So stage 2 takes stage 1's result as input (`prior_uris`) and resolves the
   `requires` chain to a fixpoint — a class is eligible only once every URI in
   its `requires` is already declared.
2. **They live in a different `_sources` tree** (`geochemBuildingBlocks`, not
   `metadataBuildingBlocks`) and **manage a different namespace**
   (`https://w3id.org/geochem/metadata/profiles/`). `apply_conformance(…,
   manage_prefix=GEOCHEM_BASE, append=True)` writes the domain URIs while leaving
   the stage-1 CDIF entries (and everything else) untouched, CDIF first.
3. **Technique profiles are a choice, not a set.** They share an
   `exclusiveGroup`; among the members whose presence holds and whose `requires`
   are met, the single highest `priority` (most specific) is declared.

### Deriving `requires` from the schema (not hand-listing)

`requires` is **derived from the profile's own schema composition**, never
hand-enumerated — hand-listing a contract the schema already states is how the
two sides drift. The rule:

> A profile's `requires` = the module URIs of the CDIF profiles its schema
> composes **unconditionally** in `allOf`. A **conditional** (`if/then`)
> composition is **not** a flat require — stage 1 declares that module on its own
> when its trigger content appears. A nested `$defs` `$ref` (using another block's
> shape for one node) is **not** an inherited profile.

Worked example — `geochemProduct/schema.yaml` composes, unconditionally, only
`cdifCore` + `cdifProvenance`. `cdifDataDescription` and `cdifManifest` are each
composed **conditionally**: `cdifDataDescription` only when the record has
variables (non-empty `schema:variableMeasured`, or a part typed
`cdi:TabularTextDataSet`), `cdifManifest` only when a distribution is a
`schema:Collection` bundle. So:

```
requires = [
  https://w3id.org/cdif/core/1.1,
  https://w3id.org/cdif/provenance/1.1
]
```

`data_description/1.1` and `manifest/1.1` are **excluded** — each is composed
conditionally, and `requires` cannot say "only if …"; a record with no variables,
or a single-file product, never carries them, and stage 1 declares each on its own
when its trigger content is present. `data_structure/1.1` is **excluded** (not
composed — only a nested `$defs` ref for an optional DataStructure node).
`discovery/1.1` is **excluded** too: geochemProduct does not compose
`cdifDiscovery`, and neither does `cdifCore` — discovery is a separate profile,
not entailed by core or by data_description. Down the chain each profile derives
from its own `allOf`: `adaProduct.requires = [geochemProduct]`,
`technique.requires = [adaProduct]`; the CDIF modules are gated transitively
through geochemProduct. Confirmed with Steve 2026-10-16.

### Ties are honest, and reported — not resolved

Some technique variants genuinely cannot be separated by `componentType` — and,
per a 2026-10 domain decision (Steve), **never will be**. There is **one
`componentType` per product kind, permanently**: the Mc/Q/Sf difference is
*procedure-side* (it lives in the `tapp/` and `detail/` metadata — 128 shared
items, MC unique in 15 — and never reaches the file), so `componentType`, which
classifies the file, is correctly one each. A future proposal to mint
`ada:LAICPMSMap.mc` / `.q` / `.sf` should be **refused on this basis, not
re-measured**. The variant identity a record *can* carry is the **TAPP reference**
(`prov:used` → a TAPP definition naming `laMcicpmsTAPP` etc.) — the axis Mc/Q/Sf
actually lives on.

So the LA- and Solution-ICP-MS families (`laMcicpms` / `laQicpms` / `laSficpms`,
and the U-Pb and solution analogues) share one `componentType`; a `priority`
order would pick a favourite and be **wrong two times in three**. Give those
group members **equal `priority`**: the engine reports a **declared tie**
(`result.ties`) and declares none of them — the honest answer ("one of these
three; the content can't say which"). The tie is not a defect in the vocabulary
that better modelling removes; it is the correct result of `componentType` not
carrying instrument-variant information, by design.

**A tie is not a failure.** It does not fail the CLI by default (only `withheld`
requires/validity failures do; `--strict-ties` opts in). This matters for
sequencing: **no record carries a TAPP reference yet** (0 of 7,447), so the
discriminating signal does not exist in the corpus — those families will tie for
every matching record, and that is *correct behaviour*, not a gap. If and when a
record carries a TAPP reference, a `presence` ASK that tests it (via `prov:used`)
makes exactly one member's presence hold and the tie resolves **through
presence** — no engine or `priority` change. Breaking a tie is always a narrower
presence signal, never a guessed ranking.

**Nothing about these families is revisited at migration.** Their `conformsTo`,
`requires`, `exclusiveGroup` and `priority` are fixed; the profile set, the groups
and the rankings do not change when TAPP references appear. The *only* thing that
changes is each member's `presence` ASK getting narrower, and that is a
regeneration of one field from the same config — not a redesign. A family member's
sidecar is written once and left alone.

### Authoring the `presence` ASK for a technique profile

The ASK must test only the componentTypes that **discriminate** this profile.
Generic componentTypes shared across unrelated techniques — `ada:analysisLocation`
(393 records), `ada:report` (210), `ada:contextPhotography` (54), `ada:quickLook`
(47) — must be **left out of the ASK**, not ranked: a presence rule that includes
them selects the profile for every record. Excluding them loses nothing, because
every record carrying one already names its real technique in
`schema:measurementTechnique`. (The resolved profile schema does **not** narrow
`ada:componentType` — it inlines the universal ~238-type enum, so every profile
admits everything — so a presence rule **cannot** be derived from it; the
discriminating list comes from `build_tapp.TAPP_CONFIGS[<tapp>]["component_types"]`,
the same config the profile's `hasPart` branches are generated from. The honest
guarantee is "selection comes from the same config the profile is generated
from," not "backed by a validation narrowing.")

### Failures are reported, never hidden

`detect_domain_conformance` returns a `DomainConformanceResult`:

| field | meaning |
|-------|---------|
| `declared` | domain URIs declared, in resolution order |
| `withheld` | classes whose **presence held but that were not declared** — `{uri, reason, detail}`, reason `"unsatisfied requires"` or `"validity gate failed"`. **A failure.** |
| `ties` | `{group, priority, candidates}` — ambiguous, not a failure |
| `.ok` | nothing withheld | 
| `.clean` | nothing withheld **and** no ties |

Withholding a class whose presence held is a real failure: *detect-then-validate*
must never silently declare less than presence says applies — otherwise validation
always "passes". The CLI (`--domain-bb-dir`) **exits non-zero** when anything is
withheld; a tie fails only under `--strict-ties`.

```python
from detect_conformance import (detect_cdif_conformance,
                                 detect_domain_conformance, apply_conformance,
                                 GEOCHEM_BASE)

cdif = detect_cdif_conformance(doc, use_bb_source=True)
dom  = detect_domain_conformance(doc, cdif, bb_dir=GEOCHEM_SOURCES)
apply_conformance(doc, cdif)                                   # CDIF modules
apply_conformance(doc, dom.declared, manage_prefix=GEOCHEM_BASE, append=True)
if not dom.ok:        # something withheld -> surface it, don't ship a silent pass
    ...
```

```bash
python detect_conformance.py record.jsonld --domain-bb-dir /path/to/geochemBuildingBlocks/_sources
```

> **Do not** point `validityShapes` at a profile `rules.shacl`. Those select
> records by the `conformsTo` they already declare (circular), and — as of
> 2026-10 — the geochem profile shapes were additionally *inert*, matching
> `schema:additionalType "dcat:CatalogRecord"` as a string literal while records
> carry the IRI, so they selected zero focus nodes. The validity gate must be a
> **content** shape that tests the data.

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
