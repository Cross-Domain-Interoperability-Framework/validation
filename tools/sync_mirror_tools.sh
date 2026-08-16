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
# Used by .github/workflows/sync-mirror-tools.yml, and runnable by hand.
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
