# CDIF to DDI-CDI Formal Property Mapping

**Date:** 2026-03-02
**Source schemas:**
- CDIF: `CDIFCompleteSchema.json` and building blocks in `BuildingBlockSubmodule/_sources/cdifProperties/`
- DDI-CDI: `ddi-cdi.schema_normative.json` (v1.0)
- DDI-CDI specification: https://docs.ddialliance.org/DDI-CDI/1.0/model/FieldLevelDocumentation/DDICDILibrary/index.html
- DDI-CDI native provenance: `ddicdiProv` building block in `BuildingBlockSubmodule/_sources/ddiProperties/ddicdiProv/`

## Overview

CDIF implements a flattened subset of the DDI-CDI model for data description and provenance. The DDI-CDI model defines 158 classes in a multi-level UML hierarchy; CDIF uses ~37 `cdi:`-prefixed properties and ~12 `csvw:`-prefixed properties drawn from approximately 5 core DDI-CDI data description classes, plus provenance concepts mapped through `cdifProv`:

| DDI-CDI Class | CDIF Usage Context |
|---|---|
| `InstanceVariable` | `schema:variableMeasured` items |
| `PhysicalSegmentLayout` | `tabularTextDatasetMapping_type` (dataset-level) |
| `ValueMapping` | `physicalMapping_type` / `cdi:hasPhysicalMapping` items |
| `DataStore` | `distributionBase_type` (distribution-level) |
| `DataStructureComponent` subclasses | `cdi:role` enum values on variableMeasured |
| `Activity` | `cdifProv` activity (via `prov:wasGeneratedBy`) |
| `Step` | `schema:actionProcess` → HowTo/HowToStep |
| `ProcessingAgent` | `schema:agent` on activity |
| `ProductionEnvironment` | `schema:location` on activity |

CDIF flattens the DDI-CDI multi-class hierarchy into JSON-LD objects at three levels: distribution, dataset mapping (tabular, structured, or long), and per-variable physical mapping. Where DDI-CDI uses separate objects linked by relationships, CDIF inlines properties directly. For provenance, CDIF uses a dual-typed `["schema:Action", "prov:Activity"]` node that maps to DDI-CDI `Activity`, `Step`, and `ProcessingAgent` concepts using schema.org and PROV-O vocabularies.

---

## 1. InstanceVariable Mapping

**CDIF location:** `variableMeasured_type` in CDIFCompleteSchema.json; `cdifVariableMeasured/schema.yaml` building block
**DDI-CDI class:** `cls-InstanceVariable` (inherits from RepresentedVariable > ConceptualVariable > Concept)

| CDIF Property | Type | DDI-CDI Property | Notes |
|---|---|---|---|
| `@type` (contains `cdi:InstanceVariable`) | array | `@type` | Requires both `schema:PropertyValue` and `cdi:InstanceVariable` |
| `@id` | string | `@id` | For cross-references from `cdi:formats_InstanceVariable` |
| `schema:name` | string | `name` (Concept) | DDI-CDI uses ObjectName type |
| `schema:description` | string | `descriptiveText` (ConceptualVariable) | DDI-CDI uses InternationalString |
| `schema:propertyID` | array | Concept.`identifier` | Inherited from Concept class |
| `schema:measurementTechnique` | string/DefinedTerm | -- | No DDI-CDI equivalent |
| `schema:unitText` | string | `simpleUnitOfMeasure` (RepresentedVariable) | Parallel to `cdi:simpleUnitOfMeasure` |
| `schema:unitCode` | string/DefinedTerm | `describedUnitOfMeasure` (RepresentedVariable) | Parallel to `cdi:describedUnitOfMeasure` |
| `schema:minValue` | number | SubstantiveValueDomain | Via valueDomain chain |
| `schema:maxValue` | number | SubstantiveValueDomain | Via valueDomain chain |
| `schema:url` | uri | `externalDefinition` (Concept) | Approximate match |
| `cdi:intendedDataType` | string | `hasIntendedDataType` (RepresentedVariable) | DDI-CDI uses ControlledVocabularyEntry |
| `cdi:role` | enum (5 values) | -- | DDI-CDI uses DataStructureComponent subclasses |
| `cdi:describedUnitOfMeasure` | DefinedTerm | `describedUnitOfMeasure` (RepresentedVariable) | Direct mapping |
| `cdi:simpleUnitOfMeasure` | string/DefinedTerm | `simpleUnitOfMeasure` (RepresentedVariable) | Also accepts @id reference |
| `cdi:uses` | array | -- | Same as `schema:propertyID`; no DDI-CDI match |
| `cdi:identifier` | string | `identifier` (Concept) | DDI-CDI uses composite Identifier type |
| `cdi:name` | string | `name` (Concept) | DDI-CDI-native naming; redundant with `schema:name` |
| `cdi:displayLabel` | string | `displayLabel` (Concept) | DDI-CDI uses multilingual LabelForDisplay type |
| `cdi:physicalDataType` | array | `physicalDataType` (InstanceVariable) | Required; DDI-CDI uses ControlledVocabularyEntry |

