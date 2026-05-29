"""Migrate CDIF test corpus from legacy cdi: shape to current cdif: schema.

Transforms (in place):
  - rename cdi: -> cdif: for the properties that moved namespace
  - cdif:physicalDataType list -> single value (first element)
  - add the cdif: prefix to a dict @context when cdif: keys are now used
  - normalize trailing-slash conformsTo URIs (…/1.0/ -> …/1.0)

Properties that legitimately stay cdi: (DDI-CDI) are left untouched:
  InstanceVariable, hasIntendedDataType, describedUnitOfMeasure, function,
  platformType, source, qualifies, numberPattern, nullSequence, scale,
  decimalPositions, min/maxLength, isRequired, length, isFixedWidth,
  isDelimited, arrayBase, allowsDuplicates, unitOfMeasureKind, and the
  DataStructure types (isStructuredBy, components, RepresentedVariable, …).
"""
import json
import re
import sys
from pathlib import Path

RENAME = {
    "cdi:physicalDataType": "cdif:physicalDataType",
    "cdi:name": "cdif:name",
    "cdi:displayLabel": "cdif:displayLabel",
    "cdi:definition": "cdif:definition",
    "cdi:descriptiveText": "cdif:descriptiveText",
    "cdi:role": "cdif:role",
    "cdi:index": "cdif:index",
    "cdi:hasIndex": "cdif:index",
    "cdi:formats_InstanceVariable": "cdif:formats_InstanceVariable",
    "cdi:isDefinedBy_InstanceVariable": "cdif:formats_InstanceVariable",
    "cdi:uses": "cdif:uses",
    "cdi:simpleUnitOfMeasure": "cdif:simpleUnitOfMeasure",
    "cdi:format": "cdif:format",
}


def rename_keys(node):
    """Recursively rename dict keys per RENAME; collapse cdif:physicalDataType
    lists to a single value."""
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            nk = RENAME.get(k, k)
            nv = rename_keys(v)
            if nk == "cdif:physicalDataType" and isinstance(nv, list):
                nv = nv[0] if nv else nv
            out[nk] = nv
        return out
    if isinstance(node, list):
        return [rename_keys(x) for x in node]
    return node


def normalize_conformsto(node):
    """Strip a trailing slash from w3id.org/cdif/*/1.0/ URIs (string values)."""
    if isinstance(node, dict):
        return {k: normalize_conformsto(v) for k, v in node.items()}
    if isinstance(node, list):
        return [normalize_conformsto(x) for x in node]
    if isinstance(node, str):
        m = re.match(r"^(https?://w3id\.org/cdif/[A-Za-z_]+/\d+\.\d+)/$", node)
        if m:
            return m.group(1)
    return node


def is_datadescription(data):
    """True when a variableMeasured item is typed cdi:InstanceVariable (i.e. the
    record carries Data Description content, not just discovery PropertyValues)."""
    vm = data.get("schema:variableMeasured")
    if not isinstance(vm, list):
        return False
    return any(isinstance(v, dict) and "cdi:InstanceVariable" in str(v.get("@type", ""))
               for v in vm)


def ensure_dd_conformance(data):
    """A Data Description record must declare data_description/1.0 (plus the
    core/discovery foundation) in its catalog record's dcterms:conformsTo."""
    so = data.get("schema:subjectOf")
    if not isinstance(so, dict):
        return
    ct = so.get("dcterms:conformsTo")
    if not isinstance(ct, list):
        return
    have = {c.get("@id") for c in ct if isinstance(c, dict)}
    for uri in ("https://w3id.org/cdif/core/1.0",
                "https://w3id.org/cdif/discovery/1.0",
                "https://w3id.org/cdif/data_description/1.0"):
        if uri not in have:
            ct.append({"@id": uri})


def uses_cdif(node):
    if isinstance(node, dict):
        return any(k.startswith("cdif:") for k in node) or any(uses_cdif(v) for v in node.values())
    if isinstance(node, list):
        return any(uses_cdif(x) for x in node)
    return False


def migrate(path: Path) -> str:
    orig = path.read_text(encoding="utf-8")
    data = json.loads(orig)
    data = rename_keys(data)
    data = normalize_conformsto(data)
    if is_datadescription(data):
        ensure_dd_conformance(data)
    # ensure the cdif: prefix is declared wherever cdif: keys are now used
    ctx = data.get("@context")
    CDIF_IRI = "https://w3id.org/cdif/"
    if uses_cdif(data):
        if isinstance(ctx, dict):
            if "cdif" not in ctx:
                new_ctx = {}
                for k, v in ctx.items():
                    new_ctx[k] = v
                    if k == "cdi":
                        new_ctx["cdif"] = CDIF_IRI
                if "cdif" not in new_ctx:
                    new_ctx["cdif"] = CDIF_IRI
                data["@context"] = new_ctx
        elif isinstance(ctx, list):
            # list @context (e.g. a remote context URL + an inline prefix dict).
            # Add cdif: to the first inline dict element, or append one.
            dict_el = next((e for e in ctx if isinstance(e, dict)), None)
            if dict_el is None:
                ctx.append({"cdif": CDIF_IRI})
            elif "cdif" not in dict_el:
                dict_el["cdif"] = CDIF_IRI
    out = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    path.write_text(out, encoding="utf-8")
    changed = out != orig
    return "changed" if changed else "nochange"


def main():
    root = Path(r"C:\GithubC\CDIF\validation")
    files = sorted(root.glob("MetadataExamples/*.json")) + sorted(root.glob("testJSONMetadata/*.json"))
    n_changed = 0
    for f in files:
        try:
            status = migrate(f)
        except Exception as e:
            print(f"ERROR {f.name}: {type(e).__name__}: {e}")
            continue
        if status == "changed":
            n_changed += 1
    print(f"Migrated {n_changed} of {len(files)} files (others unchanged)")


if __name__ == "__main__":
    main()
