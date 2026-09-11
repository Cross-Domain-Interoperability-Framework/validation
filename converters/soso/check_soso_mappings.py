#!/usr/bin/env python3
"""Check the SOSO mapping tables against the converters and the example corpus.

SOSO is the one converter pair that does NOT read its tables: ConvertToSOSO and
ConvertFromSOSO are procedural (CDIF Discovery and SOSO are both schema.org
profiles, so the conversion is a structural alignment -- strip / add the
`schema:` prefix, drop / add the CDIF catalog record -- with nothing term-to-term
to drive from a table). So `cdif-to-soso.sssom.tsv` and `soso-to-cdif.sssom.tsv`
are documentation of what the code does, and documentation drifts from code
silently. This makes the drift loud.

Two checks:

  shape     the tables are the identity mappings they claim to be. Every
            cdif-to-soso row maps schema:X to the bare X that SOSO serializes
            via @vocab (X at $.X); every soso-to-cdif row maps a bare SOSO term
            to schema:X at $.schema:X. A typo in a property name, prefix or path
            would otherwise sit in the table looking authoritative.

  coverage  over the example corpus, the mappings the tables assert are the ones
            the converters actually make, and every dataset-level property a
            converter carries is either in its table or reported as an untabled
            passthrough. Passthrough is not a failure -- both converters are
            open-world -- but the list should stay deliberate rather than drift.

The corpus is soso/examples/*.json (SOSO records) plus, for the CDIF -> SOSO
direction, the CDIF records ConvertFromSOSO produces from them: round-tripping
the SOSO examples is what gives a CDIF Discovery record shaped exactly as this
converter pair produces, with no separate fixture to keep in step.

Exit code is non-zero if any check fails.

    python check_soso_mappings.py [-c shape|coverage]
"""

import argparse
import collections
import csv
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import ConvertToSOSO as TO            # noqa: E402
import ConvertFromSOSO as FROM        # noqa: E402

MAPPINGS = os.path.join(HERE, "..", "mappings")

# Keys neither table maps: JSON-LD keywords, and -- for the CDIF side -- the
# catalog record the converters add on the way in and drop on the way out.
STRUCTURAL = {"@context", "@type", "@id"}
CDIF_ADDED = {"schema:subjectOf"}     # the CDIF catalog record ConvertFromSOSO adds


def read_table(name):
    path = os.path.join(MAPPINGS, name + ".sssom.tsv")
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    return [r for r in rows if (r.get("subject_id") or "").strip()]


def soso_records():
    """The SOSO example records (root or @graph Dataset)."""
    out = []
    for p in sorted(glob.glob(os.path.join(HERE, "examples", "*.json"))):
        try:
            doc = json.load(open(p, encoding="utf-8"))
        except Exception:
            continue
        if isinstance(doc, dict):
            out.append((os.path.basename(p), doc))
    return out


def bare(curie):
    """schema:X -> X (SOSO serializes schema.org bare via @vocab); other
    prefixes (dqv:, dcterms:, ...) are kept, as the converter keeps them."""
    return curie[len("schema:"):] if curie.startswith("schema:") else curie


def dataset_keys(doc):
    """Top-level property keys of a converted record (no keywords)."""
    return [k for k in doc if not k.startswith("@")]


