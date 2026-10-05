# Did the January 2024 approval of US spot Bitcoin ETFs change the co-movement ...

**Research question:** Did the January 2024 approval of US spot Bitcoin ETFs change the co-movement between Bitcoin returns and US equity returns?

**Verdict:** `MAJOR_REVISION` (weighted avg 6.142857142857143/10)

**Run:** governance=`full`, backend=`claude_code`, model=`claude-sonnet-4-5`

> Weighted average score: 6.14/10. Verdict: MAJOR_REVISION. Breakdown: mechanism_reviewer=5.6, technical_reviewer=6.5, literature_reviewer=5.9, writing_reviewer=7.0, data_reviewer=6.0, identification_reviewer=6.0

## Headline estimates

| term | estimate | p-value |
| --- | --- | --- |
| `d_etf_listed` | -0.02118 | 0.243 |

## Folder guide

- `paper/` — the manuscript (`paper.tex`, `abstract.tex`, `refs.bib`, compiled `paper.pdf`)
- `code/` — the estimation script (`code/scratch/` holds exploratory probes + logs)
- `data/` — the SQLite data warehouse (`data.db`) + data summary & dictionary
- `results/` — estimation/robustness JSON + figures
- `design/` — research plan, identification strategy, econometric spec
- `reviews/` — referee reports + the aggregated verdict

## Reproduce

```bash
cd code && python run_estimation.py   # reads ../data/ (or the original data files)
```

_Exported as `did-the-january-2024-approval-of-us-spot-bitcoin-etfs-change-20260911-05` from E2ER._
