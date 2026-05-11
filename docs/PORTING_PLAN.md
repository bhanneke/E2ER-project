# Porting plan — features inspired by `Imbad0202/academic-research-skills`

Five features to port, sequenced by leverage and risk. Total estimated effort
~2–3 focused days; all five can be developed offline at $0 (no live LLM
runs needed during development).

| # | Feature | Effort | Live-run cost | Independent? |
|---|---------|--------|--------------|--------------|
| 1 | Compliance front-matter (CRediT, AI-disclosure, ethics) | 2 hrs | $0 | yes |
| 2 | Devil's-Advocate concession threshold in self-attack | 3 hrs | $0 | yes |
| 3 | Reference integrity gate (independent OpenAlex/S2 verification) | 1 day | $0 | yes |
| 4 | Mid-pipeline entry modes (revision-coach, citation-check) | 1 day | $0 | depends on #3 |
| 5 | Showcase artifacts in `examples/showcase/` | 0.5 day + 1 paid run | ~$0.50 (Haiku) or $0 (CLI/Max) | last |

The order below is execution order, not leverage order. We do small wins
first to build confidence in the new patterns, then bigger architectural
work, then showcase last (because it depends on a real successful run).

---

## Item 1 — Compliance front-matter

### What

Every generated paper gets three new mandatory sections inserted by the
LaTeX assembly step:

- **CRediT statement**: contributor roles (Conceptualization, Methodology,
  Software, Validation, etc.) — even on AI-generated papers, journals
  expect a statement.
- **AI-disclosure**: which model generated which sections, which tools
  were invoked. Pulled from the `contributions` table directly — we
  already track every specialist call.
- **Ethics declaration**: data-use ethics + Allium guardrail attestation
  (linking back to `audit_log.csv`).

### Files

- `src/core/renderer/templates.py` — new function `compliance_front_matter(paper_id) -> str` that pulls from `contributions` + `data_query_records` and renders LaTeX.
- `src/core/renderer/prose.py` (or wherever the assembly happens) — call into the new function during paper rendering.
- `sql/011_compliance_artifacts.sql` — optional, only if we want a separate `compliance_declarations` table; can also live in the existing `papers` row as JSONB.

### Sketch

```python
# src/core/renderer/templates.py
async def compliance_front_matter(paper_id: str) -> str:
    """Render LaTeX `\section*{Author Contributions}`, AI-disclosure,
    ethics declaration. Pulls evidence from contributions + data_query_records."""
    from ..db.client import fetch_all

    contribs = await fetch_all(
        "SELECT specialist, model, output_file FROM contributions "
        "WHERE paper_id = %(id)s ORDER BY created_at",
        {"id": paper_id},
    )
    queries = await fetch_all(
        "SELECT query_type, validation_status, approved_by FROM data_query_records "
        "WHERE paper_id = %(id)s",
        {"id": paper_id},
    )
    return _render_jinja("compliance_front_matter.tex.j2", {...})
```

### Tests

- `tests/test_compliance_frontmatter.py`:
  - `test_credit_section_lists_contributing_specialists` — asserts every distinct specialist with at least one successful contribution appears in the rendered CRediT block.
  - `test_ai_disclosure_lists_models_used` — asserts the model column flows through.
  - `test_ethics_declaration_links_audit_log` — asserts the `replication/audit_log.csv` reference is in the LaTeX.
  - `test_compliance_front_matter_inserted_before_intro` — asserts the assembly step puts the new section before the abstract / introduction.

### Risks

Low. Pure additive feature; no behaviour change if the new sections are absent. Worst case: LaTeX compile fails on a malformed Jinja template — caught by `make smoke` if we add a test that renders against a fixture.

### Effort: ~2 hrs

---

## Item 2 — Devil's-Advocate concession threshold

### What

Today's `self_attacker` produces findings with severity scores. Critical
findings (>=7) trigger `revisor` work orders. **Missing**: the revisor's
output isn't *scored against the original finding* — there's no mechanism
to detect "the revisor responded but didn't actually address the
critique." The Imbad0202 pattern: a rebuttal must score above a threshold
on the original objection before the adversary "concedes."

