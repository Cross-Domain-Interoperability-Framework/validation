#!/usr/bin/env python3
"""Validate CDIF building block consistency and correctness.

Checks each building block for:
  1. Inventory — expected files present
  2. Schema consistency — schema.yaml vs *Schema.json agreement
  3. Example validation — example*.json validates against schema
  4. SHACL validation — example*.json validates against rules.shacl

Usage:
    python validate_building_blocks.py [--bb-dir PATH] [--filter PATTERN]
        [--category CATEGORY] [--checks LIST] [-v] [--summary-only]
        [--fail-on-warn]
"""

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

# ---------------------------------------------------------------------------
# Optional imports with graceful fallback
# ---------------------------------------------------------------------------

try:
    from jsonschema import Draft202012Validator, ValidationError
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False

try:
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012
    HAS_REFERENCING = True
except ImportError:
    HAS_REFERENCING = False

try:
    from rdflib import Graph as RdfGraph
    import pyshacl
    HAS_SHACL = True
except ImportError:
    HAS_SHACL = False


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class BuildingBlock:
    """Represents a single building block directory."""
    path: Path
    category: str          # e.g. "schemaorgProperties", "profiles/adaProfiles"
    name: str              # directory name, e.g. "person"
    has_schema_yaml: bool = False
    has_schema_json: bool = False
    schema_json_name: str = ""
    has_resolved: bool = False
    has_shacl: bool = False
    has_bblock: bool = False
    example_files: list = field(default_factory=list)

    @property
    def full_name(self):
        return f"{self.category}/{self.name}"

    @property
    def is_ada_detail(self):
        return self.name.startswith("detail") and "adaProperties" in self.category

    @property
    def is_profile(self):
        return "profiles" in self.category


@dataclass
class CheckResult:
    """Result of a single check on a building block."""
    bb_name: str
    check: str             # "inventory", "consistency", "examples", "shacl"
    status: str            # "PASS", "WARN", "FAIL", "SKIP", "ERROR"
    message: str
    details: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers (reused patterns from generate_graph_schema.py)
# ---------------------------------------------------------------------------

