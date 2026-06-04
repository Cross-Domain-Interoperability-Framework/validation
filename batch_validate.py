#!/usr/bin/env python3
"""Batch validate CDIF metadata files from sitemap groups.

Runs FrameAndValidate.py (JSON Schema) and ShaclValidation/ShaclJSONLDContext.py
(SHACL) on each file, collecting pass/fail results.
"""

import subprocess
import sys
import os
import json
import re
from pathlib import Path

VALIDATION_DIR = Path(__file__).parent
FRAME_VALIDATE = VALIDATION_DIR / "FrameAndValidate.py"
SHACL_VALIDATE = VALIDATION_DIR / "ShaclValidation" / "ShaclJSONLDContext.py"
sys.path.insert(0, str(VALIDATION_DIR))
import ConformanceValidate as CV  # noqa: E402

# Validate each record against every CDIF profile its catalog record declares,
# resolving each profile's JSON Schema + per-profile SHACL shapes from the local
# conformance-schema-map.json. Covers exactly the profiles a record claims
# (incl. provenance / manifest), not a single fixed composite.
_RESOLVER = None
_CONF_CACHE = {}


def _resolver():
    global _RESOLVER
    if _RESOLVER is None:
        _RESOLVER = CV.build_resolver("local")
    return _RESOLVER


def _conformance(filepath):
    """Run (and cache) the full per-declared-profile conformance check."""
    key = str(filepath)
    if key not in _CONF_CACHE:
        try:
            doc = json.loads(Path(filepath).read_text(encoding="utf-8"))
            _CONF_CACHE[key] = CV.run_conformance(
                doc, _resolver(), do_schema=True, do_shacl=True)
        except Exception as e:
            _CONF_CACHE[key] = {"error": str(e), "profiles": [],
                                "conformsTo": [], "total_violations": -1}
    return _CONF_CACHE[key]


# File patterns to exclude from SHACL validation (generated output, not CDIF source)
SHACL_EXCLUDE_SUFFIXES = ("-croissant.json", "-rocrate.json", "rocrate-jsonld-example.json", "ro-crate-metadata.json")

CDIF_VALIDATION = VALIDATION_DIR

# ---------------------------------------------------------------------------
# External example corpora live in sibling CDIF repos. Each group resolves its
# files either from a local clone (SOURCE_MODE="local", the default — works on a
# dev box with the repos checked out under C:\GithubC\CDIF) or straight from
# GitHub (SOURCE_MODE="github", fetched from raw.githubusercontent.com into
# _remote_cache/). Flip with the CDIF_BATCH_SOURCE env var; collect_files() is
# identical either way.
#
# Release target: once the CDIF examples are published as versioned GitHub
# *release* assets, repoint REPOS[...]["raw"] at the release download base
# (https://github.com/<org>/<repo>/releases/download/<tag>) and adjust the
# per-file relative paths if the asset layout differs. The local/github switch
# and the rest of this file stay unchanged.
# ---------------------------------------------------------------------------

SOURCE_MODE = os.environ.get("CDIF_BATCH_SOURCE", "local")  # "local" | "github"

_ORG_RAW = "https://raw.githubusercontent.com/Cross-Domain-Interoperability-Framework"
REPOS = {
    "cdifbook": {
        "local": Path(r"C:\GithubC\CDIF\cdifbook"),
        "raw": f"{_ORG_RAW}/cdifbook/main",
    },
    "buildingBlocks": {
        "local": Path(r"C:\GithubC\CDIF\metadataBuildingBlocks"),
        "raw": f"{_ORG_RAW}/metadataBuildingBlocks/main",
    },
}

_REMOTE_CACHE = VALIDATION_DIR / "_remote_cache"


def _repo_file(repo_key, relpath):
    """Return a local Path to <repo>/<relpath>, fetching from GitHub if needed.

    Returns None (with a warning) if the file can't be located."""
    relpath = relpath.replace("\\", "/")
    if SOURCE_MODE == "local":
        p = REPOS[repo_key]["local"] / relpath
        if p.exists():
            return p
        print(f"  WARNING: {p} not found")
        return None
    # github: download into a per-repo cache mirroring the relpath
    dest = _REMOTE_CACHE / repo_key / relpath
    if not dest.exists():
        url = f"{REPOS[repo_key]['raw']}/{relpath}"
        try:
            import urllib.request
            dest.parent.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(url) as resp:
                dest.write_bytes(resp.read())
        except Exception as e:
            print(f"  WARNING: could not fetch {url}: {e}")
            return None
    return dest


