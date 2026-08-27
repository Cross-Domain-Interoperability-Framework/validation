# DCAT profile example metadata

778 example metadata files covering DCAT-AP, its extensions and national derivatives, and DCAT-US in both its current (3.0) and legacy (1.1 / Project Open Data) forms. Assembled 2026-08-26 from the upstream specification repositories.

`MANIFEST.csv` lists every file with its profile, format, size, parse status and triple count. 737 of 778 files parse cleanly; the exceptions are noted under **Parse status** below and are almost all deliberate fragments.

Everything here is public-domain or openly licensed by its upstream (EUPL / CC-BY for the SEMIC material, 17 USC §105 / CC0 for the US material, AGPL for the CKAN fixtures). Original licence files were not copied — check upstream before redistributing.

---

## Layout

| Directory | Profile | Files | What it is |
|---|---|---:|---|
| `01-dcat-ap/3.0.1-core/` | DCAT-AP 3.0.1 | 31 | The canonical SEMIC examples that appear inline in the specification — the "bee population" dataset and dataset-series set, each in Turtle and JSON-LD, plus `context.jsonld` |
| `01-dcat-ap/3.0.0-hvd/` | DCAT-AP HVD 3.0.0 | 30 | High-Value Dataset examples: member-state catalogue, HVD-categorised datasets, data services with OpenAPI/SLA/service-desk endpoint descriptions, licence mapping |
| `01-dcat-ap/real-world/` | DCAT-AP as emitted | 12 | Records captured from actual portals — `dataset_gov_de.rdf` (GovData), `dataset_sweden.rdf`, `dataset_gob_es.ttl`, multilingual and catalogue-level examples |
| `02-geodcat-ap/2.0.0-examples/` | GeoDCAT-AP 2.0.0 | 76 | One example per class and per construct, each in Turtle, RDF/XML and JSON-LD: geometry, bbox, CRS, provenance, attribution, addresses, quality, lineage |
| `03-mobilitydcat-ap-1.1.0/` | mobilityDCAT-AP 1.1.0 | 5 | Swedish National Access Point records — the same dataset in the original proprietary DCAT-AP form and re-expressed in mobilityDCAT-AP, minimum and full population |
| `04-healthdcat-ap/` | HealthDCAT-AP (draft) | 5 | RDF template plus health-dataset fixtures including the multilingual and no-blank-node variants |
| `05-mldcat-ap-3.1.0/` | MLDCAT-AP 3.1.0 | 10 | Machine-learning model descriptions — EOSC, HuggingFace BLOOM and Apertus — plus the EOSC MLDCAT-AP context |
| `06-statdcat-ap-1.0.1/` | StatDCAT-AP 1.0.1 | 1 | The profile vocabulary itself (this profile ships no instance examples) |
| `07-national-profiles/de-dcat-ap-de/` | DCAT-AP.de | 9 | Reference dataset plus the V2.0 example set in Turtle, RDF/XML and JSON-LD |
| `07-national-profiles/no-dcat-ap-no/` | DCAT-AP-NO | 5 | Norwegian examples including a dataset-series example |
| `07-national-profiles/es-dcat-ap-es/` | DCAT-AP-ES 1.0.0 | 69 | The most instructive national set: `Conventions_*` files give **paired correct/incorrect** examples for contact point, spatial coverage, geometry, temporal, themes, ELI, HTTP URIs, API keys and OGC services |
| `10-dcat-us-3.0/rdf/` | DCAT-US 3.0 | 251 | The RDF examples from the (now archived) DOI-DO spec repo — one per class and per property, in Turtle and JSON-LD, with `catalog/`, `dataset/` and `agent/` subdirectories |
| `10-dcat-us-3.0/json/` | DCAT-US 3.0 | 191 | The live GSA JSON Schema examples, organised per class into `good/` and `bad/`. The `bad/` files are deliberately invalid — useful as negative test cases |
| `10-dcat-us-3.0/context/` | DCAT-US 3.0 | 1 | `dcat-us-3.0.jsonld` — the JSON-LD 1.1 context (explicitly non-normative) |
| `11-dcat-us-1.1-pod/spec-samples/` | DCAT-US 1.1 | 4 | The Project Open Data `catalog-sample.json` and `catalog-sample-extended.json`, plus CSV equivalents |
| `11-dcat-us-1.1-pod/real-world/` | DCAT-US 1.1 | 15 | **Real agency `data.json` captures** — `usda.gov`, `ny`, `arm`, plus geospatial, collection/parent-child, and a 300 KB large-spatial catalogue. Also several malformed catalogues used as harvester test cases |
| `12-ckan-crosswalk/` | CKAN ↔ DCAT | 13 | Paired CKAN-native JSON for the same records serialized in `01-dcat-ap/real-world/` — the practical mapping between CKAN's data model and both profiles, including a DCAT-US vocabularies fixture |
| `_schemas/` | — | 50 | DCAT-AP 3.0.1 SHACL, GeoDCAT-AP 3.1.0 SHACL, HealthDCAT-AP SHACL, DCAT-US 3.0 SHACL, DCAT-US 3.0 JSON Schema definitions |

