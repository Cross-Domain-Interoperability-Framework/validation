#!/usr/bin/env python3
"""Process the hand-edited DDI SSSOM worksheets into canonical form + a derived MAP.

This is the one command to run after editing any of the DDI *.sssom.tsv files
(in a text editor -- NOT a spreadsheet). It makes the TSVs the source of truth
and everything else derived. Per file it:

  1. undoes spreadsheet round-trip damage  (CRLF->LF, trailing-tab padding,
     CSV quote-wrapping, ragged rows -> exactly the header's column count)
  2. enforces the canonical column order
  3. regenerates the `# curie_map:` block from the prefixes actually used
     (subject_id / predicate_id / object_id / mapping_justification), so a new
     target prefix never has to be added to the header by hand
  4. re-checks the file (flags non-SKOS predicates, object_ids that aren't a
     single CURIE, prefixes with no known IRI, and -- with --xsd -- any schema
     field missing from the worksheet or any subject not in the schema)

and finally emits `ddi_mappings.json` -- the machine-readable MAP (mapped rows
only) that the generator / converters consume instead of a hand-kept dict.

The completeness check walks both DDI Codebook XSDs (auto-found in
../DDICodebook, or given with --xsd), partitions their text-bearing leaf
elements into the sets each worksheet owns -- common = 2.5 n 1.2.2, ddi25 = only
2.5, ddi122 = only 1.2.2 -- and reports any schema field missing from a
worksheet and any subject that is not in the schema (a likely typo).

Usage:
    python sync_ddi_mappings.py                 # process + completeness + write JSON
    python sync_ddi_mappings.py --check         # report only, no writes
    python sync_ddi_mappings.py --add-missing   # append any missing schema field as a blank row
    python sync_ddi_mappings.py --no-xsd        # skip the schema completeness check
    python sync_ddi_mappings.py --xsd ddi25=/path/codebook.xsd --xsd ddi122=/path/Version1-2-2.xsd
"""
import csv, io, json, os, sys, glob, re

HERE = os.path.dirname(os.path.abspath(__file__))
CANON = ["subject_id", "subject_label", "comment", "predicate_id",
         "object_id", "object_label", "object_json_path", "mapping_justification"]
SKOS = {"skos:exactMatch", "skos:closeMatch", "skos:narrowMatch",
        "skos:broadMatch", "skos:relatedMatch"}
FILES = ["ddi-common-to-cdif", "ddi25-to-cdif", "ddi122-to-cdif"]

# canonical prefix -> IRI registry (superset; only used prefixes are emitted)
PREFIXES = {
 "schema": "http://schema.org/",
 "cdi": "http://ddialliance.org/Specification/DDI-CDI/1.0/RDF/",
 "cdif": "https://w3id.org/cdif/",
 "cdifq": "http://crossdomaininteroperability.org/cdifq/",
 "dcterms": "http://purl.org/dc/terms/",
 "dqv": "http://www.w3.org/ns/dqv#",
 "prov": "http://www.w3.org/ns/prov#",
 "geo": "http://www.opengis.net/ont/geosparql#",
 "skos": "http://www.w3.org/2004/02/skos/core#",
 "semapv": "https://w3id.org/semapv/vocab/",
 "ddicb": "https://ddialliance.org/Specification/DDI-Codebook/element/",
 "ddi": "https://ddialliance.org/Specification/DDI-Codebook/2.5/element/",
 "ddi122": "https://ddialliance.org/Specification/DDI-Codebook/1.2.2/element/",
}
CURIE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*:")


def unquote_split(line):
    return next(csv.reader(io.StringIO(line), delimiter="\t"))


def read_text(path):
    """Decode a TSV that may have come back from Excel in any of its save
    formats: UTF-16 ('Unicode Text'), UTF-8 (with or without BOM), or the
    Windows-1252 codepage ('Text (Tab delimited)'). Output is always written
    back as UTF-8/LF, so one round-trip converges the file to UTF-8."""
    raw = open(path, "rb").read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    if raw[:3] == b"\xef\xbb\xbf":
        return raw[3:].decode("utf-8")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252")


