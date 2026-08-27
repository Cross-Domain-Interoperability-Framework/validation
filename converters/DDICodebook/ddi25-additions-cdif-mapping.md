# DDI Codebook 2.5 additions → CDIF (mapping targets)

The 84 element names present in **DDI Codebook 2.5** but **not** in **DDI 1.2.2**
(a strict superset — see [README.md](README.md#schema-availability-a-caution)).
Neither `ddi122_to_cdif.py` nor `ddi25_to_cdif.py` maps these today; this table
records the **best-guess CDIF target** for each so a future codebook enhancement
can pick them up. Confidence is noted where a mapping is speculative.

CDIF profiles referenced: **Discovery** (schema.org), **DataDescription**
(`cdi:InstanceVariable`), **DataStructure** (`data_structure/1.1` — dimensional /
tabular / long, DDI-CDI `*DataStructure`), **Provenance** (`cdifProv`:
`schema:Action`+`prov:Activity`), **Codelist / ConceptScheme** (`skos`), plus
**DQV** (`dqv:*`) and **geosparql**/`schema:GeoShape` for geometry.

## 1. Aggregate / cube data → DataStructure (Dimensional / Cube)

The highest-value group. DDI `nCube` is aggregate (cross-tabulated) data — a
different data model from the `var`/`fileDscr` microdata both converters assume.
CDIF target: the **dimensional** DataStructure profile (DDI-CDI
`DimensionalDataStructure` / `DimensionalDataSet` with Dimension/Measure/Attribute
components), i.e. what CDIF calls *DataStructure — Dimensional Data*.

| DDI 2.5 | Meaning | CDIF target |
|---------|---------|-------------|
| `nCube` | N-dimensional data cube (aggregate data) | a `cdi:DimensionalDataStructure` / cube dataset (DataStructure profile) |
| `nCubeGrp` | group of related nCubes | `schema:hasPart` set of cube datasets |
| `dmns` | a dimension of the cube | `cdi:DimensionComponent` (`cdif:role` = `Dimension`) |
| `measure` | the measured value(s) of the cube | `cdi:MeasureComponent` (`cdif:role` = `Measure`) |
| `attribute` | attribute qualifying cube cells | `cdi:AttributeComponent` (`cdif:role` = `Attribute`) |
| `CubeCoord` | coordinate (dimension-value tuple) of a cell | `cdi:DataPoint` coordinate / dimension positions |
| `dataItem` | a data value / cell of the cube | `cdi:DataPoint` / cell datum |
| `catLevel` | hierarchical category level in a dimension | code-list hierarchy level (`skos:broader`/`narrower`) |
| `specificElements` | internal reference to specific variables/cells | *structural — no direct CDIF (internal ref)* |

## 2. Controlled vocabularies / code lists → Codelist & ConceptScheme profiles

CDIF target: `skos:ConceptScheme` + `skos:Concept` (profile-codelist /
profile-conceptscheme); DDI-CDI `CodeList`. Also the natural home for the
existing `<catgry>` deferral shared with the 1.2.2 converter.

| DDI 2.5 | Meaning | CDIF target |
|---------|---------|-------------|
| `codeListID` | code-list identifier | `@id` / `schema:identifier` of the ConceptScheme |
| `codeListName` | code-list name | `skos:prefLabel` / `schema:name` |
| `codeListAgencyName` | maintaining agency | `dcterms:publisher` / `schema:publisher` |
| `codeListURN` | canonical URN of the code list | `@id` (URN) |
| `codeListSchemeURN` | scheme URN | `skos:inScheme` `@id` |
| `codeListVersionID` | code-list version | `schema:version` / `owl:versionInfo` |
| `controlledVocabUsed` | reference to a controlled vocabulary used | `dcterms:conformsTo` / `skos:inScheme` / `cdif:uses` |
| `usage` | usage / scope note | `skos:scopeNote` / `schema:description` |
| `standard` | classification / standard referenced | `dcterms:conformsTo` / `skos:inScheme` |
| `standardName` | name of the standard | `schema:name` |
| `codingInstructions` | instructions used to code responses | `schema:description` on the variable (methodology) |

## 3. Quality, compliance & evaluation → DQV (+ Provenance)

CDIF target: `dqv:QualityMeasurement` / `dqv:QualityAnnotation`
(`dqv:hasQualityMeasurement`); `dcterms:conformsTo` for standards; `cdifProv` for
evaluation activities.

| DDI 2.5 | Meaning | CDIF target |
|---------|---------|-------------|
| `qualityStatement` | statement about data quality | `dqv:QualityAnnotation` / `dqv:QualityMeasurement` + `schema:description` |
| `otherQualityStatement` | additional quality note | `dqv:QualityAnnotation` |
| `standardsCompliance` | compliance with a standard | `dcterms:conformsTo` + `dqv` annotation |
| `complianceDescription` | description of compliance | `schema:description` |
| `evaluationProcess` | the evaluation process | `prov:Activity` / `schema:Action` (evaluation) |
| `exPostEvaluation` | post-hoc evaluation | `prov:Activity` / `dqv` |
| `evaluator` | evaluating agent | `schema:agent` / `prov:wasAssociatedWith` (Role: evaluator) |
| `outcomes` / `outcome` | evaluation outcome(s) | `schema:result` / `dqv` measurement value |

## 4. Study lifecycle, processing & provenance → cdifProv

CDIF target: `prov:wasGeneratedBy` → `["schema:Action","prov:Activity"]`;
`schema:actionProcess` → `schema:HowTo`/`HowToStep`; `schema:instrument`;
`schema:agent`.

| DDI 2.5 | Meaning | CDIF target |
|---------|---------|-------------|
| `dataProcessing` | data-processing step | `prov:Activity` (cdifProv Action) |
| `developmentActivity` | a development activity | `prov:Activity` |
| `studyDevelopment` | study-development phase | `prov:Activity` / `schema:Action` |
| `instrumentDevelopment` | instrument development | `prov:Activity` / `schema:actionProcess` |
| `updateProcedure` | procedure for updates | `schema:actionProcess` (HowTo) / `dcterms:accrualMethod` |
| `command` | processing command / script | `prov:used` (SoftwareApplication) / `cdi:Command` / a HowToStep |
| `algorithmSpecification` | algorithm used | `schema:description` / methodology / `prov` |
| `algorithmVersion` | algorithm version | `schema:version` |
| `collectorTraining` | training of data collectors | `schema:description` (methodology) / `prov` |
| `purpose` | purpose of the study / activity | `schema:description` / `schema:abstract` |
| `selector` | selection / sampling method | `schema:description` (sampling methodology) |
| `dataFingerprint` | checksum / fingerprint of the data | `spdx:Checksum` |
| `digitalFingerprintValue` | the fingerprint value | `spdx:checksumValue` |

## 5. Sampling → schema.org additionalProperty / methodology

| DDI 2.5 | Meaning | CDIF target |
|---------|---------|-------------|
| `sampleFrame` | the sampling frame | `schema:description` / `schema:additionalProperty` |
| `sampleFrameName` | name of the sampling frame | `schema:name` |
| `sampleSize` | achieved sample size | `schema:additionalProperty` (PropertyValue, numeric) |
| `sampleSizeFormula` | sample-size formula | `schema:description` / `additionalProperty` |
| `targetSampleSize` | target sample size | `schema:additionalProperty` (PropertyValue) |
| `cohort` | population subgroup / cohort | `schema:about` (DefinedTerm) / `additionalProperty` |
| `frameUnit` | unit of the sampling frame | `additionalProperty` / `cdi` unit type |
| `unitType` | type of unit of analysis | `schema:additionalProperty` / analysis-unit note |
| `participant` | study participant | `schema:participant` (in an Action) / `prov` agent |

## 6. Geographic bounding & detail → schema:spatialCoverage / geosparql

The converters already emit a bounding `schema:box` for `nation`/`geogCover`;
these give finer geometry.

| DDI 2.5 | Meaning | CDIF target |
|---------|---------|-------------|
| `geoBndBox` | geographic bounding box | `schema:GeoShape` `schema:box` (`minLat minLon maxLat maxLon`) |
| `westBL`/`eastBL`/`southBL`/`northBL` | bounding-box limits | coordinate components of `schema:box` |
| `boundPoly` | bounding polygon | `schema:GeoShape` `schema:polygon` / `geosparql:asWKT` |
| `gringLat` / `gringLon` | g-ring (polygon) vertex lat/lon | polygon vertices of a `GeoShape` |
| `point` | a geographic point | `schema:GeoCoordinates` (latitude/longitude) |
| `polygon` | a geographic polygon | `schema:GeoShape` `schema:polygon` / `geosparql` |
| `geoMap` | a map figure / reference | `schema:image` / `schema:associatedMedia` |
| `locMap` | location map | `schema:image` / `schema:associatedMedia` |
| `physLoc` | physical location of the data | `schema:contentLocation` / distribution note |
| `referencePeriod` | reference time period | `schema:temporalCoverage` / `time:ProperInterval` |
| `validPeriod` | validity period | `schema:validFrom` / `schema:validThrough` / `dcterms:valid` |

## 7. Agents, custody & citations → schema.org roles / dcterms

| DDI 2.5 | Meaning | CDIF target |
|---------|---------|-------------|
| `custodian` | data custodian | `schema:maintainer` / contactPoint (Role: custodian) |
| `authorizingAgency` | agency granting authorization | `schema:Organization` (Role) / `conditionsOfAccess` |
| `authorizationStatement` | authorization statement | `schema:conditionsOfAccess` / `schema:description` |
| `studyAuthorization` | study authorization info | `schema:conditionsOfAccess` / `schema:description` |
| `studyBudget` | study budget | `schema:funding` (MonetaryGrant amount) / `additionalProperty` |
| `sourceCitation` | citation of a source | `dcterms:source` / `schema:isBasedOn` / `dcterms:bibliographicCitation` |
| `fileCitation` | citation of a file | `dcterms:bibliographicCitation` on the `schema:DataDownload` |

## 8. Rich-text markup (XHTML / MathML in text fields) → flatten to text

These carry *formatting*, not new metadata concepts; DDI 2.5 allows XHTML/MathML
inside text fields. CDIF uses plain strings, so the text content flattens into the
surrounding `schema:description` / label. **No first-class CDIF mapping.**

`div`, `head`, `hi`, `emph`, `list`, `itm`, `label` (XHTML) · `mi`, `mrow`
(MathML) · `description` (generic text container → `schema:description`) ·
`resource` (embedded link → `schema:url` / `schema:associatedMedia`).

---

### Priority for implementation

1. **`nCube` / dimensional data** (group 1) — genuinely unmapped *data structure*;
   silently dropped today. Ties into the **DataStructure — Dimensional Data**
   profile and would make `ddi25` diverge from the shared 1.2.2 engine.
2. **Code lists** (group 2, incl. the existing `<catgry>` deferral) — ties into
   the **codelist / conceptscheme** profiles.
3. Quality (3) and provenance/lifecycle (4) — additive discovery/provenance value.
4. Geometry (6), sampling (5), agents (7) — incremental discovery enrichment.
5. Markup (8) — flatten only; nothing to model.
