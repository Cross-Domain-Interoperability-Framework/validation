#!/usr/bin/env python3
"""Normalize the curie_map of every SSSOM sidecar to exactly the prefixes its
table uses.

For each `<name>.sssom.tsv` that has a sibling `<name>.sssom.yml`, this reads the
prefixes actually used in the table's CURIE-bearing columns (subject_id,
predicate_id, object_id, mapping_justification, and -- where present --
subject_class) and rewrites only the `curie_map:` block of the `.yml` to that
set, sorted, with each prefix's IRI looked up in a registry. Everything else in
the sidecar, and the whole table, is left untouched.

This generalizes the curie_map regeneration in sync_ddi_mappings.py across the
DCAT / SOSO / Croissant sets too. It scans the same columns that tool does (plus
the DCAT-only subject_class), so it produces identical curie_maps for the three
DDI worksheets; sync_ddi_mappings.py still owns the DDI XSD-completeness check
and ddi_mappings.json. It changes no table and no converter behaviour: the DCAT
converter reads the .tsv, not the sidecar's curie_map.

The registry is harvested from every sidecar's existing curie_map (so IRIs stay
whatever the files already declare), with a small fallback of well-known
prefixes. A prefix a table uses but no sidecar declares is reported and emitted
as UNKNOWN-PREFIX for the curator to fill in once.

Usage:
    python sync_sssom.py            # normalize every sidecar's curie_map
    python sync_sssom.py --check    # report what would change, write nothing
"""
import csv, io, os, glob, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
CURIE_COLS = ("subject_id", "predicate_id", "object_id",
              "mapping_justification", "subject_class")
ALWAYS = {"skos", "semapv"}            # SSSOM predicate / justification namespaces
CURIE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*:")
CURIEMAP_ENTRY = re.compile(r"^  [A-Za-z][A-Za-z0-9._-]*:\s")

# Backstop for the fundamental prefixes, used only when no sidecar declares one.
FALLBACK = {
    "schema": "http://schema.org/",
    "dcterms": "http://purl.org/dc/terms/",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "semapv": "https://w3id.org/semapv/vocab/",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "prov": "http://www.w3.org/ns/prov#",
    "dcat": "http://www.w3.org/ns/dcat#",
    "foaf": "http://xmlns.com/foaf/0.1/",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
}


def read_text(path):
    """Decode a sidecar/table whatever encoding a spreadsheet left it in."""
    raw = open(path, "rb").read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    if raw[:3] == b"\xef\xbb\xbf":
        return raw[3:].decode("utf-8")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252")


def yml_lines(path):
    lines = read_text(path).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def curie_map_of(lines):
    """Parse the `curie_map:` block of a sidecar into {prefix: iri}."""
    out, inblock = {}, False
    for ln in lines:
        if ln.strip() == "curie_map:":
            inblock = True
            continue
        if inblock:
            if CURIEMAP_ENTRY.match(ln):
                k, v = ln.strip().split(":", 1)
                out[k.strip()] = v.strip().strip('"')
            elif ln.startswith("  "):
                continue                       # a wrapped value or blank-ish
            else:
                break                          # left the block
    return out


def bases(name):
    tsv = os.path.join(HERE, name + ".sssom.tsv")
    yml = os.path.join(HERE, name + ".sssom.yml")
    return tsv, yml


def discover():
    names = []
    for tsv in sorted(glob.glob(os.path.join(HERE, "*.sssom.tsv"))):
        base = os.path.basename(tsv)[:-len(".sssom.tsv")]
        if os.path.exists(os.path.join(HERE, base + ".sssom.yml")):
            names.append(base)
    return names


def build_registry(names):
    reg, conflicts = {}, []
    for name in names:
        _, yml = bases(name)
        for p, iri in curie_map_of(yml_lines(yml)).items():
            if p in reg and reg[p] != iri:
                conflicts.append((p, reg[p], iri, name))
            reg.setdefault(p, iri)
    for p, iri in FALLBACK.items():
        reg.setdefault(p, iri)
    return reg, conflicts


def used_prefixes(tsv):
    text = read_text(tsv).replace("\r\n", "\n").replace("\r", "\n")
    rows = list(csv.reader(io.StringIO(text), delimiter="\t"))
    if not rows:
        return set()
    header = rows[0]
    idx = {c: i for i, c in enumerate(header)}
    used = set(ALWAYS)
    for row in rows[1:]:
        if not row or not row[0] or row[0].startswith("#"):
            continue
        for col in CURIE_COLS:
            i = idx.get(col)
            if i is None or i >= len(row):
                continue
            v = row[i].strip()
            if not v or "://" in v:            # blank, or a full IRI (not a CURIE)
                continue
            m = CURIE_RE.match(v)
            if m:
                used.add(v.split(":", 1)[0])
    return used


def rebuild(lines, used, reg):
    out, i, found = [], 0, False
    while i < len(lines):
        ln = lines[i]
        if ln.strip() == "curie_map:":
            found = True
            out.append("curie_map:")
            for p in sorted(used):
                out.append("  %s: %s" % (p, reg.get(p, "UNKNOWN-PREFIX")))
            i += 1
            while i < len(lines) and CURIEMAP_ENTRY.match(lines[i]):
                i += 1
            continue
        out.append(ln)
        i += 1
    if not found:                              # no curie_map block: leave the file alone
        return None
    return out


def main():
    check = "--check" in sys.argv[1:]
    names = discover()
    reg, conflicts = build_registry(names)
    for p, a, b, where in conflicts:
        print(f"  ! prefix '{p}' declared as both '{a}' and '{b}' (at {where}); "
              f"keeping the first")
    changed = 0
    for name in names:
        tsv, yml = bases(name)
        used = used_prefixes(tsv)
        for p in sorted(used):
            if p not in reg:
                print(f"  ! {name}: prefix '{p}' has no IRI in any sidecar "
                      f"(emitting UNKNOWN-PREFIX)")
        before = yml_lines(yml)
        after = rebuild(before, used, reg)
        if after is None:
            print(f"  {name}: no curie_map block -- skipped")
            continue
        if after != before:
            changed += 1
            old = set(curie_map_of(before))
            new = set(used)
            added, dropped = sorted(new - old), sorted(old - new)
            note = []
            if added:
                note.append("added " + ", ".join(added))
            if dropped:
                note.append("dropped " + ", ".join(dropped))
            print(f"  {name}: {len(used)} prefixes"
                  + (" (" + "; ".join(note) + ")" if note else " (reordered)"))
            if not check:
                open(yml, "w", encoding="utf-8", newline="\n").write("\n".join(after) + "\n")
        else:
            print(f"  {name}: up to date ({len(used)} prefixes)")
    verb = "would change" if check else "updated"
    print(f"  -> {verb} {changed} sidecar(s)")


if __name__ == "__main__":
    main()
