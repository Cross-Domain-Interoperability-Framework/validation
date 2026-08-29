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

STATUS — phased build toward the "broadest end-to-end" goal. Mapped so far:

  DataStore / WideDataSet / PhysicalDataSet -> schema:Dataset                (phase 1)
  InstanceVariable                          -> schema:variableMeasured        (phase 1)
    name, displayLabel, hasIntendedDataType, cdi:role (from its Component)
    Substantive + Sentinel ValueDomain -> CodeList -> cdif:hasValuesFrom /
                                               cdif:EnumerationDomain (valueType)
                                               -> skos:ConceptScheme/Concept (phase 2, 6)
    ValueAndConceptDescription/classificationLevel -> cdif:classificationLevel(phase 2)
    catalogDetails/title, physicalFileName, recordCount -> discovery enrichment (phase 6)
  WideDataStructure + components + PrimaryKey -> distribution cdi:*DataSet +
                                               cdif:isStructuredBy /
                                               cdi:has_DataStructureComponent  (phase 3)

  Activity (Sequence-invoked) + Step/Parameter/Organization/ProductionEnvironment
                                            -> prov:wasGeneratedBy (schema:Action/
                                               prov:Activity, actionProcess/HowTo,
                                               agent, location, used, result)     (phase 5)

  PhysicalSegmentLayout / ValueMapping / ValueMappingPosition
                                            -> distribution cdi:isDelimited /
                                               cdi:hasPhysicalMapping (index,
                                               physicalDataType, formats var)   (phase 4)

Out of scope: DataPoint / InstanceValue (the actual data values) - CDIF is a
metadata framework. See README.md.

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
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "prov": "http://www.w3.org/ns/prov#",
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


def build_concept_scheme(codelist, index):
    """Map a DDI-CDI CodeList (CodeList_has_Code -> Code -> Category + Notation)
    to a CDIF skos:ConceptScheme with skos:Concept entries."""
    scheme_id = as_id(object_id(codelist))
    scheme = {"@type": ["skos:ConceptScheme"], "@id": scheme_id}
    label = text_at(codelist, "name", "name")
    if label and not label.startswith("#"):
        scheme["skos:prefLabel"] = label

    concepts = []
    for rel in children_named(codelist, "CodeList_has_Code"):
        code = index.get(ref_target(rel))
        if code is None:
            continue
        cat = index.get(ref_target(child(code, "Code_denotes_Category")))
        notn = index.get(ref_target(child(code, "Code_uses_Notation")))
        concept = {"@type": ["skos:Concept"],
                   "@id": as_id(object_id(code)),
                   "skos:inScheme": [{"@id": scheme_id}]}
        notation = text_at(notn, "content", "content") if notn is not None else ""
        if notation:
            concept["skos:notation"] = notation
        prefl = (text_at(cat, "displayLabel", "languageSpecificString", "content")
                 or text_at(cat, "name", "name")) if cat is not None else ""
        if prefl:
            concept["skos:prefLabel"] = prefl
        concepts.append(concept)
    if concepts:
        scheme["skos:hasTopConcept"] = concepts
    return scheme


# (InstanceVariable relation, ValueDomain type, ValueType) for the two domains.
_VALUE_DOMAINS = [
    ("RepresentedVariable_takesSubstantiveValuesFrom_SubstantiveValueDomain",
     "SubstantiveValueDomain", "substantive"),
    ("RepresentedVariable_takesSentinelValuesFrom_SentinelValueDomain",
     "SentinelValueDomain", "sentinel"),
]


def value_domains(iv, index):
    """Resolve an InstanceVariable's value domains. Returns a list of
    (codelist_obj_or_None, value_type, classificationLevel_or_None) for the
    substantive domain and (when present) the sentinel domain.

    Per the CDIF value-domain guidance
    (Cross-Domain-Interoperability-Framework/profile-datadescription#1): use the
    substantive domain always; when the source distinguishes missing-value codes,
    also emit the sentinel domain — each flagged by value type — so a processor
    need not merge the two.
    """
    out = []
    for iv_rel, vd_type, vtype in _VALUE_DOMAINS:
        vd = index.get(ref_target(child(iv, iv_rel)))
        if vd is None:
            continue
        codelist = index.get(ref_target(
            child(vd, f"{vd_type}_takesValuesFrom_EnumerationDomain")))
        vacd = index.get(ref_target(
            child(vd, f"{vd_type}_isDescribedBy_ValueAndConceptDescription")))
        level = text_at(vacd, "classificationLevel") if vacd is not None else ""
        out.append((codelist, vtype, level or None))
    return out


