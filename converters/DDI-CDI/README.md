# DDI-CDI XML → CDIF

[`ddicdi_to_cdif.py`](ddicdi_to_cdif.py) converts **DDI Cross-Domain Integration
(DDI-CDI) 1.0 XML** instances to CDIF JSON-LD.

- **Root / namespace:** `<cdi:DDICDIModels>`, `http://ddialliance.org/Specification/DDI-CDI/1.0/XMLSchema/`
- **Schema:** `ddi-cdi.xsd` (DDI-CDI 1.0 XML encoding)

```bash
python ddicdi_to_cdif.py Examples/XML/SPSS_Example.xml -o out.json
python ddicdi_to_cdif.py input.xml --id https://catalog.example/dataset/123
```

`../DDI/ddi2cdif.py` also routes here: it sniffs a `<cdi:DDICDIModels>` root as
`ddi-cdi-xml` and calls this converter, producing byte-identical output. Use the
front door when you do not know the flavor up front, this script when you do.
The **RDF / JSON-LD** serialisation of DDI-CDI is a different reader and is not
implemented; the dispatcher refuses it with a message saying so.

Profile scope is decided **per content** via
[`detect_conformance`](../../detect_conformance.py).

## DDI-CDI XML in one paragraph

Unlike DDI Codebook (a nested document), a DDI-CDI XML instance is a **flat list
of typed objects** under `DDICDIModels`, linked by **`ddiReference`**. Every
object and reference is identified by a `dataIdentifier` +
`registrationAuthorityIdentifier` + `versionIdentifier` triple. The converter
indexes every object by its `dataIdentifier` and resolves references to
reassemble the graph. Reified associations appear as their own objects/elements
(`DataStructure_has_DataStructureComponent`,
`DataStructureComponent_isDefinedBy_RepresentedVariable`, `CodeList_has_Code`, …).

DDI-CDI is also far more verbose than what CDIF embeds: a `cdi:InstanceVariable`
nests `identifier → ddiIdentifier`, `name → name`, `displayLabel →
languageSpecificString → content`, `hasIntendedDataType`, and value-domain
references — which CDIF collapses into a simplified `schema:variableMeasured` /
`cdi:InstanceVariable`. **The converter is a semantic down-shift** from the full
DDI-CDI graph to the CDIF profile form, using the class/attribute crosswalk
encoded in the sibling **`ucmism2m`** project
(`configuration/ddi-cdi2cdif*_mapping.json`) as the mapping authority.

## Status — phased build toward broadest end-to-end

**Phase 1 (done — walking skeleton):**

| DDI-CDI | CDIF |
|---------|------|
| `DataStore` / `WideDataSet` / `PhysicalDataSet` | `schema:Dataset` |
| `InstanceVariable` | `schema:variableMeasured` / `cdi:InstanceVariable` |
| `…/name/name` | `schema:name` |
| `…/displayLabel/…/content` | `schema:description` |
| `…/hasIntendedDataType/name` (SPSS/Stata format) | `cdi:intendedDataType` (`xsd:*`) |
| `Measure`/`Identifier`/`Dimension`/`AttributeComponent` `_isDefinedBy_` the variable | `cdi:role` |
| `PhysicalDataSet` (no download URL) | `schema:distribution` (`DataDownload`, `nil:missing`) |

**Phase 3 (done — data structure):**

| DDI-CDI | CDIF |
|---------|------|
| `WideDataStructure` / `LongDataStructure` / `DimensionalDataStructure` | `cdif:isStructuredBy` → `cdi:<X>DataStructure` (distribution typed `cdi:StructuredDataSet` / `cdi:LongStructureDataSet` / `cdi:DimensionalDataSet`) |
| `DataStructure_has_DataStructureComponent` → `Identifier`/`Measure`/`Dimension`/`AttributeComponent` | `cdi:has_DataStructureComponent` → `cdi:<Component>` |
| `DataStructureComponent_isDefinedBy_RepresentedVariable` | `cdif:isDefinedBy_RepresentedVariable` → `{@id}` of the variable |
| `DataStructure_has_PrimaryKey` | `cdi:has_PrimaryKey` |

`detect_conformance` now adds **`data_structure/1.1`** to the declared profiles.

**Phase 2 (done — value domains + code lists):**

