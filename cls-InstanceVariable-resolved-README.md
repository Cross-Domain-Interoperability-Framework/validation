# cls-InstanceVariable-resolved.json

## Overview

`cls-InstanceVariable-resolved.json` is a self-contained JSON Schema (Draft 2020-12) for the DDI-CDI `InstanceVariable` class, derived from the full DDI-CDI normative schema (`ddi-cdi.schema_normative.json`). All `$ref` references have been resolved to produce a standalone schema that can be used for validation without requiring the full 395-definition DDI-CDI schema.

## Source

- **Input:** `ddi-cdi.schema_normative.json` (813 KB, 395 definitions, 2,478 cross-references)
- **Output:** `cls-InstanceVariable-resolved.json` (3.9 MB, 26 top-level properties, 58 `$defs` entries)
- **Root definition:** `#/$defs/cls-InstanceVariable`

## Transformations applied

The following transformations were applied during generation:

### 1. Removal of reverse relationship properties

All properties containing `_OF_` in their name were removed from every `cls-*` definition. These are reverse (inverse) relationship properties generated from the bidirectional associations in the DDI-CDI UML model. For example, `cls-InstanceVariable` originally had 58 properties; 31 of these were reverse properties such as:

- `isDescribedBy_OF_DataPoint` (reverse of `DataPoint.isDescribedBy`)
- `has_InstanceVariable_OF_LogicalRecord` (reverse of `LogicalRecord.has_InstanceVariable`)
- `hasSource_OF_InstanceVariableMap` (reverse of `InstanceVariableMap.hasSource`)

**Rationale:** In JSON-LD, reverse relationships can be expressed using the `@reverse` keyword when needed. Including both directions in the schema creates circular reference chains that prevent `$ref` resolution. Removing the 767 reverse properties across all classes eliminated approximately 60% of the circular dependencies in the schema.

### 2. Removal of `catalogDetails` property and `dt-CatalogDetails`

The `catalogDetails` property was removed from all 56 `cls-*` definitions that included it, and the `dt-CatalogDetails` datatype definition was omitted entirely. This also eliminated 6 datatype definitions that were exclusively referenced by `dt-CatalogDetails`:

- `dt-AccessInformation`
- `dt-EmbargoInformation`
- `dt-FundingInformation`
- `dt-LicenseInformation`
- `dt-ProvenanceInformation`
- `dt-InternationalIdentifier`

**Rationale:** Catalog-level metadata (access information, embargo, funding, licensing, provenance) is not relevant to instance-level variable validation.

### 3. Omission of selected class definitions

Three class definitions were omitted, simplifying their corresponding `target-*` definitions to IRI-reference-only:

| Omitted class | Reason | Effect on `target-*` |
|---|---|---|
| `cls-DataPoint` | Not needed for variable validation | `target-DataPoint` accepts IRI only |
| `cls-Datum` | Not needed for variable validation | `target-Datum` reduced from 3 to 2 options |
| `cls-RepresentedVariable` | Redundant; `cls-InstanceVariable` inherits all 21 of its properties and adds 6 more | `target-RepresentedVariable` reduced from 3 to 2 options |

### 4. Inlining of XSD primitive types

All `xsd:*` type definitions were inlined directly rather than referenced via `$ref`. These are simple one-line definitions:

| Definition | Inlined as |
|---|---|
| `xsd:string` | `{"type": "string"}` |
| `xsd:integer` | `{"type": "integer"}` |
| `xsd:boolean` | `{"type": "boolean"}` |
| `xsd:date` | `{"type": "string", "format": "date"}` |
| `xsd:anyURI` | `{"type": "string", "format": "uri-reference"}` |
| `xsd:language` | `{"type": "string", "pattern": "^[a-zA-Z]+(-[a-zA-Z]+)*$"}` |

### 5. Normalization of `if/then/else` to `anyOf`

The source schema uses two different patterns to express "single value or array" for multi-valued properties:

**Pattern A** (`if/then/else`, 196 occurrences in source — used for class-owned attributes):
```json
{
  "if": {"type": "array"},
  "then": {"items": {"$ref": "#/$defs/dt-ObjectName"}},
  "else": {"$ref": "#/$defs/dt-ObjectName"}
}
```

**Pattern B** (`anyOf`, 897 occurrences in source — used for inter-class relationships):
```json
{
  "anyOf": [
    {"type": "array", "items": {"$ref": "#/$defs/dt-ObjectName"}},
    {"$ref": "#/$defs/dt-ObjectName"}
  ]
}
```

These are semantically equivalent. All 105 instances of Pattern A reachable from `cls-InstanceVariable` were normalized to Pattern B for consistency and better tooling support.

### 6. `$ref` resolution strategy

Definitions are handled using a frequency-based strategy to balance readability against file size:

- **Definitions used more than 3 times** are placed in the local `$defs` section and referenced via `$ref`. This avoids duplicating large definition blocks.
- **Definitions used 3 or fewer times** are inlined directly at the point of use.
- **Circular references** (caused by forward compositional cycles in the DDI-CDI model) are left as `$ref` entries pointing to `$defs`, with a `"$comment": "circular-ref"` marker. There are 123 such markers in the output.

## Circular references

The DDI-CDI data model contains inherent circular dependencies in its forward (non-reverse) relationships. These cannot be eliminated without changing the data model. Examples:

- `DataStructure.has_DataStructureComponent` -> `AttributeComponent.qualifies` -> `DataStructureComponent` -> `DataStructure`
- `DimensionalKeyDefinitionMember.isRepresentedBy` -> `DimensionalKeyMember.represents` -> `ConceptualValue` -> `DimensionalKeyDefinitionMember`

In the resolved schema, these appear as `$ref` entries with the `"circular-ref"` comment. The 58 `$defs` entries include all definitions needed to resolve both shared references and circular references.

## Output structure

```
cls-InstanceVariable-resolved.json
  $schema: "https://json-schema.org/draft/2020-12/schema"
  title: "DDI-CDI cls-InstanceVariable (resolved)"
  type: "object"
  properties: (26 properties)
    @context, @id, @type
    physicalDataType, platformType, source, variableFunction
    describedUnitOfMeasure, hasIntendedDataType, simpleUnitOfMeasure
    descriptiveText, unitOfMeasureKind
    definition, displayLabel, externalDefinition, identifier, name
    has_PhysicalSegmentLayout, has_ValueMapping
    takesSentinelValuesFrom, takesSubstantiveValuesFrom_SubstantiveValueDomain
    measures, takesSentinelConceptsFrom, takesSubstantiveConceptsFrom
    uses_Concept, sameAs
  required: ["@type"]
  additionalProperties: false
  $defs: (58 definitions)
    Datatypes: dt-ControlledVocabularyEntry, dt-Identifier, dt-InternationalString,
               dt-LabelForDisplay, dt-ObjectName, dt-Reference, and 12 others
    Targets:   target-InstanceVariable, target-DataStructure,
               target-PhysicalSegmentLayout, target-ValueMapping, and 34 others
    Classes:   cls-ProcessingAgent, cls-QualifiedMeasure, cls-StatisticalClassification
    Other:     at-context, owl:sameAs, enum-WhiteSpaceRule
```

## Regeneration

The schema was generated using a Python script that:

1. Loads `ddi-cdi.schema_normative.json`
2. Applies the transformations described above to build a modified definition set
3. Counts `$ref` usage transitively from `cls-InstanceVariable` to determine shared vs. inlined definitions
4. Recursively resolves `$ref` entries with cycle detection and global caching
5. Iteratively adds any missing `$defs` entries and prunes unreferenced ones
6. Validates the output against JSON Schema Draft 2020-12

Dependencies: `pip install jsonschema`
