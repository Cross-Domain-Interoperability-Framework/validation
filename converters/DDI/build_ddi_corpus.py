#!/usr/bin/env python3
"""Rebuild the DDI example corpora, and verify them.

The DDI converter has been data-driven from its SSSOM worksheets since it was
written -- `ddi_sssom_to_cdif.py` applies `mappings/ddi_mappings.json`, which
`sync_ddi_mappings.py` compiles from the TSVs. What it did not have is a
recorded way to regenerate the example outputs, or anything that checks them.
This is the DCAT corpus build (`../DCAT/build_corpus.py`) applied here.

Two source trees, each with its own `XML/` and `cdif/`:

    DDI/Examples/          Harvard Dataverse / Nesstar exports (1.2.2)
    DDICodebook/Examples/  source-agnostic Codebook (2.5)

The flavor is sniffed per file by `ddi2cdif.sniff_flavor`, which picks the
worksheet set: a 1.x element set uses the 1.2.2 worksheets, a 2.x set the 2.5
worksheets.

Verification
------------
Three checks, the same shape as the DCAT build:

  loss    every text-bearing leaf element in the source XML is accounted for:
          either its worksheet row has a CDIF target that appears in the
          record, or the row exists with **no** target -- deliberately
          unmapped, which the worksheets record explicitly. A leaf that is in
          no worksheet at all is a coverage gap, and the one thing here that
          means the mapping is incomplete rather than merely selective.

  schema  every record validates against the profiles it declares. DDI records
          carry data-description content, so DiscoveryDataDescription is the
          target rather than CoreDiscovery.

  SHACL   (--shacl, opt-in) the assembled shapes for that profile. The
          composite's own rules.shacl is not self-contained, so the bundle is
          emitted by metadataBuildingBlocks' validate_shacl.py first.

Usage:
    python build_ddi_corpus.py                # rebuild and verify
    python build_ddi_corpus.py --check        # verify what is on disk
    python build_ddi_corpus.py --shacl        # add the SHACL pass
"""

import argparse
import collections
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONVERTERS = HERE.parent
MAPPINGS = CONVERTERS / "mappings"
sys.path.insert(0, str(HERE))

import ddi2cdif as DISPATCH  # noqa: E402
import ddi_sssom_to_cdif as ENGINE  # noqa: E402

# (XML directory, cdif directory) -- one pair per example tree.
TREES = [
    (CONVERTERS / "DDI" / "Examples" / "XML",
     CONVERTERS / "DDI" / "Examples" / "cdif"),
    (CONVERTERS / "DDICodebook" / "Examples" / "XML",
     CONVERTERS / "DDICodebook" / "Examples" / "cdif"),
]

# Which composite a record is validated against is decided by what it
# DECLARES, not fixed here: a record declaring core+discovery is not failing
# for lacking data-description content it never claimed.
COMPOSITE_FOR = [
    ({"core", "discovery", "data_description", "data_structure"},
     "DiscoveryDataDescriptionStructure"),
    ({"core", "discovery", "data_description"}, "DiscoveryDataDescription"),
    ({"core", "discovery"}, "CoreDiscovery"),
]
SHACL_PROFILE = "CoreDiscovery"


def declared_profiles(record):
    """Short names of the CDIF profiles a record's catalog record claims."""
    node = dataset_node(record).get("schema:subjectOf") or {}
    claims = node.get("dcterms:conformsTo") or []
    if isinstance(claims, dict):
        claims = [claims]
    out = set()
    for claim in claims:
        uri = claim.get("@id") if isinstance(claim, dict) else claim
        if isinstance(uri, str) and "w3id.org/cdif/" in uri:
            out.add(uri.rstrip("/").rsplit("/", 2)[-2])
    return out


def composite_for(record):
    got = declared_profiles(record)
    for needed, name in COMPOSITE_FOR:
        if needed <= got:
            return name
    return "CoreDiscovery"


def local(tag):
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def leaf_paths(xml_path):
    """{dotted path: occurrences} for every element in the file carrying text.

    Matches the worksheets' own key shape (stdyDscr.citation.titlStmt.titl), so
    a source element can be looked up directly against the mapping.
    """
    counts = collections.Counter()

    def walk(node, prefix):
        for child in node:
            name = local(child.tag)
            path = "%s.%s" % (prefix, name) if prefix else name
            text = (child.text or "").strip()
            if text:
                counts[path] += 1
            walk(child, path)

    root = ET.parse(str(xml_path)).getroot()
    walk(root, "")
    return counts


def worksheet_rows(version):
    """{path without its prefix: row} for the worksheets a version applies."""
    allm = json.load(open(MAPPINGS / "ddi_mappings.json", encoding="utf-8"))
    sets = ["ddi-common-to-cdif"]
    sets.append("ddi25-to-cdif" if version == "25" else "ddi122-to-cdif")
    rows = {}
    for name in sets:
        for key, row in (allm.get(name) or {}).items():
            rows.setdefault(key.split(":", 1)[-1], row)
    return rows


