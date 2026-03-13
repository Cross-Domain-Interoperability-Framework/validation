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
SHACL_SHAPES = VALIDATION_DIR / "ShaclValidation" / "CDIF-Complete-Shapes.ttl"

# File patterns to exclude from SHACL validation (generated output, not CDIF source)
SHACL_EXCLUDE_SUFFIXES = ("-croissant.json", "-rocrate.json", "rocrate-jsonld-example.json", "ro-crate-metadata.json")

# Repo roots
CDIF_VALIDATION = VALIDATION_DIR
USGIN_BB = Path(r"C:\Users\smrTu\OneDrive\Documents\GithubC\USGIN\metadataBuildingBlocks")
CDIFBOOK = Path(r"C:\Users\smrTu\OneDrive\Documents\GithubC\CDIF\cdifbook")

def collect_files():
    """Collect all files grouped by category."""
    groups = {}

    # Group 1: testJSONMetadata (77 files)
    test_dir = CDIF_VALIDATION / "testJSONMetadata"
    files = sorted(test_dir.glob("metadata_*.json"))
    groups["testJSONMetadata"] = files

    # Group 2: cdifbook examples (10 files)
    cdifbook_examples = CDIFBOOK / "examples"
    cdifbook_files = []
    for name in [
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
    ]:
        f = cdifbook_examples / name
        if f.exists():
            cdifbook_files.append(f)
        else:
            print(f"  WARNING: {f} not found")
    groups["cdifbook"] = cdifbook_files

    # Group 3: CDIF profile examples (5 files)
    cdif_profiles = []
    bb_profiles = USGIN_BB / "_sources" / "profiles" / "cdifProfiles"
    for subdir, fname in [
        ("CDIFDiscovery", "CDIF-XAS-Full.json"),
        ("CDIFDiscovery", "exampleCDIFDiscovery.json"),
        ("CDIFDataDescription", "exampleCDIFDataDescription.json"),
        ("CDIFcomplete", "exampleCDIFcomplete.json"),
        ("CDIFxas", "exampleCDIFxas.json"),
    ]:
        f = bb_profiles / subdir / fname
        if f.exists():
            cdif_profiles.append(f)
        else:
            print(f"  WARNING: {f} not found")
    groups["cdifProfiles"] = cdif_profiles

    # Group 4: ADA profile examples (36 files)
    ada_profiles = []
    ada_dir = USGIN_BB / "_sources" / "profiles" / "adaProfiles"
    for d in sorted(ada_dir.iterdir()):
        if d.is_dir():
            example = d / f"example{d.name}.json"
            if example.exists():
                ada_profiles.append(example)
    groups["adaProfiles"] = ada_profiles

    return groups


def run_json_schema_validation(filepath):
    """Run FrameAndValidate.py and return (passed: bool, output: str)."""
    try:
        result = subprocess.run(
            [sys.executable, str(FRAME_VALIDATE), str(filepath), "-v"],
            capture_output=True, text=True, timeout=120,
            cwd=str(VALIDATION_DIR)
        )
        output = result.stdout + result.stderr
        # Check for validation success indicators
        passed = result.returncode == 0 and "Validation errors" not in output
        return passed, output.strip()
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as e:
        return False, str(e)


def run_shacl_validation(filepath):
    """Run SHACL validation and return (violations, warnings, infos, output).

    Returns a tuple of (violation_count, warning_count, info_count, raw_output).
    """
    try:
        result = subprocess.run(
            [sys.executable, str(SHACL_VALIDATE), str(filepath), str(SHACL_SHAPES)],
            capture_output=True, text=True, timeout=120,
            cwd=str(VALIDATION_DIR)
        )
        output = result.stdout + result.stderr
        # Count issues by severity from the pyshacl report
        violations = len(re.findall(r'Severity: sh:Violation', output))
        warnings = len(re.findall(r'Severity: sh:Warning', output))
        infos = len(re.findall(r'Severity: sh:Info', output))
        return violations, warnings, infos, output.strip()
    except subprocess.TimeoutExpired:
        return -1, 0, 0, "TIMEOUT"
    except Exception as e:
        return -1, 0, 0, str(e)


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
