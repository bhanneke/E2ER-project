# The workflow

What actually happens between a research question and a bundle a stranger can
check. This document is written against the code, not against the pitch: every
phase name, gate name and regime below is the identifier the pipeline uses, and
the last section says plainly what the system does *not* establish.

---

## 1 · Before the pipeline starts

Two things are put on disk before any specialist runs, both in
`_prepare_and_run` (`src/api/app.py`).

**Your library, if you brought one.** When `LITERATURE_DIR` or
`LITERATURE_BIBTEX_FILE` names a Zotero library or a folder of PDFs, it is
discovered, staged into the workspace, enriched against CrossRef and OpenAlex,
and persisted so `search_papers` serves it offline. Your PDFs never leave the
machine; exported bundles carry the BibTeX corpus only.

**A bibliography, if you did not.** Acquisition searches the paper's own
research question and title against the configured providers and writes
`literature.bib`. It self-skips when a bibliography already exists, so a
researcher's own library always wins.

This is a stage rather than a tool on purpose. The drafter *had* a
`save_bibtex` tool and a skill file telling it to use one, and on CLI backends
`tool_loop` ignores SDK tools entirely — so the drafter cited from memory
against a `references.bib` that did not exist. Granting a capability and
instructing a model to use it does not make it used. Acquisition does not ask.

## 2 · The phases

From `PipelineRunner.run` (`src/core/strategist/runner.py`). Phases marked
*iterative only* are skipped in `--mode single_pass`.

| Phase | What happens |
|---|---|
| `initial` | The strategist fixes the design and dispatches specialists, each sandboxed with its own context. Specialists never execute code: the orchestrator runs their scripts and checks the result files came back populated. |
| `iterative` *(iterative only)* | Further design/dispatch rounds, with a ceiling check that stops the loop when returns flatten. |
| `estimation_gate` | Deterministic. Never skipped on resume. |
| `self_attack` *(iterative only)* | The strategist attacks its own paper; findings are dispatched to a patch revisor. |
| `polish` *(iterative only)* | Prose and presentation pass. |
| `review` | Internal referee panel. The numbers and citation gates run here, after the table specification is resolved. |
| `revision` | Reviewer findings are addressed. |
| `replication` | The runnable replication package is assembled. |
| *finalize* | Compile, optional GitHub push, export. Runs best-effort even on a failed paper, so a broken run still leaves an auditable trail. |

`--review-at <phase>` pauses **after** that phase's work is persisted and
before the next begins; `e2er resume <paper_id>` continues. Resume skips phases
whose canonical artifact already exists, so approving a checkpoint does not
re-spend the work behind it.

## 3 · The four gates

`GATES = ("contracts", "estimation", "numbers", "citations")`
(`src/core/governance.py`).

**contracts** — each specialist declares what it will produce; the check
verifies the contribution matches. A failure produces coached feedback and a
retry rather than a bare rejection.

**estimation** — an empirical paper with a populated data warehouse must have a
contract-clean estimation before any drafting-dependent phase runs. This gate
exists because the specialist-level contract alone was not enough: econometrics
once failed its contract, the strategist moved on, and the pipeline spent
self-attack, polish and review tokens drafting a paper around `{}`.

**numbers** — every results-table cell is filled by a deterministic renderer
from JSON sidecars, by lookup, never arithmetic. No model is anywhere in the
number path. The gate then checks the prose against those sidecars.

**citations** — every `\cite` key must resolve in `refs.bib` and against the
researcher's library, OpenAlex, Semantic Scholar and Crossref. The report
distinguishes *verified*, *unverifiable* (a real key no registry answers for —
typically a recent working paper) and *missing from the bibliography* (a key
with no entry at all). Only the last is a fabrication signal; the report also
carries whether it was conclusive, so "skipped" can never read as "verified".

## 4 · Governance is a knob, not a fixture

`e2er run --governance off|contracts|full` selects which gates **block**:

| Regime | Blocks |
|---|---|
| `full` | contracts, estimation, numbers, citations |
| `contracts` | contracts only |
| `off` | nothing |

An unknown regime resolves to `full`, so a typo fails closed.

The part that makes this an instrument rather than a convenience: **a gate that
is not enforcing still runs.** It computes its verdict and logs a `gate_shadow`
event recording what it would have caught. An ungoverned run is therefore
*measured*, not merely unblocked — which is what makes governance assignable as
a treatment rather than merely describable.

**One exception, and it is load-bearing.** Reliability checks block in *every*
regime, `off` included (`enforces_check`). Whether the estimation script ran
and wrote a parseable, non-empty result is a question about the pipeline, not
about the paper, and the answer must be the same in every arm. Conflating the
two once made the `off` cell meaningless: a script crashed on a timezone
comparison and wrote `{}`, `off` shadowed the artifact check, nothing flipped
the specialist to failure, the traceback was never fed back for a retry, and
the drafter wrote four tables of invented numbers over the hole. That run
measured a broken pipeline, not an ungoverned one, and confounded fabrication
with completion.

## 5 · What leaves the machine

`e2er export <paper_id>` assembles a bundle carrying `provenance.json`: a
SHA-256 of every file plus the derivation graph — table cells back to source
keys, citations back to the registry that answered for them, figures and
estimation back to the scripts that produced them.

`e2er verify <bundle>` re-establishes offline, with no API keys and in under a
minute, that the bundle is internally consistent and untampered: it re-hashes
every file against the manifest, recomputes the numbers, re-checks the
declared specification, and confirms every `\cite` resolves. `--online`
additionally re-queries the registries.

This is the reviewer's cheapest possible check, and it is the point. Generation
is nearly free; the aim is to make *verification* cheap too.

## 6 · What this does not establish

The distinction the whole design rests on:

**Verification** asks whether a paper's claims are faithful to the chain from
data through analysis and outputs into the manuscript. It is a question of
chain of custody, it has deterministic answers, and a machine settles it at no
cost. That is what everything above does.

**Robustness** asks whether the analysis was defensible. It has no
deterministic answer, and nothing above touches it. A paper can be perfectly
verified and still wrong — every number tracing, the specification
indefensible.

Three limits worth stating explicitly rather than leaving for a reader to
discover:

1. The contracts check that reported results **echo the declared design**, not
   that the script implements it. A faithful-looking report over a
   mis-specified estimator passes.
2. The citation gate establishes that a reference **exists and is cited**, not
   that it supports the claim attached to it.
3. The declared-specification sweep — reporting a curve over the neighbourhood
   of defensible specifications rather than a handful of robustness columns —
   is designed and not built.

Verification keeps AI-assisted research from getting worse. It is not what
makes it better.
