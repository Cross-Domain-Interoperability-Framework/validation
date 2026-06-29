#!/usr/bin/env python3
"""sync_frameandvalidate.py -- propagate the normative FrameAndValidate.py.

The normative, editable source is tools/FrameAndValidate.py in the CDIF
validation repo (this directory). Every sibling CDIF profile / documentation
release repo carries a *generated copy* at its repo root, beside its single
schema + frame, so the script auto-detects them. This tool copies the normative
body into each release repo, stamping a "DO NOT EDIT" banner with a src-sha256,
and (on POSIX) marks the copy read-only.

Safety: before overwriting a repo's copy, the script runs that repo's
examples/*.json through BOTH the existing copy (baseline) and the normative
candidate, and refuses to overwrite if any example that passed under the
baseline would fail under the candidate (a regression). Use --force to override.

Usage:
    python tools/sync_frameandvalidate.py                 # dry-run + verify, report only
    python tools/sync_frameandvalidate.py --apply         # write copies where safe
    python tools/sync_frameandvalidate.py --apply --force  # write even on regression
    python tools/sync_frameandvalidate.py --list          # list discovered target repos
    python tools/sync_frameandvalidate.py --no-verify      # skip the example regression check

Drift hash: the src-sha256 is computed over the script body *after* the banner
block (line endings normalized to LF), so banner text / line-ending differences
never affect it. The release-repo CI check (templates/check-frameandvalidate.yml)
recomputes the same hash and fails on mismatch.
"""
import argparse
import hashlib
import os
import stat
import subprocess
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
NORMATIVE = TOOLS_DIR / "FrameAndValidate.py"
CDIF_ROOT = TOOLS_DIR.parent.parent          # tools -> validation -> CDIF
VALIDATION_DIR = TOOLS_DIR.parent

BANNER_OPEN = "# >>> CDIF-SYNC GENERATED >>>"
BANNER_CLOSE = "# <<< CDIF-SYNC GENERATED <<<"
END_MARKERS = ("# <<< CDIF-SYNC NORMATIVE <<<", "# <<< CDIF-SYNC GENERATED <<<")


