# CDIF Test JSON-LD Metadata

77 CDIF metadata records in JSON-LD format, validated against `CDIFCompleteSchema.json`.

## Source

Copied from [amds-ldeo/metadata](https://github.com/amds-ldeo/metadata) repository, `schemaWork` branch, `testJSONMetadata/` directory.

These files must be kept in sync with that source when changes are made.

## Usage

These files serve as working examples for:

- CDIF schema validation testing
- GeoNetwork CDIF harvester development (via sitemap-based Simple URL Harvester)
- CDIF-to-ISO 19115-3 crosswalk verification

## File naming

Files are named `metadata_10.60707-XXXX-XXXX.json` where the suffix corresponds to the DOI identifier of the dataset (e.g., `10.60707/08fx-rj13`).

## Validation

All files pass validation against `CDIFCompleteSchema.json` (JSON Schema Draft 2020-12).

To validate:

```bash
python -c "
import json, os
from jsonschema import Draft202012Validator

with open('../CDIFCompleteSchema.json') as f:
    schema = json.load(f)
validator = Draft202012Validator(schema)

for fn in sorted(os.listdir('.')):
    if not fn.endswith('.json'): continue
    with open(fn) as f:
        data = json.load(f)
    errors = list(validator.iter_errors(data))
    status = 'FAIL' if errors else 'OK'
    print(f'{status} {fn}')
"
```
