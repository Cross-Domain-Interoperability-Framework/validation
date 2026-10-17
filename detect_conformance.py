#!/usr/bin/env python3
"""detect_conformance.py — determine which conformance classes a record should
declare, from its actual content, in two stages.

**Stage 1 — CDIF modules** (``detect_cdif_conformance``): the six CDIF profile
classes (core, discovery, data_description, data_structure, provenance,
manifest), each an independent yes/no. This is the original engine; the old name
``detect_conformance`` is kept as a deprecated alias.

**Stage 2 — domain profiles** (``detect_domain_conformance``): profiles that
*layer on* the CDIF modules — geochemProduct (needs the CDIF modules),
adaProduct (needs geochemProduct), and the ~70 technique profiles (need
adaProduct). These are NOT independent: a class's ``requires`` must already be
declared (by stage 1 or an earlier stage-2 class), and technique profiles form
an ``exclusiveGroup`` where the most specific (highest ``priority``) wins —
equal priority among applicable members is a *declared tie*, reported rather
than resolved. Stage 2 manages its own profile namespace
(``https://w3id.org/geochem/metadata/profiles/``) and leaves the CDIF entries
alone.

A generator (ada loader, ConvertFromCroissant, DCAT, DDI, ...) builds a CDIF
JSON-LD record, then calls these to set schema:subjectOf/dcterms:conformsTo from
what the record actually contains — instead of hardcoding a fixed profile list
(which over-declares).

Two signals per conformance class, both evaluated on the RDF graph (no framing,
so no normalization artifacts like dropped empty arrays):

  presence  — a SPARQL ASK testing whether the record uses the elements this
              class *introduces beyond its base*. (Not "is property X present":
              prov:wasGeneratedBy is core, so it can't mark cdifProv; the marker
              is the dual-typed prov:Activity+schema:Action with richer
              properties. Likewise data_description is marked by cdi:InstanceVariable
              typing, not by any schema:variableMeasured.)
  validity  — the class's CONTENT SHACL shapes raise no sh:Violation on the
              record. IMPORTANT: the gate uses building-block *content* shapes
              (cdifDataType/<block>/rules.shacl), NOT the *profile* rules.shacl.
              Profile shapes are circular for this purpose — they require the
              catalog record to already *declare* conformance to that profile
              (the metadataProfileProperty requirement), so they validate an
              already-declared record, they can't decide declaration. (sh:Warning
              / sh:Info are advisory and never block, per CDIF severity policy.)

A class is declared iff presence AND (no SHACL, or SHACL conforms).

The CONFORMANCE_CLASSES registry below is the default home for these rules, but
each rule (conformsTo URI + ASK + shapes) can also live WITH the building block
that defines the class, as a ``conformance.json`` sidecar — see
docs/CDIF-Conformance-Declaration-Convention.md. Run with ``--from-source`` (or
env ``CDIF_CONFORMANCE_FROM_SOURCE=1``) to read the rules from the BB sources via
load_bb_conformance() instead of the registry. This is how new classes (e.g.
geochem) register their own presence rule without editing this file.

Usage:
    python detect_conformance.py record.jsonld            # print declarable URIs
    python detect_conformance.py record.jsonld --no-shacl # presence only
    python detect_conformance.py record.jsonld --from-source  # read BB sidecars
    python detect_conformance.py record.jsonld --apply -o out.jsonld  # write conformsTo

The per-class SHACL validity shapes resolve from a local building-block
``_sources`` tree when one is present; otherwise they are fetched automatically
from the metadataBuildingBlocks repo on GitHub (raw). The git ref is configurable
(``--bb-ref``, env ``CDIF_BB_REF``; default ``main``) so detection can be pinned
for reproducibility, and ``--cache-dir`` caches fetched shapes between runs.

Dependencies: pip install rdflib pyshacl requests   (requests only for the
remote SHACL fallback; pyld optional, rdflib parses JSON-LD)
"""
import argparse
import json
import os
import sys
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import rdflib

try:
    from pyshacl import validate as shacl_validate
    HAS_PYSHACL = True
except ImportError:
    HAS_PYSHACL = False

# SPARQL prefix preamble shared by every presence ASK.
PREFIXES = """
PREFIX schema: <http://schema.org/>
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX cdi: <http://ddialliance.org/Specification/DDI-CDI/1.0/RDF/>
PREFIX cdif: <https://w3id.org/cdif/>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX dcat: <http://www.w3.org/ns/dcat#>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
PREFIX dqv: <http://www.w3.org/ns/dqv#>
"""