---

## Where to start, by task

**Comparing what the two profiles look like on the wire.** Put `01-dcat-ap/3.0.1-core/example-bee-population.ttl` next to `10-dcat-us-3.0/rdf/dataset/` and `11-dcat-us-1.1-pod/spec-samples/catalog-sample-extended.json`. The first is a fully-populated DCAT-AP dataset with authority-table URIs throughout; the third is the same conceptual record with free-text values and US-only fields (`bureauCode`, `programCode`, `accessLevel`).

**Building or testing a validator.** `10-dcat-us-3.0/json/*/bad/` gives ready-made negative cases against the GSA JSON Schema. `07-national-profiles/es-dcat-ap-es/ttl/Conventions_*_correct.ttl` / `*_incorrect.ttl` do the same for DCAT-AP conventions. `_schemas/` has the shapes to run them against.

**Understanding what publishers actually emit** (as opposed to what specs illustrate): `01-dcat-ap/real-world/` and `11-dcat-us-1.1-pod/real-world/`. The malformed catalogues in the latter — missing identifiers, numerical titles, null spatial, reserved titles — are the failure modes Data.gov's harvester actually encounters.

**Geospatial handling.** `02-geodcat-ap/2.0.0-examples/` for the European route (CRS, geometry, lineage, conformity) versus `10-dcat-us-3.0/rdf/` (`antimeridian-bbox`, `crs`, spatial/Location examples) for the US route. DCAT-US borrows GeoDCAT-AP's Address/Location shape, which is visible if you diff the address examples.

**Dataset series.** `01-dcat-ap/3.0.1-core/example-bee-population-dataset-series*.ttl` is the most thorough treatment anywhere — twelve variants covering frequency, spatial, temporal ordering, issued/modified propagation and API-backed series. Compare with `10-dcat-us-3.0/rdf/dataset-series.*` and `11-dcat-us-1.1-pod/real-world/collection-*-parent-*-children.data.json`, which is how the same idea was done with POD's `isPartOf`.

**Legislation / HVD binding.** `01-dcat-ap/3.0.0-hvd/` — `applicableLegislation` and `hvdCategory` in practice. There is no DCAT-US equivalent to compare against.

**US restriction and CUI machinery.** `10-dcat-us-3.0/json/AccessRestriction/`, `UseRestriction/`, `CUIRestriction/` and the corresponding `rdf/` files. No DCAT-AP equivalent; the nearest is `dct:accessRights` plus an ODRL policy.

---

## Parse status

From `MANIFEST.csv`: 737 files parse, 14 are fragments, 21 fail, 6 are non-parseable types (CSV, Markdown, XLSX).

The 14 **fragments** and most of the 21 failures are not defects. Specification sites embed property-level snippets without prefix declarations — a few lines showing one property in isolation. They are still useful as reference; they just need a prefix header prepended before a parser will take them. Affected: several `01-dcat-ap/3.0.1-core/example-*-series-*.ttl`, most `07-national-profiles/es-dcat-ap-es/ttl/Conventions_*.ttl`, and `01-dcat-ap/3.0.0-hvd/example-bees_wasps_dataset.ttl`.

