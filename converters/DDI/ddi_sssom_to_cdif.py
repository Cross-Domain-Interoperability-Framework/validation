#!/usr/bin/env python3
"""Data-driven DDI Codebook -> CDIF converter.

Reads the SSSOM mapping tables (converters/mappings/ddi_mappings.json) and applies
them generically, so the worksheets are the single source of truth: edit a TSV,
run sync_ddi_mappings.py, and the mapping takes effect here with no code change.

Contexts implemented
--------------------
* dataset singletons        $.schema:<prop>                     (incl. nested)
* per-variable              $.schema:variableMeasured[*].<leaf> (one item per <var>)
* per-distribution          $.schema:distribution[*].<leaf>     (one per <fileDscr>)
* provenance activity       $.prov:wasGeneratedBy[*].<leaf>     (one Action/Activity)
* derived source            $.prov:wasDerivedFrom[*].<leaf>     (one prov:Entity)
* related links             $.schema:relatedLink...             (one item per source field)

Structured constructions (NOT flat-mappable) are delegated to the hand-coded
engine ddi122_to_cdif.py so they are built identically and never re-implemented:
the enumerated value domains from <catgry> (cdi:takesSubstantiveValuesFrom /
takesSentinelValuesFrom referencing deduplicated skos:ConceptScheme code lists
emitted as sibling @graph nodes) and the per-variable statistics from
<sumStat>/<catStat> (cdif:isDescribedBy_StatisticsCollection). Every OTHER
mapping in the worksheets is still applied data-driven; only these deep targets
(cdi:takesSubstantiveValuesFrom, cdi:takesSentinelValuesFrom,
cdif:isDescribedBy_StatisticsCollection, schema:min/maxValue) are delegated.

Concatenation convention (from the worksheet)
---------------------------------------------
Several DDI fields on one scalar target are joined with newlines, each line
prefixed by that mapping's `object_label` ("label: value"), empties skipped,
identical values de-duplicated. A lone contributor is placed as a plain value.
List targets (keywords, spatialCoverage, additionalProperty, prov:used,
relatedLink) collect items instead of concatenating.

Malformed object_json_path values (unbalanced brackets, embedded quotes/commas
-- e.g. the sampleFrame pseudo-paths) are skipped and reported with --verbose;
fix them in the worksheet and they light up here automatically.
"""
import argparse
import datetime
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
MAPPINGS_JSON = os.path.normpath(os.path.join(HERE, "..", "mappings", "ddi_mappings.json"))

# Reuse the hand-coded engine's structured builders verbatim, so the
# value-domain / code-list / statistics construction is preserved exactly rather
# than re-implemented. The data-driven pass below still applies every other
# SSSOM mapping; only these structured targets are delegated to ddi122.
sys.path.insert(0, HERE)
from ddi122_to_cdif import (  # noqa: E402
    parse_variables as _parse_vars_struct, dedup_variables as _dedup_vars,
    _var_signature, CodeListRegistry, _value_domains, _statistics_collection,
    parse_files as _parse_files, build_distributions as _build_dists,
    parse_access as _parse_access, first_text as _first_text, find as _find,
    NIL_MISSING,
)

CONTEXT = {
    "schema": "http://schema.org/", "dcterms": "http://purl.org/dc/terms/",
    "dcat": "http://www.w3.org/ns/dcat#", "prov": "http://www.w3.org/ns/prov#",
    "cdi": "http://ddialliance.org/Specification/DDI-CDI/1.0/RDF/",
    "cdif": "https://w3id.org/cdif/", "skos": "http://www.w3.org/2004/02/skos/core#",
    "csvw": "http://www.w3.org/ns/csvw#", "spdx": "http://spdx.org/rdf/terms#",
    "cdifq": "http://crossdomaininteroperability.org/cdifq/",
    "dqv": "http://www.w3.org/ns/dqv#", "geo": "http://www.opengis.net/ont/geosparql#",
    "oa": "http://www.w3.org/ns/oa#", "bios": "https://bioschemas.org/",
}
XSD_TYPE = {"numeric": "xsd:decimal", "character": "xsd:string"}
LIST_LEAF = {"schema:keywords"}
# provenance / related-link target heads and the context key each builds
PROV_HEADS = {"prov:wasGeneratedBy": "activity", "prov:wasDerivedFrom": "derived",
              "schema:relatedLink": "related"}


