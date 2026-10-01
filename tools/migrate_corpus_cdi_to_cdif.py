"""Migrate CDIF test corpus from legacy cdi: shape to current cdif: schema.

Transforms (in place):
  - rename cdi: -> cdif: for the properties that moved namespace
  - cdif:physicalDataType list -> single value (first element)
  - add the cdif: prefix to a dict @context when cdif: keys are now used
  - normalize trailing-slash conformsTo URIs (…/1.0/ -> …/1.0)

Properties that legitimately stay cdi: (DDI-CDI) are left untouched:
  the physical-layout set -- numberPattern, nullSequence, scale,
  decimalPositions, min/maxLength, isRequired, length, isFixedWidth,
  isDelimited, arrayBase, allowsDuplicates -- and the class TYPE tokens
  (cdi:InstanceVariable, cdi:RepresentedVariable, cdi:LongDataStructure, the
  component classes), plus isStructuredBy and has_DataStructureComponent.

  CORRECTED 2026-10-01. This list previously named hasIntendedDataType,
  describedUnitOfMeasure, function, platformType, source, qualifies and
  unitOfMeasureKind as properties that legitimately stay cdi:. All seven moved
  to cdif: in metadataBuildingBlocks on 2026-09-30, because each takes a CDIF
  ConceptOrTermOrString (or a bare string) where canonical DDI-CDI takes a
  ControlledVocabularyEntry -- so cdi: was promising a value type CDIF does not
  supply. They are in RENAME below now. Leaving the old wording would have been
  worse than leaving the map short: it asserted the opposite of the truth about
  seven properties, and a reader would have trusted it.
"""
import argparse
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
    # Moved 2026-09-30: each takes a CDIF ConceptOrTermOrString where canonical
    # DDI-CDI takes a ControlledVocabularyEntry.
    "cdi:hasIntendedDataType": "cdif:hasIntendedDataType",
    "cdi:typeOfStatistic": "cdif:typeOfStatistic",
    "cdi:describedUnitOfMeasure": "cdif:describedUnitOfMeasure",
    "cdi:semantic": "cdif:semantic",
    "cdi:platformType": "cdif:platformType",
    "cdi:unitOfMeasureKind": "cdif:unitOfMeasureKind",
    "cdi:function": "cdif:function",
    # Structured DDI-CDI datatypes CDIF flattens to a bare string.
    "cdi:formatPattern": "cdif:formatPattern",
    "cdi:logicalExpression": "cdif:logicalExpression",
    "cdi:regularExpression": "cdif:regularExpression",
    "cdi:purpose": "cdif:purpose",
    "cdi:source": "cdif:source",
    # schema:PropertyValue where canonical is the composite cdi:Identifier.
    "cdi:identifier": "cdif:identifier",
    # Canonical qualifies is AttributeComponent -> DataStructureComponent; CDIF
    # also uses the name for an InstanceVariable -> InstanceVariable reference
    # canonical does not define, so BOTH sites are cdif:.
    "cdi:qualifies": "cdif:qualifies",
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


# The current profile series, in one place. The version used to be hard-coded
# into the three URIs below and had gone stale.
CURRENT_PROFILE_VERSION = "1.1"


def ensure_dd_conformance(data):
    """A Data Description record should declare data_description (plus the
    core/discovery foundation) in its catalog record's dcterms:conformsTo.

    Presence is checked PER PROFILE, not per exact URI. It used to compare whole
    @id strings against a hard-coded /1.0 list, so a record already declaring
    core/1.1 did not match core/1.0 and got a second claim appended -- a claim of
    conformance to a superseded spec, sitting beside the correct one. Measured
    2026-10-01 on cdifComplete-example.json: three duplicates added to a record
    that already carried all three at 1.1, which is every record in this corpus.

    That is worse than untidy. ConformanceValidate and FrameAndValidate -v
    compare declared conformance against detected content and FAIL an over-claim,
    so this function feeds them the claims they judge: one spurious entry turns a
    passing record into a failing one, and the failure names the record rather
    than the tool that wrote it.
    """
    so = data.get("schema:subjectOf")
    if not isinstance(so, dict):
        return
    ct = so.get("dcterms:conformsTo")
    if not isinstance(ct, list):
        return
    have = set()
    for c in ct:
        if not isinstance(c, dict):
            continue
        m = re.match(r"^https?://w3id\.org/cdif/([A-Za-z_]+)/", str(c.get("@id", "")))
        if m:
            have.add(m.group(1))
    for component in ("core", "discovery", "data_description"):
        if component not in have:
            ct.append({"@id": "https://w3id.org/cdif/"
                              f"{component}/{CURRENT_PROFILE_VERSION}"})


def uses_cdif(node):
    if isinstance(node, dict):
        return any(k.startswith("cdif:") for k in node) or any(uses_cdif(v) for v in node.values())
    if isinstance(node, list):
        return any(uses_cdif(x) for x in node)
    return False


def migrate(path: Path, apply: bool = False) -> str:
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
    changed = out != orig
    # Decide BEFORE writing, and only write when something changed. This used to
    # write unconditionally and ask afterwards, so every run rewrote all 85 files
    # -- invisible in git for the 82 that round-tripped to identical bytes, but it
    # would silently reformat any file whose layout differed from
    # json.dumps(indent=2).
    if changed and apply:
        path.write_text(out, encoding="utf-8")
    return "changed" if changed else "nochange"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    # Dry run by DEFAULT. It wrote in place with no arguments at all, so merely
    # importing or probing the module from the repo root migrated the corpus.
    ap.add_argument("--apply", action="store_true",
                    help="write the migrated files; without it, only report")
    args = ap.parse_args()

    # Derived, not hard-coded. This was Path(r"C:\\GithubC\\CDIF\\validation"),
    # an absolute local path in a committed tool that worked on one machine --
    # the same class of thing generate_shacl_shapes.py was fixed for.
    root = Path(__file__).resolve().parent.parent
    files = sorted(root.glob("MetadataExamples/*.json")) + sorted(root.glob("testJSONMetadata/*.json"))
    changed = []
    for f in files:
        try:
            status = migrate(f, apply=args.apply)
        except Exception as e:
            print(f"ERROR {f.name}: {type(e).__name__}: {e}")
            continue
        if status == "changed":
            changed.append(f.name)

    verb = "Migrated" if args.apply else "Would migrate"
    print(f"{verb} {len(changed)} of {len(files)} files (others unchanged)")
    for name in changed:
        print(f"  {name}")
    if changed and not args.apply:
        print("\nDry run -- nothing written. Re-run with --apply.")


if __name__ == "__main__":
    main()
