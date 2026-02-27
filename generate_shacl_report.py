#!/usr/bin/env python3
"""
Generate a markdown validation report from SHACL validation of JSON-LD metadata.

Runs pyshacl validation on a JSON-LD data file against SHACL shapes, then
produces a structured markdown report grouped by severity (Violation, Warning,
Info) and message. Each issue shows the focus node with its type and
name/identifier for context.

Usage:
    python generate_shacl_report.py <data.jsonld> <shapes.ttl> [-o report.md] [-v]

If no output file is specified, the report is printed to stdout.
"""

import argparse
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from rdflib import Graph, Namespace, URIRef, BNode, Literal
import pyshacl

SH = Namespace("http://www.w3.org/ns/shacl#")
SCHEMA = Namespace("http://schema.org/")

# Namespace prefixes for compact display
NS_PREFIXES = [
    ("http://schema.org/", "schema:"),
    ("http://www.w3.org/ns/prov#", "prov:"),
    ("http://www.w3.org/ns/dqv#", "dqv:"),
    ("http://purl.org/dc/terms/", "dcterms:"),
    ("http://www.w3.org/ns/shacl#", "sh:"),
    ("http://www.w3.org/2006/time#", "time:"),
    ("http://ddialliance.org/Specification/DDI-CDI/1.0/RDF/", "cdi:"),
    ("http://spdx.org/rdf/terms#", "spdx:"),
    ("http://www.opengis.net/ont/geosparql#", "geosparql:"),
    ("http://www.w3.org/1999/02/22-rdf-syntax-ns#", "rdf:"),
    ("http://www.w3.org/2000/01/rdf-schema#", "rdfs:"),
    ("https://cdif.org/validation/0.1/shacl#", "cdifd:"),
]

SEVERITY_ORDER = {
    SH.Violation: 0,
    SH.Warning: 1,
    SH.Info: 2,
}

SEVERITY_LABELS = {
    SH.Violation: "Violation",
    SH.Warning: "Warning",
    SH.Info: "Info",
}


def short_uri(uri):
    """Compact a URI using known namespace prefixes."""
    s = str(uri)
    for ns, prefix in NS_PREFIXES:
        if s.startswith(ns):
            return prefix + s[len(ns):]
    return s