### Building block alignment

The `cdifVariableMeasured/schema.yaml` building block and `CDIFCompleteSchema.json` are aligned as of 2026-03. The building block requires `@type` and `cdi:physicalDataType` and includes all CDI properties (`cdi:intendedDataType`, `cdi:role`, `cdi:describedUnitOfMeasure`, `cdi:identifier`, `cdi:name`, `cdi:displayLabel`).

---

## 2. Physical Mapping (ValueMapping) Properties

**CDIF location:** `physicalMapping_type` in CDIFCompleteSchema.json; `cdifPhysicalMapping/schema.yaml` building block
**DDI-CDI class:** `cls-ValueMapping`

| CDIF Property | Type | DDI-CDI Property | Notes |
|---|---|---|---|
| `cdi:index` | integer | -- | CDIF-specific ordering; DDI-CDI uses ValueMappingPosition |
| `cdi:format` | string | `format` | DDI-CDI uses ControlledVocabularyEntry |
| `cdi:physicalDataType` | string | `physicalDataType` | DDI-CDI uses ControlledVocabularyEntry |
| `cdi:length` | integer | `length` | Direct mapping |
| `cdi:nullSequence` | string | `nullSequence` | Direct mapping |
| `cdi:defaultValue` | string | `defaultValue` | DDI-CDI requires (1..1); CDIF optional |
| `cdi:scale` | integer | `scale` | Direct mapping |
| `cdi:decimalPositions` | integer | `decimalPositions` | Direct mapping |
| `cdi:minimumLength` | integer | `minimumLength` | Direct mapping |
| `cdi:maximumLength` | integer | `maximumLength` | Direct mapping |
| `cdi:isRequired` | boolean | `isRequired` | Direct mapping |
| `cdi:formats_InstanceVariable` | object (@id) | inverse of InstanceVariable relationship | Forward link; DDI-CDI uses inverse on InstanceVariable |

### Additional properties in tabular physical mapping only

These appear in CDIFCompleteSchema.json `tabularTextDatasetMapping_type` > `cdi:hasPhysicalMapping` items but not in the base `physicalMapping_type`:

| CDIF Property | DDI-CDI Property | DDI-CDI Class | Notes |
|---|---|---|---|
| `cdi:defaultDecimalSeparator` | `defaultDecimalSeparator` | ValueMapping | Direct mapping |
| `cdi:defaultDigitalGroupSeparator` | `defaultDigitGroupSeparator` | ValueMapping | Note: DDI-CDI spells it "Digit" not "Digital" |
| `cdi:displayLabel` | `displayLabel` | Concept (via InstanceVariable) | Cross-class; DDI-CDI has this on InstanceVariable/Concept, not ValueMapping |
| `cdi:length` | `length` | ValueMapping | Direct mapping (also in base physicalMapping_type) |

### DDI-CDI ValueMapping properties NOT in CDIF

