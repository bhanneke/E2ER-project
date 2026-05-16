# Release Audit

Wraps `scripts/release_audit.py` and presents the gate results in a
human-readable form. Use this before tagging a release from `main`.

`$ARGUMENTS` is currently unused — reserved for future per-gate flags.

## Process

### Step 1: Run the audit

```bash
make release-audit
```

This invokes `python3 scripts/release_audit.py`. The script reports
hard gates (must pass) and soft gates (warnings).

Hard gates:
- version match between `pyproject.toml` and `src/__init__.py`
- clean working tree
- CHANGELOG has entries under `## Unreleased` (or `## [Unreleased]`)
- no `TODO(release)` markers in src
- pytest passes

Soft gates (don't block, but flag):
- current branch is `main` (sometimes audited from `dev` pre-merge)
- latest CI run on the branch is green

### Step 2: If hard gate failed, walk the user through the fix

For each failure, propose the smallest fix:

- **version mismatch** → tell them which file is stale and bump it
- **dirty tree** → list the offending files; suggest stash or commit
- **empty CHANGELOG** → suggest the per-lane sub-headings to fill in
- **tests failing** → run `make smoke` and surface the first failure
- **TODO(release) markers** → list the files and lines

### Step 3: If only soft gates flagged, summarize and ask

Soft warnings don't block release but the user should know:

- Off-main? "Are you intentionally auditing from `dev` before the
  release PR merges?"
- CI yellow/red? "Latest CI is <conclusion> — fix or override?"

### Step 4: If all gates green, suggest the tag command

```bash
# Get the version
VERSION=$(grep '^version' pyproject.toml | head -1 | sed 's/.*"\(.*\)".*/\1/')
echo "Tag command: git tag v$VERSION && git push origin v$VERSION"
```

Don't run the tag command yourself — releases are explicit user actions.
