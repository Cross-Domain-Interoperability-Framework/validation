# DDI → CDIF converters

Converters from **DDI XML** to CDIF JSON-LD.

| Converter | Input | Notes |
|-----------|-------|-------|
| [`ddi122_to_cdif.py`](ddi122_to_cdif.py) | DDI **1.2.2** (ICPSR, `http://www.icpsr.umich.edu/DDI/Version1-2-2.xsd`)[^xsd] — e.g. Nesstar-published DHS/MICS/PHIM/World Bank microdata | **source-agnostic** (no repository assumptions) |
| [`ddi_to_cdif.py`](ddi_to_cdif.py) | DDI Codebook **2.5** | **Harvard Dataverse-specific** (identifiers + file-access URLs from the Dataverse API) |
| [`ddi_sssom_to_cdif.py`](ddi_sssom_to_cdif.py) | DDI Codebook **2.5** / **1.2.2** | **data-driven + structured** — applies *every* SSSOM mapping table in [`../mappings`](../mappings) (via `ddi_mappings.json`) and delegates the constructs a flat mapping cannot build (value domains, code lists, statistics) to `ddi122_to_cdif.py`. Edit a worksheet, run `sync_ddi_mappings.py`, and scalar/description mappings take effect with no code change |

`ddi_sssom_to_cdif.py` is the **complete** engine: it applies the full SSSOM
crosswalk data-driven (dataset, variables, distributions,
`prov:wasGeneratedBy`/`prov:wasDerivedFrom` provenance) **and** reuses
`ddi122_to_cdif.py`'s hand-coded builders for the structured content a flat
path cannot produce — the enumerated value domains and per-variable statistics
described below. A worked example is
[`Examples/cdif/cdif_MWI_2015_DHS_v01_M_sssom.json`](Examples/cdif/cdif_MWI_2015_DHS_v01_M_sssom.json)
— its output for [`Examples/XML/MWI_2015_DHS_v01_M.xml`](Examples/XML/MWI_2015_DHS_v01_M.xml)
(2430 deduplicated variables + 451 code lists, 47 distributions), which
validates 0-error against `CDIFDataDescriptionSchema.json`. Run it with:

```bash
python ddi_sssom_to_cdif.py Examples/XML/MWI_2015_DHS_v01_M.xml \
    --doi http://dhsprogram.com/data/available-datasets.cfm --version 25 \
    -o Examples/cdif/cdif_MWI_2015_DHS_v01_M_sssom.json
```

The DDI-Codebook **2.5** source-agnostic converter is
[`../DDICodebook/ddi25_to_cdif.py`](../DDICodebook/ddi25_to_cdif.py) — a thin
wrapper that reuses this converter's extraction engine (2.5 shares the Codebook
element vocabulary with 1.2.2). The **DDI-CDI** (Lifecycle) converter will live
elsewhere.

The element→CDIF mapping below is the single source for all three DDI Codebook
engines: `ddi122_to_cdif.py` (hand-coded), `ddi25_to_cdif.py` (its 2.5 wrapper),
and `ddi_sssom_to_cdif.py` (data-driven from the same crosswalk, delegating the
structured value-domain/statistics build back to `ddi122_to_cdif.py`).