# Interim registry. Each entry mirrors what would live with the building block
# that defines the class: the conformsTo URI, a presence ASK (elements the class
# introduces beyond its base), and the per-class SHACL shapes (relative to the
# BB _sources dir) used as the validity gate. shacl=None => presence-only.
CONFORMANCE_CLASSES = [
    {
        "uri": "https://w3id.org/cdif/core/1.1",
        # A described dataset: a schema:Dataset (not the catalog record) with a
        # name and an identifier.
        "presence": """ASK {
            ?d a schema:Dataset ; schema:name ?n ; schema:identifier ?i .
            FILTER NOT EXISTS { ?d schema:additionalType dcat:CatalogRecord }
        }""",
        "shacl": None,  # baseline; structural validity is the JSON Schema's job
    },
    {
        "uri": "https://w3id.org/cdif/discovery/1.1",
        # Marked by USE of the enrichment properties cdifDiscovery introduces
        # beyond core -- measurementTechnique, variableMeasured, spatialCoverage,
        # temporalCoverage, dqv:hasQualityMeasurement -- not by name+identifier
        # (which is a core marker and fires for every dataset). schema:subjectOf
        # is also a cdifDiscovery property but is the catalog-record pointer every
        # CDIF record carries, so it does not discriminate and is excluded.
        "presence": """ASK {
            ?d a schema:Dataset .
            FILTER NOT EXISTS { ?d schema:additionalType dcat:CatalogRecord }
            { ?d schema:measurementTechnique ?x } UNION
            { ?d schema:variableMeasured ?x } UNION
            { ?d schema:spatialCoverage ?x } UNION
            { ?d schema:temporalCoverage ?x } UNION
            { ?d dqv:hasQualityMeasurement ?x }
        }""",
        "shacl": None,  # cdifDiscovery is a thin wrapper (no rules.shacl)
    },
    {
        "uri": "https://w3id.org/cdif/data_description/1.1",
        # Marked by DDI-CDI InstanceVariable-typed variables (not just any
        # schema:variableMeasured, which is discovery-level PropertyValue).
        "presence": """ASK {
            ?d schema:variableMeasured ?v . ?v a cdi:InstanceVariable .
        }""",
        "shacl": "cdifDataType/cdifInstanceVariable/rules.shacl",
    },
    {
        "uri": "https://w3id.org/cdif/data_structure/1.1",
        # Marked by an explicit data-structure description: an isStructuredBy
        # link to a DataStructure node, or a node typed as one of the DDI-CDI
        # structure classes.
        #
        # cdi:, not cdif:. The property takes a canonical DDI-CDI structure
        # (cdi:LongDataStructure and friends, carrying
        # cdi:has_DataStructureComponent), so the namespace policy puts it in
        # cdi:. A cdif:isStructuredBy spelling existed in one unreferenced
        # building block and had spread to a mapping table and one record; all
        # were migrated and the block retired, so testing it here would only
        # keep a dead IRI alive.
        #
        # cdi:DataStructure sits alongside the three specialisations. It is one
        # of the profile's four variants and was missing here, so a record
        # using the base class went undetected.
        "presence": """ASK {
            { ?x cdi:isStructuredBy ?s }
            UNION { ?n a cdi:DataStructure }
            UNION { ?n a cdi:LongDataStructure }
            UNION { ?n a cdi:WideDataStructure }
            UNION { ?n a cdi:DimensionalDataStructure }
        }""",
        "shacl": "cdifDataType/cdifDataStructureComponent/rules.shacl",
    },
    {
        "uri": "https://w3id.org/cdif/provenance/1.1",
        # NOT merely prov:wasGeneratedBy (that minimal prov:Activity + prov:used
        # is declared in cdifCore). The cdifProv class is marked by a dual-typed
        # prov:Activity + schema:Action carrying properties beyond prov:used.
        "presence": """ASK {
            ?d prov:wasGeneratedBy ?a .
            ?a a prov:Activity, schema:Action ; ?p ?o .
            FILTER (?p NOT IN (rdf:type, prov:used))
        }""",
        "shacl": "cdifDataType/cdifProvActivity/rules.shacl",
    },
    {
        "uri": "https://w3id.org/cdif/manifest/1.1",
        # Marked by schema:hasPart in either of the two places the profile
        # declares it: on a distribution item, for archive members with no
        # address of their own (profile 3.5); or on the Dataset, for package
        # members that are independently accessible (3.1/3.2). Only the first
        # was detected until 2026-09-05 -- Dataset-level hasPart did not exist
        # in CDIF until 2026-08-06 and this rule predated it, so a record using
        # resourcePartArray used the profile without ever declaring it.
        # The schema:Dataset constraint is load-bearing: ?d is unbound here, and
        # schema:hasPart also means instrument sub-components and workflow
        # sub-workflows, which are not manifests.
        "presence": """ASK {
            { ?d schema:distribution ?dd . ?dd schema:hasPart ?p }
            UNION
            { ?d a schema:Dataset ; schema:hasPart ?p }
        }""",
        "shacl": None,  # cdifArchiveDistribution has no content rules.shacl yet
    },
]


