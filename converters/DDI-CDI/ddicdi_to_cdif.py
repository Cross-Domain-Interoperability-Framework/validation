#!/usr/bin/env python3
"""
ddicdi_to_cdif.py - Convert DDI-CDI XML instances to CDIF JSON-LD.

Reads a DDI Cross-Domain Integration (DDI-CDI) 1.0 **XML** instance
(root ``<cdi:DDICDIModels>``, namespace
``http://ddialliance.org/Specification/DDI-CDI/1.0/XMLSchema/``, schema
``ddi-cdi.xsd``) and converts it to CDIF JSON-LD.

DDI-CDI XML is a *flat* list of typed objects under ``DDICDIModels``, linked by
``ddiReference`` (each reference / identifier is a
``dataIdentifier`` + ``registrationAuthorityIdentifier`` + ``versionIdentifier``
triple). The converter indexes every object by its ``dataIdentifier`` and
resolves references to reassemble the graph, then maps the DDI-CDI structure onto
CDIF using the class/attribute crosswalk encoded in the sibling ``ucmism2m``
project (`configuration/ddi-cdi2cdif*_mapping.json`).

STATUS — walking skeleton (phase 1 of the "broadest end-to-end" goal). Mapped:

  DataStore / WideDataSet / PhysicalDataSet -> schema:Dataset
  InstanceVariable                          -> schema:variableMeasured / cdi:InstanceVariable
    name/name                               ->   schema:name
    displayLabel/.../content                ->   schema:description
    hasIntendedDataType/name (SPSS/Stata fmt) -> cdi:intendedDataType (xsd:*)
    <- Measure/Identifier/Dimension/Attribute Component -> cdi:role

Not yet mapped (planned): value domains + CodeList/Code/Category (codelist
profile), WideDataStructure / components (data_structure profile),
PhysicalSegmentLayout / ValueMapping (physical mappings), DataPoint / InstanceValue
(data), and the ProcessStep provenance (cdifProv). See README.md.

Usage:
    python ddicdi_to_cdif.py Examples/XML/SPSS_Example.xml -o out.json
    python ddicdi_to_cdif.py input.xml --id https://catalog.example/dataset/123
"""
import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
try:
    from detect_conformance import detect_conformance, apply_conformance
    _HAVE_DETECT = True
except Exception:
    _HAVE_DETECT = False

CDI_CTX = {
    "schema": "http://schema.org/", "dcterms": "http://purl.org/dc/terms/",
    "dcat": "http://www.w3.org/ns/dcat#",
    "cdi": "http://ddialliance.org/Specification/DDI-CDI/1.0/RDF/",
    "cdif": "https://w3id.org/cdif/",
}

# DDI-CDI DataStructureComponent type -> CDIF cdi:role.
COMPONENT_ROLE = {
    "IdentifierComponent": "Identifier",
    "MeasureComponent": "Measure",
    "DimensionComponent": "Dimension",
    "AttributeComponent": "Attribute",
    "VariableDescriptorComponent": "Descriptor",
    "VariableValueComponent": "Measure",
}

# DDI-CDI DataStructure subtype -> CDIF structured-dataset @type on the distribution.
STRUCTURE_TYPES = ("WideDataStructure", "LongDataStructure",
                   "DimensionalDataStructure", "DataStructure")
DATASET_TYPE = {
    "WideDataStructure": "cdi:StructuredDataSet",
    "DataStructure": "cdi:StructuredDataSet",
    "LongDataStructure": "cdi:LongStructureDataSet",
    "DimensionalDataStructure": "cdi:DimensionalDataSet",
}


def local(elem):
    tag = elem.tag
    return tag.split("}")[-1] if "}" in tag else tag


def txt(elem):
    return " ".join(elem.text.split()) if elem is not None and elem.text else ""


def child(obj, name):
    """First direct child of `obj` with the given local name."""
    if obj is None:
        return None
    for c in list(obj):
        if local(c) == name:
            return c
    return None


def children_named(obj, name):
    """All direct children of `obj` with the given local name."""
    return [c for c in list(obj) if local(c) == name] if obj is not None else []


def as_id(data_identifier):
    """Normalize a DDI-CDI dataIdentifier to a JSON-LD @id fragment."""
    if not data_identifier:
        return None
    return data_identifier if data_identifier.startswith(("#", "http", "urn", "ex:")) \
        else "#" + data_identifier


def text_at(obj, *path):
    """Follow a chain of single-child local names and return the leaf text."""
    cur = obj
    for name in path:
        cur = child(cur, name)
        if cur is None:
            return ""
    return txt(cur)