# cdifbook examples (schema.org-serialized CDIF documents the validator handles
# directly; the DCAT/.ttl examples in that folder need conversion first).
CDIFBOOK_EXAMPLES = [
    "SDO-CDIF-BasicDataset.json",
    "SDO-CDIF-BasicDatasetTemporalExtent.json",
    "SDO-CDIF-BasicDatasetWVariables.json",
    "SDO-CDIF-CreatorContributorExample.json",
    "SDO-CDIF-IndOBIS28001-30000.jsonld",
    "SDO-CDIF-MinimalDigitalObject.json",
    "SDO-CDIF-OIH-BuoySeaSurfaceTemp.json",
    "SDO-CDIF-QueryableDistribution.json",
    "SDO-CDIF-SwedishDataServiceWind.jsonld",
    "SDO-CDIF-datasetMultipleDistributions.json",
]

# Composite-profile example documents from metadataBuildingBlocks (restructured
# layout: _sources/profiles/cdifCompositeProfile/<profile>/example*.json). These
# are complete standalone documents, one per representative profile.
PROFILE_EXAMPLES = [
    "_sources/profiles/cdifCompositeProfile/CoreDiscovery/exampleCDIFDiscovery.json",
    "_sources/profiles/cdifCompositeProfile/DiscoveryDataDescription/exampleCDIFDataDescription.json",
    "_sources/profiles/cdifCompositeProfile/DiscoveryDataDescriptionStructure/exampleCDIFDataStructureComplete.json",
    "_sources/profiles/cdifCompositeProfile/cdifComplete/exampleCDIFcomplete.json",
    "_sources/profiles/cdifCompositeProfile/XASdata/exampleCDIFxas.json",
]


def collect_files():
    """Collect all files grouped by category."""
    groups = {}

    # Group 1: testJSONMetadata (local to this repo)
    test_dir = CDIF_VALIDATION / "testJSONMetadata"
    groups["testJSONMetadata"] = sorted(test_dir.glob("metadata_*.json"))

    # Group 2: cdifbook examples
    groups["cdifbook"] = [
        f for name in CDIFBOOK_EXAMPLES
        if (f := _repo_file("cdifbook", f"examples/{name}"))
    ]

    # Group 3: CDIF composite-profile examples (metadataBuildingBlocks)
    groups["cdifProfiles"] = [
        f for rel in PROFILE_EXAMPLES
        if (f := _repo_file("buildingBlocks", rel))
    ]

    return groups


def _short(uri):
    return uri.split("/cdif/", 1)[-1] if "/cdif/" in uri else uri


def run_json_schema_validation(filepath):
    """JSON Schema pass across every declared profile (via ConformanceValidate).

    Returns (passed: bool, output: str). Passes when no declared profile's
    framed JSON Schema fails; profiles with no local schema are reported but
    don't fail the record.
    """
    res = _conformance(filepath)
    if res.get("error"):
        return False, res["error"]
    profiles = res.get("profiles", [])
    if not profiles:
        return False, "No CDIF conformsTo profiles declared in catalog record"
    failed = [p for p in profiles if p["schema"]["status"] in ("failed", "error")]
    if failed:
        msgs = [f"{_short(p['uri'])}: {e.get('message', e)}"
                for p in failed for e in p["schema"]["errors"][:2]]
        return False, "\n".join(msgs)
    checked = [_short(p["uri"]) for p in profiles
               if p["schema"]["status"] == "passed"]
    return True, "PASSED [" + ", ".join(checked) + "]" if checked else "PASSED (no local schema)"


def run_shacl_validation(filepath):
    """SHACL pass across every declared profile (via ConformanceValidate).

    Returns (violations, warnings, infos, output). Only sh:Violation results
    count (ConformanceValidate filters severity); warnings/info are advisory and
    not surfaced here.
    """
    res = _conformance(filepath)
    if res.get("error"):
        return -1, 0, 0, res["error"]
    profiles = res.get("profiles", [])
    violations = sum(len(p["shacl"]["errors"]) for p in profiles)
    msgs = [f"{_short(p['uri'])}: {e.get('Message', e.get('message', '(violation)'))}"
            for p in profiles for e in p["shacl"]["errors"][:3]]
    return violations, 0, 0, "\n".join(msgs)


def extract_errors(output):
    """Extract key error lines from validation output."""
    lines = output.split("\n")
    errors = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if any(kw in line.lower() for kw in ["error", "fail", "violation", "invalid", "missing"]):
            errors.append(line)
        elif line.startswith("- ") or line.startswith("* "):
            errors.append(line)
    return errors[:5]  # limit to 5 most relevant


