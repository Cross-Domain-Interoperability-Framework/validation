#!/usr/bin/env python3
"""Apply an SSSOM mapping table to a document.

The generic half of what `DCAT/dcat_to_cdif.py` does, factored out so the
Croissant converters can use it rather than growing a third copy. It knows
about the two extension columns this project adds to SSSOM:

    subject_class   the class the source property sits on. Needed because
                    these vocabularies are graphs, not trees: sc:name means
                    one thing on a Croissant Dataset, another on a FileObject
                    and a third on a Field, and a flat subject -> object table
                    cannot say so.

    transform       names the shaper to apply. The table carries the term
                    correspondences -- the bulk and the tedium -- and the
                    caller supplies a small dict of shapers for the structural
                    work no table can express.

What it deliberately does NOT know: any particular vocabulary. Callers pass
their own shapers and arity, so the same engine serves Croissant -> CDIF and
CDIF -> Croissant, which have different targets and opposite directions.

Row order is precedence. For a scalar target the first row to fill it wins,
which is how "prefer this source property, else that one" is expressed with no
conditional logic in the converter. Array targets accumulate instead; getting
that backwards silently drops every source but the first.
"""

import io
import os

__all__ = ["MappingSet", "load_table", "load_aliases"]


def load_table(path):
    """Rows of an SSSOM TSV as dicts, in file order.

    Deliberately fatal when the file is missing: a converter that silently
    produced empty records because its mapping table was absent would look
    exactly like a converter that found nothing to map.
    """
    with io.open(path, encoding="utf-8") as fh:
        text = fh.read()
    lines = text.replace("\r\n", "\n").strip("\n").split("\n")
    header = lines[0].split("\t")
    rows = []
    for order, line in enumerate(lines[1:]):
        if not line.strip():
            continue
        cells = line.split("\t")
        cells += [""] * (len(header) - len(cells))
        row = dict(zip(header, cells))
        row["_order"] = order
        rows.append(row)
    return rows


def load_aliases(path):
    """{source IRI: the IRI the mapping table keys on}."""
    out = {}
    for row in load_table(path):
        if row.get("subject_id") and row.get("object_id"):
            out[row["subject_id"]] = row["object_id"]
    return out


class MappingSet(object):
    """One direction of one mapping, ready to apply.

    `transforms` is {name: fn(value, source, rule, target)} -> the shaped
    value, or None to emit nothing. `arity` is {target: 'array' | 'ordered'};
    anything unlisted is a single value.
    """

    def __init__(self, table_path, alias_path=None, transforms=None,
                 arity=None, accumulating=()):
        self.rows = load_table(table_path)
        self.aliases = load_aliases(alias_path) if alias_path else {}
        self.transforms = dict(transforms or {})
        self.arity = dict(arity or {})
        self.accumulating = set(accumulating)
        self.by_subject = {}
        for row in self.rows:
            self.by_subject.setdefault(row["subject_id"], []).append(row)

    # -- selection ---------------------------------------------------------

    def rows_for(self, classes):
        """Rows that apply to any of `classes` and have a target, in order."""
        got = [r for r in self.rows
               if r.get("subject_class") in classes and r.get("object_id")]
        got.sort(key=lambda r: r["_order"])
        return got

    def rule_for(self, subject, classes):
        for row in self.by_subject.get(subject, ()):
            if row.get("subject_class") in classes:
                return row
        return None

    def claimed(self, classes):
        """Every source property the table claims for `classes`."""
        return {r["subject_id"] for r in self.rows_for(classes)}

    # -- application -------------------------------------------------------

    def resolve(self, key):
        """`key` as the mapping table spells it."""
        return self.aliases.get(key, key)

    def place(self, target_doc, target, value, transform=""):
        """Put `value` at `target`, shaped the way the target vocabulary wants.

        Three arities, because these schemas have three: accumulating shapers
        add to a slot another row already filled; an array target gathers every
        source that maps to it; a scalar target keeps the first, which is what
        makes row order express precedence.
        """
        if value is None or value == [] or value == "":
            return False
        kind = self.arity.get(target)
        if transform in self.accumulating:
            items = value if isinstance(value, list) else [value]
            if kind == "array":
                existing = target_doc.get(target) or []
                for item in items:
                    if item not in existing:
                        existing.append(item)
                target_doc[target] = existing
            else:
                joined = "\n\n".join(str(i) for i in items)
                target_doc[target] = (
                    target_doc[target] + "\n\n" + joined
                    if target_doc.get(target) else joined)
            return True
        if kind == "ordered":
            target_doc[target] = {"@list": value if isinstance(value, list) else [value]}
        elif kind == "array":
            items = value if isinstance(value, list) else [value]
            existing = target_doc.get(target) or []
            for item in items:
                if item not in existing:
                    existing.append(item)
            target_doc[target] = existing
        else:
            if target in target_doc:
                return False
            target_doc[target] = value[0] if isinstance(value, list) else value
        return True

    def apply(self, source, target_doc, classes, changes=None, curie_of=None):
        """Apply every row for `classes`. Returns the source keys consumed.

        A key the table claims but could not map is NOT reported as consumed:
        it falls through to the caller's passthrough so its value survives. A
        shaper that cannot do its job is a reason to keep the source property,
        not to drop it.
        """
        changes = changes if changes is not None else []
        consumed = set()
        for rule in self.rows_for(classes):
            subject = rule["subject_id"]
            value, raw_key = self._lookup(source, subject, curie_of)
            if value is None:
                continue
            shaper = self.transforms.get(rule.get("transform", ""))
            if shaper is None:
                continue
            shaped = shaper(value, source, rule, target_doc)
            if self.place(target_doc, rule["object_id"], shaped,
                          rule.get("transform", "")):
                consumed.add(raw_key)
                changes.append("%s to %s" % (subject, rule["object_id"]))
        return consumed

    def _lookup(self, source, subject, curie_of):
        """(value, the key it was found under) for `subject` in `source`.

        `curie_of` maps a document key to the spelling the table uses --
        Croissant writes bare terms (`name`), the table keys on `sc:name`.
        Without it the key is compared directly.
        """
        if curie_of is None:
            return source.get(subject), subject
        for key, value in source.items():
            if key.startswith("@"):
                continue
            if self.resolve(curie_of(key)) == subject:
                return value, key
        return None, subject