def unmapped_paths(version):
    """Paths the worksheets carry with no target -- deliberately not mapped."""
    allm = json.load(open(MAPPINGS / "ddi_mappings.json", encoding="utf-8"))
    # ddi_mappings.json holds MAPPED rows only, so "in a worksheet but not in
    # the compiled map" is exactly the deliberately-unmapped set. Read it from
    # the TSVs, which keep every row.
    out = set()
    files = ["ddi-common-to-cdif.sssom.tsv"]
    files.append("ddi25-to-cdif.sssom.tsv" if version == "25"
                 else "ddi122-to-cdif.sssom.tsv")
    for name in files:
        path = MAPPINGS / name
        if not path.exists():
            continue
        lines = path.read_text(encoding="utf-8").replace("\r\n", "\n").strip("\n").split("\n")
        header = lines[0].split("\t")
        col = {c: i for i, c in enumerate(header)}
        for line in lines[1:]:
            cells = line.split("\t")
            cells += [""] * (len(header) - len(cells))
            subject = cells[col["subject_id"]].split(":", 1)[-1]
            if not cells[col.get("object_id", 0)].strip():
                out.add(subject)
    return out


def record_mentions(node, key, depth=0):
    """Is `key` used in the record -- as a property, or as a declared @type?

    A worksheet target may be either. cdi:CategoryStatistics and
    schema:DataDownload are CLASSES: the mapping says an element becomes a node
    of that type, so it appears in an @type array, never as a property name.
    Looking only at keys reported every such row as lost.
    """
    if depth > 14:
        return False
    if isinstance(node, list):
        return any(record_mentions(n, key, depth + 1) for n in node)
    if not isinstance(node, dict):
        return False
    if key in node:
        return True
    types = node.get("@type")
    if types is not None:
        values = types if isinstance(types, list) else [types]
        if key in values:
            return True
    return any(record_mentions(v, key, depth + 1)
               for k, v in node.items() if k != "@type")


def _covering_row(path, rows):
    """The worksheet row for `path`, or for the nearest ancestor that has one.

    The worksheets map at the level the DDI element carries meaning:
    dataDscr.var.qstn is a row, and its preQTxt / qstnLit children are text
    inside it rather than separate mappings. Checking only the exact path
    reported every such child as uncovered.
    """
    parts = path.split(".")
    while parts:
        row = rows.get(".".join(parts))
        if row is not None:
            return row
        parts.pop()
    return None


def check_loss(xml_path, version, record):
    """(paths with no worksheet row, paths mapped but absent from the record)."""
    rows = worksheet_rows(version)
    unmapped = unmapped_paths(version)
    uncovered, missing = collections.Counter(), collections.Counter()
    for path, n in leaf_paths(xml_path).items():
        row = _covering_row(path, rows)
        if row is None:
            parts = path.split(".")
            if not any(".".join(parts[:i + 1]) in unmapped
                       for i in range(len(parts))):
                uncovered[path] += n
            continue
        target = (row.get("object_id") or "").strip()
        if target and not record_mentions(record, target):
            missing[path + " -> " + target] += n
    return uncovered, missing


def dataset_node(document):
    """The dataset node of a converted document.

    The DDI engine emits a @graph -- study, variables, code lists and files as
    sibling nodes -- while a CDIF profile schema describes a single root
    record. Validating the wrapper reported every record as missing @id, @type
    and schema:name.
    """
    if not isinstance(document, dict):
        return document
    graph = document.get("@graph")
    if not isinstance(graph, list):
        return document
    context = document.get("@context")
    for node in graph:
        if not isinstance(node, dict):
            continue
        types = node.get("@type")
        values = types if isinstance(types, list) else [types]
        if "schema:Dataset" in values:
            out = dict(node)
            if context is not None:
                out.setdefault("@context", context)
            return out
    return document


