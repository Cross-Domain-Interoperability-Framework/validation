# CDIF to DDI-CDI Formal Property Mapping

**Date:** 2026-02-20
**Source schemas:**
- CDIF: `CDIFCompleteSchema.json` and building blocks in `BuildingBlockSubmodule/_sources/cdifProperties/`
- DDI-CDI: `ddi-cdi.schema_normative.json` (v1.0)
- DDI-CDI specification: https://docs.ddialliance.org/DDI-CDI/1.0/model/FieldLevelDocumentation/DDICDILibrary/index.html

## Overview

CDIF implements a flattened subset of the DDI-CDI model for data description. The DDI-CDI model defines 158 classes in a multi-level UML hierarchy; CDIF uses ~37 `cdi:`-prefixed properties and ~12 `csvw:`-prefixed properties drawn from approximately 5 core DDI-CDI classes:

| DDI-CDI Class | CDIF Usage Context |
|---|---|
| `InstanceVariable` | `schema:variableMeasured` items |
| `PhysicalSegmentLayout` | `tabularTextDatasetMapping_type` (dataset-level) |
| `ValueMapping` | `physicalMapping_type` / `cdi:hasPhysicalMapping` items |
| `DataStore` | `distributionBase_type` (distribution-level) |
| `DataStructureComponent` subclasses | `cdi:role` enum values on variableMeasured |

CDIF flattens the DDI-CDI multi-class hierarchy into JSON-LD objects at three levels: distribution, dataset mapping (tabular or structured), and per-variable physical mapping. Where DDI-CDI uses separate objects linked by relationships, CDIF inlines properties directly.

---

## 1. InstanceVariable Mapping

**CDIF location:** `variableMeasured_type` in CDIFCompleteSchema.json; `cdifVariableMeasured/schema.yaml` building block
**DDI-CDI class:** `cls-InstanceVariable` (inherits from RepresentedVariable > ConceptualVariable > Concept)

| CDIF Property | Type in CDIF | DDI-CDI Property | DDI-CDI Class Origin | DDI-CDI Type | Notes |
|---|---|---|---|---|---|
| `@type` (contains `cdi:InstanceVariable`) | array | `@type` | InstanceVariable | const | CDIF requires both `schema:PropertyValue` and `cdi:InstanceVariable` |
| `@id` | string | `@id` | (JSON-LD) | iri-reference | Used for cross-references from `cdi:formats_InstanceVariable` |
| `schema:name` | string (minLength 5) | `name` | Concept | dt-ObjectName | CDIF uses schema.org property; DDI-CDI uses complex ObjectName type |
| `schema:description` | string (minLength 10) | `descriptiveText` | ConceptualVariable | dt-InternationalString | CDIF uses schema.org; DDI-CDI uses internationalized string |
| `schema:propertyID` | array of string/object/DefinedTerm | —[cdi:Concept.identifier] | —(Concept) | — | DDI-CDI UML indicates inheritance from Concept class |
| `schema:measurementTechnique` | string/object/DefinedTerm | — | — | — | No direct DDI-CDI equivalent; schema.org property |
| `schema:unitText` | string | `simpleUnitOfMeasure` | RepresentedVariable | xsd:string | Parallel property; CDIF also has `cdi:simpleUnitOfMeasure` |
| `schema:unitCode` | string/object/DefinedTerm | `describedUnitOfMeasure` | RepresentedVariable | ControlledVocabularyEntry | Parallel property; CDIF also has `cdi:describedUnitOfMeasure` |
| `schema:minValue` | number | —[cdi:SubstantiveValueDomain] | —cdi:ValueAndConceptDescription | — | Link through valueDomain/valueAndConceptDescription |
| `schema:maxValue` | number | —[cdi:SubstantiveValueDomain] | — | — | Link through valueDomain/valueAndConceptDescription |
| `schema:url` | uri string | `externalDefinition` | Concept | dt-Reference | Approximate match |
| `cdi:intendedDataType` | string | `hasIntendedDataType` | RepresentedVariable | ControlledVocabularyEntry | CDIF simplifies to plain string; DDI-CDI uses ControlledVocabularyEntry |
| `cdi:role` | string enum {MeasureComponent, AttributeComponent, DimensionComponent} | — | DataStructureComponent subclasses | — | DDI-CDI models this as separate subclasses of DataStructureComponent; CDIF flattens to a string enum |
| `cdi:describedUnitOfMeasure` | DefinedTerm | `describedUnitOfMeasure` | RepresentedVariable | ControlledVocabularyEntry | Direct mapping |
| `cdi:simpleUnitOfMeasure` | string | `simpleUnitOfMeasure` | RepresentedVariable | xsd:string | Direct mapping |
| `cdi:uses` | array of string/object/DefinedTerm | — | — | — | CDIF description says "same as schema:propertyID"; no direct DDI-CDI match |