def _find_bb_dir(explicit=None):
    """Locate the building-block _sources dir for SHACL resolution."""
    if explicit:
        return Path(explicit)
    env = os.environ.get("CDIF_BB_DIR")
    if env and Path(env).is_dir():
        return Path(env)
    here = Path(__file__).resolve().parent
    for c in [here / "BuildingBlockSubmodule" / "_sources",
              here.parent / "metadataBuildingBlocks" / "_sources"]:
        if c.is_dir():
            return c
    return None


# ---------------------------------------------------------------------------
# Content-SHACL resolution — local _sources when present, else GitHub raw
# ---------------------------------------------------------------------------

# When no local building-block _sources tree is found, the per-class validity
# shapes are fetched from the metadataBuildingBlocks repo on GitHub. The ref
# (branch, tag, or commit) is configurable so detection can be pinned.
DEFAULT_BB_REF = "main"
BB_RAW_BASE_TEMPLATE = (
    "https://raw.githubusercontent.com/Cross-Domain-Interoperability-Framework/"
    "metadataBuildingBlocks/{ref}/_sources"
)


def _bb_raw_base(ref=None):
    """Base URL for remote _sources content. Precedence: CDIF_BB_RAW_BASE (full
    base override) > explicit ref arg > CDIF_BB_REF env > DEFAULT_BB_REF."""
    override = os.environ.get("CDIF_BB_RAW_BASE")
    if override:
        return override.rstrip("/")
    ref = ref or os.environ.get("CDIF_BB_REF") or DEFAULT_BB_REF
    return BB_RAW_BASE_TEMPLATE.format(ref=ref)


class _ShapesResolver:
    """Resolve a per-class content-SHACL path (e.g.
    ``cdifDataType/cdifInstanceVariable/rules.shacl``) to Turtle text.

    Uses a local building-block ``_sources`` dir when one is available; otherwise
    auto-falls-back to the metadataBuildingBlocks repo on GitHub (raw), over HTTP.
    Results are memoized; remote fetches may also be cached on disk via
    ``cache_dir``. ``get()`` returns None when a path can't be resolved, so a
    missing shape simply skips that class's validity gate (presence still counts).
    """

    def __init__(self, bb_dir=None, ref=None, cache_dir=None, verbose=False):
        self.bb_dir = Path(bb_dir) if bb_dir else None
        self.remote = self.bb_dir is None
        self.base = _bb_raw_base(ref) if self.remote else None
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.verbose = verbose
        self._mem = {}

    def source_label(self):
        return f"local {self.bb_dir}" if not self.remote else f"remote {self.base}"

    def get(self, rel_path):
        if rel_path not in self._mem:
            self._mem[rel_path] = (self._local(rel_path) if not self.remote
                                   else self._remote(rel_path))
        return self._mem[rel_path]

    def _local(self, rel_path):
        p = self.bb_dir / rel_path
        return p.read_text(encoding="utf-8") if p.is_file() else None

    def _remote(self, rel_path):
        cp = None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            cp = self.cache_dir / rel_path.replace("/", "_")
            if cp.exists():
                return cp.read_text(encoding="utf-8")
        url = f"{self.base}/{rel_path}"
        try:
            import requests
            r = requests.get(url, timeout=30)
        except Exception as e:
            if self.verbose:
                print(f"    remote SHACL fetch error ({url}): {e}", file=sys.stderr)
            return None
        if r.status_code != 200:
            if self.verbose:
                print(f"    remote SHACL HTTP {r.status_code}: {url}", file=sys.stderr)
            return None
        if cp is not None:
            cp.write_text(r.text, encoding="utf-8")
        return r.text