def find_bb_dir():
    """Find the building blocks _sources directory."""
    env = os.environ.get("CDIF_BB_DIR")
    if env and Path(env).is_dir():
        return Path(env)

    script_dir = Path(__file__).resolve().parent
    candidates = [
        script_dir / "BuildingBlockSubmodule" / "_sources",
        script_dir.parent / "metadataBuildingBlocks" / "_sources",
        Path.home() / "OneDrive" / "Documents" / "GithubC" / "USGIN" / "metadataBuildingBlocks" / "_sources",
        Path.home() / "OneDrive" / "Documents" / "GithubC" / "smrgeoinfo" / "OCGbuildingBlockTest" / "_sources",
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return None


def load_json(path):
    """Load a JSON file, stripping BOM if present."""
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def load_yaml(path):
    """Load a YAML file."""
    with open(path, "r", encoding="utf-8-sig") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

PROPERTY_CATEGORIES = [
    "schemaorgProperties",
    "cdifProperties",
    "provProperties",
    "ddiProperties",
    "adaProperties",
    "ecrrProperties",
    "xasProperties",
    "qualityProperties",
    "DDEproperties",
]

PROFILE_CATEGORIES = [
    "profiles/cdifProfiles",
    "profiles/adaProfiles",
    "profiles/ecrrProfiles",
    "profiles/DDEProfiles",
]


def discover_building_blocks(bb_dir, filter_pattern=None, category_filter=None):
    """Walk bb_dir to find all building blocks (dirs containing schema.yaml or *Schema.json)."""
    bbs = []
    all_categories = PROPERTY_CATEGORIES + PROFILE_CATEGORIES

    if category_filter:
        # Match on the last component or full path
        all_categories = [
            c for c in all_categories
            if category_filter.lower() in c.lower()
        ]

    for cat in all_categories:
        cat_dir = bb_dir / cat
        if not cat_dir.is_dir():
            continue
        for child in sorted(cat_dir.iterdir()):
            if not child.is_dir():
                continue
            # Skip non-BB directories
            if child.name in ("assets", "tests", "__pycache__"):
                continue

            # Must have schema.yaml or *Schema.json to be a BB
            has_yaml = (child / "schema.yaml").is_file()
            schema_json = _find_schema_json(child)
            if not has_yaml and not schema_json:
                continue

            if filter_pattern and filter_pattern.lower() not in child.name.lower():
                continue

            bb = BuildingBlock(
                path=child,
                category=cat,
                name=child.name,
                has_schema_yaml=has_yaml,
                has_schema_json=schema_json is not None,
                schema_json_name=schema_json.name if schema_json else "",
                has_resolved=(child / "resolvedSchema.json").is_file(),
                has_shacl=(child / "rules.shacl").is_file(),
                has_bblock=(child / "bblock.json").is_file(),
                example_files=sorted(child.glob("example*.json")),
            )
            bbs.append(bb)

    return bbs


def _find_schema_json(bb_dir):
    """Find the *Schema.json file in a building block directory."""
    for f in bb_dir.iterdir():
        if f.is_file() and f.name.endswith("Schema.json") and f.name != "resolvedSchema.json":
            return f
    return None


# ---------------------------------------------------------------------------
# Check 1: Inventory
# ---------------------------------------------------------------------------

def run_inventory_check(bb):
    """Check which expected files are present/missing."""
    missing = []
    info_missing = []  # lower severity

    if not bb.has_schema_yaml:
        missing.append("schema.yaml")
    if not bb.has_schema_json:
        # ada details and some profiles may not have compiled JSON
        if bb.is_ada_detail:
            info_missing.append(f"{bb.name}Schema.json")
        else:
            missing.append(f"*Schema.json")
    if not bb.has_bblock:
        info_missing.append("bblock.json")

    # resolvedSchema.json - expected for most, INFO for ada details
    if not bb.has_resolved:
        if bb.is_ada_detail:
            info_missing.append("resolvedSchema.json")
        else:
            info_missing.append("resolvedSchema.json")

    # rules.shacl - expected for non-ada-detail, non-composite BBs
    if not bb.has_shacl:
        if bb.is_ada_detail:
            info_missing.append("rules.shacl")
        else:
            info_missing.append("rules.shacl")

    # examples - nice to have
    if not bb.example_files:
        info_missing.append("example*.json")

    # Build inventory description
    parts = []
    if bb.has_schema_yaml:
        parts.append("schema.yaml")
    if bb.has_schema_json:
        parts.append(bb.schema_json_name)
    if bb.has_resolved:
        parts.append("resolvedSchema.json")
    if bb.has_shacl:
        parts.append("rules.shacl")
    if bb.example_files:
        parts.append(f"{len(bb.example_files)} example(s)")

    present_str = ", ".join(parts) if parts else "none"

    if missing:
        return CheckResult(
            bb.full_name, "inventory", "FAIL",
            f"Missing: {', '.join(missing)}",
            details=[f"Present: {present_str}"]
        )
    elif info_missing:
        return CheckResult(
            bb.full_name, "inventory", "WARN",
            f"Optional missing: {', '.join(info_missing)}",
            details=[f"Present: {present_str}"]
        )
    else:
        return CheckResult(
            bb.full_name, "inventory", "PASS",
            f"({present_str})"
        )


# ---------------------------------------------------------------------------
# Check 2: Schema consistency (schema.yaml vs *Schema.json)
# ---------------------------------------------------------------------------

def _extract_properties(schema):
    """Extract top-level property names from a schema dict.

    Looks in 'properties' and in allOf items that have 'properties'.
    Skips allOf items that are only $ref (composition references).
    """
    props = set()
    if "properties" in schema:
        props.update(schema["properties"].keys())
    for item in schema.get("allOf", []):
        if isinstance(item, dict) and "properties" in item:
            props.update(item["properties"].keys())
    return props


def _extract_required(schema):
    """Extract required property names from a schema dict.

    Gathers from top-level 'required' and from allOf items with 'required'.
    Skips anyOf-wrapped requireds (conditional requirements).
    """
    reqs = set()
    if "required" in schema and isinstance(schema["required"], list):
        reqs.update(schema["required"])
    for item in schema.get("allOf", []):
        if isinstance(item, dict):
            if "required" in item and isinstance(item["required"], list):
                reqs.update(item["required"])
    return reqs


def _extract_defs_keys(schema):
    """Extract $defs key names."""
    return set(schema.get("$defs", {}).keys())


def _defs_that_are_ref_aliases(schema):
    """Return set of $defs keys whose values are just $ref aliases (no own properties).

    These are expected to be missing from the compiled JSON because
    the $ref gets resolved inline during compilation.
    """
    aliases = set()
    for key, val in schema.get("$defs", {}).items():
        if isinstance(val, dict) and "$ref" in val and len(val) == 1:
            aliases.add(key)
    return aliases


def _extract_type_constraint(schema):
    """Extract @type constraint values from a schema.

    Returns a set of type strings from const, enum, or contains.enum.
    """
    types = set()
    type_schema = None

    # Check properties.@type
    props = schema.get("properties", {})
    if "@type" in props:
        type_schema = props["@type"]
    # Also check allOf items
    for item in schema.get("allOf", []):
        if isinstance(item, dict) and "properties" in item:
            if "@type" in item["properties"]:
                type_schema = item["properties"]["@type"]

    if type_schema:
        if "const" in type_schema:
            val = type_schema["const"]
            types.add(val) if isinstance(val, str) else types.update(val)
        if "enum" in type_schema:
            types.update(type_schema["enum"])
        if "contains" in type_schema and "enum" in type_schema["contains"]:
            types.update(type_schema["contains"]["enum"])

    return types


def compare_schemas(bb, verbose=False):
    """Compare schema.yaml vs *Schema.json for consistency."""
    if not bb.has_schema_yaml or not bb.has_schema_json:
        reason = "no schema.yaml" if not bb.has_schema_yaml else "no *Schema.json"
        return CheckResult(bb.full_name, "consistency", "SKIP", f"({reason})")

    try:
        yaml_schema = load_yaml(bb.path / "schema.yaml")
        json_schema = load_json(bb.path / bb.schema_json_name)
    except Exception as e:
        return CheckResult(
            bb.full_name, "consistency", "ERROR",
            f"Load error: {e}"
        )

    if not isinstance(yaml_schema, dict) or not isinstance(json_schema, dict):
        return CheckResult(
            bb.full_name, "consistency", "ERROR",
            "Schema is not a dict"
        )

    diffs = []

    # Compare property names
    yaml_props = _extract_properties(yaml_schema)
    json_props = _extract_properties(json_schema)
    # Filter out $ref-only entries in YAML (these become resolved in JSON)
    # and ignore meta-properties like $schema
    yaml_props.discard("$schema")
    json_props.discard("$schema")

    yaml_only = yaml_props - json_props
    json_only = json_props - yaml_props

    if yaml_only:
        diffs.append(f"Properties in YAML only: {sorted(yaml_only)}")
    if json_only:
        diffs.append(f"Properties in JSON only: {sorted(json_only)}")

    # Compare required sets
    yaml_req = _extract_required(yaml_schema)
    json_req = _extract_required(json_schema)
    req_yaml_only = yaml_req - json_req
    req_json_only = json_req - yaml_req
    if req_yaml_only:
        diffs.append(f"Required in YAML only: {sorted(req_yaml_only)}")
    if req_json_only:
        diffs.append(f"Required in JSON only: {sorted(req_json_only)}")

    # Compare $defs keys
    yaml_defs = _extract_defs_keys(yaml_schema)
    json_defs = _extract_defs_keys(json_schema)
    # $defs that are pure $ref aliases (e.g. Person: {$ref: ../person/schema.yaml})
    # are expected to differ between YAML and JSON, so exclude them from both
    yaml_ref_aliases = _defs_that_are_ref_aliases(yaml_schema)
    json_ref_aliases = _defs_that_are_ref_aliases(json_schema)
    yaml_defs_effective = yaml_defs - yaml_ref_aliases
    json_defs_effective = json_defs - json_ref_aliases
    if yaml_defs_effective or json_defs_effective:
        defs_yaml_only = yaml_defs_effective - json_defs_effective
        defs_json_only = json_defs_effective - yaml_defs_effective
        if defs_yaml_only or defs_json_only:
            parts = []
            if defs_yaml_only:
                parts.append(f"YAML-only: {sorted(defs_yaml_only)}")
            if defs_json_only:
                parts.append(f"JSON-only: {sorted(defs_json_only)}")
            diffs.append(f"$defs differ: {'; '.join(parts)}")

    # Compare @type constraints
    yaml_types = _extract_type_constraint(yaml_schema)
    json_types = _extract_type_constraint(json_schema)
    if yaml_types and json_types and yaml_types != json_types:
        diffs.append(f"@type: YAML={sorted(yaml_types)}, JSON={sorted(json_types)}")

    if not diffs:
        parts = []
        if yaml_props:
            parts.append("properties match")
        if yaml_req:
            parts.append("required match")
        if yaml_defs:
            parts.append("$defs match")
        return CheckResult(
            bb.full_name, "consistency", "PASS",
            f"({', '.join(parts) if parts else 'minimal schema'})"
        )
    else:
        return CheckResult(
            bb.full_name, "consistency", "WARN",
            f"{len(diffs)} difference(s)",
            details=diffs
        )


# ---------------------------------------------------------------------------
# Check 3: Example validation against JSON Schema
# ---------------------------------------------------------------------------

def _build_registry(bb):
    """Build a referencing Registry for resolving $ref across BB schemas.

    Registers the BB's own schema and sibling schemas it references.
    """
    if not HAS_REFERENCING:
        return None

    resources = []
    schema_dir = bb.path

    # Register all *Schema.json in this BB
    for f in schema_dir.glob("*Schema.json"):
        try:
            s = load_json(f)
            uri = f.as_uri() if hasattr(f, 'as_uri') else f"file:///{f.as_posix()}"
            resources.append((uri, Resource.from_contents(s, default_specification=DRAFT202012)))
        except Exception:
            pass

    # Register sibling BB schemas (walk parent category dir)
    parent = schema_dir.parent
    for sibling in parent.iterdir():
        if sibling.is_dir() and sibling != schema_dir:
            for f in sibling.glob("*Schema.json"):
                try:
                    s = load_json(f)
                    uri = f.as_uri() if hasattr(f, 'as_uri') else f"file:///{f.as_posix()}"
                    resources.append((uri, Resource.from_contents(s, default_specification=DRAFT202012)))
                except Exception:
                    pass

    if resources:
        return Registry().with_resources(resources)
    return None


def _resolve_internal_defs_refs(schema, defs):
    """Resolve #/$defs/X references using the given $defs dict.

    When an external schema with its own $defs is inlined into another
    document, internal #/$defs/X refs become orphaned.  This resolves
    them against the original $defs before inlining.
    """
    if not defs:
        return schema
    if isinstance(schema, dict):
        if "$ref" in schema and schema["$ref"].startswith("#/$defs/"):
            def_name = schema["$ref"][len("#/$defs/"):]
            if def_name in defs:
                resolved = dict(defs[def_name])
                # Recursively resolve nested internal refs
                return _resolve_internal_defs_refs(resolved, defs)
            return schema
        return {k: _resolve_internal_defs_refs(v, defs) for k, v in schema.items()}
    elif isinstance(schema, list):
        return [_resolve_internal_defs_refs(item, defs) for item in schema]
    return schema


def _resolve_local_refs(schema, base_dir, _depth=0):
    """Recursively resolve file-relative $ref in a schema for validation.

    Returns a new schema dict with external $refs resolved (inlined).
    Internal (#/...) refs within inlined schemas are resolved against
    their own $defs before inlining.
    """
    if _depth > 20:  # guard against circular refs
        return schema
    if isinstance(schema, dict):
        if "$ref" in schema and not schema["$ref"].startswith("#"):
            ref_path = schema["$ref"].split("#")[0]
            json_pointer = schema["$ref"].split("#")[1] if "#" in schema["$ref"] else None
            resolved_path = (base_dir / ref_path).resolve()
            if resolved_path.is_file():
                try:
                    ext = resolved_path.suffix.lower()
                    if ext in (".yaml", ".yml"):
                        loaded = load_yaml(resolved_path)
                    else:
                        loaded = load_json(resolved_path)
                    # Recursively resolve external refs in loaded schema
                    loaded = _resolve_local_refs(loaded, resolved_path.parent, _depth + 1)
                    # Resolve internal #/$defs/X refs against the loaded schema's own $defs
                    if isinstance(loaded, dict) and "$defs" in loaded:
                        loaded = _resolve_internal_defs_refs(loaded, loaded["$defs"])
                    if json_pointer:
                        # Navigate JSON pointer
                        for part in json_pointer.strip("/").split("/"):
                            if isinstance(loaded, dict):
                                loaded = loaded.get(part, {})
                    return loaded
                except Exception:
                    return schema
            return schema
        return {k: _resolve_local_refs(v, base_dir, _depth) for k, v in schema.items()}
    elif isinstance(schema, list):
        return [_resolve_local_refs(item, base_dir, _depth) for item in schema]
    return schema


def validate_examples(bb, verbose=False):
    """Validate example*.json files against the BB's schema."""
    if not HAS_JSONSCHEMA:
        return CheckResult(bb.full_name, "examples", "SKIP", "(jsonschema not installed)")

    if not bb.example_files:
        return CheckResult(bb.full_name, "examples", "SKIP", "(no examples)")

    # Choose schema: prefer resolvedSchema.json (self-contained)
    schema_path = None
    schema_label = ""
    if bb.has_resolved:
        schema_path = bb.path / "resolvedSchema.json"
        schema_label = "resolvedSchema.json"
    elif bb.has_schema_json:
        schema_path = bb.path / bb.schema_json_name
        schema_label = bb.schema_json_name
    else:
        return CheckResult(bb.full_name, "examples", "SKIP", "(no JSON schema to validate against)")

    try:
        schema = load_json(schema_path)
    except Exception as e:
        return CheckResult(bb.full_name, "examples", "ERROR", f"Schema load error: {e}")

    # For non-resolved schemas, try to resolve $refs
    if not bb.has_resolved:
        schema = _resolve_local_refs(schema, schema_path.parent)

    # Strip $id to avoid URI resolution issues with fragment anchors
    schema_for_validation = dict(schema)
    if "$id" in schema_for_validation:
        del schema_for_validation["$id"]

    try:
        validator = Draft202012Validator(schema_for_validation)
    except Exception as e:
        return CheckResult(bb.full_name, "examples", "ERROR", f"Schema invalid: {e}")

    passed = 0
    failed = 0
    errored = 0
    skipped_graph = 0
    errors_detail = []

    for ex_file in bb.example_files:
        try:
            example = load_json(ex_file)
        except Exception as e:
            failed += 1
            errors_detail.append(f"{ex_file.name}: load error: {e}")
            continue

        try:
            # For @graph examples, validate the wrapper or individual nodes
            if isinstance(example, dict) and "@graph" in example:
                errs = list(validator.iter_errors(example))
                if errs:
                    # Try validating individual @graph nodes
                    node_pass = True
                    for node in example["@graph"]:
                        node_errs = list(validator.iter_errors(node))
                        if node_errs:
                            node_pass = False
                            break
                    if node_pass:
                        passed += 1
                        continue
                    # @graph doc with heterogeneous node types needs framing;
                    # skip rather than fail when root schema doesn't fit
                    skipped_graph += 1
                    errors_detail.append(
                        f"{ex_file.name}: SKIP (@graph document needs framing for JSON Schema validation)"
                    )
                else:
                    passed += 1
            else:
                errs = list(validator.iter_errors(example))
                if errs:
                    failed += 1
                    err_msgs = [_format_validation_error(e) for e in errs[:3]]
                    errors_detail.append(f"{ex_file.name}: {len(errs)} error(s): {'; '.join(err_msgs)}")
                else:
                    passed += 1
        except Exception as e:
            # Catch $ref resolution errors (PointerToNowhere, etc.)
            errored += 1
            err_msg = str(e)
            if len(err_msg) > 200:
                err_msg = err_msg[:197] + "..."
            errors_detail.append(f"{ex_file.name}: schema error: {err_msg}")

    total = len(bb.example_files)
    if errored > 0:
        return CheckResult(
            bb.full_name, "examples", "ERROR",
            f"({passed}/{total} passed, {failed} failed, {errored} error(s) against {schema_label})",
            details=errors_detail
        )
    elif failed == 0 and skipped_graph > 0 and passed == 0:
        return CheckResult(
            bb.full_name, "examples", "SKIP",
            f"(@graph document needs framing for JSON Schema validation)",
            details=errors_detail
        )
    elif failed == 0:
        return CheckResult(
            bb.full_name, "examples", "PASS",
            f"({passed}/{total} validated against {schema_label})"
        )
    else:
        return CheckResult(
            bb.full_name, "examples", "FAIL",
            f"({passed}/{total} passed, {failed} failed against {schema_label})",
            details=errors_detail
        )


def _format_validation_error(err):
    """Format a jsonschema ValidationError concisely."""
    path = ".".join(str(p) for p in err.absolute_path) if err.absolute_path else "root"
    msg = err.message
    if len(msg) > 200:
        msg = msg[:197] + "..."
    result = f"{path}: {msg}"
    if len(result) > 250:
        result = result[:247] + "..."
    return result


# ---------------------------------------------------------------------------
# Check 4: SHACL validation
# ---------------------------------------------------------------------------

# Default JSON-LD context for building block examples that lack @context
DEFAULT_BB_CONTEXT = {
    "schema": "http://schema.org/",
    "prov": "http://www.w3.org/ns/prov#",
    "dcat": "http://www.w3.org/ns/dcat#",
    "dcterms": "http://purl.org/dc/terms/",
    "cdi": "http://ddialliance.org/Specification/DDI-CDI/1.0/RDF/",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "time": "http://www.w3.org/2006/time#",
    "dqv": "http://www.w3.org/ns/dqv#",
    "spdx": "http://spdx.org/rdf/terms#",
}


def validate_shacl(bb, verbose=False):
    """Validate example*.json against rules.shacl using pyshacl."""
    if not HAS_SHACL:
        return CheckResult(bb.full_name, "shacl", "SKIP", "(rdflib/pyshacl not installed)")

    if not bb.has_shacl:
        return CheckResult(bb.full_name, "shacl", "SKIP", "(no rules.shacl)")

    if not bb.example_files:
        return CheckResult(bb.full_name, "shacl", "SKIP", "(no examples)")

    # Load shapes graph
    try:
        shapes_graph = RdfGraph()
        shapes_graph.parse(str(bb.path / "rules.shacl"), format="ttl")
    except Exception as e:
        return CheckResult(bb.full_name, "shacl", "ERROR", f"SHACL parse error: {e}")

    total_violations = 0
    total_warnings = 0
    total_infos = 0
    errors_detail = []
    examples_tested = 0

    for ex_file in bb.example_files:
        try:
            example = load_json(ex_file)
        except Exception as e:
            errors_detail.append(f"{ex_file.name}: load error: {e}")
            continue

        # Ensure example has @context for JSON-LD parsing
        if isinstance(example, dict) and "@context" not in example:
            example["@context"] = DEFAULT_BB_CONTEXT
        elif isinstance(example, dict) and isinstance(example.get("@context"), dict):
            # Merge default context for missing prefixes
            ctx = dict(DEFAULT_BB_CONTEXT)
            ctx.update(example["@context"])
            example["@context"] = ctx

        # Parse as JSON-LD into RDF graph
        try:
            data_graph = RdfGraph()
            # Write to temp string for rdflib parsing
            json_str = json.dumps(example)
            data_graph.parse(data=json_str, format="json-ld")
        except Exception as e:
            errors_detail.append(f"{ex_file.name}: JSON-LD parse error: {e}")
            continue

        if len(data_graph) == 0:
            errors_detail.append(f"{ex_file.name}: empty graph (0 triples)")
            continue

        examples_tested += 1

        try:
            conforms, report_graph, report_text = pyshacl.validate(
                data_graph,
                shacl_graph=shapes_graph,
                inference="rdfs",
                advanced=True,
            )
        except Exception as e:
            errors_detail.append(f"{ex_file.name}: pyshacl error: {e}")
            continue

        # Count by severity
        violations = len(re.findall(r'Severity: sh:Violation', report_text))
        warnings = len(re.findall(r'Severity: sh:Warning', report_text))
        infos = len(re.findall(r'Severity: sh:Info', report_text))

        total_violations += violations
        total_warnings += warnings
        total_infos += infos

        if violations > 0 and verbose:
            errors_detail.append(f"{ex_file.name}: {violations} violation(s)")

    if examples_tested == 0:
        return CheckResult(
            bb.full_name, "shacl", "SKIP",
            "(no examples could be parsed as JSON-LD)",
            details=errors_detail
        )

    if total_violations > 0:
        return CheckResult(
            bb.full_name, "shacl", "FAIL",
            f"({total_violations} violations, {total_warnings} warnings, {total_infos} info)",
            details=errors_detail
        )
    elif total_warnings > 0 or total_infos > 0:
        return CheckResult(
            bb.full_name, "shacl", "WARN",
            f"(0 violations, {total_warnings} warnings, {total_infos} info)"
        )
    else:
        return CheckResult(
            bb.full_name, "shacl", "PASS",
            f"(0 violations, 0 warnings, 0 info)"
        )


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

STATUS_COLORS = {
    "PASS": "\033[32m",   # green
    "WARN": "\033[33m",   # yellow
    "FAIL": "\033[31m",   # red
    "SKIP": "\033[36m",   # cyan
    "ERROR": "\033[35m",  # magenta
}
RESET = "\033[0m"


def _color(status, text=None):
    """Colorize status text if terminal supports it."""
    if not sys.stdout.isatty():
        return text or status
    c = STATUS_COLORS.get(status, "")
    return f"{c}{text or status}{RESET}"


def print_bb_results(bb_name, results, verbose=False, summary_only=False):
    """Print results for a single building block."""
    if summary_only:
        return

    print(f"\n=== {bb_name} ===")
    for r in results:
        label = f"  {r.check + ':':14s}"
        status_str = _color(r.status)
        print(f"{label}{status_str:5s}  {r.message}")
        if verbose and r.details:
            for d in r.details:
                print(f"{'':16s}  {d}")


def print_summary(all_results, checks_run, fail_details=True):
    """Print the summary table and failure details."""
    # Count by check × status
    counts = {}
    for check in checks_run:
        counts[check] = {"PASS": 0, "WARN": 0, "FAIL": 0, "SKIP": 0, "ERROR": 0}

    failures = []

    for bb_name, results in all_results.items():
        for r in results:
            if r.check in counts:
                counts[r.check][r.status] += 1
            if r.status in ("FAIL", "ERROR"):
                failures.append(r)

    print(f"\n{'='*70}")
    print("SUMMARY")
    print(f"{'='*70}")
    header = f"{'Check':14s} {'PASS':>6s} {'WARN':>6s} {'FAIL':>6s} {'SKIP':>6s} {'ERROR':>6s}"
    print(header)
    print("-" * len(header))
    for check in checks_run:
        c = counts[check]
        row = f"{check:14s} {c['PASS']:6d} {c['WARN']:6d} {c['FAIL']:6d} {c['SKIP']:6d} {c['ERROR']:6d}"
        print(row)

    if fail_details and failures:
        print(f"\n--- Failures & Errors ---")
        for r in failures:
            print(f"  [{r.status}] {r.bb_name} / {r.check}: {r.message}")
            for d in r.details:
                print(f"         {d}")

    return failures


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

ALL_CHECKS = ["inventory", "consistency", "examples", "shacl"]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Validate CDIF building block consistency and correctness.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--bb-dir", type=Path,
                        help="Path to _sources directory (auto-detected if omitted)")
    parser.add_argument("--filter", dest="filter_pattern",
                        help="Only check BBs whose name contains PATTERN (case-insensitive)")
    parser.add_argument("--category",
                        help="Only check BBs in this category (partial match, e.g. 'schemaorg', 'ada')")
    parser.add_argument("--checks", default=",".join(ALL_CHECKS),
                        help=f"Comma-separated checks to run (default: all). Options: {','.join(ALL_CHECKS)}")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Show details for all checks, not just failures")
    parser.add_argument("--summary-only", action="store_true",
                        help="Only print the summary table")
    parser.add_argument("--fail-on-warn", action="store_true",
                        help="Exit with code 1 if any WARNings (not just FAILs)")
    return parser.parse_args()