def strip_ns(tag):
    return tag.split("}", 1)[-1]


def iter_local(root, name):
    for e in root.iter():
        if strip_ns(e.tag) == name:
            yield e


def text_of(elem):
    return " ".join("".join(elem.itertext()).split())


def descend(elem, parts):
    attr = None
    if parts and "@" in parts[-1]:
        parts = list(parts)
        parts[-1], attr = parts[-1].split("@", 1)
        if parts[-1] == "":
            parts = parts[:-1]
    nodes = [elem]
    for p in parts:
        nxt = []
        for n in nodes:
            nxt += [c for c in list(n) if strip_ns(c.tag) == p]  # direct children only
        nodes = nxt
    if attr:
        return [n.get(attr) for n in nodes if n.get(attr)]
    return nodes


def values_at(elem, parts):
    out = []
    for node in descend(elem, parts):
        s = node if isinstance(node, str) else text_of(node)
        if s:
            out.append(s)
    return out


# ---- target-path parsing -------------------------------------------------

def split_target(jp):
    body = jp[2:] if jp.startswith("$.") else jp.lstrip("$")
    if body.startswith("schema:variableMeasured[*]"):
        return "variable", body[len("schema:variableMeasured[*]"):].lstrip(".")
    if body.startswith("schema:distribution[*]"):
        return "distribution", body[len("schema:distribution[*]"):].lstrip(".")
    for head, ctx in PROV_HEADS.items():
        if body == head or body.startswith(head + "[*]") or body.startswith(head + "."):
            leaf = body[len(head):].lstrip("[*]").lstrip(".")
            return ctx, leaf
    return "dataset", body


def clean_leaf(leaf):
    """Normalise a leaf path: drop [filter] segments (keep [*] as a list marker),
    reject anything still malformed. Returns [(key, is_list), ...] or None."""
    protected = leaf.replace("[*]", "\0")
    protected = re.sub(r"\[[^\]]*\]", "", protected)          # drop [role = x] etc.
    if any(c in protected for c in '[]",') or "  " in protected or " " in protected.strip():
        return None
    segs = []
    for part in protected.split("."):
        if not part:
            continue
        is_list = part.endswith("\0")
        key = part.replace("\0", "")
        if key:
            segs.append((key, is_list))
    return segs or None


# ---- value shaping / concatenation --------------------------------------

def concat(contribs):
    parts, seen = [], set()
    for lbl, v in contribs:
        if isinstance(v, list):
            v = " ".join(v)
        if v and v not in seen:
            seen.add(v)
            parts.append((lbl, v))
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0][1]
    return "\n".join(f"{lbl}: {v}" for lbl, v in parts)


def flat_values(contribs):
    return [v for _, vs in contribs for v in (vs if isinstance(vs, list) else [vs]) if v]


def array_distinct(contribs):
    """[*] target -> array of distinct values."""
    out, seen = [], set()
    for v in flat_values(contribs):
        if v not in seen:
            seen.add(v); out.append(v)
    return out or None


def shape_conditions(contribs):
    """schema:conditionsOfAccess -> an array of plain "label: value" strings, one
    per contributing DDI use-statement field. The discovery rightsProperty shape
    accepts a rights value that is an IRI, a plain string, or a CreativeWork *with*
    a resolvable schema:url; DDI use-statement text carries no URL, so a labelled
    string is the correct form (a url-less CreativeWork matches none of the three
    and fails the shape). This mirrors ddi122's plain-string conditionsOfAccess,
    keeping the object_label as a prefix so the originating field stays visible."""
    out = []
    for lbl, vs in contribs:
        for v in (vs if isinstance(vs, list) else [vs]):
            if v:
                out.append(f"{lbl}: {v}" if lbl else v)
    return out or None