Two are genuinely malformed upstream and worth knowing about:

- `07-national-profiles/de-dcat-ap-de/2024-02-22_UAG_Beispieldatensatz_v1.ttl` — carries a `Stand: 22.02.2024` header line outside any comment.
- `01-dcat-ap/real-world/dataset.ttl` — uses an unbound `healthdcatap:` prefix.

Several files also carry lexical values that are invalid for their declared datatype — `01-01-1981` typed as `xsd:date`, `1440.0` and `604800.0` typed as `xsd:duration`, an empty `xsd:duration`, and a URI containing a space in the Spanish set. rdflib parses these but warns. They are realistic: this is exactly the class of error a harvester meets in production, so they are left as-is rather than cleaned.

---

## Sources

| Directory | Upstream |
|---|---|
| `01-dcat-ap/3.0.1-core`, `3.0.0-hvd`, `_schemas/dcat-ap-*` | <https://github.com/SEMICeu/DCAT-AP> — `releases/3.0.1/html/examples`, `releases/3.0.0-hvd/html/examples` |
| `01-dcat-ap/real-world`, `04-healthdcat-ap` (fixtures), `12-ckan-crosswalk` | <https://github.com/ckan/ckanext-dcat> — `examples/dcat`, `examples/ckan` |
| `02-geodcat-ap`, `_schemas/geodcat-ap-*` | <https://github.com/SEMICeu/GeoDCAT-AP> — `releases/2.0.0/examples`, `releases/3.1.0/shacl` |
| `03-mobilitydcat-ap-1.1.0` | <https://github.com/mobilityDCAT-AP/mobilityDCAT-AP> — `releases/1.1.0/examples` |
| `04-healthdcat-ap` (template), `_schemas/healthdcat-ap-shacl` | <https://github.com/HealthDCAT-AP/healthdcat-ap.github.io> |
| `05-mldcat-ap-3.1.0` | <https://github.com/SEMICeu/MLDCAT-AP> — `releases/3.1.0/html/examples` |
| `06-statdcat-ap-1.0.1` | <https://github.com/SEMICeu/StatDCAT-AP> — `Release 1.0.1` |
| `07-national-profiles/de-dcat-ap-de` | <https://github.com/GovDataOfficial/DCAT-AP.de> |
| `07-national-profiles/no-dcat-ap-no` | <https://github.com/Informasjonsforvaltning/dcat-ap-no> — `examples` |
| `07-national-profiles/es-dcat-ap-es` | <https://github.com/datosgobes/DCAT-AP-ES> — `examples/ttl`, `examples/rdf` |
| `10-dcat-us-3.0/rdf`, `context`, `_schemas/dcat-us-3.0-shacl` | <https://github.com/DOI-DO/dcat-us> — **archived 2026-04-28**, still the only home of the DCAT-US SHACL, JSON-LD context and RDF examples |
| `10-dcat-us-3.0/json`, `_schemas/dcat-us-3.0-jsonschema` | <https://github.com/GSA/dcat-us> — `jsonschema/examples`, `jsonschema/definitions` (the live, maintained artifact) |
| `11-dcat-us-1.1-pod/spec-samples` | <https://github.com/project-open-data/project-open-data.github.io> — `v1.1/examples` |
| `11-dcat-us-1.1-pod/real-world` | <https://github.com/GSA/ckanext-datajson> — `ckanext/datajson/tests/datajson-samples` |

---

## Caveats

No live production records were captured — the sandbox that assembled this had no route to the portals themselves, so `real-world/` here means fixtures captured upstream from real portals rather than records pulled today. If current live records matter (a data.europa.eu Turtle record, an agency `data.json` as served this week, an ArcGIS Hub `/api/feed/dcat-us/1.1.json`), those need a fetch from a networked machine.

No DCAT-US **3.0** production record is included, because as of 2026-08-26 no agency has been confirmed to serve one. Everything in `10-dcat-us-3.0/` is specification-authored.

GeoDCAT-AP examples are from the 2.0.0 release; 3.0.0 and 3.1.0 ship shapes and a context but no example instances. The shapes for 3.1.0 are in `_schemas/`.
