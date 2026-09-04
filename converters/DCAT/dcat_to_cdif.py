#!/usr/bin/env python3
"""
dcat_to_cdif.py - Convert DCAT JSON-LD metadata to CDIF schema.org format.

Reads a DCAT catalog or individual dataset records in JSON-LD and converts
them to CDIF-conformant schema.org JSON-LD, following the property mapping
defined in the CDIF DCAT implementation guide:
https://cross-domain-interoperability-framework.github.io/cdifbook/metadata/dcat.html

Supports:
- DCAT catalogs with nested dcat:Dataset entries (extracts and converts each)
- Individual dcat:Dataset or dcat:Distribution records
- FOAF agents (Person, Organization) to schema:Person/Organization
- prov:qualifiedAttribution to schema:contributor with roles
- Spatial/temporal coverage (dcterms:spatial/temporal)
- Distribution mapping (dcat:Distribution to schema:DataDownload)

Unmapped DCAT properties are preserved in the output (open-world assumption).

Usage:
    # Convert all datasets from a DCAT catalog
    python DCAT/dcat_to_cdif.py catalog.jsonld --output ./examples

    # Convert and validate against cdifCore
    python DCAT/dcat_to_cdif.py catalog.jsonld --output ./examples --validate

    # Convert a single dataset record
    python DCAT/dcat_to_cdif.py dataset.jsonld --output ./examples

    # List datasets in a catalog without converting
    python DCAT/dcat_to_cdif.py catalog.jsonld --list

    # Select specific datasets by index
    python DCAT/dcat_to_cdif.py catalog.jsonld --output ./examples --select 0,3,5
"""

import datetime as _dt
import json
import sys
import os
import re
import argparse
from pathlib import Path

# detect_conformance (validation/ root) derives dcterms:conformsTo from the
# record's actual content. Best-effort: falls back to the built-in conformsTo
# when it (or its rdflib/pyshacl deps) is unavailable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
try:
    from detect_conformance import detect_conformance, apply_conformance
    _HAVE_DETECT = True
except Exception:
    _HAVE_DETECT = False


# ---------------------------------------------------------------------------
# DCAT → schema.org property mapping
# ---------------------------------------------------------------------------

CDIF_CONTEXT = {
    "schema": "http://schema.org/",
    "dcterms": "http://purl.org/dc/terms/",
    "dcat": "http://www.w3.org/ns/dcat#",
    "prov": "http://www.w3.org/ns/prov#",
}


def _split_iri(iri):
    """(namespace, local name) for an absolute IRI, or (iri, "") if indivisible."""
    for sep in ("#", "/"):
        idx = iri.rfind(sep)
        if idx > 0 and idx < len(iri) - 1:
            local = iri[idx + 1:]
            if local and not local[0].isdigit() and ":" not in local:
                return iri[:idx + 1], local
    return iri, ""


# Conventional prefixes, so a minted one does not end up as "rdfschema" for a
# namespace the world already calls "rdfs".
_WELL_KNOWN_PREFIXES = {
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#": "rdf",
    "http://www.w3.org/2000/01/rdf-schema#": "rdfs",
    "http://www.w3.org/2002/07/owl#": "owl",
    "http://www.w3.org/2004/02/skos/core#": "skos",
    "http://www.w3.org/2001/XMLSchema#": "xsd",
    "http://xmlns.com/foaf/0.1/": "foaf",
    "http://www.w3.org/2006/vcard/ns#": "vcard",
    "http://www.w3.org/ns/adms#": "adms",
    "http://www.w3.org/ns/locn#": "locn",
    "http://www.w3.org/ns/dqv#": "dqv",
    "http://www.w3.org/2006/time#": "time",
    "http://spdx.org/rdf/terms#": "spdx",
    "http://www.opengis.net/ont/geosparql#": "geosparql",
}


# The reverse lookup, for CURIEs the source used but did not declare.
_NAMESPACE_FOR_PREFIX = {p: ns for ns, p in _WELL_KNOWN_PREFIXES.items()}
_NAMESPACE_FOR_PREFIX.update({
    "dct": "http://purl.org/dc/terms/",
    "dcterms": "http://purl.org/dc/terms/",
    "dcat": "http://www.w3.org/ns/dcat#",
    "schema": "http://schema.org/",
    "prov": "http://www.w3.org/ns/prov#",
    "dqv": "http://www.w3.org/ns/dqv#",
    "spdx": "http://spdx.org/rdf/terms#",
})


def _prefix_for(context, namespace):
    """A prefix bound to `namespace` in `context`, reusing or minting one."""
    for prefix, value in context.items():
        if value == namespace:
            return prefix
    known = _WELL_KNOWN_PREFIXES.get(namespace)
    if known and known not in context:
        context[known] = namespace
        return known
    # Derive something readable from the last meaningful path segment.
    stem = namespace.rstrip("#/").rsplit("/", 1)[-1]
    base = "".join(ch for ch in stem if ch.isalnum()).lower() or "ext"
    if base[0].isdigit():
        base = "x" + base
    prefix, n = base, 1
    while prefix in context:
        n += 1
        prefix = "%s%d" % (base, n)
    context[prefix] = namespace
    return prefix


# The CDIF shapes accept YYYY-MM through YYYY-MM-DDThh:mm:ss with an optional
# Z/offset -- and no fractional seconds, which sources routinely carry.
_CDIF_DATE_RE = re.compile(
    r"^[1-2][0-9]{3}-([0][1-9]|[1][0-2])"
    r"(-([0-2][0-9]|[3][0-1])"
    r"(T([0-1][0-9]|[2][0-3])(:[0-5][0-9])?"
    r"(:[0-5][0-9](Z|[+-][0-2][0-9]:[0-5][0-9])?)?)?)?$")


def _normalize_date(value):
    """Coerce a date string into the form the CDIF shapes accept, or None."""
    if not isinstance(value, str):
        return None
    v = value.strip()
    if _CDIF_DATE_RE.match(v):
        return v
    trimmed = re.sub(r"\.\d+", "", v)          # "...:24.309486" -> "...:24"
    if _CDIF_DATE_RE.match(trimmed):
        return trimmed
    for length in (10, 7):                     # fall back to date, then month
        if _CDIF_DATE_RE.match(v[:length]):
            return v[:length]
    return None


def _as_list(value):
    """value as a list: None -> [], a scalar -> [scalar], a list unchanged."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _declare_prefix_of(curie, context):
    """Declare the namespace for `curie`'s prefix, when we know it."""
    if not isinstance(curie, str) or ":" not in curie:
        return
    if curie.startswith(("http://", "https://", "urn:", "_:", "@")):
        return
    prefix = curie.split(":", 1)[0]
    if prefix and prefix not in context:
        ns = _NAMESPACE_FOR_PREFIX.get(prefix)
        if ns:
            context[prefix] = ns


def _prefix_keys(key, value, context, depth=0):
    """(key, value) with every absolute-IRI property key turned into a CURIE.

    An absolute IRI as a JSON-LD property key breaks framing: the part before
    the first colon is read as a prefix. Minting a prefix keeps the term -- these
    are real vocabulary properties from DCAT-AP extensions -- rather than
    dropping content to make the record parse.
    """
    if key.startswith(("http://", "https://")):
        ns, local = _split_iri(key)
        if local:
            key = "%s:%s" % (_prefix_for(context, ns), local)
    elif ":" in key and not key.startswith("@"):
        # A CURIE whose prefix the record does not declare is worse than an
        # absolute IRI: jsonld cannot resolve "skos" and raises "Absolute IRI
        # confused with prefix", so the record does not frame and never reaches
        # validation. Declare the namespace when we know it.
        prefix = key.split(":", 1)[0]
        if prefix and prefix not in context:
            ns = _NAMESPACE_FOR_PREFIX.get(prefix)
            if ns:
                context[prefix] = ns
    if depth < 12:
        if isinstance(value, dict):
            # @type and @id are IRI positions: a CURIE there with an undeclared
            # prefix parses as an absolute IRI whose SCHEME is the prefix, which
            # then collides with the frame's own prefix during compaction.
            for iri_key in ("@type", "@id"):
                for candidate in _as_list(value.get(iri_key)):
                    if isinstance(candidate, str):
                        _declare_prefix_of(candidate, context)
            out = {}
            for k2, v2 in value.items():
                nk, nv = _prefix_keys(k2, v2, context, depth + 1)
                out[nk] = nv
            value = out
        elif isinstance(value, list):
            value = [_prefix_keys("x", item, context, depth + 1)[1]
                     for item in value]
    return key, value