def shape_dataset(leaf, object_id, contribs):
    flat = flat_values(contribs)
    if leaf in LIST_LEAF:
        out, seen = [], set()
        for v in flat:
            if v not in seen:
                seen.add(v); out.append(v)
        return out or None
    if leaf == "schema:spatialCoverage" or object_id == "schema:spatialCoverage":
        return [{"@type": ["schema:Place"], "schema:name": v} for v in flat] or None
    if object_id == "schema:creator":
        return {"@list": [{"@type": ["schema:Person"], "schema:name": v} for v in flat]} if flat else None
    if object_id in ("schema:publisher", "schema:provider", "schema:maintainer", "schema:funder"):
        return {"@type": ["schema:Organization"], "schema:name": flat[0]} if flat else None
    return concat([(lbl, " ".join(vs) if isinstance(vs, list) else vs) for lbl, vs in contribs])


def build_contributors(root, maps, paths):
    """Structured schema:contributor from DDI <producer>/<contact> elements,
    preserving the XML attributes (role, affiliation, URI, email) that the flat
    value pipeline would otherwise drop. The SSSOM rows declare which elements
    are contributors and their roleName (object_label); the Role / Organization /
    ContactPoint grammar -- which a flat crosswalk cannot express -- is built here.

      <producer role="R" affiliation="A">Name</producer>
        -> Role{roleName} / Organization{name=Name, description=R, affiliation=A};
           each producer is its own organization.
      <contact affiliation="Org" email="E" URI="U">Purpose</contact>   (distStmt form)
        -> Role{roleName} / Organization{name=Org} carrying one ContactPoint
           {description=Purpose, email=E, url=U} per contact; contacts that share
           an organization merge into a single Organization.
      <contact affiliation="" URI="U" email="E">Org name</contact>     (useStmt form)
        -> Organization{name=Org name, url=U}: with no affiliation the element
           text *is* the organization, so it names the org rather than a purpose.
    """
    roles = []
    for p in paths:
        role_name = maps[p]["object_label"] or "contributor"
        tag = p.split(".")[-1]
        elems = [n for n in descend(root, p.split(".")) if not isinstance(n, str)]
        if tag == "producer":
            for e in elems:
                name = text_of(e)
                if not name:
                    continue
                org = {"@type": ["schema:Organization"], "schema:name": name}
                if (e.get("role") or "").strip():
                    org["schema:description"] = e.get("role").strip()
                if (e.get("affiliation") or "").strip():
                    org["schema:affiliation"] = {"@type": ["schema:Organization"],
                                                 "schema:name": e.get("affiliation").strip()}
                roles.append({"@type": ["schema:Role"], "schema:roleName": role_name,
                              "schema:contributor": org})
        else:  # <contact>
            by_org, order = {}, []
            for e in elems:
                text = text_of(e)
                aff = (e.get("affiliation") or "").strip()
                email = (e.get("email") or "").strip()
                uri = (e.get("URI") or "").strip()
                org_name = aff or text
                if not org_name:
                    continue
                if org_name not in by_org:
                    by_org[org_name] = {"@type": ["schema:Organization"],
                                        "schema:name": org_name}
                    order.append(org_name)
                org = by_org[org_name]
                if aff:
                    cp = {"@type": ["schema:ContactPoint"]}
                    if text:
                        cp["schema:description"] = text
                    if email:
                        cp["schema:email"] = email
                    if uri:
                        cp["schema:url"] = uri
                    if len(cp) > 1:
                        org.setdefault("schema:contactPoint", []).append(cp)
                else:
                    if uri:
                        org["schema:url"] = uri
                    if email:
                        org.setdefault("schema:contactPoint", []).append(
                            {"@type": ["schema:ContactPoint"], "schema:email": email})
            for org_name in order:
                roles.append({"@type": ["schema:Role"], "schema:roleName": role_name,
                              "schema:contributor": by_org[org_name]})
    return roles or None


def set_nested(container, keys, value):
    if value is None or not keys:
        return
    d = container
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = value


def shape_place(v):
    """A spatialCoverage value -> schema:Place. A long string keeps a short
    derived name (text before the first ':' or the first few words) and carries
    the full text as schema:description."""
    place = {"@type": ["schema:Place"]}
    if ":" in v:
        place["schema:name"] = v.split(":", 1)[0].strip()
        place["schema:description"] = v
    elif len(v.split()) > 6:
        place["schema:name"] = " ".join(v.split()[:5]) + "…"
        place["schema:description"] = v
    else:
        place["schema:name"] = v
    return place


