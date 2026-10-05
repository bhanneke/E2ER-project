# Did the January 2024 approval of US spot Bitcoin ETFs change the co-movement ...

**Research question:** Did the January 2024 approval of US spot Bitcoin ETFs change the co-movement between Bitcoin returns and US equity returns?

**e2er's internal quality review:** 6.1 of 10 (weighted average): data 6.0, identification 6.0, literature 5.9, mechanism 5.6, technical 6.5, writing 7.0

**Run:** governance=`full`, backend=`claude_code`, model=`claude-sonnet-4-5`

## Headline estimates

| term | estimate | p-value |
| --- | --- | --- |
| `d_etf_listed` | -0.02118 | 0.243 |

## Folder guide

- `paper/` — the manuscript (`paper.tex`, `abstract.tex`, `refs.bib`, compiled `paper.pdf`)
- `code/` — the estimation script (`code/scratch/` holds exploratory scripts and logs); `requirements.txt` pins the packages it runs with; `get_data.py` loads the inputs the folder does not ship
- `data/` — the data summary and dictionary; `data_sources.json` records where each input came from and under which terms
- `results/` — estimation/robustness JSON + figures
- `design/` — research plan, identification strategy, econometric spec
- `reviews/` — the six reviewer reports and the combined score (`review_aggregation.json`)

## Reproduce

`reproduce.json` says how to run the study's code again. With e2er installed:

```bash
e2er reproduce .
```

This runs the code in a folder of its own, in a new environment with the pinned packages, and compares every result value and every table with the ones in this folder.

_Exported as `did-the-january-2024-approval-of-us-spot-bitcoin-etfs-change-20261005-01` from e2er._
