#!/usr/bin/env bash
# Mirror the CDIF instance-validation tools + supporting artifacts from the
# validation repo into a cdif-umlmodel tools/ directory.
#
#   tools/sync_mirror_tools.sh <validation-repo-root> <cdif-umlmodel-tools-dir>
#
# The validation repo is the source of truth; the copied files must not be
# edited in the mirror. Only the files listed here are touched — the mirror's
# examples/ and readme.md are deliberately left alone.
#
# Invoked by the cdif-umlmodel repo's own workflow
# (.github/workflows/sync-tools-from-validation.yml), which CHECKS OUT this repo
# and runs this script. It is also runnable by hand:
#
#   bash tools/sync_mirror_tools.sh . ../cdif-umlmodel/tools
#
# The direction was inverted on 2026-10-02. This repo used to push into the
# mirror via .github/workflows/sync-mirror-tools.yml, which needed a cross-repo
# write credential (MIRROR_SYNC_TOKEN) that was never created -- and whose guard
# degraded to "do nothing and pass", so it reported success on every push for its
# entire life while the mirror went stale in all 15 files. Pulling needs no
# credential: both repos are public, and a job writing to its own repo has the
# built-in GITHUB_TOKEN. That workflow is deleted; do not reinstate a
# push-based one.
set -euo pipefail

SRC="${1:?usage: sync_mirror_tools.sh <validation-root> <mirror-tools-dir>}"
DST="${2:?usage: sync_mirror_tools.sh <validation-root> <mirror-tools-dir>}"

mkdir -p "$DST/ShaclValidation"

# Source paths (relative to the validation repo root) copied to <DST>/<basename>.
FILES=(
  tools/FrameAndValidate.py
  ShaclValidation/ShaclJSONLDContext.py
  ConformanceValidate.py
  detect_conformance.py
  CDIF-frame-2026.jsonld
  CDIF-context-2026.jsonld
  CDIFDiscoverySchema.json
  CDIFDataDescriptionSchema.json
  CDIFCompleteSchema.json
  conformance-schema-map.json
)
for f in "${FILES[@]}"; do
  cp -f "$SRC/$f" "$DST/$(basename "$f")"
done

# SHACL shape sets copied into <DST>/ShaclValidation/.
for t in Discovery DataDescription DataStructure Provenance Manifest Complete; do
  cp -f "$SRC/ShaclValidation/CDIF-$t-Shapes.ttl" "$DST/ShaclValidation/"
done

echo "Synced $(( ${#FILES[@]} + 6 )) files into $DST"