| DDI-CDI Property | Type | Notes |
|---|---|---|
| `numberPattern` | xsd:string | Not implemented in CDIF |
| `identifier` | dt-Identifier | Not implemented in CDIF |
| Relationship: `uses_PhysicalSegmentLocation` | target-PhysicalSegmentLocation | CDIF uses `cdi:index` instead of the full segment location model |

---

## 3. Tabular Text Dataset Mapping (PhysicalSegmentLayout)

**CDIF location:** `tabularTextDatasetMapping_type` in CDIFCompleteSchema.json; `cdifTabularData/schema.yaml` building block
**DDI-CDI class:** `cls-PhysicalSegmentLayout`

CDIF types this as `cdi:TabularTextDataSet` rather than `cdi:PhysicalSegmentLayout` -- this is a CDIF design choice that merges the DDI-CDI DataSet and PhysicalSegmentLayout concepts.

All DDI-CDI properties below are from `PhysicalSegmentLayout` unless noted.

| CDIF Property | Type | DDI-CDI Property | Notes |
|---|---|---|---|
| `@type` (contains `cdi:TabularTextDataSet`) | array | -- | CDIF-specific composite type |
| `cdi:arrayBase` | integer | `arrayBase` | Direct mapping |
| `csvw:commentPrefix` | string | `commentPrefix` | CSVW alias |
| `csvw:delimiter` | string | `delimiter` | CSVW alias |
| `cdi:escapeCharacter` | string | `escapeCharacter` | Direct mapping |
| `csvw:header` | boolean | `hasHeader` | CSVW name differs |
| `cdi:headerIsCaseSensitive` | boolean | `headerIsCaseSensitive` | Direct mapping |
| `csvw:headerRowCount` | integer | `headerRowCount` | CSVW alias |
| `cdi:isDelimited` | boolean | `isDelimited` | DDI-CDI requires (1..1) |
| `cdi:isFixedWidth` | boolean | `isFixedWidth` | DDI-CDI requires (1..1) |
| `csvw:lineTerminators` | string enum | `lineTerminator` | CSVW alias; DDI-CDI allows 0..* |
| `csvw:quoteChar` | string | `quoteCharacter` | CSVW name differs |
| `csvw:skipBlankRows` | boolean | `skipBlankRows` | CSVW alias |
| `csvw:skipColumns` | integer | `skipDataColumns` | CSVW name differs |
| `csvw:skipInitialSpace` | boolean | `skipInitialSpace` | CSVW alias |
| `csvw:skipRows` | integer | `skipRows` | CSVW alias |
| `csvw:tableDirection` | enum | `tableDirection` | DDI-CDI: TableDirectionValues |
| `csvw:textDirection` | enum | `textDirection` | DDI-CDI: TextDirectionValues |
| `cdi:treatConsecutiveDelimitersAsOne` | boolean | `treatConsecutiveDelimitersAsOne` | Direct mapping |
| `csvw:trim` | enum | `trim` | DDI-CDI: TrimValues |
| `cdi:hasPhysicalMapping` | array | -- | CDIF design; inline ValueMapping items |
| `countRows` | integer | `recordCount` (DataStore) | Cross-class mapping |
| `countColumns` | integer | -- | No DDI-CDI equivalent |

### Building block alignment

The `cdifTabularData/schema.yaml` building block and `CDIFCompleteSchema.json` are aligned as of 2026-03. All PhysicalSegmentLayout properties are present in both, including `cdi:escapeCharacter`, `cdi:headerIsCaseSensitive`, `cdi:treatConsecutiveDelimitersAsOne`, `csvw:tableDirection`, `csvw:textDirection`, and `csvw:trim`. The building block also enforces a `oneOf` constraint requiring exactly one of `cdi:isDelimited` or `cdi:isFixedWidth` to be true.

### DDI-CDI PhysicalSegmentLayout properties NOT in CDIF