def _get_str(val):
    """Extract a string value from a JSON-LD value (plain, @value, or @id).

    Returns None for a dict carrying neither, rather than str(val). The old
    fallback turned the `{}` defaults that callers pass in -- dist.get(k, {}) --
    into the literal string "{}", which is truthy, so it sailed through the
    `if url:` guards and was written out as a value. 163 distributions across
    108 records ended up with "schema:contentUrl": "{}".
    """
    if val is None:
        return None
    if isinstance(val, dict):
        for key in ("@value", "@id"):
            if key in val:
                return str(val[key])
        return None
    if isinstance(val, (list, tuple)):
        for item in val:
            got = _get_str(item)
            if got:
                return got
        return None
    return str(val)


# ---------------------------------------------------------------------------
# SSSOM mapping tables
# ---------------------------------------------------------------------------
#
# converters/mappings/dcat-to-cdif.sssom.tsv is the authority for which DCAT
# property becomes which CDIF property. This module reads it rather than
# restating it, so the table and the behaviour cannot drift apart -- the same
# arrangement ddi_sssom_to_cdif.py uses.
#
# Two columns beyond stock SSSOM, declared as extension slots in the .yml:
#   subject_class  DCAT is a graph, so a property's meaning depends on the
#                  class it sits on: dcterms:title is schema:name on a Dataset
#                  and the distribution's name on a Distribution.
#   transform      names the shaper below. Empty means a plain copy.

_MAPPINGS_DIR = Path(__file__).resolve().parent.parent / "mappings"

# Classes a property sits on when it is a property of the dataset itself.
_ROOT_CLASSES = ("dcat:Dataset", "dcat:Resource")


def _read_sssom(name):
    """Rows of an SSSOM TSV as dicts. Raises if the table is missing.

    Deliberately fatal: a converter that silently produced empty records
    because its mapping table was absent would look like a converter that
    found nothing to map.
    """
    path = _MAPPINGS_DIR / name
    with path.open(encoding="utf-8") as fh:
        header = fh.readline().rstrip("\n").split("\t")
        rows = []
        for line in fh:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            cells = line.split("\t")
            cells += [""] * (len(header) - len(cells))
            rows.append(dict(zip(header, cells)))
    return rows


def _load_tables():
    aliases = {}
    for row in _read_sssom("dcat-aliases.sssom.tsv"):
        if row["subject_id"] and row["object_id"]:
            aliases[row["subject_id"]] = row["object_id"]
    rules = {}
    for order, row in enumerate(_read_sssom("dcat-to-cdif.sssom.tsv")):
        row["_order"] = order
        rules.setdefault(row["subject_id"], []).append(row)
    return aliases, rules


ALIASES, RULES = _load_tables()


def build_node_index(doc):
    """{@id: node} for every node in `doc` that says more than its own @id.

    A node carrying only @id is a reference, not a description, so it never
    shadows the real node -- otherwise a document that mentions a distribution
    before defining it would index the mention.
    """
    index = {}

    def walk(node, depth=0):
        if depth > 20:
            return
        if isinstance(node, list):
            for item in node:
                walk(item, depth + 1)
            return
        if not isinstance(node, dict):
            return
        nid = node.get("@id")
        if isinstance(nid, str) and len(node) > 1 and nid not in index:
            index[nid] = node
        for value in node.values():
            walk(value, depth + 1)

    walk(doc)
    return index


def _resolve(value, graph, seen=None, depth=0):
    """`value` with @id references replaced by the nodes they name."""
    if not graph or depth > 8:
        return value
    if seen is None:
        seen = set()
    if isinstance(value, list):
        return [_resolve(v, graph, seen, depth + 1) for v in value]
    if not isinstance(value, dict):
        return value
    nid = value.get("@id")
    if isinstance(nid, str) and len(value) == 1 and nid in graph and nid not in seen:
        seen = seen | {nid}
        return _resolve(graph[nid], graph, seen, depth + 1)
    return {k: (v if k.startswith("@") else _resolve(v, graph, seen, depth + 1))
            for k, v in value.items()}


def _rule_for(key, classes):
    """The row governing `key` on any of `classes`, or None."""
    for row in RULES.get(key, ()):
        if row["subject_class"] in classes:
            return row
    return None


def _apply_aliases(ds, changes):
    """`ds` with source IRIs rewritten to the IRI the publisher meant.

    Most of these come from official context documents rather than from
    careless records -- see dcat-aliases.sssom.yml -- so the rewrite is
    routine, but it is recorded: a silent correction is indistinguishable
    from the source having been right all along.
    """
    if not any(k in ALIASES for k in ds):
        return ds
    out = {}
    for key, value in ds.items():
        target = ALIASES.get(key)
        if target and target not in ds:      # never clobber a real value
            out[target] = value
            changes.append("%s read as %s" % (key, target))
        elif target:
            changes.append("%s dropped (%s also present)" % (key, target))
        else:
            out[key] = value
    return out


# A node this pass creates still has to say what it is.
_NODE_TYPES = {"prov:wasGeneratedBy": ["prov:Activity"]}


# --- transforms ------------------------------------------------------------
#
# (value, ds, rule, doc) -> the CDIF value, or None to emit nothing.
# `rule` is the table row, so a shaper can use the source property and the
# curated object_label; `doc` is the record so far, for the shapers that
# accumulate.

NIL = "http://www.opengis.net/def/nil/OGC/0/missing"


def _local(curie):
    return curie.rsplit(":", 1)[-1] if curie else curie


def _is_iri(text):
    return isinstance(text, str) and text.startswith(("http://", "https://", "urn:"))


def _tf_text(value, ds, rule, doc):
    return _get_str(value)


def _tf_iri(value, ds, rule, doc):
    if isinstance(value, list):
        got = [_tf_iri(v, ds, rule, doc) for v in value]
        got = [g for g in got if g]
        return got or None
    if isinstance(value, dict):
        return value.get("@id") or _get_str(value)
    return _get_str(value)


def _tf_idref(value, ds, rule, doc):
    """An IRI -> {"@id": ...}, the reference form CDIF declares.

    A distribution's dcterms:conformsTo is an array of objects, not of
    strings: it names standards, and a name that cannot be dereferenced is
    not much use.
    """
    got = _tf_iri(value, ds, rule, doc)
    items = got if isinstance(got, list) else ([got] if got else [])
    # CDIF requires @type on the nodes it declares, so a reference to one has
    # to say what it refers to -- an untyped {"@id": ...} does not validate.
    types = _NODE_TYPES.get(rule.get("object_id"))
    if types:
        return [{"@id": i, "@type": list(types)} for i in items] or None
    return [{"@id": i} for i in items] or None


def _tf_date(value, ds, rule, doc):
    return _get_str(value)


def _tf_langcode(value, ds, rule, doc):
    text = _tf_iri(value, ds, rule, doc)
    if isinstance(text, list):
        text = text[0] if text else None
    if not text:
        return None
    tail = text.rstrip("/").rsplit("/", 1)[-1].rsplit("#", 1)[-1]
    return tail or text


