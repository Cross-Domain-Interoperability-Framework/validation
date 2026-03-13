# SHACL Validation for CDIF Metadata

This directory contains tools and composite shape files for validating CDIF JSON-LD metadata using [SHACL (Shapes Constraint Language)](https://www.w3.org/TR/shacl/). SHACL validation operates on the RDF graph representation of JSON-LD and can express constraints that JSON Schema cannot, such as SPARQL-based target selection, cross-node relationship constraints, and semantic validation using RDF inference.

## Files

| File | Description |
|------|-------------|
| `CDIF-Discovery-Shapes.ttl` | Composite SHACL shapes for the CDIFDiscovery profile (64 shapes, generated) |
| `CDIF-Complete-Shapes.ttl` | Composite SHACL shapes for the CDIFcomplete profile (76 shapes, generated) |
| `ShaclJSONLDContext.py` | Validates a JSON-LD file against a SHACL shapes file |
| `generate_shacl_shapes.py` | Compiles composite SHACL shapes from building block `rules.shacl` files |
| `generate_shacl_report.py` | Runs SHACL validation and produces a structured markdown report |

## How the SHACL shapes are built

The composite shapes files (`CDIF-Discovery-Shapes.ttl`, `CDIF-Complete-Shapes.ttl`) are **not hand-maintained**. They are compiled from modular `rules.shacl` files defined in individual building blocks in the [metadataBuildingBlocks](https://github.com/usgin/metadataBuildingBlocks) repository (under `_sources/`).

Each building block (e.g., `schemaorgProperties/person`, `cdifProperties/cdifOptional`) defines its own SHACL shapes for the properties it introduces. `generate_shacl_shapes.py` merges these into a single Turtle file per profile, using priority-based conflict resolution:

1. **Sub-building blocks** (leaf components like `identifier`, `person`, `definedTerm`) — highest priority, most authoritative
2. **CDIF composite building blocks** (like `cdifCatalogRecord`, `cdifProv`) — middle priority
3. **CDIF aggregate building blocks** (like `cdifMandatory`, `cdifOptional`) — lower priority
4. **Profile-level copies** (like `CDIFDiscovery`, `CDIFcomplete`) — lowest priority, these are duplicates

When the same named shape URI appears in multiple files, the highest-priority version is kept and later copies are skipped.

### Profiles

Two profiles are supported:

- **discovery** (default) — merges 22 building block rule sets into `CDIF-Discovery-Shapes.ttl` (64 shapes). Covers the CDIFDiscovery profile: identifiers, people, organizations, spatial/temporal extent, variables, keywords, distributions, etc.
- **complete** — merges 32 building block rule sets into `CDIF-Complete-Shapes.ttl` (76 shapes). Adds provenance (cdifProv, provActivity), data description (cdifVariableMeasured, cdifPhysicalMapping, cdifTabularData, cdifDataCube, cdifLongData), and archive distribution shapes.

### SOSO namespace-check shapes

The composite shapes include 3 shapes from [SOSO (Science on Schema.org)](http://science-on-schema.org/) that detect incorrect `schema.org` namespace variants — using `https://` instead of `http://`, or omitting the trailing slash. These catch a common authoring mistake that breaks RDF validation.

### Regenerating shapes

Run from the repository root:

```bash
# Regenerate discovery profile shapes (default)
python ShaclValidation/generate_shacl_shapes.py

# Regenerate complete profile shapes
python ShaclValidation/generate_shacl_shapes.py --profile complete

# Both profiles
python ShaclValidation/generate_shacl_shapes.py --profile discovery
python ShaclValidation/generate_shacl_shapes.py --profile complete

# Verbose output showing which shapes come from which building block
python ShaclValidation/generate_shacl_shapes.py -v

# Explicit building block source directory
python ShaclValidation/generate_shacl_shapes.py --bb-dir /path/to/_sources
```

The `--bb-dir` defaults to the `metadataBuildingBlocks/_sources/` directory detected relative to the script, or set via the `CDIF_BB_DIR` environment variable.

### Adding a new building block's shapes

1. Create `rules.shacl` in the building block directory (in the metadataBuildingBlocks repo)
2. Add the building block path to `CDIF_DISCOVERY_BLOCKS` or `CDIF_COMPLETE_BLOCKS` in `generate_shacl_shapes.py`
3. Regenerate: `python ShaclValidation/generate_shacl_shapes.py --profile discovery`

## Validating metadata with ShaclJSONLDContext.py

`ShaclJSONLDContext.py` validates a JSON-LD metadata file against any SHACL shapes file (composite or individual building block rules).

### Prerequisites

```bash
pip install rdflib pyshacl
```

### Usage

```bash
# Validate against the discovery profile shapes
python ShaclValidation/ShaclJSONLDContext.py my-metadata.jsonld ShaclValidation/CDIF-Discovery-Shapes.ttl

# Validate against the complete profile shapes
python ShaclValidation/ShaclJSONLDContext.py my-metadata.jsonld ShaclValidation/CDIF-Complete-Shapes.ttl

# Validate against a single building block's rules
python ShaclValidation/ShaclJSONLDContext.py my-metadata.jsonld path/to/_sources/schemaorgProperties/variableMeasured/rules.shacl

# Verbose output (shows SPARQL target matches and debug info)
python ShaclValidation/ShaclJSONLDContext.py -v my-metadata.jsonld ShaclValidation/CDIF-Discovery-Shapes.ttl
```

**Options:**
- `-d, --data` — Path to JSON-LD metadata file
- `-s, --shapes` — Path to SHACL shapes file (Turtle format)
- `-v, --verbose` — Show SPARQL target matches and pyshacl debug output

### Output

The script reports:

1. **Data graph size** — number of triples in the parsed JSON-LD
2. **Shapes graph size** — number of triples in the SHACL rules
3. **Validation results** — for each constraint violation:
   - Focus node (the node that failed)
   - Source shape (the SHACL shape that was violated)
   - Result message (explanation)

Exit code is 0 if the data conforms, 1 otherwise.

## Generating markdown reports with generate_shacl_report.py

`generate_shacl_report.py` wraps SHACL validation and produces a structured markdown report suitable for sharing. Issues are grouped by severity (Violation, Warning, Info), then by constraint message, with each issue showing the focus node's `@type` and `schema:name` for context.

```bash
# Generate a report to a file
python ShaclValidation/generate_shacl_report.py metadata.jsonld ShaclValidation/CDIF-Complete-Shapes.ttl -o report.md

# Print report to stdout
python ShaclValidation/generate_shacl_report.py metadata.jsonld ShaclValidation/CDIF-Discovery-Shapes.ttl

# Named arguments with verbose output
python ShaclValidation/generate_shacl_report.py -d metadata.jsonld -s ShaclValidation/CDIF-Complete-Shapes.ttl -o report.md -v
```

**Options:**
- `-o, --output FILE` — Write the markdown report to a file (default: stdout)
- `-v, --verbose` — Show diagnostic output on stderr during validation

### Report structure

- **Header** — date, file paths, triple counts, conformance status, total issue count
- **Summary table** — counts by severity level
- **Detail sections** — one per severity level, with issues grouped by constraint message. Each issue shows the focus node described with its `@type` and `schema:name` (or `@id` for URI nodes)

### Severity levels

SHACL shapes use three severity levels aligned with the JSON Schema optionality:

| Severity | Meaning | Example |
|----------|---------|---------|
| **Violation** | Structurally required property missing or invalid | `prov:used` missing from activity |
| **Warning** | Recommended property missing | `schema:name` on activity, `cdi:physicalDataType` on InstanceVariable |
| **Info** | Suggested property missing | `schema:description`, `schema:actionStatus` |

## SHACL vs JSON Schema validation

| Aspect | JSON Schema | SHACL |
|--------|-------------|-------|
| Operates on | JSON structure | RDF graph |
| Target selection | JSON paths | Classes, predicates, SPARQL |
| Cross-references | Limited | Full graph traversal |
| Inference | None | RDFS/OWL supported |
| Best for | Structure validation | Semantic validation |

**Recommendation**: Use both validation approaches for comprehensive coverage. `batch_validate.py` (in the parent directory) runs both JSON Schema and SHACL validation across multiple file groups.