def load(path):
    text = read_text(path)
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while lines and lines[-1] == "":
        lines.pop()
    header_lines, hdr, rows = [], None, []
    for line in lines:
        f = unquote_split(line)
        while f and f[-1] == "":
            f.pop()
        if f and f[0].startswith("#"):
            header_lines.append(f[0])
        elif f and f[0] == "subject_id":
            hdr = f
        elif f and f[0]:
            rows.append(f)
    return header_lines, hdr, rows


def used_prefixes(recs):
    used = set()
    for r in recs:
        for col in ("subject_id", "predicate_id", "object_id", "mapping_justification"):
            v = r.get(col, "")
            m = CURIE_RE.match(v)
            if m:
                used.add(v.split(":", 1)[0])
    return used


def rebuild_header(header_lines, used):
    """Keep narrative header lines; regenerate the curie_map block."""
    out, i, skipping = [], 0, False
    while i < len(header_lines):
        ln = header_lines[i]
        if ln.strip() == "# curie_map:":
            out.append("# curie_map:")
            for p in sorted(used):
                iri = PREFIXES.get(p, "UNKNOWN-PREFIX")
                out.append(f"#   {p}: {iri}")
            i += 1
            while i < len(header_lines) and header_lines[i].startswith("#   "):
                i += 1  # drop old curie entries
            continue
        out.append(ln)
        i += 1
    return out


# subjects that are legitimately in a worksheet but are not leaf elements:
# mapped container elements (var, nCube) and any @attribute row.
NONLEAF_SUBJECTS = {"dataDscr.var", "dataDscr.nCube"}


def process(basename, check=False, expected=None, add_missing=False):
    path = os.path.join(HERE, basename + ".sssom.tsv")
    header_lines, hdr, rows = load(path)
    idx = {n: i for i, n in enumerate(hdr)} if hdr else {}
    recs = []
    for row in rows:
        rec = {n: (row[idx[n]] if n in idx and idx[n] < len(row) else "") for n in CANON}
        recs.append(rec)

    used = used_prefixes(recs) | {"skos", "semapv"}
    warn = []
    subjects = set()
    for r in recs:
        subjects.add(r["subject_id"])
        p, o = r["predicate_id"].strip(), r["object_id"].strip()
        if p and p not in SKOS:
            warn.append(f"non-SKOS predicate '{p}' on {r['subject_id']}")
        if o and (not CURIE_RE.match(o) or "[" in o or "." in o.split(":", 1)[-1]):
            warn.append(f"object_id not a single CURIE: '{o}' on {r['subject_id']}")
    for p in used:
        if p not in PREFIXES:
            warn.append(f"prefix '{p}' has no IRI in registry")

    # optional schema completeness check (expected = leaf paths this set should carry)
    if expected is not None:
        prefix = recs[0]["subject_id"].split(":", 1)[0] + ":" if recs else ""
        present = {r["subject_id"] for r in recs}
        missing = [p for p in sorted(expected) if prefix + p not in present]
        leaf_present = {s[len(prefix):] for s in present
                        if "@" not in s and s[len(prefix):] not in NONLEAF_SUBJECTS}
        extra = sorted(leaf_present - set(expected))
        if missing:
            warn.append(f"{len(missing)} schema leaf field(s) missing from worksheet"
                        + (" -- adding as blank rows" if (add_missing and not check)
                           else f" (e.g. {missing[:3]})"))
        if extra:
            warn.append(f"{len(extra)} subject(s) not in the schema -- possible typos (e.g. {extra[:3]})")
        if add_missing and not check:
            for p in missing:
                recs.append({"subject_id": prefix + p, "subject_label": p.split(".")[-1],
                             "comment": "unmapped literal field (no CDIF target) - for review",
                             "predicate_id": "", "object_id": "", "object_label": "",
                             "object_json_path": "", "mapping_justification": ""})

    n_map = sum(1 for r in recs if r["object_id"].strip())
    print(f"  {basename}: {len(recs)} rows, {n_map} mapped, prefixes={sorted(used)}")
    for w in warn:
        print(f"      ! {w}")

    if not check:
        out = rebuild_header(header_lines, used) + ["\t".join(CANON)]
        for r in recs:
            out.append("\t".join(r.get(c, "") for c in CANON))
        open(path, "w", encoding="utf-8", newline="\n").write("\n".join(out) + "\n")

    # derived MAP: mapped rows only
    mp = {}
    for r in recs:
        if r["object_id"].strip():
            mp[r["subject_id"]] = {k: r[k] for k in
                ("predicate_id", "object_id", "object_label", "object_json_path", "comment")}
    return mp, warn


