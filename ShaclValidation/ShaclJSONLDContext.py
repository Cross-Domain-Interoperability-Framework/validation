#!/usr/bin/env python3
"""Validate JSON-LD metadata against SHACL shapes."""

import argparse
import sys
from rdflib import Graph
from rdflib import Namespace
import pyshacl


def parse_args():
    parser = argparse.ArgumentParser(
        description='Validate JSON-LD metadata against SHACL shapes.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python ShaclJSONLDContext.py data.jsonld shapes.ttl
  python ShaclJSONLDContext.py --data my-metadata.jsonld --shapes CDIF-Discovery-Core-Shapes2.ttl
  python ShaclJSONLDContext.py -d data.jsonld -s shapes.ttl --verbose
        '''
    )
    parser.add_argument('data', nargs='?',
                        help='Path to JSON-LD metadata file to validate')
    parser.add_argument('shapes', nargs='?',
                        help='Path to SHACL shapes file (TTL format)')
    parser.add_argument('-d', '--data', dest='data_opt',
                        help='Path to JSON-LD metadata file (alternative to positional)')
    parser.add_argument('-s', '--shapes', dest='shapes_opt',
                        help='Path to SHACL shapes file (alternative to positional)')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Show detailed diagnostic output including SPARQL target matches')

    args = parser.parse_args()

    # Use optional args if positional not provided
    data_path = args.data or args.data_opt
    shapes_path = args.shapes or args.shapes_opt

    if not data_path or not shapes_path:
        parser.print_help()
        print("\nError: Both data file and shapes file are required.")
        sys.exit(1)

    return data_path, shapes_path, args.verbose


def validate_shacl(data_path, shapes_path, verbose=False):
    """
    Validate a JSON-LD file against SHACL shapes.

    Args:
        data_path: Path to JSON-LD data file
        shapes_path: Path to SHACL shapes file (TTL format)
        verbose: If True, show detailed diagnostic output

    Returns:
        True if valid, False otherwise
    """
    # Load data graph
    data_graph = Graph()
    data_graph.parse(data_path, format="json-ld")
    print(f"Length of DataGraph to evaluate: {len(data_graph)}")

    # Load shapes graph
    shapes_graph = Graph()
    shapes_graph.parse(shapes_path, format="ttl")
    print(f"Length of shapesGraph with rules: {len(shapes_graph)}")

    if verbose:
        # Check for DefinedTerm matches
        q = """
              PREFIX schema: <http://schema.org/>
                    SELECT DISTINCT ?this

                WHERE {
                ?this a schema:DefinedTerm .
                {
                  ?this schema:name "example defined term" .
                  FILTER NOT EXISTS { ?s ?p ?this . }
                }
                Union
                {
                 VALUES ?p {
                    schema:linkRelationship
                    schema:measurementTechnique
                    schema:keywords
                    schema:name
                  }
                 ?s ?p ?this .
                }
              }
        """
        print("matches for definedTerm")
        for row in data_graph.query(q):
            print(row)

        SH = Namespace("http://www.w3.org/ns/shacl#")
        print("All NodeShapes and their targets:")
        q = """
        PREFIX sh: <http://www.w3.org/ns/shacl#>
        SELECT ?shape ?targetType ?target
        WHERE {
          ?shape a sh:NodeShape .
          ?shape ?targetType ?target .
          FILTER(?targetType IN (sh:targetNode, sh:targetClass, sh:targetSubjectsOf, sh:targetObjectsOf))
        }
        """
        for row in shapes_graph.query(q):
            print(f"Shape {row.shape} targets {row.targetType} {row.target}")

        print("Shapes with SPARQL targets:")
        q = """
        PREFIX sh: <http://www.w3.org/ns/shacl#>
        SELECT ?shape ?query
        WHERE {
          ?shape sh:select ?query .
        }
        """
        for row in shapes_graph.query(q):
            print(f"Shape {row.shape} uses SPARQL target:\n{row.query}\n")
        for shape, qtext in shapes_graph.query(q):
            print(f"Running {shape}")
            for row in data_graph.query(qtext.toPython()):
                print("  -> matched node:", row.this)

    # Run validation
    conforms, report_graph, report_text = pyshacl.validate(
        data_graph,
        shacl_graph=shapes_graph,
        inference="rdfs",
        debug=verbose,
        advanced=True
    )

    # Query for validation results
    q = """
    PREFIX sh: <http://www.w3.org/ns/shacl#>
    SELECT DISTINCT ?focus ?shape ?message
    WHERE {
      ?r a sh:ValidationResult ;
         sh:focusNode ?focus ;
         sh:sourceShape ?shape .
      OPTIONAL { ?r sh:resultMessage ?message . }
    }
    """
    for row in report_graph.query(q):
        print(f"Focus node: {row.focus}\n  Shape: {row.shape}\n  Message: {row.message}\n")

    if conforms:
        print("Data graph conforms to SHACL shapes.")
        return True
    else:
        print("Data graph does NOT conform to SHACL shapes.")
        print("Validation Report:")
        print(report_text)
        return False


if __name__ == '__main__':
    data_path, shapes_path, verbose = parse_args()
    success = validate_shacl(data_path, shapes_path, verbose)
    sys.exit(0 if success else 1)
