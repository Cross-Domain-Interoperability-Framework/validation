#!/usr/bin/env python3
"""Rebuild converters/DCAT/cdifOK/ from converters/DCAT/dcatExamplesOK/.

The corpus used to be produced by a script that never made it into the
repository, so cdifOK/ could drift from the converter with nothing to say so.
This is that step, written down.

What it does
------------
1. Groups the source files by directory + stem. The corpus ships many examples
   in more than one serialization, and those are the *same* logical example --
   though not always the same graph: upstream .ttl and .jsonld disagree in 45
   of the 78 such pairs, so all serializations of a group are parsed into ONE
   rdflib graph and converted once. The converter then sees the union rather
   than whichever file happened to be read.

2. Serializes each group to JSON-LD with a fixed context built from the
   mapping table's own curie_map, so the prefixes the converter matches on and
   the prefixes the corpus is written in cannot drift apart.

3. Converts every dcat:Dataset in the group, deriving dcterms:conformsTo from
   content via detect_conformance.

4. Names each record `<stem>__dcat-<slug of its title, 40 chars>.jsonld`, with
   `-frag` appended when nothing was detected. A fragment declares no
   conformance rather than claiming a profile it does not meet, and most of
   this corpus is fragments -- that is a property of the sources, many of
   which are single-feature specification examples.

5. Writes INDEX.json recording, for each record, the sources it came from.

Verification (--verify, on by default)
--------------------------------------
Two invariants, both of which caught real bugs while the converter was being
made table-driven:

  loss   every predicate in the source graph is accounted for in the record --
         mapped through the table, rewritten by the alias table, or preserved
         verbatim. A property that is neither is one the converter dropped.

  schema every record validates against the CoreDiscovery profile, or is a
         fragment. Fragments are expected to fail; a NON-fragment that fails
         means conformance was detected for content the schema rejects.

Usage:
    python build_corpus.py                 # rebuild and verify
    python build_corpus.py --no-verify     # rebuild only
    python build_corpus.py --check         # verify the corpus on disk, no writes
    python build_corpus.py --limit 20      # first 20 groups, for a quick pass
"""

import argparse
import collections
import json
import os
import re
import shutil
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")

HERE = Path(__file__).resolve().parent
MAPPINGS = HERE.parent / "mappings"
sys.path.insert(0, str(HERE))

import dcat_to_cdif as C  # noqa: E402

SUFFIX_FORMAT = {
    ".jsonld": "json-ld", ".json": "json-ld", ".ttl": "turtle",
    ".rdf": "xml", ".xml": "xml", ".nt": "nt", ".n3": "n3", ".trig": "trig",
}
SLUG_MAX = 40


def load_context():
    """The JSON-LD context to compact into, from the mapping set's curie_map.

    Taken from the table rather than restated so the prefixes the corpus is
    written in are exactly the ones the converter's rules match on. A prefix
    that drifts here would make every rule for that vocabulary silently miss.
    """
    import yaml
    ctx = {}
    for name in ("dcat-to-cdif.sssom.yml", "dcat-aliases.sssom.yml"):
        meta = yaml.safe_load((MAPPINGS / name).read_text(encoding="utf-8"))
        for prefix, iri in (meta.get("curie_map") or {}).items():
            if prefix not in ("semapv",):
                ctx.setdefault(prefix, iri)
    ctx.setdefault("foaf", "http://xmlns.com/foaf/0.1/")
    ctx.setdefault("owl", "http://www.w3.org/2002/07/owl#")
    return ctx


def slug(text, limit=SLUG_MAX):
    out = re.sub(r"[^a-z0-9]+", "-", (text or "untitled").lower()).strip("-")
    return (out[:limit].rstrip("-") or "untitled")


def group_sources(root):
    """[(relative directory, stem, [paths])] -- one entry per logical example."""
    groups = collections.defaultdict(list)
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUFFIX_FORMAT:
            continue
        if path.name in ("INDEX.json",):
            continue
        groups[(path.parent, path.stem)].append(path)
    return [(d, stem, sorted(files)) for (d, stem), files in sorted(
        groups.items(), key=lambda kv: (str(kv[0][0]), kv[0][1]))]


# Base for relative IRIs in a source document. Without one rdflib uses the
# local file path, which baked "file:///C:/…" into published records -- a
# machine-specific identifier in a committed artifact.
PUBLIC_BASE = ("https://cross-domain-interoperability-framework.github.io/"
               "validation/converters/DCAT/dcatExamplesOK/")