def object_id(obj):
    """The object's own dataIdentifier (identifier/ddiIdentifier/dataIdentifier
    or a bare ddiIdentifier/dataIdentifier)."""
    ident = child(obj, "identifier")
    if ident is None:
        ident = obj
    return text_at(ident, "ddiIdentifier", "dataIdentifier") \
        or text_at(obj, "ddiIdentifier", "dataIdentifier")


def ref_target(rel):
    """dataIdentifier referenced inside a relationship element's ddiReference."""
    if rel is None:
        return None
    return text_at(rel, "ddiReference", "dataIdentifier") or None


SPSS_NUMERIC = ("F", "N", "E", "COMMA", "DOLLAR", "PCT")


def map_intended_type(fmt):
    """Map an SPSS/Stata display format (e.g. 'F5.0', 'A8') to an xsd type."""
    if not fmt:
        return "xsd:string"
    f = fmt.strip().upper()
    if f.startswith("A") or f.startswith("STRING"):
        return "xsd:string"
    if f.startswith(("DATE", "ADATE", "TIME", "DATETIME")):
        return "xsd:date"
    if f.startswith(SPSS_NUMERIC):
        # F5.0 -> integer; F8.2 -> decimal
        return "xsd:decimal" if ("." in f and not f.rstrip("0").endswith(".")) \
            and f.split(".")[-1] not in ("", "0") else "xsd:integer"
    return "xsd:string"


def build_role_map(objects):
    """InstanceVariable dataIdentifier -> cdi:role, from the components."""
    roles = {}
    for obj in objects:
        role = COMPONENT_ROLE.get(local(obj))
        if not role:
            continue
        var_id = ref_target(
            child(obj, "DataStructureComponent_isDefinedBy_RepresentedVariable"))
        if var_id:
            roles[var_id] = role
    return roles


def build_variable(iv, roles):
    var_id = object_id(iv)
    name = text_at(iv, "name", "name") or var_id.lstrip("#")
    vm = {"@type": ["schema:PropertyValue", "cdi:InstanceVariable"],
          "@id": var_id if var_id.startswith("#") else "#" + var_id,
          "schema:name": name}
    label = text_at(iv, "displayLabel", "languageSpecificString", "content")
    if label:
        vm["schema:description"] = label
    vm["cdi:intendedDataType"] = map_intended_type(text_at(iv, "hasIntendedDataType", "name"))
    if var_id in roles:
        vm["cdi:role"] = roles[var_id]
    return vm


def build_data_structure(objects, index):
    """Map the DDI-CDI DataStructure + its components + primary key to a CDIF
    cdif:isStructuredBy node. Returns (structure_node, dataset_type) or (None, None).

    DDI-CDI:  <WideDataStructure> has DataStructure_has_DataStructureComponent ->
              <MeasureComponent> isDefinedBy_RepresentedVariable -> <InstanceVariable>
    CDIF:     cdi:<X>DataStructure { cdi:has_DataStructureComponent: [
                  cdi:<Component> { cdif:isDefinedBy_RepresentedVariable: {@id: var} } ] }
    """
    struct = next((o for o in objects if local(o) in STRUCTURE_TYPES), None)
    if struct is None:
        return None, None
    stype = local(struct)

    components = []
    for rel in children_named(struct, "DataStructure_has_DataStructureComponent"):
        cid = ref_target(rel)
        cobj = index.get(cid)
        if cobj is None:
            continue
        comp = {"@type": ["cdi:" + local(cobj)], "@id": as_id(cid)}
        var_id = ref_target(
            child(cobj, "DataStructureComponent_isDefinedBy_RepresentedVariable"))
        if var_id:
            comp["cdif:isDefinedBy_RepresentedVariable"] = {"@id": as_id(var_id)}
        components.append(comp)

    node = {"@type": ["cdi:" + stype], "@id": as_id(object_id(struct))}
    if components:
        node["cdi:has_DataStructureComponent"] = components

    pk_id = ref_target(child(struct, "DataStructure_has_PrimaryKey"))
    if pk_id:
        node["cdi:has_PrimaryKey"] = {"@id": as_id(pk_id)}

    return node, DATASET_TYPE.get(stype, "cdi:StructuredDataSet")


def dataset_name(objects, fallback):
    for tag in ("WideDataSet", "DataStore", "PhysicalDataSet", "LogicalRecord"):
        for obj in objects:
            if local(obj) == tag:
                nm = (text_at(obj, "displayLabel", "languageSpecificString", "content")
                      or text_at(obj, "name", "name"))
                if nm:
                    return nm
    return fallback


def dataset_id(objects, explicit_id, base_uri, fallback):
    if explicit_id:
        return explicit_id
    for tag in ("WideDataSet", "DataStore", "PhysicalDataSet"):
        for obj in objects:
            if local(obj) == tag:
                oid = object_id(obj)
                if oid:
                    return f"{base_uri}:{oid.lstrip('#')}"
    return f"{base_uri}:{fallback}"


