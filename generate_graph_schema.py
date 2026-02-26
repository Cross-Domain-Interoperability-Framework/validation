#!/usr/bin/env python3
"""
Generate a JSON Schema for validating flattened JSON-LD graphs of CDIF metadata.

Reads CDIF building block source schemas from BuildingBlockSubmodule/_sources/
and produces a single self-contained schema (CDIF-graph-schema-2026.json) that
validates @graph-based (flattened) JSON-LD documents.

Usage:
    python generate_graph_schema.py [--bb-dir PATH] [--output PATH]

The --bb-dir defaults to the metadataBuildingBlocks/_sources/ directory
detected relative to this script or via the CDIF_BB_DIR environment variable.
"""

import argparse
import copy
import json
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration: type dispatch table (ordered, most specific first)
# ---------------------------------------------------------------------------

# Each entry: (dispatch_type, defs_name, description)
# Sources are loaded separately below.
TYPE_DISPATCH = [
    ("cdi:StructuredDataSet", "type-StructuredDataSet"),
    ("cdi:TabularTextDataSet", "type-TabularTextDataSet"),
    ("cdi:LongStructureDataSet", "type-LongStructureDataSet"),
    ("cdi:InstanceVariable", "type-InstanceVariable"),
    ("cdi:Identifier", "type-Identifier"),
    ("dcat:CatalogRecord", "type-CatalogRecord"),
    ("schema:Dataset", "type-Dataset"),
    ("schema:Person", "type-Person"),
    ("schema:Organization", "type-Organization"),
    ("schema:PropertyValue", "type-PropertyValue"),
    ("schema:DefinedTerm", "type-DefinedTerm"),
    ("schema:CreativeWork", "type-CreativeWork"),
    ("schema:DataDownload", "type-DataDownload"),
    ("schema:MediaObject", "type-MediaObject"),
    ("schema:WebAPI", "type-WebAPI"),
    ("schema:Action", "type-Action"),
    ("schema:HowTo", "type-HowTo"),
    ("schema:Place", "type-Place"),
    ("time:ProperInterval", "type-ProperInterval"),
    ("schema:MonetaryGrant", "type-MonetaryGrant"),
    ("schema:Role", "type-Role"),
    ("prov:Activity", "type-Activity"),
    ("dqv:QualityMeasurement", "type-QualityMeasurement"),
    ("schema:Claim", "type-Claim"),
]