# ---- data extraction helpers --------------------------------------------

def gather(elem, subj_paths, mapping, anchor=""):
    """Collect (label, values) for each subject, relative to a DDI anchor path.
    anchor is a string prefix (e.g. 'dataDscr.var'); the remainder -- including a
    trailing '@attr' on the anchor element itself -- is navigated within elem."""
    contribs = []
    for path in subj_paths:
        rel = path[len(anchor):].lstrip(".") if anchor else path
        parts = rel.split(".") if rel else []
        label = mapping[path]["object_label"] or (parts[-1] if parts else path.split(".")[-1])
        contribs.append((label, values_at(elem, parts)))
    return contribs


# ---- provenance / related-link builders ---------------------------------

def build_activity(root, items, maps, skipped):
    """items: list of subject paths whose target head is prov:wasGeneratedBy."""
    act = {"@type": ["schema:Action", "prov:Activity"]}
    frame = {}  # the single "used" entity assembled from direct prov:used subfields (sample frame)
    groups = {}
    for path in items:
        _, leaf = split_target(maps[path]["object_json_path"])
        segs = clean_leaf(leaf)
        if segs is None:
            skipped.append(path); continue
        groups.setdefault(tuple(s[0] for s in segs), []).append(path)
    for keys, paths in groups.items():
        contribs = gather(root, paths, maps)
        vals = flat_values(contribs)
        leafstr = ".".join(keys)
        if leafstr == "schema:additionalProperty":
            for lbl, vs in [(maps[p]["object_label"], values_at(root, p.split("."))) for p in paths]:
                for v in vs:
                    act.setdefault("schema:additionalProperty", []).append(
                        {"@type": ["schema:PropertyValue"], "schema:name": lbl, "schema:value": v})
        elif keys and keys[0] == "prov:used":
            if "schema:instrument" in keys:                       # instrument wrapper, one per value
                for v in vals:
                    act.setdefault("prov:used", []).append(
                        {"schema:instrument": {"@type": ["schema:Thing"], "schema:name": v}})
            elif "bios:computationalTool" in keys:                # software/tool, one per value
                for v in vals:
                    act.setdefault("prov:used", []).append(
                        {"bios:computationalTool": {"schema:name": v}})
            else:                                                 # direct subfield of the used entity
                prop = keys[-1]
                if prop == "schema:conditionsOfAccess":
                    val = shape_conditions(contribs)
                elif prop == "schema:contributor":
                    val = [{"@type": ["schema:Person"], "schema:name": x}
                           for x in flat_values(contribs)] or None
                else:
                    val = concat(contribs)
                if val is not None:
                    frame[prop] = val
        elif keys and keys[0] == "schema:actionProcess":
            hp = act.setdefault("schema:actionProcess", {"@type": ["schema:HowTo"]})
            sub = "schema:step" if keys[-1] == "schema:step" else "schema:description"
            val = concat(contribs)
            if val:
                hp[sub] = (hp[sub] + "\n" + val) if hp.get(sub) else val
        elif leafstr == "schema:agent":
            val = concat(contribs)
            if val:
                act["schema:agent"] = {"@type": ["schema:Organization"], "schema:name": val}
        else:
            val = concat(contribs)
            set_nested(act, list(keys), val)
    if frame:
        act.setdefault("prov:used", []).append(
            {"@type": ["schema:CreativeWork", "prov:Entity"],
             "schema:additionalType": "sampleFrame", **frame})
    return act


def parse_role(leaf):
    """Return the role named in a schema:contributor[role = X] filter, or None."""
    m = re.search(r"\[\s*role\s*=\s*([^\]]+)\]", leaf)
    return m.group(1).strip() if m else None


