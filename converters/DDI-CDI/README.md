# DDI-CDI XML → CDIF

[`ddicdi_to_cdif.py`](ddicdi_to_cdif.py) converts **DDI Cross-Domain Integration
(DDI-CDI) 1.0 XML** instances to CDIF JSON-LD.

- **Root / namespace:** `<cdi:DDICDIModels>`, `http://ddialliance.org/Specification/DDI-CDI/1.0/XMLSchema/`
- **Schema:** `ddi-cdi.xsd` (DDI-CDI 1.0 XML encoding)

```bash
python ddicdi_to_cdif.py Examples/XML/SPSS_Example.xml -o out.json
python ddicdi_to_cdif.py input.xml --id https://catalog.example/dataset/123
```

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

**Planned phases** (toward the "broadest end-to-end" goal):

2. **Value domains + code lists** — `SubstantiveValueDomain` /
   `SentinelValueDomain` / `ValueAndConceptDescription` / `CodeList` / `Code` /
   `Category` / `Notation` → the CDIF **codelist / conceptscheme** profiles
   (`skos:ConceptScheme`) and variable value ranges.
4. **Physical mappings** — `PhysicalSegmentLayout` / `ValueMapping` /
   `ValueMappingPosition` → `cdi:hasPhysicalMapping` on the distribution.
5. **Provenance** — the process model (`Activity` / `Step` / `Parameter` /
   `ProcessingAgent` / `ProductionEnvironment`, as in `Process_Example_CDI.xml`)
   → **cdifProv** (`prov:wasGeneratedBy`). Parallels the `ddicdiProv` building
   block.
6. **Discovery enrichment** — titles, agents, dates where the instance carries
   them (DDI-CDI examples are often technical and lack a friendly title; the
   dataset name currently falls back to the file stem).

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
- `cdif_Process_Example.json` — Discovery JSON Schema passes (0 variables until
  phase 5 maps the provenance).
