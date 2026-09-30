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

It then asks the same question of the CDIF book, which pins its links to
release tags rather than to main. A stale pin there does not 404 -- it serves a
correct-looking page describing an older release -- so it needs the same kind of
guard for the same reason.

Third, it checks the XAS identifier space (w3id.org/cdif/xas/*), which nothing
checked until 2026-09-29. That space was repointed from a personal account to
the CDIF-4-XAS organisation, and a wrong base there would have left this
workflow green -- not a rule that stopped working, but a space no rule
covered.

    python tools/check_w3id_redirects.py            # report
    python tools/check_w3id_redirects.py --strict   # exit 1 on any mismatch

See w3id.org/ids/cdif/CLAUDE.md for the release checklist this guards.
"""
import argparse
import json
import os
import re
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


# ---------------------------------------------------------------------------
# Second check: does the CDIF book still pin the newest release tag?
#
# The book links release artifacts by tag, not by branch, so a reader always
# gets the spec the prose was written against. That is the right policy, and it
# is exactly why it needs a guard: a tag pin does not rot into a 404, it rots
# into a page that looks entirely correct while describing a superseded release.
# Nothing in the book's own build can notice, because every link it contains
# still resolves. Same failure shape as an un-repointed w3id rule, which is why
# the two checks live together.
#
# Every tracked file is scanned rather than a known list of pages, so a link
# added to a new chapter is covered the day it lands.
# ---------------------------------------------------------------------------

ORG = "Cross-Domain-Interoperability-Framework"
BOOK_TARBALL = f"https://github.com/{ORG}/cdifbook/archive/refs/heads/main.tar.gz"

# Generated output, rebuilt from the sources; a stale tag here is not a finding.
BOOK_SKIP_DIRS = ("_build/", "_book/", "_site/")

# Members larger than this are assets, not prose. Keeps the scan from decoding
# megabytes of PNG to find nothing.
BOOK_MAX_BYTES = 2_000_000

TAG_REF = re.compile(
    r"github\.com/" + ORG + r"/([A-Za-z0-9._-]+)/(?:blob|tree|raw)/(v\d+\.\d+\.\d+)")


def _semver(tag):
    return tuple(int(part) for part in tag.lstrip("v").split("."))


def book_tag_refs():
    """{repo: {tag: count}} over every release-tag link in the book sources."""
    import io
    import tarfile

    with urllib.request.urlopen(BOOK_TARBALL, timeout=TIMEOUT) as r:
        archive = r.read()

    refs = {}
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tf:
        for member in tf.getmembers():
            if not member.isfile() or member.size > BOOK_MAX_BYTES:
                continue
            # Drop the "cdifbook-main/" wrapper the archive adds.
            path = member.name.split("/", 1)[-1]
            if path.startswith(BOOK_SKIP_DIRS):
                continue
            handle = tf.extractfile(member)
            if handle is None:
                continue
            text = handle.read().decode("utf-8", "ignore")
            for repo, tag in TAG_REF.findall(text):
                refs.setdefault(repo, {})
                refs[repo][tag] = refs[repo].get(tag, 0) + 1
    return refs


def newest_tag(repo):
    """Highest vX.Y.Z tag in a release repo, or None if it has none.

    Sorted by parsed semver rather than trusting the API's order, which is not
    documented to be version order -- v1.1.10 must beat v1.1.9.
    """
    url = f"https://api.github.com/repos/{ORG}/{repo}/tags?per_page=100"
    headers = {"Accept": "application/vnd.github+json"}
    # Unauthenticated API calls from a shared runner IP hit the 60/hour limit;
    # the workflow passes the job's own token, which needs no extra permission
    # to read public tags.
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(
            urllib.request.Request(url, headers=headers), timeout=TIMEOUT) as r:
        tags = json.load(r)
    versions = [t["name"] for t in tags
                if re.fullmatch(r"v\d+\.\d+\.\d+", t["name"])]
    return max(versions, key=_semver) if versions else None


def check_book():
    """Report the book's tag pins. Returns the list of (repo, detail) problems."""
    print("=== cdifbook release-tag pins ===")
    try:
        refs = book_tag_refs()
    except (urllib.error.URLError, OSError) as e:
        print(f"  SKIP  could not fetch the book sources: {e}")
        print()
        return []

    if not refs:
        # Zero findings from zero matches is the failure this repo keeps
        # relearning, so say so instead of printing a clean bill of health.
        print("  NOTE  no release-tag links found at all -- either the book stopped")
        print("        linking artifacts by tag, or the link style changed and this")
        print("        check is now matching nothing.")
        print()
        return []

    print(f"{'repo':<28} {'pinned':<20} {'newest':<10} result")
    print("-" * 96)
    bad = []
    for repo in sorted(refs):
        pins = refs[repo]
        pinned = ", ".join(sorted(pins, key=_semver))
        count = sum(pins.values())
        try:
            newest = newest_tag(repo)
        except (urllib.error.URLError, OSError) as e:
            print(f"{repo:<28} {pinned:<20} {'?':<10} SKIP  {e}")
            continue
        if newest is None:
            print(f"{repo:<28} {pinned:<20} {'-':<10} SKIP  no vX.Y.Z tags")
            continue

        if len(pins) > 1:
            result = f"MIXED {count} link(s) split across {len(pins)} tags"
            bad.append((repo, result))
        elif pinned != newest:
            result = f"STALE {count} link(s) still at {pinned}"
            bad.append((repo, result))
        else:
            result = f"OK    {count} link(s)"
        print(f"{repo:<28} {pinned:<20} {newest:<10} {result}")

    print()
    if bad:
        print(f"::error::{len(bad)} repo(s) linked from the CDIF book are pinned "
              f"to a superseded release tag.")
        for repo, result in bad:
            print(f"    {repo}: {result}")
        print()
        print("Repoint the book's links to the newest tag and push; Pages")
        print("redeploys on merge to main. The 2026-09-10 sweep is a worked")
        print("example -- cdifbook commit 'Repoint profile artifact links to")
        print("the v1.1.1 release tag'.")
    else:
        print(f"All {len(refs)} repo(s) linked from the book are pinned to the "
              f"newest release tag.")
    return bad


# ---------------------------------------------------------------------------
# Third check: do the XAS identifiers resolve through the organisation?
#
# w3id.org/cdif/xas/* is the XAS SKOS glossary and its three value-list
# vocabularies -- the largest identifier space CDIF publishes, and until
# 2026-09-29 the only one resolving through an individual's GitHub account
# rather than an organisation. It was repointed to CDIF-4-XAS then
# (perma-id/w3id.org#6767).
#
# Nothing checked it before. The two checks above cover the versioned
# conformance URIs and the book's tag pins, so a wrong XAS_PAGES base -- stale,
# or back on a personal fork -- would have left this workflow green. That is
# the same failure family as an un-repointed rule, one step further back: not a
# rule that stopped working, but a space no rule ever covered.
#
# What is asserted is deliberately narrow: the 303 lands on the expected base,
# and the target it names serves. The exact path per rule is NOT asserted --
# that would duplicate the rewrite table in ids/cdif/.htaccess and drift from
# it. The path is printed so a human reviewing a diff can see it move.
#
# Limit worth knowing: a concept URI under a value list resolves to a FRAGMENT
# of the whole-vocabulary document (`...#kalpha`), and HTTP cannot tell whether
# a fragment exists -- the file returns 200 either way. So these cases prove
# the document is reachable, not that the concept is in it.
# ---------------------------------------------------------------------------

XAS_EXPECTED_BASE = "https://cdif-4-xas.github.io/XAS-CDIF"

# The transition is over. perma-id/w3id.org#6767 merged 2026-09-29 23:18Z
# (93b9432b7) and the live redirects moved: all ten families resolve through the
# organisation. XAS_TRANSITIONAL_BASE, which accepted the old personal-account
# base and reported it as PENDING rather than failing, is gone -- while it
# existed this check could not tell "repointed" from "never repointed", which is
# the one question it is for. Any resolution outside XAS_EXPECTED_BASE is now a
# --strict failure.

# One per rule family in ids/cdif/.htaccess, not one per rule.
# (uri path, Accept header or None, what the rule family is for)
XAS_CASES = [
    ("xas/", None, "namespace root"),
    ("xas/facility", None, "concept, default Accept"),
    ("xas/facility", "application/ld+json", "concept, JSON-LD"),
    ("xas/facility/jsonld", None, "concept, explicit suffix"),
    ("xas/edge/", None, "value list, whole document"),
    ("xas/emissionline/", None, "value list, whole document"),
    ("xas/detectionmode/", None, "value list, whole document"),
    ("xas/edge/k", None, "value-list concept (fragment)"),
    ("xas/CDIF4XAS_Reference_Concepts", None, "ConceptScheme URI"),
    ("xas/XAS_AbsorptionEdges", None, "ConceptScheme URI"),
]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Stop at the 303 so its Location can be inspected, not followed."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _location(url, accept):
    """(status, Location) for *url* without following the redirect."""
    opener = urllib.request.build_opener(_NoRedirect)
    headers = {"Accept": accept} if accept else {}
    req = urllib.request.Request(url, headers=headers)
    try:
        with opener.open(req, timeout=TIMEOUT) as r:
            return r.status, r.headers.get("Location", "")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Location", "")


def _serves(url):
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, OSError):
        return None


def check_xas():
    print(f"{'XAS identifier':<46} {'result':<8} detail")
    print("-" * 96)
    bad = []
    for path, accept, what in XAS_CASES:
        uri = f"{BASE}/{path}"
        label = uri.replace("https://", "")
        if accept:
            label += "  (ld+json)"
        try:
            status, location = _location(uri, accept)
        except (urllib.error.URLError, OSError) as e:
            print(f"{label:<46} {'SKIP':<8} unreachable: {e}")
            continue

        if status not in (301, 302, 303, 307, 308) or not location:
            print(f"{label:<46} {'WRONG':<8} HTTP {status}, no redirect ({what})")
            bad.append((uri, f"HTTP {status}, no redirect"))
            continue

        target = location.split("#")[0]
        if not location.startswith(XAS_EXPECTED_BASE):
            print(f"{label:<46} {'WRONG':<8} -> {location}")
            bad.append((uri, f"resolves outside {XAS_EXPECTED_BASE}: {location}"))
            continue

        served = _serves(target)
        tail = location[len(XAS_EXPECTED_BASE):] or "/"
        if served != 200:
            print(f"{label:<46} {'WRONG':<8} 303 -> {tail} but that returns "
                  f"{served} ({what})")
            bad.append((uri, f"303 to {served}: {location}"))
            continue
        print(f"{label:<46} {'OK':<8} -> {tail}")

    print()
    if bad:
        print(f"::error::{len(bad)} XAS identifier(s) do not resolve as expected.")
        for uri, detail in bad:
            print(f"    {uri}: {detail}")
        print()
        print("XAS_PAGES in ids/cdif/.htaccess names the base these resolve")
        print("through; it must be the CDIF-4-XAS organisation's Pages site.")
        print("A 303 to a 404 is worse than leaving a redirect where it was --")
        print("confirm the new site serves before repointing it.")
    else:
        print(f"All {len(XAS_CASES)} XAS identifier families resolve through "
              f"{XAS_EXPECTED_BASE.replace('https://', '')} and serve.")
    return bad


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
        print("w3id.org/ids/cdif/CLAUDE.md, 'Cutting a new minor version'.")
    else:
        print(f"All {len(PROFILES) - len(skipped)} checked conformance URIs "
              f"resolve to the version they name.")
    if skipped:
        print(f"Not checked (unreachable): {', '.join(skipped)}")

    print()
    book_bad = check_book()

    print()
    xas_bad = check_xas()

    return 1 if ((bad or book_bad or xas_bad) and args.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