### Building block divergence (cdifVariableMeasured/schema.yaml)

The building block has additional properties not in CDIFCompleteSchema.json:

| Building Block Property | DDI-CDI Property | DDI-CDI Class Origin | Status |
|---|---|---|---|
| `cdi:identifier` | `identifier` | Concept | In building block only; should be added to CDIFCompleteSchema.json or removed |
| `cdi:name` | `name` | Concept | In building block only; redundant with `schema:name` |
| `cdi:displayLabel` | `displayLabel` | Concept | In building block only; should be added to CDIFCompleteSchema.json or removed |
| `cdi:physicalDataType` (as array) | `physicalDataType` | InstanceVariable | In building block only; physically maps to InstanceVariable.physicalDataType |

Properties in CDIFCompleteSchema.json missing from building block:

| Complete Schema Property | DDI-CDI Property | Status |
|---|---|---|
| `cdi:intendedDataType` | `hasIntendedDataType` (RepresentedVariable) | Missing from building block; should be added |
| `cdi:role` | DataStructureComponent subclass type | Missing from building block; should be added |
| `cdi:describedUnitOfMeasure` | `describedUnitOfMeasure` (RepresentedVariable) | Missing from building block; should be added |

---

## 2. Physical Mapping (ValueMapping) Properties

**CDIF location:** `physicalMapping_type` in CDIFCompleteSchema.json; `cdifPhysicalMapping/schema.yaml` building block
**DDI-CDI class:** `cls-ValueMapping`

| CDIF Property | Type in CDIF | DDI-CDI Property | DDI-CDI Type | Notes |
|---|---|---|---|---|
| `cdi:index` | integer (min 0) | — | — | CDIF-specific; orders fields. DDI-CDI uses `ValueMappingPosition` for ordering |
| `cdi:format` | string | `format` | ControlledVocabularyEntry | CDIF simplifies to string |
| `cdi:physicalDataType` | string | `physicalDataType` | ControlledVocabularyEntry | CDIF simplifies to string |
| `cdi:length` | integer | `length` | xsd:integer | Direct mapping |
| `cdi:nullSequence` | string | `nullSequence` | xsd:string | Direct mapping |
| `cdi:defaultValue` | string | `defaultValue` | xsd:string | Direct mapping; DDI-CDI requires it (1..1), CDIF makes it optional |
| `cdi:scale` | integer | `scale` | xsd:integer | Direct mapping |
| `cdi:decimalPositions` | integer | `decimalPositions` | xsd:integer | Direct mapping |
| `cdi:minimumLength` | integer | `minimumLength` | xsd:integer | Direct mapping |
| `cdi:maximumLength` | integer | `maximumLength` | xsd:integer | Direct mapping |
| `cdi:isRequired` | boolean (default false) | `isRequired` | xsd:boolean | Direct mapping |
| `cdi:formats_InstanceVariable` | object with @id | `has_ValueMapping_OF_InstanceVariable` | relationship | CDIF uses forward link from mapping to variable; DDI-CDI models as inverse relationship on InstanceVariable |

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

CDIF types this as `cdi:TabularTextDataSet` rather than `cdi:PhysicalSegmentLayout` — this is a CDIF design choice that merges the DDI-CDI DataSet and PhysicalSegmentLayout concepts.