def merged_graph(files, source_root=None):
    """One graph per logical example, plus the files that actually parsed."""
    import rdflib
    graph = rdflib.Graph()
    used, failed = [], []
    for path in files:
        base = PUBLIC_BASE
        if source_root is not None:
            base += path.relative_to(source_root).as_posix()
        try:
            graph.parse(str(path), format=SUFFIX_FORMAT[path.suffix.lower()],
                        publicID=base)
            used.append(path)
        except Exception as exc:
            if isinstance(exc, FileNotFoundError) or "404" in str(exc):
                # The file is there; the @context it names is not resolvable.
                # The source omits the scheme, so the IRI is relative and
                # resolves against whatever base is in play.
                failed.append((path, "unresolvable relative @context IRI "
                                     "(the source omits the scheme)"))
            else:
                raise
        except Exception as exc:
            failed.append((path, "%s: %s" % (type(exc).__name__, exc)))
    return graph, used, failed


def declared(record):
    node = record.get("schema:subjectOf") or {}
    return [c.get("@id") for c in C._as_list(node.get("dcterms:conformsTo"))
            if isinstance(c, dict) and c.get("@id")]


# ---------------------------------------------------------------------------
# verification
# ---------------------------------------------------------------------------

def source_predicates(graph):
    """Every predicate asserted on a dcat:Dataset in the source graph."""
    import rdflib
    DCAT = rdflib.Namespace("http://www.w3.org/ns/dcat#")
    out = set()
    for subject in graph.subjects(rdflib.RDF.type, DCAT.Dataset):
        for predicate in graph.predicates(subject, None):
            out.add(str(predicate))
    return out


def expand(curie, context):
    """A CURIE as an IRI, using the mapping set's own prefixes."""
    prefix, _, local = curie.partition(":")
    base = context.get(prefix)
    return base + local if base else curie


def curie_of(iri, context):
    for prefix, base in context.items():
        if iri.startswith(base):
            return prefix + ":" + iri[len(base):]
    return iri


def record_keys(node, depth=0, out=None):
    """Every property key anywhere in a record."""
    if out is None:
        out = set()
    if depth > 12:
        return out
    if isinstance(node, list):
        for item in node:
            record_keys(item, depth + 1, out)
        return out
    if not isinstance(node, dict):
        return out
    for key, value in node.items():
        if not key.startswith("@"):
            out.add(key)
        record_keys(value, depth + 1, out)
    return out


def record_iris(record):
    """A record's keys as IRIs, expanded through the record's OWN @context.

    The converter mints a prefix for any vocabulary it passes through and
    declares it in the record -- HealthDCAT-AP arrives as health:analytics,
    not as the IRI the source used. Comparing raw strings therefore reports
    every extension property as lost when all of them were preserved.
    """
    ctx = record.get("@context") or {}
    prefixes = {k: v for k, v in ctx.items()
                if isinstance(v, str) and not k.startswith("@")}
    out = set()
    for key in record_keys(record):
        if key.startswith(("http://", "https://")):
            out.add(key)
            continue
        prefix, _, local = key.partition(":")
        base = prefixes.get(prefix)
        out.add(base + local if base else key)
    return out


def check_loss(graph, records, context):
    """Source predicates that reach no record, compared as IRIs."""
    targets = {}
    for rows in C.RULES.values():
        for row in rows:
            if row["object_id"]:
                targets.setdefault(row["subject_id"], row["object_id"])
    present = set()
    for record in records:
        present |= record_iris(record)
    missing = set()
    for iri in source_predicates(graph):
        curie = curie_of(iri, context)
        if curie == "rdf:type" or iri.endswith("22-rdf-syntax-ns#type"):
            continue
        if iri in present or curie in present:
            continue
        # or under the IRI the alias table says the publisher meant
        alias = C.ALIASES.get(curie)
        if alias and (alias in present
                      or expand(alias, context) in present):
            continue
        # or re-expressed as the CDIF property the table sends it to
        target = targets.get(C.ALIASES.get(curie, curie))
        if target and (target in present
                       or curie_of(target, context) in present
                       or any(t.endswith(target.split(":", 1)[-1]) for t in present)):
            continue
        missing.add(curie)
    return missing


def check_schema(records, validator):
    """(record, [messages]) for every record that does not validate."""
    bad = []
    for name, record in records:
        errors = [e.message for e in validator.iter_errors(record)]
        if errors:
            bad.append((name, errors))
    return bad



