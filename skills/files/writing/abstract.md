# Writing the Abstract

## When you write it, and from what

You write the abstract last. The paper is final when you start: it has been
drafted, reviewed and revised, and the abstract step hands you the final
`paper_draft.tex`, the headline result entries (the result values the paper's
own text cites) and what the reviewers said about the abstract. Write
`abstract.tex` from these. Every statement in the abstract is one the paper
makes, and every number is a value of the results files. The compiler puts
your abstract into the paper; the PDF, the report and the study page all show it.

`abstract.tex` holds one `\begin{abstract} ... \end{abstract}` environment and
nothing else: no `\title`, no `\documentclass`. Keywords go on a line inside
the environment, after the text.

**JEL codes (economics papers only) and keywords.** An economics paper gives
2 to 3 JEL codes after the keywords. A paper in any other field (astronomy,
climate, earth science, linguistics, public health, ...) has no JEL line: give
keywords only.

## What it says

A good abstract has five parts, usually one sentence each, in 100 to 150 words
(the check refuses more than 160):

1. **Context.** The phenomenon and why it matters, anchored in a concrete fact.
2. **Question.** What the paper asks, stated precisely.
3. **Design and data.** How the paper answers it: the data, the setting, the method.
4. **Finding.** What the paper found, in plain words, with one to three headline
   magnitudes in plain units ("22 percentage points", "about three times",
   "12.3 deaths per 100,000 people"). Give the finding the most space.
5. **Meaning.** What follows from the finding for the question, stated as far
   as the evidence carries it.

The finding is stated as a finding: "Gross enrolment rose by about 22
percentage points", never "We examine enrolment".

## Numbers in the abstract

Write one to three headline magnitudes, no more, each in plain units. Every
number must be a value of the results files at the precision you show, and it
gets its own source note on the line after its sentence, as everywhere in the
paper (`writing/cite-numbers-by-source`):

```latex
The median country records 12.3 deaths per 100,000 people.
% src: estimation_results.json#statistics.death_rate.median
```

