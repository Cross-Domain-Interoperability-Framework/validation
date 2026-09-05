#!/usr/bin/env python3
"""Check the Croissant mapping tables against the converters and the corpus.

Both converters read their mappings from `converters/mappings/*.sssom.tsv`
rather than stating them in code, which moves the failure modes out of the
Python and into the table -- where they are quieter. A row with a
`subject_class` no converter passes is never selected; a row naming a
`transform` no converter defines is skipped and its property falls through to
passthrough. Neither raises. Both look exactly like the property being absent
from the source.

So the table needs its own checks. This runs three:

  transforms  every `transform` a row names is one the converter defines, and
              every row with a target can say where its value lands.

  loss        for CDIF -> Croissant, the direction that genuinely loses
              things: every CDIF property in the corpus either reaches the
              output, or has a row saying it does not. The point of the
              table's target-less `unmapped` rows is to make this checkable --
              a property in neither category is a gap in the table.

  coverage    for Croissant -> CDIF: which source properties the table claims,
              and which are passed through verbatim. Passthrough is not a
              failure -- JSON-LD is open-world -- but the list should stay
              deliberate rather than drifting.

Exit code is non-zero if any check fails.

    python check_croissant_mappings.py [-c transforms|loss|coverage]
"""

import argparse
import collections
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ConvertToCroissant as TO          # noqa: E402
import ConvertFromCroissant as FROM      # noqa: E402

# Properties each converter handles structurally rather than by a table row: a
# distribution becomes both a FileObject and a RecordSet, a variable becomes
# fields inside one. No single row can express that, and none tries to.
STRUCTURAL_CDIF = {
    "@context", "@type", "@id",
    "schema:distribution", "schema:variableMeasured",
    "cdif:hasPhysicalMapping", "cdif:hasPrimaryKey",
}
STRUCTURAL_CROISSANT = {
    "@context", "@type", "@id",
    "distribution", "recordSet", "field", "subField",
    "sc:distribution", "cr:recordSet", "cr:field",
}


def read(path):
    try:
        doc = json.loads(open(path, encoding="utf-8").read())
    except Exception:
        return None
    return doc if isinstance(doc, dict) else None


def cdif_records():
    paths = sorted(glob.glob(os.path.join(HERE, "croissantExamples", "cdif", "*.json*")))
    paths += sorted(glob.glob(os.path.join(HERE, "MLCroissantExamples", "cdif-output", "*.json*")))
    return [(p, d) for p in paths for d in [read(p)] if d]


def croissant_records():
    # Both extensions, because the corpus uses both: the Dataverse exports are
    # .croissant.jsonld and the hand-added examples are .json. Globbing only
    # .jsonld here quietly excluded two files, and an example that is never
    # read is an example that never finds anything.
    paths = sorted(glob.glob(os.path.join(HERE, "croissantExamples", "*.jsonld")))
    paths += sorted(glob.glob(os.path.join(HERE, "croissantExamples", "*.json")))
    paths += sorted(glob.glob(os.path.join(HERE, "MLCroissantExamples", "*.json")))
    paths = [p for p in paths if not os.path.basename(p).startswith("_")]
    return [(p, d) for p in paths for d in [read(p)] if d]


def check_transforms():
    """A misspelled transform is inert, not an error. Make it an error.

    Only for the rows that are actually dispatched through the table, though.
    Both tables also carry rows describing work the converter does in dedicated
    functions -- a distribution becoming a FileObject and a RecordSet, an
    archive being decomposed, a physical mapping being built -- and those name
    their handling (`distribution`, `archive`, `mapping`) rather than a
    transform in the dict. They are documentation, and demanding a defined
    transform for them was this check's own first bug.

    A row is dispatched if `rows_for` selects it at the classes the converter
    passes to `apply()`. Anything else is either structural or a row for a
    nested class the converter walks itself.
    """
    bad = 0
    for label, table, classes, structural in (
            ("cdif-to-croissant", TO.CDIF_TO_CROISSANT,
             TO.DATASET_CLASSES, STRUCTURAL_CDIF),
            ("croissant-to-cdif", FROM.CROISSANT_TO_CDIF,
             FROM.DATASET_CLASSES, STRUCTURAL_CROISSANT)):
        defined = table.transforms
        dispatched = [r for r in table.rows_for(classes)
                      if r["subject_id"] not in structural]
        for row in dispatched:
            name = (row.get("transform") or "").strip()
            if name not in defined:
                print("  %s: row %s names transform %r, which the converter "
                      "does not define -- the row is inert"
                      % (label, row["subject_id"], name))
                bad += 1
            if not table.target_key(row):
                print("  %s: row %s has a target but no key to write it under"
                      % (label, row["subject_id"]))
                bad += 1
        print("%-18s %d rows, %d dispatched at %s, %d transforms defined"
              % (label, len(table.rows), len(dispatched),
                 "/".join(classes), len(defined)))
    return bad


