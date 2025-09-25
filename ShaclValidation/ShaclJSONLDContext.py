from rdflib import Graph
import pyshacl


data_graph = Graph()
data_graph.parse("../integrationPublic/TestCDIMetadata/cdi_wdsNectarValid.jsonld", format="json-ld")

shapes_graph = Graph()
shapes_graph.parse("SHACL-Examples/ddi-cdi.shaclDLingleySMR.ttl", format="ttl")


conforms, report_graph, report_text = pyshacl.validate(
    data_graph,
    shacl_graph=shapes_graph,
    inference="rdfs",  # Optional: enables RDFS inferencing during validation
    debug=False,        # Optional: provides more detailed debug information
    serialize_report_graph="ttl" # Optional: serializes the report graph
)


if conforms:
    print("Data graph conforms to SHACL shapes.")
else:
    print("Data graph does NOT conform to SHACL shapes.")
    print("Validation Report:")
    print(report_text)
