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

## What counts as the published result

- The target is the number as printed in the paper (or its online appendix):
  the coefficient, standard error, confidence bound, sample size, test
  statistic, or figure value the paper reports. Record it exactly as printed,
  with its page and its table or figure, column and row.
- A number that only exists in a results file the package ships is not a
  published target. Shipped results files are useful to locate things; the
  paper is the reference.
- If the paper reports a number only in a figure, record that the target is
  graphical and compare the figure's underlying data if the code writes it.
  Do not read values off a picture and treat them as exact.
- Never estimate, round up or fill in a target you could not find. List it as
  missing, with where you looked.

## Levels, per result

Each table or figure (or each headline number, when a table is large) gets one
level.

| Level | Rule |
|---|---|
| `reproduced` | The code ran and every compared number equals the published one at the published precision (rounding to the printed decimals gives the printed value). |
| `reproduced_minor` | The code ran; some numbers differ beyond rounding, but every difference is small (relative difference at most the template's tolerance, 10 % by default), no sign changes, and no conclusion the paper draws from the number changes (conventional significance level, direction, which estimate is larger). |
| `not_reproduced` | The code ran and produced the numbers, but at least one differs beyond the minor tolerance, changes sign, or changes a conclusion. |
| `could_not_run` | The code that produces the result failed, timed out, needed network access or data the package does not include, or wrote no output that holds the number. |

A result's level is its worst number. Name the reason in one sentence: which
number, how far off, and the likely cause if the logs show one (a package
version, a random seed, a missing file).

## Practical rules for running

- Run the package as its README says, from the folder it says, in the order it
  says. Do not edit the authors' code. If a script only fails because of an
  environment detail (a missing system library, a hard-coded path you can set
  as the working directory), fix the environment, never the code, and record
  what you did.
- Use the software versions the package documents. Where it names none, use the
  version current at the package's publication date and say so.
- Scripts that download data at run time cannot run in the sandbox (no network).
  Mark them `needs_network`, run everything that works from the included data,
  and level the results that depended on the download `could_not_run`.
- Randomness: if the code sets a seed, a difference is a finding. If it does
  not, say so; small differences in bootstrap or simulation results are then
  expected and belong in `reproduced_minor` when within the tolerance.
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