Years, the base of a rate ("per 100,000") and the threshold that defines the
sample ("magnitude 5 and larger", "within 3 degrees") are not counted as numbers. Everything else
is: sample sizes, shares, ratios, estimates. Say the rest in words ("about
three times", "two-thirds", "most").

Never report a p-value, a confidence interval (no "95%", no "interval"), a
standard error, a Fisher-z or a test statistic. "No statistically significant
effect" is plain language and allowed.

## Null results and caveats

A null result leads with what the null means. Write "Calendar seasonality in
NFT returns is no larger than chance would produce" before any number, and
then say what that implies for the question.

A caveat gets at most one clause. The abstract does not list limitations; the
paper does.

Write "makes no causal claim" only where a reader could read the question
causally (a policy, a treatment, an exposure). A descriptive question about a
distribution needs no such sentence.

Use plain language: a reader outside the field must understand every word.
Name the method in words a general reader knows ("a difference-in-differences
comparison of reforming and non-reforming countries").

## How the abstract ends

The last sentence says what the study shows or what follows from it. It is not
a negation ("makes no causal claim", "does not identify", "none is causal") and
it has no "rather than".

## Constructions the check refuses

"rather than"; "X, not Y" ("patterns in the catalogue, not in the planet
population"); the mirrored "changed A; changed nothing about B"; and every
construction of the phrase check (`reasoning/anti-slop`): "not only X but
also Y", "not X but Y", "It is important to note", "Against this
background", "delve", "plays a crucial role". State the positive claim and stop.

## The check after you

A deterministic check reads `abstract.tex` when you finish: at most 160 words;
no p-values, intervals, standard errors, Fisher-z or test statistics; at most
three numbers, each one a value of the results; at least one sentence that
states a finding; a last sentence that is no negation and has no "rather
than"; none of the refused constructions. When it fails you are sent back once
with its reasons. Change what it names and keep the rest.

---

## Worked example: an empirical paper (NFT seasonality, e2er v1)

> The Halloween effect---systematically higher November--April returns
> relative to May--October---is the most robust calendar anomaly in equity
> markets, persisting across countries and centuries. We test whether this
> anomaly extends to non-fungible token (NFT) markets, which lack the
> institutional features commonly invoked to explain equity seasonality while
> preserving behavioral channels that operate through retail investor
> psychology. Using 35.8 million Ethereum-based NFT trades across eight
> platforms from 2017 to 2023, we find no statistically significant Halloween
> effect in either USD- or ETH-denominated returns. Two-thirds of the raw
> seasonal differential in USD returns comes from ETH price seasonality.
> Summer returns are twice as volatile as winter returns. Day-of-week effects,
> by contrast, are highly significant, suggesting that shorter-horizon
> calendar patterns dominate seasonal ones. The absence of a Halloween effect
> in a market without institutional investors, short selling, or exchange
> closures is consistent with institutional mechanisms playing a necessary
> role in sustaining the equity anomaly.
>
> Keywords: calendar anomaly, seasonality, cryptocurrency, behavioral finance.
> JEL codes: G12, G14, G41.

149 words; one counted number (35.8 million; the years 2017 and 2023 are not counted).

Sentence by sentence:

1. *The Halloween effect ... persisting across countries and centuries.*
   Context. It names the phenomenon, defines it in the same sentence and says
   why it matters (the most robust calendar anomaly). No citation, no number.
2. *We test whether this anomaly extends to NFT markets, which lack ...
   while preserving ...* The question, and why this market is the test: it
   removes the institutional explanations and keeps the behavioural ones. The
   reader now knows what each outcome would mean.
3. *Using 35.8 million Ethereum-based NFT trades ... we find no statistically
   significant Halloween effect ...* Data, scope and the headline finding in
   one sentence. The one number is the sample's size, in plain units. The
   null is stated in plain words, with no p-value.
4. *Two-thirds of the raw seasonal differential in USD returns comes from ETH
   price seasonality.* A second finding, as a magnitude in words. It says
   where the raw difference comes from. (The v1 paper wrote "reflects ETH
   price seasonality rather than NFT-specific patterns"; the positive claim
   alone says the same.)
5. *Summer returns are twice as volatile as winter returns.* A finding in
   eight words, the magnitude in words.
6. *Day-of-week effects, by contrast, are highly significant, suggesting ...*
   The contrast that gives the null its meaning: calendar patterns exist,
   at a shorter horizon.
7. *The absence of a Halloween effect in a market without ... is consistent
   with institutional mechanisms playing a necessary role ...* What follows
   for the question asked in sentence 2. It ends on a positive inference,
   hedged once ("is consistent with").

## Worked example: a descriptive study (road traffic deaths, e2er demo)

> Road traffic deaths are a major source of preventable mortality, and the
> reported burden differs sharply between countries. We ask how the World
> Health Organization's estimated road traffic death rate varies across
> countries and WHO regions in 2021. We describe the rate for 195 countries
> from the WHO Global Health Observatory and summarise it by region. The
> median country records 12.3 deaths per 100,000 population, and the average
> rate of the African region is about three times that of the European region.
> WHO region membership accounts for 39 percent of the variation between
> countries. Because the rates are WHO model estimates, comparisons between
> countries inherit the assumptions of WHO's estimation model.

111 words; three counted numbers (195, 12.3, 39), each with its `% src:` line in
`abstract.tex`; 2021 and "per 100,000" are not counted.

1. Context: why the rate matters and that it varies.
2. The question, as the study asks it.
3. Data and design: the source, the sample and what is computed. A description
   needs no method name beyond "describe" and "summarise".
4. The headline finding: the typical level and the largest regional contrast,
   one number and one ratio in words.
5. A second finding: how much of the variation the regions account for.
6. The one caveat, in one clause, stated as what it implies for the
   comparisons. There is no "makes no causal claim": the question is
   descriptive and cannot be read causally.

## Checklist

- [ ] 100 to 150 words (the check refuses more than 160)
- [ ] The question is stated
- [ ] Data and design in one sentence
- [ ] The finding is stated as a finding, in plain words
- [ ] One to three headline numbers, each a value of the results with its `% src:` line
- [ ] No p-values, intervals, standard errors, Fisher-z or test statistics
- [ ] A null result leads with what it means
- [ ] At most one clause of caveat; "no causal claim" only where the question could be read causally
- [ ] The last sentence is no negation and has no "rather than"
- [ ] No "X, not Y", no mirrored clauses, no constructions of the phrase check
- [ ] Keywords inside the environment; JEL codes only in an economics paper