def check_loss():
    """CDIF -> Croissant: is every dropped property a declared drop?"""
    table = TO.CDIF_TO_CROISSANT
    known = {r["subject_id"] for r in table.rows}
    target = {}
    for row in table.rows:
        if row["object_id"]:
            target.setdefault(row["subject_id"], table.target_key(row))

    unknown = collections.Counter()
    where = {}
    carried = collections.Counter()
    declared = collections.Counter()
    records = 0
    for path, cdif in cdif_records():
        try:
            got = TO.convert_cdif_to_croissant(json.loads(json.dumps(cdif)))
        except Exception as exc:
            print("  %s: converter raised %s" % (os.path.basename(path),
                                                 type(exc).__name__))
            unknown["<converter error>"] += 1
            continue
        cr = got[0] if isinstance(got, tuple) else got
        records += 1
        for key in cdif:
            if key.startswith("@") or key in STRUCTURAL_CDIF:
                continue
            if key not in known:
                unknown[key] += 1
                where.setdefault(key, os.path.basename(path))
            elif target.get(key) and target[key] in cr:
                carried[key] += 1
            else:
                declared[key] += 1

    print("records             : %d" % records)
    print("carried over        : %d distinct" % len(carried))
    print("knowingly lost      : %d distinct" % len(declared))
    if not unknown:
        print("unknown to the table: none")
        return 0
    print("unknown to the table:")
    for key, n in unknown.most_common(20):
        print("  %4d  %-38s e.g. %s" % (n, key, where.get(key, "")))
    return len(unknown)


def check_coverage():
    """Croissant -> CDIF: is every source property accounted for?"""
    table = FROM.CROISSANT_TO_CDIF
    # Two different things, and conflating them makes the check lie: `claimed`
    # is the rows that map somewhere, `known` also counts the rows that exist
    # to say a property is deliberately NOT mapped. Only a property in neither
    # is a gap.
    claimed = table.claimed(FROM.DATASET_CLASSES)
    known = {r["subject_id"] for r in table.rows}
    seen = collections.Counter()
    declared = collections.Counter()
    unclaimed = collections.Counter()
    records = 0
    for path, doc in croissant_records():
        node = doc
        if "@graph" in doc:
            graph = doc["@graph"]
            node = graph[0] if isinstance(graph, list) and graph else doc
        if not isinstance(node, dict):
            continue
        records += 1
        for key in node:
            if key.startswith("@") or key in STRUCTURAL_CROISSANT:
                continue
            curie = table.resolve(FROM.croissant_curie(key, doc.get("@context")))
            seen[curie] += 1
            if curie in claimed:
                continue
            (declared if curie in known else unclaimed)[curie] += 1
    print("records             : %d" % records)
    print("properties seen     : %d distinct" % len(seen))
    print("mapped by the table : %d distinct" % (len(seen) - len(declared) - len(unclaimed)))
    print("declared unmapped   : %d distinct (kept verbatim by passthrough)" % len(declared))
    for key, n in declared.most_common(15):
        print("  %4d  %s" % (n, key))
    if not unclaimed:
        print("unknown to the table: none")
        return 0
    print("unknown to the table:")
    for key, n in unclaimed.most_common(15):
        print("  %4d  %s" % (n, key))
    return len(unclaimed)


# --- the class census -----------------------------------------------------
#
# `coverage` reads only the root dataset node, which is where the converter
# dispatches the table. Most of the table is not about that node: 79 of its
# 104 rows describe FileObjects, RecordSets, Fields and Sources. Those rows
# are never dispatched, so nothing exercises them, so nothing notices when
# their subject_class is wrong -- and subject_class is the column a reader
# trusts to say where a property lives.

# An untyped node under this property is this class. Croissant's examples
# routinely omit @type inside source/extract/transform.
IMPLIED_CLASS = {
    "source": "cr:Source", "cr:source": "cr:Source",
    "extract": "cr:Extract", "cr:extract": "cr:Extract",
    "transform": "cr:Transform", "cr:transform": "cr:Transform",
    "references": "cr:Source", "cr:references": "cr:Source",
    "field": "cr:Field", "subField": "cr:Field",
    "distribution": "cr:FileObject", "recordSet": "cr:RecordSet",
}

# Values under these keys are inline data ROWS keyed by field @id, not
# metadata. Walking into them invents properties out of the data.
DATA_KEYS = {"data", "cr:data", "examples", "cr:examples"}

