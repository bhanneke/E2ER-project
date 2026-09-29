# Reproduction Protocol

Rules for rerunning a published study from its replication package. They follow
the distinctions the Institute for Replication uses and that mass-reproduction
studies apply (Brodeur et al., 2025): a result is checked with the authors' own
data and code first, and only then, separately, with other choices.

## Three kinds of check, kept apart

1. **Computational reproduction.** Same data, same code, same specification.
   Question: does running the package produce the numbers printed in the paper?
   This is what the `replication` template does.
2. **Robustness.** Same data, different analysis: another estimator, sample,
   control set, clustering, functional form. Question: does the result survive
   reasonable alternatives?
3. **Replication.** New data, same question. Question: does the finding hold
   elsewhere?

Do not mix them. A reproduction report says nothing about robustness, and a
failed robustness check is not a failed reproduction. If you notice something
that a robustness check should examine (a coding choice, an odd sample
restriction), write it down under "notes for a robustness study" and leave the
levels alone.

## Two levels of targets

Every target belongs to one of two levels, and they are reported separately.

- **Level 1 — the package's own results.** The target is a cell of a result
  file the package ships. The question is whether the code, run again,
  rebuilds its own results. The reproduced number is read from the rebuilt
  copy of the same file.
- **Level 2 — the published paper.** The target is a number printed in the
  paper, taken only from the paper, with its page. The question is whether the
  rerun reproduces what was published.

A study can pass level 1 and fail level 2 (the package's results are not the
paper's, e.g. a later version of the code) or the reverse. Neither level
stands in for the other: a number read from a shipped results file is never a
level-2 target, and a printed number is never a level-1 target.

## What counts as the published result

- For level 2, the target is the number as printed in the paper (or its online appendix):
  the coefficient, standard error, confidence bound, sample size, test
  statistic, or figure value the paper reports. Record it exactly as printed,
  with its page and its table or figure, column and row.
- A number that only exists in a results file the package ships is not a
  published target; it is a level-1 target. For level 2 the paper is the
  reference.
- The paper may come from the researcher (`paper/paper.pdf`, fingerprinted and
  recorded as researcher-supplied) when the publisher refuses automated
  downloads. Without it there are no level-2 targets.
- If the paper reports a number only in a figure, record that the target is
  graphical and compare the figure's underlying data if the code writes it.
  Do not read values off a picture and treat them as exact.
- Never estimate, round up or fill in a target you could not find. List it as
  missing, with where you looked.

## Labels, per number and per result

Every compared number gets a label by these rules, and nothing else decides
it. The reproduction check applies the same thresholds to the numbers it
re-reads and stops the run when a label disagrees with them.

Let *t* be the target, *r* the rerun value, and the relative difference
|r − t| / |t|.

| Label | Rule for one number |
|---|---|
| `reproduced` | Level 2 (a printed number): *r* rounded to the printed decimals is the printed value. Level 1 (a full-precision cell of a shipped file): relative difference at most 1e-9 (absolute 1e-12 when *t* is zero). |
| `reproduced_minor` | Not `reproduced`, same sign, and relative difference at most 10 % (the template's `minor_rel_tolerance`). |
| `not_reproduced` | Relative difference above 10 %, or the sign changes, or *t* is zero and *r* is not. |
| `could_not_run` | No number: the code that produces it failed, timed out, needed network access or data the package does not include, or wrote no output that holds it. |

A result (a table or figure at one target level) takes the label of its worst
number, in the order `reproduced` < `reproduced_minor` < `not_reproduced` <
`could_not_run`. A table can be `reproduced` at level 1 and `not_reproduced` at
level 2.

A 0.09 % difference is not `reproduced`, however small: at level 1 the rerun
must equal the shipped cell to nine significant digits. Whether a minor
difference changes a conclusion of the paper (significance, direction, which
estimate is larger) is a note, not a label.

## Reason texts

- Say what the numbers show: which number, the target, the rerun value, the
  relative difference. Never say "equals", "identical" or "at full precision"
  about a number that differs, and never say "differs" about one that is
  equal; the check compares the wording with the numbers.
- Causes are never established by a reproduction. Name them as possible
  causes only, with what points to them: "possible causes: DRDID is not
  pinned (1.3.0 installed); 07_did.R sets no seed before its bootstrap". Do
  not write "because", "due to", "caused by", "the reason is", "bug" or
  "mistake" as a finding; the check refuses a reason text that states a cause
  without "possible", "may", "might" or "could".
- Record the environment the rerun used from `sandbox_log.json`: the package
  snapshot date and repository, the platform, and the versions of the packages
  you discuss. Code records every installed version, dependencies included.
  Differences in it are among the possible causes.

## Practical rules for running

- Run the package as its README says, from the folder it says, in the order it
  says. Do not edit the authors' code. If a script only fails because of an
  environment detail (a missing system library, a hard-coded path you can set
  as the working directory), fix the environment, never the code, and record
  what you did.
- Use the software versions the package documents. Where it names none, use the
  versions current at the package's publication date: by default the sandbox
  installs R packages from the dated CRAN snapshot of the Zenodo record's
  publication date and Python packages uploaded before it, and a declared
  version always wins. Dependencies the package does not declare (e.g. a
  package's own dependencies) come from the same snapshot; all installed
  versions are recorded.
- Scripts that download data at run time cannot run in the sandbox (no network).
  Mark them `needs_network`, run everything that works from the included data,
  and level the results that depended on the download `could_not_run`.
- Randomness: if the code sets a seed, a difference is a finding. If it does
  not (e.g. a bootstrap without `set.seed`), say so as a possible cause; the
  label still follows the thresholds above.
- Keep every log. A level without the log that supports it is an opinion.

## Reporting

- Report every target, compared or not. A target you could not assess is listed
  with the reason, never dropped.
- State the reproduced number, the file it was read from, and the difference.
  The reproduction check re-reads each number from that file.
- Keep judgement and fact apart: the levels follow the rules above; anything
  else (what a difference might mean, what a robustness study should test) goes
  in the notes.
- Write plainly. No verdict adjectives ("fully", "successfully",
  "remarkably"); the level says it.