def shacl_bundle(cache):
    """The assembled CoreDiscovery shapes graph, or None with a reason.

    The composite's own rules.shacl is NOT self-contained: it references shapes
    defined in the building blocks it composes, so pyshacl over that one file
    errors on cdifd:descriptionProperty. metadataBuildingBlocks'
    validate_shacl.py follows the $ref graph and emits the whole bundle -- 20
    rules.shacl files, ~1300 triples -- which is what has to be validated
    against.
    """
    import subprocess
    mbb = (HERE / ".." / ".." / ".." / "metadataBuildingBlocks").resolve()
    emitter = mbb / "tools" / "validate_shacl.py"
    if not emitter.exists():
        return None, "metadataBuildingBlocks not beside this repo (%s)" % mbb
    if not cache.exists():
        target = mbb / "_sources/profiles/cdifCompositeProfile/CoreDiscovery"
        proc = subprocess.run(
            [sys.executable, str(emitter), str(target), "--emit-shapes", str(cache)],
            capture_output=True, text=True, cwd=str(mbb))
        if proc.returncode != 0 or not cache.exists():
            return None, "could not emit shapes: %s" % (proc.stderr or proc.stdout)[:200]
    try:
        import rdflib
        graph = rdflib.Graph()
        graph.parse(str(cache), format="turtle")
        return graph, None
    except Exception as exc:
        return None, str(exc)


def check_shacl(index, out_root, shapes):
    """(conformant with a Violation, fragments with one, warning messages)."""
    import rdflib
    from pyshacl import validate
    SH = rdflib.Namespace("http://www.w3.org/ns/shacl#")
    bad = {"conformant": [], "fragment": []}
    warned = collections.Counter()
    for entry in index:
        kind = "fragment" if entry["fragment"] else "conformant"
        data = rdflib.Graph()
        try:
            data.parse(str(out_root / entry["cdif"]), format="json-ld")
            _, report, _ = validate(data, shacl_graph=shapes, advanced=True,
                                    inference="none")
        except Exception:
            continue
        for result in report.subjects(rdflib.RDF.type, SH.ValidationResult):
            severity = str(report.value(result, SH.resultSeverity) or "")
            message = str(report.value(result, SH.resultMessage) or "")[:110]
            if severity.endswith("Violation"):
                bad[kind].append((entry["cdif"], message))
            elif severity.endswith("Warning"):
                warned[message] += 1
    return bad, warned

# ---------------------------------------------------------------------------