def _to_graph(doc):
    """Parse a CDIF JSON-LD dict into an rdflib Graph (expanded triples).

    Fails LOUDLY if JSON-LD parsing is unavailable or yields nothing from a
    non-empty document: otherwise an empty graph makes every presence ASK false
    and detection silently reports zero conformance — indistinguishable from a
    record that genuinely conforms to nothing."""
    g = rdflib.Graph()
    try:
        g.parse(data=json.dumps(doc), format="json-ld")
    except Exception as e:  # missing/!registered json-ld parser, bad context, ...
        raise RuntimeError(
            f"rdflib could not parse the document as JSON-LD "
            f"({type(e).__name__}: {e}). Ensure JSON-LD support is active "
            f"(rdflib>=6 has it built in; older rdflib needs the rdflib-jsonld "
            f"plugin). rdflib in use: {rdflib.__version__}.") from e
    # A real CDIF record (more than a bare @context) always yields triples. An
    # empty graph here means the parser did not run, not that the record is empty.
    substantive = isinstance(doc, dict) and (
        doc.get("@graph") or [k for k in doc if k != "@context"])
    if len(g) == 0 and substantive:
        raise RuntimeError(
            "JSON-LD parsed to an EMPTY graph from a non-empty document, so "
            "conformance detection would wrongly report nothing. rdflib's "
            "JSON-LD parser is likely not active here "
            f"(rdflib {rdflib.__version__}); verify format='json-ld' parses a "
            "known-good CDIF record to a non-empty graph.")
    return g


def load_bb_conformance(bb_dir):
    """Read per-building-block conformance declarations from a BB _sources tree.

    Scans for ``conformance.json`` sidecars (one per profile building block; see
    docs/CDIF-Conformance-Declaration-Convention.md) and returns class entries in
    the SAME shape as the CONFORMANCE_CLASSES registry — ``{uri, presence, shacl}``
    — so detect_conformance() can consume either source. ``validityShapes`` paths
    are relative to ``bb_dir`` (the _sources root), exactly as the registry's
    ``shacl`` paths are. Returns [] if no sidecars are found.

    This is the migration path away from the hardcoded registry: once every
    profile BB carries a sidecar, detect_conformance can read its rules from the
    building blocks that define them (run with ``use_bb_source=True`` or
    ``CDIF_CONFORMANCE_FROM_SOURCE=1``)."""
    classes = []
    root = Path(bb_dir)
    if not root.is_dir():
        return classes
    for path in sorted(root.glob("**/conformance.json")):
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        uri, ask = d.get("conformsTo"), d.get("presence")
        if not uri or not ask:
            continue
        # requires / exclusiveGroup / priority are the 0.2 stage-2 fields; stage 1
        # never reads them, so carrying them through is harmless for CDIF classes.
        classes.append({"uri": uri, "presence": ask,
                        "shacl": d.get("validityShapes"),
                        "requires": d.get("requires", []),
                        "exclusiveGroup": d.get("exclusiveGroup"),
                        "priority": d.get("priority", 0)})
    return classes