| DDI-CDI | CDIF |
|---------|------|
| `InstanceVariable` -takesSubstantiveValuesFrom-> `SubstantiveValueDomain` | `cdif:hasValuesFrom` → `cdif:EnumerationDomain` (on the variable) |
| `SubstantiveValueDomain` -takesValuesFrom-> `EnumerationDomain`/`CodeList` | `cdif:references` → `skos:ConceptScheme` |
| `CodeList_has_Code` → `Code` -denotes-> `Category`, -uses-> `Notation` | `skos:hasTopConcept` → `skos:Concept` (`skos:notation` = notation, `skos:prefLabel` = category label) |
| `ValueAndConceptDescription/classificationLevel` (Nominal/Continuous/…) | `cdif:classificationLevel` |

Coded (Nominal) variables get their full concept list (e.g. `maritalb`:
`1.0`→"Legally married", …); Continuous/identifier variables carry the
classification level but no code list. Sentinel (missing-value) domains are
deferred to a later pass.

**Phase 5 (done — provenance):**

| DDI-CDI | CDIF |
|---------|------|
| `Activity` (invoked by `Sequence`) + sub-activities | `prov:wasGeneratedBy` → `["schema:Action","prov:Activity"]` |
| `name` / `description` | `schema:name` / `schema:description` |
| `entityUsed/uri` (over the activity tree) | `prov:used` (`{@id}`) |
| `entityProduced/uri` | `schema:result` (`{@id}`) |
| `Activity_has_Step` → `Step` (name, description, script) | `schema:actionProcess` → `schema:HowTo` / `schema:step` (`schema:HowToStep`) |
| `Organization/organizationName` | `schema:agent` |
| `ProductionEnvironment/name` | `schema:location` |

Lights up `Process_Example_CDI.xml` (58 steps, 13 inputs, agent, environment) →
`detect_conformance` adds **`provenance/1.1`**.

**Phase 4 (done — physical mappings):**

| DDI-CDI | CDIF |
|---------|------|
| `PhysicalSegmentLayout` `isDelimited` / `isFixedWidth` | `cdi:isDelimited` / `cdi:isFixedWidth` on the distribution |
| `InstanceVariable_has_ValueMapping` → `ValueMapping`, positioned by `ValueMappingPosition/value` | `cdi:hasPhysicalMapping` entry: `cdi:index` (column), `schema:name`, `cdi:physicalDataType`, `cdi:formats_InstanceVariable` → the variable |

**Phase 6 (done — discovery enrichment + sentinel value domains):**

| DDI-CDI | CDIF |
|---------|------|
| `catalogDetails/title` (dataset-level, when present) | `schema:name` (else the DDI-CDI name / activity name / file stem) |
| `PhysicalDataSet/physicalFileName` | `schema:name` of the distribution |
| `DataStore/recordCount` | `schema:additionalProperty` ("record count") on the distribution |
| `InstanceVariable` -takesSentinelValuesFrom-> `SentinelValueDomain` → CodeList | a second `cdif:hasValuesFrom` → `cdif:EnumerationDomain` with `cdif:valueType: "sentinel"` |

The substantive enumeration (phase 2) now also carries `cdif:valueType:
"substantive"`, so each variable can list *both* domains, flagged by type — e.g.
Continuous `nwspol` has an empty substantive list but a 3-code sentinel list
(Refusal / Don't know / No answer). This follows the CDIF value-domain guidance in
[profile-datadescription#1](https://github.com/Cross-Domain-Interoperability-Framework/profile-datadescription/issues/1#issuecomment-5255033824):
substantive always, sentinel when the source distinguishes it, so a processor need
not merge the two.

**Out of scope:** `DataPoint` / `InstanceValue` (the actual data values) — CDIF is
a *metadata* framework, so the data itself is not carried over.

## Test fixtures

`Examples/XML/` holds two of the **official DDI-CDI 1.0 example instances**
(from `ddi-toolkit/specifications/ddi-cdi-1.0/source/example/xml/`):

- **`SPSS_Example.xml`** — data description/structure: 10 `InstanceVariable`s,
  value domains, code lists, `WideDataStructure`, physical layout, and data
  points (an ESS-style survey extract).
- **`Process_Example_CDI.xml`** — pure **provenance**: `Activity` / `Step` /
  `Parameter` / `ProcessingAgent` (0 variables — exercises phase 5).

A larger `Stata_Example.xml` (2 MB) is available upstream.

## Validation status

- `cdif_SPSS_Example.json` — **Discovery + DataDescription JSON Schema pass**;
  Discovery **and Complete** SHACL **0 violations** (warnings advisory:
  per-variable propertyID, physical data type, contacts). conformsTo:
  core + discovery + data_description + **data_structure**.
- `cdif_Process_Example.json` — **Discovery + Provenance JSON Schema pass**;
  Discovery and Provenance SHACL **0 violations**. conformsTo:
  core + discovery + **provenance** (a pure process/workflow, 0 variables).
