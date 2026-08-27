# DCAT-AP vs DCAT-US

**Two national/regional profiles of the same W3C vocabulary, built by two governance cultures for two different enforcement models — and deployed at very different levels of maturity.**

| | |
|---|---|
| **Profiles compared** | DCAT-AP 3.0.1 (3.0.2 in public review) · DCAT-US 3.0 + Project Open Data v1.1 |
| **Base** | W3C DCAT 3 (Recommendation, 2024-08-22) |
| **Live figures retrieved** | 2026-08-26 |

---

## The short read

1. **They profile the same vocabulary but enforce it in different substrates.** DCAT-AP is RDF-first: the normative artifact is a set of SHACL shape graphs, and conformance is graph validation. DCAT-US is JSON-first in practice: the artifact GSA actually maintains is a per-class JSON Schema (draft 2020-12), the delivery vehicle is still a `data.json` document at `[agency].gov/data.json`, and RDF serialization is not required for conformance — only that the exchange "SHOULD be unambiguously transformable into RDF."

2. **DCAT-AP constrains values; DCAT-US constrains fields.** DCAT-AP makes only two properties mandatory on `dcat:Dataset` but binds eight properties to EU Publications Office authority tables at SHACL `sh:Violation` severity. DCAT-US makes four properties mandatory on Dataset but its mandatory-vocabulary table is *empty*, with the Data.gov theme taxonomy marked "(TBD)". Practical effect: a DCAT-AP record's licence, frequency, format, language and access-rights values are machine-comparable across 36 countries. The DCAT-US equivalents are strings.

3. **Each profile's extension surface reflects its legal driver.** DCAT-AP grew a family of sibling profiles (GeoDCAT-AP, HVD, MLDCAT-AP, mobilityDCAT-AP, HealthDCAT-AP…) plus ~12 national profiles, and carries first-class legislation binding via `dcatap:applicableLegislation`. DCAT-US grew none, and instead pulled US-specific machinery *into the core*: FOIA/NARA access and use restrictions, CUI banner markings, liability statements, data-dictionary links, an inventoried date — all traceable to OMB M-25-05's 17 required inventory elements.

4. **Deployment maturity is a generation apart.** DCAT-AP has been in continuous release since 2013 and underpins a single federated index of **1,728,622** datasets from 211 harvested catalogues across 36 countries. DCAT-US 3.0 was published 2026-05-01; essentially the entire **552,877**-dataset Data.gov catalogue is still legacy **DCAT-US 1.1**, with roughly four pilot sources being switched to v3 five weeks before the 2026-09-30 compliance deadline.

5. **The raw endpoint census is dominated by one vendor default.** Of 22,835 registered catalogues worldwide, 3,196 expose a DCAT-US 1.1 endpoint and 2,734 expose a DCAT-AP endpoint — but **2,673** catalogues expose *both*, and 2,672 of those are ArcGIS Hub sites emitting both feeds by default. Strip the vendor default and deliberate DCAT-US emission drops to ~512 catalogues.

6. **Neither profile is what search engines actually read.** Google Dataset Search ingests schema.org `Dataset` markup embedded in HTML pages (or "equivalent structures in W3C DCAT"), not standalone DCAT-AP RDF dumps or `data.json` files, and honours no profile-specific term from either side. Both communities reach it through a schema.org side channel — the JRC maintains a DCAT-AP→schema.org crosswalk for exactly this reason.

7. **Only one of the two is measured.** data.europa.eu's Metadata Quality Assurance scores every harvested catalogue against DCAT-AP on a 405-point scale and regenerates reports continuously. The equivalent US instrument — the Project Open Data Dashboard at `labs.data.gov`, which validated every agency `data.json` — is offline; there is currently no public DCAT-US conformance dashboard.

---

# Part I · What the two profiles require

## 1. Provenance and status

Both are profiles of W3C DCAT 3 — neither is a new vocabulary. The asymmetry is age and cadence: DCAT-AP is on its eleventh public release in thirteen years; DCAT-US 3.0 is four months old and is the first genuine profile in a lineage that began as a bespoke JSON schema.

### DCAT-AP

| | |
|---|---|
| Owner | SEMIC action, Interoperable Europe (EC DG DIGIT) |
| Current | **3.0.1**, SEMIC Recommendation, 2025-10-27 |
| In review | 3.0.2 draft, 2026-06-17 |
| 3.0.0 | 2024-06 (finalised against the DCAT 3 Proposed Recommendation) |
| First release | 1.0, 2013-08-06 — 11 releases since |
| Drivers | PSI / Open Data Directive (EU) 2019/1024; HVD Implementing Regulation (EU) 2023/138 |
| Status ladder | Draft → Candidate Recommendation → Recommendation |
| Scope | Explicitly "not limited to publicly accessible Open Data" |

### DCAT-US

| | |
|---|---|
| Owner | Data.gov team, GSA TTS; Federal CDO Council Tiger Team; FCSM co-developer |
| Current | **3.0**, published 2026-05-01 |
| Implementation Guide | v1.0 final, 2026-08-21 |
| Predecessor | Project Open Data v1.1 ("DCAT-US 1.1"), 2014-11-06 — no v2.0; numbering jumped to match DCAT 3 |
| Drivers | Evidence Act / OPEN Government Data Act; OMB M-25-05 (2025-01-15), which rescinded M-13-13 |
| Mandate | Full agency compliance by **2026-09-30** |
| Cadence | Semi-annual per `MAINTENANCE.md` — still self-labelled DRAFT; formal plan due 2026-10-01 |

> **Worth noting.** DCAT-US names DCAT-AP only three times in its entire specification, all in the archived narrative, and always as "akin to" or "a similar approach" — never as an alignment claim. Concrete reuse is exactly *one* term: `dcatap:availability` from `http://data.europa.eu/r5r/`, surfacing as `Distribution.availability`. The Address and Location classes are separately aligned to GeoDCAT-AP 2.0.0.

---

## 2. How conformance is defined

This is the deepest divergence, and it propagates into everything downstream. DCAT-AP asks whether a graph satisfies a shape. DCAT-US asks whether a document satisfies a schema.

