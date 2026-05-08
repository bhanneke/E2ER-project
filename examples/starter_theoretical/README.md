# Starter — theoretical paper template

A minimal template for trying E2ER's `theoretical` methodology without needing
any data, Allium, or external services. Just an LLM API key and ~$3-8 of credit.

## What this is

A one-page paper plan for a purely theoretical paper:

> "When does a profit-maximising platform optimally subsidise a side
> of a two-sided market?"

This is a textbook two-sided-market problem. The pipeline will run
`theory_specialist` (formal model + propositions), `literature_scanner`,
`identification_strategist` (conceptual identification of the mechanism),
writing, and review — but will skip `data_architect`, `data_analyst`, and
`econometrics_specialist` because the methodology is theoretical.

## How to use

### Option 1 — via the dashboard

1. Open `http://localhost:8280/` after `./scripts/quickstart.sh`
2. Click **New paper**
3. Copy the `title` and `research_question` from `manifest.json`
4. Set **Mode** = `single_pass` (faster, cheaper) or `iterative` (better quality)
5. Set **Methodology** = `theoretical`
6. Set **Cost cap** = `10` to be safe
7. Submit. The strategist will dispatch theory_specialist, literature_scanner,
   etc. — but not data/econometrics specialists.

### Option 2 — via the API

```bash
curl -X POST http://localhost:8280/api/papers \
  -H "Content-Type: application/json" \
  -d @examples/starter_theoretical/manifest.json
```

(If you have `API_AUTH_TOKEN` set, add `-H "Authorization: Bearer <token>"`.)

## What you should expect

A `theoretical` single-pass run typically produces:

| File | Specialist | Description |
|------|------------|-------------|
| `paper_plan.md` | idea_developer | Research design with propositions |
| `literature_review.md` | literature_scanner | Related work synthesis |
| `model_spec.md` | theory_specialist | Formal model with assumptions, derivations, propositions in LaTeX |
| `identification_strategy.md` | identification_strategist | Conceptual identification of the mechanism |
| `paper_draft.tex` | paper_drafter | Full LaTeX draft |
| `abstract.tex` | abstract_writer | Standalone abstract |
| `review_*.md` | reviewer specialists ×6 | Mechanism, technical, literature, writing, identification + (data review will be light since there's no data) |
| `review_aggregation.json` | (mechanical) | Final verdict |

Notably **absent**: `data_dictionary.json`, `data_summary.md`, `econometric_spec.md`.
Those are skipped because the methodology is theoretical.

## Cost expectation

- Single-pass + Haiku 4.5: ~$0.50
- Single-pass + Sonnet 4.6: ~$3-5
- Iterative + Sonnet 4.6: ~$10-15

Set a `max_cost_usd` cap that matches your appetite. The pipeline halts before
over-spending.