| DDI-CDI Property | Type | Notes |
|---|---|---|
| `allowsDuplicates` | boolean (required) | Not implemented |
| `encoding` | ControlledVocabularyEntry | CDIF uses `cdi:characterSet` on distribution instead |
| `nullSequence` | string | On PhysicalSegmentLayout; CDIF has it on ValueMapping (physicalMapping_type) instead |
| `name` | ObjectName | Not implemented at dataset level |
| `identifier` | Identifier | Not implemented at dataset level |
| `overview`, `purpose` | InternationalString | Not implemented |

---

## 4. Structured Dataset Mapping (Data Cube)

**CDIF location:** `structuredDatasetMapping_type` in CDIFCompleteSchema.json; `cdifDataCube/schema.yaml` building block
**DDI-CDI classes:** No single class -- combines `PhysicalDataSet` and `DataSet` concepts

| CDIF Property | Type in CDIF | DDI-CDI Property | DDI-CDI Class | Notes |
|---|---|---|---|---|
| `@type` (contains `cdi:StructuredDataSet`) | array | -- | -- | CDIF-specific type combining dataset concepts |
| `cdi:hasPhysicalMapping` | array | -- | -- | CDIF design; same as tabular but with `cdi:locator` |
| `cdi:locator` | string (on mapping items) | -- | -- | CDIF-specific; for locating values in multi-dimensional structures (e.g., NetCDF variable paths) |

---

## 5. Long Data Structure Mapping

**CDIF location:** `cdifLongData/schema.yaml` building block
**DDI-CDI classes:** No single class -- a CDIF design combining dataset and layout concepts

CDIF types long-format data as `cdi:LongStructureDataSet`. Long (narrow) format has each row representing a single observation, with descriptor columns identifying the variable and reference columns holding the value. The long-data building block shares most PhysicalSegmentLayout properties with the tabular data building block.

| CDIF Property | Type in CDIF | DDI-CDI Property | DDI-CDI Class | Notes |
|---|---|---|---|---|
| `@type` (contains `cdi:LongStructureDataSet`) | array | -- | -- | CDIF-specific composite type |
| `cdi:hasPhysicalMapping` | array | -- | -- | Same as tabular mapping |
| `cdi:arrayBase` | integer | `arrayBase` | PhysicalSegmentLayout | Direct mapping |
| `csvw:delimiter`, `csvw:header`, etc. | various | (same as tabular) | PhysicalSegmentLayout | Shared subset of tabular properties |
| `cdi:escapeCharacter` | string | `escapeCharacter` | PhysicalSegmentLayout | Direct mapping |

Long data uses `cdi:role` values `DescriptorComponent` and `ReferenceValueComponent` on InstanceVariable to distinguish descriptor columns (which variable is being observed) from reference columns (the observation value).

---

## 6. Distribution-Level Properties (DataStore / PhysicalDataSet)

**CDIF location:** `distributionBase_type` in CDIFCompleteSchema.json
**DDI-CDI classes:** `cls-DataStore`, `cls-PhysicalDataSet`

| CDIF Property | Type in CDIF | DDI-CDI Property | DDI-CDI Class | Notes |
|---|---|---|---|---|
| `schema:contentUrl` | string | `overview` | PhysicalDataSet | Approximate; DDI-CDI `overview` is descriptive text, not a URL. `physicalFileName` is closer for file name |
| `cdi:characterSet` | string | `characterSet` | DataStore | Direct mapping |
| `cdi:fileSize` | number | -- | -- | No direct DDI-CDI equivalent; closest is schema.org contentSize |
| `cdi:fileSizeUofM` | string | -- | -- | No direct DDI-CDI equivalent |
| `spdx:checksum` | object (algorithm + value) | -- | -- | No DDI-CDI equivalent; SPDX vocabulary. Requires `@type: spdx:Checksum` |
| `schema:encodingFormat` | array of strings | `encoding` | PhysicalSegmentLayout | Approximate; DDI-CDI uses ControlledVocabularyEntry |

---

## 7. Role Mapping (DataStructureComponent Subclasses)

**CDIF property:** `cdi:role` on variableMeasured items
**DDI-CDI:** Separate subclasses of `DataStructureComponent`

DDI-CDI models the role of a variable in a data structure as distinct classes. CDIF collapses these into a string enum:

| CDIF `cdi:role` Value | DDI-CDI Class | DDI-CDI Description |
|---|---|---|
| `MeasureComponent` | `cls-MeasureComponent` | The observed/measured quantity |
| `DimensionComponent` | `cls-DimensionComponent` | An independent axis (has `categoricalAdditivity` property) |
| `AttributeComponent` | `cls-AttributeComponent` | A qualifier/attribute (has `qualifies` relationship) |
| `DescriptorComponent` | `cls-DescriptorComponent` | Identifies which variable is observed in long data format |
| `ReferenceValueComponent` | `cls-ReferenceValueComponent` | Holds the observation value in long data format |

---

## 8. Provenance Mapping (Activity / Step / ProcessingAgent)

**CDIF location:** `cdifProv/schema.yaml` building block (value of `prov:wasGeneratedBy`)
**DDI-CDI classes:** `cls-Activity`, `cls-Step`, `cls-ProcessingAgent`, `cls-Parameter`, `cls-ProductionEnvironment`
**DDI-CDI native building block:** `ddicdiProv/schema.yaml` (see `docs/CDIF-Provenance-Building-Blocks-Comparison.md` for detailed comparison)

CDIF uses dual-typed `["schema:Action", "prov:Activity"]` nodes that implement the same provenance concepts as DDI-CDI but with schema.org and PROV-O vocabulary. The `ddicdiProv` building block provides the DDI-CDI native alternative for communities using that standard directly.

### Activity mapping

| CDIF Property (cdifProv) | Type in CDIF | DDI-CDI Property | DDI-CDI Class | Notes |
|---|---|---|---|---|
| `@type` (`["schema:Action", "prov:Activity"]`) | array | `@type` (`cdi:Activity`) | Activity | CDIF dual-typed; DDI-CDI single-typed |
| `schema:name` | string | `cdi:name` | Activity (Concept) | DDI-CDI uses ObjectName wrapper type |
| `schema:description` | string | `cdi:description` | Activity | Direct semantic match |
| `schema:identifier` | string/PropertyValue | `cdi:identifier` | Activity (Concept) | DDI-CDI uses composite Identifier type |
| `prov:used` | array (strings, objects, CreativeWork) | `cdi:entityUsed` | Activity | CDIF accepts mixed types; DDI-CDI uses Reference objects |
| `schema:result` | string/object | `cdi:entityProduced` | Activity | CDIF uses schema.org Action property; DDI-CDI uses Reference objects |
| `schema:agent` | Person/Organization/AgentInRole | -- | -- | DDI-CDI inverts: `cdi:ProcessingAgent --cdi:performs--> cdi:Activity` |
| `schema:startTime` | ISO 8601 string | -- | -- | DDI-CDI Activity has no temporal bounds (gap in spec) |
| `schema:endTime` | ISO 8601 string | -- | -- | DDI-CDI Activity has no temporal bounds (gap in spec) |
| `schema:location` | Place/string | -- | -- | DDI-CDI has `cdi:ProductionEnvironment` as separate class |
| `schema:actionStatus` | enum (4 values) | -- | -- | No DDI-CDI equivalent |
| `schema:object` | string/object | -- | -- | Action chaining input; DDI-CDI uses `cdi:hasSubActivity` |
| `schema:error` | string | -- | -- | No DDI-CDI equivalent |

### Methodology / Step mapping