| CDIF Property | Type in CDIF | DDI-CDI Property | DDI-CDI Class | Notes |
|---|---|---|---|---|
| `@type` (contains `cdi:TabularTextDataSet`) | array | — | — | CDIF-specific composite type |
| `cdi:arrayBase` | integer | `arrayBase` | PhysicalSegmentLayout | Direct mapping |
| `csvw:commentPrefix` | string | `commentPrefix` | PhysicalSegmentLayout | CSVW alias for DDI-CDI property |
| `csvw:delimiter` | string | `delimiter` | PhysicalSegmentLayout | CSVW alias for DDI-CDI property |
| `cdi:escapeCharacter` | string | `escapeCharacter` | PhysicalSegmentLayout | Direct mapping (Complete schema only) |
| `csvw:header` | boolean | `hasHeader` | PhysicalSegmentLayout | CSVW name differs from DDI-CDI |
| `cdi:headerIsCaseSensitive` | boolean | `headerIsCaseSensitive` | PhysicalSegmentLayout | Direct mapping (Complete schema only) |
| `csvw:headerRowCount` | integer (min 0) | `headerRowCount` | PhysicalSegmentLayout | CSVW alias for DDI-CDI property |
| `cdi:isDelimited` | boolean | `isDelimited` | PhysicalSegmentLayout | Direct mapping; DDI-CDI makes required (1..1) |
| `cdi:isFixedWidth` | boolean | `isFixedWidth` | PhysicalSegmentLayout | Direct mapping; DDI-CDI makes required (1..1) |
| `csvw:lineTerminators` | string enum {CRLF, LF, \r\n, \n} | `lineTerminator` | PhysicalSegmentLayout | CSVW alias; DDI-CDI allows 0..* strings |
| `csvw:quoteChar` | string (default `"`) | `quoteCharacter` | PhysicalSegmentLayout | CSVW name differs from DDI-CDI |
| `csvw:skipBlankRows` | boolean (default false) | `skipBlankRows` | PhysicalSegmentLayout | CSVW alias for DDI-CDI property |
| `csvw:skipColumns` | integer (default 0) | `skipDataColumns` | PhysicalSegmentLayout | CSVW name differs from DDI-CDI |
| `csvw:skipInitialSpace` | boolean (default true) | `skipInitialSpace` | PhysicalSegmentLayout | CSVW alias for DDI-CDI property |
| `csvw:skipRows` | integer (default 0) | `skipRows` | PhysicalSegmentLayout | CSVW alias for DDI-CDI property |
| `csvw:tableDirection` | enum {Ltr, Rtl} | `tableDirection` | PhysicalSegmentLayout | DDI-CDI type: enum-TableDirectionValues |
| `csvw:textDirection` | enum {Auto, Inherit, Ltr, Rtl} | `textDirection` | PhysicalSegmentLayout | DDI-CDI type: enum-TextDirectionValues |
| `cdi:treatConsecutiveDelimitersAsOne` | boolean (default false) | `treatConsecutiveDelimitersAsOne` | PhysicalSegmentLayout | Direct mapping (Complete schema only) |
| `csvw:trim` | enum {true, end, false, start} | `trim` | PhysicalSegmentLayout | DDI-CDI type: enum-TrimValues |
| `cdi:hasPhysicalMapping` | array of physicalMapping_type | — | — | CDIF design; links to ValueMapping items inline |
| `countRows` | integer | `recordCount` | DataStore | Cross-class mapping |
| `countColumns` | integer | — | — | No direct DDI-CDI equivalent |

### Building block divergence (cdifTabularData/schema.yaml)

Properties in CDIFCompleteSchema.json missing from building block:

| Complete Schema Property | DDI-CDI Property | Status |
|---|---|---|
| `cdi:escapeCharacter` | `escapeCharacter` | Missing from building block; should be added |
| `cdi:headerIsCaseSensitive` | `headerIsCaseSensitive` | Missing from building block; should be added |
| `cdi:treatConsecutiveDelimitersAsOne` | `treatConsecutiveDelimitersAsOne` | Missing from building block; should be added |
| `csvw:tableDirection` | `tableDirection` | Missing from building block; should be added |
| `csvw:textDirection` | `textDirection` | Missing from building block; should be added |
| `csvw:trim` | `trim` | Missing from building block; should be added |

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
**DDI-CDI classes:** No single class — combines `PhysicalDataSet` and `DataSet` concepts

| CDIF Property | Type in CDIF | DDI-CDI Property | DDI-CDI Class | Notes |
|---|---|---|---|---|
| `@type` (contains `cdi:StructuredDataSet`) | array | — | — | CDIF-specific type combining dataset concepts |
| `cdi:hasPhysicalMapping` | array | — | — | CDIF design; same as tabular but with `cdi:locator` |
| `cdi:locator` | string (on mapping items) | — | — | CDIF-specific; for locating values in multi-dimensional structures (e.g., NetCDF variable paths) |

