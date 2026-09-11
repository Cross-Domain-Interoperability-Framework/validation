#!/usr/bin/env python3
"""Build converters/DCAT/dcat_profile_coverage.xlsx: which DCAT profile in
dcatExamplesOK uses each dcat-to-cdif SSSOM subject_id, plus a profile summary
and the corpus-only ('wild') predicates. Regenerated from the live table+corpus.
"""
import csv, glob, os, logging, warnings, collections, datetime, rdflib
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
logging.getLogger("rdflib").setLevel(logging.CRITICAL); warnings.filterwarnings("ignore")

HERE = Path(__file__).resolve().parent            # converters/DCAT
MAP = str(HERE.parent / "mappings")
CORPUS = str(HERE / "dcatExamplesOK")
OUT = str(HERE / "dcat_profile_coverage.xlsx")
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
PROFILES = [("01-dcat-ap","DCAT-AP"),("02-geodcat-ap","GeoDCAT-AP"),
    ("03-mobilitydcat-ap-1.1.0","MobilityDCAT-AP"),("04-healthdcat-ap","HealthDCAT-AP"),
    ("05-mldcat-ap-3.1.0","MLDCAT-AP"),("07-national-profiles","National"),
    ("10-dcat-us-3.0","DCAT-US-3.0"),("11-dcat-us-1.1-pod","DCAT-US-1.1-POD")]
FMT = {".ttl":"turtle",".rdf":"xml",".xml":"xml",".jsonld":"json-ld",".json":"json-ld"}
LABELS = [l for _, l in PROFILES]


def curie_map(y):
    ns, b = {}, False
    for ln in open(y, encoding="utf-8"):
        if ln.startswith("curie_map:"):
            b = True; continue
        if b:
            if ln.startswith("  ") and ":" in ln:
                k, v = ln.strip().split(":", 1); ns[k.strip()] = v.strip().strip('"')
            else:
                break
    return ns

def expand(c, ns):
    if ":" not in c:
        return c
    p, l = c.split(":", 1)
    return ns.get(p, p + ":") + l

dn = curie_map(os.path.join(MAP, "dcat-to-cdif.sssom.yml"))
an = curie_map(os.path.join(MAP, "dcat-aliases.sssom.yml"))
rows = list(csv.DictReader(open(os.path.join(MAP, "dcat-to-cdif.sssom.tsv"), encoding="utf-8"), delimiter="\t"))
iri2canon = {}
for r in rows:
    iri2canon[expand(r["subject_id"], dn)] = r["subject_id"]
for a in csv.DictReader(open(os.path.join(MAP, "dcat-aliases.sssom.tsv"), encoding="utf-8"), delimiter="\t"):
    iri2canon[expand(a["subject_id"], an)] = a["object_id"]

DISPLAY = dict(dn, **{"rdf":"http://www.w3.org/1999/02/22-rdf-syntax-ns#",
 "owl":"http://www.w3.org/2002/07/owl#","time":"http://www.w3.org/2006/time#",
 "dc":"http://purl.org/dc/elements/1.1/","csvw":"http://www.w3.org/ns/csvw#",
 "oa":"http://www.w3.org/ns/oa#","dpv":"https://w3id.org/dpv#",
 "odrs":"http://schema.theodi.org/odrs#","mdcat":"https://w3id.org/mobilitydcat-ap#",
 "healthdcat":"http://healthdataportal.eu/ns/health#","eli":"http://data.europa.eu/eli/ontology#"})
def cur(iri):
    best = None
    for p, base in DISPLAY.items():
        if iri.startswith(base) and (best is None or len(base) > len(DISPLAY[best])):
            best = p
    return f"{best}:{iri[len(best):]}" if best else iri

