# Versioning reset — proposal

> **Status**: open proposal (2026-06-09). Owner asked for it after merging
> the M4.1/M4.2/M4.3 follow-ups: *"I think we are approaching v1 too
> quickly; already at 0.9 but many things not working yet."* This document
> argues that read is correct, proposes the cleanest fix, and inventories
> what would need to change.

## TL;DR

We've been calling this trajectory "v0.9 → v1.0" but that's the calendar
talking, not the system. **The pipeline has never produced a successful
end-to-end paper.** It has caught its own failures correctly four times
in a row, which is real progress, but conventional v0.9 implies
"release-candidate, things work for the stated purpose." E2ER's stated
purpose is *to produce empirical research papers end-to-end*, and we
haven't done that yet.

**Recommendation**: pull the line back to **0.8.x**. Treat M1-M3 and
M4.1-M4.3 as the **v0.8.2** cumulative release. Don't tag v0.9 until the
v0.9 plan's own definition is met — *"the install → trust loop is
closed"*, i.e. a real paper survives review under real conditions. Don't
talk about v1.0 until that has happened more than once across
methodologies.

## Why the current trajectory misreads the state

The v0.9 plan defined the milestone as **"closing the install → trust
loop"** — the install path, the doctor, the citation gate, the OA reach,
and a real end-to-end paper proof. The first four shipped (M1-M3 + M4.x
fixes). The last one — the actual proof — **failed in the M4 run**, and
correctly so. That's the load-bearing detail.

What M4 surfaced (documented in [`docs/M4_FINDINGS.md`](M4_FINDINGS.md)):

- Three real bugs in the v0.8 stack that M4.1/M4.2/M4.3 fixed.
- The mechanism reviewer's verdict — *"A referee cannot accept, or even
  major-revise, a paper into existence: the required 'revision' is to
  run the study"* — because `estimation_results.json` was literally
  `{}`. The pipeline wrote a paper around an empty result.
- A `REJECTED` terminal status, reached cleanly through the full
  30-stage pipeline.

The fix shipped. The proof did not. We are now in the position of having
**code that catches its own failures well but has not been shown to
succeed.** That is a different milestone than v0.9.

## What's actually working vs. what's mocked

Honest inventory — the column on the right is what would need to change
to put the row on the left in a release-candidate state.

| Surface | Status | Gap |
|---|---|---|
| `e2er doctor` preflight | ✅ live-validated | None |
| Verify-numbers gate + auto-patch | ✅ live in M4 | None |
| Verify-citations gate (`.bib` path) | ✅ live in M4 | None |
| Verify-citations gate (`\bibitem` path) | ✅ live in M4 post-M4.2 | None |
| OA-PDF resolver chain | ⚠️ live on hand-picked DOIs | Never tested against a real paper's reference list at scale |
| Cost tracker on $0 backends | ✅ live in M4 (caused PAUSED), fixed in M4.1 | None |
| Specialist contract check | ✅ unit + integration | Never fired in anger on a real run — we only know the M4 case it was designed for |
| **End-to-end empirical paper** | ❌ never succeeded | M5: produce one |
| End-to-end theoretical paper | ❌ never run | unit-tested, never live |
| `theory_specialist` | ❌ mocked only | live run never executed |
| 5× `polish_*` specialists | ⚠️ each ran in M4 but on a hollow paper | rerun on a paper that has real results |
| `replication_packager` | ⚠️ ran in M4 on a hollow paper | rerun on a paper that has real results |
| Reviewer scoring + aggregation | ❌ never pressure-tested | every test pins `Score: 7/10` literally; we don't know how aggregation handles a real split panel |
| Skill files (133+) | ⚠️ shipped, mostly unverified vs. output | needs sampling QA on real runs |

The shape of this table is what's misleading about "we're at v0.9." Most
green rows are "code paths that ran once and didn't crash." That's
v0.8-quality validation, not v0.9.

## Three options

### Option A — Pull back to v0.8.2 (recommended)

- Tag the current state as `v0.8.2` (or `v0.8.3` if more bugfix work
  lands first).