def _tf_list(value, ds, rule, doc):
    return [v for v in (_get_str(item) for item in _as_list(value)) if v]


def _tf_describe(value, ds, rule, doc):
    """Fold an extension property's prose into schema:description.

    Seventeen extension properties (it6:*, dcatde:*, adms:versionNotes) carry
    text a reader wants, and CDIF has one description. Each is appended as its
    own labelled line rather than competing for the slot, so nothing is lost
    and the source of each sentence stays visible.
    """
    text = " ".join(v for v in (_get_str(i) for i in _as_list(value)) if v).strip()
    if not text:
        return None
    return "%s: %s" % (rule.get("object_label") or _local(rule["subject_id"]), text)


def _tf_prefixedtext(value, ds, rule, doc):
    """Label a conditionsOfAccess entry with the property it came from.

    Seven properties feed conditionsOfAccess -- dcterms:accessRights and
    dcterms:rights are different things, and POD and DCAT-US each add their own
    vocabulary. Prefixing keeps them distinguishable in one list.
    """
    out = []
    for item in _as_list(value):
        text = _tf_iri(item, ds, rule, doc) if isinstance(item, dict) else _get_str(item)
        if isinstance(text, list):
            text = text[0] if text else None
        if text:
            out.append("%s: %s" % (rule["subject_id"], text))
    return out or None


def _name_from_iri(iri, taken):
    """A readable name for a theme that came as a bare IRI.

    The last two path segments carry the meaning in every theme vocabulary in
    the corpus (".../sector-publico/sector/medio-ambiente"), and a bare IRI is
    useless as a keyword. Numbered when two IRIs reduce to the same name.
    """
    parts = [p for p in iri.rstrip("/").replace("#", "/").split("/") if p]
    name = "/".join(parts[-2:]) if len(parts) >= 2 else (parts[-1] if parts else iri)
    if name not in taken:
        return name
    n = 2
    while "%s (%d)" % (name, n) in taken:
        n += 1
    return "%s (%d)" % (name, n)


def _tf_theme(value, ds, rule, doc):
    """dcat:theme -> a schema:DefinedTerm marked as a DCAT theme.

    A theme is a subject category, not a free-text keyword, so it keeps its
    IRI in schema:identifier and is tagged schema:about = 'DCATtheme' to stay
    distinguishable from dcat:keyword once both are in schema:keywords.
    """
    taken = set()
    for existing in _as_list(doc.get("schema:keywords")):
        if isinstance(existing, dict) and existing.get("schema:name"):
            taken.add(existing["schema:name"])
    out = []
    for item in _as_list(value):
        name = iri = None
        if isinstance(item, dict):
            name = _get_str(item.get("skos:prefLabel") or item.get("rdfs:label")
                            or item.get("schema:name"))
            iri = item.get("@id")
        else:
            text = _get_str(item)
            if _is_iri(text):
                iri = text
            else:
                name = text
        term = {"@type": ["schema:DefinedTerm"], "schema:about": "DCATtheme"}
        if iri:
            term["schema:identifier"] = iri
        if not name and iri:
            name = _name_from_iri(iri, taken)
        if not name:
            continue
        taken.add(name)
        term["schema:name"] = name
        out.append(term)
    return out or None


def _tf_concept(value, ds, rule, doc):
    out = []
    for item in _as_list(value):
        if isinstance(item, dict):
            name = _get_str(item.get("skos:prefLabel") or item.get("rdfs:label")
                            or item.get("schema:name"))
            if name:
                term = {"@type": ["schema:DefinedTerm"], "schema:name": name}
                if item.get("@id"):
                    term["schema:identifier"] = item["@id"]
                out.append(term)
                continue
            if item.get("@id"):
                out.append({"@type": ["schema:DefinedTerm"],
                            "schema:identifier": item["@id"]})
                continue
        text = _get_str(item)
        if text:
            # A term of its own, not a bare keyword: this came from a
            # classification property, and the DefinedTerm is what says so.
            out.append({"@type": ["schema:DefinedTerm"], "schema:name": text})
    return out or None


def _tf_agent(value, ds, rule, doc):
    got = [convert_agent(a) for a in _as_list(value)]
    return [a for a in got if a] or None


def _tf_vcard(value, ds, rule, doc):
    """A vCard contact -> a schema:Person (or Organization) with a ContactPoint.

    Default to Person: a contact point names a human unless the source says
    otherwise, and guessing Organization made every named individual an
    institution. A contact with no name still carries its address, so the name
    becomes the nil URI rather than the node being dropped.
    """
    out = []
    for contact in _as_list(value):
        if not isinstance(contact, dict):
            text = _get_str(contact)
            if text:
                out.append({"@type": ["schema:Person"], "schema:name": text})
            continue
        types = " ".join(_as_list(contact.get("@type")))
        kind = "schema:Organization" if ("Organization" in types or "Org" in types) \
            else "schema:Person"
        name = _get_str(contact.get("vcard:fn") or contact.get("schema:name"))
        email = contact.get("vcard:hasEmail") or contact.get("vcard:email")
        url = contact.get("vcard:hasURL") or contact.get("vcard:url")
        phone = contact.get("vcard:hasTelephone")
        agent = {"@type": [kind], "schema:name": name or NIL}
        if contact.get("@id") and _is_iri(contact["@id"]):
            agent["@id"] = contact["@id"]
        point = {"@type": ["schema:ContactPoint"]}
        if email:
            addr = _tf_iri(email, ds, rule, doc)
            if isinstance(addr, list):
                addr = addr[0] if addr else None
            if addr:
                point["schema:email"] = addr.replace("mailto:", "")
        if url:
            link = _tf_iri(url, ds, rule, doc)
            if isinstance(link, list):
                link = link[0] if link else None
            if link:
                point["schema:url"] = link
        if phone:
            tel = _tf_iri(phone, ds, rule, doc)
            if isinstance(tel, list):
                tel = tel[0] if tel else None
            if tel:
                point["schema:telephone"] = tel.replace("tel:", "")
        if len(point) > 1:
            agent["schema:contactPoint"] = point
        out.append(agent)
    return out or None


def _tf_contributorid(value, ds, rule, doc):
    """A bare contributor identifier -> a contributor that has only that.

    DCAT-AP.de puts the ID at dataset level with no link to any particular
    contributor, so attaching it to one already in the record would pick a
    contributor at random. This says exactly what the source says: something
    contributed, here is its identifier, its name is knowably absent.
    """
    idents = []
    for item in _as_list(value):
        ident = _tf_iri(item, ds, rule, doc)
        if isinstance(ident, list):
            ident = ident[0] if ident else None
        if ident and ident not in idents:
            idents.append(ident)
    if not idents:
        return None

    existing = doc.get("schema:contributor") or []
    if len(idents) == 1 and len(existing) == 1:
        # One ID and one contributor: they are each other's, and saying so
        # keeps the identifier attached to the agent it identifies.
        node = existing[0]
        agent = node.get("schema:contributor")             if "schema:Role" in _as_list(node.get("@type")) else node
        if isinstance(agent, dict):
            agent.setdefault("schema:identifier", idents[0])
            return existing        # already in place; marks the row as applied

    # Nothing to attach it to, or too many candidates to choose between. The
    # ID becomes a contributor of its own, saying exactly what the source
    # says: something contributed, here is its identifier, no name given.
    return [{
        "@type": ["schema:Role"],
        "schema:roleName": "contributor",
        "schema:contributor": {
            "@type": ["schema:Organization"],
            "schema:name": NIL,
            "schema:identifier": ident,
        },
    } for ident in idents]