prof_canon = {l: set() for l in LABELS}
prof_files = collections.Counter()
prof_preds = {l: set() for l in LABELS}
wild = collections.defaultdict(set)
for d, label in PROFILES:
    for f in glob.glob(os.path.join(CORPUS, d, "**", "*"), recursive=True):
        if not (os.path.isfile(f) and os.path.splitext(f)[1].lower() in FMT):
            continue
        try:
            g = rdflib.Graph(); g.parse(f, format=FMT[os.path.splitext(f)[1].lower()])
        except Exception:
            continue
        prof_files[label] += 1
        for p in set(g.predicates()):
            s = str(p)
            if s == RDF_TYPE:
                continue
            prof_preds[label].add(s)
            if s in iri2canon:
                prof_canon[label].add(iri2canon[s])
            else:
                wild[s].add(label)

# ---- workbook ----
ARIAL = "Arial"
hfont = Font(name=ARIAL, bold=True, color="FFFFFF")
hfill = PatternFill("solid", fgColor="305496")
cfont = Font(name=ARIAL)
center = Alignment(horizontal="center")
usedfill = PatternFill("solid", fgColor="E2EFDA")
thin = Side(style="thin", color="D9D9D9")
border = Border(left=thin, right=thin, top=thin, bottom=thin)
wb = Workbook()

# Sheet 1: Field x Profile
ws = wb.active; ws.title = "Field x Profile"
hdr = ["subject_id", "subject_class", "mapped"] + LABELS + ["n_profiles"]
ws.append(hdr)
CK = "\u2713"
marked = {l: 0 for l in LABELS}    # rows marked per profile
n_mapped = 0
for r in rows:
    canon = r["subject_id"]
    marks = [CK if canon in prof_canon[l] else "" for l in LABELS]
    for l, m in zip(LABELS, marks):
        if m:
            marked[l] += 1
    mp = CK if r.get("object_json_path", "").strip() else ""
    if mp:
        n_mapped += 1
    ws.append([r["subject_id"], r.get("subject_class", ""), mp, *marks,
               sum(1 for m in marks if m)])       # n_profiles as a value
ncol = len(hdr)
first_prof = 4                     # column D
last_prof = 3 + len(LABELS)        # column K
# totals row (computed values; re-run the generator to refresh)
tot = len(rows) + 2
ws.cell(tot, 1).value = "TOTAL (rows using)"
ws.cell(tot, 3).value = n_mapped
for idx, l in enumerate(LABELS):
    ws.cell(tot, first_prof + idx).value = marked[l]
# style
for c in range(1, ncol + 1):
    ws.cell(1, c).font = hfont; ws.cell(1, c).fill = hfill; ws.cell(1, c).alignment = center
for i in range(2, len(rows) + 2):
    for c in range(1, ncol + 1):
        cell = ws.cell(i, c); cell.font = cfont; cell.border = border
        if c >= first_prof:
            cell.alignment = center
            if cell.value == "\u2713":
                cell.fill = usedfill
        if c == 3 and cell.value == "\u2713":
            cell.alignment = center
for c in range(1, ncol + 1):
    ws.cell(tot, c).font = Font(name=ARIAL, bold=True); ws.cell(tot, c).alignment = center if c >= 3 else Alignment()
ws.column_dimensions["A"].width = 42
ws.column_dimensions["B"].width = 26
ws.column_dimensions["C"].width = 8
for c in range(first_prof, last_prof + 1):
    ws.column_dimensions[get_column_letter(c)].width = 15
ws.column_dimensions[get_column_letter(ncol)].width = 11
ws.freeze_panes = "D2"
ws.auto_filter.ref = f"A1:{get_column_letter(ncol)}1"

# Sheet 2: Profile summary
ws2 = wb.create_sheet("Profile summary")
ws2.append(["Profile", "Corpus files", "Distinct predicates", "SSSOM rows marked", "Wild (not in SSSOM)"])
for l in LABELS:
    n_wild = sum(1 for iri, profs in wild.items() if l in profs)
    ws2.append([l, prof_files[l], len(prof_preds[l]), marked[l], n_wild])
for c in range(1, 6):
    ws2.cell(1, c).font = hfont; ws2.cell(1, c).fill = hfill; ws2.cell(1, c).alignment = center