def shacl_bundle(cache):
    mbb = (CONVERTERS / ".." / ".." / "metadataBuildingBlocks").resolve()
    emitter = mbb / "tools" / "validate_shacl.py"
    if not emitter.exists():
        return None, "metadataBuildingBlocks not beside this repo (%s)" % mbb
    if not cache.exists():
        target = mbb / "_sources/profiles/cdifCompositeProfile" / SHACL_PROFILE
        proc = subprocess.run(
            [sys.executable, str(emitter), str(target), "--emit-shapes", str(cache)],
            capture_output=True, text=True, cwd=str(mbb))
        if proc.returncode != 0 or not cache.exists():
            return None, "could not emit shapes: %s" % (proc.stderr or proc.stdout)[:200]
    import rdflib
    graph = rdflib.Graph()
    graph.parse(str(cache), format="turtle")
    return graph, None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="verify without writing")
    ap.add_argument("--shacl", action="store_true", help="also run SHACL (slow)")
    args = ap.parse_args()

    produced = []
    counts = collections.Counter()
    uncovered_all, missing_all = collections.Counter(), collections.Counter()

    for xml_dir, cdif_dir in TREES:
        if not xml_dir.is_dir():
            continue
        for xml_path in sorted(xml_dir.glob("*.xml")):
            flavor = DISPATCH.sniff_flavor(str(xml_path))
            version = DISPATCH._CODEBOOK_VERSION.get(flavor)
            if version is None:
                counts["unsupported flavor"] += 1
                print("  ! %-46s %s (not a Codebook)" % (xml_path.name, flavor))
                continue
            try:
                record = ENGINE.convert(str(xml_path), version=version)
                if isinstance(record, tuple):
                    record = record[0]
            except Exception as exc:
                counts["conversion failed"] += 1
                print("  ! %-46s %s: %s" % (xml_path.name, type(exc).__name__, exc))
                continue
            out = cdif_dir / ("cdif_%s.json" % xml_path.stem)
            if not args.check:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n",
                               encoding="utf-8")
            produced.append((out, record))
            counts[flavor] += 1
            uncovered, missing = check_loss(xml_path, version, record)
            uncovered_all.update(uncovered)
            missing_all.update(missing)

    print("records : %d" % len(produced))
    for label, n in sorted(counts.items()):
        print("  %-24s %d" % (label, n))

    status = 0
    print("\n=== loss: source elements with no worksheet row ===")
    if not uncovered_all:
        print("  none")
    else:
        status = 1
        for path, n in uncovered_all.most_common(15):
            print("  %4d  %s" % (n, path))
    print("\n=== loss: mapped elements absent from the record ===")
    if not missing_all:
        print("  none")
    else:
        status = 1
        for path, n in missing_all.most_common(15):
            print("  %4d  %s" % (n, path))

    print("")
    print("=== schema: each record against the profile it declares ===")
    try:
        from jsonschema import Draft202012Validator
        schema_path = (CONVERTERS / ".." / ".." / "metadataBuildingBlocks"
                       / "_sources" / "profiles" / "cdifCompositeProfile").resolve()
        _cache = {}

        def validator_for(name):
            if name not in _cache:
                _cache[name] = Draft202012Validator(json.loads(
                    (schema_path / name / "resolvedSchema.json").read_text(
                        encoding="utf-8")))
            return _cache[name]
    except Exception as exc:
        print("  skipped (%s)" % exc)
    else:
        bad = 0
        for out, record in produced:
            name = composite_for(record)
            errors = [e.message for e in
                      validator_for(name).iter_errors(dataset_node(record))]
            if errors:
                bad += 1
                print("  %s  (declares %s)" % (out.name, name))
                for msg in errors[:3]:
                    print("     %s" % msg[:120])
        print("  records failing: %d of %d" % (bad, len(produced)))
        if bad:
            status = 1

    if args.shacl:
        print("\n=== SHACL: %s shapes ===" % SHACL_PROFILE)
        cache = HERE / (".shacl-%s.ttl" % SHACL_PROFILE)
        shapes, why = shacl_bundle(cache)
        if shapes is None:
            print("  skipped (%s)" % why)
        else:
            import rdflib
            from pyshacl import validate
            SH = rdflib.Namespace("http://www.w3.org/ns/shacl#")
            bad, warned = 0, collections.Counter()
            for out, record in produced:
                data = rdflib.Graph()
                try:
                    data.parse(data=json.dumps(record), format="json-ld")
                    _, report, _ = validate(data, shacl_graph=shapes,
                                            advanced=True, inference="none")
                except Exception as exc:
                    print("  ! %s %s" % (out.name, exc))
                    continue
                violations = []
                for result in report.subjects(rdflib.RDF.type, SH.ValidationResult):
                    severity = str(report.value(result, SH.resultSeverity) or "")
                    message = str(report.value(result, SH.resultMessage) or "")[:110]
                    if severity.endswith("Violation"):
                        violations.append(message)
                    elif severity.endswith("Warning"):
                        warned[message] += 1
                if violations:
                    bad += 1
                    print("  %s" % out.name)
                    for msg in sorted(set(violations))[:4]:
                        print("     %s" % msg)
            print("  records with a Violation: %d of %d" % (bad, len(produced)))
            if warned:
                print("  most common warnings (advisory):")
                for msg, n in warned.most_common(4):
                    print("     %4d  %s" % (n, msg))
            if bad:
                status = 1

    return status


if __name__ == "__main__":
    sys.exit(main())