def _tf_identifier(value, ds, rule, doc):
    """adms:Identifier -> a string, preferring a DOI when there are several.

    A record may carry many identifiers and CDIF names one. Picking a DOI
    first means the chosen one is the citable, resolvable identifier rather
    than whichever the serializer happened to put first; the rest are kept on
    schema:sameAs so nothing is lost.
    """
    found = []
    for item in _as_list(value):
        if isinstance(item, dict):
            got = (item.get("skos:notation") or item.get("dcterms:identifier")
                   or item.get("@id"))
        else:
            got = item
        text = _get_str(got)
        if text and text not in found:
            found.append(text)
    if not found:
        return None
    doi = next((f for f in found if "doi.org" in f.lower()
                or f.lower().startswith("doi:") or "10." in f[:4]), None)
    chosen = doi or found[0]
    rest = [f for f in found if f != chosen and _is_iri(f)]
    if rest:
        same = doc.get("schema:sameAs") or []
        for r in rest:
            if r not in same:
                same.append(r)
        doc["schema:sameAs"] = same
    return chosen


def _tf_place(value, ds, rule, doc):
    got = [convert_spatial(p) for p in _as_list(value)]
    return [p for p in got if p] or None


def _tf_bbox(value, ds, rule, doc):
    """DCAT-US bounding coordinates -> a schema:GeoShape box.

    schema:box is "lower corner, then upper corner": south west north east.
    The values are checked before use -- a box whose north is below its south,
    or whose numbers are outside the coordinate range, is a transcription
    error, and emitting it would put a wrong footprint in a discovery index.
    """
    for node in _as_list(value):
        if not isinstance(node, dict):
            continue

        def coord(local):
            for key, val in node.items():
                if key.rsplit(":", 1)[-1] == local:
                    text = _get_str(val)
                    try:
                        return float(text)
                    except (TypeError, ValueError):
                        return None
            return None

        west, east = coord("westBoundingLongitude"), coord("eastBoundingLongitude")
        south, north = coord("southBoundingLatitude"), coord("northBoundingLatitude")
        if None in (west, east, south, north):
            continue
        if not (-90 <= south <= 90 and -90 <= north <= 90):
            continue
        if not (-180 <= west <= 180 and -180 <= east <= 180):
            continue
        if north < south:
            continue                      # transposed corners, not a real box
        # west > east is legitimate: a box crossing the antimeridian.
        return [{"@type": ["schema:Place"],
                 "schema:geo": {"@type": ["schema:GeoShape"],
                                "schema:box": "%g %g %g %g"
                                              % (south, west, north, east)}}]
    return None


def _tf_period(value, ds, rule, doc):
    got = [convert_temporal(t) for t in _as_list(value)]
    return [t for t in got if t] or None


def _tf_distribution(value, ds, rule, doc):
    got = [convert_distribution(d) for d in _as_list(value) if isinstance(d, dict)]
    return [d for d in got if d] or None


def _tf_service(value, ds, rule, doc):
    """dcat:accessService -> the action that reaches this distribution.

    CDIF does not describe services as resources in their own right, so a
    service a distribution is obtained through is recorded as a
    schema:potentialAction on it -- which is what that property means, and
    what its shape requires: an Action whose EntryPoint carries a urlTemplate.
    Emitting a nested schema:WebAPI there instead said "this action is a web
    API" and then failed the WebAPI shape for having no terms of service and
    no action of its own.

    A processing service -- one that takes an arbitrary input and returns a
    result -- is out of scope and skipped: it does not distribute this data.
    """
    out = []
    for node in _as_list(value):
        if isinstance(node, dict):
            types = " ".join(_as_list(node.get("@type")))
            if "Process" in types:
                continue
            url = _tf_iri(node.get("dcat:endpointURL") or node, ds, rule, doc)
        else:
            url = _tf_iri(node, ds, rule, doc)
        if isinstance(url, list):
            url = url[0] if url else None
        if not url:
            continue
        action = {"@type": ["schema:SearchAction"],
                  "schema:target": {"@type": ["schema:EntryPoint"],
                                    "schema:urlTemplate": url}}
        if isinstance(node, dict):
            desc = node.get("dcat:endpointDescription")
            if desc:
                link = _tf_iri(desc, ds, rule, doc)
                if isinstance(link, list):
                    link = link[0] if link else None
                if link:
                    action["schema:target"]["schema:contentType"] = None
                    del action["schema:target"]["schema:contentType"]
        out.append(action)
    return out or None


def _tf_attribution(value, ds, rule, doc):
    got = [convert_qualified_attribution(a) for a in _as_list(value)]
    return [a for a in got if a] or None


def _tf_relatedlink(value, ds, rule, doc):
    """An IRI -> a CDIF relatedLink that remembers which relation it was.

    isReferencedBy, references, replaces, isReplacedBy, foaf:page,
    wdrs:describedby and the dataset-series pointers all land here. Writing the
    source property into linkRelationship is what keeps them distinguishable
    afterwards -- the alternative loses the difference between "this replaces
    that" and "that documents this".
    """
    out = []
    for item in _as_list(value):
        target = _tf_iri(item, ds, rule, doc)
        if isinstance(target, list):
            target = target[0] if target else None
        if not target:
            continue
        out.append({"schema:linkRelationship": rule["subject_id"],
                    "schema:target": {"@type": ["schema:EntryPoint"],
                                      "schema:url": target}})
    return out or None


def _tf_bytes(value, ds, rule, doc):
    return _get_str(value)


def _tf_mediatype(value, ds, rule, doc):
    got = [_get_str(v) if not isinstance(v, dict) else _tf_iri(v, ds, rule, doc)
           for v in _as_list(value)]
    got = [g for g in got if g]
    return got or None


def _tf_measurement(value, ds, rule, doc):
    """A bare quality value -> a dqv:QualityMeasurement.

    POD's dataQuality is a boolean, and CDIF wants a measurement object that
    names what was measured. Wrapping keeps the assertion and says which
    property it came from, instead of dropping a lone `true` into a slot
    declared as an object.
    """
    out = []
    for item in _as_list(value):
        if isinstance(item, dict) and len(item) > 1:
            out.append(item)
            continue
        # CDIF declares the measured value as a string or number, so a
        # boolean flag is written the way JSON-LD would spell it.
        val = "true" if item is True else ("false" if item is False else _get_str(item))
        if val is None or val == "":
            continue
        out.append({"@type": ["dqv:QualityMeasurement"],
                    "dqv:isMeasurementOf": rule["subject_id"],
                    "dqv:value": val})
    return out or None


def _tf_checksum(value, ds, rule, doc):
    """spdx:Checksum -> the single object CDIF declares (not an array)."""
    out = []
    for node in _as_list(value):
        if not isinstance(node, dict):
            continue
        algo = _tf_iri(node.get("spdx:algorithm"), ds, rule, doc)
        val = _get_str(node.get("spdx:checksumValue"))
        if not val:
            continue
        item = {"@type": ["spdx:Checksum"], "spdx:checksumValue": val}
        if algo:
            item["spdx:algorithm"] = algo[0] if isinstance(algo, list) else algo
        out.append(item)
    return out[0] if out else None


_TRANSFORMS = {
    "": _tf_text,
    "text": _tf_text,
    "iri": _tf_iri,
    "idref": _tf_idref,
    "date": _tf_date,
    "langcode": _tf_langcode,
    "list": _tf_list,
    "describe": _tf_describe,
    "prefixedtext": _tf_prefixedtext,
    "theme": _tf_theme,
    "bytes": _tf_bytes,
    "mediatype": _tf_mediatype,
    "concept": _tf_concept,
    "agent": _tf_agent,
    "vcard": _tf_vcard,
    "identifier": _tf_identifier,
    "contributorid": _tf_contributorid,
    "place": _tf_place,
    "bbox": _tf_bbox,
    "period": _tf_period,
    "distribution": _tf_distribution,
    "service": _tf_service,
    "checksum": _tf_checksum,
    "measurement": _tf_measurement,
    "attribution": _tf_attribution,
    "relatedlink": _tf_relatedlink,
}