# Non-standard extension bags whose keys are not vocabulary at all. This one
# holds BeautifulSoup scraping expressions. Named explicitly rather than
# guessed at, so adding to this list stays a deliberate act.
NOT_VOCABULARY = {"bs4ExtractionPattern"}

_SC_CLASSES = ("Dataset", "Person", "Organization", "DataCatalog",
               "CreativeWork", "MonetaryGrant", "SoftwareApplication",
               "Place", "Event", "Thing", "DefinedTerm", "Role",
               "PropertyValue", "ContactPoint")
_CR_CLASSES = ("FileObject", "FileSet", "RecordSet", "Field", "Source",
               "Extract", "Transform")


def norm_class(name):
    """One spelling per class.

    The corpus types the same class three ways -- `Person`, `sc:Person`, and
    `https://schema.org/Person` -- and comparing those to the table verbatim
    reports differences that are only punctuation.
    """
    if not name:
        return name
    short = name.split(":")[-1].rsplit("/", 1)[-1].rsplit("#", 1)[-1]
    if short in _SC_CLASSES:
        return "sc:" + short
    if short in _CR_CLASSES:
        return "cr:" + short
    return name


def _node_class(node, parent_prop):
    got = node.get("@type")
    if isinstance(got, list):
        got = got[0] if got else None
    if isinstance(got, str) and got:
        return norm_class(got)
    return IMPLIED_CLASS.get(parent_prop,
                             "(untyped under %s)" % parent_prop
                             if parent_prop else "(untyped root)")


def _walk(node, context, table, parent_prop=None, out=None):
    """Every (class, property) pair in the document, at every depth."""
    if out is None:
        out = []
    if isinstance(node, list):
        for item in node:
            _walk(item, context, table, parent_prop, out)
        return out
    if not isinstance(node, dict):
        return out
    cls = _node_class(node, parent_prop)
    for key, value in node.items():
        if key.startswith("@"):
            continue
        curie = table.resolve(FROM.croissant_curie(key, context))
        out.append((cls, curie))
        if key in DATA_KEYS or curie in ("cr:data", "cr:examples"):
            continue
        if key in NOT_VOCABULARY or key.split(":")[-1] in NOT_VOCABULARY:
            continue
        _walk(value, context, table, key, out)
    return out


def check_classes():
    """Does the table cover the corpus at every depth, on the right classes?

    Two findings, and conflating them hides the worse one. A property absent
    from the table is a gap anyone can see. A property present but filed under
    a class it never occurs on LOOKS covered -- it is right there in the file
    -- and is inert. Only a per-class census tells them apart.
    """
    table = FROM.CROISSANT_TO_CDIF
    by_class = collections.defaultdict(set)
    everywhere = set()
    for row in table.rows:
        everywhere.add(row["subject_id"])
        by_class[norm_class(row.get("subject_class") or "")].add(row["subject_id"])

    absent = collections.Counter()
    misfiled = collections.Counter()
    where = {}
    pairs = 0
    records = 0
    for path, doc in croissant_records():
        records += 1
        context = doc.get("@context")
        root = doc
        if "@graph" in doc and isinstance(doc["@graph"], list) and doc["@graph"]:
            root = doc["@graph"][0]
        for cls, curie in _walk(root, context, table):
            pairs += 1
            if curie not in everywhere:
                absent[curie] += 1
                where.setdefault(curie, os.path.basename(path))
            elif curie not in by_class.get(cls, set()):
                misfiled[(cls, curie)] += 1
                where.setdefault((cls, curie), os.path.basename(path))

    print("source files        : %d" % records)
    print("class/property pairs: %d" % pairs)
    print("absent from table   : %d distinct" % len(absent))
    for curie, n in absent.most_common(25):
        print("  %4d  %-34s e.g. %s" % (n, curie, where.get(curie, "")))
    print("filed under a class it never occurs on: %d" % len(misfiled))
    for (cls, curie), n in misfiled.most_common(25):
        listed = sorted(c for c, s in by_class.items() if curie in s and c)
        print("  %4d  %-24s on %-20s table says: %s"
              % (n, curie, cls, ", ".join(listed) or "(no class)"))
    return len(absent) + len(misfiled)


CHECKS = {"transforms": check_transforms, "loss": check_loss,
          "coverage": check_coverage, "classes": check_classes}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-c", "--check", choices=sorted(CHECKS),
                    help="run one check instead of all")
    args = ap.parse_args()
    names = ([args.check] if args.check
             else ["transforms", "loss", "coverage", "classes"])
    failures = 0
    for name in names:
        print("\n=== %s ===" % name)
        failures += CHECKS[name]()
    print("\n%s" % ("FAILED (%d)" % failures if failures else "all checks pass"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
