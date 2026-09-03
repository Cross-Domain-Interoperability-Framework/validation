# validation/tools

Shared, normative tooling for the CDIF validation + release repositories.

## FrameAndValidate.py — normative source

`tools/FrameAndValidate.py` is the **single source of truth** for the
`FrameAndValidate.py` script that ships in every CDIF profile / documentation
release repo (`profile-core`, `profile-manifest`, `profile-discovery`,
`doc-corediscovery`, …). Edit it **here** and propagate; never hand-edit the
copies.

It is profile-agnostic: when `--schema` / `--frame` are omitted it auto-detects
the single `*Schema*.json` and `*-frame.jsonld` next to it, so the identical file
works in every repo (each repo has exactly one of each). The array-property list
is the **union** across all profiles (wrapping an absent property is a no-op), and
the main-entity picker matches the frame's root `@type`, so it handles both
Dataset-rooted and SKOS `ConceptScheme`-rooted profiles.

### Detecting conformance while framing

`FrameAndValidate.py --conformance` frames the document, then derives which CDIF
profiles the framed result conforms to (from its content, via `detect_conformance.py`)
and rewrites `schema:subjectOf/dcterms:conformsTo` to declare them — preserving any
non-CDIF (domain) profile already claimed. The import of `detect_conformance` is
best-effort: it works in the validation repo (which ships it and can reach the
building-block SHACL gates) and is a no-op in a release repo that doesn't have it.

```bash
python tools/FrameAndValidate.py record.jsonld --frame CDIF-frame-2026.jsonld --conformance -o out.json
```

### Checking conformance while validating

`-v` now also **compares** the record's declared `conformsTo` against the
conformance `detect_conformance.py` derives from its content, and reports the
disagreement in both directions:

```
Checking declared conformsTo against detected conformance...
  DECLARED BUT NOT DETECTED: https://w3id.org/cdif/data_description/1.1
  DETECTED BUT NOT DECLARED: https://w3id.org/cdif/discovery/1.1
  Conformance INCONSISTENT
```

`DECLARED BUT NOT DETECTED` is a record claiming a profile its content does not
support; `DETECTED BUT NOT DECLARED` is one under-selling itself. Only the
CDIF-managed URI space (`https://w3id.org/cdif/`) is compared — a project or
domain profile claim is listed and left alone, matching what `apply_conformance`
preserves.

**An over-claim is fatal; an under-claim is advisory.** Declaring a profile the
content does not support is a wrong statement about the record, and it is the
declaration that tells a consumer which schema to apply — so the run exits 1
even when JSON Schema validation passes:

```
Validation PASSED

FAILED: conformsTo declares 1 profile(s) the content does not support:
  https://w3id.org/cdif/data_description/1.1
```

The exit is deferred until after the schema pass, so a document with both
problems reports its schema errors rather than having them masked. A record that
merely under-claims still exits 0.

Two things bound what the comparison can honestly say, and both were found by
making it fatal and watching correct records fail:

- **Only the six detectable profiles are compared.** `detect_conformance` emits
  from a fixed registry — core, discovery, data_description, data_structure,
  provenance, manifest. A record declaring anything else (`codelist/1.1`,
  `complexCitation/0.1`) would read as over-claiming every single time, because
  no rule exists that could produce it. Those are reported as
  `not checked (no detection rule)` and never fail a run.
- **Both halves are read from the source document, never the framed one.**
  Framing is lossy in both directions. It can drop `schema:subjectOf` outright,
  so the declaration reads as "declares nothing". And evidence below
  `schema:distribution` does not survive it — `exampleCDIFDataStructureMinimal.json`
  detects `data_structure/1.1` from its source and not from its framed result —
  so detection under-reports and a correct record looks like it is over-claiming.
  Framing stays where it belongs: feeding JSON Schema, which validates the
  framed shape.


Two details worth knowing:

- The declared URIs are read from the **source** document, not the framed one.
  Framing can drop `schema:subjectOf` — a frame whose `subjectOf` clause carries
  `"@type": "schema:Dataset"` will not match a `subjectOf` node that has no
  `@type` — and reading the declaration from the framed output would then report
  "declares nothing" for a record that declares plenty. When that happens the
  check says so, which turns an otherwise baffling
  `'schema:subjectOf' is a required property` into a diagnosis.
- It is skipped after `--conformance`, which has just rewritten the declaration
  to the detected set; agreement would be trivially true.

The check no-ops with a one-line note where `detect_conformance.py` cannot be
imported. A release-repo copy finds it when the validation repo is checked out
as a sibling (`CDIF/validation/`), or via `CDIF_VALIDATION_DIR`.

### Propagating changes

```bash
# from the validation repo root
python tools/sync_frameandvalidate.py            # dry-run: verify + report
python tools/sync_frameandvalidate.py --apply    # write copies where safe
```

`sync_frameandvalidate.py`:

1. **Discovers** every sibling repo under `CDIF/` that has a `FrameAndValidate.py`
   (excluding this validation repo).
2. **Verifies** before overwriting: runs each repo's `examples/*.json` through the
   existing copy (baseline) and the normative candidate, and **refuses to
   overwrite** any repo where an example that passed under the baseline would fail
   under the candidate (a regression). `--force` overrides; `--no-verify` skips.
3. **Stamps** each copy with a generated `DO NOT EDIT` banner carrying a
   `src-sha256` of the normative script body, and marks the file read-only.

The `src-sha256` is computed over the script body **after** the banner block,
with line endings normalized to LF — so banner text and CRLF/LF differences never
affect it.

### Enforcement — keeping the copies from drifting

Three layers, weakest to strongest:

| Layer | File | What it does |
|---|---|---|
| Banner + read-only | (written by the sync script) | Marks each copy generated and awkward to edit. A `git checkout` resets the read-only flag, so this is a deterrent only. |
| Pre-commit reminder | `.githooks/pre-commit` (this repo) | When a commit changes `tools/FrameAndValidate.py` but the release copies are stale, warns (or, with `CDIF_SYNC_STRICT=1`, blocks) and tells you to run the sync. Enable with `git config core.hooksPath .githooks`. |
| CI drift check | `tools/templates/check-frameandvalidate.yml` → each release repo's `.github/workflows/` | On any change to a repo's `FrameAndValidate.py`, fetches the normative source and **fails the build** if the script body has drifted. This is the only layer that can't be bypassed locally. |

To install the CI check in a release repo, copy the template to that repo's
`.github/workflows/check-frameandvalidate.yml` and set `UPSTREAM_REF` to the
validation branch/tag holding the normative source (default `main`).

## FlattenCDIF.py — the inverse of framing

`FlattenCDIF.py` takes a nested / compacted CDIF JSON-LD document and produces the
flattened `@graph` form (every node a top-level entry, cross-references by `@id`),
re-applying the CDIF namespace prefixes (`schema:`, `cdi:`, …) so the output stays
readable. It is the inverse direction of `FrameAndValidate.py`.

```bash
python tools/FlattenCDIF.py my-metadata.jsonld -o flattened.json
```

Pipeline: `jsonld.expand` → `jsonld.flatten` → compact with the namespace prefixes
from `CDIF-context-2026.jsonld` (`--context` to override). It is a validation-repo
utility — **not** part of the `FrameAndValidate.py` sync set.

Note: this is a *full* JSON-LD flatten, so embedded value objects (`schema:GeoShape`,
`schema:QuantitativeValue`, `spdx:Checksum`, …) are promoted to their own `@graph`
nodes. That is standard flattened JSON-LD, but it is **not** the shape the framed
`*Schema*.json` files expect, and the generated `CDIF-graph-schema-2026.json`
expects those value objects to remain nested — so it is not a validation target for
this output. Correctness is instead confirmed by round-trip: flattening then
re-framing reproduces a schema-valid tree.

## migrate_corpus_cdi_to_cdif.py

One-off corpus migration helper (pre-2026 `cdi:` → current `cdif:` data-structure
prefixes). See the repo CLAUDE.md / git history for context.