# Shapers that add to what is already there instead of filling an empty slot.
_ACCUMULATING = {"describe", "prefixedtext"}

# How CDIF wants each target shaped. This is CDIF-side knowledge -- what the
# profile schema declares -- not part of the DCAT correspondence, so it lives
# here rather than in the table. Anything unlisted is a single value.
_TARGET_ARITY = {
    "schema:license": "array",
    "schema:conditionsOfAccess": "array",
    "schema:keywords": "array",
    "schema:contributor": "array",
    "schema:provider": "array",
    "schema:distribution": "array",
    "schema:spatialCoverage": "array",
    "schema:temporalCoverage": "array",
    "schema:relatedLink": "array",
    "schema:additionalType": "array",
    "schema:hasPart": "array",
    "schema:isPartOf": "array",
    "schema:sameAs": "array",
    "schema:inDefinedTermSet": "array",
    "prov:wasGeneratedBy": "array",
    "dqv:hasQualityMeasurement": "array",
    "prov:used": "array",
    "schema:creator": "ordered",       # {"@list": [...]}, order is meaningful
    # reached inside a distribution
    "schema:encodingFormat": "array",
    "dcterms:conformsTo": "array",
    "schema:potentialAction": "array",
}


def _place(doc, target, value, transform=""):
    """Put `value` at `target`, shaped the way the CDIF profile declares it.

    Three arities, because CDIF's own schema has three:
      accumulating -- `describe` and `prefixedtext` add to a slot another row
        already filled. schema:description is a single string, so an appended
        line is joined onto it; conditionsOfAccess is a list, so it gains an
        entry.
      array -- six properties map onto schema:relatedLink and three onto
        schema:keywords; letting the first win would drop the rest on the
        floor, consumed by the table and so not passed through either.
      scalar -- keeps the first value, which is how the table's row order
        expresses "dcterms:identifier, else adms:identifier".
    """
    if value is None or value == [] or value == "":
        return False
    arity = _TARGET_ARITY.get(target)
    if transform in _ACCUMULATING:
        items = value if isinstance(value, list) else [value]
        if arity == "array":
            existing = doc.get(target) or []
            for item in items:
                if item not in existing:
                    existing.append(item)
            doc[target] = existing
        else:
            joined = "\n\n".join(str(i) for i in items)
            doc[target] = (doc[target] + "\n\n" + joined) if doc.get(target) else joined
        return True
    if arity == "ordered":
        doc[target] = {"@list": value if isinstance(value, list) else [value]}
    elif arity == "array":
        items = value if isinstance(value, list) else [value]
        existing = doc.get(target) or []
        for item in items:
            if item not in existing:
                existing.append(item)
        doc[target] = existing
    else:
        if target in doc:
            return False
        doc[target] = value[0] if isinstance(value, list) else value
    return True


# Root-level rows with a CDIF target, in table order. Order is precedence: for
# a scalar target the first row to fill it wins, which is how the table
# expresses "dcterms:identifier, else adms:identifier" with no conditional
# logic here. Walking the document instead would make precedence depend on
# JSON key order.
_SEGMENT_RE = re.compile(r"^([^\[]+)(?:\[([^\]]*)\])?$")


def _parse_segment(text):
    """"name[key=value]" -> (name, {key: value}); "name[*]" -> (name, {})."""
    match = _SEGMENT_RE.match(text.strip())
    if not match:
        return text, None
    name, body = match.group(1), match.group(2)
    if body is None:
        return name, None
    body = body.strip()
    if body in ("", "*"):
        return name, {}
    filters = {}
    for clause in body.split(","):
        key, _, value = clause.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key:
            filters[key] = value
    return name, filters


def _path_segments(rule):
    """object_json_path as [(name, filters)], or None if it names a root key.

    "$.schema:spatialCoverage.schema:box" -> two segments; a single segment is
    a property of the record itself and is handled by the main pass.
    """
    path = (rule.get("object_json_path") or "").strip()
    if not path.startswith("$."):
        return None
    segs = [_parse_segment(p) for p in path[2:].split(".")]
    return segs if len(segs) > 1 else None


def _matches(node, filters):
    if not isinstance(node, dict):
        return False
    for key, wanted in (filters or {}).items():
        if key == "@type":
            if wanted not in _as_list(node.get("@type")):
                return False
        else:
            values = [v.get("@id") if isinstance(v, dict) else v
                      for v in _as_list(node.get(key))]
            if wanted not in values:
                return False
    return True


def _make(filters):
    """A new member satisfying `filters` -- the filter says what it must be."""
    node = {}
    for key, value in (filters or {}).items():
        node["@type" if key == "@type" else key] = (
            [value] if key == "@type" else value)
    return node


# A node this pass creates still has to say what it is, even when the path
# carried no @type filter.
_NODE_TYPES = {"prov:wasGeneratedBy": ["prov:Activity"]}


def _descend(container, segs):
    """The object the last segment should be written into."""
    for name, filters in segs[:-1]:
        array = filters is not None or _TARGET_ARITY.get(name) == "array"
        node = container.get(name)
        if array:
            if not isinstance(node, list):
                node = [] if node is None else [node]
                container[name] = node
            spot = next((x for x in node
                         if isinstance(x, dict) and _matches(x, filters)), None)
            if spot is None:
                spot = _make(filters)
                node.append(spot)
            container = spot
        else:
            if not isinstance(node, dict):
                node = _make(filters)
                container[name] = node
            container = node
        if isinstance(container, dict) and name in _NODE_TYPES:
            container.setdefault("@type", list(_NODE_TYPES[name]))
    return container


def _apply_nested(doc, ds, changes, graph=None):
    """Apply the rows whose target sits inside another property.

    Deliberately after the catalog record exists: two rows write into
    schema:subjectOf, and building that afterwards would overwrite them.
    """
    consumed = set()
    for rule in _NESTED_ROWS:
        key = rule["subject_id"]
        value = ds.get(key)
        if value is None:
            continue
        transform = _TRANSFORMS.get(rule["transform"])
        if transform is None:
            continue
        shaped = transform(_resolve(value, graph), ds, rule, doc)
        if shaped is None or shaped == [] or shaped == "":
            continue
        segs = _path_segments(rule)
        leaf = segs[-1][0]
        target = _descend(doc, segs)
        if _place(target, leaf, shaped, rule["transform"]):
            consumed.add(key)
            changes.append("%s to %s" % (key, rule["object_json_path"]))
    return consumed


_ALL_ROOT = [row for group in RULES.values() for row in group
             if row["subject_class"] in _ROOT_CLASSES and row["object_id"]]
_ALL_ROOT.sort(key=lambda row: row["_order"])

# A row whose path is "$.<one segment>" writes a property of the record; a
# deeper path writes inside one, and is applied later.
_ROOT_ROWS = [r for r in _ALL_ROOT if not _path_segments(r)]
# Parents the nested pass may build. Deliberately short: most CDIF containers
# are arrays of typed objects (a contributor is an Agent, a relatedLink is a
# link node, a keyword is a term), and writing a loose property into the first
# element invents a type-less node that does not validate and attaches the
# value to whichever member happened to be first. prov:wasGeneratedBy is the
# exception -- nothing else fills it, so building it here is unambiguous.
_NESTABLE_PARENTS = {"prov:wasGeneratedBy"}

# Every CDIF property some row writes, so a source property that shares its
# name is never mistaken for an unmapped leftover.
_ROOT_TARGETS = {r["object_id"] for r in _ALL_ROOT if r["object_id"]}

def _nestable(rule):
    """Can this row's path be built without inventing an arbitrary node?

    Yes when every step through an array either carries a filter -- which says
    both which member to use and what to create if there is none -- or names a
    container the converter fills itself. Without that, writing into the first
    member of an array of typed objects attaches the value to whichever
    sibling happened to be first.
    """
    segs = _path_segments(rule)
    if not segs:
        return False
    for name, filters in segs[:-1]:
        if filters:
            continue
        if name in _NESTABLE_PARENTS:
            continue
        if _TARGET_ARITY.get(name) == "array":
            return False
    return True