for i in range(2, len(LABELS) + 2):
    for c in range(1, 6):
        ws2.cell(i, c).font = cfont; ws2.cell(i, c).border = border
        if c >= 2:
            ws2.cell(i, c).alignment = center
ws2.column_dimensions["A"].width = 20
for c in "BCDE":
    ws2.column_dimensions[c].width = 20
ws2.freeze_panes = "A2"

# Sheet 3: Wild predicates
ws3 = wb.create_sheet("Wild predicates")
whdr = ["predicate", "IRI"] + LABELS + ["n_profiles"]
ws3.append(whdr)
wl = sorted(wild.items(), key=lambda kv: (-len(kv[1]), cur(kv[0]).lower()))
for iri, profs in wl:
    marks = [CK if l in profs else "" for l in LABELS]
    ws3.append([cur(iri), iri, *marks, len(profs)])
wn = len(whdr)
for c in range(1, wn + 1):
    ws3.cell(1, c).font = hfont; ws3.cell(1, c).fill = hfill; ws3.cell(1, c).alignment = center
wf, wlp = 3, 2 + len(LABELS)
for i in range(2, len(wl) + 2):
    for c in range(1, wn + 1):
        ws3.cell(i, c).font = cfont; ws3.cell(i, c).border = border
        if c >= wf:
            ws3.cell(i, c).alignment = center
            if ws3.cell(i, c).value == "\u2713":
                ws3.cell(i, c).fill = usedfill
ws3.column_dimensions["A"].width = 34
ws3.column_dimensions["B"].width = 60
for c in range(wf, wlp + 1):
    ws3.column_dimensions[get_column_letter(c)].width = 15
ws3.column_dimensions[get_column_letter(wn)].width = 11
ws3.freeze_panes = "C2"
ws3.auto_filter.ref = f"A1:{get_column_letter(wn)}1"

# Sheet 4: About
ws4 = wb.create_sheet("About")
about = [
 ("DCAT profile coverage of the dcat-to-cdif SSSOM crosswalk", True),
 ("", False),
 (f"Generated: {datetime.date.today().isoformat()}", False),
 ("Source table: converters/mappings/dcat-to-cdif.sssom.tsv (+ dcat-aliases.sssom.tsv)", False),
 ("Corpus: converters/DCAT/dcatExamplesOK/ (8 DCAT profile families)", False),
 ("Regenerate: scripts/make_coverage_xlsx.py (or the committed generator)", False),
 ("", False),
 ("Method", True),
 ("Every record in each profile directory is parsed with rdflib (ttl/rdf/xml/jsonld,", False),
 ("and POD .json as json-ld); the set of predicate IRIs used is collected and", False),
 ("normalized through the SSSOM curie_map + dcat-aliases back to a canonical", False),
 ("subject_id. A check mark means that profile's corpus records use the property.", False),
 ("Presence is class-agnostic: subject_class is shown for reference but a mark", False),
 ("reflects the predicate appearing anywhere in the profile. rdf:type is excluded.", False),
 ("", False),
 ("Sheets", True),
 ("Field x Profile  - each SSSOM subject_id x the 8 profiles; 'mapped' = has a CDIF", False),
 ("                   target (non-empty object_json_path); n_profiles = COUNTIF of marks.", False),
 ("Profile summary  - per profile: corpus files, distinct predicates, how many are in", False),
 ("                   the SSSOM (formula over the matrix), and how many are 'wild'.", False),
 ("Wild predicates  - predicates used in the corpus that are NOT in the SSSOM/aliases", False),
 ("                   (coverage gaps); excludes rdf:type.", False),
]
for i, (text, bold) in enumerate(about, 1):
    c = ws4.cell(i, 1); c.value = text
    c.font = Font(name=ARIAL, bold=bold, size=13 if (bold and i == 1) else 11)
ws4.column_dimensions["A"].width = 95

wb.save(OUT)
print("wrote", OUT)
print(f"  Field x Profile: {len(rows)} rows x {len(LABELS)} profiles")
print(f"  Wild predicates: {len(wl)}")
print("  per-profile files:", dict(prof_files))