def main():
    groups = collect_files()
    total_files = sum(len(files) for files in groups.values())
    print(f"=== CDIF Batch Validation: {total_files} files ===\n")

    all_results = {}
    overall_schema_pass = 0
    overall_schema_fail = 0
    overall_shacl_clean = 0    # no violations, no warnings
    overall_shacl_warn = 0     # warnings/info only (no violations)
    overall_shacl_viol = 0     # has violations
    overall_shacl_skip = 0

    for group_name, files in groups.items():
        print(f"\n{'='*60}")
        print(f"Group: {group_name} ({len(files)} files)")
        print(f"{'='*60}")

        group_results = []
        schema_pass = 0
        schema_fail = 0
        shacl_clean = 0
        shacl_warn = 0
        shacl_viol = 0
        shacl_skip = 0

        for i, filepath in enumerate(files):
            fname = filepath.name
            print(f"\n[{i+1}/{len(files)}] {fname}")

            # JSON Schema validation
            js_passed, js_output = run_json_schema_validation(filepath)
            if js_passed:
                schema_pass += 1
                print(f"  JSON Schema: PASS")
            else:
                schema_fail += 1
                errors = extract_errors(js_output)
                print(f"  JSON Schema: FAIL")
                for e in errors:
                    print(f"    {e}")

            # SHACL validation (skip generated output files)
            sh_violations = None
            sh_warnings = 0
            sh_infos = 0
            if any(fname.endswith(s) for s in SHACL_EXCLUDE_SUFFIXES):
                shacl_skip += 1
                print(f"  SHACL:       SKIP (generated output)")
            else:
                sh_violations, sh_warnings, sh_infos, sh_output = run_shacl_validation(filepath)
                if sh_violations < 0:
                    # error running validation
                    shacl_viol += 1
                    print(f"  SHACL:       ERROR")
                    errors = extract_errors(sh_output)
                    for e in errors:
                        print(f"    {e}")
                elif sh_violations > 0:
                    shacl_viol += 1
                    print(f"  SHACL:       FAIL ({sh_violations} violations, {sh_warnings} warnings, {sh_infos} info)")
                    errors = extract_errors(sh_output)
                    for e in errors:
                        print(f"    {e}")
                elif sh_warnings > 0 or sh_infos > 0:
                    shacl_warn += 1
                    print(f"  SHACL:       PASS ({sh_warnings} warnings, {sh_infos} info)")
                else:
                    shacl_clean += 1
                    print(f"  SHACL:       PASS (clean)")

            shacl_skipped = any(fname.endswith(s) for s in SHACL_EXCLUDE_SUFFIXES)
            group_results.append({
                "file": fname,
                "schema_pass": js_passed,
                "shacl_violations": sh_violations,
                "shacl_warnings": sh_warnings,
                "shacl_infos": sh_infos,
                "shacl_skipped": shacl_skipped,
            })

        all_results[group_name] = group_results
        overall_schema_pass += schema_pass
        overall_schema_fail += schema_fail
        overall_shacl_clean += shacl_clean
        overall_shacl_warn += shacl_warn
        overall_shacl_viol += shacl_viol
        overall_shacl_skip += shacl_skip

        shacl_tested = len(files) - shacl_skip
        print(f"\n--- {group_name} Summary ---")
        print(f"  JSON Schema: {schema_pass} pass, {schema_fail} fail")
        print(f"  SHACL ({shacl_tested} tested): {shacl_clean} clean, {shacl_warn} warnings-only, {shacl_viol} violations")

    # Overall summary
    total_shacl_tested = total_files - overall_shacl_skip
    print(f"\n{'='*60}")
    print(f"OVERALL SUMMARY ({total_files} files)")
    print(f"{'='*60}")
    print(f"  JSON Schema: {overall_schema_pass} pass, {overall_schema_fail} fail")
    print(f"  SHACL ({total_shacl_tested} tested, {overall_shacl_skip} skipped):")
    print(f"    {overall_shacl_clean} clean (no issues)")
    print(f"    {overall_shacl_warn} pass with warnings/info only")
    print(f"    {overall_shacl_viol} violations")

    # List files with violations
    print(f"\n--- Files with SHACL Violations ---")
    any_violations = False
    for group_name, results in all_results.items():
        for r in results:
            if r["shacl_violations"] is not None and r["shacl_violations"] > 0:
                any_violations = True
                print(f"  [{group_name}] {r['file']}: {r['shacl_violations']} violations, {r['shacl_warnings']} warnings")
    if not any_violations:
        print("  None! No SHACL violations across any files.")

    # List JSON Schema failures
    any_schema_fail = False
    for group_name, results in all_results.items():
        for r in results:
            if not r["schema_pass"]:
                if not any_schema_fail:
                    print(f"\n--- Files with JSON Schema Failures ---")
                any_schema_fail = True
                print(f"  [{group_name}] {r['file']}")
    if not any_schema_fail:
        print(f"\n--- JSON Schema: All {overall_schema_pass} files passed ---")


if __name__ == "__main__":
    main()
