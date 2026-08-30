#!/usr/bin/env python3
"""Enumerate the literal-valued leaf fields of a DDI Codebook XML Schema.

Used by sync_ddi_mappings.py to keep the SSSOM worksheets in step with the
schema: every text-bearing element under the main description branches should
appear as a subject, and every subject should trace to a real element.

`leaf_fields(xsd_path)` returns the ordered dotted paths of the text-bearing
elements (e.g. "stdyDscr.citation.titlStmt.titl"). Attributes are not returned
-- the worksheets carry only the handful of data-bearing attributes explicitly,
so attribute rows are whitelisted by the caller rather than enumerated here.
"""
import xml.etree.ElementTree as ET

XS = "http://www.w3.org/2001/XMLSchema"
DEFAULT_BRANCHES = ["stdyDscr", "fileDscr", "dataDscr", "docDscr"]
XS_PRIM = {"string", "token", "normalizedString", "anyURI", "date", "dateTime",
           "gYear", "gYearMonth", "gMonth", "gDay", "gMonthDay", "integer", "int",
           "long", "decimal", "float", "double", "boolean", "NMTOKEN", "NMTOKENS",
           "ID", "IDREF", "IDREFS", "language", "duration", "time",
           "positiveInteger", "nonNegativeInteger", "QName"}


def _q(t):
    return "{%s}%s" % (XS, t)


def _loc(ref):
    return ref.split(":")[-1] if ref else ref


class Schema:
    def __init__(self, path):
        self.root = ET.parse(path).getroot()
        self.ct, self.st, self.ag, self.grp = {}, {}, {}, {}
        for c in self.root:
            n = c.get("name")
            if not n:
                continue
            if c.tag == _q("complexType"):
                self.ct[n] = c
            elif c.tag == _q("simpleType"):
                self.st[n] = c
            elif c.tag == _q("attributeGroup"):
                self.ag[n] = c
            elif c.tag == _q("group"):
                self.grp[n] = c
        # element name -> type across ALL declarations (global + local); DDI uses
        # a consistent <name> -> <name>Type convention so first-wins is fine
        self.etm = {}
        for e in self.root.iter(_q("element")):
            n, t = e.get("name"), e.get("type")
            if n and t and n not in self.etm:
                self.etm[n] = _loc(t)

    def elem_type(self, elem):
        if elem in self.etm:
            return self.etm[elem]
        if (elem + "Type") in self.ct:
            return elem + "Type"
        return None

    def is_text(self, tname, seen=None):
        if tname is None:
            return False
        if tname in XS_PRIM or tname in self.st:
            return True
        seen = seen or set()
        if tname in seen:
            return False
        seen.add(tname)
        ct = self.ct.get(tname)
        if ct is None:
            return tname in XS_PRIM
        if ct.get("mixed") == "true":
            return True
        if ct.find(_q("simpleContent")) is not None:
            return True
        cc = ct.find(_q("complexContent"))
        if cc is not None:
            ext = cc.find(_q("extension"))
            if ext is None:
                ext = cc.find(_q("restriction"))
            if ext is not None:
                if ext.get("mixed") == "true":
                    return True
                if self.is_text(_loc(ext.get("base")), seen):
                    return True
        return False

    def _collect(self, node, elems, seen_g):
        for ch in node:
            t = ch.tag
            if t == _q("element"):
                nm = ch.get("name") or _loc(ch.get("ref"))
                if nm:
                    elems.append(nm)
            elif t in (_q("sequence"), _q("choice"), _q("all")):
                self._collect(ch, elems, seen_g)
            elif t == _q("group"):
                gref = _loc(ch.get("ref"))
                if gref and gref in self.grp and gref not in seen_g:
                    seen_g.add(gref)
                    self._collect(self.grp[gref], elems, seen_g)

    def children(self, tname, seen=None):
        ct = self.ct.get(tname)
        if ct is None:
            return []
        seen = seen or set()
        if tname in seen:
            return []
        seen.add(tname)
        elems = []
        for kid in ct:
            if kid.tag in (_q("sequence"), _q("choice"), _q("all")):
                self._collect(kid, elems, set())
            elif kid.tag == _q("complexContent"):
                ext = kid.find(_q("extension"))
                if ext is None:
                    ext = kid.find(_q("restriction"))
                if ext is not None:
                    base = _loc(ext.get("base"))
                    elems += self.children(base, seen)
                    self._collect(ext, elems, set())
        return list(dict.fromkeys(elems))


def _walk(sch, elem, path, visited, out, depth=0):
    if depth > 30:
        return
    et = sch.elem_type(elem)
    if et is None or sch.is_text(et):
        out.append(path)
        return
    if et in visited:
        out.append(path)   # recursion cut -> record as a field location
        return
    kids = sch.children(et)
    if not kids:
        return
    v2 = visited | {et}
    for cn in kids:
        _walk(sch, cn, path + "." + cn, v2, out, depth + 1)


def leaf_fields(xsd_path, branches=None):
    """Ordered dotted paths of text-bearing elements under the given branches."""
    sch = Schema(xsd_path)
    out = []
    for b in (branches or DEFAULT_BRANCHES):
        _walk(sch, b, b, set(), out)
    seen, ordered = set(), []
    for p in out:
        if p not in seen:
            seen.add(p)
            ordered.append(p)
    return ordered


if __name__ == "__main__":
    import sys
    fields = leaf_fields(sys.argv[1])
    print("%d leaf fields" % len(fields))
    for f in fields[:20]:
        print("  " + f)