| Dimension | DCAT-AP 3.0.x | DCAT-US 3.0 |
|---|---|---|
| **Normative artifact** | SHACL shape graphs shipped per release: `shapes.ttl` (mandatory), `shapes_recommended.ttl`, `range.ttl`, `imports.ttl`, `deprecateduris.ttl`, `mdr-vocabularies.shape.ttl` | JSON Schema draft 2020-12, one file per class, `$id` base `resources.data.gov/dcat-us/3.0.0/definitions/` |
| **Obligation encoding** | SHACL severity: `sh:Violation` = mandatory, `sh:Warning` = recommended; range checks for optional | `requirementLevel` annotation per property + JSON Schema `required[]` |
| **Exchange format** | Serialization-agnostic RDF — RDF/XML, Turtle, N-Triples, JSON-LD all accepted | `data.json` at `[agency].gov/data.json`, ISO/IEC 21778 JSON. RDF optional but the exchange "SHOULD be unambiguously transformable into RDF" |
| **Official validator** | SEMIC SHACL validator on the EC Interoperability Test Bed — 8 validation types (Base / Base Zero / Ranges / Recommendations / Full / Controlled Vocabularies…), REST and SOAP APIs, open-source config | `catalog.data.gov/dcat-us/validator` and `harvest.data.gov/validate/`. Checks mandatory-property presence and format only |
| **Extra properties** | Explicitly allowed — "any property mentioned in DCAT applicable to a class but not explicitly listed in DCAT-AP is considered optional." No `sh:closed` shapes | Allowed; agencies told to "supplement DCAT-US v3.0 with any metadata needed" for agency-specific requirements |
| **Conformance levels** | None formally; the validator's Base / Ranges / Recommendations / Codelists split serves as de facto levels | None. Guide states explicitly that validation ≠ M-25-05 compliance — agencies must independently confirm the 17 statutory elements |
| **SHACL status** | Shipped and maintained per release; backs the official validator | **Unresolved.** Shapes exist only in the archived DOI-DO repo. GSA issue #163 (2026-08-16, open) literally asks "Is SHACL still part of DCAT-US v3, and where do the shapes now live?" |

Obligation levels throughout this report are read from the SHACL severities for DCAT-AP and from the live GSA JSON Schema for DCAT-US, since those are the artifacts the respective validators actually run.

---

## 3. Obligations, class by class

Both profiles carry the same six core DCAT 3 classes. DCAT-AP additionally formalises Catalogued Resource as abstract; DCAT-US adds five classes of its own in a `dcat-us:` namespace (§5).

### Mandatory properties, side by side

| Class | DCAT-AP mandatory | DCAT-US mandatory |
|---|---|---|
| `dcat:Dataset` | `dct:title`, `dct:description` **(2)** | `title`, `description`, `contactPoint`, `identifier` **(4)** |
| `dcat:Distribution` | `dcat:accessURL` **(1)** | *none* — `required[]` is empty **(0)** |
| `dcat:Catalog` | `dct:title`, `dct:description`, `dct:publisher` **(3)** | `dataset` only **(1)** |
| `dcat:DataService` | `dct:title`, `dcat:endpointURL` **(2)** | `title`, `endpointURL`, `contactPoint`, `publisher` **(4)** |
| `dcat:DatasetSeries` | `dct:title`, `dct:description` | `title`, `description` |
| `dcat:CatalogRecord` | `foaf:primaryTopic`, `dct:modified` | `primaryTopic`, `modified` |
| `vcard:Kind` | *(class used only if referenced)* | `fn`, `hasEmail` — and Dataset must carry one |

The empty Distribution requirement in DCAT-US is not a transcription error: the live JSON Schema has `"required": []`, and `downloadURL` is merely optional — a weakening from POD v1.1, where `downloadURL` was required-if-applicable and `mediaType` was required whenever `downloadURL` was present.

### Selected `dcat:Dataset` properties

| Property | RDF term | DCAT-AP | DCAT-US |
|---|---|---|---|
| title | `dct:title` | **mandatory** 1..* | **mandatory** 1..1 |
| description | `dct:description` | **mandatory** 1..* | **mandatory** 1..1 |
| identifier | `dct:identifier` | optional 0..* | **mandatory** 1..1 |
| contact point | `dcat:contactPoint` | recommended | **mandatory** 1..n |
| publisher | `dct:publisher` | recommended + corporate-body NAL | recommended (Organization) |
| distribution | `dcat:distribution` | recommended | recommended |
| keyword | `dcat:keyword` | recommended | recommended |
| theme | `dcat:theme` | recommended — *must* include EU data-theme NAL | recommended — taxonomy TBD |
| spatial coverage | `dct:spatial` | recommended — country/place NAL or GeoNames | recommended — Location w/ WKT, GeoJSON or GML bbox |
| temporal coverage | `dct:temporal` | recommended | recommended |
| landing page | `dcat:landingPage` | optional | recommended |
| licence | `dct:license` | optional on Dataset; recommended on Distribution | recommended on both |
| frequency | `dct:accrualPeriodicity` | optional — EU frequency NAL enforced | optional — three alternative vocabularies accepted |
| applicable legislation | `dcatap:applicableLegislation` | optional (mandatory under HVD) | **absent** |
| in series | `dcat:inSeries` | optional (inverse deliberately unused) | optional; series also carry `seriesMember`, `first`, `last` |
| data dictionary | `dcat-us:describedBy` | **absent** | recommended — full Distribution object |
| inventoried date | *DCAT-US only* | **absent** | recommended — serves M-25-05 |
| access restriction | `dcat-us:accessRestriction` | **absent** | recommended — NARA authority lists |
| use restriction | `dcat-us:useRestriction` | **absent** | recommended |
| CUI restriction | `dcat-us:cuiRestriction` | **absent** | recommended — CUI banner marking + designation indicator |
| quality | `dqv:hasQualityMeasurement` | **absent** (DQV not profiled) | optional — Metric + value + unit |

*Cardinality note:* DCAT-AP repeats literal properties with language tags for multilinguality (`dct:title` is 1..* for exactly this reason); DCAT-US caps `title` and `description` at 1..1, which forecloses the same mechanism.

