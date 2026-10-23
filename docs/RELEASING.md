# Releasing e2er

A release is one command on `dev`, a merge to `main` and a tag. Everything else (the
tests, the wheel, the GitHub release, PyPI, the release facts and the Zenodo DOI) is done by
`.github/workflows/release.yml`.

## 1. The version edits: `scripts/release.py`

On a clean `dev` with the release's entries under `## [Unreleased]` in CHANGELOG.md:

```bash
python scripts/release.py 0.18.0 --dry-run   # what would change
python scripts/release.py 0.18.0 --commit    # edit every place and commit "Release 0.18.0"
```

(`make release VERSION=0.18.0` runs the second line.) The date is today's unless `--date
YYYY-MM-DD` gives another. The script edits every place in the repository that names the current
version:

| File | What changes |
| --- | --- |
| `pyproject.toml` | `[project].version` |
| `src/__init__.py` | `__version__` |
| `CITATION.cff` | `version`, `date-released`, `preferred-citation.version`, `preferred-citation.year` |
| `README.md` | the BibTeX entry's `version` and `year` (section "Citing") |
| `CHANGELOG.md` | `## [Unreleased]` becomes `## [0.18.0] — YYYY-MM-DD` under a new, empty `## [Unreleased]`; the link references at the end (`[Unreleased]: …compare/v0.18.0...HEAD`, `[0.18.0]: …/releases/tag/v0.18.0`) |

It refuses, and writes nothing, when the tree has uncommitted changes, the version is not
`X.Y.Z` or not greater than the current one, the Unreleased section is empty, or a place is not
where the script expects it (a renamed BibTeX key, a moved `version` line).

Every other version in the repository is history and stays: "up to 0.17.3" in the CHANGELOG and in
code comments, the `e2er_version` a study recorded (`examples/showcase/`), the schema examples in
`docs/STRUCTURED_EXPORT_SPEC.md`, the comments in the workflows. A document that names a coming
version ("comes in 0.17.4") is printed as a warning when another version is released, so it can be
corrected in the same commit.

`python scripts/release.py --check` says whether every place names the same version;
`--check --tag v0.18.0` also whether it is the tag's. The release workflow's first job runs the
latter, and `tests/test_release_script.py` runs the former on every push.

## 2. Merge and tag

```bash
git checkout main && git merge --ff-only dev   # or the release PR dev → main
git tag v0.18.0 && git push origin main v0.18.0
```

The tag starts the release workflow: version check (`scripts/release.py --check --tag`), tests,
build, GitHub release (notes from the CHANGELOG section), PyPI (trusted publishing), and the release
facts below. Do not create the GitHub release by hand; a run that failed after the release was
created is re-run with `gh run rerun <id>` (every job is idempotent).

## 3. The release facts: `release-facts.json`

The workflow attaches `release-facts.json` to every GitHub release. e2er.org reads it at runtime,
so the format is fixed: these keys, in this order, and nothing else.

```json
{
  "version": "0.18.0",
  "date": "2026-10-23",
  "tag_url": "https://github.com/bhanneke/E2ER-project/releases/tag/v0.18.0",
  "concept_doi": "10.5281/zenodo.20187238",
  "doi": "10.5281/zenodo.23600000",
  "counts": {
    "templates": 11,
    "specialists": 39,
    "skills": 90,
    "data_sources": 17,
    "tests": 4314
  }
}
```

