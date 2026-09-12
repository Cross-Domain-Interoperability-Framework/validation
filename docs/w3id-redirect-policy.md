# w3id.org/cdif redirects — versioning policy and maintenance

The redirect rules for `https://w3id.org/cdif/*` live in
[`perma-id/w3id.org`](https://github.com/perma-id/w3id.org) under `ids/cdif/`, and reach
production by pull request on that project's schedule. That repository hosts `.htaccess` and a
short README only, so the policy behind the rules, the release checklist and the traps are kept
here, next to the tool that checks them —
[`tools/check_w3id_redirects.py`](../tools/check_w3id_redirects.py).

## The one thing that must not go wrong

**A versioned conformance URI must keep resolving to the version it names.** A record declaring
`dcterms:conformsTo: https://w3id.org/cdif/core/1.1` has to stay checkable against 1.1
indefinitely.

The rules for a *current* version point at GitHub Pages, which serves each release repo's `main`
branch — and `main` is always the newest release. That is correct only while the version in the
URI *is* the newest one. The moment a newer minor version merges to `main`, an un-repointed rule
serves the wrong spec, and **nothing anywhere reports an error**: there is no build to fail, and a
1.2 schema is a perfectly valid schema. This is a silent-failure design, which is why it is
guarded from outside rather than trusted.

## How a version is served

Each profile lives in its own release repo (`profile-core`, `doc-corediscovery`, …). GitHub Pages
serves that repo's `main` branch, work happens on an `updates` branch, and `main` advances by pull
request when a release is cut — so **the merge is the release**. Each release is also tagged
(`v1.1.0`, `v1.1.1`, …).

| target | serves | content type | use for |
|---|---|---|---|
| Pages (`…github.io/profile-core/…`) | whatever is on `main` = the current release | `application/json` | the **current** version |
| tag (`raw.githubusercontent.com/…/v1.1.1/…`) | that exact release, immutably | `text/plain` | **superseded** versions |

Pages gives correct content types but always serves the newest release, so it can only back the
version that is currently newest. Tags are immutable, but `raw.githubusercontent.com` serves
everything as `text/plain`. That was measured (2026-09-10) against the consumers CDIF actually
has and is harmless: the JSON Schema and SHACL loaders name the format rather than sniffing the
header, and CDIF records carry an inline `@context` rather than fetching one.

**Do not "fix" a superseded version's rules back to a Pages URL.** It looks like an
inconsistency and is load-bearing — changing it silently starts serving the wrong version.

## Cutting a new minor version — checklist

Both steps, in one change:

1. **Repoint the outgoing version to its tag.** Every rule for the superseded version moves from
   `%{ENV:PROFILE_*}/<file>` to
   `https://raw.githubusercontent.com/Cross-Domain-Interoperability-Framework/<repo>/<tag>/<file>`,
   where `<tag>` is that version's **last patch release** (`v1.1.3`, not `v1.1.0` — picking the
   first archives a spec nobody shipped).
2. **Add the incoming version's rules** pointing at `%{ENV:PROFILE_*}`, and bump the unversioned
   aliases at the bottom of the file to the new version.

A **patch** release needs no `.htaccess` edit at all: every release-repo rule targets a Pages base
and Pages serves `main`, so the URL keeps meaning "current release" on its own.

Then verify — do not assume:

```bash
# a superseded version must announce its own version, not the current one
curl -sL https://w3id.org/cdif/core/1.1/schema | head -c 400

# the unversioned alias should land on the CURRENT version
curl -sIL https://w3id.org/cdif/core/schema | grep -i '^location:'

# or check every conformance URI at once, from a CDIF/validation clone
python tools/check_w3id_redirects.py --strict
```

Add the new version to that script's `PROFILES` list in the same change, or the incoming version
is the one thing nothing is watching.

## Traps

- **Sub-path rules must precede bare conformance-URI rules**, so `{component}/{version}/{resource}`
  matches before `{component}/{version}`. Keep new rules on the correct side of that boundary.
- **Unversioned aliases are 302, versioned URIs are 303.** The alias target is expected to move; a
  versioned URI's is not. Do not normalise them to match.
- **An unversioned URI must never appear in a `dcterms:conformsTo`.** A record declares the version
  it was written against. The aliases exist for humans and for docs tracking the current spec.
- **Upstream moved every rule directory under `ids/` on 2026-09-04.** A pull request must target
  `ids/cdif/`; a fork that has not synced still shows the old top-level `cdif/`, and a PR against
  that path re-creates a directory upstream deleted while leaving the live rules untouched.
- **`profile-provenance` is not yet released.** It has no `v1.1.0` tag, still uses its review
  branch, and its Pages source is that branch — so its rules behave differently from the other
  eight profiles. Check its state before assuming the pattern holds.

## The guard

[`tools/check_w3id_redirects.py`](../tools/check_w3id_redirects.py) fetches each versioned
conformance URI and fails if the artifact that comes back does not declare the version the URI
names. It runs weekly
([`check-w3id-redirects.yml`](../.github/workflows/check-w3id-redirects.yml)). It is a backstop on
a weekly cadence, not a gate — a mistake is live until the next run — so the checklist above is
still what has to be right.
