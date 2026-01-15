from rdflib import Graph
from rdflib import Namespace
import pyshacl



# theData = "../integrationPublic/TestCDIMetadata/cdi_wdsNectarValid.jsonld"
theData = "C:/Users/smrTu/OneDrive/Documents/GithubC/CDIF/integrationPublic/TestCDIMetadata/se_na2so4-testschemaorg-cdiv3.jsonLD"
#theData = "C:/Users/smrTu/OneDrive/Documents/GithubC/smrgeoinfo/OCGbuildingBlockTest/_sources/provProperties/derivedFrom/exampleDerivedFrom.json"
# theData = "C:/Users/smrTu/OneDrive/Documents/GithubC/smrgeoinfo/OCGbuildingBlockTest/_sources/properties/definedTerm/exampleDefinedTerm.json"
# theData = "C:/Users/smrTu/OneDrive/Documents/GithubC/smrgeoinfo/OCGbuildingBlockTest/_sources/entities/CDIFDiscovery/CDIF-XAS-Full.json"
#  C:\Users\smrTu\OneDrive\Documents\GithubC\smrgeoinfo\OCGbuildingBlockTest\_sources\entities\CDIFDiscovery\xrd-2j0t-gq80.json
data_graph = Graph()
data_graph.parse(theData, format="json-ld")

print("Length of DataGraph to evaluate:", len(data_graph))
#for s,p,o in data_graph:
#    print(s, p, o)

# theShapes = "SHACL-Examples/ddi-cdi.shaclDLingleySMR.ttl"
# theShapes = "C:/Users/smrTu/OneDrive/Documents/GithubC/CDIF/validation/CDIF-Discovery-Core-Shapes.ttl"
# theShapes = "C:/Users/smrTu/OneDrive/Documents/GithubC/smrgeoinfo/OCGbuildingBlockTest/_sources/provProperties/derivedFrom/rules.shacl"
theShapes = "C:/Users/smrTu/OneDrive/Documents/GithubC/smrgeoinfo/OCGbuildingBlockTest/_sources/schemaorgProperties/cdifMandatory/rules.shacl"
shapes_graph = Graph()
shapes_graph.parse(theShapes, format="ttl")
print("Length of shapesGraph with rules:", len(shapes_graph))
#for s,p,o in shapes_graph:
#    print(s, p, o)

# check an sparqlTarget to see if it is a valid property
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
        print("  → matched node:", row.this)


conforms, report_graph, report_text = pyshacl.validate(
    data_graph,
    shacl_graph=shapes_graph,
    inference="rdfs",  # Optional: enables RDFS inferencing during validation
    debug= True,        # Optional: provides more detailed debug information

    advanced=True
)

#    serialize_report_graph="ttl", # Optional: serializes the report graph

#for s, p, o in report_graph.triples((None, None, None)):
#    print(s, p, o)

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
else:
    print("Data graph does NOT conform to SHACL shapes.")
    print("Validation Report:")
    print(report_text)
# print("report graph")
# print(report_graph.serialize(format="turtle"))