| CDIF Property (cdifProv) | Type in CDIF | DDI-CDI Property | DDI-CDI Class | Notes |
|---|---|---|---|---|
| `schema:actionProcess` | HowTo object | `cdi:has_Step` | Activity → Step | CDIF uses schema.org HowTo; DDI-CDI uses Step objects |
| `schema:actionProcess.schema:name` | string | `cdi:name` (on Step) | Step (Concept) | Methodology name |
| `schema:actionProcess.schema:step` | array of HowToStep | `cdi:has_Step` | Step (nested) | CDIF uses ordered HowToStep; DDI-CDI uses Step with `cdi:hasSubStep` |
| `schema:HowToStep.schema:name` | string | `cdi:name` (on Step) | Step | Step name |
| `schema:HowToStep.schema:position` | integer | -- | -- | CDIF uses schema.org ordering; DDI-CDI relies on array order |
| `schema:HowToStep.schema:description` | string | `cdi:description` | Step | Step description |
| `schema:HowToStep.schema:url` | uri | -- | -- | No DDI-CDI equivalent on Step |
| -- | -- | `cdi:script` | Step | DDI-CDI has executable code (CommandCode); CDIF has no equivalent |
| -- | -- | `cdi:receives` / `cdi:produces` | Step → Parameter | DDI-CDI has explicit data flow; CDIF does not model parameters |

### Agent mapping

| CDIF Property (cdifProv) | Type in CDIF | DDI-CDI Property | DDI-CDI Class | Notes |
|---|---|---|---|---|
| `schema:agent` | Person/Organization | -- | ProcessingAgent | DDI-CDI inverts the relationship: `ProcessingAgent --cdi:performs--> Activity` |
| `schema:agent.schema:name` | string | `cdi:name` (implied) | ProcessingAgent | DDI-CDI ProcessingAgent has no name; linked via identifier |
| `schema:agent.schema:identifier` | string/PropertyValue | `cdi:identifier` | ProcessingAgent | Direct mapping for agent identification |
| `schema:participant` | array of Person/Organization | -- | -- | No DDI-CDI equivalent; DDI-CDI has single ProcessingAgent |

### Location / Environment mapping

| CDIF Property (cdifProv) | Type in CDIF | DDI-CDI Property | DDI-CDI Class | Notes |
|---|---|---|---|---|
| `schema:location` | Place/string | -- | ProductionEnvironment | DDI-CDI uses separate ProductionEnvironment class with `cdi:name`, `cdi:description` |
| -- | -- | `cdi:operatesOn` | ProcessingAgent → ProductionEnvironment | DDI-CDI links agent to environment; CDIF puts location on activity |

### DDI-CDI provenance concepts NOT in cdifProv

| DDI-CDI Concept | Type | Notes |
|---|---|---|
| `cdi:Parameter` | cls-Parameter | Data flow parameters between steps; CDIF does not model |
| `cdi:script` / `cdi:CommandCode` | dt-CommandCode | Executable code on steps; CDIF uses `schema:url` on HowToStep for documentation links |
| `cdi:standardModelMapping` | Reference | Link to standard process model (e.g., GSBPM); CDIF has no equivalent |
| `cdi:hasSubActivity` | Activity → Activity | DDI-CDI nested activities; CDIF uses `schema:object`/`schema:result` for action chaining |
| Temporal bounds on Activity | -- | DDI-CDI Activity has no `startedAtTime`/`endedAtTime`; this is a DDI-CDI gap |

---

## 9. CSVW to DDI-CDI Property Name Crosswalk

CDIF uses CSVW vocabulary names for properties that have DDI-CDI equivalents. This table shows the naming differences:

| CSVW Name (used in CDIF) | DDI-CDI Name | Semantic Match |
|---|---|---|
| `csvw:commentPrefix` | `commentPrefix` | Exact |
| `csvw:delimiter` | `delimiter` | Exact |
| `csvw:header` | `hasHeader` | Equivalent (different name) |
| `csvw:headerRowCount` | `headerRowCount` | Exact |
| `csvw:lineTerminators` | `lineTerminator` | Equivalent (CSVW plural, DDI-CDI singular) |
| `csvw:quoteChar` | `quoteCharacter` | Equivalent (abbreviated vs full) |
| `csvw:skipBlankRows` | `skipBlankRows` | Exact |
| `csvw:skipColumns` | `skipDataColumns` | Equivalent (different name) |
| `csvw:skipInitialSpace` | `skipInitialSpace` | Exact |
| `csvw:skipRows` | `skipRows` | Exact |
| `csvw:tableDirection` | `tableDirection` | Exact |
| `csvw:textDirection` | `textDirection` | Exact |
| `csvw:trim` | `trim` | Exact |