- Release notes describe M1-M3 + M4.x as improvements to the v0.8 line
  with no breaking API changes.
- The `docs/V0.9_PLAN.md` document stays as **the goal**, and a tag of
  `v0.9.0` is **gated on M5 producing a paper that survives review**.
- v1.0 is not on the timeline; it gets a separate plan when v0.9 has
  shipped and been used.

**Pros**: honest. Semantic. Doesn't promise what hasn't been
demonstrated. Cheapest path to fix.

**Cons**: minor messaging awkwardness — we already cut v0.8.1 and have
been calling the trajectory v0.9. Anyone who follows the changelog
closely will see a numeric step-down, which we should address head-on
in the release notes (*"we caught ourselves overpromising; here's how
we're calibrating"*).

### Option B — Tag v0.9.0 with explicit "incubating" / "alpha" status

- Ship v0.9.0 as scheduled but flag it as incubating in the README,
  release notes, and on PyPI (classifier: `Development Status ::
  3 - Alpha`).
- v1.0 stays in the distance, gated on N successful papers across
  methodologies (e.g., 3 empirical + 1 theoretical + 1 mixed).

**Pros**: keeps the trajectory the codebase already advertises.

**Cons**: dilutes what v0.9 means by convention. SemVer doesn't have a
clean "release candidate" track-record requirement; an "alpha" tag at
v0.9 is unusual and signals confusion.

### Option C — Reset to 0.x indefinitely

- Drop all v0.9 framing. Use 0.x for everything until production usage
  proves things work; only then propose v1.0.

**Pros**: maximally honest.

**Cons**: loses the readable milestone structure the V0.9 plan gave
us. Probably overcorrects.

## Recommendation

**Option A.** It matches what M4 actually showed: the system catches its
own failures well, the orchestration layer is sound, and the gates work.
What we don't have yet is a paper. Real software ships when the thing
it's for can be done, not when the things that make doing it possible
are individually merged.

## If we go with A, here's what changes

Light, mostly mechanical:

1. **Bump down**: `pyproject.toml` and `src/__init__.py` from whatever
   `v0.9` work was implicit back to **`0.8.2`** (or `0.8.3` if a few more
   bugfix PRs land before tagging). The standardised release flow then
   does the rest.
2. **Rename or annotate**: `docs/V0.9_PLAN.md` either renamed to
   something neutral (`docs/ROADMAP.md`) or kept as-is with a top-line
   note that v0.9.0 is **gated on M5 (real paper succeeds)** and the
   five Mi milestones in it are necessary but not sufficient.
3. **CHANGELOG.md**: move the seven `### v0.9 Mi` entries under
   `## v0.8.2 — <date>` instead of `## [Unreleased]`. The release notes
   call out the tactical wins (gates work, doctor works, OA chain
   works, cost tracker zeroes) and the strategic gap (no paper yet).
4. **README**: any v0.9-talk in the README softens to "v0.8 line,
   actively converging on the v0.9 quality bar".
5. **M5 / "ship v0.9.0" definition**: write it down explicitly. A paper
   that goes through the pipeline with a tight identification mechanism,
   produces non-empty results, survives the M2 + verify_numbers gates,
   gets a non-mocked reviewer panel score above the accept threshold,
   and compiles. **That** is v0.9.0.

## What I'd shelve until A is decided

- Tagging anything.
- Treating M5 as just "drop a paper into examples/showcase/". M5 needs
  to be the harder thing — *produce a paper that demonstrably works* —
  for any of this to matter.

## Open question for the owner

This document is a proposal, not an executed plan. Three things I'd want
your call on before doing the version bump:

1. **A vs. B vs. C?** I argued for A above; happy to be wrong if you
   want a different framing.
2. **0.8.2 or 0.8.3?** Are there more bugfix PRs you'd want to land
   before the cumulative tag, or do M1-M3 + M4.x represent the v0.8.2
   surface as it should ship?
3. **M5 definition.** Is *"one paper that survives a real review"* the
   right v0.9 gate, or do we want a stricter one (e.g., a paper that's
   externally publishable, not just internally-passing)?
