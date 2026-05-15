# AGENTS.md — E2ER v3

Conventions every coding agent (Claude Code, Codex, Gemini CLI) and human
contributor follows when working in this repo. Adapted from the pattern
in `Davidvandijcke/coarse`.

Branch model: `dev` is the integration branch, `main` is the released branch.

---

## Default workflow

For any substantial change:

1. Branch from `dev`: `git checkout -b feat/<topic>` or `fix/<topic>`.
2. Land the change on the feature branch into `dev` via PR.
3. Validate against the lane's CI (path-filtered workflows) plus the
   full pipeline integration smoke on `dev`.
4. Merge `dev` → `main` via a release PR only when a coherent set of
   changes is ready to ship.
5. Tag from `main` (`v0.X.Y`) — the release workflow then builds the
   wheel and creates the GitHub release. PyPI publish is gated on a
   separate manual step until Phase 4 of the stability sprint lands.

Hard rules:

- **No direct pushes to `main`.** Branch protection enforces PR-only.
- **No live paper runs from `dev`** without prior integration-smoke pass.
- **Every cross-lane change needs an explicit `AGENTS.md` flag** in the
  PR description. Lanes are independent by default; breaking a lane's
  public contract is a main-blocking issue.
- **A failed real-paper run is a test failure.** If a live run uncovers
  a bug, the fix lands with a regression test in the relevant lane's
  `tests/` directory before reaching `main`.

---

## Tag-driven release

`E2ER` is **not** auto-published when `dev` merges into `main`. The
`.github/workflows/release.yml` workflow only fires on `push: tags: v*`,
and the build job hard-fails unless the tag matches both:

  - `pyproject.toml` `version`
  - `src/__init__.py` `__version__`

Substantial changes can sit on `main` indefinitely without ever
shipping a tagged release. That is intentional.

Release procedure:

1. Open a release PR `dev` → `main`. In that PR:
   - Bump version in both files.
   - Move `CHANGELOG.md` entries from `## Unreleased` to
     `## vX.Y.Z — YYYY-MM-DD`.
2. Merge the PR.
3. Tag and push from `main`:
   ```
   git checkout main && git pull
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```
4. The release workflow runs: tests → version-consistency check → build →
   GitHub release artifact.

Skipping step 3 leaves the release un-cut no matter how much code lands
on `main`. Doing step 3 without step 1 fails the version-check job by
design.

---

## Three-lane modular split

The codebase has three largely-independent lanes. Agents working on
different lanes do not need to coordinate beyond the public contracts.

```
src/
├── core/                  ← Lane A — Knowledge Production Pipeline
│   ├── specialists/       ← Specialist runners, dispatcher, registry
│   ├── strategist/        ← Runner, engine, context, review aggregation
│   ├── pipeline/          ← DAG, state persistence
│   ├── artifacts/         ← Artifact registry
│   └── renderer/          ← LaTeX assembly + compilation
│
├── modules/literature/    ← Lane B — Knowledge & Literature Ingestion
│   ├── (provider clients: OpenAlex, S2, arxiv, …)
│   └── (KB indexing, citation graph, reference checking)
│
└── modules/data/          ← Lane C — Data Module
    ├── allium.py          (SQL Explorer client)
    ├── allium_developer.py (Developer-tier REST client)
    ├── cli.py             (gatekeeper subcommands)
    ├── guardrails.py
    ├── audit.py
    └── dictionary.py
```

### Public contracts (what each lane MUST keep stable)

- **Lane A → world**:
  - `POST /api/papers` (create + start)
  - `GET /api/papers/{id}`, `/events`, `/artifacts`, `/usage`
  - Canonical workspace artifact filenames (see `SPECIALIST_ARTIFACTS`)

- **Lane B → Lane A**:
  - `literature_review.md` written to workspace (canonical artifact for
    `literature_scanner`)
  - Bibliography references usable by `polish_bibliography` specialist
  - Provider HTTP-shape contracts in `tests/lit/contract/`

- **Lane C → Lane A**:
  - `e2er-allium-query` bash wrapper subcommands (see
    `scripts/e2er-allium-query`)
  - `data_dictionary.json` schema (pydantic model in `dictionary.py`)
  - Guardrail rejection-string contracts (model reads these as plain text)
  - Provider param-name contracts in `tests/data/contract/`

### Tests per lane

- `tests/pipeline/` — Lane A
- `tests/lit/` — Lane B
- `tests/data/` — Lane C
- `tests/shared/` — cross-lane (config, logging, llm backends)

### CI gating

Each lane has a path-filtered workflow:

- `.github/workflows/ci-pipeline.yml` triggers on `src/core/**`, `tests/pipeline/**`
- `.github/workflows/ci-lit.yml` triggers on `src/modules/literature/**`, `tests/lit/**`
- `.github/workflows/ci-data.yml` triggers on `src/modules/data/**`, `tests/data/**`

A PR that only touches Lane B does not run Lane C's tests, and vice
versa. The full `ci.yml` ("everything") runs on `dev`/`main` merges.

### CHANGELOG discipline

CHANGELOG entries under `## Unreleased` are grouped by lane:

```markdown
## Unreleased

### Lane A — Pipeline
- ...

### Lane B — Literature
- ...

### Lane C — Data
- ...

### Cross-lane
- ...
```

Makes release notes auto-organizable and shows which lanes are evolving.

---

## What NOT to do

- Do not run `make rebuild-app` against the user's running production
  uvicorn without warning — it kills in-flight paper runs.
- Do not modify the GitHub branch-protection ruleset; the configuration
  lives in `scripts/setup_branch_protection.sh` and any change should go
  through that script with a code-review PR.
- Do not push directly to `main`. Branch protection will reject, but
  the intent matters: every fix is reviewable.
- Do not skip CI for "obvious" doc-only fixes. Doc CI is fast (~30s).
- Do not bypass the data-module guardrails or talk to Allium directly
  from inside specialists. Use `e2er-allium-query`.

---

Primary references:

- [CLAUDE.md](CLAUDE.md) — Claude-specific notes (project overview,
  pipeline mechanics, hot-spots)
- [CONTRIBUTING.md](CONTRIBUTING.md) — first-time-contributor checklist
- [docs/NEXT_STEPS.md](docs/NEXT_STEPS.md) — current status snapshot