---

## 5. Distribution-Level Properties (DataStore / PhysicalDataSet)

**CDIF location:** `distributionBase_type` in CDIFCompleteSchema.json
**DDI-CDI classes:** `cls-DataStore`, `cls-PhysicalDataSet`

| CDIF Property | Type in CDIF | DDI-CDI Property | DDI-CDI Class | Notes |
|---|---|---|---|---|
| `schema:contentUrl` | string | `overview` | PhysicalDataSet | Approximate; DDI-CDI `overview` is descriptive text, not a URL. `physicalFileName` is closer for file name |
| `cdi:characterSet` | string | `characterSet` | DataStore | Direct mapping |
| `cdi:fileSize` | number | — | — | No direct DDI-CDI equivalent; closest is schema.org contentSize |
| `cdi:fileSizeUofM` | string | — | — | No direct DDI-CDI equivalent |
| `spdx:checksum` | object (algorithm + value) | — | — | No DDI-CDI equivalent; SPDX vocabulary |
| `schema:encodingFormat` | array of strings | `encoding` | PhysicalSegmentLayout | Approximate; DDI-CDI uses ControlledVocabularyEntry |

---

## 6. Role Mapping (DataStructureComponent Subclasses)

**CDIF property:** `cdi:role` on variableMeasured items
**DDI-CDI:** Separate subclasses of `DataStructureComponent`

DDI-CDI models the role of a variable in a data structure as distinct classes. CDIF collapses these into a string enum:

| CDIF `cdi:role` Value | DDI-CDI Class | DDI-CDI Description |
|---|---|---|
| `MeasureComponent` | `cls-MeasureComponent` | The observed/measured quantity |
| `DimensionComponent` | `cls-DimensionComponent` | An independent axis (has `categoricalAdditivity` property) |
| `AttributeComponent` | `cls-AttributeComponent` | A qualifier/attribute (has `qualifies` relationship) |

---

## 7. CSVW to DDI-CDI Property Name Crosswalk

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

## 8. Coverage Summary

### DDI-CDI classes fully or substantially covered by CDIF

| DDI-CDI Class | Properties Covered | Properties Not Covered | Coverage |
|---|---|---|---|
| `InstanceVariable` | physicalDataType, hasIntendedDataType, simpleUnitOfMeasure, describedUnitOfMeasure, displayLabel, identifier, name, descriptiveText | platformType, source, variableFunction, unitOfMeasureKind, externalDefinition, catalogDetails | ~57% |
| `ValueMapping` | decimalPositions, defaultDecimalSeparator, defaultDigitGroupSeparator, defaultValue, format, isRequired, length, maximumLength, minimumLength, nullSequence, physicalDataType, scale | identifier, numberPattern | ~86% |
| `PhysicalSegmentLayout` | arrayBase, commentPrefix, delimiter, escapeCharacter, hasHeader, headerIsCaseSensitive, headerRowCount, isDelimited, isFixedWidth, lineTerminator, quoteCharacter, skipBlankRows, skipDataColumns, skipInitialSpace, skipRows, tableDirection, textDirection, treatConsecutiveDelimitersAsOne, trim | allowsDuplicates, encoding, name, identifier, nullSequence, overview, purpose | ~73% |
| `DataStore` | characterSet | aboutMissing, allowsDuplicates, catalogDetails, dataStoreType, identifier, name, purpose, recordCount | ~12% |
| `DataStructureComponent` subclasses | MeasureComponent, DimensionComponent, AttributeComponent (via `cdi:role` enum) | identifier, semantic, specialization, categoricalAdditivity, qualifies | type coverage only |

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

### DDI-CDI classes NOT represented in CDIF

The following major DDI-CDI classes have no CDIF representation:
- `LogicalRecord`, `DataPoint`, `Key`, `PrimaryKey`, `ForeignKey`
- `Population`, `Universe`, `UnitType`
- `SentinelValueDomain`, `SubstantiveValueDomain`
- `CodeList`, `Category`, `StatisticalClassification`
- `ProcessingAgent`, `ProcessingStep`
- All provenance classes (CDIF uses PROV-O instead)
- All cataloging classes (CDIF uses schema.org and Dublin Core instead)