> **Internal contradictions to watch.** Two spec-versus-artifact divergences are load-bearing if you build a validator.
>
> In **DCAT-US**, the prose spec marks Catalog `title`, `description` and `publisher` mandatory and Distribution `license` mandatory; the live JSON Schema makes all four optional or recommended.
>
> In **DCAT-AP**, the class table gives Catalogue `dct:publisher` cardinality 1, but it carries no `minCount 1` in `shapes.ttl`; conversely `skos:prefLabel`, Concept Scheme `dct:title` and `dcat:hadRole` are `minCount 1` Violations in SHACL while the tables show them optional.
>
> In both cases the executable artifact wins in practice.

---

## 4. Controlled vocabularies

If you only read one section for interoperability purposes, read this one. It is where the two profiles diverge most and where a mechanical crosswalk between them fails.

### DCAT-AP — bound and validated

The spec says the associated vocabularies **MUST** be used; additional vocabularies MAY be added alongside. The bindings are enforced in `mdr-vocabularies.shape.ttl` at `sh:Violation` severity, and the validator exposes a dedicated "Controlled Vocabularies" run.

**Mandated (Violation):**

| Property | Vocabulary |
|---|---|
| `dct:language` | EU Language NAL |
| `dct:accrualPeriodicity` | EU Frequency NAL |
| `dct:accessRights` | EU Access-right NAL |
| `dct:format` | EU File-type NAL |
| `adms:status` | EU Distribution-status NAL |
| `dcatap:availability` | EU Planned-availability NAL |
| Agent `dct:type` | ADMS publisher type |

**Recommended (Warning):** `dcat:theme` and `dcat:themeTaxonomy` → EU data-theme NAL (prose additionally says the value set *must* include data-theme) · `dcat:mediaType`, `compressFormat`, `packageFormat` → IANA · `dct:spatial` → continent/country/place NALs or GeoNames · `dct:publisher` → corporate-body NAL · `dct:type` → dataset-type NAL.

Under the HVD profile, `dcatap:hvdCategory` (EU HVD categories) and an `applicableLegislation` pointing at ELI `reg_impl/2023/138` become mandatory.

### DCAT-US — mostly deferred

The mandatory-vocabularies table in the published specification is **empty**, carrying the caveat that "some of the vocabularies listed are placeholders and will be further developed during the implementation phase." The Data.gov theme taxonomy is marked **(TBD)**.

**What is concrete:** the NARA authority lists behind the restriction classes — Access/Use Restriction Status (Restricted Fully / Partly / Possibly, Undetermined, Unrestricted), Specific Access Restriction (FOIA exemptions (b)(1)–(b)(9), Security Classified, Executive Privilege, PRMPA…), Specific Use Restriction, and the NARA CUI Registry category-marking list (`CUI//SP-CTI` and similar). A SKOS Turtle file of 67 concepts exists — in the archived repo.

**Where a vocabulary exists, it is permissive rather than binding.** `accrualPeriodicity` accepts *any of three* encodings: ISO 19115 maintenance-frequency codes, an ISO 8601 repeating duration (`^R/P.+$`, the POD 1.1 form), or the DCMI Collection Description Frequency vocabulary. `dcterms:accessRights` is free text, with "public" given only as an example.

For geospatial the spec names NGDA spatial data themes, ISO 19115-1 topic categories and the OGC EPSG register — with the harmonised mapping to Data.gov themes marked "(TBD)".

> **Consequence.** A DCAT-AP harvester can filter 1.7 M records by licence type, update frequency, file format, language and access right without normalisation, because the values are URIs from a shared register. The same query against a DCAT-US corpus requires per-publisher string normalisation for every one of those facets. This — not class structure — is the substantive interoperability gap between the two profiles.

---

## 5. What each adds beyond DCAT 3

| Concern | DCAT-AP | DCAT-US |
|---|---|---|
| **Own namespace** | `dcatap:` = `http://data.europa.eu/r5r/` — 4 terms: `applicableLegislation`, `availability`, `hvdCategory`, `LegalResource` | `dcat-us:` — 5 classes, ~19 properties. **Broken:** the namespace IRI resolves nowhere — context and SHACL say `data.resources.gov`, the spec table says `resources.data.gov`. GSA issue #164, open |
| **Legal binding** | First-class: `applicableLegislation` (any ELI resource) and `hvdCategory`, implementing Reg. (EU) 2023/138 | None. Policy compliance is asserted outside the metadata, in the agency inventory process |
| **Restriction / classification** | Only `dct:accessRights` (bound to the access-right NAL) and optionally an ODRL `odrl:hasPolicy` on Distribution | Three dedicated classes: `AccessRestriction`, `UseRestriction` (status + specific restriction + note), `CuiRestriction` (banner marking + designation indicator + per-authority indicators). Plus `LiabilityStatement` |
| **Documentation of variables** | `dct:conformsTo` → Standard; `foaf:page` | `dcat-us:describedBy` — a full Distribution object for the data dictionary; the mechanism M-25-05 uses for "variable names and definitions". Also `metadataDistribution` and `purpose` |
| **Quality** | Not profiled | DQV: `Metric` + `QualityMeasurement` (`isMeasurementOf`, `value`, `unitMeasure`), replacing POD 1.1's `dataQuality` boolean |
| **Geospatial** | Delegated to **GeoDCAT-AP 3.1.0** (2026-02-16), a full sibling profile with an ISO 19115/19139 crosswalk | Folded into core: `Location.bbox` (WKT, GeoJSON or GML), `locn:geometry`, `centroid`, gazetteer `inScheme`, plus a `dcat-us:GeographicBoundingBox` class that exists in SHACL but *not* in the JSON Schema. Stated goal: "eliminating the need for a separate federal standard for this subset of data" |
| **Extension family** | GeoDCAT-AP 3.1.0 · DCAT-AP HVD 3.0.0 · MLDCAT-AP 3.0.0 · mobilityDCAT-AP 1.1.0 · HealthDCAT-AP (draft, EHDS) · StatDCAT-AP (1.0.1; 3.0.0 in review) · languageDCAT-AP · BRegDCAT-AP · EPOS-DCAT-AP v3 · DCAT-AP-JRC | None |
| **National derivatives** | ~12: DCAT-AP.de 3.0 · DCAT-AP-NO 3.0.7 · DCAT-AP-SE 2.0.0 · DCAT-AP-ES 1.0.0 · DCAT-AP_IT 1.1 · DCAT-AP CH 3.0.0 · DCAT-AP-CZ · DCAT-AP-DONL · DCAT-AP.at · DCAT-AP-PL · ModellDCAT-AP-NO · GeoDCAT-AP.de | None. No non-US government has adopted DCAT-US as a national profile |
| **Shared vocabularies** | Both profile SKOS, ADMS, PROV, SPDX, vCard, FOAF, Dublin Core and locn | DCAT-US additionally uses `org:Organization`, `cnt:characterEncoding`, DQV and `schema:image` |