def build_variable(iv, roles, index):
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

    # Phase 2 + 6 - substantive and sentinel value domains / code lists.
    enumerations = []
    for codelist, vtype, level in value_domains(iv, index):
        if vtype == "substantive" and level:
            vm["cdif:classificationLevel"] = level
        if codelist is not None:
            enumerations.append({
                "@type": ["cdif:EnumerationDomain"],
                "cdif:valueType": vtype,
                "cdif:references": build_concept_scheme(codelist, index),
            })
    if enumerations:
        vm["cdif:hasValuesFrom"] = enumerations
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


def _activity_tree(main, index):
    """Main activity + all descendants reachable via hasSubActivity (BFS)."""
    seen, queue, out = set(), [main], []
    while queue:
        act = queue.pop(0)
        aid = object_id(act)
        if aid in seen:
            continue
        seen.add(aid)
        out.append(act)
        for rel in children_named(act, "Activity_hasSubActivity_Activity"):
            sub = index.get(ref_target(rel))
            if sub is not None:
                queue.append(sub)
    return out


def _pick_main_activity(objects, index):
    activities = [o for o in objects if local(o) == "Activity"]
    if not activities:
        return None
    for o in objects:
        if local(o) == "Sequence":
            inv = ref_target(child(o, "ControlLogic_invokes_Activity"))
            if inv in index and local(index[inv]) == "Activity":
                return index[inv]
    sub_ids = {ref_target(r) for a in activities
               for r in children_named(a, "Activity_hasSubActivity_Activity")}
    roots = [a for a in activities if object_id(a) not in sub_ids]
    return roots[0] if roots else activities[0]


def build_step(step):
    node = {"@type": ["schema:HowToStep"]}
    nm = text_at(step, "name", "name")
    if nm:
        node["schema:name"] = nm
    desc = text_at(step, "description")
    lang = text_at(step, "scriptingLanguage", "entryValue")
    if lang:
        desc = (desc + f" [{lang}]").strip() if desc else lang
    if desc:
        node["schema:description"] = desc
    uri = text_at(step, "script", "commandFile", "uri")
    if uri:
        node["schema:url"] = uri
    return node


def build_provenance(objects, index):
    """Map the DDI-CDI process model to a cdifProv prov:wasGeneratedBy activity.

        Activity (invoked by Sequence)      -> ["schema:Action","prov:Activity"]
          name / description                ->   schema:name / schema:description
          entityUsed/uri  (over the tree)   ->   prov:used ({@id})
          entityProduced/uri                ->   schema:result ({@id})
          Activity_has_Step -> Step         ->   schema:actionProcess (HowTo) / schema:step
          Organization                      ->   schema:agent
          ProductionEnvironment             ->   schema:location
    """
    main = _pick_main_activity(objects, index)
    if main is None:
        return None
    tree = _activity_tree(main, index)

    used, produced, steps = [], [], []
    for act in tree:
        for e in children_named(act, "entityUsed"):
            u = text_at(e, "uri")
            if u:
                used.append({"@id": u})
        for e in children_named(act, "entityProduced"):
            u = text_at(e, "uri")
            if u:
                produced.append({"@id": u})
        for rel in children_named(act, "Activity_has_Step"):
            s = index.get(ref_target(rel))
            if s is not None:
                steps.append(build_step(s))

    node = {"@type": ["schema:Action", "prov:Activity"]}
    nm = text_at(main, "name", "name")
    desc = text_at(main, "description") \
        or text_at(main, "displayLabel", "languageSpecificString", "content")
    if nm:
        node["schema:name"] = nm
    if desc:
        node["schema:description"] = desc

    org = next((o for o in objects if local(o) == "Organization"), None)
    if org is not None:
        org_name = text_at(org, "organizationName", "name")
        if org_name:
            node["schema:agent"] = {"@type": ["schema:Organization"],
                                    "schema:name": org_name}
    env = next((o for o in objects if local(o) == "ProductionEnvironment"), None)
    if env is not None:
        env_name = text_at(env, "name", "name")
        if env_name:
            node["schema:location"] = {"@type": ["schema:Place"],
                                       "schema:name": env_name}
    if used:
        node["prov:used"] = used
    if produced:
        node["schema:result"] = produced if len(produced) > 1 else produced[0]
    if steps:
        howto = {"@type": ["schema:HowTo"], "schema:step": steps}
        if nm:
            howto["schema:name"] = nm
        node["schema:actionProcess"] = howto
    return node