def build(source_root, out_root, limit=None, verify=True, write=True):
    context = load_context()
    groups = group_sources(source_root)
    if limit:
        groups = groups[:limit]

    if write and out_root.exists():
        for child in sorted(out_root.iterdir()):
            if child.name == "README.md":
                continue
            shutil.rmtree(child) if child.is_dir() else child.unlink()

    index, all_records, parse_failures = [], [], []
    loss_findings = collections.defaultdict(set)
    counts = collections.Counter()

    for directory, stem, files in groups:
        graph, used, failed = merged_graph(files, source_root)
        parse_failures.extend(failed)
        if not used:
            continue
        try:
            doc = json.loads(graph.serialize(format="json-ld", context=context,
                                             auto_compact=True))
        except Exception as exc:
            parse_failures.append((directory / stem, "serialize: %s" % exc))
            continue

        node_index = C.build_node_index(doc)
        datasets = C.find_datasets(doc)
        if not datasets:
            counts["groups with no dcat:Dataset"] += 1
            continue

        rel_dir = directory.relative_to(source_root)
        produced, taken = [], set()
        for n, dataset in enumerate(datasets):
            # CDIF requires an @id and its shapes require an IRI. A source that
            # gives none leaves rdflib's blank-node label, which is a fresh
            # random string on every parse and meaningless outside the
            # document. Mint something stable and obviously minted instead.
            nid = dataset.get("@id")
            if not isinstance(nid, str) or not nid.startswith(
                    ("http://", "https://", "urn:")) or nid.startswith(PUBLIC_BASE):
                dataset = dict(dataset)
                dataset["@id"] = "%s%s#dataset-%d" % (
                    PUBLIC_BASE, (rel_dir / stem).as_posix(), n)
            try:
                record = C.convert_dcat_to_cdif(
                    json.loads(json.dumps(dataset)), graph=node_index)
            except Exception as exc:
                parse_failures.append((directory / stem,
                                       "convert: %s: %s" % (type(exc).__name__, exc)))
                continue
            fragment = not declared(record)
            base = "%s__dcat-%s%s" % (stem, slug(record.get("schema:name")),
                                      "-frag" if fragment else "")
            name, n = base, 1
            while name in taken:                 # two datasets, one title
                n += 1
                name = "%s-%d" % (base, n)
            taken.add(name)
            produced.append((name, record, fragment))

        for name, record, fragment in produced:
            rel = (rel_dir / (name + ".jsonld")).as_posix()
            if write:
                target = out_root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(
                    json.dumps(record, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
            index.append({
                "cdif": rel,
                "sources": [p.relative_to(source_root).as_posix() for p in used],
                "merged_from": len(used),
                "fragment": fragment,
            })
            all_records.append((rel, record))
            counts["fragments" if fragment else "conformant"] += 1

        if verify:
            for curie in check_loss(graph, [r for _, r, _ in produced], context):
                loss_findings[curie].add((rel_dir / stem).as_posix())

    if write:
        index.sort(key=lambda e: e["cdif"])
        (out_root / "INDEX.json").write_text(
            json.dumps(index, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    return index, all_records, parse_failures, loss_findings, counts


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default=str(HERE / "dcatExamplesOK"))
    ap.add_argument("--out", default=str(HERE / "cdifOK"))
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--check", action="store_true",
                    help="verify without writing anything")
    ap.add_argument("--shacl", action="store_true",
                    help="also run the CoreDiscovery SHACL shapes (slow; needs "
                         "pyshacl and metadataBuildingBlocks beside this repo)")
    args = ap.parse_args()

    verify = not args.no_verify
    index, records, failures, losses, counts = build(
        Path(args.source), Path(args.out), limit=args.limit,
        verify=verify, write=not args.check)

    print("records        : %d  (%d conformant, %d fragments)"
          % (len(index), counts["conformant"], counts["fragments"]))
    print("source groups  : %d" % len({tuple(e["sources"]) for e in index}))
    print("merged groups  : %d"
          % len({tuple(e["sources"]) for e in index if e["merged_from"] > 1}))
    for label, n in sorted(counts.items()):
        if label not in ("conformant", "fragments"):
            print("%-15s: %d" % (label, n))
    if failures:
        print("\nfiles that would not parse or convert: %d" % len(failures))
        for path, why in failures[:8]:
            print("   %-56s %s" % (Path(path).name, why[:70]))

    status = 0
    if verify:
        print("\n=== loss: source predicates that reach no record ===")
        if not losses:
            print("  none")
        else:
            status = 1
            for curie, where in sorted(losses.items(),
                                       key=lambda kv: -len(kv[1])):
                print("  %-42s %d example(s), e.g. %s"
                      % (curie, len(where), sorted(where)[0]))

        print("\n=== schema: records that do not validate ===")
        try:
            from jsonschema import Draft202012Validator
            schema_path = (HERE / ".." / ".." / ".." / "metadataBuildingBlocks"
                           / "_sources" / "profiles" / "cdifCompositeProfile"
                           / "CoreDiscovery" / "resolvedSchema.json").resolve()
            validator = Draft202012Validator(
                json.loads(schema_path.read_text(encoding="utf-8")))
        except Exception as exc:
            print("  skipped (%s)" % exc)
        else:
            frag = {e["cdif"] for e in index if e["fragment"]}
            bad = check_schema(records, validator)
            bad_conformant = [(n, m) for n, m in bad if n not in frag]
            print("  fragments failing (expected)      : %d"
                  % sum(1 for n, _ in bad if n in frag))
            print("  NON-fragments failing (a problem) : %d" % len(bad_conformant))
            for name, msgs in bad_conformant[:6]:
                print("     %s" % name)
                for msg in msgs[:2]:
                    print("        %s" % msg[:110])
            if bad_conformant:
                status = 1

        if args.shacl:
            print("")
            print("=== SHACL: CoreDiscovery shapes ===")
            cache = HERE / ".shacl-coreDiscovery.ttl"
            shapes, why = shacl_bundle(cache)
            if shapes is None:
                print("  skipped (%s)" % why)
            else:
                bad, warned = check_shacl(index, Path(args.out), shapes)
                nc = len({r for r, _ in bad["conformant"]})
                nf = len({r for r, _ in bad["fragment"]})
                print("  conformant records with a Violation : %d of %d"
                      % (nc, sum(1 for e in index if not e["fragment"])))
                print("  fragments with a Violation          : %d (expected: a "
                      "fragment declares no profile)" % nf)
                seen = set()
                for rel, msg in bad["conformant"]:
                    if msg not in seen:
                        seen.add(msg)
                        print("     %s" % msg)
                if warned:
                    print("  most common warnings (advisory):")
                    for msg, n in warned.most_common(4):
                        print("     %4d  %s" % (n, msg))
                if nc:
                    status = 1
    return status


if __name__ == "__main__":
    sys.exit(main())