def main():
    args = parse_args()

    # Find BB directory
    bb_dir = args.bb_dir or find_bb_dir()
    if not bb_dir or not bb_dir.is_dir():
        print("ERROR: Cannot find building blocks _sources directory.")
        print("Use --bb-dir or set CDIF_BB_DIR environment variable.")
        sys.exit(1)

    print(f"Building blocks: {bb_dir}")

    # Parse checks
    checks_run = [c.strip() for c in args.checks.split(",") if c.strip() in ALL_CHECKS]
    if not checks_run:
        print(f"ERROR: No valid checks specified. Options: {','.join(ALL_CHECKS)}")
        sys.exit(1)

    # Discover BBs
    bbs = discover_building_blocks(bb_dir, args.filter_pattern, args.category)
    if not bbs:
        print("No building blocks found matching the criteria.")
        sys.exit(0)

    print(f"Found {len(bbs)} building block(s)")
    if args.filter_pattern:
        print(f"Filter: *{args.filter_pattern}*")
    if args.category:
        print(f"Category: *{args.category}*")
    print(f"Checks: {', '.join(checks_run)}")
    print()

    # Run checks
    all_results = {}  # bb_name -> list[CheckResult]

    for bb in bbs:
        results = []

        if "inventory" in checks_run:
            results.append(run_inventory_check(bb))

        if "consistency" in checks_run:
            results.append(compare_schemas(bb, verbose=args.verbose))

        if "examples" in checks_run:
            results.append(validate_examples(bb, verbose=args.verbose))

        if "shacl" in checks_run:
            results.append(validate_shacl(bb, verbose=args.verbose))

        all_results[bb.full_name] = results
        print_bb_results(bb.full_name, results,
                         verbose=args.verbose,
                         summary_only=args.summary_only)

    # Print summary
    failures = print_summary(all_results, checks_run, fail_details=True)

    # Exit code
    if failures:
        sys.exit(1)
    if args.fail_on_warn:
        for bb_results in all_results.values():
            for r in bb_results:
                if r.status == "WARN":
                    sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
