# CDIF Provenance Building Blocks: Comparison of Three Approaches

**Date:** 2026-02-25
**Status:** Draft for review
**Repository:** [usgin/metadataBuildingBlocks](https://github.com/usgin/metadataBuildingBlocks)

## 1. Overview

CDIF provides three building blocks for describing activities that produce datasets. All three serve as the value for `prov:wasGeneratedBy` on a `schema:Dataset`, following the W3C PROV pattern: `Dataset --prov:wasGeneratedBy--> Activity`. Each building block uses a different primary vocabulary while describing the same provenance concepts: what was done, who did it, what was used, what was produced, and how it was done.

| Building Block | Primary Vocabulary | Activity Type | Location |
|---|---|---|---|
| **cdifProv** | schema.org + PROV-O | `["schema:Action", "prov:Activity"]` | [cdifProperties/cdifProv](https://github.com/usgin/metadataBuildingBlocks/tree/main/_sources/cdifProperties/cdifProv) |
| **provActivity** | W3C PROV-O | `["prov:Activity"]` | [provProperties/provActivity](https://github.com/usgin/metadataBuildingBlocks/tree/main/_sources/provProperties/provActivity) |
| **ddicdiProv** | DDI-CDI 1.0 | `cdi:Activity` | [ddiProperties/ddicdiProv](https://github.com/usgin/metadataBuildingBlocks/tree/main/_sources/ddiProperties/ddicdiProv) |

All three building blocks share a common example scenario -- a soil chemistry analysis (ICP-MS and XRF spectrometry on soil samples from a Great Basin transect) -- to facilitate direct comparison.

### Links to schemas and examples

| Building Block | Resolved Schema | Example Instance |
|---|---|---|
| cdifProv | [resolvedSchema.json](https://github.com/usgin/metadataBuildingBlocks/blob/main/_sources/cdifProperties/cdifProv/resolvedSchema.json) | [exampleCdifProv.json](https://github.com/usgin/metadataBuildingBlocks/blob/main/_sources/cdifProperties/cdifProv/exampleCdifProv.json) |
| provActivity | [provActivitySchema.json](https://github.com/usgin/metadataBuildingBlocks/blob/main/_sources/provProperties/provActivity/provActivitySchema.json) | [exampleProvActivity.json](https://github.com/usgin/metadataBuildingBlocks/blob/main/_sources/provProperties/provActivity/exampleProvActivity.json) |
| ddicdiProv | [resolvedSchema.json](https://github.com/usgin/metadataBuildingBlocks/blob/main/_sources/ddiProperties/ddicdiProv/resolvedSchema.json) | [exampleDdicdiProv.json](https://github.com/usgin/metadataBuildingBlocks/blob/main/_sources/ddiProperties/ddicdiProv/exampleDdicdiProv.json) |

A multi-activity CDIF provenance example (using cdifProv) is also available: [prov-ocean-temp-example.json](https://github.com/usgin/metadataBuildingBlocks/blob/main/../../../CDIF/validation/MetadataExamples/prov-ocean-temp-example.json) in the CDIF validation repository.

## 2. Design Rationale

### cdifProv -- Schema.org-first with PROV-O linkage

The cdifProv building block is the primary CDIF recommendation. It follows the approach developed by the [ODIS (Ocean Data and Information System) Architecture](https://github.com/iodepo/odis-arch/blob/414-update-provenance-recommendations/book/thematics/provenance/common-provenance-cases.md) provenance recommendations, which map schema.org `Action` to `prov:Activity` and use schema.org properties (`agent`, `object`, `result`, `instrument`, `startTime`, `endTime`, `location`, `actionProcess`) to describe provenance in a vocabulary already familiar to web developers and search engines.

Activity nodes carry dual types `["schema:Action", "prov:Activity"]` so that:
- Schema.org-aware consumers (search engines, web crawlers) see a well-typed `Action`
- PROV-aware consumers (provenance trackers, RDF reasoners) see a `prov:Activity`
- The `prov:used` property (from the base `generatedBy` building block) provides backward-compatible input listing

The `schema:actionProcess` property (domain: `schema:Action`, range: `schema:HowTo`) links activities to structured methodology descriptions with ordered `HowToStep` arrays. This property was added to schema.org via [PR #3692](https://github.com/schemaorg/schemaorg/issues/3692) (merged October 2024, available in schema.org V29.4+).

### provActivity -- PROV-O-first with schema.org fallbacks

The provActivity building block prioritizes W3C PROV-O vocabulary, using native PROV-O properties wherever they exist and falling back to schema.org only for concepts PROV-O does not cover (name, description, instrument, methodology, action status). This approach is appropriate for communities already invested in PROV-O tooling and ontologies, or where formal provenance reasoning (e.g., PROV constraints checking) is needed.

Activity nodes are typed `["prov:Activity"]` only -- no `schema:Action` dual typing is required.

### ddicdiProv -- DDI-CDI native workflow description

The ddicdiProv building block uses the [DDI Cross-Domain Integration (DDI-CDI) 1.0](https://ddialliance.org/Specification/DDI-CDI/1.0/) vocabulary natively. It is designed for communities already using DDI-CDI for statistical and survey data, where the detailed workflow modeling capabilities of DDI-CDI (Steps, Parameters, data flow between steps, ProcessingAgents, ProductionEnvironments) are valuable.

This building block is based on the [BBeuster EU-SoGreen-Prov](https://github.com/ddialliance/ddi-cdi_provenance-examples) example pattern from the DDI Alliance.

## 3. Property Mapping

The table below shows how each provenance concept maps across the three building blocks.

| Concept | cdifProv | provActivity | ddicdiProv |
|---|---|---|---|
| **Activity type** | `["schema:Action", "prov:Activity"]` | `["prov:Activity"]` | `cdi:Activity` |
| **Name** | `schema:name` | `schema:name` (fallback) | `cdi:name` (ObjectName wrapper) |
| **Description** | `schema:description` | `schema:description` (fallback) | `cdi:description` |
| **Inputs** | `prov:used` (from base) | `prov:used` (from base) | `cdi:entityUsed` (Reference) |
| **Outputs** | `schema:result` | `prov:generated` | `cdi:entityProduced` (Reference) |
| **Agent** | `schema:agent` (inline Person/Org) | `prov:wasAssociatedWith` (inline Person/Org) | Separate `cdi:ProcessingAgent` node with `cdi:performs` |
| **Instrument** | Within `prov:used` items via `schema:instrument` sub-key | Within `prov:used` items via `schema:instrument` sub-key | Not directly supported (use `cdi:entityUsed`) |
| **Methodology** | `schema:actionProcess` -> `schema:HowTo` with `schema:HowToStep` | `schema:actionProcess` -> `schema:HowTo` (fallback) | `cdi:has_Step` -> separate `cdi:Step` nodes with `cdi:script` (CommandCode) |
| **Start time** | `schema:startTime` | `prov:startedAtTime` | Not expressible |
| **End time** | `schema:endTime` | `prov:endedAtTime` | Not expressible |
| **Location** | `schema:location` | `prov:atLocation` | Separate `cdi:ProductionEnvironment` node |
| **Activity chain** | `schema:object` / `schema:result` | `prov:wasInformedBy` | `cdi:hasSubActivity`, `cdi:has_Step` |
| **Status** | `schema:actionStatus` | `schema:actionStatus` (fallback) | Not expressible |
| **Data flow** | Not explicit | Not explicit | `cdi:receives` / `cdi:produces` -> `cdi:Parameter` nodes |
| **Error** | `schema:error` | `schema:error` (fallback) | Not expressible |
| **Start trigger** | -- | `prov:wasStartedBy` | -- |
| **End trigger** | -- | `prov:wasEndedBy` | -- |
| **Standard model** | -- | -- | `cdi:standardModelMapping` (e.g., GSBPM) |
| **Serialization** | Single-node (inline in graph) | Single-node (inline in graph) | Multi-node `@graph` document |

### Instrument handling

All three schema.org-based building blocks (cdifProv and provActivity) use a shared pattern for instruments: instruments are nested within `prov:used` items using a `schema:instrument` sub-key. This reflects the W3C PROV model where instruments are a subclass of `prov:Entity` and belong among the entities "used" by an activity. Instruments reference the generic [instrument building block](https://github.com/usgin/metadataBuildingBlocks/tree/main/_sources/schemaorgProperties/instrument), which supports hierarchical instrument systems via `schema:hasPart` for sub-components.

```json
"prov:used": [
    {
        "schema:instrument": {
            "@type": ["schema:Thing", "schema:DefinedTerm"],
            "schema:name": "ICP-MS",
            "schema:hasPart": [ ... sub-components ... ]
        }
    },
    "https://vocab.nerc.ac.uk/collection/L05/current/LAB02",
    { "@type": "schema:CreativeWork", "schema:name": "EPA Method 6200" }
]
```

DDI-CDI has no dedicated instrument class; instruments would be described as `cdi:entityUsed` references or through `cdi:Parameter` bindings on steps.

### Methodology description

cdifProv and provActivity both use `schema:actionProcess` to link to a `schema:HowTo` with ordered `schema:HowToStep` entries. This keeps methodology inline and human-readable.

ddicdiProv uses `cdi:has_Step` to reference separate `cdi:Step` graph nodes, each with `cdi:script` (containing `cdi:CommandCode` / `cdi:CommandFile` for executable references) and `cdi:receives` / `cdi:produces` for explicit data-flow Parameters. This is more detailed but requires a multi-node graph structure.

## 4. Structural Differences

### Single-node vs. multi-node serialization

cdifProv and provActivity produce a single JSON object that can be embedded inline as the value of `prov:wasGeneratedBy` on a Dataset node, or placed as a separate node in a `@graph` array with an `@id` reference from the Dataset.

ddicdiProv produces a multi-node `@graph` document with separate nodes for the Activity, each Step, each Parameter, the ProcessingAgent, and the ProductionEnvironment. These nodes cross-reference each other via `@id`. This makes ddicdiProv more verbose but enables richer querying of individual workflow components.

**cdifProv / provActivity** (single node, ~77 lines):
```
Activity node
  +-- prov:used (inline array of instruments, references, strings)
  +-- schema:agent (inline Person)
  +-- schema:actionProcess (inline HowTo with HowToSteps)
  +-- schema:location (inline Place)
```

**ddicdiProv** (8 separate graph nodes, ~178 lines):
```
@graph:
  Activity node  --cdi:has_Step-->  Step 1, Step 2
                 --cdi:entityUsed-->  References
                 --cdi:entityProduced-->  References
  Step 1  --cdi:receives-->  Parameter (soil samples)
          --cdi:produces-->  Parameter (digested solutions)
  Step 2  --cdi:receives-->  Parameter (digested solutions)
          --cdi:produces-->  Parameter (measurement data)
  ProcessingAgent  --cdi:performs-->  Activity
                   --cdi:operatesOn-->  ProductionEnvironment
  ProductionEnvironment
```

### Schema composition

cdifProv and provActivity both extend a common base building block (`generatedBy`) via JSON Schema `allOf`, inheriting the minimal `@type: prov:Activity` + `prov:used` foundation and adding their vocabulary-specific properties on top.

ddicdiProv is a standalone schema with its own `$defs` section (15 type definitions) -- it does not extend the `generatedBy` base because DDI-CDI uses entirely different property names.

## 5. Benefits and Challenges

### cdifProv

**Benefits:**
- Broadest interoperability with web infrastructure: schema.org Action is understood by Google Dataset Search, web crawlers, and general-purpose JSON-LD consumers
- Aligned with [ODIS/OIH provenance recommendations](https://github.com/iodepo/odis-arch/blob/414-update-provenance-recommendations/book/thematics/provenance/common-provenance-cases.md), enabling interoperability with the Ocean InfoHub community
- Dual typing (`schema:Action` + `prov:Activity`) bridges the schema.org and PROV-O worlds without requiring consumers to understand both
- Compact single-node serialization is easy to author and embed
- `schema:actionProcess` -> `HowTo` -> `HowToStep` provides human-readable methodology that search engines can surface
- Action chaining via `schema:object` / `schema:result` supports multi-step provenance lineage

**Challenges:**
- `schema:actionProcess` is present on the schema.org website (V29.4+) but has not yet appeared in the downloadable RDF vocabulary files, which may cause issues for strict RDF validators
- Dual typing adds a concept (`schema:Action`) that is less familiar to provenance specialists
- No explicit data-flow modeling between steps (inputs/outputs of individual steps are not tracked)
- Agents are limited to a single `schema:agent` (plus `schema:participant` array), rather than the richer qualified associations of full PROV-O

### provActivity

**Benefits:**
- Uses canonical W3C PROV-O property names (`prov:wasAssociatedWith`, `prov:generated`, `prov:startedAtTime`, `prov:wasInformedBy`), enabling direct use with PROV-O reasoning tools and constraint validators
- Simpler typing -- `prov:Activity` only, no need to understand schema.org Action
- Supports PROV-O expanded terms (`prov:wasStartedBy`, `prov:wasEndedBy`, `prov:atLocation`) not available in schema.org
- Activity-to-activity chaining via `prov:wasInformedBy` is more precise than schema.org's `object`/`result` pattern (which conflates input entities with prior activities)
- Falls back to schema.org gracefully for properties PROV-O lacks (name, description, instrument, methodology, status)

**Challenges:**
- PROV-O property names are less familiar to web developers and not recognized by search engines
- No `schema:Action` typing means schema.org-only consumers won't interpret the provenance properties
- The mix of `prov:` and `schema:` prefixes (e.g., `prov:wasAssociatedWith` for agent but `schema:actionProcess` for methodology) may confuse implementers
- Qualified PROV-O patterns (`prov:qualifiedAssociation`, `prov:qualifiedUsage`, `prov:qualifiedGeneration`) are deferred, limiting the expressiveness advantage over cdifProv
- PROV-O has no native property for methodology/plans outside of qualified associations (`prov:hadPlan` requires `prov:qualifiedAssociation`), forcing a schema.org fallback

### ddicdiProv

**Benefits:**
- Native DDI-CDI vocabulary is directly compatible with DDI-CDI-based statistical infrastructure and tools
- Explicit data-flow modeling via `cdi:Parameter` with `cdi:receives` / `cdi:produces` tracks how data moves between steps -- useful for reproducibility and pipeline documentation
- `cdi:Step` nodes with `cdi:script` (CommandCode/CommandFile) can reference executable code, enabling automated reproducibility
- `cdi:ProcessingAgent` with `cdi:operatesOn` -> `cdi:ProductionEnvironment` captures where the agent runs, not just where the activity happened
- `cdi:standardModelMapping` links activities to standard process models (e.g., [GSBPM](https://statswiki.unece.org/display/GSBPM/))
- Multi-node graph structure enables fine-grained SPARQL queries on individual workflow components

**Challenges:**
- DDI-CDI vocabulary is specialized and not widely recognized outside the statistical/survey data community
- Multi-node graph structure is significantly more verbose (~2.5x the line count for the same scenario)
- Cannot express temporal bounds (start/end time), activity status, or location directly on the Activity -- these concepts are gaps in the DDI-CDI 1.0 specification
- No dedicated instrument class -- instruments must be described as generic entity references
- Agent-activity relationship is inverted (`ProcessingAgent --cdi:performs--> Activity` rather than `Activity --agent--> Person`), which is counterintuitive for some implementations
- Structured name wrappers (`cdi:ObjectName`, `cdi:LabelForDisplay`, `cdi:LanguageString`) add verbosity for simple string values
- Not understood by web search engines or general-purpose JSON-LD consumers
- Authoring requires understanding the DDI-CDI class hierarchy and Reference patterns

## 6. When to Use Each Approach

| Use Case | Recommended Building Block |
|---|---|
| General CDIF metadata with web discoverability | **cdifProv** |
| Interoperability with ODIS / Ocean InfoHub | **cdifProv** |
| PROV-O tooling and formal provenance reasoning | **provActivity** |
| Integration with PROV-O constraint validators | **provActivity** |
| DDI-CDI infrastructure and statistical workflows | **ddicdiProv** |
| Detailed data-flow modeling between processing steps | **ddicdiProv** |
| Automated reproducibility with executable code references | **ddicdiProv** |
| Minimal authoring effort | **cdifProv** or **provActivity** |

Multiple building blocks can coexist in the same CDIF ecosystem. A Dataset's `prov:wasGeneratedBy` can point to an activity described using any of the three approaches, and the base `generatedBy` building block provides a minimal common denominator (`@type: prov:Activity` + `prov:used`) that all PROV-aware consumers can process.

## 7. Shared Infrastructure

### Base generatedBy building block

Both cdifProv and provActivity extend the [generatedBy](https://github.com/usgin/metadataBuildingBlocks/tree/main/_sources/provProperties/generatedBy) building block via JSON Schema `allOf`. The base requires:
- `@type` array containing `prov:Activity`
- `prov:used` array of strings or `@id` references

This ensures any consumer that understands `prov:Activity` and `prov:used` can extract basic provenance from any CDIF document, regardless of which extended building block was used.

### Instrument building block

The generic [instrument](https://github.com/usgin/metadataBuildingBlocks/tree/main/_sources/schemaorgProperties/instrument) building block (new) provides a reusable `schema:Thing`-based instrument description with:
- Required `@type` containing `schema:Thing`
- `schema:name`, `schema:identifier`, `schema:description`, `schema:alternateName`
- `schema:additionalType` for domain-specific type URIs
- `schema:additionalProperty` for domain-specific key-value properties (detection limits, calibration info, etc.)
- `schema:hasPart` for hierarchical instrument systems (recursive self-reference)

This building block is referenced by cdifProv, provActivity, and the XAS-specific instrument building block.

### SHACL validation

All three building blocks include companion `rules.shacl` files providing SHACL validation shapes with three severity levels:
- **Violation** (required): properties that must be present
- **Warning** (recommended): properties that should be present for good practice
- **Info** (optional): properties that enhance the description

## 8. Sources and References

### Standards and specifications

- [W3C PROV-O: The PROV Ontology](https://www.w3.org/TR/prov-o/) -- OWL ontology for PROV-DM
- [W3C PROV-DM: The PROV Data Model](https://www.w3.org/TR/prov-dm/) -- core data model for provenance interchange
- [DDI-CDI 1.0 Specification](https://ddialliance.org/Specification/DDI-CDI/1.0/) -- DDI Cross-Domain Integration standard
- [schema.org Action](https://schema.org/Action) -- schema.org type for describing actions/activities
- [schema.org actionProcess](https://schema.org/actionProcess) -- property linking Actions to HowTo methodology (V29.4+)
- [schema.org HowTo](https://schema.org/HowTo) -- methodology description type
- [schema.org instrument](https://schema.org/instrument) -- the object that helped the agent perform the action

### Community recommendations and patterns

- [ODIS Architecture: Common Provenance Cases](https://github.com/iodepo/odis-arch/blob/414-update-provenance-recommendations/book/thematics/provenance/common-provenance-cases.md) -- ODIS/Ocean InfoHub provenance recommendations using schema.org Action + PROV-O patterns. The cdifProv building block implements the core patterns from this document: dual-typed activities, `schema:actionProcess` -> `HowTo` methodology, agent/instrument/object/result action chaining, and `schema:Claim` for quality assertions.
- [Ocean InfoHub (OIH)](https://oceaninfohub.org/) -- the implementation community driving the ODIS provenance recommendations
- [BBeuster EU-SoGreen-Prov DDI-CDI Provenance Examples](https://github.com/ddialliance/ddi-cdi_provenance-examples) -- DDI Alliance community example that the ddicdiProv building block is based on
- [UNECE Generic Statistical Business Process Model (GSBPM) v5.1](https://statswiki.unece.org/display/GSBPM/) -- standard process model referenced by ddicdiProv's `standardModelMapping`

### Schema infrastructure

- [JSON Schema Draft 2020-12](https://json-schema.org/draft/2020-12/schema) -- schema language used by all building blocks
- [OGC Building Blocks](https://opengeospatial.github.io/bblocks/) -- modular schema composition pattern used for building block organization
- [NERC Vocabulary Server (NVS)](https://vocab.nerc.ac.uk/) -- controlled vocabulary for instrument and technique terms used in examples
