# DCAT-US 1.1 / Project Open Data — how `dcat:Dataset` is asserted here

These files passed the "must contain at least one `dcat:Dataset`, `dcat:DataService` or `dcat:DatasetSeries` node" filter, but they do it in two different ways. Seven of them carry **no `@type` on their dataset entries at all**, so a naive type scan will report zero DCAT nodes and wrongly discard them.

## Why the seven have no explicit type

Project Open Data v1.1 defines `data.json` as a **JSON document with an external JSON-LD context**, not as inline-typed JSON-LD. The catalog declares

```json
"conformsTo": "https://project-open-data.cio.gov/v1.1/schema"
```

and the POD context at `https://project-open-data.cio.gov/v1.1/schema/catalog.jsonld` maps the top-level `dataset` array to `dcat:dataset`, whose range coerces each member to `dcat:Dataset`. The typing lives in the context, so it never appears in the instance document. `distribution[]` members are typed `dcat:Distribution` by the same mechanism.

The `@type` keys that *do* appear in POD files (`"@type": "dcat:Dataset"`, `"@type": "vcard:Contact"`) are **optional "expanded" fields** in the v1.1 schema. Some publishers emit them, most do not — which is exactly the split visible in this folder.

**Practical consequence for a converter:** you cannot detect DCAT class membership in POD `data.json` by inspecting the document alone. You must either expand against the POD context, or apply the structural rule "a member of the catalog-level `dataset` array is a `dcat:Dataset`". Anything that only pattern-matches on `@type` will silently drop the majority of real agency catalogs.

## Which files use which style

**Typed by context only — no `@type` in the document** (matched by the structural `dataset[]` rule):

| File | Datasets |
|---|---:|
| `spec-samples/catalog-sample.json` | 3 |
| `real-world/usda.gov.data.json` | 3 |
| `real-world/missing-identifier-title.data.json` | 3 |
| `real-world/large-spatial.data.json` | 1 |
| `real-world/null-spatial.data.json` | 1 |
| `real-world/numerical-title.data.json` | 1 |
| `real-world/reserved-title.data.json` | 1 |

**Carry an inline `"@type": "dcat:Dataset"`** (matched by a plain type scan):

| File | Datasets |
|---|---:|
| `spec-samples/catalog-sample-extended.json` | 3 |
| `real-world/collection-2-parent-4-children.data.json` | 6 |
| `real-world/arm.data.json` | 3 |
| `real-world/collection-1-parent-2-children.data.json` | 3 |
| `real-world/geospatial.data.json` | 2 |
| `real-world/many-resources.data.json` | 1 |
| `real-world/missing-catalog.data.json` | 1 |
| `real-world/missing-dataset-fields.data.json` | 1 |
| `real-world/ny.data.json` | 1 |

Both groups are unmodified as captured upstream. Several in `real-world/` are deliberately malformed harvester test cases — missing identifiers, numerical titles, null spatial values, a reserved title, a missing catalog wrapper.

## Contrast with DCAT-US 3.0

DCAT-US 3.0 (`10-dcat-us-3.0/`) reverses this: its JSON examples carry `"@type": "Dataset"` inline, and its published JSON-LD context is explicitly **non-normative** — the spec says other contexts may be used for a conformant exchange. So for v3.0 the inline type is the reliable signal, and for v1.1 it is the structure. A converter handling both needs both paths.
