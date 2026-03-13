# Validating CDIF Profile Metadata

## 1. Introduction -- Why JSON-LD?

CDIF (Cross-Domain Interoperability Framework) profiles produce metadata as [JSON-LD](https://www.w3.org/TR/json-ld11/) -- JSON for Linking Data. JSON-LD is a W3C standard that adds a thin semantic layer on top of ordinary JSON. CDIF chose JSON-LD for several reasons:

- **Graph semantics.** A JSON-LD document describes a graph of nodes and edges, not just a tree. A dataset, its creator, and that creator's organization are all first-class nodes that can be linked, merged, and queried independently.
- **Namespace-qualified vocabulary.** Every property key maps to an IRI (Internationalized Resource Identifier) via a `@context` declaration. This means `schema:name` in one document and `name` in another can both resolve to `http://schema.org/name`, eliminating ambiguity when combining data from different sources.
- **Self-describing documents.** The `@context` embedded in (or referenced by) a JSON-LD document tells any consumer how to interpret its keys -- no out-of-band schema registry is needed.
- **Dual-stack tooling.** A JSON-LD file is simultaneously valid JSON and valid RDF. It can be processed by JSON libraries (parse, query with JSONPath, validate with JSON Schema) and by RDF/SPARQL tooling (triple stores, reasoners, SHACL validators) without conversion.
- **Multi-typing.** JSON-LD allows `@type` to be an array, so a single node can be typed as both `schema:Action` and `prov:Activity`. CDIF uses this to combine schema.org and PROV-O semantics on activity nodes.
- **Linked Data interoperability.** Because every key and value can be an IRI, JSON-LD documents can link to external vocabularies, controlled term sets, and other datasets on the web.

## 2. JSON vs JSON-LD -- What is Different?

A JSON-LD document **is** syntactically valid JSON. Any JSON parser will read it. The difference is in a handful of reserved keys that carry semantic meaning:

| Reserved key | Purpose |
|---|---|
| `@context` | Maps JSON keys to IRIs; declares namespace prefixes |
| `@id` | Assigns a globally unique identifier (IRI) to a node |
| `@type` | Declares the type(s) of a node (maps to `rdf:type`) |
| `@graph` | Contains an array of nodes (a named or default graph) |
| `@list` | Marks an array as an ordered collection (RDF list) |
| `@value` | Holds a literal value with optional `@type` or `@language` |

### Key conceptual differences

**JSON keys are opaque strings; JSON-LD keys are IRIs.**
In plain JSON, the key `"name"` is just a string. Two systems using `"name"` might mean entirely different things. In JSON-LD, the `@context` maps `"name"` to `http://schema.org/name`, giving it a precise, globally unambiguous meaning.

**A JSON document is a tree; a JSON-LD document is a graph.**
Plain JSON is hierarchical -- objects nest inside objects, forming a tree with a single root. In JSON-LD, nodes have `@id` identifiers and can reference each other, forming an arbitrary graph. The same person node can be the `creator` of one dataset and the `contributor` of another, without duplication.

**JSON arrays are positional; JSON-LD arrays are sets (by default).**
In plain JSON, array order matters. In JSON-LD, arrays are unordered sets unless explicitly wrapped in `@list`. This reflects RDF semantics, where a property can have multiple values but the values have no inherent order.

### Example

Plain JSON:
```json
{
  "name": "Water Quality Observations",
  "creator": {
    "name": "Jane Smith",
    "affiliation": "USGS"
  }
}
```

JSON-LD (same data, with semantic context):
```json
{
  "@context": {
    "schema": "http://schema.org/"
  },
  "@type": "schema:Dataset",
  "@id": "https://doi.org/10.5066/example",
  "schema:name": "Water Quality Observations",
  "schema:creator": {
    "@type": "schema:Person",
    "@id": "https://orcid.org/0000-0001-2345-6789",
    "schema:name": "Jane Smith",
    "schema:affiliation": {
      "@type": "schema:Organization",
      "@id": "https://www.usgs.gov",
      "schema:name": "USGS"
    }
  }
}
```

The JSON-LD version carries the same data, but every key resolves to a schema.org IRI, every node has a globally unique `@id`, and every node has a declared `@type`. A consumer can merge this with another document that references the same `@id` values, and the combined graph will be consistent.

## 3. The Role of `@context`

The `@context` is the bridge between JSON keys and RDF semantics. It tells a JSON-LD processor how to interpret every key in the document.

### Prefix declarations

The most common use is declaring namespace prefixes:

```json
{
  "@context": {
    "schema": "http://schema.org/",
    "prov": "http://www.w3.org/ns/prov#",
    "dqv": "http://www.w3.org/ns/dqv#"
  }
}
```

With these prefixes, the key `"schema:name"` expands to the full IRI `http://schema.org/name`, and `"prov:wasGeneratedBy"` expands to `http://www.w3.org/ns/prov#wasGeneratedBy`.

### Term aliases

A context can also map bare (unprefixed) keys to prefixed or full IRIs:

```json
{
  "@context": {
    "schema": "http://schema.org/",
    "name": "schema:name",
    "creator": "schema:creator",
    "url": {"@id": "schema:url", "@type": "@id"}
  }
}
```

Now authors can write `"name": "Water Quality"` instead of `"schema:name": "Water Quality"`. Both mean the same thing after expansion. The `@type: "@id"` directive on `url` tells the processor that the value of `url` should be treated as an IRI reference, not a plain string.

CDIF provides `CDIF-context-2026.jsonld` as a comprehensive context file with term aliases for all CDIF properties, so authors can write documents with bare property names instead of prefixed keys.

### Container directives

A context entry can also declare the container type for a property's values:

```json
{
  "@context": {
    "keywords": {"@id": "schema:keywords", "@container": "@set"},
    "creator": {"@id": "schema:creator", "@container": "@list"}
  }
}
```

- `@set` -- values are an unordered set (default RDF behavior). Even a single value will be treated as a one-element set.
- `@list` -- values form an ordered RDF list. `schema:creator` uses `@list` in CDIF because author order matters.

### The challenge of context-dependent keys

A consequence of `@context` is that the same data can be expressed with different JSON keys depending on the context. One document might use `"schema:name"`, another might use `"name"`, and a third might use the full IRI `"http://schema.org/name"`. All three are semantically identical, but they look different to a JSON Schema validator that checks property names literally.

This context-dependence is one of the central reasons CDIF needs a **framing** step before JSON Schema validation (explained in sections 8-9).

## 4. Instance Document Validation -- Two Approaches

CDIF validates metadata documents using two complementary technologies:

1. **JSON Schema** validates the **JSON tree structure** -- checking property names, value types, required properties, array lengths, string patterns, and nesting structure. It sees the document as JSON and knows nothing about RDF.

2. **SHACL** (Shapes Constraint Language) validates the **RDF graph** -- checking that nodes of a given type have the right properties, that property values are the right type, that cardinality constraints are met, and that cross-references between nodes are consistent. It operates on RDF triples parsed from the JSON-LD.

Both are needed because JSON-LD is simultaneously JSON and RDF. JSON Schema catches structural problems (wrong nesting, missing keys, incorrect value types) that are invisible to SHACL. SHACL catches semantic problems (missing cross-references, wrong node types, namespace errors) that JSON Schema cannot express.

### Validation pipeline

```
                    JSON-LD document
                          |
             +------------+------------+
             |                         |
        Frame + Compact           Parse to RDF
             |                         |
        JSON tree                 RDF triples
             |                         |
      JSON Schema check          SHACL check
             |                         |
        tree errors              graph errors
```

In CDIF, the JSON Schema path uses `FrameAndValidate.py`, and the SHACL path uses `ShaclValidation/ShaclJSONLDContext.py` with composite shapes files (`ShaclValidation/CDIF-Discovery-Shapes.ttl` or `ShaclValidation/CDIF-Complete-Shapes.ttl`).

## 5. JSON Schema vs SHACL -- Comparison

| Aspect | JSON Schema | SHACL |
|---|---|---|
| **What it validates** | JSON tree structure | RDF graph |
| **Input format** | JSON (after framing/compaction) | RDF triples (parsed from JSON-LD) |
| **Specification** | [JSON Schema](https://json-schema.org/) (Draft 2020-12) | [W3C SHACL](https://www.w3.org/TR/shacl/) |
| **Type dispatch** | `if`/`then`/`else` chains on `@type` value | `sh:targetClass` or SPARQL-based `sh:target` |
| **Cardinality** | `minItems`/`maxItems` (arrays), `required` (keys) | `sh:minCount`/`sh:maxCount` (per property) |
| **Value type checking** | `type: "string"`, `format: "uri"`, `pattern` | `sh:datatype xsd:string`, `sh:class`, `sh:nodeKind` |
| **Severity** | Binary pass/fail | Three levels: Violation, Warning, Info |
| **Cross-references** | Limited (no native `@id` resolution) | Native (`sh:class` checks referenced node types) |
| **Composition** | `allOf`/`$ref`/`$defs` | `sh:node` (reference another shape) |
| **Tooling** | `jsonschema` Python library | `pyshacl` Python library |
| **Key strength** | Validates exact document structure before any RDF processing | Validates semantic correctness regardless of serialization |
| **Key limitation** | Requires controlled serialization (framing) | Cannot check JSON-specific structure |

### When each catches errors the other misses

**JSON Schema catches:**
- Wrong nesting depth (e.g., a `Person` nested inside `distribution` instead of `creator`)
- Properties that are valid in RDF but attached to the wrong parent in JSON
- Missing `@context` or wrong context structure
- Value format errors (a date string that is not ISO 8601)

**SHACL catches:**
- A `schema:creator` node that is missing `schema:name` (regardless of where it appears in the tree)
- Incorrect schema.org namespace variants (`https://schema.org/` instead of `http://schema.org/`)
- A `spdx:checksum` that references a non-existent algorithm IRI
- Cross-node consistency (an `@id` reference that points to a node of the wrong type)

## 6. JSON-LD Serialization Formats

The same RDF graph can be serialized in several JSON-LD forms. Understanding these is key to understanding why validation requires care.

### Compacted (what authors write)

Prefixed keys, nested objects, human-readable. This is the form CDIF authors produce:

```json
{
  "@context": {"schema": "http://schema.org/"},
  "@type": "schema:Dataset",
  "@id": "https://doi.org/10.5066/example",
  "schema:name": "Water Quality",
  "schema:creator": {
    "@type": "schema:Person",
    "@id": "https://orcid.org/0000-0001-2345-6789",
    "schema:name": "Jane Smith"
  }
}
```

### Expanded (full IRIs, no context)

Every prefix is resolved to a full IRI. No `@context` is needed because nothing is abbreviated. Verbose but unambiguous:

```json
[
  {
    "@type": ["http://schema.org/Dataset"],
    "@id": "https://doi.org/10.5066/example",
    "http://schema.org/name": [{"@value": "Water Quality"}],
    "http://schema.org/creator": [
      {
        "@type": ["http://schema.org/Person"],
        "@id": "https://orcid.org/0000-0001-2345-6789",
        "http://schema.org/name": [{"@value": "Jane Smith"}]
      }
    ]
  }
]
```

Note: in expanded form, all values become arrays of `@value` objects, and `@type` is always an array.

### Flattened (flat `@graph` with `@id` references)

All nodes are top-level entries in a `@graph` array. Nesting is replaced by `@id` cross-references:

```json
{
  "@context": {"schema": "http://schema.org/"},
  "@graph": [
    {
      "@type": "schema:Dataset",
      "@id": "https://doi.org/10.5066/example",
      "schema:name": "Water Quality",
      "schema:creator": {"@id": "https://orcid.org/0000-0001-2345-6789"}
    },
    {
      "@type": "schema:Person",
      "@id": "https://orcid.org/0000-0001-2345-6789",
      "schema:name": "Jane Smith"
    }
  ]
}
```

Each serialization is semantically identical -- they all produce the same set of RDF triples. The difference is purely structural, which is exactly why JSON Schema validation requires a controlled form.

## 7. Why a Valid JSON-LD Document Might Not Pass JSON Schema Validation

JSON Schema validates the literal JSON structure -- property names, nesting, value types. Several features of JSON-LD can cause a semantically correct document to fail JSON Schema checks:

### Property names depend on context

The same property can appear as `"schema:name"`, `"name"`, or `"http://schema.org/name"` depending on the `@context`. A JSON Schema that checks for `"schema:name"` will reject a document that uses `"name"`, even though both mean the same thing.

### Framing and compaction change nesting

A person node might be nested inside `schema:creator` in one document and appear as a top-level `@graph` entry in another. JSON Schema checks for specific nesting paths, so different serializations of the same graph will produce different validation results.

### `@type` may be string or array

The JSON-LD specification allows `@type` to be either a string (`"schema:Dataset"`) or an array (`["schema:Dataset"]`). JSON-LD framing compacts single-element `@type` arrays to plain strings. A schema expecting arrays will reject string values and vice versa.

### `@list` vs plain array

`schema:creator` in CDIF uses `@list` to preserve author order. After compaction, an `@list` value appears as `{"@list": [...]}` rather than a plain array. The JSON structure is different even though the data is the same.

### Null values from framing

When a JSON-LD frame requests a property that does not exist in the data, the framing algorithm inserts `null`. These nulls must be removed before JSON Schema validation, since the schema does not expect null values for optional properties.

### `@graph` wrapper

A document with multiple top-level nodes uses `@graph`. A document with a single root node may omit `@graph`. These are structurally different JSON documents describing the same data.

**Bottom line:** JSON Schema validation of JSON-LD requires a normalization step that produces a predictable JSON structure. In CDIF, that step is **framing**.

## 8. What is Framing?

JSON-LD framing reshapes a flat graph of nodes into a nested tree, guided by a template called a **frame**. The frame specifies which node type should be the root, which properties should be embedded (nested), and how deep the embedding should go.

### Before framing -- flat graph

Three independent nodes, cross-referenced by `@id`:

```json
{
  "@context": {"schema": "http://schema.org/"},
  "@graph": [
    {
      "@type": "schema:Dataset",
      "@id": "https://doi.org/10.5066/example",
      "schema:name": "Water Quality Observations",
      "schema:creator": {"@id": "https://orcid.org/0000-0001-2345-6789"}
    },
    {
      "@type": "schema:Person",
      "@id": "https://orcid.org/0000-0001-2345-6789",
      "schema:name": "Jane Smith",
      "schema:affiliation": {"@id": "https://www.usgs.gov"}
    },
    {
      "@type": "schema:Organization",
      "@id": "https://www.usgs.gov",
      "schema:name": "U.S. Geological Survey"
    }
  ]
}
```

### The frame (template)

The frame says: "Give me a tree rooted at `schema:Dataset`, and embed everything you can."

```json
{
  "@context": {"schema": "http://schema.org/"},
  "@type": "schema:Dataset",
  "@embed": "@always",
  "schema:creator": {
    "@embed": "@always",
    "schema:affiliation": {"@embed": "@always"}
  }
}
```

### After framing -- nested tree

The three flat nodes are reassembled into a single nested tree:

```json
{
  "@context": {"schema": "http://schema.org/"},
  "@type": "schema:Dataset",
  "@id": "https://doi.org/10.5066/example",
  "schema:name": "Water Quality Observations",
  "schema:creator": {
    "@type": "schema:Person",
    "@id": "https://orcid.org/0000-0001-2345-6789",
    "schema:name": "Jane Smith",
    "schema:affiliation": {
      "@type": "schema:Organization",
      "@id": "https://www.usgs.gov",
      "schema:name": "U.S. Geological Survey"
    }
  }
}
```

The `Person` is now nested inside `creator`, and the `Organization` is nested inside the person's `affiliation`. The `@id` values are preserved, so the semantic graph is unchanged -- only the JSON structure has changed from flat to nested.

## 9. The CDIF Framing Pipeline

CDIF uses `FrameAndValidate.py` to frame and validate metadata documents. The pipeline has five steps:

### Step 1: Expand

```python
expanded = jsonld.expand(doc)
```

Resolve all prefixes and context mappings to full IRIs. This eliminates context-dependent property names -- `"schema:name"`, `"name"`, and `"http://schema.org/name"` all become `"http://schema.org/name"`. The output is the **expanded form** (section 6).

### Step 2: Frame

```python
framed = jsonld.frame(expanded, frame)
```

Apply the frame template (`CDIF-frame-2026.jsonld`) to reshape the expanded graph into a nested tree rooted at `schema:Dataset`. The frame specifies embedding directives for each property -- `schema:creator` embeds person nodes, `schema:distribution` embeds data download nodes, `prov:wasGeneratedBy` embeds the full activity structure, and so on.

### Step 3: Compact

```python
framed = jsonld.compact(framed, OUTPUT_CONTEXT)
```

Re-introduce namespace prefixes and term mappings to produce readable property names. The output context maps full IRIs back to prefixed keys like `schema:name`, `prov:wasGeneratedBy`, and `dqv:hasQualityMeasurement`.

### Step 4: Extract root dataset

If the compacted output contains a `@graph` array (because multiple `schema:Dataset` nodes exist, e.g., a dataset and its metadata-about-metadata record), extract the main dataset node -- the one with `schema:distribution`.

### Step 5: Post-process (normalize)

The `remove_nulls_and_normalize()` function applies four corrections to make the framed output match JSON Schema expectations:

1. **Remove null values.** Framing inserts `null` for optional properties not present in the data.
2. **Normalize `@type` to arrays.** Framing compacts `["schema:Dataset"]` to `"schema:Dataset"`. The schema expects arrays, so single-string `@type` values are wrapped back into arrays.
3. **Rename unprefixed terms.** Some terms compact to bare names (e.g., `"conformsTo"` instead of `"dcterms:conformsTo"`). These are mapped back to their prefixed forms.
4. **Wrap singletons in arrays.** Properties like `schema:distribution` and `prov:wasGeneratedBy` are defined as arrays in the schema. If framing produces a single object, it is wrapped in a one-element array.

The normalized output then validates against `CDIFDiscoverySchema.json` (discovery profile) or `CDIFCompleteSchema.json` (complete profile).

## 10. Why Framing is Useful

Framing provides several practical benefits beyond just enabling JSON Schema validation:

**Standard JSON tooling.** After framing, a CDIF document is a predictable JSON tree. It can be queried with JSONPath, processed with `jq`, indexed by search engines, and consumed by any application that reads JSON -- no RDF libraries required.

**Human readability.** A nested tree where a person is inside `creator` and an organization is inside `affiliation` is much easier to read than a flat `@graph` array where those relationships are expressed through `@id` cross-references.

**JSON Schema validation.** Tree-shaped schemas with `required`, `properties`, and `$defs` can check nesting, cardinality, and value constraints. This is only possible when the document has a predictable tree structure.

**Deterministic output.** Given the same graph and the same frame, the framing algorithm produces the same tree. This means validation results are reproducible regardless of how the input was originally serialized.

**JSONPath querying.** With a consistent tree structure, paths like `$.schema:creator[0].schema:name` reliably locate the first creator's name across all CDIF documents.

## 11. Benefits of the Flattened Format

While framing is essential for JSON Schema validation, the flattened (`@graph`) format has its own advantages:

**Natural for RDF.** Each node in the `@graph` array maps directly to a set of RDF triples. There is no ambiguity about which node "owns" a property -- every property is on the node where it is declared.

**Circular references.** Flat graphs handle circular references naturally. Node A can reference node B by `@id`, and node B can reference node A. This is impossible in a strict tree. Provenance chains, for example, can have activities that reference each other.

**Graph merging.** Combining two flattened documents is a union of their `@graph` arrays (with deduplication by `@id`). There is no need to figure out how nested trees should be merged.

**No duplication.** In a nested tree, if two different properties reference the same person node, that person's data might be duplicated at both nesting locations. In a flat graph, the person appears once and is referenced by `@id` wherever needed.

**SPARQL querying.** Flattened JSON-LD can be loaded directly into an RDF triple store and queried with SPARQL, which is the standard query language for RDF graphs.

**RO-Crate compatibility.** [RO-Crate](https://www.researchobject.org/ro-crate/), a widely used research data packaging format, requires the flattened `@graph` structure. CDIF metadata can be converted to RO-Crate using `ConvertToROCrate.py`.

**Graph schema validation.** CDIF provides `CDIF-graph-schema-2026.json`, a JSON Schema that validates flattened `@graph` documents directly without framing. It uses an `if`/`then`/`else` dispatch chain on `@type` to validate each node in the `@graph` array against the correct type-specific sub-schema.

## Summary

| Concept | Key point |
|---|---|
| JSON-LD | JSON with semantic annotations (`@context`, `@id`, `@type`, `@graph`) |
| `@context` | Maps JSON keys to IRIs; enables vocabulary interoperability |
| Framing | Reshapes a flat graph into a nested tree for JSON Schema validation |
| JSON Schema | Validates the JSON tree structure (property names, types, nesting) |
| SHACL | Validates the RDF graph semantics (node types, cross-references, cardinality) |
| Flattened format | Natural for RDF, supports circular refs and merging, used by RO-Crate |
| Both needed | JSON Schema catches structural errors; SHACL catches semantic errors |

## CDIF Validation Files Reference

| File | Purpose |
|---|---|
| `FrameAndValidate.py` | Frames JSON-LD and validates against JSON Schema |
| `CDIF-frame-2026.jsonld` | Frame template for reshaping graphs into trees |
| `CDIF-context-2026.jsonld` | Context for prefix-free authoring |
| `CDIFDiscoverySchema.json` | JSON Schema for discovery profile (framed tree) |
| `CDIFCompleteSchema.json` | JSON Schema for complete profile (framed tree) |
| `CDIF-graph-schema-2026.json` | JSON Schema for flattened `@graph` documents |
| `ShaclValidation/ShaclJSONLDContext.py` | SHACL validation script |
| `ShaclValidation/CDIF-Discovery-Shapes.ttl` | SHACL shapes for discovery profile |
| `ShaclValidation/CDIF-Complete-Shapes.ttl` | SHACL shapes for complete profile |
| `ShaclValidation/generate_shacl_report.py` | Generates structured SHACL validation reports |
| `batch_validate.py` | Runs both JSON Schema and SHACL validation across file groups |

## Further Reading

- [JSON-LD 1.1 Specification](https://www.w3.org/TR/json-ld11/)
- [JSON-LD Framing](https://www.w3.org/TR/json-ld11-framing/)
- [JSON Schema](https://json-schema.org/)
- [SHACL (Shapes Constraint Language)](https://www.w3.org/TR/shacl/)
- [RO-Crate Specification](https://www.researchobject.org/ro-crate/specification/)
- [Schema.org](https://schema.org/)