def build_derived(root, items, maps, skipped):
    # The value on prov:wasDerivedFrom is a cdifReference typed schema:CreativeWork,
    # so the entity carries that type and the source-citation properties sit
    # directly on it (a leading schema:CreativeWork path segment is the type, not
    # a key, and is dropped).
    node = {"@type": ["prov:Entity", "schema:CreativeWork"]}
    groups = {}
    for path in items:
        _, leaf = split_target(maps[path]["object_json_path"])
        role = parse_role(leaf)
        segs = clean_leaf(leaf)
        if segs is None:
            skipped.append(path); continue
        if segs and segs[0][0] == "schema:CreativeWork":
            segs = segs[1:]
        if not segs:
            continue
        keys = tuple(s[0] for s in segs)
        groups.setdefault((keys, segs[-1][1], role), []).append(path)
    for (keys, is_list, role), paths in groups.items():
        contribs = gather(root, paths, maps)
        if role and keys and keys[-1] in ("schema:contributor", "schema:creator"):
            vals = flat_values(contribs)
            if not vals:
                continue
            arr = node.setdefault(keys[-1], [])
            if not isinstance(arr, list):
                arr = node[keys[-1]] = [arr]
            for v in vals:
                arr.append({"@type": ["schema:Person"], "schema:name": v,
                            "schema:roleName": role})
        elif is_list:                                  # [*] -> an array of distinct values
            vals, seen = [], set()
            for v in flat_values(contribs):
                if v not in seen:
                    seen.add(v); vals.append(v)
            if vals:
                set_nested(node, list(keys), vals)
        else:
            set_nested(node, list(keys), concat(contribs))
    return node if len(node) > 1 else None


def build_related(root, items, maps, skipped):
    links = []
    for path in items:
        m = maps[path]
        segs = clean_leaf(split_target(m["object_json_path"])[1])
        if segs is None:
            skipped.append(path); continue
        for v in values_at(root, path.split(".")):
            links.append({"schema:linkRelationship": m["object_label"],
                          "schema:target": {"schema:name": v}})
    return links


# ---- conversion ----------------------------------------------------------

def load_mappings(version):
    allm = json.load(open(MAPPINGS_JSON, encoding="utf-8"))
    merged = {}
    merged.update(allm.get("ddi-common-to-cdif", {}))
    merged.update(allm.get(f"ddi{version}-to-cdif", {}))
    out = {}
    for subj, m in merged.items():
        path = subj.split(":", 1)[1] if ":" in subj else subj
        out[path] = m
    return out


def derive_dataset_id(root, xml_path, base_uri="urn:ddi"):
    """Dataset @id, source-agnostically, the same way ddi122_to_cdif.py does:
    the access-location URL (dataAccs/accsPlac/@URI) when present, else a urn
    minted from the study IDNo (or the filename as a last resort)."""
    stdy = _find(root, "stdyDscr")
    cite = _find(stdy, "citation") if stdy is not None else None
    id_no = (_first_text(cite, "IDNo") or _first_text(root, "IDNo")
             or os.path.splitext(os.path.basename(xml_path))[0])
    access_url = _parse_access(stdy)[0] if stdy is not None else None
    return access_url or f"{base_uri}:{id_no}"


