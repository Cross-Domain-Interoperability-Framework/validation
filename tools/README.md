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
