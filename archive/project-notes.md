# Project notes (DDI → CDIF conversion)

> Migrated on 2026-09-01 from Claude Code's per-project memory store so the
> conventions live with the code instead of in an assistant's private store.
> These are point-in-time observations (original capture dates noted per
> section); verify against current code before treating any file/line claim as
> live fact.

---

## Project scope — Layer C only (OHDSI / DDI → CDIF)

The working context in `C:/GithubC/CDIF/validation` is the **OHDSI project**. Its
scope is **Layer C only**: code and mappings that convert **DDI Codebook 1.2.2**
or **DDI Lifecycle 2.5** metadata (from the OHDSI / Malawi project) into **valid
CDIF metadata**, and **determining which CDIF profiles are required**
(conformance).

In-scope work lives in:

- `validation/converters/DDI/`, `validation/converters/DDICodebook/` (the converters)
- `validation/converters/mappings/` (the SSSOM crosswalks)
- profile determination: `detect_conformance.py` / `ConformanceValidate.py` (which
  CDIF profiles the output conforms to)

**Out of scope — separate concerns, do NOT do them as part of OHDSI work:**

- **Layer A (generalizable building blocks):**
  `metadataBuildingBlocks/_sources/{cdifDataType,schemaorgProperties,profiles/cdifProfile}`,
  shared tooling (`FrameAndValidate.py`, `resolve_schema.py`). Changes here ripple
  to every profile + release repo.
- **Layer B (XAS domain profile):** `xasProperties/*`, `xasDocument`, `XAS-CDIF`,
  `cdif-xas-UKDS`.

**How to apply:** the converter is a **pure consumer** of the published CDIF
profiles — it must not edit building blocks to make its output validate. When
conversion hits a genuine building-block gap (e.g. no clean way to represent
category statistics), that is a **separate, explicitly-scoped mBB change** decided
on its own merits for all profiles, on its own branch/commit — never smuggled into
OHDSI conversion work. A converter commit that also touches
`metadataBuildingBlocks/**` is the signal to split it. See *FrameAndValidate
normative source* below.

---

## FrameAndValidate.py — single normative source (captured 2026-06)

`FrameAndValidate.py` has **one normative source**:
`validation/tools/FrameAndValidate.py`. The identical script is shipped in every
CDIF release repo (`profile-core`, `profile-manifest`, `profile-discovery`,
`profile-codelist`, `doc-*`, …) as a *generated copy* carrying a
`# GENERATED FILE -- DO NOT EDIT` banner + `src-sha256`.

**How to change it (when working in the validation repo):**