def canonical_body(text):
    """Return the script body after any CDIF-SYNC banner block, LF-normalized.

    This is the content the src-sha256 is computed over and the content copied
    into release repos. Banner text (paths, hash) is excluded, so it never
    perturbs the hash."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    last = -1
    for i, ln in enumerate(lines):
        if ln.strip() in END_MARKERS:
            last = i
    body = lines[last + 1:] if last >= 0 else lines
    while body and body[0].strip() == "":
        body.pop(0)
    return "\n".join(body)


def body_hash(text):
    return hashlib.sha256(canonical_body(text).encode("utf-8")).hexdigest()


def generated_text(body, src_sha, newline="\r\n"):
    """Assemble a release-repo copy: shebang + GENERATED banner + body."""
    banner = [
        "#!/usr/bin/env python3",
        BANNER_OPEN,
        "# GENERATED FILE -- DO NOT EDIT.",
        "# Synced from CDIF/validation/tools/FrameAndValidate.py (the normative source).",
        "# Edit there, then run:  python tools/sync_frameandvalidate.py --apply",
        f"# src-sha256: {src_sha}",
        BANNER_CLOSE,
        "",
    ]
    return newline.join(banner) + newline + body.replace("\n", newline)


def discover_targets():
    """Sibling repos under CDIF_ROOT that carry a FrameAndValidate.py (excluding
    the validation source repo itself)."""
    targets = []
    for child in sorted(CDIF_ROOT.iterdir()):
        if not child.is_dir() or child == VALIDATION_DIR:
            continue
        if (child / "FrameAndValidate.py").exists():
            targets.append(child)
    return targets


def _run_validate(script, example):
    """Run `python <script> <example> -v` from the script's repo dir; return
    True iff it reports a successful validation."""
    try:
        p = subprocess.run(
            [sys.executable, str(script), str(example), "-v"],
            cwd=str(script.parent), capture_output=True, text=True, timeout=180)
    except Exception as e:
        return False, f"run error: {e}"
    ok = p.returncode == 0 and "Validation PASSED" in p.stdout
    return ok, ""


def verify_repo(repo, candidate_body, src_sha):
    """Run each example through the existing copy (baseline) and a temp candidate;
    return (regressions, n_examples). A regression = baseline PASS, candidate FAIL."""
    examples = sorted((repo / "examples").glob("*.json")) if (repo / "examples").is_dir() else []
    if not examples:
        return [], 0
    existing = repo / "FrameAndValidate.py"
    cand = repo / ".FrameAndValidate.candidate.py"
    cand.write_text(generated_text(candidate_body, src_sha), encoding="utf-8")
    regressions = []
    try:
        for ex in examples:
            base_ok, _ = _run_validate(existing, ex) if existing.exists() else (False, "")
            cand_ok, _ = _run_validate(cand, ex)
            if base_ok and not cand_ok:
                regressions.append(ex.name)
    finally:
        cand.unlink(missing_ok=True)
    return regressions, len(examples)


def deploy_ci(repo):
    """Place the drift-check GitHub Action into a release repo's workflows dir.
    Returns 'written' | 'present' | 'no-template'."""
    template = TOOLS_DIR / "templates" / "check-frameandvalidate.yml"
    if not template.exists():
        return "no-template"
    dest = repo / ".github" / "workflows" / "check-frameandvalidate.yml"
    new = template.read_text(encoding="utf-8")
    if dest.exists() and dest.read_text(encoding="utf-8") == new:
        return "present"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(new, encoding="utf-8")
    return "written"


def set_readonly(path):
    """Best-effort read-only flag (deterrent; git checkout will reset it)."""
    try:
        mode = os.stat(path).st_mode
        os.chmod(path, mode & ~stat.S_IWUSR & ~stat.S_IWGRP & ~stat.S_IWOTH)
    except Exception:
        pass


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write copies (default: dry-run)")
    ap.add_argument("--force", action="store_true", help="write even if examples regress")
    ap.add_argument("--no-verify", action="store_true", help="skip the example regression check")
    ap.add_argument("--with-ci", action="store_true",
                    help="also deploy the drift-check GitHub Action into each repo")
    ap.add_argument("--list", action="store_true", help="list discovered target repos and exit")
    ap.add_argument("--repos", nargs="*", help="limit to these repo dir names")
    args = ap.parse_args(argv)

    if not NORMATIVE.exists():
        print(f"Normative source not found: {NORMATIVE}", file=sys.stderr)
        return 2

    targets = discover_targets()
    if args.repos:
        want = set(args.repos)
        targets = [t for t in targets if t.name in want]

    if args.list:
        for t in targets:
            print(t.name)
        return 0

    src_text = NORMATIVE.read_text(encoding="utf-8")
    body = canonical_body(src_text)
    src_sha = body_hash(src_text)
    print(f"Normative: {NORMATIVE}")
    print(f"src-sha256: {src_sha}")
    print(f"Targets: {len(targets)}   mode: {'APPLY' if args.apply else 'dry-run'}"
          f"{'  (no-verify)' if args.no_verify else ''}\n")

    wrote = skipped = uptodate = 0
    for repo in targets:
        target = repo / "FrameAndValidate.py"
        cur_sha = body_hash(target.read_text(encoding="utf-8")) if target.exists() else None
        in_sync = cur_sha == src_sha

        regressions, n_ex = ([], 0)
        if not args.no_verify and not in_sync:
            regressions, n_ex = verify_repo(repo, body, src_sha)

        status = "in-sync" if in_sync else ("REGRESSION" if regressions else "stale")
        detail = ""
        if regressions:
            detail = f"  !! {len(regressions)} regress: {', '.join(regressions[:4])}" + \
                     (" ..." if len(regressions) > 4 else "")
        elif not in_sync and n_ex:
            detail = f"  ({n_ex} examples ok)"
        print(f"  {repo.name:42s} {status}{detail}")

        # CI workflow is a separate artifact -- (re)deploy it independently of
        # whether the script body itself needs rewriting.
        if args.apply and args.with_ci:
            if deploy_ci(repo) == "written":
                print(f"      + deployed/updated .github/workflows/check-frameandvalidate.yml")

        if in_sync:
            uptodate += 1
            continue
        if regressions and not args.force:
            skipped += 1
            continue
        if args.apply:
            nl = "\r\n"
            if target.exists():
                raw = target.read_bytes()
                nl = "\r\n" if b"\r\n" in raw else "\n"
            if target.exists():
                set_readonly_off(target)
            # write_bytes (not write_text) so we control newlines exactly --
            # write_text would translate \n -> os.linesep, doubling CR on Windows.
            target.write_bytes(generated_text(body, src_sha, newline=nl).encode("utf-8"))
            set_readonly(target)
            wrote += 1

    print(f"\n{'Wrote' if args.apply else 'Would write'}: {wrote}   "
          f"in-sync: {uptodate}   skipped (regression): {skipped}")
    if not args.apply and (wrote == 0 and skipped == 0):
        pass
    if not args.apply:
        print("Dry-run only. Re-run with --apply to write.")
    return 0


def set_readonly_off(path):
    try:
        mode = os.stat(path).st_mode
        os.chmod(path, mode | stat.S_IWUSR)
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main())