DDICODEBOOK = os.path.normpath(os.path.join(HERE, "..", "DDICodebook"))


def find_xsds(override):
    """Locate the two DDI Codebook XSDs (2.5 and 1.2.2) in ../DDICodebook,
    or take explicit --xsd overrides. Returns (path_2.5, path_1.2.2)."""
    def find(patterns):
        for pat in patterns:
            hits = sorted(glob.glob(os.path.join(DDICODEBOOK, pat)))
            if hits:
                return hits[0]
        return None
    p25 = override.get("ddi25") or find(["*2.5*odebook*.xsd", "*2_5*.xsd", "*codebook*.xsd"])
    p122 = override.get("ddi122") or find(["*1-2-2*.xsd", "*Version1-2-2*.xsd", "*1_2_2*.xsd"])
    return p25, p122


def main():
    args = sys.argv[1:]
    check = "--check" in args
    add_missing = "--add-missing" in args
    no_xsd = "--no-xsd" in args
    override = {}
    it = iter(args)
    for a in it:
        kv = None
        if a == "--xsd":
            kv = next(it, "")
        elif a.startswith("--xsd="):
            kv = a[len("--xsd="):]
        if kv and "=" in kv:
            k, p = kv.split("=", 1)
            override[k] = p

    # Schema completeness: walk both XSDs, partition leaves into the sets each
    # worksheet is responsible for (common = 2.5 n 1.2.2; version files = the
    # difference), and hand each set its expected leaves.
    expected = {}
    if not no_xsd:
        sys.path.insert(0, HERE)
        p25, p122 = find_xsds(override)
        if p25 and p122:
            try:
                import ddiwalk_lib as W
                l25, l122 = set(W.leaf_fields(p25)), set(W.leaf_fields(p122))
                expected = {"ddi-common-to-cdif": l25 & l122,
                            "ddi25-to-cdif": l25 - l122,
                            "ddi122-to-cdif": l122 - l25}
                print(f"  schema check vs XSD: 2.5={len(l25)} 1.2.2={len(l122)} "
                      f"common={len(l25 & l122)} only2.5={len(l25 - l122)} "
                      f"only1.2.2={len(l122 - l25)}")
            except Exception as e:
                print(f"  (schema check skipped: {e})")
        else:
            print("  (schema check skipped: DDI XSD(s) not found in DDICodebook/; "
                  "pass --xsd ddi25=PATH --xsd ddi122=PATH, or --no-xsd)")

    allmap = {}
    for f in FILES:
        allmap[f], _ = process(f, check=check, expected=expected.get(f),
                               add_missing=add_missing)
    if not check:
        jp = os.path.join(HERE, "ddi_mappings.json")
        json.dump(allmap, open(jp, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
        total = sum(len(v) for v in allmap.values())
        print(f"  -> ddi_mappings.json  ({total} mappings across {len(allmap)} sets)")


if __name__ == "__main__":
    main()