def check_shape():
    """The tables are the identity mappings they document."""
    def path_ok(path, prop):
        # $.prop, or $.prop[*] for an array target -- both are valid SSSOM paths.
        return path in ("$." + prop, "$." + prop + "[*]")

    bad = 0
    for row in read_table("cdif-to-soso"):
        s, o, path = row["subject_id"], row["object_id"], row["object_json_path"]
        pred = row["predicate_id"]
        if s != o:
            print("  cdif-to-soso: %s -> %s is not identity" % (s, o)); bad += 1
        if not path_ok(path, bare(o)):
            print("  cdif-to-soso: %s path %r, expected $.%s[*]?" % (s, path, bare(o)))
            bad += 1
        if pred != "skos:exactMatch":
            print("  cdif-to-soso: %s predicate %r (identity rows are exactMatch)"
                  % (s, pred)); bad += 1
    for row in read_table("soso-to-cdif"):
        s, o, path = row["subject_id"], row["object_id"], row["object_json_path"]
        pred = row["predicate_id"]
        if not path_ok(path, o):
            print("  soso-to-cdif: %s path %r, expected $.%s[*]?" % (s, path, o))
            bad += 1
        if pred not in ("skos:exactMatch", "skos:closeMatch"):
            print("  soso-to-cdif: %s predicate %r" % (s, pred)); bad += 1
        # closeMatch rows (author->creator, datePublished->dateModified) are
        # deliberately not identity; exactMatch rows are.
        if pred == "skos:exactMatch" and s != o:
            print("  soso-to-cdif: %s -> %s is exactMatch but not identity"
                  % (s, o)); bad += 1
    print("cdif-to-soso: %d rows;  soso-to-cdif: %d rows"
          % (len(read_table("cdif-to-soso")), len(read_table("soso-to-cdif"))))
    return bad


def check_coverage():
    """Per example: the table mappings are realized, and carried-but-untabled
    properties are reported."""
    to_rows = read_table("cdif-to-soso")
    from_rows = read_table("soso-to-cdif")
    # bare SOSO term -> the schema: property it should become, for exactMatch rows
    from_target = {bare(r["subject_id"]): r["object_id"]
                   for r in from_rows if r["predicate_id"] == "skos:exactMatch"}
    to_bare = {bare(r["object_id"]) for r in to_rows}          # bare terms the table maps
    from_obj = {r["object_id"] for r in from_rows}             # schema: terms the table maps
    keep = set(TO.KEEP_NAMESPACES)

    bad = 0
    untabled_from = collections.Counter()
    untabled_to = collections.Counter()
    records = 0
    for name, soso in soso_records():
        src_node, _ = FROM._pick_dataset(soso)
        src_keys = {k for k in src_node if not k.startswith("@")}
        cdif, _ = FROM.convert_soso_to_cdif(soso, detect=False)
        records += 1

        # SOSO -> CDIF: every bare SOSO term the table maps and the source has
        # must appear, prefixed, in the CDIF record.
        for term, target in from_target.items():
            if term in src_keys and target not in cdif:
                print("  %s: soso-to-cdif maps %s -> %s, but %s is absent from the"
                      " CDIF output" % (name, term, target, target)); bad += 1
        # schema: properties carried but in no table row (and not the added record)
        for k in dataset_keys(cdif):
            if k.startswith("schema:") and k not in from_obj and k not in CDIF_ADDED:
                untabled_from[k] += 1

        # CDIF -> SOSO (round-trip): every schema: property the table maps and
        # the CDIF record has must appear, bare, in the SOSO record.
        soso_out, _ = TO.convert_cdif_to_soso(cdif)
        for row in to_rows:
            s = row["subject_id"]
            if s in cdif and bare(s) not in soso_out:
                print("  %s: cdif-to-soso maps %s -> %s, but %s is absent from the"
                      " SOSO output" % (name, s, bare(s), bare(s))); bad += 1
        for k in dataset_keys(soso_out):
            prefix = k.split(":", 1)[0] if ":" in k else ""
            if k not in to_bare and prefix not in keep:
                untabled_to[k] += 1

    print("records                 : %d" % records)
    print("soso-to-cdif untabled   : %s"
          % (", ".join("%s(%d)" % (k, n) for k, n in untabled_from.most_common())
             or "none"))
    print("cdif-to-soso untabled   : %s"
          % (", ".join("%s(%d)" % (k, n) for k, n in untabled_to.most_common())
             or "none"))
    return bad


CHECKS = {"shape": check_shape, "coverage": check_coverage}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-c", "--check", choices=sorted(CHECKS),
                    help="run only this check (default: all)")
    args = ap.parse_args()

    names = [args.check] if args.check else ["shape", "coverage"]
    failures = 0
    for name in names:
        print("== %s ==" % name)
        failures += CHECKS[name]()
        print()
    if failures:
        print("FAIL: %d problem(s)" % failures)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