1. Edit `validation/tools/FrameAndValidate.py` (never a release-repo copy).
2. `python tools/sync_frameandvalidate.py --apply` (verifies each repo's
   `examples/` don't regress, then rewrites copies with banner + read-only).
3. Commit the validation repo **and** each updated release-repo copy.

**Why:** the copies had drifted (40–772 differing lines) before unification. The
script is profile-agnostic (auto-detects each repo's one schema/frame;
`ARRAY_PROPERTIES` is the union across all profiles; the main-entity picker matches
the frame root, handling Dataset- and SKOS-rooted profiles).

**Note on scope:** in-file `DO NOT EDIT` banner and the per-repo CI drift check
(`.github/workflows/check-frameandvalidate.yml`, `UPSTREAM_REF: main`) guard the
copies in other repos' sessions. See `validation/tools/README.md`.

---

## CDIF access-URL convention (captured 2026-07)

In CDIF, map the DCAT access pattern onto schema.org like this:

- **`dcat:accessURL` that returns a landing/browse page** (e.g. a web-accessible
  directory index, a DOI landing page) → serialize as
  **`schema:Dataset/schema:url`** (may be an array of several). NOT as a
  `schema:DataDownload`.
- **`dcat:downloadURL` (a direct file)** → `schema:DataDownload` with
  `schema:contentUrl`. A templated single-file fetch (URL pattern with parameters)
  is a real download → a `DataDownload` hosting a `schema:DownloadAction`
  (`EntryPoint.urlTemplate` + `PropertyValueSpecification` query-input).
- **`dcat:accessService` (an API)** → `schema:WebAPI` distribution carrying
  `schema:potentialAction` (`SearchAction` for a query service; requires
  `schema:termsOfService`).

Un-parameterized concrete URLs are links, not Actions; parameterized/templated URLs
are `potentialAction`s with the verb matching the result (DownloadAction for a
file, SearchAction for a query/listing).

**Why:** a draft that modeled a browsable data directory as a `DataDownload` was
corrected — per CDIF it is an accessURL and belongs on `schema:url`. **How to
apply:** when converting SPASE/DCAT/agency metadata to CDIF, sort each URL into
landing-page (→`schema:url`), direct-file (→`DataDownload/contentUrl`), or service
(→`WebAPI/potentialAction`) before choosing the serialization.

---

## CatalogRecord additionalType must be an IRI (captured 2026-08-26)

The regenerated `validation/ShaclValidation/CDIF-Discovery-Shapes.ttl` (from the
"[automated] Update SHACL shapes" commit) excludes catalog-record nodes from
`cdifd:CDIFDatasetMandatoryShape` via
`MINUS { ?this schema:about ?x ; schema:additionalType dcat:CatalogRecord }` where
`dcat:CatalogRecord` is an **IRI**. It also lints `schema:additionalType` string
values that look like CURIEs.

Consequence: a `schema:subjectOf` CatalogRecord that serializes
`"schema:additionalType": ["dcat:CatalogRecord"]` as a **string** is NOT excluded,
so the mandatory shape fires 5 spurious violations per record (identifier,
url-or-distribution, dateModified, license, + the CURIE lint). This hits the whole
legacy corpus: `testJSONMetadata/*` and the OHDSI `cdifMetadata/*` — all on the
CatalogRecord node.

**Convention (confirmed by user):** the building blocks definitively require the
IRI form `"schema:additionalType": [{"@id": "dcat:CatalogRecord"}]`. The string
form is deprecated.

**Fixed (2026-08) — all emit sites now output the IRI form:**
`converters/DDI/ddi122_to_cdif.py` (new), `converters/soso/ConvertFromSOSO.py`,
`converters/croissant/ConvertFromCroissant.py`, `converters/DCAT/dcat_to_cdif.py`,
`converters/DDI/ddi_to_cdif.py`, `geocodes_harvester.py`, and the OHDSI harvester
`../OHDSI/harvest_ohdsi_to_cdif.py`. Match sites made tolerant of
string/@id/full-IRI. `converters/DDI/ddi_sssom_to_cdif.py` (the engine that
generates the committed converter examples) added the same typed catalog record
on 2026-09-01 (`build_contributors`/subjectOf typing) — before that its examples
carried an *untyped* `schema:subjectOf` with no `dcat:CatalogRecord` marker.

**Re-verified 2026-09-01 — the follow-on corpus has since migrated to the IRI
form:** all 77 `testJSONMetadata/*` (ADA pipeline), all 4 `MetadataExamples/*`,
and the committed converter example outputs now serialize
`schema:additionalType: [{"@id":"dcat:CatalogRecord"}]`. **Still string-form:**
only the generated schemas `CDIFCompleteSchema.json` /
`CDIF-graph-schema-2026.json`, which carry `"dcat:CatalogRecord"` as a JSON
Schema `const` and must be regenerated from updated building blocks. Analogous
separate lint: URI-valued `schema:propertyID` should also be `{"@id":...}`.

**Shape note (2026-09-01):** in `CDIF-Discovery-Shapes.ttl` the *mandatory* shape
(`CDIFDatasetMandatoryShape`) excludes catalog records by the `dcat:CatalogRecord`
**IRI**, but the *recommended* shape (`CDIFDatasetRecommendedShape`) still MINUSes
the **string** `"dcat:CatalogRecord"` — the two shapes disagree on form. This is a
Layer-A/building-block matter, not an OHDSI-converter concern.

**Why:** IRI is the more correct RDF (reference to the DCAT class) and is what the
current shapes match. **How to apply:** when writing/patching any CDIF
`schema:subjectOf` CatalogRecord, use `{"@id":"dcat:CatalogRecord"}` for
`schema:additionalType`.

---

## XAS generator tracking (captured 2026-07-17) — *Layer B, out of OHDSI scope*

> Retained here for reference only; this concerns the XAS domain profile, not the
> DDI → CDIF conversion work.

`C:\GithubC\CDIF\XAS-CDIF\tests\cdif_dds_framed.jsonld` is produced by generator
code **Deirdre** maintains (the "cdif xas JSON" generator). When this file is
hand-fixed or fails schema validation, the changes must be reported back so the
generator can be updated. Running log of what the generator should emit lives in
`C:\GithubC\CDIF\XAS-CDIF\tests\cdif_dds_framed-generator-notes.md` (before→after
per gap).

As of 2026-07-17 the file declares `https://w3id.org/cdif/xasCore/1.0` and still
fails 6 xasCore / 7 XASdata checks. Remaining generator gaps: (1) activity `@type` →
`["schema:Action","prov:Activity"]` (not `schema:Event`) **plus**
`schema:additionalType: ["xas:AnalysisEvent"]`; (2) instrument wrapper needs
`schema:instrument.schema:hasPart` with NXsource (type+probe) + NXmonochromator
(type+d_spacing+reflection); (3) all `schema:keywords` must be DefinedTerm objects
(element→SWEET matrElement, edge→XDI dict; no plain strings); (4) `@context` `xas` →
`https://xas.org/dictionary/` (not `ada.astromat.org/metadata/xas/`).