---

## 6. What DCAT-US 3.0 dropped

Migrating US federal publishers is not the additive operation the early messaging described. Nine POD v1.1 fields are absent from the v3.0 JSON Schema, and the published migration guide is silent on five of them.

| Field | Was | Disposition in 3.0 |
|---|---|---|
| `accessLevel` | Required; `public` / `restricted public` / `non-public` | Replaced by free-text `dcterms:accessRights` plus the structured restriction classes. Migration guide gives literal replacement strings |
| `dataQuality` | Boolean | → `dqv:hasQualityMeasurement` |
| `describedByType` | IANA media type | → `mediaType` of the `describedBy` Distribution |
| `references` | Array of URLs | → split into `dcterms:isReferencedBy` and `foaf:page` |
| `isPartOf` | Parent dataset identifier | → `dcat:DatasetSeries` / `dcterms:hasPart` — **not in migration guide** |
| `bureauCode` | Required, `NNN:NN` from OMB Circular A-11 App. C | **No successor. Not in migration guide** |
| `programCode` | Required, `NNN:NNN` from the Federal Program Inventory | **No successor. Not in migration guide** |
| `primaryITInvestmentUII` | Expanded field | No successor — **not in migration guide** |
| `systemOfRecords` | Expanded field, Privacy Act SORN link | No successor — **not in migration guide** |

GSA issue #40, "Make clear what is not backward compatible from v1.1" (opened 2026-01-23), remains open. The loss of `bureauCode`/`programCode` is consequential: they were the only structured link from a dataset to the federal organisational and budget hierarchies, and Data.gov's own organisation facets were built on them.

**Format-level changes that break existing validators regardless:** catalog-level `@context` and `describedBy` are removed; `conformsTo` becomes a `Standard` *object*; `temporal` becomes an array of `PeriodOfTime` objects rather than an ISO 8601 interval string; `spatial` becomes an array of `Location` objects; `language` moves from RFC 5646 tags (`en-US`) to ISO 639-1 (`en`); `license` moves from Dataset to Distribution; and the JSON Schema draft moves from Draft-04 to 2020-12.

For comparison, DCAT-AP 3.0.0's breaking changes were narrow: `dcat:isVersionOf` removed (inverse-property alignment with W3C DCAT), the "Dataset member of a Dataset Series" helper class removed in favour of `dcat:DatasetSeries`, `dcat:byteSize` retyped to `xsd:nonNegativeInteger`, and the Distribution `adms:status` vocabulary swapped.

---

## 7. Health of the specifications themselves

Worth stating plainly, because it affects anyone implementing against either document this year.

### DCAT-AP

- Single canonical location, per-release changelogs, formal change and release management policy.
- Validator maintained in the open with published configuration.
- Known wrinkles: publication dates disagree across the spec page, the Interoperable Europe release list and the git tags; `shapes_recommended.ttl` at the 3.0.0 path still carries a 2.1.1 header; the spec-vs-SHACL divergences noted in §3.
- The EU's own harvesting guidelines still specify **DCAT-AP 2.1.1** — a two-version lag against the current Recommendation.

### DCAT-US