def convert(xml_path, doi_url=None, version="25", detect=True, verbose=False,
            base_uri="urn:ddi"):
    root = ET.parse(xml_path).getroot()
    if not doi_url:
        doi_url = derive_dataset_id(root, xml_path, base_uri)
    maps = load_mappings(version)

    ds_by_leaf, var_by_leaf, dist_by_leaf = {}, {}, {}
    prov = {"activity": [], "derived": [], "related": []}
    for path, m in maps.items():
        if not m["object_id"].strip():
            continue
        ctx, leaf = split_target(m["object_json_path"])
        if ctx in prov:
            prov[ctx].append(path)
        elif ctx == "dataset":
            ds_by_leaf.setdefault((leaf, m["object_id"]), []).append(path)
        elif ctx == "variable":
            var_by_leaf.setdefault((leaf, m["object_id"]), []).append(path)
        elif ctx == "distribution":
            dist_by_leaf.setdefault((leaf, m["object_id"]), []).append(path)

    doc = {"@context": CONTEXT, "@id": doi_url, "@type": ["schema:Dataset"]}

    desc_overflow, kw_terms, places = [], [], []
    for (leaf, oid), paths in ds_by_leaf.items():
        if leaf == "schema:keywords" or leaf.startswith("schema:keywords."):
            # Keyword targets. A value >4 words is concatenated onto the dataset
            # description, labelled by the mapping's object_label. A short value
            # becomes a keyword DefinedTerm; when it came from a field OTHER than
            # subject/keyword (path $.schema:keywords.schema:name), its
            # schema:about is the object_label (e.g. "Analysis Unit", "Data
            # Kind") so the origin is retained.
            plain = (leaf == "schema:keywords")     # subject/keyword -> genuine keyword
            for p in paths:
                label = maps[p]["object_label"] or p.split(".")[-1]
                for v in values_at(root, p.split(".")):
                    if len(v.split()) > 4:
                        desc_overflow.append((label, v))
                    elif plain:
                        kw_terms.append({"@type": ["schema:DefinedTerm"], "schema:name": v})
                    else:
                        kw_terms.append({"@type": ["schema:DefinedTerm"],
                                         "schema:name": v, "schema:about": label})
            continue
        if leaf.startswith("schema:spatialCoverage"):
            sub = leaf[len("schema:spatialCoverage"):].lstrip("[*]").lstrip(".")
            for p in paths:
                for v in values_at(root, p.split(".")):
                    if not sub:
                        places.append(shape_place(v))
                    else:
                        pl = {"@type": ["schema:Place"]}
                        set_nested(pl, [k.replace("[*]", "") for k in sub.split(".")], v)
                        places.append(pl)
            continue
        if leaf == "schema:contributor":
            # <producer>/<contact> agents: structured Role/Organization/
            # ContactPoint (attributes preserved), not a flattened string.
            val = build_contributors(root, maps, paths)
            if val is not None:
                doc["schema:contributor"] = val
            continue
        contribs = gather(root, paths, maps)
        prop = leaf.split(".")[-1].replace("[*]", "")
        if prop == "schema:conditionsOfAccess":
            val = shape_conditions(contribs)
        elif leaf.endswith("[*]"):
            val = array_distinct(contribs)
        else:
            val = shape_dataset(leaf.replace("[*]", ""), oid, contribs)
        if val is not None:
            set_nested(doc, [k.replace("[*]", "") for k in leaf.split(".")], val)
    if places:
        doc["schema:spatialCoverage"] = places
    if kw_terms:
        doc["schema:keywords"] = kw_terms
    if desc_overflow:
        extra = concat(desc_overflow)
        base = doc.get("schema:description")
        doc["schema:description"] = (base + "\n" + extra) if (base and extra) else (extra or base)
    doc["schema:identifier"] = doc.get("schema:identifier", doi_url)
    # schema:url is a resolvable landing page: only set it when the @id is an
    # http(s) URL. A urn: @id (minted from IDNo) is a valid identifier but not a
    # URL, so emitting it as schema:url fails the discovery url pattern -- leave
    # schema:url absent (the distributions satisfy the url-or-distribution rule),
    # matching ddi122, which sets schema:url only from a real accsPlac/@URI.
    if doi_url.startswith(("http://", "https://")):
        doc["schema:url"] = doi_url
    # Access rights are required by the discovery profile (license OR
    # conditionsOfAccess). When the DDI states neither, emit an honest OGC nil
    # "missing" license placeholder rather than assuming a license -- matching
    # ddi122 (the shared code lists already use the same fallback).
    if not doc.get("schema:license") and not doc.get("schema:conditionsOfAccess"):
        doc["schema:license"] = [NIL_MISSING]
    # schema:dateModified is required by the discovery profile; DDI does not
    # always carry a production/version date, so fall back to the conversion
    # date (the shared code lists below inherit this value).
    doc.setdefault("schema:dateModified", datetime.date.today().isoformat())

    # variables -- data-driven flat mappings for scalar/description fields, plus
    # the structured value-domain / statistics construction delegated to ddi122.
    # <var> elements (document order) pair one-to-one with the parsed dicts;
    # dedup by ddi122's signature so a variable repeated across a study's per-file
    # <dataDscr> (e.g. DHS hhid/caseid) is one InstanceVariable, and same-name /
    # different-definition variables keep distinct #var/<name>[~N] @ids.
    parsed = _parse_vars_struct(root)
    # dedup_variables returns (unique_vars, sig->ivid); the second map is exactly
    # the signature->@id lookup the physical mapping and this loop both need.
    sig_to_ivid = _dedup_vars(parsed)[1]
    registry = CodeListRegistry(doc.get("schema:license") or [NIL_MISSING],
                                doc.get("schema:dateModified") or "1900-01-01")
    # leafs the structured builder owns -- skip them in the flat pass so it does
    # not try to set the deep value-domain/statistics paths (or mis-read sumStat).
    struct_leaf = ("cdi:takesSubstantiveValuesFrom", "cdi:takesSentinelValuesFrom",
                   "cdif:isDescribedBy_StatisticsCollection", "schema:minValue",
                   "schema:maxValue")

    vitems, seen_sig = [], set()
    for var, pv in zip(iter_local(root, "var"), parsed):
        if not pv["name"]:
            continue                       # skip unnamed <var> stubs
        sig = _var_signature(pv)
        if sig in seen_sig:
            continue                       # skip duplicate definitions
        seen_sig.add(sig)
        ivid = sig_to_ivid[sig]
        base = ivid.lstrip("#")
        item = {"@type": ["schema:PropertyValue", "cdi:InstanceVariable"],
                "@id": ivid}
        for (leaf, oid), paths in var_by_leaf.items():
            # skip leafs the structured builder owns (match the first segment,
            # stripped of any [*], so e.g. cdi:takesSentinelValuesFrom[*] is caught)
            if leaf.split(".")[0].replace("[*]", "") in struct_leaf:
                continue
            if oid == "cdi:role":
                role = {"contin": "MeasureComponent", "discrete": "AttributeComponent"}.get(var.get("intrvl", ""))
                if role:
                    item["cdi:role"] = role
                continue
            if oid == "cdi:intendedDataType":
                item["cdi:intendedDataType"] = XSD_TYPE.get(var.get("intrvl", ""), "xsd:string")
                continue
            val = shape_dataset(leaf, oid, gather(var, paths, maps, anchor="dataDscr.var"))
            if val is not None:
                set_nested(item, [k.replace("[*]", "") for k in leaf.split(".")], val)
        # variable-context array properties must be arrays even when the SSSOM
        # path did not mark them [*] (framing would otherwise wrap them).
        for arr_key in ("schema:alternateName", "schema:propertyID"):
            if arr_key in item and not isinstance(item[arr_key], list):
                item[arr_key] = [item[arr_key]]
        # structured min/max + enumerated value domains + statistics (from ddi122)
        for sk, jk in (("min", "schema:minValue"), ("max", "schema:maxValue")):
            if sk in pv["stats"]:
                try:
                    item[jk] = float(pv["stats"][sk])
                except ValueError:
                    pass
        vdoms, idmap = _value_domains(base, pv["cats"], registry)
        item.update(vdoms)
        coll = _statistics_collection(base, item["@id"], pv["stats"], pv["cats"], idmap)
        if coll is not None:
            item["cdif:isDescribedBy_StatisticsCollection"] = coll
        vitems.append(item)
    if vitems:
        doc["schema:variableMeasured"] = vitems

    # distributions. DDI never declares the files as tabular text, but the
    # <var files="..."> -> <fileDscr ID> linkage lets us build the physical
    # column-to-variable mapping, which is what justifies the cdi:TabularTextDataSet
    # typing. ddi122.build_distributions constructs that mapping (cdi:isDelimited +
    # cdif:hasPhysicalMapping, each column's cdif:formats_InstanceVariable pointing
    # at the shared InstanceVariable); it runs over the fileDscr elements in
    # document order, so it aligns one-to-one with the loop below. The SSSOM
    # mappings supply the file-level fields (name, descriptive title, counts).
    struct_dists = _build_dists(_parse_files(root), parsed, sig_to_ivid)
    ditems = []
    for i, fd in enumerate(iter_local(root, "fileDscr")):
        # schema:contentUrl: prefer a resolvable per-file download URL when the
        # producer supplies one on <fileDscr URI="..."> (e.g. Dataverse). Only an
        # http(s) URL counts -- NADA omits it and Nesstar puts a non-resolvable
        # internal reference there -- so otherwise fall back to the OGC nil
        # "missing" value (required by the dataDownload building block).
        _furi = (fd.get("URI") or "").strip()
        item = {"@type": ["schema:DataDownload", "cdi:TabularTextDataSet"],
                "schema:contentUrl": _furi if _furi.startswith(("http://", "https://"))
                else NIL_MISSING}
        for (leaf, oid), paths in dist_by_leaf.items():
            val = shape_dataset(leaf, oid, gather(fd, paths, maps, anchor="fileDscr"))
            if val is not None:
                set_nested(item, leaf.split("."), val)
        # merge in the structured column mapping for this file (delimited layout +
        # per-column links); files with no columns get neither, as they should.
        if i < len(struct_dists):
            for k in ("cdi:isDelimited", "cdif:hasPhysicalMapping"):
                if k in struct_dists[i]:
                    item[k] = struct_dists[i][k]
        ditems.append(item)
    if ditems:
        doc["schema:distribution"] = ditems

    # provenance + related links
    skipped = []
    if prov["activity"]:
        act = build_activity(root, prov["activity"], maps, skipped)
        if len(act) > 1:
            doc["prov:wasGeneratedBy"] = [act]
    if prov["derived"]:
        der = build_derived(root, prov["derived"], maps, skipped)
        if der:
            doc["prov:wasDerivedFrom"] = [der]
    if prov["related"]:
        links = build_related(root, prov["related"], maps, skipped)
        if links:
            doc["schema:relatedLink"] = links

    if verbose and skipped:
        print(f"  [skipped] {len(skipped)} mapping(s) with a malformed object_json_path "
              f"(fix in the worksheet): {sorted(skipped)[:3]}...", file=sys.stderr)

    if detect:
        try:
            sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..")))
            from detect_conformance import detect_conformance, apply_conformance
            apply_conformance(doc, detect_conformance(doc))
        except Exception as e:
            if verbose:
                print(f"  (conformance detection skipped: {e})", file=sys.stderr)

    # Type the metadata catalog record like ddi122_to_cdif.py's build_catalog_record:
    # a schema:Dataset bearing schema:additionalType {@id: dcat:CatalogRecord} and
    # schema:about the described dataset. The docDscr.* SSSOM rows fill its content
    # (identifier/maintainer/conformsTo/...) but cannot express this node typing, so
    # add it here -- after conformance detection, which keys off the main dataset.
    # The IRI form (not the bare string) plus schema:about is what the discovery
    # mandatory SHACL shape's MINUS excludes, so the record is not held to the
    # dataset-mandatory requirements.
    rec = doc.get("schema:subjectOf")
    if isinstance(rec, dict) and "@type" not in rec:
        typed = {"@type": ["schema:Dataset"],
                 "schema:additionalType": [{"@id": "dcat:CatalogRecord"}],
                 "@id": doc["@id"] + "#cdif-catalog-record",
                 "schema:about": {"@id": doc["@id"]}}
        typed.update(rec)
        doc["schema:subjectOf"] = typed

    # When coded variables produced shared code lists, emit a flattened @graph
    # with the dataset first and each distinct code list as a sibling node
    # (preserved from ddi122).
    if registry.nodes:
        ctx = doc.pop("@context")
        doc = {"@context": ctx, "@graph": [doc] + registry.nodes}
    return doc


def main():
    ap = argparse.ArgumentParser(description="Data-driven DDI Codebook -> CDIF converter")
    ap.add_argument("xml")
    ap.add_argument("--doi", help="dataset DOI/landing-page URL (@id); when "
                    "omitted it is derived from accsPlac/@URI or the study IDNo")
    ap.add_argument("--version", choices=["25", "122"], default="25")
    ap.add_argument("--base-uri", default="urn:ddi",
                    help="base for minting @id from IDNo when no --doi/access URL "
                         "is present (default: urn:ddi)")
    ap.add_argument("-o", "--output")
    ap.add_argument("--no-detect", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    doc = convert(a.xml, a.doi, a.version, detect=not a.no_detect,
                  verbose=a.verbose, base_uri=a.base_uri)
    out = a.output or (os.path.splitext(a.xml)[0] + "-cdif.json")
    json.dump(doc, open(out, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
