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
    paths = sorted(glob.glob(os.path.join(HERE, "croissantExamples", "*.jsonld")))
    paths += sorted(glob.glob(os.path.join(HERE, "MLCroissantExamples", "*.json")))
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


CHECKS = {"transforms": check_transforms, "loss": check_loss,
          "coverage": check_coverage}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-c", "--check", choices=sorted(CHECKS),
                    help="run one check instead of all")
    args = ap.parse_args()
    names = [args.check] if args.check else ["transforms", "loss", "coverage"]
    failures = 0
    for name in names:
        print("\n=== %s ===" % name)
        failures += CHECKS[name]()
    print("\n%s" % ("FAILED (%d)" % failures if failures else "all checks pass"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
