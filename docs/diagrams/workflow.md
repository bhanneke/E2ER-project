# The researcher's workflow

Where a human decides, where the machine runs, and where the gates sit. This is
the outside view; [`pipeline_overview.md`](pipeline_overview.md) is the same run
seen from inside, as specialist invocations. The prose version, with what each
gate actually checks, is [`docs/WORKFLOW.md`](../WORKFLOW.md).

Diamonds are human decisions. Nothing advances past one without the researcher.

```mermaid
flowchart TD
    subgraph bring["1 · Bring your own"]
        A1["your data folder<br/>csv · parquet · xlsx"]
        A2["your literature folder<br/>PDFs · Zotero · .bib"]
        A1 --> DOC[["e2er doctor<br/>reports what it found"]]
        A2 --> DOC
    end

    DOC --> RQ

    subgraph sharpen["2 · Sharpen the question"]
        RQ[["e2er rq --draft<br/>advisory only — never starts a run"]]
        RQ --> HUMAN1{{"Researcher accepts<br/>the question"}}
    end

    HUMAN1 --> ACQ

    subgraph run["3 · Run, with the human in the loop"]
        ACQ["literature acquisition<br/>writes literature.bib before any specialist<br/>self-skips if you brought a library"]
        ACQ --> PIPE[["e2er run --governance … --review-at …"]]
        PIPE --> PAUSE{{"checkpoint:<br/>inspect the workspace"}}
        PAUSE -->|"e2er resume"| GATES
        MATRIX[["e2er run-matrix<br/>k backends × n repeats"]] --> CMP[["e2er compare<br/>diffs design choices"]]
        CMP -.->|"coverage, not selection:<br/>no run is promoted"| HUMAN1
    end

    subgraph verify["4 · Everything verifiable"]
        GATES{"four gates<br/>see below"}
        GATES --> EXP[["e2er export<br/>bundle + provenance.json"]]
        EXP --> VER[["e2er verify<br/>offline, no keys, under a minute"]]
    end

    VER --> OUT([Bundle a stranger can check])

    classDef human fill:#fde9c8,stroke:#9d6a12,color:#3a2a06
    classDef gate fill:#d7ece2,stroke:#1a7350,color:#06251a
    class HUMAN1,PAUSE human
    class GATES,VER gate
```

## The gate chain, and what the regime changes

Four gates stand between the analysis and the paper. The regime chosen at
`e2er run --governance` decides which of them **block** — but every gate runs
in every regime. A gate that is not enforcing still computes its verdict and
logs a `gate_shadow` event saying what it would have caught.

That is what makes an ungoverned run *measured* rather than merely unblocked,
and what makes governance assignable as a treatment instead of only
describable.

```mermaid
flowchart LR
    S["Specialist output"] --> C{"contracts<br/>declared equals delivered"}
    C --> E{"estimation<br/>script ran, result parseable"}
    E --> N{"numbers<br/>cells from JSON sidecars"}
    N --> T{"citations<br/>every cite resolves"}
    T --> OK([Draft proceeds])

    C -.->|fail| FB["coached feedback<br/>then retry"]
    FB -.-> S

    classDef g fill:#d7ece2,stroke:#1a7350,color:#06251a
    class C,E,N,T g
```

| Regime | contracts | estimation | numbers | citations |
|---|---|---|---|---|
| `full` | blocks | blocks | blocks | blocks |
| `contracts` | blocks | shadow | shadow | shadow |
| `off` | shadow | shadow | shadow | shadow |

An unrecognised regime resolves to `full`, so a typo fails closed.

**One exception cuts across the table.** *Reliability* checks block in every
regime, `off` included. Whether the estimation script ran and wrote a
parseable, non-empty result is a question about the pipeline, not about the
paper, and the answer has to be the same in every arm — otherwise the `off`
cell measures a broken pipeline rather than an ungoverned one, and fabrication
is confounded with completion. That is not hypothetical; it is why the
distinction exists. See `enforces_check` in `src/core/governance.py`.

## What the picture does not show

No arrow above establishes that the analysis was *defensible*. The chain runs
from data through analysis into the manuscript and back out again, and
verification is a question about that chain — deterministic, cheap, settled by
a machine. Robustness is a different question with no deterministic answer, and
nothing in this diagram touches it.