_NESTED_ROWS = [r for r in _ALL_ROOT if _nestable(r)]

# A row whose path points inside a container we will not build is left to the
# passthrough pass, so its value survives under its own property.
_ROOT_ROWS = [r for r in _ROOT_ROWS
              if not _path_segments(r)]


def _apply_table(doc, ds, changes, graph=None):
    """Apply every root-level mapping row, in table order.

    Returns the keys that actually produced a value. A key the table claims
    but could not map is NOT consumed: it falls through to the passthrough
    pass and survives. rdflib hoists nested nodes to the top level, so a
    property whose value should be an object routinely arrives as a bare
    {"@id": "_:b0"} reference that no transform can shape -- dropping those
    would lose content the source really carried.
    """
    consumed = set()
    for rule in _ROOT_ROWS:
        key = rule["subject_id"]
        value = ds.get(key)
        if value is None:
            continue
        value = _resolve(value, graph)
        transform = _TRANSFORMS.get(rule["transform"])
        if transform is None:
            continue
        if _place(doc, rule["object_id"], transform(value, ds, rule, doc),
                  rule["transform"]):
            consumed.add(key)
            changes.append("%s to %s" % (key, rule["object_id"]))
    return consumed


# ---------------------------------------------------------------------------
# Dataset discovery
# ---------------------------------------------------------------------------

def find_datasets(obj, results=None):
    """Recursively find all dcat:Dataset nodes in a JSON-LD structure."""
    if results is None:
        results = []
    if isinstance(obj, dict):
        t = obj.get("@type", "")
        if isinstance(t, list):
            if "dcat:Dataset" in t:
                results.append(obj)
        elif t == "dcat:Dataset":
            results.append(obj)
        for v in obj.values():
            find_datasets(v, results)
    elif isinstance(obj, list):
        for item in obj:
            find_datasets(item, results)
    return results


# ---------------------------------------------------------------------------
# Agent conversion
# ---------------------------------------------------------------------------

def convert_agent(agent):
    """Convert a FOAF/DCAT agent to schema:Person or schema:Organization."""
    if isinstance(agent, list):
        for item in agent:
            got = convert_agent(item)
            if got:
                return got
        return None
    if not isinstance(agent, dict):
        if isinstance(agent, str) and agent.startswith("http"):
            return {"@id": agent}
        return None
    # rdflib compacts an RDF collection to {"@list": [...]}. Taking that dict at
    # face value emitted {"@list": [...]} where an Organization belonged.
    if "@list" in agent:
        return convert_agent(agent["@list"])

    t = agent.get("@type", "")
    result = {}

    # Determine type
    if isinstance(t, list):
        t = " ".join(t)
    if "Person" in t:
        result["@type"] = ["schema:Person"]
    else:
        result["@type"] = ["schema:Organization"]

    # Name
    for name_key in ("foaf:name", "rdfs:label", "schema:name", "vcard:fn"):
        name = agent.get(name_key)
        if name:
            result["schema:name"] = _get_str(name)
            break

    # Identifier / @id
    aid = agent.get("@id")
    if aid and aid.startswith("http"):
        result["@id"] = aid

    # Email
    mbox = agent.get("foaf:mbox")
    if mbox:
        email = _get_str(mbox).replace("mailto:", "")
        result["schema:contactPoint"] = {
            "@type": ["schema:ContactPoint"],
            "schema:email": email,
        }

    # Homepage
    homepage = agent.get("foaf:homepage")
    if homepage:
        result["schema:url"] = _get_str(homepage)

    # CDIF requires a name on an agent. A DCAT record routinely gives only an
    # IRI -- an ORCID, a ROR, a publisher URI -- and emitting that alone
    # produced an agent the schema rejects, while dropping it would lose the
    # attribution entirely. Say the name is knowably absent, as the record
    # already does for a missing licence or access URL.
    if not result.get("schema:name"):
        if not result.get("@id"):
            return None
        result["schema:name"] = "http://www.opengis.net/def/nil/OGC/0/missing"
    return result


def convert_qualified_attribution(attr):
    """Convert prov:qualifiedAttribution to schema:contributor with role."""
    if not isinstance(attr, dict):
        return None

    agent = attr.get("prov:agent")
    role = attr.get("dcat:hadRole")

    converted_agent = convert_agent(agent) if isinstance(agent, dict) else None
    if not converted_agent and isinstance(agent, str):
        converted_agent = {"@id": agent}

    if not converted_agent:
        return None

    role_name = None
    if isinstance(role, dict):
        role_name = _get_str(role.get("skos:prefLabel") or role.get("rdfs:label")
                             or role.get("@id"))
    elif role:
        role_name = _get_str(role)

    if role_name:
        return {
            "@type": ["schema:Role"],
            "schema:roleName": role_name,
            "schema:contributor": converted_agent,
        }
    return converted_agent


# ---------------------------------------------------------------------------
# Distribution conversion
# ---------------------------------------------------------------------------

_DIST_ROWS = None


def _dist_rows():
    """Distribution rows, in table order. Built lazily: RULES is defined below
    the shapers this module needs at import time."""
    global _DIST_ROWS
    if _DIST_ROWS is None:
        # dcat:DataService rows included: a service is routinely the value of
        # dcat:distribution, and shaping it with the Distribution rows alone
        # produced a DataDownload whose only property was a nil access URL.
        rows = [row for group in RULES.values() for row in group
                if row["subject_class"] in ("dcat:Distribution", "dcat:DataService")
                and row["object_id"]]
        rows.sort(key=lambda row: row["_order"])
        _DIST_ROWS = rows
    return _DIST_ROWS


def convert_distribution(dist):
    """Convert a dcat:Distribution to schema:DataDownload, from the table.

    The table carries fifteen distribution rows -- title, description, licence,
    access rights, conformsTo, compression and packaging alongside the obvious
    URLs -- so hard-coding a handful here would mean the table said one thing
    and the converter did another.
    """
    if not isinstance(dist, dict):
        return None
    dist = _apply_aliases(dist, [])
    if len(dist) == 1 and "@id" in dist:
        # An unresolved reference -- the node it names is not in this document.
        # Still a distribution the source asserts, so keep it, carrying the
        # identifier it was referenced by. A blank-node label is meaningless
        # outside its document, so only a real IRI is worth keeping.
        stub = {"@type": ["schema:DataDownload"]}
        if _is_iri(dist["@id"]):
            stub["@id"] = dist["@id"]
        return stub
    result = {"@type": ["schema:DataDownload"]}
    for rule in _dist_rows():
        value = dist.get(rule["subject_id"])
        if value is None:
            continue
        transform = _TRANSFORMS.get(rule["transform"])
        if transform is None:
            continue
        _place(result, rule["object_id"], transform(value, dist, rule, result),
               rule["transform"])
    # A service endpoint replaces the download type: it is not a file. CDIF
    # does not describe services as resources in their own right, so a service
    # a dataset is reached through is recorded as how that dataset is accessed.
    types = " ".join(_as_list(dist.get("@type")))
    if result.get("schema:serviceType") or "DataService" in types:
        result["@type"] = ["schema:WebAPI"]
        result.setdefault("schema:serviceType", "dcat:DataService")
        # Typing a distribution as a WebAPI incurs the obligations CDIF puts on
        # one: a terms-of-service statement and at least one action saying how
        # it is invoked. Emitting the type without them produced a record that
        # said "this is a service" and then failed to describe it as one.
        url = result.get("schema:contentUrl")
        if url and url != NIL and not result.get("schema:potentialAction"):
            result["schema:potentialAction"] = [{
                "@type": ["schema:SearchAction"],
                "schema:target": {"@type": ["schema:EntryPoint"],
                                  # the Action's EntryPoint wants urlTemplate,
                                  # where a relatedLink's wants url
                                  "schema:urlTemplate": url},
            }]
        if not result.get("schema:termsOfService"):
            terms = (dist.get("dcterms:license") or dist.get("odrl:hasPolicy")
                     or dist.get("dcterms:accessRights"))
            got = _tf_iri(terms, dist, {"subject_id": "terms"}, result) if terms else None
            if isinstance(got, list):
                got = got[0] if got else None
            result["schema:termsOfService"] = got or NIL
    # Emitted even when nothing but the type is known. The source asserts that
    # this dataset HAS a distribution; dropping it would say the dataset has
    # none. The access URL then becomes the nil URI, which says the value is
    # knowably absent rather than merely unstated.
    return result


