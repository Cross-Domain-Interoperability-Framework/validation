# Stage-2 domain-conformance — handoff notes

Status as of 2026-10-16. Cross-session effort to add **domain-profile conformance
detection** (geochemProduct → adaProduct → technique profiles) on top of the CDIF
module detection, plus the sidecars and loader wiring that feed it.

**Sessions / repos involved**

| Role | Session | Repo |
|------|---------|------|
| Stage-2 engine, format, builder | *Validation* | `Cross-Domain-Interoperability-Framework/validation` |
| Sidecar generation | *gBB TAPPS* | `amds-ldeo/geochemBuildingBlocks` (geochemProduct schema: `_sources/BaseSchema/geochemProduct/schema.yaml`) |
| Loader that calls detection | *metadata Geochem forms interface* | `amds-ldeo/metadata` (ADA loader / `load_json_table`) |
| CDIF module profiles + shapes | — | `Cross-Domain-Interoperability-Framework/metadataBuildingBlocks` |

---

## Status — the validation engine is done and validated

Landed and **pushed** to validation `main`: two-stage engine
(`detect_cdif_conformance` + `detect_domain_conformance`), sidecar schema **0.2**
(`requires` / `exclusiveGroup` / `priority`), the presence-ASK builder
(`build_component_presence_ask`), the convention doc, 19 tests, and an
empty-graph guard in `_to_graph`.

**Acceptance (gBB, 2026-10-16)** over the 111 examples that declare a geochem
profile: **55 reproduce, 56 differ, 0 errors** — and all 56 are accounted for,
**none on the validation side**: 35 are ties behaving as designed (20 ICP-MS
families + 15 forked-cid pairs), 18 are profile blocks with no discriminating
componentType (not content-detectable, correctly skipped), 3 are a gBB
base-fixture over-match bug. The engine is confirmed correct against real data.
(An earlier "stage 1 returns zero" alarm was a gBB result-wrapper bug, not the
engine.)

---

## Decisions made (Steve, 2026-10-16)

- **`requires` is derived from the schema**, not hand-listed: a profile's
  `requires` = the module URIs of the CDIF profiles its schema composes
  **unconditionally** in `allOf`. A conditional (`if/then`) composition is not a
  flat require; a nested `$defs` `$ref` is not an inherited profile.
- **`geochemProduct.requires = core/1.1 + provenance/1.1`** (two). `cdifDataDescription`
  and `cdifManifest` are now composed **conditionally**, so they are not flat
  requires; `discovery` and `data_structure` are not composed at all.
- **`data_description` condition**: required only when the record has variables —
  non-empty `schema:variableMeasured`, or a part typed `cdi:TabularTextDataSet`
  (the neutral type, since geochemProduct is the domain-neutral base).
- **Forked-cid ties → one label per technique, the new (TAPP) block wins.** Where
  a technique has two cids (the TAPP block and a legacy `profile-ada` twin), put
  the pair in one `exclusiveGroup` and rank the TAPP block above the legacy twin,
  so a record resolves to the new profile. (No engine change — priorities only.)
- **ICP-MS families stay an honest tie.** The six LA-/Solution-ICP-MS families
  share one componentType by design (the Mc/Q/Sf difference is procedure-side,
  never in the file); equal priority → reported tie, none declared, until records
  carry a TAPP reference. Correct, non-fatal.
- **Exclusion set** = the 22 universal componentTypes from gBB's
  `registry/vocab/componentType.json` (the four generics `analysisLocation` /
  `report` / `contextPhotography` / `quickLook` are a subset), left out of every
  technique `presence` ASK so they don't match universally.

---

## Open problems

### O1 — `#None` physical-mapping generator bug
- **Problem.** Of 1,754 `cdif:hasPhysicalMapping` entries, **912 point at
  `{"@id": "#None"}`** instead of a real `cdi:InstanceVariable`, affecting **877
  records**. Columns were described, but their variable references were emitted as
  the literal `#None` — a bug, not missing metadata. (It is also why the
  `data_description` condition includes "OR a tabular part": so these 877 keep
  being asked for data description until the bug is fixed.)
- **Proposed solution.** Fix the generator so physical-mapping references resolve
  to real `cdi:InstanceVariable` nodes.
- **Target repo.** `amds-ldeo/metadata` (the ADA `json_table` → CDIF generator).
- **Owner.** *metadata Geochem forms interface*. Open.

### O2 — Base-fixture over-match (gBB acceptance group 4)
- **Problem.** 3 base fixtures over-match: `exampleadaProduct*` pick up
  `adaEPMA`; `examplegeochemProduct` picks up `adaProduct`. The base-layer
  `presence` rules are too loose, so a base product matches a technique.
- **Proposed solution.** Tighten the base-layer presence so a base product does
  not satisfy a narrower profile's marker.