def build_physical_mappings(objects, index):
    """Map DDI-CDI physical layout to CDIF cdi:hasPhysicalMapping entries.

        InstanceVariable_has_ValueMapping -> ValueMapping (the physical column)
        ValueMappingPosition_indexes_ValueMapping, value -> column index
        PhysicalSegmentLayout isDelimited / isFixedWidth -> distribution flags

    Returns (mappings, isDelimited, isFixedWidth).
    """
    vm_index = {}
    for o in objects:
        if local(o) == "ValueMappingPosition":
            vm = ref_target(child(o, "ValueMappingPosition_indexes_ValueMapping"))
            val = text_at(o, "value")
            if vm and val != "":
                try:
                    vm_index[vm] = int(val)
                except ValueError:
                    vm_index[vm] = val

    psl = next((o for o in objects if local(o) == "PhysicalSegmentLayout"), None)
    is_delim = text_at(psl, "isDelimited") if psl is not None else ""
    is_fixed = text_at(psl, "isFixedWidth") if psl is not None else ""

    mappings = []
    for iv in objects:
        if local(iv) != "InstanceVariable":
            continue
        vm = ref_target(child(iv, "InstanceVariable_has_ValueMapping"))
        if not vm:
            continue
        entry = {"schema:name": text_at(iv, "name", "name"),
                 "cdi:physicalDataType": map_intended_type(
                     text_at(iv, "hasIntendedDataType", "name")),
                 "cdi:formats_InstanceVariable": {"@id": as_id(object_id(iv))}}
        if vm in vm_index:
            entry["cdi:index"] = vm_index[vm]
        mappings.append(entry)
    mappings.sort(key=lambda m: m.get("cdi:index", 1_000_000))
    return mappings, is_delim, is_fixed


_DATASET_LEVEL = ("DataStore", "WideDataSet", "PhysicalDataSet", "LogicalRecord",
                  "Catalog")


def catalog_title(objects):
    """A human title from catalogDetails on any dataset-level object, if present."""
    for o in objects:
        if local(o) in _DATASET_LEVEL:
            cd = child(o, "catalogDetails")
            if cd is not None:
                title = text_at(cd, "title", "languageSpecificString", "content")
                if title:
                    return title
    return None


def physical_file_name(objects):
    for o in objects:
        if local(o) == "PhysicalDataSet":
            fn = text_at(o, "physicalFileName")
            if fn:
                return fn
    return None


def record_count(objects):
    for o in objects:
        if local(o) == "DataStore":
            rc = text_at(o, "recordCount")
            if rc:
                return rc
    return None


def dataset_name(objects, fallback):
    for tag in ("WideDataSet", "DataStore", "PhysicalDataSet", "LogicalRecord",
                "Activity", "Sequence"):
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
    variables = [build_variable(o, roles, index) for o in objects
                 if local(o) == "InstanceVariable"]

    iri = dataset_id(objects, explicit_id, base_uri, stem)
    # Phase 6 - discovery enrichment: prefer a real catalogDetails title.
    name = catalog_title(objects) or dataset_name(objects, stem)

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
        "schema:name": physical_file_name(objects) or f"{name} (data file)",
        "schema:contentUrl": "http://www.opengis.net/def/nil/OGC/0/missing",
    }
    rc = record_count(objects)
    if rc:
        dist["schema:additionalProperty"] = [{
            "@type": ["schema:PropertyValue"],
            "schema:name": "record count", "schema:value": rc}]
    # Phase 3 - data structure: type the distribution as a structured dataset and
    # attach the DDI-CDI DataStructure + components via cdif:isStructuredBy.
    structure, dataset_type = build_data_structure(objects, index)
    if structure is not None:
        dist["@type"] = ["schema:DataDownload", dataset_type]
        dist["cdif:isStructuredBy"] = structure
    # Phase 4 - physical mappings: variable -> column position/format.
    mappings, is_delim, is_fixed = build_physical_mappings(objects, index)
    if is_delim:
        dist["cdi:isDelimited"] = (is_delim == "true")
    if is_fixed:
        dist["cdi:isFixedWidth"] = (is_fixed == "true")
    if mappings:
        dist["cdi:hasPhysicalMapping"] = mappings
    doc["schema:distribution"] = [dist]

    # Phase 5 - provenance: map the DDI-CDI process model (Activity/Step/...) to
    # a cdifProv prov:wasGeneratedBy activity, when present.
    provenance = build_provenance(objects, index)
    if provenance is not None:
        doc["prov:wasGeneratedBy"] = [provenance]

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