def detect_cdif_conformance(doc, bb_dir=None, do_shacl=True, verbose=False,
                            use_bb_source=None, ref=None, cache_dir=None):
    """Stage 1. Return the list of CDIF conformsTo URIs the record should declare,
    based on its content (presence ASK) and well-formedness (per-class SHACL).

    By default the rules come from the hardcoded CONFORMANCE_CLASSES registry.
    Set ``use_bb_source=True`` (or env ``CDIF_CONFORMANCE_FROM_SOURCE=1``) to read
    them instead from the building blocks' ``conformance.json`` sidecars via
    load_bb_conformance() — the eventual source of truth. Falls back to the
    registry if no sidecars are found.

    The per-class SHACL validity shapes resolve from a local ``_sources`` tree
    when one is found, else are fetched from the metadataBuildingBlocks repo on
    GitHub at ``ref`` (default ``main``; env ``CDIF_BB_REF``), optionally cached
    under ``cache_dir``."""
    if use_bb_source is None:
        use_bb_source = os.environ.get("CDIF_CONFORMANCE_FROM_SOURCE") == "1"
    graph = _to_graph(doc)
    bb = _find_bb_dir(bb_dir) if (do_shacl or use_bb_source) else None

    # Validity-gate shapes: local _sources when present, else auto-fallback to
    # the metadataBuildingBlocks repo on GitHub.
    resolver = None
    if do_shacl and HAS_PYSHACL:
        resolver = _ShapesResolver(bb_dir=bb, ref=ref, cache_dir=cache_dir,
                                   verbose=verbose)
        if verbose:
            print(f"  SHACL shapes: {resolver.source_label()}", file=sys.stderr)

    classes = CONFORMANCE_CLASSES
    if use_bb_source and bb is not None:
        src = load_bb_conformance(bb)
        if src:
            classes = src
            if verbose:
                print(f"  using {len(src)} source-declared conformance "
                      f"class(es) from {bb}", file=sys.stderr)
    declared = []
    for cls in classes:
        present = bool(graph.query(PREFIXES + cls["presence"]).askAnswer)
        if verbose:
            print(f"  presence {cls['uri'].split('/cdif/')[-1]:18} {present}",
                  file=sys.stderr)
        if not present:
            continue
        if do_shacl and cls["shacl"] and resolver is not None:
            shapes_ttl = resolver.get(cls["shacl"])
            if shapes_ttl:
                _conforms, results_graph, _t = shacl_validate(
                    graph, shacl_graph=shapes_ttl,
                    shacl_graph_format="turtle", inference="rdfs",
                    advanced=True)
                # Only sh:Violation blocks declaration; sh:Warning / sh:Info are
                # advisory (consistent with CDIF's severity policy).
                sh = rdflib.Namespace("http://www.w3.org/ns/shacl#")
                violations = list(results_graph.triples(
                    (None, sh.resultSeverity, sh.Violation)))
                if violations:
                    if verbose:
                        print(f"    -> {len(violations)} SHACL violation(s); "
                              f"not declaring", file=sys.stderr)
                    continue
        declared.append(cls["uri"])
    return declared


def detect_conformance(*args, **kwargs):
    """Deprecated alias for :func:`detect_cdif_conformance`.

    Retained so existing callers — the format converters, ConformanceValidate.py,
    tools/FrameAndValidate.py — keep working across the rename. Prefer
    ``detect_cdif_conformance`` in new code. Emits a ``DeprecationWarning``
    (silent by default in library context, per Python's warning policy)."""
    warnings.warn(
        "detect_conformance() is deprecated; use detect_cdif_conformance()",
        DeprecationWarning, stacklevel=2)
    return detect_cdif_conformance(*args, **kwargs)


# CDIF profile URIs all live under this base. apply_conformance manages exactly
# this space and leaves any other conformsTo entries (e.g. a domain-specific
# profile) untouched.
CDIF_BASE = "https://w3id.org/cdif/"

# Stage-2 domain profiles (geochemProduct, adaProduct, technique profiles) live
# under this base. detect_domain_conformance / apply_conformance manage exactly
# this space and leave the CDIF (and any other) entries alone.
GEOCHEM_BASE = "https://w3id.org/geochem/metadata/profiles/"


def apply_conformance(doc, uris, manage_prefix=CDIF_BASE, append=False):
    """Set schema:subjectOf.dcterms:conformsTo to the detected URIs (in place).

    Only the profile space under ``manage_prefix`` is replaced; any existing
    conformsTo entries outside that space are preserved. For stage 1
    (``manage_prefix=CDIF_BASE``) the detected CDIF URIs go first and any
    non-CDIF (domain) claims follow. For stage 2 (``manage_prefix=GEOCHEM_BASE``,
    ``append=True``) the preserved entries — the stage-1 CDIF URIs — stay first
    and the detected domain URIs are appended after them, so a two-stage run
    reads CDIF-then-domain."""
    subj = doc.get("schema:subjectOf")
    if not isinstance(subj, dict):
        return doc
    preserved = []
    existing = subj.get("dcterms:conformsTo")
    if isinstance(existing, list):
        for entry in existing:
            ref = entry.get("@id") if isinstance(entry, dict) else entry
            if isinstance(ref, str) and not ref.startswith(manage_prefix):
                preserved.append(entry)
    managed = [{"@id": u} for u in uris]
    subj["dcterms:conformsTo"] = (preserved + managed) if append else (managed + preserved)
    return doc


# ---------------------------------------------------------------------------
# Stage 2 — domain profiles (geochemProduct / adaProduct / technique profiles)
# ---------------------------------------------------------------------------