### Files

- `src/core/strategist/review_aggregator.py` — already has `_WEIGHTS`, `_RECOMMENDATION_FLOOR`. Add `_CONCESSION_THRESHOLD = 7.0`.
- `src/core/strategist/runner.py:307` (`_run_self_attack_phase`) — after revisor work orders complete, run a follow-up `concession_check` step that compares the revisor's output to the original finding.
- `src/core/specialists/registry.py` — new specialist entry `concession_judge` (writes `concession_report.json`).

### Sketch

```python
# In _run_self_attack_phase, after critical revisions complete:

concession_orders = [
    WorkOrder(
        paper_id=self._paper_id,
        specialist="concession_judge",
        focus=(
            f"Original finding (severity {f.severity}): {f.description}\n"
            f"Revisor's response in {f.suggested_fix_artifact}.\n"
            f"Score whether the response materially addresses the finding "
            f"(0-10). Concession threshold: 7.0. Below 7 means the finding "
            f"is NOT resolved — flag for human review."
        ),
        context_tier=2,
    )
    for f in attack_report.critical_findings[:3]
]

contributions = await execute_parallel(concession_orders, ...)
unresolved = [c for c in contributions if _parse_score(c.output) < _CONCESSION_THRESHOLD]
if unresolved:
    logger.warning("Self-attack: %d critical findings remain unresolved", len(unresolved))
    # Block status from advancing to REVIEW until human reviews the concession_report.
```

### Tests

- `tests/test_concession_threshold.py`:
  - `test_concession_above_threshold_advances_pipeline` — score 8/10 → status advances.
  - `test_concession_below_threshold_blocks` — score 5/10 → status stays SELF_ATTACK with a clear log entry.
  - `test_concession_judge_skill_files_exist` — same pattern as `test_methodology.py::test_theory_specialist_skill_files_exist`.

### Risks

Medium. The judge's output must be parseable; we need a strict prompt
returning JSON `{"score": float, "rationale": str}`. If the judge
hallucinates a score, the threshold is meaningless. Mitigation: require
the judge to *quote* the revisor's text before scoring, and cap to a
short structured response. Pattern proven in the Allium guardrail
parsing — we know how to do strict JSON on Sonnet/Haiku.

### Effort: ~3 hrs

---

## Item 3 — Reference integrity gate

### What

Imbad0202's most-cited insight: their post-publication audit found 31% of
references in their AI-generated papers had errors that *passed* three
rounds of internal review. The fix: a **dedicated, model-isolated**
verification step that re-checks every citation against an independent
authority (OpenAlex, Semantic Scholar) and **blocks finalization** on
failure.

E2ER already has the verification primitives (`src/modules/literature/openalex.py`,
`semantic_scholar.py`). What's missing is a hard gate that runs them
against the assembled bibliography.

### Files

- `src/core/specialists/integrity_checker.py` (new specialist) — reads `references.bib`, queries OpenAlex/S2 for each entry, produces `integrity_report.json` with per-citation pass/fail.
- `src/core/specialists/registry.py` — register specialist + skill bundle.
- `src/core/strategist/runner.py` — new phase `integrity` that runs *between* `revision` and `replication`. **Must block** on any failed citation; this is a hard gate, not a warning.
- `skills/files/review/integrity-check.md` (new) — skill doc for the integrity_checker specialist.
- `src/api/app.py` — new GET endpoint `/api/papers/{id}/integrity-report` so the dashboard can display the report.

### Integrity report shape

```json
{
  "verified": 14,
  "failed": 3,
  "items": [
    {
      "key": "Smith2023",
      "claimed": {"title": "...", "authors": [...], "year": 2023, "doi": "..."},
      "verified": true,
      "source": "openalex",
      "discrepancies": []
    },
    {
      "key": "Jones2022",
      "claimed": {"title": "Deep liquidity in Uniswap v3", "doi": "10.1234/fake"},
      "verified": false,
      "source": "openalex",
      "discrepancies": ["DOI not found", "No matching title in OpenAlex"]
    }
  ]
}
```