# ---------------------------------------------------------------------------
# Spatial / temporal coverage
# ---------------------------------------------------------------------------

def _coords_of(text):
    """Every (lon, lat) pair in a WKT or GeoJSON geometry string."""
    if not isinstance(text, str):
        return []
    pairs = []
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
        except Exception:
            return []

        def dig(node):
            if isinstance(node, list):
                if (len(node) == 2 and all(isinstance(v, (int, float)) for v in node)):
                    pairs.append((float(node[0]), float(node[1])))
                    return
                for item in node:
                    dig(item)
            elif isinstance(node, dict):
                for value in node.values():
                    dig(value)

        dig(data.get("coordinates", data))
        return pairs
    numbers = re.findall(r"-?\d+(?:\.\d+)?", stripped)
    for i in range(0, len(numbers) - 1, 2):
        pairs.append((float(numbers[i]), float(numbers[i + 1])))
    return pairs


def _box_of(text):
    """A schema:box "south west north east" enclosing a geometry, or None.

    CDIF's GeoShape requires schema:box and defines no schema:polygon, so a
    geometry has to be reduced to its envelope to be expressible at all. WKT
    and GeoJSON both order coordinates longitude first.
    """
    pairs = [(x, y) for x, y in _coords_of(text)
             if -180 <= x <= 180 and -90 <= y <= 90]
    if not pairs:
        return None
    lons = [p[0] for p in pairs]
    lats = [p[1] for p in pairs]
    return "%g %g %g %g" % (min(lats), min(lons), max(lats), max(lons))


def convert_spatial(spatial):
    """Convert dcterms:spatial to schema:spatialCoverage."""
    if not isinstance(spatial, dict):
        if isinstance(spatial, str):
            return {"@type": ["schema:Place"], "schema:name": spatial}
        return None

    place = {"@type": ["schema:Place"]}

    # Name / label
    label = spatial.get("rdfs:label") or spatial.get("locn:geographicName")
    if label:
        place["schema:name"] = _get_str(label)

    # Bounding box (WKT)
    bbox = spatial.get("dcat:bbox")
    if bbox:
        wkt = _get_str(bbox)
        place["schema:geo"] = {"@type": ["schema:GeoShape"],
                               "schema:box": _box_of(wkt) or wkt}

    # A geometry becomes the box that encloses it. CDIF's GeoShape requires
    # schema:box and has no schema:polygon, so emitting the polygon produced a
    # shape that could not validate; the geometry is kept alongside as an
    # extension rather than discarded.
    geom = spatial.get("locn:geometry")
    if geom and not bbox:
        text = _get_str(geom)
        box = _box_of(text)
        if box:
            place["schema:geo"] = {"@type": ["schema:GeoShape"],
                                   "schema:box": box}
        if text:
            place["locn:geometry"] = text

    return place if len(place) > 1 else None


def convert_temporal(temporal):
    """Convert dcterms:temporal to schema:temporalCoverage string."""
    if not isinstance(temporal, dict):
        return _get_str(temporal) if temporal else None

    start = temporal.get("dcat:startDate") or temporal.get("schema:startDate")
    end = temporal.get("dcat:endDate") or temporal.get("schema:endDate")

    if start and end:
        return f"{_get_str(start)}/{_get_str(end)}"
    elif start:
        return f"{_get_str(start)}/.."
    elif end:
        return f"../{_get_str(end)}"
    return None


# ---------------------------------------------------------------------------
# Main conversion
# ---------------------------------------------------------------------------

