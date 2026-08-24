# DCAT to CDIF Conversion

Tools for converting [DCAT](https://www.w3.org/TR/vocab-dcat-3/) metadata to CDIF-conformant [schema.org](http://schema.org/) JSON-LD.

## Background

Many institutional and government data catalogs publish metadata using the W3C DCAT vocabulary (often serialized as JSON-LD with Dublin Core and FOAF terms). CDIF uses schema.org as its primary vocabulary. The property mappings between DCAT and schema.org are documented in the [CDIF DCAT implementation guide](https://cross-domain-interoperability-framework.github.io/cdifbook/metadata/dcat.html), which draws on the W3C DXWG group's alignment work.

This converter enables DCAT catalog records to be consumed by CDIF-aware tools by translating DCAT/Dublin Core properties to their schema.org equivalents while preserving any unmapped properties (open-world assumption).

## Property Mapping

| DCAT / Dublin Core | Schema.org | Notes |
|---|---|---|
| `dcterms:title` | `schema:name` | Required |
| `dcterms:description` | `schema:description` | |
| `dcterms:identifier` | `schema:identifier` | |
| `dcterms:modified` | `schema:dateModified` | Falls back to `dcterms:issued` |
| `dcterms:issued` | `schema:datePublished` | |
| `dcterms:license` | `schema:license` | |
| `dcterms:accessRights` | `schema:conditionsOfAccess` | |
| `dcterms:creator` | `schema:creator` | FOAF agents → schema:Person/Organization |
| `dcterms:publisher` | `schema:publisher` | |
| `dcterms:spatial` | `schema:spatialCoverage` | Bounding box and named places |
| `dcterms:temporal` | `schema:temporalCoverage` | Start/end dates → ISO 8601 interval |
| `dcat:keyword` | `schema:keywords` | |
| `dcat:landingPage` | `schema:url` | |
| `dcat:Distribution` | `schema:DataDownload` | `dcat:downloadURL`/`accessURL` → `schema:contentUrl` |
| `dcat:mediaType` | `schema:encodingFormat` | |
| `dcat:version` | `schema:version` | |
| `prov:qualifiedAttribution` | `schema:contributor` | Agent + role extracted |
| `dcat:contactPoint` (vcard) | `schema:provider` | Only if vcard has a name |

Properties not in this mapping are passed through to the output unchanged.

## Usage

### List datasets in a DCAT catalog

```bash
python DCAT/dcat_to_cdif.py catalog.jsonld --list
```

### Convert all datasets

```bash
python DCAT/dcat_to_cdif.py catalog.jsonld \
  --output ./examples \
  --catalog-name "My Data Catalog" \
  --catalog-url "https://example.org/catalog"
```

### Convert specific records by index

```bash
python DCAT/dcat_to_cdif.py catalog.jsonld \
  --output ./examples \
  --select 0,3,5,10
```

### Convert and validate against CDIF schema

```bash
python DCAT/dcat_to_cdif.py catalog.jsonld \
  --output ./examples \
  --validate --verbose
```

### Example: PSDI Resource Catalogue

The [PSDI](https://www.psdi.ac.uk/) (Physical Sciences Data Infrastructure) publishes a DCAT catalog at `https://metadata.psdi.ac.uk/psdi-dcat.jsonld` with 41 dataset records describing materials science databases (Cambridge Structural Database, AFLOW, Chemotion, OPTIMADE providers, etc.).

```bash
# Download the catalog
curl -o psdi-dcat.jsonld https://metadata.psdi.ac.uk/psdi-dcat.jsonld

# List available datasets
python DCAT/dcat_to_cdif.py psdi-dcat.jsonld --list

# Convert 5 records to CDIF Core
python DCAT/dcat_to_cdif.py psdi-dcat.jsonld \
  --output ./examples \
  --select 0,1,3,5,10 \
  --catalog-name "PSDI Resource Catalogue" \
  --catalog-url "https://metadata.psdi.ac.uk/" \
  --validate
```

## Output Format

Each converted record is a CDIF-conformant JSON-LD file with:

- `@context` declaring `schema`, `dcterms`, `dcat`, `prov` prefixes
- `@type: ["schema:Dataset"]`
- `schema:` prefixed property names for all mapped properties
- `schema:subjectOf` with `dcat:CatalogRecord`, `dcterms:conformsTo` (core/1.0 and/or discovery/1.0), and documentation of all mappings applied
- Unmapped DCAT properties preserved with their original prefixes

The profile (`core` or `discovery`) is auto-detected based on whether the record has spatial or temporal coverage. Records with `dcterms:spatial` or `dcterms:temporal` get `discovery/1.0` conformance; others get `core/1.0` only.

## Requirements

- Python 3.8+
- `pyyaml` (for catalog parsing)
- `jsonschema` (optional, for `--validate`)

## Known Limitations

- `dcat:contactPoint` with vcard properties is mapped to `schema:provider` (closest schema.org equivalent); the vcard structure is simplified to name + email
- Spatial coverage conversion supports `dcat:bbox` (WKT) and named places but not all geometry types
- Temporal coverage assumes `dcat:startDate`/`dcat:endDate` pattern; complex temporal extents may need manual review
- Nested catalog structures (catalog-of-catalogs) are traversed recursively to find all `dcat:Dataset` nodes at any depth