@dataclass
class DomainConformanceResult:
    """Outcome of :func:`detect_domain_conformance`.

    ``declared``  — domain URIs declared, in resolution order.
    ``withheld``  — classes whose *presence held* but that were NOT declared,
                    each ``{"uri", "reason", "detail"}``. reason is
                    ``"unsatisfied requires"`` (a required conformsTo is absent)
                    or ``"validity gate failed"`` (content SHACL raised a
                    sh:Violation). These are failures: detect-then-validate must
                    never silently declare less than presence says applies.
    ``ties``      — exclusiveGroups where the top ``priority`` was shared by more
                    than one applicable member, each ``{"group", "priority",
                    "candidates"}``. A tie is *ambiguity*, not a failure: it is
                    the honest answer when the content cannot pick one member
                    (e.g. ICP-MS Mc/Q/Sf variants that componentType can't
                    separate). Reported, never resolved by guessing."""
    declared: list = field(default_factory=list)
    withheld: list = field(default_factory=list)
    ties: list = field(default_factory=list)

    @property
    def ok(self):
        """True when nothing was withheld (requires/validity). Ties do not make a
        run not-ok by themselves — see ``clean`` for the stricter check."""
        return not self.withheld

    @property
    def clean(self):
        """True when nothing was withheld AND no ties were reported."""
        return not self.withheld and not self.ties


def detect_domain_conformance(doc, prior_uris, bb_dir, manage_prefix=GEOCHEM_BASE,
                              do_shacl=True, verbose=False, ref=None, cache_dir=None):
    """Stage 2. Declare domain profiles that layer on the stage-1 CDIF modules.

    ``prior_uris`` is the stage-1 result (the CDIF module URIs already declared);
    it seeds the set a class's ``requires`` is checked against, and it grows as
    stage-2 classes are declared, so a chain (geochemProduct → adaProduct →
    technique) resolves to a fixpoint.

    Domain rules come from ``conformance.json`` sidecars under ``bb_dir`` (a
    *different* ``_sources`` tree — geochemBuildingBlocks, not metadataBuildingBlocks),
    read via :func:`load_bb_conformance`, which carries the 0.2 fields
    ``requires`` / ``exclusiveGroup`` / ``priority``. Only sidecars whose
    ``conformsTo`` is under ``manage_prefix`` are considered.

    Rules:

    * **requires** — a class is eligible only when every URI in its ``requires``
      is already declared (by stage 1 or an earlier stage-2 class).
    * **exclusiveGroup / priority** — among eligible members of a group, the
      single highest ``priority`` wins. Equal top priority among >1 member is a
      *declared tie*: reported, none declared. A winner excludes its lower-priority
      siblings (expected, not a failure).
    * **validity** — the winner is declared only if its content SHACL
      (``validityShapes``) raises no sh:Violation; otherwise it is withheld with a
      reason. No silent fall-back to a lower-priority sibling.
    * A class whose presence holds but whose ``requires`` can never be satisfied
      is withheld with reason ``"unsatisfied requires"``.

    Returns a :class:`DomainConformanceResult`."""
    result = DomainConformanceResult()
    bb = Path(bb_dir) if bb_dir else None
    if bb is None or not bb.is_dir():
        if verbose:
            print("  stage 2: no domain _sources dir; skipped", file=sys.stderr)
        return result
    classes = [c for c in load_bb_conformance(bb)
               if c["uri"].startswith(manage_prefix)]
    if not classes:
        if verbose:
            print(f"  stage 2: no sidecars under {manage_prefix} in {bb}",
                  file=sys.stderr)
        return result

    graph = _to_graph(doc)
    resolver = None
    if do_shacl and HAS_PYSHACL:
        resolver = _ShapesResolver(bb_dir=bb, ref=ref, cache_dir=cache_dir,
                                   verbose=verbose)

    present = {}
    for c in classes:
        present[c["uri"]] = bool(graph.query(PREFIXES + c["presence"]).askAnswer)
        if verbose:
            short = c["uri"][len(manage_prefix):]
            print(f"  presence {short:30} {present[c['uri']]}", file=sys.stderr)

    def _valid(c):
        """(ok, detail). ok=True when there is no content SHACL, the shapes can't
        be resolved, or they raise no sh:Violation."""
        if not (do_shacl and c.get("shacl") and resolver is not None):
            return True, None
        ttl = resolver.get(c["shacl"])
        if not ttl:
            return True, None
        _conf, rg, _t = shacl_validate(graph, shacl_graph=ttl,
                                       shacl_graph_format="turtle",
                                       inference="rdfs", advanced=True)
        sh = rdflib.Namespace("http://www.w3.org/ns/shacl#")
        viol = list(rg.triples((None, sh.resultSeverity, sh.Violation)))
        return (not viol), (f"{len(viol)} SHACL violation(s)" if viol else None)

    declared_set = set(prior_uris)   # CDIF modules + domain-declared-so-far
    decided = set()                  # uris finalized (declared / withheld / superseded)

    def _group_key(c):
        return c.get("exclusiveGroup") or ("\x00single\x00" + c["uri"])

    changed = True
    while changed:
        changed = False
        ready = [c for c in classes
                 if present[c["uri"]] and c["uri"] not in decided
                 and all(r in declared_set for r in c.get("requires", []))]
        groups = {}
        for c in ready:
            groups.setdefault(_group_key(c), []).append(c)
        for members in groups.values():
            maxp = max(m.get("priority", 0) for m in members)
            top = [m for m in members if m.get("priority", 0) == maxp]
            if len(top) > 1:
                continue  # tie among current ready — defer (a higher member may
                          # still become ready); reported at the fixpoint if it holds
            winner = top[0]
            ok, detail = _valid(winner)
            if ok:
                declared_set.add(winner["uri"])
                result.declared.append(winner["uri"])
            else:
                result.withheld.append({"uri": winner["uri"],
                                        "reason": "validity gate failed",
                                        "detail": detail})
            decided.add(winner["uri"])
            # The group is resolved: exclude the lower-priority siblings
            # (expected exclusion, not a failure).
            grp = winner.get("exclusiveGroup")
            if grp:
                for m in classes:
                    if m.get("exclusiveGroup") == grp:
                        decided.add(m["uri"])
            changed = True

    # Fixpoint reached. Anything whose presence holds but that is still undecided
    # is either requires-blocked (a failure) or a genuine tie (ambiguity).
    for c in classes:
        u = c["uri"]
        if u in decided or not present[u]:
            continue
        missing = [r for r in c.get("requires", []) if r not in declared_set]
        if missing:
            result.withheld.append({"uri": u, "reason": "unsatisfied requires",
                                    "detail": "missing: " + ", ".join(missing)})
        else:
            grp = c.get("exclusiveGroup")
            sibs = [m for m in classes
                    if m.get("exclusiveGroup") == grp and grp is not None
                    and present[m["uri"]] and m["uri"] not in decided
                    and all(r in declared_set for r in m.get("requires", []))]
            if sibs:
                maxp = max(m.get("priority", 0) for m in sibs)
                cands = sorted(m["uri"] for m in sibs
                               if m.get("priority", 0) == maxp)
                tie = {"group": grp, "priority": maxp, "candidates": cands}
                if tie not in result.ties:
                    result.ties.append(tie)
    if verbose:
        for w in result.withheld:
            print(f"  WITHHELD {w['uri']} ({w['reason']}: {w['detail']})",
                  file=sys.stderr)
        for t in result.ties:
            print(f"  TIE group={t['group']} priority={t['priority']} "
                  f"candidates={t['candidates']}", file=sys.stderr)
    return result