def convert_dcat_to_cdif(ds, catalog_name="", catalog_url="", profile="core",
                         detect=True, graph=None):
    """Convert a dcat:Dataset to CDIF schema.org JSON-LD.

    Args:
        ds: The dcat:Dataset dict.
        catalog_name: Name of the source catalog (for subjectOf).
        catalog_url: URL of the source catalog.
        profile: 'core' or 'discovery'.

    Returns:
        Converted dict.
    """
    changes = []
    doc = {"@context": dict(CDIF_CONTEXT)}

    # @id
    dsid = ds.get("@id", "")
    # Expand known prefixes
    for prefix in ("psdiDcat:", "dcat:"):
        if dsid.startswith(prefix):
            dsid = f"http://metadata.psdi.ac.uk/psdi-dcat/{dsid[len(prefix):]}"
    doc["@id"] = dsid
    doc["@type"] = ["schema:Dataset"]

    # --- Mapped properties, from converters/mappings/dcat-to-cdif.sssom.tsv ---
    ds = _apply_aliases(ds, changes)
    consumed = _apply_table(doc, ds, changes, graph)

    # --- What CDIF requires and DCAT does not guarantee ---
    # These are not term correspondences, so they are not in the table: they
    # are the converter deciding what to do when the source is silent about
    # something CDIF core insists on.

    if not doc.get("schema:name"):
        doc["schema:name"] = "Untitled"

    # dcterms:issued also serves as dateModified when nothing else does.
    if "schema:dateModified" not in doc and doc.get("schema:datePublished"):
        doc["schema:dateModified"] = doc["schema:datePublished"]
        changes.append("schema:datePublished reused as dateModified "
                       "(no dcterms:modified)")

    # Whatever the date came from -- source, fallback, or conversion time -- it
    # has to match the shape's pattern to be worth emitting. Sources carry
    # fractional seconds, which the pattern rejects.
    if "schema:dateModified" in doc:
        fixed = _normalize_date(doc["schema:dateModified"])
        if fixed:
            if fixed != doc["schema:dateModified"]:
                changes.append("schema:dateModified normalized to %s" % fixed)
            doc["schema:dateModified"] = fixed
        else:
            del doc["schema:dateModified"]

    if "schema:dateModified" not in doc:
        # Was the hardcoded "2025-01-01" -- untrue, and plausible enough to be
        # taken for real. The conversion timestamp is at least true of this
        # serialization. Seconds precision, no fractional part: that is what the
        # CDIF dateModified pattern accepts.
        doc["schema:dateModified"] = _dt.datetime.now(
            _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        changes.append("schema:dateModified set to the conversion time "
                       "(no date in source)")

    # --- Preserve unmapped DCAT properties (open world) ---
    for k, v in ds.items():
        if k in ("@context", "@type", "@id") or k in consumed or k in doc:
            continue
        # Rewrite absolute-IRI keys at EVERY depth, not just this one. The
        # passed-through value carries whole sub-objects (qualifiedRelation,
        # provenance, sample), and their nested keys break framing just as
        # readily as a top-level one.
        key, value = _prefix_keys(k, v, doc["@context"])
        doc[key] = value
    for candidate in _as_list(doc.get("@type")):
        _declare_prefix_of(candidate, doc["@context"])

    # --- Determine profile ---
    has_spatial = "schema:spatialCoverage" in doc
    has_temporal = "schema:temporalCoverage" in doc
    has_variables = "schema:variableMeasured" in doc
    actual_profile = ("discovery" if (has_spatial or has_temporal or has_variables)
                      else profile)

    # An access point is required for FAIR reuse. When the source offers neither
    # a landing page nor a distribution, say the value is knowably absent rather
    # than leaving the record silent about it.
    # Both schema:url and schema:contentUrl are declared sh:datatype xsd:string
    # (url with a ^https?://... pattern besides), so the nil URI goes in as a
    # plain string, not an {"@id": ...} reference.
    if not doc.get("schema:url") and not doc.get("schema:distribution"):
        doc["schema:url"] = "http://www.opengis.net/def/nil/OGC/0/missing"
    for _dist in (doc.get("schema:distribution") or []):
        if isinstance(_dist, dict) and not _dist.get("schema:contentUrl"):
            _dist["schema:contentUrl"] = "http://www.opengis.net/def/nil/OGC/0/missing"

    # CDIF requires licence / access-conditions information for FAIR reuse, and
    # a silent omission cannot be told from an oversight. Say it is knowably
    # absent instead.
    if not doc.get("schema:license"):
        doc["schema:license"] = [{"@id": "http://www.opengis.net/def/nil/OGC/0/missing"}]

    # --- subjectOf ---
    # 1.1 is the current series. These are only the fallback: detect_conformance
    # overrides them below from the record's actual content.
    conformsTo = [{"@id": "https://w3id.org/cdif/core/1.1"}]
    if actual_profile == "discovery":
        conformsTo.append({"@id": "https://w3id.org/cdif/discovery/1.1"})

    doc["schema:subjectOf"] = {
        "@type": ["schema:Dataset"],
        "schema:additionalType": [{"@id": "dcat:CatalogRecord"}],
        "@id": (dsid + "#metadata") if dsid else "#metadata",
        "schema:name": f"Metadata record for: {doc['schema:name'][:120]}",
        "schema:about": {"@id": dsid},
        "dcterms:conformsTo": conformsTo,
        "schema:includedInDataCatalog": {
            "@type": ["schema:DataCatalog"],
            "schema:name": catalog_name or "Unknown Catalog",
            "schema:url": catalog_url or "",
        },
        "schema:description": (
            f"Converted from DCAT to CDIF {actual_profile} profile by "
            f"dcat_to_cdif.py. Mappings applied: {'; '.join(changes)}. "
            f"Unmapped DCAT properties preserved (open world)."
        ),
    }

    # Rows that write inside another property, now that schema:subjectOf exists.
    _nested = _apply_nested(doc, ds, changes, graph)
    consumed |= _nested
    for _key in _nested:
        # Only what THIS pass consumed, and never a key that is also a CDIF
        # target: dcterms:conformsTo maps to itself, so popping every consumed
        # key deleted the value the row had just written.
        if _key not in _ROOT_TARGETS:
            doc.pop(_key, None)

    # Derive dcterms:conformsTo from the record's actual content (overrides the
    # built-in default), preserving any non-cdif domain claims.
    if detect and _HAVE_DETECT:
        try:
            uris = detect_conformance(doc)
        except Exception as exc:
            # Was a bare `pass`, which hid a broken detection as a record that
            # simply kept the fallback conformsTo -- indistinguishable from a
            # record whose content genuinely matched nothing.
            print(f"  WARNING: detect_conformance failed ({exc}); keeping the "
                  "fallback conformsTo", file=sys.stderr)
        else:
            if uris:
                apply_conformance(doc, uris)
            else:
                # Nothing detected: the content does not meet even core. Keeping
                # the built-in claim here is what made fragments look conformant,
                # so drop it -- a record that conforms to nothing declares
                # nothing, and the caller can tell the two apart.
                doc["schema:subjectOf"].pop("dcterms:conformsTo", None)

    return doc


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Convert DCAT JSON-LD to CDIF schema.org format")
    parser.add_argument("input", help="Input DCAT JSON-LD file")
    parser.add_argument("--output", "-o", type=str, default=".",
                        help="Output directory (default: current dir)")
    parser.add_argument("--catalog-name", type=str, default="",
                        help="Name of the source catalog")
    parser.add_argument("--catalog-url", type=str, default="",
                        help="URL of the source catalog")
    parser.add_argument("--profile", type=str, choices=["core", "discovery"],
                        default="core",
                        help="Target CDIF profile (default: core; auto-upgrades to discovery if spatial/temporal present)")
    parser.add_argument("--list", action="store_true",
                        help="List datasets without converting")
    parser.add_argument("--select", type=str, default=None,
                        help="Comma-separated indices to convert (default: all)")
    parser.add_argument("--validate", action="store_true",
                        help="Validate output against CDIF schema")
    parser.add_argument("--static-conformance", action="store_true",
                        help="Use the built-in conformsTo instead of deriving it "
                             "from content via detect_conformance")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    # Load input
    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Find datasets
    graph = build_node_index(data)
    if isinstance(data, dict) and data.get("@type") == "dcat:Dataset":
        datasets = [data]
    else:
        datasets = find_datasets(data)

    if not datasets:
        print("No dcat:Dataset records found.")
        return 1

    print(f"Found {len(datasets)} dcat:Dataset record(s)")

    if args.list:
        for i, ds in enumerate(datasets):
            title = _get_str(ds.get("dcterms:title", ds.get("@id", "?")))
            print(f"  [{i}] {title[:70]}")
        return 0

    # Select
    if args.select:
        indices = [int(x.strip()) for x in args.select.split(",")]
    else:
        indices = list(range(len(datasets)))

    os.makedirs(args.output, exist_ok=True)

    # Convert
    for i in indices:
        if i >= len(datasets):
            print(f"  [{i}] SKIP (out of range)")
            continue

        ds = datasets[i]
        title = _get_str(ds.get("dcterms:title", "unknown"))

        converted = convert_dcat_to_cdif(
            ds,
            catalog_name=args.catalog_name,
            catalog_url=args.catalog_url,
            profile=args.profile,
            detect=not args.static_conformance,
            graph=graph,
        )

        # Derive filename
        safe = re.sub(r"[^a-z0-9-]", "", title[:40].lower().replace(" ", "-"))
        filename = f"dcat-{safe}.jsonld"
        outpath = os.path.join(args.output, filename)

        with open(outpath, "w", encoding="utf-8") as f:
            json.dump(converted, f, indent=2, ensure_ascii=False)

        profile_used = "discovery" if "https://w3id.org/cdif/discovery/1.1" in str(
            converted.get("schema:subjectOf", {}).get("dcterms:conformsTo", [])
        ) else "core"
        print(f"  [{i}] {profile_used:9s} {filename}: {title[:50]}")

    # Validate if requested
    if args.validate:
        try:
            from jsonschema import Draft202012Validator

            bb_dir = os.environ.get(
                "CDIF_BB_DIR",
                os.path.join(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "..", "metadataBuildingBlocks", "_sources",
                ),
            )
            core_schema = json.load(open(
                os.path.join(bb_dir, "cdifProperties/cdifCore/resolvedSchema.json"),
                encoding="utf-8",
            ))

            print("\nValidation:")
            for i in indices:
                if i >= len(datasets):
                    continue
                title = _get_str(datasets[i].get("dcterms:title", "unknown"))
                safe = re.sub(r"[^a-z0-9-]", "", title[:40].lower().replace(" ", "-"))
                outpath = os.path.join(args.output, f"dcat-{safe}.jsonld")
                if os.path.exists(outpath):
                    doc = json.load(open(outpath, encoding="utf-8"))
                    errors = list(Draft202012Validator(core_schema).iter_errors(doc))
                    status = "PASS" if not errors else f"FAIL({len(errors)})"
                    print(f"  {status:8s} dcat-{safe}.jsonld")
                    if args.verbose:
                        for e in errors[:3]:
                            p = "/".join(str(x) for x in e.absolute_path) or "(root)"
                            print(f"           {p}: {e.message[:120]}")
        except ImportError:
            print("  (jsonschema not installed, skipping validation)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
