#!/usr/bin/env python3
"""Do the w3id conformance URIs still resolve to the version they name?

The redirect rules for a *current* version point at GitHub Pages, which serves
each release repo's `main` branch -- and main is always the newest release. That
is correct only while the version in the URI is the newest one. When a newer
minor version merges to main, an un-repointed rule serves the wrong spec and
nothing reports an error: there is no build to fail, and a schema for 1.2 is a
perfectly valid schema. The URI just quietly stops meaning what it says.

This is the check that makes that loud. Each profile's StructuredSchema embeds
its own conformance URI once, as the `contains` const on dcterms:conformsTo, so
the artifact states which version it is. Fetch each URI and confirm the artifact
that comes back agrees.

    python tools/check_w3id_redirects.py            # report
    python tools/check_w3id_redirects.py --strict   # exit 1 on any mismatch

See w3id.org/cdif/CLAUDE.md for the release checklist this guards.
"""
import argparse
import json
import sys
import urllib.error
import urllib.request

BASE = "https://w3id.org/cdif"

# (component, version) -- the URI, and therefore what its artifact must claim.
PROFILES = [
    ("core", "1.1"),
    ("discovery", "1.1"),
    ("data_description", "1.1"),
    ("data_structure", "1.1"),
    ("manifest", "1.1"),
    ("conceptscheme", "1.1"),
    ("codelist", "1.1"),
    # provenance/1.1 is deliberately absent: profile-provenance is still in
    # review, has no v1.1.0 tag, and its Pages source is its review branch. Add
    # it here when it is released.
]

TIMEOUT = 30


def fetch(url):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.status, r.headers.get("Content-Type", ""), r.read().decode("utf-8", "replace")


def check(component, version):
    """Return (ok, detail). ok is None when the check could not run."""
    uri = f"{BASE}/{component}/{version}/schema"
    want = f"w3id.org/cdif/{component}/{version}"
    try:
        status, ctype, body = fetch(uri)
    except (urllib.error.URLError, OSError) as e:
        return None, f"unreachable: {e}"
    if status != 200:
        return False, f"HTTP {status}"
    try:
        json.loads(body)
    except ValueError as e:
        return False, f"not JSON ({ctype}): {str(e)[:60]}"

    if want in body:
        return True, f"declares {component}/{version}"

    # Wrong version, or none at all -- say which, because "serving the next
    # version" and "serving something unrelated" need different fixes.
    import re
    found = sorted(set(re.findall(
        r"w3id\.org/cdif/%s/(\d+\.\d+)" % re.escape(component), body)))
    if found:
        return False, f"SERVES {component}/{', '.join(found)} -- expected {version}"
    return False, f"artifact declares no {component} conformance URI"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 if any URI resolves to the wrong version")
    args = ap.parse_args()

    print(f"{'conformance URI':<46} {'result':<8} detail")
    print("-" * 96)
    bad, skipped = [], []
    for component, version in PROFILES:
        ok, detail = check(component, version)
        label = f"{BASE}/{component}/{version}/schema".replace("https://", "")
        mark = "OK" if ok else ("SKIP" if ok is None else "WRONG")
        print(f"{label:<46} {mark:<8} {detail}")
        if ok is False:
            bad.append((component, version, detail))
        elif ok is None:
            skipped.append(component)

    print()
    if bad:
        print(f"::error::{len(bad)} conformance URI(s) resolve to the wrong version.")
        for component, version, detail in bad:
            print(f"    {component}/{version}: {detail}")
        print()
        print("A version's rules must be repointed from GitHub Pages to that")
        print("version's release tag when a newer minor version ships. See")
        print("w3id.org/cdif/CLAUDE.md, 'Cutting a new minor version'.")
    else:
        print(f"All {len(PROFILES) - len(skipped)} checked conformance URIs "
              f"resolve to the version they name.")
    if skipped:
        print(f"Not checked (unreachable): {', '.join(skipped)}")

    return 1 if (bad and args.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
