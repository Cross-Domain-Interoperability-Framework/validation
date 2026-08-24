# CDIF ↔ ESIP Science-on-Schema.org (SOSO) converters

Bidirectional converters between the **CDIF core + discovery** profile and the
**ESIP Science-on-Schema.org (SOSO) v1.3** Dataset guidance. Both are schema.org
profiles, so the conversion is mostly structural alignment plus supplying (or
dropping) each side's required scaffolding.

| Script | Direction |
|--------|-----------|
| `ConvertToSOSO.py` | CDIF core+discovery → SOSO Dataset |
| `ConvertFromSOSO.py` | SOSO Dataset → CDIF core+discovery |

The property-by-property mapping is documented authoritatively in
[`doc-corediscovery/documents/CDIF-Discovery-vs-SOSO-comparison.md`](../../doc-corediscovery/documents/CDIF-Discovery-vs-SOSO-comparison.md),
which tracks the ESIP discussion in
[science-on-schema.org issue #283](https://github.com/ESIPFed/science-on-schema.org/issues/283).

## Install

```bash
pip install pyshacl rdflib        # only needed to validate output; converters use stdlib
```

The converters themselves are pure standard library (no dependencies).

## Usage

```bash
# CDIF core+discovery  ->  SOSO
python ConvertToSOSO.py path/to/cdif-record.json -o soso-record.json -v

# SOSO  ->  CDIF core+discovery
python ConvertFromSOSO.py examples/soso-dataset-example.json -o cdif-record.json -v --profile discovery
```

`ConvertToSOSO.py` accepts a framed CDIF tree **or** a flattened `@graph`
document (it inlines `@id` references before converting). `ConvertFromSOSO.py`
accepts a SOSO Dataset (bare schema.org terms via `@vocab`) or an `@graph`.

## What each converter does

### CDIF → SOSO (`ConvertToSOSO.py`)

- Rewrites `@context` to SOSO style — `{"@vocab": "http://schema.org/"}` plus any
  non-schema prefixes the record still needs (`dcterms`, `prov`, `dqv`, …).
- Strips the `schema:` prefix from property names and `@type` values (SOSO uses
  bare schema.org terms); keeps non-schema prefixes.
- **Drops the CDIF catalog record** (`schema:subjectOf` tagged
  `dcat:CatalogRecord` with `dcterms:conformsTo`) — SOSO has no metadata-
  conformance mechanism, and its `subjectOf` means something else.
- Passes CDIF-only properties through unchanged (SOSO is open-world).
- Emits **warnings** for SOSO-required fields the CDIF record lacks
  (`description`, `version`, `url`, `license`) — it never fabricates values.

### SOSO → CDIF (`ConvertFromSOSO.py`)

- Prefixes property names with `schema:` (unrecognized names → `unk:`) and
  normalizes `@type` to prefixed arrays.
- Rewrites `@context` to CDIF prefix declarations
  (`schema`/`dcterms`/`dcat`/`prov`, canonical `http://schema.org/`).
- Ensures CDIF-required fields where derivable: `@id` (from `url`),
  `schema:identifier` (from `@id`), `schema:dateModified` (from
  `datePublished`/`dateCreated`); wraps `schema:creator` in a JSON-LD `@list`;
  synthesizes Person names from given/family names.
- **Adds the CDIF catalog record**: `schema:subjectOf` typed `schema:Dataset` +
  `dcat:CatalogRecord`, pointing at the dataset `@id` via `schema:about`.
- **Derives `dcterms:conformsTo` from content** by running `detect_conformance`
  (presence + content-SHACL gate) on the converted record, instead of a
  hardcoded profile list. Best-effort — falls back to the profile default when
  `detect_conformance` (or its deps) is unavailable; pass `--static-conformance`
  to force the profile default.

To convert a SOSO record from a **file path or URL** (with the same
detect-conformance step and a default/`-o` output location), use
[`../converters/soso2cdif.py`](../converters/soso2cdif.py), the file/URL
front-end that wraps this engine:

```bash
python ../converters/soso2cdif.py path/to/soso.json            # -> soso-cdif.json
python ../converters/soso2cdif.py https://example.org/dataset -o out.json
```
- Reports (does not invent) CDIF-required fields it cannot derive
  (`dateModified`, `license`/`conditionsOfAccess`, `url`/`distribution`).

## The `http://` vs `https://` namespace note (important)

SOSO's **guide** states the canonical schema.org namespace is `http://schema.org/`
(its namespace-check shapes emit *"Expecting SO namespace of `http://schema.org/`"*),
so **`ConvertToSOSO.py` emits `http://schema.org/` by default**.

However, SOSO's **own v1.3 SHACL requirement shapes** (`soso_common_v1.3.0.ttl`)
are written against the `https://schema.org/` namespace (`SO:` prefix) and only
validate data in that namespace — so a correctly-namespaced (`http://`) SOSO
record passes SOSO's SHACL *vacuously* (the shapes never target it). This is an
internal inconsistency in SOSO v1.3.

To get output that SOSO's SHACL will actually exercise, pass `--https`:

```bash
python ConvertToSOSO.py cdif-record.json --https -o soso-record.json
```

Google Dataset Search accepts either namespace.

## Scope and limitations

- **Core + Discovery only.** These converters target the CDIF `core/1.1` +
  `discovery/1.1` properties. Higher-profile content (Data Description
  `cdi:InstanceVariable` variables, archive manifests, rich `prov:` provenance
  activities) is passed through open-world but not specifically mapped — a
  provenance `schema:Action`'s sub-properties survive a round trip as `schema:`
  terms, but their CDIF-vs-SOSO semantics are out of scope here.
- **No fabrication.** Required fields on the target side that cannot be derived
  from the source are reported as warnings, not invented.
- **Requirement mismatches** (per issue #283 / the comparison doc): CDIF requires
  `dateModified`, `subjectOf`/`conformsTo`, and license-or-conditionsOfAccess;
  SOSO's SHACL requires `url`, `version`, and `description`. A record minimal for
  one profile may need a field added for the other — the converters add the CDIF
  scaffolding automatically (SOSO→CDIF) and flag the SOSO gaps (CDIF→SOSO).

## Validating the output

```bash
# CDIF output -> CDIF Discovery schema
python ../tools/FrameAndValidate.py cdif-record.json -v --schema ../CDIFDiscoverySchema.json --frame ../CDIF-frame-2026.jsonld

# SOSO output -> SOSO v1.3 SHACL (use --https output so the shapes target it)
#   shapes: https://github.com/ESIPFed/science-on-schema.org/blob/v1.3-SHACL/validation/shapegraphs/soso_common_v1.3.0.ttl
python -c "from pyshacl import validate; from rdflib import Graph; \
print(validate(Graph().parse('soso-record.json', format='json-ld'), \
shacl_graph='soso_common_v1.3.0.ttl', inference='rdfs', advanced=True)[0])"
```

## Files

```
soso/
├── ConvertToSOSO.py                 CDIF core+discovery -> SOSO
├── ConvertFromSOSO.py               SOSO -> CDIF core+discovery
├── README.md                        this file
└── examples/
    └── soso-dataset-example.json    a representative SOSO v1.3 Dataset record
```