# Stage-2 technique profiles classify a record by its file componentType. gBB
# confirmed (2026-10-16): the property is this IRI (ada: => ada.astromat.org),
# and its VALUES are plain string LITERALS like "ada:SEMImageMap" (no @type
# coercion in the context), NOT IRIs.
COMPONENT_TYPE_PROPERTY = "https://ada.astromat.org/metadata/componentType"


def _sparql_str_literal(s):
    """Render a Python str as a SPARQL double-quoted string literal."""
    esc = (s.replace("\\", "\\\\").replace('"', '\\"')
            .replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t"))
    return f'"{esc}"'


def build_component_presence_ask(component_type_values,
                                 property_iri=COMPONENT_TYPE_PROPERTY):
    """Build a stage-2 technique-profile ``presence`` ASK from its DISCRIMINATING
    componentType values, so the generator passes a list and never hand-writes
    SPARQL. Returns the ASK string to store as the sidecar's ``presence``.

    Encodes two facts gBB confirmed (2026-10-16), each a known failure mode:

    * **Literal, not IRI.** componentType values are plain string literals
      (``"ada:componentType": "ada:SEMImageMap"``) — no ``@type`` coercion in the
      context — so the ASK matches a *literal*. Matching an IRI-valued property as
      a literal (or the reverse) is what made 35 gBB SHACL shapes select zero
      focus nodes (gBB PR #141); this avoids it.
    * **Path-agnostic.** componentType has two legal homes: on a bundle's
      ``schema:hasPart`` member, or on a monolithic single-file
      ``schema:distribution`` itself (gBB #136). A ``hasPart``-pinned ASK would
      silently miss the monolithic form by reporting "not present". The marker is
      therefore "the record carries componentType in {values}" at *any* path —
      measured to occur nowhere spurious (21,974 occurrences, all under
      distribution/hasPart, zero elsewhere).

    ``component_type_values`` is the discriminating list (from
    ``build_tapp.TAPP_CONFIGS[<tapp>]["component_types"]``) with the generic
    shared types (analysisLocation/report/contextPhotography/quickLook) already
    excluded. The ASK uses a full-IRI predicate and literal values, so it needs no
    prefixes beyond the engine's standard preamble. To break an ICP-MS family tie
    once records carry a TAPP reference, narrow the returned ASK with a
    ``prov:used`` clause for that reference — not covered here until the TAPP
    reference shape exists."""
    if not component_type_values:
        raise ValueError("component_type_values must be a non-empty list")
    values = " ".join(_sparql_str_literal(v) for v in component_type_values)
    return (f"ASK {{\n"
            f"  ?node <{property_iri}> ?ct .\n"
            f"  VALUES ?ct {{ {values} }}\n"
            f"}}")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("input", help="CDIF JSON-LD record")
    p.add_argument("--no-shacl", action="store_true",
                   help="presence-only (skip the SHACL validity gate)")
    p.add_argument("--bb-dir", help="building-block _sources dir (for SHACL)")
    p.add_argument("--bb-ref",
                   help="git ref (branch/tag/commit) for fetching SHACL shapes "
                        "from GitHub when no local _sources tree is found "
                        "(default: main; env CDIF_BB_REF)")
    p.add_argument("--cache-dir",
                   help="cache directory for remotely fetched SHACL shapes")
    p.add_argument("--from-source", action="store_true",
                   help="read conformance rules from BB conformance.json sidecars "
                        "instead of the hardcoded registry")
    p.add_argument("--domain-bb-dir",
                   help="run stage 2 (domain profiles): read conformance.json "
                        "sidecars from this _sources tree (e.g. geochemBuildingBlocks)")
    p.add_argument("--manage-prefix", default=GEOCHEM_BASE,
                   help="stage-2 managed profile namespace "
                        f"(default: {GEOCHEM_BASE})")
    p.add_argument("--strict-ties", action="store_true",
                   help="exit non-zero on a stage-2 tie too (default: only "
                        "withheld requires/validity failures do)")
    p.add_argument("--apply", action="store_true",
                   help="write detected conformsTo into the record")
    p.add_argument("-o", "--output", help="output path (with --apply)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    doc = json.load(open(args.input, encoding="utf-8"))
    uris = detect_cdif_conformance(doc, bb_dir=args.bb_dir,
                                   do_shacl=not args.no_shacl, verbose=args.verbose,
                                   use_bb_source=args.from_source or None,
                                   ref=args.bb_ref, cache_dir=args.cache_dir)
    print("Declarable CDIF conformance classes (stage 1):")
    for u in uris:
        print(f"  {u}")

    domain = None
    if args.domain_bb_dir:
        domain = detect_domain_conformance(
            doc, uris, bb_dir=args.domain_bb_dir,
            manage_prefix=args.manage_prefix, do_shacl=not args.no_shacl,
            verbose=args.verbose, ref=args.bb_ref, cache_dir=args.cache_dir)
        print("\nDeclarable domain profiles (stage 2):")
        for u in domain.declared:
            print(f"  {u}")
        if domain.withheld:
            print("\nWITHHELD (presence held but not declared):")
            for w in domain.withheld:
                print(f"  {w['uri']}  -- {w['reason']}: {w['detail']}")
        if domain.ties:
            print("\nTIES (ambiguous; no single most-specific profile):")
            for t in domain.ties:
                print(f"  group {t['group']} @ priority {t['priority']}: "
                      f"{', '.join(t['candidates'])}")

    if args.apply:
        apply_conformance(doc, uris)
        if domain is not None:
            apply_conformance(doc, domain.declared,
                              manage_prefix=args.manage_prefix, append=True)
        out = args.output or args.input
        json.dump(doc, open(out, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
        open(out, "a", encoding="utf-8").write("\n")
        print(f"\nWrote {out}")

    # Exit non-zero when stage 2 withheld a class whose presence held (a real
    # failure); ties fail only under --strict-ties.
    if domain is not None and (domain.withheld or (args.strict_ties and domain.ties)):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