def build_catalog_record(dataset_iri, name, nvars):
    note = (
        f"Metadata harvested from a DDI-CDI 1.0 XML instance "
        f"(cdi:DDICDIModels) and converted to CDIF by ddicdi_to_cdif.py. "
        f"DataStore/WideDataSet -> schema:Dataset; {nvars} cdi:InstanceVariable "
        f"-> schema:variableMeasured (name, displayLabel, hasIntendedDataType, "
        f"and cdi:role from the DataStructureComponent). Value domains, code "
        f"lists, data structure, physical mappings, data and provenance are not "
        f"yet carried over (walking skeleton)."
    )
    return {
        "@type": ["schema:Dataset"],
        "schema:additionalType": [{"@id": "dcat:CatalogRecord"}],
        "@id": dataset_iri + "#cdif-catalog-record",
        "schema:name": f"Metadata record for: {name[:120]}",
        "schema:about": {"@id": dataset_iri},
        "schema:description": note,
        "dcterms:conformsTo": [
            {"@id": "https://w3id.org/cdif/core/1.1"},
            {"@id": "https://w3id.org/cdif/discovery/1.1"},
            {"@id": "https://w3id.org/cdif/data_description/1.1"}],
    }


def convert(xml_path, explicit_id=None, base_uri="urn:ddi-cdi", detect=True):
    root = ET.parse(xml_path).getroot()
    if local(root) != "DDICDIModels":
        print(f"WARN: root is <{local(root)}>, expected <cdi:DDICDIModels>",
              file=sys.stderr)
    objects = list(root)
    stem = Path(xml_path).stem
    index = {object_id(o): o for o in objects if object_id(o)}

    roles = build_role_map(objects)
    variables = [build_variable(o, roles) for o in objects
                 if local(o) == "InstanceVariable"]

    iri = dataset_id(objects, explicit_id, base_uri, stem)
    name = dataset_name(objects, stem)

    doc = {
        "@context": dict(CDI_CTX),
        "@id": iri,
        "@type": ["schema:Dataset"],
        "schema:name": name,
        "schema:identifier": {"@type": ["schema:PropertyValue"],
                              "schema:value": iri.split(":")[-1]},
        "schema:dateModified": "1900-01-01",
        "schema:license": ["http://www.opengis.net/def/nil/OGC/0/missing"],
    }
    if variables:
        doc["schema:variableMeasured"] = variables
    # DDI-CDI PhysicalDataSet is the data file, but carries no resolvable
    # download URL; emit a DataDownload with the OGC nil value so the CDIF
    # url-or-distribution requirement is met honestly.
    dist = {
        "@type": ["schema:DataDownload"],
        "schema:name": f"{name} (data file)",
        "schema:contentUrl": "http://www.opengis.net/def/nil/OGC/0/missing",
    }
    # Phase 3 - data structure: type the distribution as a structured dataset and
    # attach the DDI-CDI DataStructure + components via cdif:isStructuredBy.
    structure, dataset_type = build_data_structure(objects, index)
    if structure is not None:
        dist["@type"] = ["schema:DataDownload", dataset_type]
        dist["cdif:isStructuredBy"] = structure
    doc["schema:distribution"] = [dist]
    doc["schema:subjectOf"] = build_catalog_record(iri, name, len(variables))

    if detect and _HAVE_DETECT:
        try:
            uris = detect_conformance(doc)
            if uris:
                apply_conformance(doc, uris)
        except Exception:
            pass
    return doc


def main():
    ap = argparse.ArgumentParser(
        description="Convert DDI-CDI 1.0 XML instances to CDIF JSON-LD")
    ap.add_argument("input", help="Input DDI-CDI XML file (cdi:DDICDIModels)")
    ap.add_argument("-o", "--output", help="Output JSON file (default: stdout)")
    ap.add_argument("--id", dest="explicit_id",
                    help="Explicit dataset IRI for @id (overrides auto-derived)")
    ap.add_argument("--base-uri", default="urn:ddi-cdi",
                    help="Base for minting @id (default: urn:ddi-cdi)")
    ap.add_argument("--static-conformance", action="store_true",
                    help="Keep the built-in conformsTo instead of detecting it")
    args = ap.parse_args()

    doc = convert(args.input, explicit_id=args.explicit_id,
                  base_uri=args.base_uri, detect=not args.static_conformance)
    out = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        Path(args.output).write_text(out, encoding="utf-8")
        print(f"Written: {args.output} "
              f"({len(doc.get('schema:variableMeasured', []))} vars)")
    else:
        print(out)


if __name__ == "__main__":
    main()