### Tests

- `tests/test_integrity_checker.py`:
  - `test_valid_citation_passes` — mock OpenAlex returns matching record → verified=true.
  - `test_invalid_doi_fails` — mock OpenAlex 404s → verified=false with discrepancy.
  - `test_title_mismatch_fails` — mock returns different title → discrepancy logged.
  - `test_integrity_phase_blocks_on_failure` — runner raises if any citation has verified=false.
  - `test_integrity_phase_allows_on_all_pass` — runner advances normally.
  - `test_integrity_report_endpoint_returns_report` — API smoke test.

### Risks

Medium-high. False negatives are the killer (OpenAlex misses a real
paper, we block a valid bibliography). Mitigation:
- Two-source fallback: if OpenAlex fails, try Semantic Scholar, then arXiv.
- Soft-fail mode for first month: run the gate but log instead of block, until we've validated the false-negative rate on real bibliographies.
- Allow human override (existing `acknowledge_unproven_tuple` pattern — extend to `acknowledge_integrity_failures: list[str]`).

### Effort: ~1 day

### Dependency

This is the credibility play. Required before we ship showcase artifacts
(item 5) — the showcase paper should advertise "passed integrity check
against OpenAlex" prominently. **Item 4 should follow this** to expose the
report as a mid-pipeline mode (citation-check).

---

## Item 4 — Mid-pipeline entry modes

### What

Today `POST /api/papers` assumes RQ → full paper. Adding entry modes
expands the addressable use case 5×:

- **`citation-check`**: user provides only `references.bib` (or a paper draft); pipeline runs only the integrity-checker (item 3), no LLM-driven generation. Cost: ~$0 (lookups only).
- **`revision-coach`**: user provides their *own* paper draft + reviewer comments PDF/text; pipeline runs `revisor` + `concession_judge` (item 2) and produces a revision plan. Cost: ~$1-3.
- **`outline-only`**: user provides RQ; pipeline stops after `paper_plan.md`. Cost: ~$0.50.
- **`disclosure-only`**: user provides their finished paper; pipeline runs item 1's compliance front-matter generator and returns LaTeX they can paste in. Cost: ~$0.

### Files

- `src/api/app.py` — `CreatePaperRequest.entry_mode: Literal["full", "citation-check", "revision-coach", "outline-only", "disclosure-only"] = "full"`.
- `src/core/strategist/runner.py` — `PipelineRunner.__init__` accepts `entry_mode`; `run()` dispatches to a different phase sequence per mode.
- `src/core/strategist/runner_modes.py` (new) — `MODE_DAGS: dict[str, list[str]]` defining which phases each mode runs. Keeps `runner.py` clean.
- `src/api/app.py` — `POST /api/papers/{id}/upload` now accepts `references.bib`, `reviewer_comments.txt`, `existing_draft.tex` for the upload-driven modes.
- README — table of modes with cost estimates per mode.
- `examples/starter_*` — add starter templates for each mode.

### Sketch

```python
# src/core/strategist/runner_modes.py
MODE_DAGS = {
    "full": ["initial", "iterative", "self_attack", "polish", "review", "revision", "integrity", "replication"],
    "citation-check": ["integrity"],
    "revision-coach": ["revision", "concession_check", "integrity"],
    "outline-only": ["initial"],  # stops after idea_developer
    "disclosure-only": [],  # only the compliance render step
}
```

```python
# src/core/strategist/runner.py
async def run(self) -> dict[str, Any]:
    phases = MODE_DAGS[self._entry_mode]
    for phase in phases:
        if state.is_complete(phase):
            continue
        await self._run_phase(phase)
        state.mark_complete(phase)
        state.save(self._workspace)
```

### Tests

