#!/usr/bin/env python3
"""Batch validate CDIF metadata files from sitemap groups.

Runs FrameAndValidate.py (JSON Schema) and ShaclValidation/ShaclJSONLDContext.py
(SHACL) on each file, collecting pass/fail results.
"""

import subprocess
import sys
import os
import json
from pathlib import Path

VALIDATION_DIR = Path(__file__).parent
FRAME_VALIDATE = VALIDATION_DIR / "FrameAndValidate.py"
SHACL_VALIDATE = VALIDATION_DIR / "ShaclValidation" / "ShaclJSONLDContext.py"
SHACL_SHAPES = VALIDATION_DIR / "CDIF-Complete-Shapes.ttl"

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
    """Run SHACL validation and return (passed: bool, output: str)."""
    try:
        result = subprocess.run(
            [sys.executable, str(SHACL_VALIDATE), str(filepath), str(SHACL_SHAPES)],
            capture_output=True, text=True, timeout=120,
            cwd=str(VALIDATION_DIR)
        )
        output = result.stdout + result.stderr
        passed = result.returncode == 0
        return passed, output.strip()
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as e:
        return False, str(e)


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
    overall_shacl_pass = 0
    overall_shacl_fail = 0

    for group_name, files in groups.items():
        print(f"\n{'='*60}")
        print(f"Group: {group_name} ({len(files)} files)")
        print(f"{'='*60}")

        group_results = []
        schema_pass = 0
        schema_fail = 0
        shacl_pass = 0
        shacl_fail = 0

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
            sh_passed = None
            if any(fname.endswith(s) for s in SHACL_EXCLUDE_SUFFIXES):
                print(f"  SHACL:       SKIP (generated output)")
            else:
                sh_passed, sh_output = run_shacl_validation(filepath)
                if sh_passed:
                    shacl_pass += 1
                    print(f"  SHACL:       PASS")
                else:
                    shacl_fail += 1
                    errors = extract_errors(sh_output)
                    print(f"  SHACL:       FAIL")
                    for e in errors:
                        print(f"    {e}")

            shacl_skipped = any(fname.endswith(s) for s in SHACL_EXCLUDE_SUFFIXES)
            group_results.append({
                "file": fname,
                "schema_pass": js_passed,
                "shacl_pass": None if shacl_skipped else sh_passed,
            })

        all_results[group_name] = group_results
        overall_schema_pass += schema_pass
        overall_schema_fail += schema_fail
        overall_shacl_pass += shacl_pass
        overall_shacl_fail += shacl_fail

        print(f"\n--- {group_name} Summary ---")
        print(f"  JSON Schema: {schema_pass} pass, {schema_fail} fail")
        print(f"  SHACL:       {shacl_pass} pass, {shacl_fail} fail")

    # Overall summary
    print(f"\n{'='*60}")
    print(f"OVERALL SUMMARY ({total_files} files)")
    print(f"{'='*60}")
    print(f"  JSON Schema: {overall_schema_pass} pass, {overall_schema_fail} fail")
    print(f"  SHACL:       {overall_shacl_pass} pass, {overall_shacl_fail} fail")

    # List all failures
    print(f"\n--- Failed Files ---")
    any_failures = False
    for group_name, results in all_results.items():
        for r in results:
            schema_failed = not r["schema_pass"]
            shacl_failed = r["shacl_pass"] is not None and not r["shacl_pass"]
            if schema_failed or shacl_failed:
                any_failures = True
                status = []
                if schema_failed:
                    status.append("schema")
                if shacl_failed:
                    status.append("shacl")
                print(f"  [{group_name}] {r['file']}: {', '.join(status)}")
    if not any_failures:
        print("  None! All files passed both validations.")


if __name__ == "__main__":
    main()