# Mapping from building-block $ref aliases to output $defs names
BB_REF_MAP = {
    "person": "type-Person",
    "personSchema.json": "type-Person",
    "organization": "type-Organization",
    "organizationSchema.json": "type-Organization",
    "identifier": "type-Identifier",
    "identifierSchema.json": "type-Identifier",
    "definedTerm": "type-DefinedTerm",
    "definedTermSchema.json": "type-DefinedTerm",
    "labeledLink": "type-CreativeWork",
    "labeledLinkSchema.json": "type-CreativeWork",
    "dataDownload": "type-DataDownload",
    "dataDownloadSchema.json": "type-DataDownload",
    "webAPI": "type-WebAPI",
    "webAPISchema.json": "type-WebAPI",
    "action": "type-Action",
    "actionSchema.json": "type-Action",
    "spatialExtent": "type-Place",
    "spatialExtentSchema.json": "type-Place",
    "temporalExtent": "type-ProperInterval",
    "temporalExtentSchema.json": "type-ProperInterval",
    "funder": "type-MonetaryGrant",
    "funderSchema.json": "type-MonetaryGrant",
    "agentInRole": "type-Role",
    "agentInRoleSchema.json": "type-Role",
    "variableMeasured": "type-InstanceVariable",
    "variableMeasuredSchema.json": "type-InstanceVariable",
    "cdifCatalogRecord": "type-CatalogRecord",
    "cdifCatalogRecordSchema.json": "type-CatalogRecord",
    "additionalProperty": "type-PropertyValue",
    "additionalPropertySchema.json": "type-PropertyValue",
    "generatedBy": "type-Activity",
    "generatedBySchema.json": "type-Activity",
    "cdifProv": "type-Activity",
    "cdifProvSchema.json": "type-Activity",
    "derivedFrom": "type-Dataset",  # derivedFrom is a property on Dataset, not a dispatch type
    "derivedFromSchema.json": "type-Dataset",
    "qualityMeasure": "type-QualityMeasurement",
    "qualityMeasureSchema.json": "type-QualityMeasurement",
    "cdifDataCube": "type-StructuredDataSet",
    "cdifDataCubeSchema.json": "type-StructuredDataSet",
    "cdifTabularData": "type-TabularTextDataSet",
    "cdifTabularDataSchema.json": "type-TabularTextDataSet",
    "cdifLongData": "type-LongStructureDataSet",
    "cdifLongDataSchema.json": "type-LongStructureDataSet",
    "cdiVariableMeasured": "type-InstanceVariable",
    "cdiVariableMeasuredSchema.json": "type-InstanceVariable",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def find_bb_dir():
    """Find the building blocks _sources directory."""
    # Try environment variable first
    env = os.environ.get("CDIF_BB_DIR")
    if env and Path(env).is_dir():
        return Path(env)

    # Try common relative locations
    script_dir = Path(__file__).resolve().parent
    candidates = [
        script_dir / "BuildingBlockSubmodule" / "_sources",
        script_dir.parent / "metadataBuildingBlocks" / "_sources",
        # Windows OneDrive paths
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


def resolve_ref_path(ref_str, base_dir):
    """Resolve a relative file $ref to an absolute path."""
    if ref_str.startswith("#"):
        return None  # internal ref
    # Strip any JSON pointer suffix after the filename
    file_part = ref_str.split("#")[0]
    return (base_dir / file_part).resolve()


def ref_to_bb_name(ref_str):
    """Extract the building block name from a $ref path."""
    file_part = ref_str.split("#")[0]
    basename = Path(file_part).name
    return basename


def is_external_bb_ref(ref_str):
    """Check if a $ref points to an external building block schema file."""
    if ref_str.startswith("#"):
        return False
    file_part = ref_str.split("#")[0]
    return file_part.endswith("Schema.json")


def is_internal_type_ref(ref_str):
    """Check if a $ref is an internal reference (#/$defs/...)."""
    return ref_str.startswith("#/$defs/") or ref_str.startswith("#/")


# ---------------------------------------------------------------------------
# Schema loading and resolution
# ---------------------------------------------------------------------------

class SchemaLoader:
    """Loads and caches building block schemas."""

    def __init__(self, bb_dir):
        self.bb_dir = Path(bb_dir)
        self._cache = {}

    def load(self, rel_path):
        """Load a schema by relative path from bb_dir."""
        abs_path = (self.bb_dir / rel_path).resolve()
        return self._load_abs(abs_path)

    def _load_abs(self, abs_path):
        key = str(abs_path)
        if key not in self._cache:
            self._cache[key] = load_json(abs_path)
        return copy.deepcopy(self._cache[key])


# ---------------------------------------------------------------------------
# Phase 2: Resolve external $refs and transform
# ---------------------------------------------------------------------------

def resolve_and_transform(schema, base_dir, loader, depth=0):
    """
    Recursively walk a schema, resolving external file $refs.

    - External BB refs → replaced with {"$ref": "#/$defs/<type-name>"} + id-reference alternative
    - Internal $defs that are external refs → resolved and inlined
    - Everything else left in place
    """
    if depth > 20:
        return schema

    if isinstance(schema, list):
        return [resolve_and_transform(item, base_dir, loader, depth + 1) for item in schema]

    if not isinstance(schema, dict):
        return schema

    # Handle $ref
    if "$ref" in schema and len(schema) == 1:
        ref = schema["$ref"]
        if is_external_bb_ref(ref):
            bb_name = ref_to_bb_name(ref)
            if bb_name in BB_REF_MAP:
                return {"$ref": f"#/$defs/{BB_REF_MAP[bb_name]}"}
            else:
                # Resolve inline: load and recursively process
                ref_path = resolve_ref_path(ref, base_dir)
                if ref_path and ref_path.is_file():
                    loaded = loader._load_abs(ref_path)
                    return resolve_and_transform(loaded, ref_path.parent, loader, depth + 1)
        return schema

    result = {}
    for key, value in schema.items():
        if key == "$defs":
            # Process $defs: resolve external refs within them
            new_defs = {}
            for def_name, def_schema in value.items():
                if isinstance(def_schema, dict) and "$ref" in def_schema and len(def_schema) == 1:
                    ref = def_schema["$ref"]
                    if is_external_bb_ref(ref):
                        bb_name = ref_to_bb_name(ref)
                        if bb_name in BB_REF_MAP:
                            # This $def just redirects to a building block;
                            # we'll replace usages with the type-level $ref
                            new_defs[def_name] = {"$ref": f"#/$defs/{BB_REF_MAP[bb_name]}"}
                        else:
                            ref_path = resolve_ref_path(ref, base_dir)
                            if ref_path and ref_path.is_file():
                                loaded = loader._load_abs(ref_path)
                                new_defs[def_name] = resolve_and_transform(
                                    loaded, ref_path.parent, loader, depth + 1
                                )
                            else:
                                new_defs[def_name] = def_schema
                    else:
                        new_defs[def_name] = resolve_and_transform(
                            def_schema, base_dir, loader, depth + 1
                        )
                else:
                    new_defs[def_name] = resolve_and_transform(
                        def_schema, base_dir, loader, depth + 1
                    )
            result[key] = new_defs
        else:
            result[key] = resolve_and_transform(value, base_dir, loader, depth + 1)

    return result


def flatten_local_defs(schema):
    """
    Replace references to local $defs that are just redirects to #/$defs/type-X
    with the redirect target directly. Remove those $defs entries.
    """
    if "$defs" not in schema:
        return schema

    # Find local $defs that are simple redirects to root $defs
    redirects = {}
    for name, defn in list(schema.get("$defs", {}).items()):
        if isinstance(defn, dict) and "$ref" in defn and defn["$ref"].startswith("#/$defs/type-"):
            redirects[f"#/$defs/{name}"] = defn["$ref"]

    if not redirects:
        return schema

    # Remove redirect $defs
    for name in list(schema.get("$defs", {}).keys()):
        if f"#/$defs/{name}" in redirects:
            del schema["$defs"][name]

    # Clean up empty $defs
    if not schema.get("$defs"):
        del schema["$defs"]

    # Replace references throughout the schema
    return _replace_refs(schema, redirects)


def _replace_refs(obj, mapping):
    """Replace $ref values according to mapping dict."""
    if isinstance(obj, list):
        return [_replace_refs(item, mapping) for item in obj]
    if not isinstance(obj, dict):
        return obj
    if "$ref" in obj and obj["$ref"] in mapping:
        obj["$ref"] = mapping[obj["$ref"]]
    for key in obj:
        obj[key] = _replace_refs(obj[key], mapping)
    return obj


# ---------------------------------------------------------------------------
# Phase 3 & 4: Build individual type definitions
# ---------------------------------------------------------------------------

def add_id_reference_alternatives(schema):
    """
    Walk the schema and add id-reference alternatives wherever a property
    references a type definition.
    """
    if isinstance(schema, list):
        return [add_id_reference_alternatives(item) for item in schema]
    if not isinstance(schema, dict):
        return schema

    # Process properties
    if "properties" in schema and isinstance(schema["properties"], dict):
        for prop_name, prop_schema in schema["properties"].items():
            if prop_name.startswith("@"):
                continue  # skip @id, @type, @context
            schema["properties"][prop_name] = _add_id_ref_to_property(prop_schema)

    # Process items
    if "items" in schema:
        schema["items"] = _add_id_ref_to_property(schema["items"])

    # Recurse into sub-schemas
    for key in ["allOf", "anyOf", "oneOf"]:
        if key in schema:
            schema[key] = [add_id_reference_alternatives(item) for item in schema[key]]

    if "if" in schema:
        schema["if"] = add_id_reference_alternatives(schema["if"])
    if "then" in schema:
        schema["then"] = add_id_reference_alternatives(schema["then"])
    if "else" in schema:
        schema["else"] = add_id_reference_alternatives(schema["else"])

    for key in ["properties", "additionalProperties", "patternProperties"]:
        if key in schema and isinstance(schema[key], dict):
            for k, v in schema[key].items():
                if k.startswith("@"):
                    continue
                schema[key][k] = add_id_reference_alternatives(v)

    return schema


def _add_id_ref_to_property(prop):
    """Add id-reference alternative to a property that references a type."""
    if not isinstance(prop, dict):
        return prop

    id_ref = {"$ref": "#/$defs/id-reference"}

    # Direct $ref to a type
    if "$ref" in prop and prop["$ref"].startswith("#/$defs/type-"):
        return {"anyOf": [prop, id_ref]}

    # anyOf already containing a type $ref - add id-reference if not present
    if "anyOf" in prop:
        has_type_ref = any(
            isinstance(item, dict) and "$ref" in item and item["$ref"].startswith("#/$defs/type-")
            for item in prop["anyOf"]
        )
        has_id_ref = any(
            isinstance(item, dict) and "$ref" in item and item["$ref"] == "#/$defs/id-reference"
            for item in prop["anyOf"]
        )
        if has_type_ref and not has_id_ref:
            prop["anyOf"].append(id_ref)
        # Do NOT recurse into individual anyOf items when this anyOf already
        # handles type refs + id-reference; recursion would double-wrap bare
        # type $refs that are siblings of id-reference at this level.
        if not has_type_ref:
            prop["anyOf"] = [_add_id_ref_to_property(item) for item in prop["anyOf"]]
        return prop

    # oneOf containing a type $ref
    if "oneOf" in prop:
        has_type_ref = any(
            isinstance(item, dict) and "$ref" in item and item["$ref"].startswith("#/$defs/type-")
            for item in prop["oneOf"]
        )
        if has_type_ref:
            # Convert oneOf to anyOf and add id-reference
            items = prop.pop("oneOf")
            has_id_ref = any(
                isinstance(item, dict) and "$ref" in item and item["$ref"] == "#/$defs/id-reference"
                for item in items
            )
            if not has_id_ref:
                items.append(id_ref)
            prop["anyOf"] = items
        return prop

    # Array of type refs
    if prop.get("type") == "array" and "items" in prop:
        prop["items"] = _add_id_ref_to_property(prop["items"])

    return prop


def strip_schema_key(schema):
    """Remove $schema from a definition (only root needs it)."""
    schema.pop("$schema", None)
    return schema


def ensure_id_property(schema):
    """Make sure @id is in the properties of a type."""
    if "properties" not in schema:
        schema["properties"] = {}
    if "@id" not in schema["properties"]:
        schema["properties"]["@id"] = {"type": "string"}
    return schema


def strip_context(schema):
    """Remove @context from properties and required lists (goes on root-graph)."""
    if "properties" in schema:
        schema["properties"].pop("@context", None)
    if "required" in schema and isinstance(schema["required"], list):
        schema["required"] = [r for r in schema["required"] if r != "@context"]
        if not schema["required"]:
            del schema["required"]
    # Also strip from allOf required lists
    if "allOf" in schema:
        for item in schema["allOf"]:
            if isinstance(item, dict) and "required" in item:
                item["required"] = [r for r in item["required"] if r != "@context"]
                if not item["required"]:
                    del item["required"]
    return schema


# ---------------------------------------------------------------------------
# Build each type definition
# ---------------------------------------------------------------------------

def build_type_person(loader, bb_dir):
    """Build type-Person definition."""
    schema = loader.load("schemaorgProperties/person/personSchema.json")
    base_dir = bb_dir / "schemaorgProperties" / "person"
    schema = resolve_and_transform(schema, base_dir, loader)
    schema = flatten_local_defs(schema)
    schema = strip_schema_key(schema)
    schema = ensure_id_property(schema)
    return schema


def build_type_organization(loader, bb_dir):
    """Build type-Organization definition."""
    schema = loader.load("schemaorgProperties/organization/organizationSchema.json")
    base_dir = bb_dir / "schemaorgProperties" / "organization"
    schema = resolve_and_transform(schema, base_dir, loader)
    schema = flatten_local_defs(schema)
    schema = strip_schema_key(schema)
    schema = ensure_id_property(schema)
    return schema


def build_type_identifier(loader, bb_dir):
    """Build type-Identifier definition. Add cdi:Identifier to @type."""
    schema = loader.load("schemaorgProperties/identifier/identifierSchema.json")
    base_dir = bb_dir / "schemaorgProperties" / "identifier"
    schema = resolve_and_transform(schema, base_dir, loader)
    schema = flatten_local_defs(schema)
    schema = strip_schema_key(schema)
    schema = ensure_id_property(schema)

    # Modify @type to be array containing both schema:PropertyValue and cdi:Identifier
    schema["properties"]["@type"] = {
        "type": "array",
        "items": {"type": "string"},
        "allOf": [
            {"contains": {"const": "schema:PropertyValue"}},
            {"contains": {"const": "cdi:Identifier"}}
        ]
    }
    return schema


def build_type_defined_term(loader, bb_dir):
    """Build type-DefinedTerm definition."""
    schema = loader.load("schemaorgProperties/definedTerm/definedTermSchema.json")
    base_dir = bb_dir / "schemaorgProperties" / "definedTerm"
    schema = resolve_and_transform(schema, base_dir, loader)
    schema = flatten_local_defs(schema)
    schema = strip_schema_key(schema)
    schema = ensure_id_property(schema)
    return schema


def build_type_creative_work(loader, bb_dir):
    """Build type-CreativeWork (labeled link) definition."""
    schema = loader.load("schemaorgProperties/labeledLink/labeledLinkSchema.json")
    base_dir = bb_dir / "schemaorgProperties" / "labeledLink"
    schema = resolve_and_transform(schema, base_dir, loader)
    schema = flatten_local_defs(schema)
    schema = strip_schema_key(schema)
    schema = ensure_id_property(schema)
    return schema


def build_type_data_download(loader, bb_dir):
    """Build type-DataDownload definition with optional hasPart for archives."""
    schema = loader.load("schemaorgProperties/dataDownload/dataDownloadSchema.json")
    base_dir = bb_dir / "schemaorgProperties" / "dataDownload"
    schema = resolve_and_transform(schema, base_dir, loader)
    schema = flatten_local_defs(schema)
    schema = strip_schema_key(schema)
    schema = ensure_id_property(schema)

    # Add optional hasPart for archive support (references MediaObject by @id)
    schema["properties"]["schema:hasPart"] = {
        "type": "array",
        "description": "Component files in an archive distribution.",
        "items": {
            "anyOf": [
                {"$ref": "#/$defs/type-MediaObject"},
                {"$ref": "#/$defs/id-reference"}
            ]
        }
    }

    # Add optional schema:description
    if "schema:description" not in schema.get("properties", {}):
        schema["properties"]["schema:description"] = {"type": "string"}

    return schema


def build_type_media_object(loader, bb_dir):
    """Build type-MediaObject from archive distribution hasPart items.

    In CDIFcomplete, archive hasPart items are MediaObjects that can
    optionally include cdifDataCube or cdifTabularData data description
    properties (via allOf + anyOf in the source schema). In flattened
    form these properties appear directly on the MediaObject node.
    """
    # Load physical mapping inline (used by dataCube and tabularData)
    pm_schema = loader.load("cdifProperties/cdifPhysicalMapping/cdifPhysicalMappingSchema.json")
    pm_schema = strip_schema_key(pm_schema)

    # Load tabularData properties
    tab_schema = loader.load("cdifProperties/cdifTabularData/cdifTabularDataSchema.json")
    tab_schema = strip_schema_key(tab_schema)

    # Base MediaObject properties (from cdifArchiveDistribution hasPart items)
    schema = {
        "type": "object",
        "description": "A component file within an archive distribution. Typed as "
                       "schema:MediaObject (not DataDownload, since not independently "
                       "accessible). May optionally include CDIF data description "
                       "extensions (tabular data or data cube properties).",
        "properties": {
            "@id": {
                "type": "string",
                "description": "Identifier for this file, typically a hash-based anchor."
            },
            "@type": {
                "type": "array",
                "items": {"type": "string"},
                "contains": {"const": "schema:MediaObject"},
                "not": {"contains": {"const": "schema:DataDownload"}},
                "minItems": 1
            },
            "schema:name": {
                "type": "string",
                "description": "Filename of the component file within the archive."
            },
            "schema:description": {"type": "string"},
            "schema:encodingFormat": {
                "type": "array",
                "items": {"type": "string"}
            },
            "schema:size": {
                "type": "object",
                "properties": {
                    "@type": {"type": "string", "const": "schema:QuantitativeValue"},
                    "schema:value": {"type": "number"},
                    "schema:unitText": {"type": "string"}
                }
            },
            "schema:about": {
                "type": "array",
                "description": "For metadata sidecar files, references the data file this metadata describes.",
                "items": {"$ref": "#/$defs/id-reference"}
            },
            "spdx:checksum": {
                "type": "object",
                "properties": {
                    "spdx:algorithm": {"type": "string"},
                    "spdx:checksumValue": {"type": "string"}
                }
            },
            # --- Optional cdifTabularData properties (from cdifTabularDataSchema) ---
            "cdi:arrayBase": {"type": "integer"},
            "csvw:commentPrefix": {"type": "string"},
            "csvw:delimiter": {"type": "string"},
            "csvw:header": {"type": "boolean"},
            "csvw:headerRowCount": {"type": "integer", "minimum": 0, "default": 1},
            "cdi:isDelimited": {"type": "boolean"},
            "cdi:isFixedWidth": {"type": "boolean"},
            "csvw:lineTerminators": {
                "type": "string",
                "enum": ["CRLF", "LF", "\r\n", "\n"]
            },
            "csvw:quoteChar": {"type": "string", "default": "\""},
            "csvw:skipBlankRows": {"type": "boolean", "default": False},
            "csvw:skipColumns": {"type": "integer", "default": 0},
            "csvw:skipInitialSpace": {"type": "boolean", "default": True},
            "csvw:skipRows": {"type": "integer", "default": 0},
            "countRows": {"type": "integer"},
            "countColumns": {"type": "integer"},
            # --- Optional cdifDataCube locator extension ---
            "cdi:hasPhysicalMapping": {
                "type": "array",
                "description": "Links variables to their physical representation. Present when this component has tabular or structured data description.",
                "items": {
                    "allOf": [
                        pm_schema,
                        {
                            "type": "object",
                            "properties": {
                                "cdi:locator": {
                                    "type": "string",
                                    "description": "String to locate values of the variable in a structured dataset."
                                }
                            }
                        }
                    ]
                }
            }
        },
        "required": ["@type", "schema:name", "schema:encodingFormat"]
    }
    return schema


def build_type_web_api(loader, bb_dir):
    """Build type-WebAPI definition."""
    schema = loader.load("schemaorgProperties/webAPI/webAPISchema.json")
    base_dir = bb_dir / "schemaorgProperties" / "webAPI"
    schema = resolve_and_transform(schema, base_dir, loader)
    schema = flatten_local_defs(schema)
    schema = strip_schema_key(schema)
    schema = ensure_id_property(schema)

    # potentialAction items should allow id-reference
    if "schema:potentialAction" in schema.get("properties", {}):
        pa = schema["properties"]["schema:potentialAction"]
        if "items" in pa:
            pa["items"] = {
                "anyOf": [
                    pa["items"],
                    {"$ref": "#/$defs/id-reference"}
                ]
            }

    return schema


def build_type_action(loader, bb_dir):
    """Build type-Action definition with inline sub-defs."""
    schema = loader.load("schemaorgProperties/action/actionSchema.json")
    base_dir = bb_dir / "schemaorgProperties" / "action"
    schema = resolve_and_transform(schema, base_dir, loader)
    schema = strip_schema_key(schema)
    schema = ensure_id_property(schema)

    # Keep internal $defs (target_type, result_type, query-input_type, object_type) inline
    # But resolve the VariableMeasured $def to the type reference
    if "$defs" in schema:
        if "VariableMeasured" in schema["$defs"]:
            # Replace VariableMeasured reference with type ref
            schema["$defs"]["VariableMeasured"] = {"$ref": "#/$defs/type-InstanceVariable"}

    return schema


def build_type_place(loader, bb_dir):
    """Build type-Place (spatialExtent) definition."""
    schema = loader.load("schemaorgProperties/spatialExtent/spatialExtentSchema.json")
    base_dir = bb_dir / "schemaorgProperties" / "spatialExtent"
    schema = resolve_and_transform(schema, base_dir, loader)
    schema = flatten_local_defs(schema)
    schema = strip_schema_key(schema)
    schema = ensure_id_property(schema)
    return schema


def build_type_proper_interval(loader, bb_dir):
    """Build type-ProperInterval (temporalExtent) definition with inline timePosition_type."""
    schema = loader.load("schemaorgProperties/temporalExtent/temporalExtentSchema.json")
    base_dir = bb_dir / "schemaorgProperties" / "temporalExtent"
    schema = resolve_and_transform(schema, base_dir, loader)
    schema = strip_schema_key(schema)
    # timePosition_type stays inline in $defs

    # Wrap the anyOf at root level: the schema is an anyOf of object variants + string
    # We need to ensure @id is available on the object variants
    if "anyOf" in schema:
        for variant in schema["anyOf"]:
            if isinstance(variant, dict) and variant.get("type") == "object":
                if "properties" not in variant:
                    variant["properties"] = {}
                if "@id" not in variant["properties"]:
                    variant["properties"]["@id"] = {"type": "string"}
                # Strip @context from the numeric-ages variant
                variant.get("properties", {}).pop("@context", None)

    return schema


def build_type_monetary_grant(loader, bb_dir):
    """Build type-MonetaryGrant (funder) definition."""
    schema = loader.load("schemaorgProperties/funder/funderSchema.json")
    base_dir = bb_dir / "schemaorgProperties" / "funder"
    schema = resolve_and_transform(schema, base_dir, loader)
    schema = flatten_local_defs(schema)
    schema = strip_schema_key(schema)
    schema = ensure_id_property(schema)
    return schema


def build_type_role(loader, bb_dir):
    """Build type-Role (agentInRole) definition."""
    schema = loader.load("schemaorgProperties/agentInRole/agentInRoleSchema.json")
    base_dir = bb_dir / "schemaorgProperties" / "agentInRole"
    schema = resolve_and_transform(schema, base_dir, loader)
    schema = flatten_local_defs(schema)
    schema = strip_schema_key(schema)
    schema = ensure_id_property(schema)
    return schema


def build_type_activity(loader, bb_dir):
    """Build type-Activity from cdifProv (extended) or generatedBy (minimal fallback)."""
    cdif_prov_path = bb_dir / "cdifProperties" / "cdifProv" / "cdifProvSchema.json"
    if cdif_prov_path.is_file():
        # Load the base generatedBy schema directly (before resolve_and_transform
        # turns the $ref into a self-reference #/$defs/type-Activity)
        base_schema = loader.load("provProperties/generatedBy/generatedBySchema.json")
        base_schema = strip_schema_key(base_schema)

        # Load the extended cdifProv schema
        schema = loader.load("cdifProperties/cdifProv/cdifProvSchema.json")
        base_dir = bb_dir / "cdifProperties" / "cdifProv"
        schema = resolve_and_transform(schema, base_dir, loader)
        schema = flatten_local_defs(schema)
        schema = strip_schema_key(schema)

        # Merge: start with base generatedBy properties (@type, prov:used),
        # then overlay the extended cdifProv properties from allOf
        merged_props = {}
        for key, val in base_schema.get("properties", {}).items():
            merged_props[key] = val

        # Extract extended properties from allOf items
        if "allOf" in schema:
            remaining_allof = []
            for item in schema["allOf"]:
                if isinstance(item, dict) and "properties" in item:
                    for key, val in item["properties"].items():
                        merged_props[key] = val
                elif isinstance(item, dict) and "$ref" in item:
                    ref = item["$ref"]
                    if "type-Activity" in ref:
                        continue  # skip self-reference (already merged base above)
                    remaining_allof.append(item)
                else:
                    remaining_allof.append(item)
            if remaining_allof:
                schema["allOf"] = remaining_allof
            else:
                schema.pop("allOf", None)

        # Also pick up any top-level properties
        for key, val in schema.get("properties", {}).items():
            if key not in merged_props:
                merged_props[key] = val

        schema["properties"] = merged_props
    else:
        schema = loader.load("provProperties/generatedBy/generatedBySchema.json")
        base_dir = bb_dir / "provProperties" / "generatedBy"
        schema = resolve_and_transform(schema, base_dir, loader)
        schema = flatten_local_defs(schema)
        schema = strip_schema_key(schema)

    schema = ensure_id_property(schema)
    return schema


def build_type_howto(loader, bb_dir):
    """Build type-HowTo definition for methodology/protocol references."""
    schema = {
        "type": "object",
        "description": "A methodology or protocol described as a HowTo with optional steps.",
        "properties": {
            "@id": {"type": "string"},
            "@type": {
                "type": "string",
                "const": "schema:HowTo"
            },
            "schema:name": {
                "type": "string",
                "description": "Name of the methodology or protocol"
            },
            "schema:description": {
                "type": "string",
                "description": "Description of the methodology"
            },
            "schema:url": {
                "type": "string",
                "format": "uri",
                "description": "URL to a published methodology or protocol document"
            },
            "schema:step": {
                "type": "array",
                "description": "Ordered steps in this methodology",
                "items": {
                    "type": "object",
                    "properties": {
                        "@type": {
                            "type": "string",
                            "const": "schema:HowToStep"
                        },
                        "schema:name": {
                            "type": "string",
                            "description": "Name of this step"
                        },
                        "schema:description": {
                            "type": "string",
                            "description": "Description of what this step involves"
                        },
                        "schema:url": {
                            "type": "string",
                            "format": "uri"
                        },
                        "schema:position": {
                            "type": "integer",
                            "description": "Ordinal position of this step"
                        }
                    },
                    "required": ["@type", "schema:name"]
                }
            }
        },
        "required": ["@type"],
        "anyOf": [
            {"required": ["schema:name"]},
            {"required": ["schema:url"]}
        ]
    }
    return schema


def build_type_claim(loader, bb_dir):
    """Build type-Claim definition for quality or provenance assertions."""
    schema = {
        "type": "object",
        "description": "A statement or assertion, such as a quality claim about a dataset.",
        "properties": {
            "@id": {"type": "string"},
            "@type": {
                "type": "string",
                "const": "schema:Claim"
            },
            "schema:claimReviewed": {
                "type": "string",
                "description": "The claim being reviewed or asserted"
            },
            "schema:author": {
                "description": "Author of this claim",
                "anyOf": [
                    {"$ref": "#/$defs/type-Person"},
                    {"$ref": "#/$defs/type-Organization"},
                    {"$ref": "#/$defs/id-reference"}
                ]
            },
            "schema:datePublished": {
                "type": "string",
                "description": "ISO8601 date when this claim was published"
            },
            "schema:appearance": {
                "description": "Where this claim appears",
                "anyOf": [
                    {"type": "string"},
                    {"$ref": "#/$defs/type-CreativeWork"},
                    {"$ref": "#/$defs/id-reference"}
                ]
            }
        },
        "required": ["@type", "schema:claimReviewed"]
    }
    return schema


def build_type_quality_measurement(loader, bb_dir):
    """Build type-QualityMeasurement (qualityMeasure) definition."""
    schema = loader.load("qualityProperties/qualityMeasure/qualityMeasureSchema.json")
    base_dir = bb_dir / "qualityProperties" / "qualityMeasure"
    schema = resolve_and_transform(schema, base_dir, loader)
    schema = flatten_local_defs(schema)
    schema = strip_schema_key(schema)
    schema = ensure_id_property(schema)
    return schema


def build_type_property_value(loader, bb_dir):
    """Build type-PropertyValue (additionalProperty) definition."""
    schema = loader.load("schemaorgProperties/additionalProperty/additionalPropertySchema.json")
    base_dir = bb_dir / "schemaorgProperties" / "additionalProperty"
    schema = resolve_and_transform(schema, base_dir, loader)
    schema = flatten_local_defs(schema)
    schema = strip_schema_key(schema)
    schema = ensure_id_property(schema)
    return schema


def build_type_instance_variable(loader, bb_dir):
    """Build type-InstanceVariable from cdifVariableMeasured + variableMeasured."""
    # Load the CDI extension
    cdi_schema = loader.load("cdifProperties/cdifVariableMeasured/cdiVariableMeasuredSchema.json")
    cdi_dir = bb_dir / "cdifProperties" / "cdifVariableMeasured"
    cdi_schema = resolve_and_transform(cdi_schema, cdi_dir, loader)
    cdi_schema = strip_schema_key(cdi_schema)

    # Load the base variableMeasured
    base_schema = loader.load("schemaorgProperties/variableMeasured/variableMeasuredSchema.json")
    base_dir_path = bb_dir / "schemaorgProperties" / "variableMeasured"
    base_schema = resolve_and_transform(base_schema, base_dir_path, loader)
    base_schema = strip_schema_key(base_schema)

    # Merge: the CDI schema has allOf[required, $ref to variableMeasured]
    # We'll build a merged definition with all properties from both
    merged = {"type": "object", "properties": {}, "allOf": []}

    # Copy base properties
    for key, val in base_schema.get("properties", {}).items():
        merged["properties"][key] = val

    # Copy CDI properties (overrides @type)
    for key, val in cdi_schema.get("properties", {}).items():
        merged["properties"][key] = val

    # Merge $defs
    merged_defs = {}
    for d in [base_schema.get("$defs", {}), cdi_schema.get("$defs", {})]:
        merged_defs.update(d)
    if merged_defs:
        merged["$defs"] = merged_defs

    # Merge allOf constraints
    for s in [base_schema, cdi_schema]:
        for constraint in s.get("allOf", []):
            if isinstance(constraint, dict):
                ref = constraint.get("$ref", "")
                # Skip $ref to variableMeasuredSchema (already merged into properties)
                # After resolution this becomes #/$defs/type-InstanceVariable (self-ref)
                if ref and ("variableMeasured" in ref or "type-InstanceVariable" in ref):
                    continue
                merged["allOf"].append(constraint)

    if not merged["allOf"]:
        del merged["allOf"]

    merged = flatten_local_defs(merged)
    merged = ensure_id_property(merged)
    return merged


def build_type_catalog_record(loader, bb_dir):
    """Build type-CatalogRecord from cdifCatalogRecord with @type changed to dcat:CatalogRecord."""
    schema = loader.load("cdifProperties/cdifCatalogRecord/cdifCatalogRecordSchema.json")
    base_dir = bb_dir / "cdifProperties" / "cdifCatalogRecord"
    schema = resolve_and_transform(schema, base_dir, loader)
    schema = flatten_local_defs(schema)
    schema = strip_schema_key(schema)
    schema = ensure_id_property(schema)

    # Change @type from schema:Dataset to dcat:CatalogRecord
    schema["properties"]["@type"] = {
        "type": "string",
        "const": "dcat:CatalogRecord"
    }

    # Keep conformsTo_item inline
    return schema


def build_type_dataset(loader, bb_dir):
    """Build type-Dataset: merge mandatory + optional + CDIFDataDescription distribution."""
    mandatory = loader.load("cdifProperties/cdifMandatory/cdifMandatorySchema.json")
    mandatory_dir = bb_dir / "cdifProperties" / "cdifMandatory"
    mandatory = resolve_and_transform(mandatory, mandatory_dir, loader)
    mandatory = strip_schema_key(mandatory)

    optional = loader.load("cdifProperties/cdifOptional/cdifOptionalSchema.json")
    optional_dir = bb_dir / "cdifProperties" / "cdifOptional"
    optional = resolve_and_transform(optional, optional_dir, loader)
    optional = strip_schema_key(optional)

    # Load CDIFDataDescription for distribution constraints
    # Try new nested path first, fall back to old flat path
    dd_rel = "profiles/cdifProfiles/CDIFDataDescription/CDIFDataDescriptionSchema.json"
    dd_dir = bb_dir / "profiles" / "cdifProfiles" / "CDIFDataDescription"
    if not (bb_dir / dd_rel).exists():
        dd_rel = "profiles/CDIFDataDescription/CDIFDataDescriptionSchema.json"
        dd_dir = bb_dir / "profiles" / "CDIFDataDescription"
    dd_schema = loader.load(dd_rel)
    dd_schema = resolve_and_transform(dd_schema, dd_dir, loader)
    dd_schema = strip_schema_key(dd_schema)

    # Merge all properties from mandatory + optional
    merged = {"type": "object", "properties": {}}

    for src in [mandatory, optional]:
        for key, val in src.get("properties", {}).items():
            merged["properties"][key] = val

    # Merge $defs
    merged_defs = {}
    for src in [mandatory, optional]:
        merged_defs.update(src.get("$defs", {}))
    if merged_defs:
        merged["$defs"] = merged_defs

    # Build allOf from mandatory constraints
    all_of = []
    for constraint in mandatory.get("allOf", []):
        all_of.append(constraint)

    if all_of:
        merged["allOf"] = all_of

    # Strip @context (goes on root-graph wrapper)
    merged = strip_context(merged)

    # Flatten the local defs to point at root-level types
    merged = flatten_local_defs(merged)

    # Ensure @id present
    merged = ensure_id_property(merged)

    # In flattened form, schema:subjectOf, schema:distribution, etc. become id-references
    # Modify schema:subjectOf to allow id-reference
    if "schema:subjectOf" in merged.get("properties", {}):
        subj = merged["properties"]["schema:subjectOf"]
        if "$ref" in subj:
            merged["properties"]["schema:subjectOf"] = {
                "anyOf": [
                    subj,
                    {"$ref": "#/$defs/id-reference"}
                ]
            }

    # Modify schema:distribution items to allow id-references
    if "schema:distribution" in merged.get("properties", {}):
        merged["properties"]["schema:distribution"] = {
            "type": "array",
            "items": {
                "anyOf": [
                    {"$ref": "#/$defs/type-DataDownload"},
                    {"$ref": "#/$defs/type-WebAPI"},
                    {"$ref": "#/$defs/type-StructuredDataSet"},
                    {"$ref": "#/$defs/type-TabularTextDataSet"},
                    {"$ref": "#/$defs/type-LongStructureDataSet"},
                    {"$ref": "#/$defs/id-reference"}
                ]
            }
        }

    # Modify schema:creator @list items to allow id-references
    if "schema:creator" in merged.get("properties", {}):
        merged["properties"]["schema:creator"] = {
            "type": "object",
            "properties": {
                "@list": {
                    "type": "array",
                    "items": {
                        "anyOf": [
                            {"$ref": "#/$defs/type-Person"},
                            {"$ref": "#/$defs/type-Organization"},
                            {"$ref": "#/$defs/id-reference"}
                        ]
                    }
                }
            }
        }

    # Modify schema:contributor items to allow id-references
    if "schema:contributor" in merged.get("properties", {}):
        merged["properties"]["schema:contributor"] = {
            "type": "array",
            "items": {
                "anyOf": [
                    {"$ref": "#/$defs/type-Person"},
                    {"$ref": "#/$defs/type-Organization"},
                    {"$ref": "#/$defs/type-Role"},
                    {"$ref": "#/$defs/id-reference"}
                ]
            }
        }

    # Modify schema:publisher
    if "schema:publisher" in merged.get("properties", {}):
        merged["properties"]["schema:publisher"] = {
            "anyOf": [
                {"$ref": "#/$defs/type-Person"},
                {"$ref": "#/$defs/type-Organization"},
                {"$ref": "#/$defs/id-reference"}
            ]
        }

    # Modify schema:provider
    if "schema:provider" in merged.get("properties", {}):
        merged["properties"]["schema:provider"] = {
            "type": "array",
            "items": {
                "anyOf": [
                    {"$ref": "#/$defs/type-Person"},
                    {"$ref": "#/$defs/type-Organization"},
                    {"$ref": "#/$defs/id-reference"}
                ]
            }
        }

    # Modify schema:funding items
    if "schema:funding" in merged.get("properties", {}):
        merged["properties"]["schema:funding"] = {
            "type": "array",
            "items": {
                "anyOf": [
                    {"$ref": "#/$defs/type-MonetaryGrant"},
                    {"$ref": "#/$defs/id-reference"}
                ]
            }
        }

    # Modify schema:variableMeasured items
    if "schema:variableMeasured" in merged.get("properties", {}):
        merged["properties"]["schema:variableMeasured"] = {
            "type": "array",
            "items": {
                "anyOf": [
                    {"$ref": "#/$defs/type-InstanceVariable"},
                    {"$ref": "#/$defs/id-reference"}
                ]
            }
        }

    # Modify schema:spatialCoverage items
    if "schema:spatialCoverage" in merged.get("properties", {}):
        merged["properties"]["schema:spatialCoverage"] = {
            "type": "array",
            "items": {
                "anyOf": [
                    {"$ref": "#/$defs/type-Place"},
                    {"$ref": "#/$defs/id-reference"}
                ]
            }
        }

    # Modify schema:temporalCoverage items
    if "schema:temporalCoverage" in merged.get("properties", {}):
        merged["properties"]["schema:temporalCoverage"] = {
            "type": "array",
            "items": {
                "anyOf": [
                    {"$ref": "#/$defs/type-ProperInterval"},
                    {"type": "string"},
                    {"$ref": "#/$defs/id-reference"}
                ]
            }
        }

    # Modify prov:wasGeneratedBy items
    if "prov:wasGeneratedBy" in merged.get("properties", {}):
        merged["properties"]["prov:wasGeneratedBy"] = {
            "type": "array",
            "items": {
                "anyOf": [
                    {"$ref": "#/$defs/type-Activity"},
                    {"$ref": "#/$defs/id-reference"}
                ]
            }
        }

    # prov:wasDerivedFrom items - keep as-is (strings, @id refs, labeled links)
    if "prov:wasDerivedFrom" in merged.get("properties", {}):
        merged["properties"]["prov:wasDerivedFrom"] = {
            "type": "array",
            "items": {
                "anyOf": [
                    {"type": "string"},
                    {"$ref": "#/$defs/type-CreativeWork"},
                    {"$ref": "#/$defs/id-reference"}
                ]
            }
        }

    # dqv:hasQualityMeasurement items
    if "dqv:hasQualityMeasurement" in merged.get("properties", {}):
        merged["properties"]["dqv:hasQualityMeasurement"] = {
            "type": "array",
            "items": {
                "anyOf": [
                    {"$ref": "#/$defs/type-QualityMeasurement"},
                    {"$ref": "#/$defs/id-reference"}
                ]
            }
        }

    # Modify schema:identifier to include id-reference
    if "schema:identifier" in merged.get("properties", {}):
        merged["properties"]["schema:identifier"] = {
            "anyOf": [
                {"$ref": "#/$defs/type-Identifier"},
                {"type": "string"},
                {"$ref": "#/$defs/id-reference"}
            ]
        }

    # Modify schema:sameAs items to include id-reference for Identifiers
    if "schema:sameAs" in merged.get("properties", {}):
        merged["properties"]["schema:sameAs"] = {
            "type": "array",
            "items": {
                "anyOf": [
                    {"$ref": "#/$defs/type-Identifier"},
                    {"type": "string"},
                    {"$ref": "#/$defs/id-reference"}
                ]
            }
        }

    # schema:additionalType items
    if "schema:additionalType" in merged.get("properties", {}):
        merged["properties"]["schema:additionalType"] = {
            "type": "array",
            "items": {
                "anyOf": [
                    {"type": "string"},
                    {"$ref": "#/$defs/type-DefinedTerm"},
                    {"$ref": "#/$defs/id-reference"}
                ]
            }
        }

    # schema:keywords items
    if "schema:keywords" in merged.get("properties", {}):
        merged["properties"]["schema:keywords"] = {
            "type": "array",
            "items": {
                "anyOf": [
                    {"$ref": "#/$defs/type-DefinedTerm"},
                    {"type": "string"},
                    {"$ref": "#/$defs/id-reference"}
                ]
            }
        }

    # schema:conditionsOfAccess items
    if "schema:conditionsOfAccess" in merged.get("properties", {}):
        merged["properties"]["schema:conditionsOfAccess"] = {
            "type": "array",
            "items": {
                "anyOf": [
                    {"type": "string"},
                    {"$ref": "#/$defs/type-CreativeWork"},
                    {"$ref": "#/$defs/id-reference"}
                ]
            }
        }

    # schema:license items
    if "schema:license" in merged.get("properties", {}):
        merged["properties"]["schema:license"] = {
            "type": "array",
            "items": {
                "anyOf": [
                    {"type": "string"},
                    {"$ref": "#/$defs/type-CreativeWork"},
                    {"$ref": "#/$defs/id-reference"}
                ]
            }
        }

    # schema:publishingPrinciples items
    if "schema:publishingPrinciples" in merged.get("properties", {}):
        merged["properties"]["schema:publishingPrinciples"] = {
            "type": "array",
            "items": {
                "anyOf": [
                    {"type": "string"},
                    {"$ref": "#/$defs/type-CreativeWork"},
                    {"$ref": "#/$defs/id-reference"}
                ]
            }
        }

    return merged


def build_type_structured_dataset(loader, bb_dir):
    """Build type-StructuredDataSet: compose dataDownload + cdifDataCube."""
    dd_schema = loader.load("schemaorgProperties/dataDownload/dataDownloadSchema.json")
    dd_dir = bb_dir / "schemaorgProperties" / "dataDownload"
    dd_schema = resolve_and_transform(dd_schema, dd_dir, loader)
    dd_schema = strip_schema_key(dd_schema)

    cube_schema = loader.load("cdifProperties/cdifDataCube/cdifDataCubeSchema.json")
    cube_dir = bb_dir / "cdifProperties" / "cdifDataCube"
    cube_schema = resolve_and_transform(cube_schema, cube_dir, loader)
    cube_schema = strip_schema_key(cube_schema)

    # Load physical mapping inline
    pm_schema = loader.load("cdifProperties/cdifPhysicalMapping/cdifPhysicalMappingSchema.json")
    pm_schema = strip_schema_key(pm_schema)

    # Merge: allOf [dataDownload properties, dataCube properties]
    merged = {"type": "object", "properties": {}}

    # Copy dataDownload properties
    for key, val in dd_schema.get("properties", {}).items():
        merged["properties"][key] = val

    # Copy dataCube properties
    for key, val in cube_schema.get("properties", {}).items():
        merged["properties"][key] = val

    # Override @type to require both schema:DataDownload and cdi:StructuredDataSet
    merged["properties"]["@type"] = {
        "type": "array",
        "items": {"type": "string"},
        "allOf": [
            {"contains": {"const": "schema:DataDownload"}},
            {"contains": {"const": "cdi:StructuredDataSet"}}
        ]
    }

    # Inline the physical mapping in cdi:hasPhysicalMapping
    merged["properties"]["cdi:hasPhysicalMapping"] = {
        "type": "array",
        "description": "Links variables to their physical representation in this dataset.",
        "items": {
            "allOf": [
                pm_schema,
                {
                    "type": "object",
                    "properties": {
                        "cdi:locator": {
                            "type": "string",
                            "description": "String that can be used by software to locate values of the variable in this physical dataset."
                        }
                    }
                }
            ]
        }
    }

    # Required
    merged["required"] = ["schema:contentUrl", "@type"]

    # Merge $defs
    merged_defs = {}
    for src in [dd_schema]:
        merged_defs.update(src.get("$defs", {}))
    if merged_defs:
        merged["$defs"] = merged_defs

    merged = flatten_local_defs(merged)
    merged = ensure_id_property(merged)
    return merged


def build_type_tabular_text_dataset(loader, bb_dir):
    """Build type-TabularTextDataSet: compose dataDownload + cdifTabularData."""
    dd_schema = loader.load("schemaorgProperties/dataDownload/dataDownloadSchema.json")
    dd_dir = bb_dir / "schemaorgProperties" / "dataDownload"
    dd_schema = resolve_and_transform(dd_schema, dd_dir, loader)
    dd_schema = strip_schema_key(dd_schema)

    tab_schema = loader.load("cdifProperties/cdifTabularData/cdifTabularDataSchema.json")
    tab_dir = bb_dir / "cdifProperties" / "cdifTabularData"
    tab_schema = resolve_and_transform(tab_schema, tab_dir, loader)
    tab_schema = strip_schema_key(tab_schema)

    # Load physical mapping inline
    pm_schema = loader.load("cdifProperties/cdifPhysicalMapping/cdifPhysicalMappingSchema.json")
    pm_schema = strip_schema_key(pm_schema)

    # Merge
    merged = {"type": "object", "properties": {}}

    # Copy dataDownload properties
    for key, val in dd_schema.get("properties", {}).items():
        merged["properties"][key] = val

    # Copy tabularData properties
    for key, val in tab_schema.get("properties", {}).items():
        merged["properties"][key] = val

    # Override @type to require both schema:DataDownload and cdi:TabularTextDataSet
    merged["properties"]["@type"] = {
        "type": "array",
        "items": {"type": "string"},
        "allOf": [
            {"contains": {"const": "schema:DataDownload"}},
            {"contains": {"const": "cdi:TabularTextDataSet"}}
        ]
    }

    # Inline physical mapping
    merged["properties"]["cdi:hasPhysicalMapping"] = {
        "type": "array",
        "description": "Links variables to their physical representation in this dataset.",
        "items": pm_schema
    }

    # Required
    merged["required"] = ["schema:contentUrl", "@type"]

    # Copy oneOf constraint from tabular (isDelimited/isFixedWidth)
    if "oneOf" in tab_schema:
        merged["oneOf"] = tab_schema["oneOf"]

    # Merge $defs
    merged_defs = {}
    for src in [dd_schema]:
        merged_defs.update(src.get("$defs", {}))
    if merged_defs:
        merged["$defs"] = merged_defs

    merged = flatten_local_defs(merged)
    merged = ensure_id_property(merged)
    return merged


def build_type_long_structure_dataset(loader, bb_dir):
    """Build type-LongStructureDataSet: compose dataDownload + cdifLongData."""
    dd_schema = loader.load("schemaorgProperties/dataDownload/dataDownloadSchema.json")
    dd_dir = bb_dir / "schemaorgProperties" / "dataDownload"
    dd_schema = resolve_and_transform(dd_schema, dd_dir, loader)
    dd_schema = strip_schema_key(dd_schema)

    long_schema = loader.load("cdifProperties/cdifLongData/cdifLongDataSchema.json")
    long_dir = bb_dir / "cdifProperties" / "cdifLongData"
    long_schema = resolve_and_transform(long_schema, long_dir, loader)
    long_schema = strip_schema_key(long_schema)

    # Load physical mapping inline
    pm_schema = loader.load("cdifProperties/cdifPhysicalMapping/cdifPhysicalMappingSchema.json")
    pm_schema = strip_schema_key(pm_schema)

    # Merge
    merged = {"type": "object", "properties": {}}

    # Copy dataDownload properties
    for key, val in dd_schema.get("properties", {}).items():
        merged["properties"][key] = val

    # Copy longData properties
    for key, val in long_schema.get("properties", {}).items():
        merged["properties"][key] = val

    # Override @type to require both schema:DataDownload and cdi:LongStructureDataSet
    merged["properties"]["@type"] = {
        "type": "array",
        "items": {"type": "string"},
        "allOf": [
            {"contains": {"const": "schema:DataDownload"}},
            {"contains": {"const": "cdi:LongStructureDataSet"}}
        ]
    }

    # Inline physical mapping in cdi:hasPhysicalMapping
    merged["properties"]["cdi:hasPhysicalMapping"] = {
        "type": "array",
        "description": "Links variables to their physical representation in this dataset.",
        "items": pm_schema
    }

    # Required
    merged["required"] = ["schema:contentUrl", "@type"]

    # Merge $defs
    merged_defs = {}
    for src in [dd_schema]:
        merged_defs.update(src.get("$defs", {}))
    if merged_defs:
        merged["$defs"] = merged_defs

    merged = flatten_local_defs(merged)
    merged = ensure_id_property(merged)
    return merged


# ---------------------------------------------------------------------------
# Phase 5: Assemble output schema
# ---------------------------------------------------------------------------

def build_dispatch_condition(dispatch_type):
    """Build an if condition that matches @type as string or array containing the type."""
    return {
        "properties": {
            "@type": {
                "anyOf": [
                    {"const": dispatch_type},
                    {"type": "array", "contains": {"const": dispatch_type}}
                ]
            }
        }
    }


def build_root_object_dispatch(type_dispatch):
    """Build anyOf array of if/then/else branches for dispatching by @type.

    Uses the same pattern as ddi-cdi.schema_normative.json: each branch is
    an if/then/else where else:false causes non-matching branches to fail,
    and anyOf requires at least one branch to succeed.
    """
    branches = []
    for dispatch_type, defs_name in type_dispatch:
        condition = build_dispatch_condition(dispatch_type)
        branches.append({
            "if": condition,
            "then": {"$ref": f"#/$defs/{defs_name}"},
            "else": False
        })

    return {
        "type": "object",
        "required": ["@type"],
        "$comment": "Dispatch each graph node to its type-specific schema by @type value.",
        "anyOf": branches
    }


def promote_internal_defs(defs):
    """
    Promote internal $defs from each type definition to the root level.

    In JSON Schema, $ref: "#/$defs/foo" always resolves from the schema root.
    When a type definition has its own $defs (e.g., type-Action has target_type),
    those must be promoted to the root $defs with qualified names, and all
    internal refs rewritten accordingly.

    Runs iteratively until no more internal $defs remain, handling cases where
    promoted defs themselves contain $defs (e.g., instrument building block
    promoted from type-Activity has its own Identifier/AdditionalProperty $defs).
    """
    changed = True
    while changed:
        changed = False
        promoted = {}
        for type_name, type_schema in list(defs.items()):
            if not isinstance(type_schema, dict):
                continue
            internal_defs = type_schema.get("$defs", {})
            if not internal_defs:
                continue

            changed = True

            # Build a mapping from old refs to new qualified names
            ref_mapping = {}
            for def_name, def_schema in list(internal_defs.items()):
                # Skip defs that are already just redirects to root-level type defs
                if (isinstance(def_schema, dict) and "$ref" in def_schema
                        and def_schema["$ref"].startswith("#/$defs/type-")):
                    # This is already pointing to a root type; just rewrite refs to it
                    ref_mapping[f"#/$defs/{def_name}"] = def_schema["$ref"]
                    continue

                qualified_name = f"{type_name}--{def_name}"
                ref_mapping[f"#/$defs/{def_name}"] = f"#/$defs/{qualified_name}"
                promoted[qualified_name] = def_schema

            # Remove the internal $defs from the type schema
            del type_schema["$defs"]

            # Rewrite all refs within this type schema
            _replace_refs(type_schema, ref_mapping)

            # Also rewrite refs within the promoted defs themselves
            for qname, qschema in promoted.items():
                if qname.startswith(f"{type_name}--"):
                    _replace_refs(qschema, ref_mapping)

        # Add all promoted defs to root
        defs.update(promoted)

    return defs


def build_output_schema(defs, type_dispatch):
    """Assemble the complete output schema."""
    root_object = build_root_object_dispatch(type_dispatch)

    # Context schema for root-graph
    context_schema = {
        "type": "object",
        "properties": {
            "schema": {"const": "http://schema.org/"},
            "dcterms": {"const": "http://purl.org/dc/terms/"},
            "geosparql": {"const": "http://www.opengis.net/ont/geosparql#"},
            "spdx": {"const": "http://spdx.org/rdf/terms#"},
            "cdi": {"const": "http://ddialliance.org/Specification/DDI-CDI/1.0/RDF/"},
            "csvw": {"const": "http://www.w3.org/ns/csvw#"},
            "prov": {"const": "http://www.w3.org/ns/prov#"},
            "dcat": {"const": "http://www.w3.org/ns/dcat#"},
            "dqv": {"const": "http://www.w3.org/ns/dqv#"},
            "time": {"const": "http://www.w3.org/2006/time#"}
        },
        "required": ["schema", "dcterms"],
        "additionalProperties": True
    }

    # id-reference definition
    id_reference = {
        "type": "object",
        "required": ["@id"],
        "properties": {
            "@id": {"type": "string"}
        },
        "additionalProperties": False
    }

    # root-array: array of root-objects
    root_array = {
        "type": "array",
        "items": {"$ref": "#/$defs/root-object"}
    }

    # root-graph: object with @context and @graph
    root_graph = {
        "type": "object",
        "required": ["@context", "@graph"],
        "properties": {
            "@context": context_schema,
            "@graph": {"$ref": "#/$defs/root-array"}
        }
    }

    # Add structural definitions
    defs["root-object"] = root_object
    defs["root-array"] = root_array
    defs["root-graph"] = root_graph
    defs["id-reference"] = id_reference

    # Root schema: if object → anyOf [root-object, root-graph], else → root-array
    output = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "CDIF Flattened JSON-LD Graph Schema",
        "description": (
            "JSON Schema for validating flattened JSON-LD graphs containing CDIF metadata. "
            "Accepts either a single graph node (object), an array of nodes, or a "
            "JSON-LD document with @context and @graph. Each node is dispatched by "
            "@type to the appropriate type-specific sub-schema. Generated from CDIF "
            "building block source schemas."
        ),
        "if": {"type": "object"},
        "then": {
            "anyOf": [
                {"$ref": "#/$defs/root-graph"},
                {"$ref": "#/$defs/root-object"}
            ]
        },
        "else": {"$ref": "#/$defs/root-array"},
        "$defs": defs
    }

    return output


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate CDIF flattened JSON-LD graph schema"
    )
    parser.add_argument(
        "--bb-dir",
        help="Path to BuildingBlockSubmodule/_sources/ directory",
        default=None,
    )
    parser.add_argument(
        "--output", "-o",
        help="Output schema file path",
        default=None,
    )
    args = parser.parse_args()

    # Find building blocks directory
    bb_dir = Path(args.bb_dir) if args.bb_dir else find_bb_dir()
    if bb_dir is None or not bb_dir.is_dir():
        print("ERROR: Cannot find building blocks _sources directory.", file=sys.stderr)
        print("  Use --bb-dir to specify the path, or set CDIF_BB_DIR.", file=sys.stderr)
        sys.exit(1)

    print(f"Building blocks directory: {bb_dir}")

    # Output path
    script_dir = Path(__file__).resolve().parent
    output_path = Path(args.output) if args.output else script_dir / "CDIF-graph-schema-2026.json"

    loader = SchemaLoader(bb_dir)

    # Phase 3 & 4: Build all type definitions
    print("Building type definitions...")
    defs = {}

    builders = {
        "type-Person": build_type_person,
        "type-Organization": build_type_organization,
        "type-Identifier": build_type_identifier,
        "type-DefinedTerm": build_type_defined_term,
        "type-CreativeWork": build_type_creative_work,
        "type-DataDownload": build_type_data_download,
        "type-MediaObject": build_type_media_object,
        "type-WebAPI": build_type_web_api,
        "type-Action": build_type_action,
        "type-Place": build_type_place,
        "type-ProperInterval": build_type_proper_interval,
        "type-MonetaryGrant": build_type_monetary_grant,
        "type-Role": build_type_role,
        "type-Activity": build_type_activity,
        "type-HowTo": build_type_howto,
        "type-Claim": build_type_claim,
        "type-QualityMeasurement": build_type_quality_measurement,
        "type-PropertyValue": build_type_property_value,
        "type-InstanceVariable": build_type_instance_variable,
        "type-CatalogRecord": build_type_catalog_record,
        "type-Dataset": build_type_dataset,
        "type-StructuredDataSet": build_type_structured_dataset,
        "type-TabularTextDataSet": build_type_tabular_text_dataset,
        "type-LongStructureDataSet": build_type_long_structure_dataset,
    }

    for name, builder in builders.items():
        print(f"  {name}...")
        if name == "type-MediaObject":
            defs[name] = builder(loader, bb_dir)
        else:
            defs[name] = builder(loader, bb_dir)

    # Apply id-reference alternatives to all type definitions
    print("Adding @id-reference alternatives...")
    for name in defs:
        if name.startswith("type-"):
            defs[name] = add_id_reference_alternatives(defs[name])

    # Promote internal $defs to root level
    print("Promoting internal $defs to root level...")
    defs = promote_internal_defs(defs)

    # Phase 5: Assemble
    print("Assembling output schema...")
    output = build_output_schema(defs, TYPE_DISPATCH)

    # Write output
    print(f"Writing {output_path}...")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=4, ensure_ascii=False)

    print(f"Done. Output: {output_path}")

    # Basic validation: check all $ref targets exist
    print("Validating internal references...")
    all_refs = _collect_refs(output)
    all_defs = set(f"#/$defs/{name}" for name in output.get("$defs", {}))
    missing = set()
    for ref in all_refs:
        if ref.startswith("#/$defs/") and ref not in all_defs:
            # Check if it's a sub-path within a $defs entry (e.g. #/$defs/type-Action/$defs/...)
            parts = ref.split("/")
            if len(parts) >= 4 and f"#/$defs/{parts[2]}" in all_defs:
                continue
            missing.add(ref)
    if missing:
        print(f"WARNING: {len(missing)} unresolved $ref(s):")
        for ref in sorted(missing):
            print(f"  {ref}")
    else:
        print("All internal references resolved successfully.")


def _collect_refs(obj):
    """Collect all $ref values in a schema."""
    refs = set()
    if isinstance(obj, dict):
        if "$ref" in obj:
            refs.add(obj["$ref"])
        for v in obj.values():
            refs.update(_collect_refs(v))
    elif isinstance(obj, list):
        for item in obj:
            refs.update(_collect_refs(item))
    return refs


if __name__ == "__main__":
    main()