- `tests/test_entry_modes.py`:
  - `test_full_mode_runs_all_phases` — pin existing default behaviour.
  - `test_citation_check_skips_generation` — only `integrity` phase runs; LLM tool_loop called zero times for generation specialists.
  - `test_revision_coach_uses_uploaded_draft` — pipeline reads `existing_draft.tex` from workspace; doesn't run `paper_drafter`.
  - `test_outline_only_stops_after_initial` — `paper_plan.md` exists, `paper_draft.tex` doesn't.
  - `test_disclosure_only_runs_no_specialists` — pure rendering; cost = $0.
  - `test_unknown_entry_mode_rejected_with_400` — API validation.

### Risks

Medium. The biggest change is moving the phase loop from
hardcoded-sequence to a list lookup. The resilience test suite already
validates per-phase resume; if we keep that contract, the modes layer
is just a different list of phases.

### Effort: ~1 day

### Dependency

Item 3 (integrity gate) provides the `integrity` phase, which
`citation-check` and `revision-coach` need. Item 1 (compliance) provides
the renderer that `disclosure-only` calls.

---

## Item 5 — Showcase artifacts

### What

Three to five fully-generated paper repos under `examples/showcase/`,
linked prominently from the README. Each includes the LaTeX, the
replication package, the audit log, the integrity report (item 3), and
the compliance declarations (item 1).

### Files

- `examples/showcase/01-nft-marketplace-fees/` — the paper from the May 2026 attempt, *now* completed via CLI backend ($0).
- `examples/showcase/02-theoretical-two-sided-markets/` — generated via the existing `examples/starter_theoretical/` template.
- `examples/showcase/03-mixed-event-study/` — for the `mixed` methodology.
- `examples/showcase/README.md` — one-paragraph summary of each, with cost / runtime / model used.
- `README.md` — link from the "Example outputs" section.

### Process

1. After items 1–3 ship, set `LLM_BACKEND=claude_code` in `.env` and run each paper at $0 (Max plan).
2. Capture the workspace, the integrity report, the audit log, the LaTeX-compiled PDF.
3. Copy into `examples/showcase/<name>/`.
4. Strip any environment-specific paths.
5. Add a one-paragraph "what this demonstrates" note per paper.

### Tests

None — these are static artifacts. Instead, add to CI:

- `tests/test_examples.py::test_each_showcase_paper_has_required_artifacts` — pin that every `examples/showcase/*/` has `paper.pdf`, `paper.tex`, `replication/`, `audit_log.csv`, `integrity_report.json`. Static check; if a showcase loses a file, CI fails.

### Risks

Low for the *files*. The risk is the *runs failing* — we still haven't
confirmed an end-to-end CLI-mode run completes cleanly. **Item 5 is
contingent on at least one successful end-to-end pipeline run.** If that
fails, the diagnosis is free (CLI mode is $0) but it might block this
item until fixed.

### Effort: ~0.5 day for the writing/staging + however long the runs take

### Dependency

Items 1, 2, 3, 4 should ship first so the showcase reflects the full
feature set we're advertising.

---

## Sequencing recommendation

```
Week 1:
  Day 1: Item 1 (compliance) + Item 2 (concession threshold)
         — both small, both ship value, build muscle for #3
  Day 2: Item 3 (integrity gate)
         — credibility play, the public differentiator vs Imbad0202
  Day 3: Item 4 (mid-pipeline modes)
         — market-expansion play, depends on #3

Week 2:
  Day 1: Validate end-to-end CLI-mode run ($0)
  Day 2: Generate showcase artifacts
  Day 3: README polish, blog post, share publicly
```

## What this plan deliberately omits

- **Bilingual abstracts (zh-TW/EN)** — Imbad0202 has this; E2ER's audience is empirical IS/econ/finance, mostly EN. Skip until requested.
- **PRISMA / RoB 2 / ROBINS-I bias assessment** — relevant for systematic reviews, not for the empirical-paper workflow E2ER targets. Out of scope.
- **Retraction monitoring** — running cron jobs against retraction databases is a separate piece of infrastructure. Not blocking item 3; can fold in later as an extension to the integrity checker.
- **Cross-model verification** (run GPT/Gemini against Anthropic on integrity stages) — interesting, but doubles API spend on a check that already passes 99% of the time when OpenAlex is the source of truth. Worth it only if false-negative rate on item 3 turns out to be high.
