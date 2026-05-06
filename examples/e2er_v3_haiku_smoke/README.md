# E2ER v3 Smoke Test — Ethereum Block Timing

**This is a smoke test, not a research paper.** The artifacts here were produced by running the v3 pipeline end-to-end against a real LLM, primarily to validate that the pipeline plumbing works. The research content has substantial limitations (see "Quality and limitations" below) and should not be cited.

## Run details

| | |
|---|---|
| Backend | OpenRouter |
| Model | `anthropic/claude-haiku-4.5` |
| Mode | `single_pass` |
| Data module | disabled (no Allium key) |
| GitHub push | disabled |
| LaTeX compile | skipped (no `latexmk` on host) |
| Cost cap | $3.00 |
| **Runtime** | **650.9 s (≈ 11 minutes)** |
| **Estimated cost** | **~$1.25–1.50** |
| **Tokens** | **~675K total** |
| **Status** | `completed` (13 specialist contributions) |

## Research question (input)

> What is the empirical relationship between Ethereum block height and wall-clock elapsed time on Ethereum mainnet since the merge?

The `idea_developer` specialist correctly identified that the literal question is mechanically deterministic (block time targets 12 seconds post-Merge by protocol specification), and reframed it into a substantive empirical question about **block timing regularity, slot-skip rates, and validator-ecosystem maturation**. That reframing is the most genuinely useful piece of work in this run.

## What's here

```
manifest.json                       Run metadata
paper_plan.md                       Research design (40 KB) — solid reframing of the RQ
literature_review.md                Related work (25 KB)
identification_strategy.md          Causal identification (26 KB)
data_dictionary.json                Pre-specified data footprint (22 KB)
econometric_spec.md                 Model + equations (30 KB)
paper_draft.tex                     Full LaTeX manuscript (45 KB) — post-revision
review_mechanism.md                 (25 KB)
review_technical.md                 (25 KB)
review_identification.md            (25 KB)
review_literature.md                (23 KB)
review_data.md                      (26 KB)
review_writing.md                   (39 KB)
review_aggregation.json             Verdict (MAJOR_REVISION, 5.7/10 weighted)
replication/estimation.py           Full Python estimation script (36 KB)
replication/README.md               How to reproduce (16 KB)
```

## Pipeline self-assessment

The pipeline's own review aggregator gave the paper a **MAJOR_REVISION** verdict (weighted avg 5.7/10):

```json
{
  "verdict": "MAJOR_REVISION",
  "weighted_avg": 5.7,
  "rule_triggered": "Rule 3: weighted average",
  "rationale": "Weighted average score: 5.70/10. Verdict: MAJOR_REVISION."
}
```

The reviewers (without access to real data) flagged genuine weaknesses — fabricated numbers, weak identification, missing robustness work — which the pipeline then addressed in revision. The revised draft is what's here.

## Quality and limitations

**The hard truth**:

1. **Numbers are fabricated.** The data module was disabled (no Allium key), so the `data_analyst` and `econometrics_specialist` did not query real Ethereum data. Specific claims in the paper draft like "average inter-block interval is 12.01 seconds with standard deviation of 0.31 seconds" or "slot skip rates declined from 3.2% to 2.1%" are *plausible but invented* by Haiku. The replication script exists but has not been run against live data.

2. **Haiku 4.5 is a small model.** It produced workable structure and reasonable prose but lacks the depth that Sonnet would bring. Several reviews (mechanism, literature) scored 5–6/10 — explicitly because the underlying argument and lit synthesis are thin. Running this same pipeline on Sonnet would cost ~5× more but produce noticeably better content.

3. **No real literature search.** The literature tools (`search_papers` etc.) are wired but the model didn't invoke them in this run; the literature review is built from the model's training data, with citations the model believes exist. Some may be hallucinated. Running with `LITERATURE_BIBTEX_FILE` set to a curated `.bib` would fix this.

4. **No PDF.** `latexmk` isn't installed on the host that ran this, so the paper wasn't compiled to PDF. The `.tex` is well-formed and should compile.

5. **Single-pass mode.** No iterative loop, no self-attack phase, no polish stack. Iterative mode would catch more issues but also cost more.

## What this run actually demonstrates

It validates that v3's pipeline plumbing works end-to-end on a real (cheap) LLM:

- ✅ Strategist emits parseable JSON, dispatches specialists in correct phase order.
- ✅ Each specialist writes its **single canonical artifact** with the expected filename — no `START_HERE.md` / index / completion-report meta-files (a real failure mode that surfaced in earlier diagnostic runs).
- ✅ Reviewer context-injection works: each reviewer made exactly **one tool call** (`write_file`), down from 8 in pre-fix runs. Review-phase tokens dropped 4.7× (803K → 172K).
- ✅ Cost cap engages without a database (in-memory cumulative cost tracking).
- ✅ Revision phase reads + revises the draft based on aggregated reviews.
- ✅ Replication phase produces a self-contained estimation script and README.
- ✅ All 13 contributions persisted; full audit bundle available via `GET /api/papers/{id}/audit-bundle` if running through the API.

## Reading order (suggested)

1. **`manifest.json`** — run metadata
2. **`paper_plan.md`** — start here for the reframed research question
3. **`paper_draft.tex`** — the post-revision paper itself (45 KB)
4. **`review_aggregation.json`** + any one **`review_*.md`** — see how reviewers scored it
5. **`replication/estimation.py`** — the Python script that *would* run if you had data

## How to produce a higher-quality reference output