[^xsd]: Heads-up: that canonical 1.2.2 XSD URL is **not reliably accessible**
(icpsr.umich.edu returns HTTP 403 behind Cloudflare, and the schema is not in the
DDI Alliance GitHub repos). See [../DDICodebook/README.md](../DDICodebook/README.md#schema-availability-a-caution)
for where to obtain it (a CESSDA mirror) and the 1.2.2-vs-2.5 element diff.

## `ddi122_to_cdif.py`

```bash
python ddi122_to_cdif.py Examples/XML/MWI-PHIM-CAC-2026-v01.xml -o out.json
python ddi122_to_cdif.py input.xml --id https://catalog.example/dataset/123
python ddi122_to_cdif.py input.xml --base-uri urn:mycat   # mint @id from IDNo
```

Profile scope is **decided per content**: the full study + variable + file
structure is mapped, then [`detect_conformance`](../../detect_conformance.py)
derives `dcterms:conformsTo` from what is actually present (the example files
resolve to **core + discovery + data_description**).

### Mapping (all text whitespace-trimmed)

| DDI 1.2.2 | CDIF |
|-----------|------|
| `stdyDscr/citation/titlStmt/titl` | `schema:name` (scoped to the **study**, not `docDscr/titl` which is the file ID) |
| `…/altTitl` | `schema:alternateName` |
| `…/IDNo` | `schema:identifier` (PropertyValue); also the `@id` fallback |
| `stdyInfo/abstract` | `schema:description` |
| `citation/rspStmt/AuthEnty` (+`@affiliation`) | `schema:creator` (Person\|Organization by name heuristic) |
| `prodStmt/producer` \| `distStmt/distrbtr` | `schema:publisher` |
| `prodStmt/fundAg` | `schema:funder` |
| `method/dataColl/dataCollector` | `schema:contributor` |
| `subject/keyword`, `subject/topcClas` | `schema:keywords` |
| `sumDscr/nation`, `sumDscr/geogCover` | `schema:spatialCoverage` |
| `sumDscr/collDate` (start/end) \| `sumDscr/timePrd` | `schema:temporalCoverage` |
| `method/dataColl/collMode`, `sumDscr/dataKind` | `schema:measurementTechnique` |
| `dataAccs/setAvail/accsPlac[@URI]` | `schema:url` (+ `@id`) |
| `dataAccs/useStmt/conditions`\|`restrctn` | `schema:conditionsOfAccess` |
| `dataAccs/useStmt/citReq` | `dcterms:bibliographicCitation` |
| `prodDate` / `version[@date]` / `collDate` end | `schema:dateModified` / `datePublished` |
| `dataDscr/var` (+`labl`,`varFormat`,`intrvl`) | `schema:variableMeasured` / `cdi:InstanceVariable` (deduplicated by signature; `@id` = `#var/<name>[~N]`) |
| `var/catgry` (`catValu`/`labl`) | enumerated value domain → `cdi:takesSubstantiveValuesFrom` → `cdif:EnumerationDomain` → `cdif:references` a shared `skos:ConceptScheme` code list |
| `var/catgry[@missing]` | `cdi:takesSentinelValuesFrom` → `cdif:SentinelValueDomain` |
| `var/sumStat`, `var/catgry/catStat` | `cdif:isDescribedBy_StatisticsCollection` → `cdi:Statistics` (count/min/max, split by `cdi:computationBase`) + `cdi:CategoryStatistics` |
| `var/sumStat[@type=min\|max]` | also `schema:minValue` / `schema:maxValue` |
| `fileDscr` (+`fileName`,`dimensns`) | `schema:distribution` (`schema:DataDownload`) |
| `docDscr` (producer/prodDate/version) | `schema:subjectOf` catalog record |

### Design decisions

- **No fabricated URLs.** DDI 1.2.2 gives no per-file download URL, so
  distributions carry the OGC nil value
  `http://www.opengis.net/def/nil/OGC/0/missing` as `schema:contentUrl` rather
  than an invented link. The real landing page (`accsPlac/@URI`) becomes
  `schema:url`.
- **No fabricated license.** When the source states no access conditions, a nil
  `schema:license` placeholder is emitted (to satisfy the discovery
  license-or-conditionsOfAccess requirement) rather than assuming CC-BY.
- **Distributions are plain `schema:DataDownload`**, not `cdi:TabularTextDataSet`:
  without a resolvable file and column-to-variable physical mapping, claiming the
  tabular data-structure profile would over-claim (it requires
  `cdi:hasPhysicalMapping` and `cdi:isDelimited`). Row/column counts are kept as
  `schema:additionalProperty`.
- **Agent typing** uses a name heuristic (organization keywords → `Organization`,
  else `Person`), since DDI `AuthEnty` may be either.

### Coded variables → enumerated value domains + statistics

Categorical variables carry an inline DDI code list (`<var><catgry>` with
`catValu`/`labl`/`catStat`) and summary statistics (`<sumStat>`). Both are now
fully emitted:

- **Value domain.** The valid categories become an enumerated substantive value
  domain: `cdi:takesSubstantiveValuesFrom` → `cdif:SubstantiveValueDomain` →
  `cdif:takesValuesFrom` → `cdif:EnumerationDomain` whose `cdif:references`
  points, **by `@id`**, at a shared `skos:ConceptScheme` code list. Categories
  flagged `missing="Y"` route instead to `cdi:takesSentinelValuesFrom` →
  `cdif:SentinelValueDomain`.
- **Shared, deduplicated code lists.** Each distinct set of categories is
  emitted **once** as a `skos:ConceptScheme` node (with the `cdifCodelist`
  discovery metadata: `skos:prefLabel`, `schema:identifier`,
  `schema:dateModified`, `schema:license`, and `skos:Concept`/`cdi:Category`
  entries carrying `skos:notation` + `skos:prefLabel` + `skos:inScheme`).
  Variables that share a code list (e.g. every yes/no field) reference the same
  node. When any code list is emitted the document is a **flattened `@graph`**:
  `{ "@graph": [ dataset, …code lists ] }`.
- **Statistics.** `<sumStat>` and `<catStat>` become
  `cdif:isDescribedBy_StatisticsCollection` → `cdi:StatisticsCollection`:
  `cdi:Statistics` for `count` (valid/invalid/total split by
  `cdi:computationBase`), `minimum`, `maximum`, `mean`, `standardDeviation`,
  `median`, `mode`; and one `cdi:CategoryStatistics` per category (`cdi:for`
  pointing at the shared code-list concept), so per-category frequencies
  reconcile with the valid count.

Both engines build these identically — `ddi122_to_cdif.py` in code, and
`ddi_sssom_to_cdif.py` by delegating to it. `nCube` **aggregate/dimensional**
data (a different data structure) is still not emitted; see
[`../DDICodebook/README.md`](../DDICodebook/README.md).

### The SSSOM worksheets are the source of truth

The DDI→CDIF crosswalk lives in the SSSOM worksheets under
[`../mappings`](../mappings) (`ddi-common-to-cdif`, `ddi25-to-cdif`,
`ddi122-to-cdif`). To change a mapping: edit the TSV in a **text editor**, then
run [`../mappings/sync_ddi_mappings.py`](../mappings/sync_ddi_mappings.py). It
canonicalizes the worksheets (undoing spreadsheet round-trip damage), checks
them against the DDI XSDs, and regenerates `ddi_mappings.json`, which
`ddi_sssom_to_cdif.py` consumes — so a scalar/description mapping takes effect
with no code change. (The structured value-domain/statistics construction is
code, not a flat mapping, and lives in `ddi122_to_cdif.py`.)

## Validation status (3 example files)

`Examples/XML/` holds the three v1.2.2 inputs; they convert to `Examples/cdif/`
(hand-coded engine; `*_sssom.json` is the data-driven engine's output for the
DHS file). Variables are deduplicated by signature. (Two other Malawi files,
`MWI_2019_MICS_v01_M.xml` and `MWI_2024_DHS_v01_M.xml`, are DDI **2.5** and live
under `../DDICodebook/Examples/XML/`.)

| File | vars | dists | code lists |
|------|-----:|------:|-----------:|
| `MWI-CHLINELIST-PHIM-v0` | 39 | 2 | 27 |
| `MWI-PHIM-CAC-2026-v01` | 32 | 1 | 16 |
| `MWI_2015_DHS_v01_M` | 2430 | 47 | 451 |

- **JSON Schema:** each dataset validates 0-error against the
  `cdifDataDescription` profile and every code list against `cdifCodelist`; all
  `cdi:for` / `cdif:references` cross-references resolve within the `@graph`.
  (Both engines' outputs validate; their structured variable content is
  identical.)
- **SHACL** (`../../ShaclValidation/CDIF-Discovery-Shapes.ttl`): **0 violations**;
  warnings are advisory (missing per-variable `propertyID`/physical data type,
  contact points).

> **Note on the CatalogRecord `additionalType` serialization:** the current
> discovery SHACL excludes catalog-record nodes from the dataset mandatory shape
> by matching the **IRI** `dcat:CatalogRecord`, so this converter serializes
> `schema:additionalType` as `{"@id":"dcat:CatalogRecord"}` (not the bare string).
> The older string form used elsewhere in the repo now trips five spurious
> violations per record under the regenerated shapes — see the conversation notes.
