# DDI → CDIF converters

Converters from **DDI XML** to CDIF JSON-LD.

| Converter | Input | Notes |
|-----------|-------|-------|
| [`ddi122_to_cdif.py`](ddi122_to_cdif.py) | DDI **1.2.2** (ICPSR, `http://www.icpsr.umich.edu/DDI/Version1-2-2.xsd`) — e.g. Nesstar-published DHS/MICS/PHIM/World Bank microdata | **source-agnostic** (no repository assumptions) |
| [`ddi_to_cdif.py`](ddi_to_cdif.py) | DDI Codebook **2.5** | **Harvard Dataverse-specific** (identifiers + file-access URLs from the Dataverse API) |

The DDI-Codebook **2.5** source-agnostic converter and the **DDI-CDI** converter
live (or will live) elsewhere; this README documents `ddi122_to_cdif.py`.

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
| `dataDscr/var` (+`labl`,`varFormat`,`intrvl`,`sumStat`) | `schema:variableMeasured` / `cdi:InstanceVariable` |
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

### Known deferral — coded variables

Categorical variables carry an inline DDI code list (`<var><catgry>` with
`catValu`/`labl`/`catStat`). These categories are **not yet emitted** as a CDIF /
DDI-CDI code list (that belongs with the codelist profile); the variable is still
mapped and its category count is recorded in the catalog-record note.

## Validation status (3 example files)

`Examples/XML/` holds the three v1.2.2 inputs; they convert to `Examples/cdif/`.
(Two other Malawi files, `MWI_2019_MICS_v01_M.xml` and `MWI_2024_DHS_v01_M.xml`,
are actually DDI **2.5** and live under `../DDICodebook/Examples/XML/` for the
planned 2.5 codebook converter.)

- **JSON Schema** (`CDIFDataDescriptionSchema.json` and `CDIFDiscoverySchema.json`
  via `../../tools/FrameAndValidate.py`): **3/3 pass** both.
- **SHACL** (`../../ShaclValidation/CDIF-Discovery-Shapes.ttl`): **0 violations**;
  warnings are advisory (missing per-variable `propertyID`/physical data type,
  contact points).

> **Note on the CatalogRecord `additionalType` serialization:** the current
> discovery SHACL excludes catalog-record nodes from the dataset mandatory shape
> by matching the **IRI** `dcat:CatalogRecord`, so this converter serializes
> `schema:additionalType` as `{"@id":"dcat:CatalogRecord"}` (not the bare string).
> The older string form used elsewhere in the repo now trips five spurious
> violations per record under the regenerated shapes — see the conversation notes.