---

## 10. Coverage Summary

### DDI-CDI classes fully or substantially covered by CDIF

| DDI-CDI Class | Properties Covered | Properties Not Covered | Coverage |
|---|---|---|---|
| `InstanceVariable` | physicalDataType, hasIntendedDataType, simpleUnitOfMeasure, describedUnitOfMeasure, displayLabel, identifier, name, descriptiveText | platformType, source, variableFunction, unitOfMeasureKind, externalDefinition, catalogDetails | ~57% |
| `ValueMapping` | decimalPositions, defaultDecimalSeparator, defaultDigitGroupSeparator, defaultValue, format, isRequired, length, maximumLength, minimumLength, nullSequence, physicalDataType, scale | identifier, numberPattern | ~86% |
| `PhysicalSegmentLayout` | arrayBase, commentPrefix, delimiter, escapeCharacter, hasHeader, headerIsCaseSensitive, headerRowCount, isDelimited, isFixedWidth, lineTerminator, quoteCharacter, skipBlankRows, skipDataColumns, skipInitialSpace, skipRows, tableDirection, textDirection, treatConsecutiveDelimitersAsOne, trim | allowsDuplicates, encoding, name, identifier, nullSequence, overview, purpose | ~73% |
| `DataStore` | characterSet | aboutMissing, allowsDuplicates, catalogDetails, dataStoreType, identifier, name, purpose, recordCount | ~12% |
| `DataStructureComponent` subclasses | MeasureComponent, DimensionComponent, AttributeComponent, DescriptorComponent, ReferenceValueComponent (via `cdi:role` enum) | identifier, semantic, specialization, categoricalAdditivity, qualifies | type coverage only |
| `Activity` | name, description, identifier, entityUsed, entityProduced (via schema.org/PROV-O) | standardModelMapping, hasSubActivity (native form) | ~50% (conceptual) |
| `Step` | name, description (via HowTo/HowToStep) | script, receives, produces, hasSubStep | ~33% (conceptual) |
| `ProcessingAgent` | identifier (via schema:agent) | purpose, performs, operatesOn | ~25% (conceptual) |

### CDIF properties with no DDI-CDI equivalent

| CDIF Property | Location | Notes |
|---|---|---|
| `cdi:fileSize` | distributionBase_type | Size in numeric form |
| `cdi:fileSizeUofM` | distributionBase_type | Unit of file size |
| `cdi:locator` | structuredDatasetMapping_type | Data cube variable path |
| `cdi:index` | physicalMapping_type | Column ordering (DDI-CDI uses ValueMappingPosition object) |
| `cdi:uses` | variableMeasured_type | Concept reference |
| `cdi:role` | variableMeasured_type | Flattened from class hierarchy |
| `countRows` | tabularTextDatasetMapping_type | DDI-CDI has `recordCount` on DataStore |
| `countColumns` | tabularTextDatasetMapping_type | No equivalent |
| `schema:actionStatus` | cdifProv activity | No DDI-CDI equivalent |
| `schema:error` | cdifProv activity | No DDI-CDI equivalent |
| `schema:participant` | cdifProv activity | DDI-CDI has single ProcessingAgent, not multiple participants |

### DDI-CDI classes NOT represented in CDIF

The following major DDI-CDI classes have no CDIF representation:
- `LogicalRecord`, `DataPoint`, `Key`, `PrimaryKey`, `ForeignKey`
- `Population`, `Universe`, `UnitType`
- `SentinelValueDomain`, `SubstantiveValueDomain`
- `CodeList`, `Category`, `StatisticalClassification`

Note: DDI-CDI provenance classes (`Activity`, `Step`, `ProcessingAgent`, `Parameter`, `ProductionEnvironment`) are conceptually covered by the `cdifProv` building block using schema.org and PROV-O vocabulary. The `ddicdiProv` building block provides the DDI-CDI native alternative. See `docs/CDIF-Provenance-Building-Blocks-Comparison.md` for the detailed three-way comparison (cdifProv, provActivity, ddicdiProv).