- The canonical home moved twice in 2026. The `DOI-DO/dcat-us` repo was archived 2026-04-28, yet it remains the *only* place hosting the SHACL shapes, the JSON-LD context, the UML and the full narrative.
- The `dcat-us:` namespace IRI does not resolve (issue #164, open).
- No canonical `conformsTo` URI string is published for v3.0 — the only example given is a `Standard` object with the title "DCAT-US 3.0". POD v1.1 had one.
- `MAINTENANCE.md` is self-labelled DRAFT; the formal plan is due 2026-10-01, one day after the compliance deadline.
- `resources.data.gov/resources/data-gov-open-data-howto/` still stated as of 2026-08-26 that "the current version is DCAT-US 1.1. DCAT-US 3.0 is in active development" — five weeks before that deadline. Issue #155 tracks it.
- GSA's own CKAN extension, `ckanext-datajson`, is still 1.1-only. The most mature DCAT-US 3 implementation is the community `ckanext-dcat`, which shipped a `dcat_us_3` profile in v2.1.0 on 2024-10-31 — eighteen months before the profile was published.

---

## 8. Crosswalk feasibility

Because both profile the same DCAT 3 core, the structural mapping is close to trivial. The losses are all at the edges.

| Layer | Assessment |
|---|---|
| **Core classes and properties** | Lossless both ways. Catalog / Dataset / Distribution / DataService / DatasetSeries / CatalogRecord, and the Dublin Core, FOAF, vCard and SKOS properties on them, are shared DCAT 3 terms |
| **Cardinality** | AP→US loses multilingual parallel titles and descriptions (US caps at 1..1). US→AP is safe |
| **Vocabulary values** | The hard direction. US→AP requires mapping free-text `accessRights`, three possible frequency encodings, human-readable formats and RFC 5646 language tags onto EU authority-table URIs — unmappable without publisher-specific rules. AP→US is a simple downgrade to labels |
| **Restrictions** | US `AccessRestriction` / `UseRestriction` / `CuiRestriction` have no DCAT-AP equivalent. The nearest landing spot is `dct:accessRights` plus an ODRL policy, which loses the NARA FOIA-exemption granularity and all CUI marking |
| **Legislation** | AP `applicableLegislation` / `hvdCategory` have no US equivalent and are simply dropped |
| **US organisational codes** | Already lost inside DCAT-US itself (§6), so nothing survives to map |
| **Geospatial** | Both route through ISO 19115 lineage — AP via GeoDCAT-AP, US via the FGDC crosswalk and `metadataDistribution`. GeoDCAT-AP is the better-specified bridge, and DCAT-US already borrows its Address/Location shape |
| **Serialization** | DCAT-US's JSON-LD context is explicitly non-normative and lives in an archived repo; expect to write your own context to lift `data.json` into RDF reliably |

---

# Part II · Where the records actually are

## 9. DCAT-AP in the field

| Metric | Value | Source |
|---|---|---|
| Datasets discoverable on data.europa.eu | **1,728,622** | portal counter, 2026-08-26 |
| Harvested catalogues | **211** | portal counter |
| Countries (EU-27 + 3 EFTA + 6 candidate/partner) | **36** | portal counter |
| Resources carrying an HVD category | **37,054** | SPARQL, 2026-08-26 |

Triplestore counts run higher than the indexed counts, as expected: `dcat:Dataset` 1,907,229 · `dcat:Distribution` 5,427,737 · `dcat:DataService` 1,237,690 · `dcat:Catalog` 35,748 · `r5r:applicableLegislation` assertions 550,798. The Catalog figure counts nested per-organisation catalogue nodes inside harvested payloads, not registered sources.

The structural point behind those numbers: data.europa.eu accepts DCAT-AP over OAI-PMH (its stated preference), SPARQL, or RDF dump files, plus CKAN API "for legacy systems" and CSW for geospatial — and *"every incoming non-DCAT-AP format will be transformed to the most recent version of DCAT-AP."* DCAT-AP is not one option among several in the European chain; it is the interlingua the chain normalises into.

### National portals (counts retrieved 2026-08-26)

| Portal | Software | Profile | Datasets |
|---|---|---|---:|
| datos.gob.es (ES) | Custom + apidata | NTI-RISP / DCAT-AP-ES | 116,424 |
| GovData.de (DE) | CKAN → piveau | DCAT-AP.de 3.0 | ~96,555 † |
| data.gouv.fr (FR) | uData | DCAT-AP | 74,057 |
| data.gov.ua (UA) | Custom | DCAT-AP conformant | ~80,000 |
| data.gov.cz (CZ) | RDF/SPARQL-native | DCAT-AP-CZ | 32,339 |
| data.overheid.nl (NL) | CKAN + ckanext-dcat | DCAT-AP-DONL | 27,090 |
| dataportal.se (SE) | EntryScape | DCAT-AP-SE 2.0.0 | 23,338 |
| data.gov.ie (IE) | CKAN | DCAT-AP | 22,665 |
| data.gv.at (AT) | CKAN | DCAT-AP.at | 22,276 |
| dane.gov.pl (PL) | Custom | DCAT-AP-PL | 21,787 ‡ |
| opendata.swiss (CH) | CKAN | DCAT-AP CH 3.0.0 | 11,934 |
| dados.gov.pt (PT) | uData | DCAT-AP | 10,798 |
| dati.gov.it (IT) | CKAN + ckanext-dcatapit | DCAT-AP_IT 1.1 | 10,528 |

† March 2024 figure; govdata.de is robots-disallowed and the CKAN→piveau migration state could not be confirmed.
‡ All record types, not strictly `dcat:Dataset` — treat as an upper bound.
data.norge.no, avoindata.fi and data.gov.be are client-side rendered and could not be counted.
**The UK is not a DCAT-AP adopter** — data.gov.uk harvests a home-grown profile mixing plain W3C DCAT predicates with US-style `data.json`.

### Platform support

- **ckanext-dcat** — ships `euro_dcat_ap` (1.1.1), `euro_dcat_ap_2` (2.1.0), `euro_dcat_ap_3` (3.0, the default) and `dcat_us_3`. Release 2.4.x, May 2026. It is the single most consequential piece of software in this whole story.
- **piveau** — the Fraunhofer FOKUS stack behind data.europa.eu itself (harvest, store, validate, MQA, SPARQL); supports DCAT-AP, StatDCAT-AP and GeoDCAT-AP; 17 named deployments including Open.NRW, open.bydata and PISTIS.
- **GeoNetwork 4.4** — the widest profile matrix found anywhere: W3C DCAT 3, DCAT-AP 3.0.0, GeoDCAT-AP 3.0.0 (two flavours), DCAT-AP HVD 2.2.0, DCAT-AP-Mobility 1.0.1, exposed via the Formatters API, CSW `outputSchema` and OGC API Records.
- **uData** (data.gouv.fr, dados.gov.pt, data.public.lu), **EntryScape** (dataportal.se, nightly `all.rdf` dump), **InvenioRDM** and therefore **Zenodo** (per-record DCAT-AP export at `application/dcat+xml`), **ArcGIS Hub** (DCAT-AP 3 feed at `/api/feed/dcat-ap/3.0.0.json`).

### Sector deployments

- **INSPIRE.** The INSPIRE Geoportal was **retired 2026-07-01** and now 302-redirects to data.europa.eu; INSPIRE records are discoverable there through GeoDCAT-AP. The number of records migrated was never published — the 1.24 M `dcat:DataService` resources in the triplestore are the best available proxy.
- **Mobility.** mobilityDCAT-AP 1.1.0 (2025-01-17) is a NAPCORE Recommendation across 30+ operational National Access Points covering 26 Member States — but it still profiles **DCAT-AP 2.0.1**, two majors behind, and NAPCORE has never published how many NAPs actually implement it.
- **Health.** HealthDCAT-AP came out of the HealthData@EU pilot (~80-participant technical working group), adds ~20 properties, and is positioned as the foundation for EHDS implementing acts planned for 2027. Still draft; no deployment count.
- **Solid earth.** EPOS-DCAT-AP v3 extends DCAT-AP 3.0 across ~250 data sources and 10 thematic core services — held up by the Commission as its reference implementation.
- **Statistics.** StatDCAT-AP appears dormant: stable at 1.0.1 since 2019, with a 3.0.0 public-review draft opened June 2026 and no deployment count published.
- **Research infrastructure.** The EOSC EU Node Resource Catalogue does *not* use DCAT-AP — it aligns to RDA SKG-IF and the EOSC Research Product Profile. DCAT-AP's touchpoint with the research world is at the repository layer (InvenioRDM/Zenodo), not the aggregator.

---

## 10. DCAT-US in the field

| Metric | Value | Source |
|---|---|---|
| Datasets on catalog.data.gov | **552,877** | portal counter, 2026-08-26 |
| Organizations in the API (103 with public datasets) | **120** | api.gsa.gov v4 |
| Harvest sources being switched to DCAT-US 3.0 | **~4** | GSA issue tracker |
| Days to the M-25-05 compliance deadline | **35** | 2026-09-30 |

Effectively all 552,877 records are **DCAT-US 1.1**. The v3 story is a platform story so far, not a publisher story: Data.gov's harvester gained the ability to ingest DCAT-US 3 `Catalog`, `CatalogRecord`, `DatasetSeries` and `DataService` objects in issues closed 2026-07-17, and the pilots visible in the tracker are the State Department, SSA, OpenTopography and King County WA. No publicly live agency `data.json` serving v3 could be confirmed.

### Concentration

| Publisher | Datasets |
|---|---:|
| US Census Bureau | 293,640 |
| NOAA (across 70 harvest sources) | 87,161 |
| Department of the Interior | 53,209 |
| NASA | 34,772 |
| All others | ~84,095 |

Data.gov metrics for the period ending 2026-07-31, plus the NASA harvest-source page. Four publishers account for roughly 85% of the catalogue; most organisations run one harvest source. The largest non-federal contributors sit two orders of magnitude lower — City of Austin 1,565, Vermont Center for Geographic Information 167, City of Baltimore 40.

> **Ingest surface narrowed in 2026.** Data.gov has migrated to Harvester 2.0 and retired the CKAN Action API (`catalog.data.gov/api/3/action/*` now returns 404; the replacement is `api.gsa.gov/technology/datagov/v4/`). Accepted metadata standards are now only **DCAT-US JSON, ISO 19115 XML and CSDGM XML**, over two source types: a single document, or a Web-Accessible Folder of XML. **CSW, ArcGIS and Socrata are no longer harvester types** — those portals now arrive as plain `data.json` documents like everyone else.

### Beyond the federal government

This is where DCAT-US's real footprint lives, and it is genuinely large: the endpoint census (§11) finds **1,163 local-government** and **421 state/regional** US catalogues exposing a DCAT-US 1.1 endpoint, against 82 central-government ones. Socrata portals — NYC Open Data (3,014 assets), Chicago (2,016), New York State (1,600), Texas (1,470), Los Angeles (926) — all serve `/data.json` declaring `conformsTo: https://project-open-data.cio.gov/v1.1/schema`.

On the geospatial side, **geoplatform.gov** is a consumer rather than a publisher: it harvests federal geospatial metadata from the Data.gov catalogue daily, accepting DCAT-US v1.1 alongside ISO 19139/19115 and FGDC CSDGM.

---

## 11. The endpoint census — and its biggest caveat

Counting catalogues that expose a profile endpoint is the only way to compare the two outside their home portals. It also produces the most misleading number in this report unless you decompose it.

I analysed the commondataio / Dateno data-portals registry directly (`catalogs.jsonl.zst`, 22,835 catalogue records, retrieved 2026-08-26) and tallied typed endpoints.

| Metric | Value |
|---|---|
| Catalogues exposing a DCAT-US 1.1 endpoint | **3,196** (128 countries) |
| Catalogues exposing a DCAT-AP endpoint | **2,734** (109 countries) |
| Catalogues exposing **both** | **2,673** — 2,672 of them ArcGIS Hub |
| Non-ArcGIS-Hub catalogues emitting DCAT-US / DCAT-AP | **512 / 58** |

**Read the fourth row before the first three.** ArcGIS Hub turns on both a `/api/feed/dcat-us/1.1.json` and a DCAT-AP feed for its sites by default; 2,684 of the 3,196 DCAT-US emitters and 2,676 of the 2,734 DCAT-AP emitters are Hub sites. Raw endpoint counts therefore measure one vendor's defaults far more than they measure either profile's adoption.

### DCAT-US 1.1 endpoints by platform

| Platform | Catalogues |
|---|---:|
| ArcGIS Hub | 2,684 |
| Socrata / Tyler | 215 |
| DKAN | 104 |
| CKAN | 83 |
| OpenDataSoft | 30 |
| JKAN | 22 |
| Junar | 14 |
| GeoNode | 13 |
| Esri Geoportal | 8 |
| Other / custom | 23 |

### DCAT-US 1.1 endpoints by country

| Country | Catalogues |
|---|---:|
| United States | 1,948 |
| Canada | 254 |
| United Kingdom | 114 |
| France | 93 |
| Argentina | 53 |
| Germany | 49 |
| Spain | 47 |
| New Zealand | 41 |
| Netherlands | 39 |
| Australia | 37 |

1,248 of the 3,196 are outside the US, across 128 countries — but ~79% of those are ArcGIS Hub emitting the feed by default, not a deliberate national choice. There is no evidence of any non-US government adopting DCAT-US as its national profile.

> **The registry undercounts DCAT-AP.** Only 58 non-Hub catalogues are typed as DCAT-AP endpoints, which is obviously wrong against the 211 catalogues data.europa.eu actually harvests. European portals expose DCAT-AP through CKAN APIs, OAI-PMH, SPARQL and RDF dumps that the registry types generically — 1,681 catalogues carry CKAN endpoints, 1,619 OAI-PMH, 644 a generic DCAT serialization. Treat the DCAT-AP column as a floor, and the DCAT-US column as a vendor-inflated ceiling. The honest comparison: DCAT-AP has more *records* and deeper conformance; DCAT-US 1.1 has more *endpoints*, most of them switched on by Esri.

**Esri's roadmap is the thing to watch.** Esri shipped DCAT-AP 3 support in ArcGIS Hub first (announced 2025-10-28, updated 2026-02-20), stating DCAT-US 3 would follow "within three months" of approval. DCAT-US 3.0 was approved 2026-05-01; as of late August 2026 no shipping announcement exists and the Esri Community idea thread remains open. Given that Hub is ~83% of worldwide DCAT-US emission, that one vendor decision will move the adoption numbers more than the federal mandate will.

---

## 12. Who consumes these profiles

| System | Consumes | Detail |
|---|---|---|
| **data.europa.eu** | DCAT-AP, natively | 1.73 M datasets, 211 catalogues, 36 countries. Normalises every incoming format into current DCAT-AP; re-exposes it over SPARQL and REST |
| **National EU portals** | DCAT-AP | Both consume (from municipal/regional sub-portals) and emit upward. The two-tier chain is why 35,748 catalogue nodes sit behind 211 registered sources |
| **catalog.data.gov** | DCAT-US 1.1 → 3.0 | 552,877 datasets. Harvester 2.0 accepts DCAT-US JSON documents and XML WAFs only |
| **geoplatform.gov** | DCAT-US 1.1 | Daily harvest of the Data.gov catalogue; also ISO 19139/19115-2/19115-3 and FGDC CSDGM |
| **Google Dataset Search** | schema.org, not either profile | Reads schema.org `Dataset` markup embedded in HTML pages, or "equivalent structures represented in W3C's DCAT format" — standalone RDF dumps and `data.json` files are not ingested, and no DCAT-AP or DCAT-US profile term is honoured. CKAN portals reach it through a separate `structured_data` plugin; the JRC maintains a DCAT-AP→schema.org crosswalk for the same reason |
| **Dateno / Common Data Index** | Both, as typed endpoints | Commercial cross-catalogue index; explicitly crawls `dcatus11` and `dcatap201` endpoint types across 22,835 registered catalogues |
| **Eclipse EDC / Dataspace Protocol** | W3C DCAT, not DCAT-AP | The DSP catalog protocol is DCAT 3 + ODRL. DCAT-AP alignment is an open discussion on the connector, not a shipped feature |
| **EOSC Resource Catalogue** | Neither | RDA SKG-IF and the EOSC Research Product Profile |
| **science.data.gov** | — | Dead; the hostname no longer resolves |

The practical implication for anyone optimising for discovery: neither profile is a route into general-purpose web search. Both are portal-to-portal interchange formats, and reaching Google requires per-dataset schema.org JSON-LD on landing pages regardless of which profile you publish.

---

## 13. What is measured, and what is not

### DCAT-AP — continuously measured

The **Metadata Quality Assurance** service scores every harvested catalogue against DCAT-AP on a 405-point scale: Findability 100, Accessibility 100, Interoperability 110, Reusability 75, Contextuality 20. SHACL conformance sits inside Interoperability. Reports regenerate continuously — a GovData report generated on request carried the date 2026-08-26.

The methodology is published: Wentzel et al., *An Extensive Methodology and Framework for Quality Assessment of DCAT-AP Datasets* (EGOV 2023) — 1.6 M+ datasets across 170+ catalogues, 64 M+ discrete measurements, and a longitudinal study of 164 catalogues (Jan 2022 – Mar 2023) showing the average rating move from "sufficient" to "good".

*Gap:* aggregate MQA figures are not published in a fetchable form, and the flagship Open Data Maturity Report 2025 (36 countries, EU-27 portal dimension at 85%) publishes *no* country-by-country DCAT-AP conformance table. The November 2025 EU policy brief on DCAT-AP contains no deployment statistics at all.

### DCAT-US — not measured

The Project Open Data Dashboard at `labs.data.gov/dashboard/` validated every agency `data.json` against the schema and was the instrument for counting compliance. **It is offline — the hostname no longer resolves in DNS.** No replacement public conformance dashboard exists.

The Implementation Guide is explicit that this is by design: *"Data.gov verifies only that catalog submissions include the DCAT-US v3.0 mandatory properties and that those properties are correctly formatted according to the schema."* Passing validation does not establish M-25-05 compliance; agencies must independently confirm all 17 statutory elements. The annual compliance summary is described as "an implementation support tool, not an enforcement document".

Consequence: five weeks from a government-wide mandate, there is no public instrument that can answer "how many agencies are compliant?" — which is why the pilot count in §10 comes from a GitHub issue tracker.

---

# Part III · Implications

## 14. If you harvest or publish across both

1. **Normalise on DCAT 3, not on either profile.** The shared core is genuinely shared and stable. Both profiles' divergences live in vocabularies and profile-specific namespaces, so a DCAT 3 internal model with per-profile decorators survives version churn on both sides better than picking one profile as the canonical form.
2. **Budget for value normalisation on the US side, not schema mapping.** The class and property mapping is a day's work. Reconciling free-text `accessRights`, three legal frequency encodings, human-readable formats and RFC 5646 language tags across ~100 federal publishers and 1,500+ state and local ones is the actual cost.
3. **Validate against the executable artifact, not the prose.** DCAT-AP's SHACL and DCAT-US's JSON Schema each contradict their own specification text in places (§3). Where they disagree, the artifact is what the official validators run.
4. **Treat DCAT-US 3.0 as a moving target through at least Q4 2026.** The namespace IRI is broken, no canonical `conformsTo` URI is published, SHACL's status is an open question in the issue tracker, and the maintenance plan lands a day after the compliance deadline. Pin to the GSA JSON Schema and expect a v3.1 cycle.
5. **Expect a long DCAT-US 1.1 tail regardless of the mandate.** The mandate covers federal agencies; the majority of DCAT-US endpoints in the world are state, local and vendor-default, and both GSA's own `ckanext-datajson` and ArcGIS Hub still emit 1.1 only. Any US harvester needs to speak both versions for years.
6. **For geospatial, prefer GeoDCAT-AP as the bridge.** It is the better-specified of the two ISO 19115 routes, it is on a current release (3.1.0, 2026-02), DCAT-US already borrows its Address/Location shape, and GeoNetwork implements both profiles' formatters side by side.
7. **Don't publish either profile expecting search-engine reach.** Add per-dataset schema.org JSON-LD to landing pages as a separate output. That is the only path into Google Dataset Search from either side.

---

## 15. Sources and method

Live counts were retrieved 2026-08-26. Portal counters for data.europa.eu and catalog.data.gov were read directly and independently confirmed. The endpoint census in §11 was computed locally from the commondataio registry dump rather than taken from any published figure. SPARQL counts against data.europa.eu are reported as retrieved; per-catalogue and per-country `GROUP BY` breakdowns could not be obtained. Figures marked as unverified in the notes could not be confirmed against a primary source.

### Specifications

- W3C DCAT 3 — <https://www.w3.org/TR/vocab-dcat-3/>
- DCAT-AP 3.0.0 / 3.0.1 + changelogs — <https://semiceu.github.io/DCAT-AP/releases/3.0.0/> · <https://semiceu.github.io/DCAT-AP/releases/3.0.1/>
- DCAT-AP repo and SHACL shapes — <https://github.com/SEMICeu/DCAT-AP>
- SEMIC SHACL validator — <https://www.itb.ec.europa.eu/shacl/dcat-ap/upload> · config <https://github.com/ISAITB/validator-resources-dcat-ap>
- Release history — <https://interoperable-europe.ec.europa.eu/collection/semic-support-centre/solution/dcat-application-profile-data-portals-europe/releases>
- DCAT-AP HVD 3.0.0 — <https://semiceu.github.io/DCAT-AP/releases/3.0.0-hvd/>
- GeoDCAT-AP 3.1.0 — <https://semiceu.github.io/GeoDCAT-AP/releases/3.1.0/>
- MLDCAT-AP 3.0.0 — <https://semiceu.github.io/MLDCAT-AP/releases/3.0.0/>
- mobilityDCAT-AP releases — <https://mobilitydcat-ap.github.io/mobilityDCAT-AP/releases/>
- HealthDCAT-AP — <https://healthdcat-ap.github.io/>
- EPOS-DCAT-AP v3 — <https://epos-eu.github.io/EPOS-DCAT-AP/v3/>

### DCAT-US

- GSA schema repo (JSON Schema, `MAINTENANCE.md`, issues #40 #139 #155 #156 #160 #163 #164) — <https://github.com/GSA/dcat-us>
- DCAT-US 3.0 reference — <https://resources.data.gov/resources/dcat-us3/>
- Migration guide — <https://resources.data.gov/resources/dcat-us-3-migration/>
- Schedule / maintenance / release plan — <https://resources.data.gov/resources/dcat-us-3-updates/>
- Implementation Guide v1.0 (2026-08-21) — <https://resources.data.gov/assets/documents/dcat-us-3-implementation-guide.pdf>
- Legacy spec, SHACL, JSON-LD context, NARA vocabularies (archived 2026-04-28) — <https://github.com/DOI-DO/dcat-us> · <https://doi-do.github.io/dcat-us/>
- Project Open Data v1.1 / DCAT-US 1.1 — <https://resources.data.gov/resources/dcat-us/> · <https://resources.data.gov/resources/podm-field-mapping/>
- OMB M-25-05 (2025-01-15) — <https://bidenwhitehouse.archives.gov/wp-content/uploads/2025/01/M-25-05-Phase-2-Implementation-of-the-Foundations-for-Evidence-Based-Policymaking-Act-of-2018-Open-Government-Data-Access-and-Management-Guidance.pdf>
- CDO Council publication notice — <https://www.councils.gov/news-events/news/dcat-us-schema-30-is-published/>

### Deployment

- data.europa.eu portal — <https://data.europa.eu/en> · SPARQL <https://data.europa.eu/sparql> · MQA <https://data.europa.eu/mqa/>
- Harvesting requirements — <https://dataeuropa.gitlab.io/data-provider-manual/how-to-publish/request-harvesting/>
- INSPIRE Geoportal retirement — <https://data.europa.eu/en/news-events/news/inspire-datasets-move-european-data-portal>
- catalog.data.gov — <https://catalog.data.gov/> · metrics <https://data.gov/metrics/> · API <https://api.gsa.gov/technology/datagov/v4/>
- Data.gov harvest pilots (issues #6110–#6260) — <https://github.com/GSA/data.gov/issues>
- Data portals registry — <https://github.com/commondataio/dataportals-registry> (`data/datasets/catalogs.jsonl.zst`, 22,835 records)
- ArcGIS Hub catalog feeds announcement — <https://www.esri.com/arcgis-blog/products/arcgis-hub/data-management/arcgis-hub-catalog-feeds-support-dcat-rss-ogc>
- ckanext-dcat — <https://github.com/ckan/ckanext-dcat> · ckanext-datajson — <https://github.com/GSA/ckanext-datajson>
- Google Dataset Search structured data — <https://developers.google.com/search/docs/appearance/structured-data/dataset>
- DCAT-AP → schema.org crosswalk — <https://ec-jrc.github.io/dcat-ap-to-schema-org/>

### Studies

- Wentzel, Kirstein, Jastrow, Sturm, Peters & Schimmler (2023). *An Extensive Methodology and Framework for Quality Assessment of DCAT-AP Datasets.* EGOV 2023, LNCS 14130, 262–278. <https://doi.org/10.1007/978-3-031-41138-0_17>
- Kirstein, F. et al. (2019). *Linked Data in the European Data Portal: A Comprehensive Platform for Applying DCAT-AP.* EGOV 2019. <https://doi.org/10.1007/978-3-030-27325-5_15>
- Neumaier / Kubler et al. (2022). *Towards a standard-based open data ecosystem: analysis of DCAT-AP use at national and European level.* Electronic Government, an International Journal. <https://doi.org/10.1504/EG.2022.121856>
- Bailo, D. et al. (2023). *The EPOS multi-disciplinary Data Portal.* Scientific Data 10:784. <https://doi.org/10.1038/s41597-023-02697-9>
- Derycke, P. et al. (2025). *Designing DCAT-AP extensions for common European data spaces: The EHDS HealthDCAT-AP case study.* CEUR-WS Vol-4064. <https://ceur-ws.org/Vol-4064/NXDG25-paper5.pdf>
- Open Data Maturity Report 2025 — <https://data.europa.eu/sites/default/files/2025-12/2025_odm_report_5.pdf>

---

*Prepared 2026-08-26. Profiles as published at that date: DCAT-AP 3.0.1 (3.0.2 in public review), DCAT-US 3.0 (Implementation Guide v1.0). Both profile W3C DCAT 3. Counts change; the structural comparison in Part I should outlast them.*