To close the two largest quality gaps in this run:

1. **Use a stronger model.** Sonnet 4.6 or Opus 4.7 produce noticeably better prose, argument depth, and review feedback than Haiku. Cost scales roughly with the model's price-per-token (see table below).
2. **Supply real data.** Set `ALLIUM_API_KEY` in `.env` and run on a research question that has actual on-chain data. Without it, the `data_analyst` and `econometrics_specialist` invent plausible numbers — the structure looks right but the substance is fictional.
3. **Supply curated literature.** Set `LITERATURE_BIBTEX_FILE=/path/to/refs.bib` in `.env` so `literature_scanner` and `paper_drafter` work from real BibTeX entries instead of inferring citations from training data (some of which may be hallucinated).
4. **Use iterative mode.** This run used `mode: "single_pass"` (one design pass + reviews + revision). `mode: "iterative"` adds the ceiling-check + self-attack + polish stack, catching more issues. ~3× the cost but substantially better output.

A "best-effort" demo run (Sonnet 4.6 + iterative + Allium + curated bibtex) would cost roughly $15–25 and take 30–60 minutes, and should produce a draft worth sending to a real co-author.

## How to select a model

Model selection is via two environment variables in `.env` (or the running container's environment):

```bash
# Pick the backend
LLM_BACKEND=openrouter      # or: anthropic

# Set the model for that backend
ANTHROPIC_MODEL=claude-sonnet-4-6              # used when LLM_BACKEND=anthropic
OPENROUTER_MODEL=anthropic/claude-sonnet-4.6   # used when LLM_BACKEND=openrouter
```

After changing `.env`, restart the app (`docker compose restart app`, or relaunch `uvicorn`). The `default_model` in `src/config.py` reads the backend-appropriate setting at startup.

### Current OpenRouter models (verified against the live API)

Pricing per 1M tokens (input / output). A v3 single_pass run uses ~675K tokens (~80/20 in/out split), so estimate:
**cost ≈ 0.54 × in_price + 0.135 × out_price**.

| Model | OpenRouter ID | $/M in | $/M out | Est. single_pass | Notes |
|---|---|---|---|---|---|
| **Claude Haiku 4.5** | `anthropic/claude-haiku-4.5` | 1.00 | 5.00 | **~$1.20** | what this smoke test used |
| **Claude Sonnet 4.6** | `anthropic/claude-sonnet-4.6` | 3.00 | 15.00 | **~$3.65** | recommended for real runs |
| Claude Opus 4.7 | `anthropic/claude-opus-4.7` | 5.00 | 25.00 | ~$6.10 | top-tier reasoning |
| GPT-5.4 | `openai/gpt-5.4` | 2.50 | 15.00 | ~$3.40 | OpenAI parallel to Sonnet |
| GPT-5.4 mini | `openai/gpt-5.4-mini` | 0.75 | 4.50 | ~$1.00 | cheap, capable for tools |
| GPT-5.4 nano | `openai/gpt-5.4-nano` | 0.20 | 1.25 | ~$0.28 | very cheap; may struggle with discipline |
| GPT-5.5 | `openai/gpt-5.5` | 5.00 | 30.00 | ~$6.75 | newer, more expensive |
| Gemini 3.1 Pro | `google/gemini-3.1-pro-preview` | 2.00 | 12.00 | ~$2.70 | competitive with Sonnet |
| Gemini 3 Flash | `google/gemini-3-flash-preview` | 0.50 | 3.00 | ~$0.67 | cheap fast option |
| Grok 4.3 | `x-ai/grok-4.3` | 1.25 | 2.50 | ~$1.00 | unusually cheap output |
| DeepSeek v4 Pro | `deepseek/deepseek-v4-pro` | 0.43 | 0.87 | ~$0.35 | very cheap reasoning model |
| DeepSeek v4 Flash | `deepseek/deepseek-v4-flash` | 0.14 | 0.28 | **~$0.11** | cheapest viable option |
| Kimi K2.6 | `moonshotai/kimi-k2.6` | 0.75 | 3.50 | ~$0.88 | Moonshot's mid-tier |
| Qwen 3.6 Flash | `qwen/qwen3.6-flash` | 0.25 | 1.50 | ~$0.34 | cheap |

The full live list (370+ models as of 2026-05): <https://openrouter.ai/models>.

**Tool-use is required.** Any model in the list above supports function/tool calling. Older models (GPT-3.5, Claude 1/2) and pure-completion models do not — avoid them. A model that doesn't follow the single-file output discipline will burn through `max_tokens` on partial outputs (the original $4-runaway failure mode that drove the v3 hardening).

**`~` prefix means "alias to latest"** — e.g. `~anthropic/claude-sonnet-latest` always points to the newest Sonnet. Useful if you don't want to update the version in `.env` every release, but pins are safer for reproducibility.

### Per-paper override (not yet exposed)

The current API uses the `.env` setting for every paper. There is no `model:` field on `POST /api/papers`. If you want different papers to use different models, run multiple instances with different `.env` files, or extend `CreatePaperRequest` to accept a `model` field and pass it down to `PipelineRunner`. About 20 lines of code.

## How to compare future runs

This file format is stable across the v3 pipeline. To preserve a similar smoke-test artifact from a future run:

```bash
cp -r /tmp/e2er_smoke/<paper_id>/ examples/e2er_v3_<descriptor>/
# add a README following this template
```

Helpful for tracking quality drift across model upgrades, prompt tweaks, or skill changes.