- **Target repo.** `amds-ldeo/geochemBuildingBlocks`.
- **Owner.** *gBB TAPPS*. Open (gBB's defect).

### O3 — `cdifDiscovery` presence rule is too broad
- **Problem.** `cdifDiscovery`'s presence is `?d a schema:Dataset ; schema:name ;
  schema:identifier` — it fires for essentially every dataset, so discovery is
  declared for everything. Per Steve, discovery should be identified by **use of
  its optional properties** (spatialCoverage, temporalCoverage, variableMeasured,
  measurementTechnique, dqv:hasQualityMeasurement, subjectOf, …), none of which is
  top-level required.
- **Proposed solution.** Revise the discovery presence ASK to test for use of any
  of those marker properties. Needs a decision on which properties mark discovery.
- **Target repo.** `metadataBuildingBlocks` (`cdifDiscovery/conformance.json`) +
  the `CONFORMANCE_CLASSES` registry in `validation/detect_conformance.py`.
- **Owner.** Needs **Steve's design decision**; then mBB + validation. Open.

### O4 — Generate and commit the geochem sidecars
- **Problem / status.** ~63 `conformance.json` sidecars generated across 76
  blocks (7 skipped as forked-cid losers, 6 as having no discriminating
  componentType), **not yet committed** — pending the decisions above having been
  exercised.
- **Proposed solution.** Finalize per the decided contract (requires derived;
  `presence` via `build_component_presence_ask`; forked-cid pairs ranked
  TAPP-over-legacy; ICP-MS families equal-priority ties), then commit.
- **Target repo.** `amds-ldeo/geochemBuildingBlocks`.
- **Owner.** *gBB TAPPS*. Open.

### O5 — Wire both detection stages into the loader
- **Problem.** The ADA loader must run stage 1, then stage 2, and write both into
  `dcterms:conformsTo`.
- **Proposed solution.** From `load_json_table`: `cdif = detect_cdif_conformance(doc)`;
  `dom = detect_domain_conformance(doc, cdif, bb_dir=<geochem _sources>)`;
  `apply_conformance(doc, cdif)`; `apply_conformance(doc, dom.declared,
  manage_prefix=GEOCHEM_BASE, append=True)`. Surface `dom.withheld` / `dom.ties`.
  Add a **caller-side assertion**: a stage-1 result of zero modules for a
  non-empty document should fail loudly, not flow into stage 2 as empty
  `prior_uris` (the check that would have caught the earlier wrapper bug).
- **Target repo.** `amds-ldeo/metadata`.
- **Owner.** *metadata Geochem forms interface*. Open (waits on O4).

### O6 — ICP-MS tie-break when TAPP references exist
- **Problem.** The six ICP-MS families tie today because no record carries a TAPP
  reference (`prov:used` → a TAPP definition). This is correct now, not a defect.
- **Proposed solution.** When records carry a TAPP reference, narrow each
  variant's `presence` with a `prov:used` clause testing it → exactly one member
  matches, tie resolves through presence. `build_component_presence_ask` is
  extended with the TAPP clause once gBB sends its shape (property + structure).
- **Target repos.** `validation` (builder) + `amds-ldeo/geochemBuildingBlocks`
  (regenerate those families' presence) + `amds-ldeo/metadata` (records carry the
  ref). Open by design, sequenced last.

---

## Resolved / recorded (no action — listed so they aren't reintroduced)

- **35 inert profile SHACL shapes** targeted `schema:additionalType
  "dcat:CatalogRecord"` as a string literal (records carry the IRI) → selected 0
  focus nodes, "passed" vacuously. Fixed in **gBB PR #141 (merged)**. Do not reuse
  them as `validityShapes` (circular, and never content shapes). Repo:
  `amds-ldeo/geochemBuildingBlocks`.
- **One-componentType-per-product permanence** recorded in gBB's `CLAUDE.md`
  (**gBB PR #145**); a `.mc/.q/.sf` componentType proposal is refused on this
  basis. Also in `validation/docs/CDIF-Conformance-Declaration-Convention.md`.

---

## What each repo would change

| Repo | Pending changes |
|------|-----------------|
| `amds-ldeo/geochemBuildingBlocks` | O2 (tighten base presence), O4 (finalize + commit sidecars), O6 (regenerate ICP-MS presence when TAPP refs exist) |
| `amds-ldeo/metadata` | O1 (fix `#None` refs), O5 (wire both stages + caller-side zero assertion) |
| `metadataBuildingBlocks` | O3 (revise `cdifDiscovery` presence rule) |
| `Cross-Domain-Interoperability-Framework/validation` | O3 (registry side of the discovery rule), O6 (TAPP-reference clause in the presence builder) — both on decision/sequencing |

The validation engine itself needs no further change for the current scope; the
remaining work is sidecars (gBB), loader wiring (forms), and the two decisions in
O3 and O6's sequencing.