| Key | Where it comes from |
| --- | --- |
| `version` | `pyproject.toml` |
| `date` | `CITATION.cff` `date-released` (set by `scripts/release.py`) |
| `tag_url` | `https://github.com/bhanneke/E2ER-project/releases/tag/v<version>` |
| `concept_doi` | always `10.5281/zenodo.20187238`; resolves to the latest version |
| `doi` | the Zenodo DOI of this version, or `null` until Zenodo has minted it (readers then use `concept_doi`) |
| `counts.templates` | the files `pipelines/*.toml` |
| `counts.specialists` | the specialists of `src/core/specialists/registry.py` (as `docs/SPECIALISTS.md` counts them) |
| `counts.skills` | the files `skills/files/**/*.md` |
| `counts.data_sources` | the connectors of `src/core/specialists/data_sources.py` (the connector kit's sources and Allium) |
| `counts.tests` | the tests the release workflow runs: `pytest tests/ -m "not e2e" --collect-only` |

`scripts/release_facts.py` computes every value from the code; no count is written by hand
(`tests/test_release_facts.py` checks the format and each count against its source). To see the
file for the current checkout:

```bash
python scripts/release_facts.py --out release-facts.json
```

The URL of the file of a release is
`https://github.com/bhanneke/E2ER-project/releases/download/v<version>/release-facts.json`, and of
the latest release `https://github.com/bhanneke/E2ER-project/releases/latest/download/release-facts.json`.

### The Zenodo version DOI

Zenodo's GitHub integration archives each GitHub release and mints its version DOI on its own,
usually within a minute (0.17.3: five seconds), sometimes not at all (0.16.1 has no Zenodo
version). The workflow's `zenodo-doi` job therefore runs after the release is created and asks
Zenodo's public records API (no token) every 30 seconds for up to 30 minutes for the version of the
concept record 20187238 that is named like the tag (`v0.18.0`):

```bash
python scripts/release_facts.py zenodo-doi release-facts.json --wait 1800
```

When it finds the DOI it writes it into `doi` and uploads the file to the release again
(`gh release upload --clobber`); when not, `doi` stays `null` and the job still succeeds. A DOI
minted later can be added by re-running that job.

## 4. The release's tests in four parts

The suite took up to 30 minutes in one job on a hosted runner (25 minutes cancelled 0.17.2's
release). The release workflow now runs it as four parallel jobs, each with a 30-minute limit:
`E2ER_TEST_PART=k/4` makes `tests/conftest.py` keep part k of whole test files
(`tests/parts.py`), balanced by the seconds each file took last time
(`tests/test_durations.json`). Every collected test is in exactly one part whatever the file
says (a new file weighs its number of tests times the average), so stale durations only make the
parts uneven. Without the variable every test runs, as before (and as `tests.yml` runs them).

After adding slow tests, refresh the durations:

```bash
pytest tests/ -m "not e2e" --junitxml=/tmp/junit.xml
python -m tests.parts /tmp/junit.xml   # rewrites tests/test_durations.json
```

## 5. The workflows' supply chain: pinned actions, hashed installs, least permissions

Every workflow in `.github/workflows/` (CI and release alike):

- declares `permissions: contents: read` at the top; a job that writes says so itself
  (`release` and `zenodo-doi`: `contents: write`; `publish`: `id-token: write` for PyPI's OIDC;
  `schema-drift`: `issues: write`);
- names every action by a full commit SHA, with its version in a comment
  (`actions/checkout@11d5960a… # v4.4.0`), and checks out with `persist-credentials: false`;
- installs from hash-pinned files: `.github/requirements/ci.txt` (the `dev` extra plus the
  build tools, every package with its hashes, for Python 3.11–3.14 on every platform) with
  `pip install --require-hashes`, then e2er itself with `pip install --no-deps --no-build-isolation -e .`;
  the build jobs install `.github/requirements/build.txt` and run `python -m build --no-isolation`.
  The release workflow keeps no pip cache.

`tests/test_workflow_supply_chain.py` fails when one of these slips.

Refresh the hashed files after changing a dependency in `pyproject.toml` (or to take newer
versions), and commit them with the change:

```bash
uv pip compile pyproject.toml .github/requirements/build.in --extra dev --generate-hashes \
    --universal --python-version 3.11 -o .github/requirements/ci.txt
uv pip compile .github/requirements/build.in --generate-hashes \
    --universal --python-version 3.11 -o .github/requirements/build.txt
```

To move an action to a newer version, resolve the tag to its commit (dereference an annotated tag)
and replace both the SHA and the comment:

```bash
gh api repos/actions/checkout/git/ref/tags/v4.4.0 --jq '.object.type + " " + .object.sha'
gh api repos/<owner>/<repo>/git/tags/<sha-of-the-tag-object> --jq .object.sha   # when the type is "tag"
```