def describe_focus(focus, data_graph):
    """Describe a focus node with its type and name/identifier."""
    if isinstance(focus, BNode):
        # Get type
        types = list(data_graph.objects(focus, URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")))
        type_str = short_uri(types[0]) if types else "unknown type"
        return f"[{type_str}] (anonymous blank node)"

    if isinstance(focus, URIRef):
        # Get type and name
        types = list(data_graph.objects(focus, URIRef("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")))
        names = list(data_graph.objects(focus, SCHEMA.name))

        if types and names:
            type_str = short_uri(types[0])
            return f'[{type_str}] "{names[0]}"'
        elif types:
            type_str = short_uri(types[0])
            return f"[{type_str}] <{focus}>"
        else:
            return f"<{focus}>"

    return str(focus)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate a markdown SHACL validation report.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python generate_shacl_report.py data.jsonld CDIF-Complete-Shapes.ttl
  python generate_shacl_report.py data.jsonld CDIF-Discovery-Core-Shapes.ttl -o report.md
  python generate_shacl_report.py -d data.jsonld -s shapes.ttl -o report.md -v
        """,
    )
    parser.add_argument("data", nargs="?", help="Path to JSON-LD metadata file")
    parser.add_argument("shapes", nargs="?", help="Path to SHACL shapes file (TTL)")
    parser.add_argument(
        "-d", "--data", dest="data_opt", help="Path to JSON-LD metadata file (alternative)"
    )
    parser.add_argument(
        "-s", "--shapes", dest="shapes_opt", help="Path to SHACL shapes file (alternative)"
    )
    parser.add_argument("-o", "--output", help="Output markdown file (default: stdout)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")

    args = parser.parse_args()
    data_path = args.data or args.data_opt
    shapes_path = args.shapes or args.shapes_opt

    if not data_path or not shapes_path:
        parser.print_help()
        print("\nError: Both data file and shapes file are required.")
        sys.exit(1)

    return data_path, shapes_path, args.output, args.verbose


def generate_report(data_path, shapes_path, verbose=False):
    """Run SHACL validation and return a markdown report string."""
    # Load graphs
    data_graph = Graph()
    data_graph.parse(data_path, format="json-ld")

    shapes_graph = Graph()
    shapes_graph.parse(shapes_path, format="ttl")

    if verbose:
        print(f"Data graph: {len(data_graph)} triples", file=sys.stderr)
        print(f"Shapes graph: {len(shapes_graph)} triples", file=sys.stderr)

    # Run validation
    conforms, report_graph, report_text = pyshacl.validate(
        data_graph,
        shacl_graph=shapes_graph,
        inference="rdfs",
        advanced=True,
    )

    # Query detailed results
    q = """
    PREFIX sh: <http://www.w3.org/ns/shacl#>
    SELECT ?result ?focus ?severity ?path ?message ?value ?constraint
    WHERE {
        ?result a sh:ValidationResult ;
                sh:focusNode ?focus ;
                sh:resultSeverity ?severity .
        OPTIONAL { ?result sh:resultPath ?path . }
        OPTIONAL { ?result sh:resultMessage ?message . }
        OPTIONAL { ?result sh:value ?value . }
        OPTIONAL { ?result sh:sourceConstraintComponent ?constraint . }
    }
    """
    results = list(report_graph.query(q))

    # Group by severity then message
    by_severity = defaultdict(lambda: defaultdict(list))
    for row in results:
        sev = row.severity
        msg = str(row.message) if row.message else "(no message)"
        path_str = short_uri(row.path) if row.path else ""
        focus_desc = describe_focus(row.focus, data_graph)
        by_severity[sev][msg].append((focus_desc, path_str))

    # Build markdown
    lines = []
    lines.append("# CDIF SHACL Validation Report")
    lines.append("")
    lines.append(f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"**Data file:** {Path(data_path).as_posix()}")
    lines.append(f"**Shapes file:** {Path(shapes_path).name}")
    lines.append(f"**Data graph triples:** {len(data_graph)}")
    lines.append(f"**Shapes graph triples:** {len(shapes_graph)}")
    lines.append(f"**Conforms:** {conforms}")
    lines.append(f"**Total issues:** {len(results)}")
    lines.append("")

    # Summary table
    lines.append("## Summary by severity")
    lines.append("")
    lines.append("| Severity | Count |")
    lines.append("|----------|-------|")
    for sev in sorted(SEVERITY_ORDER, key=SEVERITY_ORDER.get):
        count = sum(len(items) for items in by_severity[sev].values())
        if count > 0:
            lines.append(f"| {SEVERITY_LABELS[sev]} | {count} |")
    lines.append("")

    # Detail sections
    for sev in sorted(SEVERITY_ORDER, key=SEVERITY_ORDER.get):
        messages = by_severity[sev]
        if not messages:
            continue
        total = sum(len(items) for items in messages.values())
        label = SEVERITY_LABELS[sev]
        lines.append(f"## {label}s ({total})")
        lines.append("")

        for msg, items in sorted(messages.items(), key=lambda x: (-len(x[1]), x[0])):
            lines.append(f"### {msg} ({len(items)})")
            lines.append("")
            for focus_desc, path_str in items:
                if path_str:
                    lines.append(f"- **Focus:** {focus_desc}  **Path:** {path_str}")
                else:
                    lines.append(f"- **Focus:** {focus_desc}")
            lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    data_path, shapes_path, output_path, verbose = parse_args()
    report = generate_report(data_path, shapes_path, verbose)

    if output_path:
        Path(output_path).write_text(report, encoding="utf-8")
        print(f"Report written to {output_path}", file=sys.stderr)
    else:
        print(report)
