# Writing Review

**Paper:** *No Cash Flows, New Owners: Spot Bitcoin ETFs and the Origins of Co-movement*
**Paper ID:** e432cf3f-9008-4202-8ee6-ff09a93948ec
**Reviewer:** Writing Reviewer · **Date:** 2026-09-11
**Scope:** prose quality, argument flow, evidence–claim alignment, hedging, structure, consistency. Identification and estimation are reviewed elsewhere; where I raise a numerical point it is because the *prose* misstates what the sidecars report, not because I dispute the estimate.

---

## 1. Summary judgment

This is well-written economics. The voice is distinctive and controlled, the sentences are active, the hedging discipline is mostly right, and the paper does something rare: it reports the evidence that cuts against it — the BITO placebo larger than the treatment, the sign flip under the VIX interaction, the endogenous break landing on the halving — in the body, at full strength, rather than in a footnote. The `\paragraph{}`-led structure of §2 and §4 works. §7.3 ("What the control group is doing") is the best-constructed subsection in the paper.

The problem is not craft. It is that a paper whose entire rhetorical position is *we are more careful than the literature* contains a displayed equation that contradicts its own reported statistic, a superlative that is demonstrably false against its own robustness table, a variance-share number that confuses `E[ρ²]` with `(E[ρ])²`, a concluding sentence that rests on a quantity the paper elsewhere declines to measure, and a claim in the conclusion that directly contradicts the power section three pages earlier. Each is individually small. Together they are exactly the class of error a referee hunts for in a paper that claims this much methodological virtue, and finding them is disproportionately damaging here.

The second, softer problem is repetition of the honesty framing. I count roughly fifteen instances of the construction "we state X rather than Y" / "we pre-committed" / "the honest statement is." One or two are a strength; fifteen reads as protesting, and it is the single largest recoverable source of words.

None of this requires rewriting the paper. It requires one disciplined verification pass and one compression pass.

---

## 2. What works — preserve these

Listed specifically so the revision does not sand them off.

- **The narrowing of the cash-flow claim** (§1, ¶3): "We are careful about how far that claim reaches… What the setting shuts off is narrower than 'no fundamentals' and sharper than anything available in an equity cross-section: the cash-flow-news channel specifically." This is the right claim, correctly bounded, and it pre-empts the strongest referee objection (Froot–Dabora twin shares, which §2 then cites). Do not weaken it.
- **"The null is robust but the sign is not."** (§1). Six words carrying the paper's second-most-important qualification. Keep verbatim.
- **The Andrews demonstration** (§7.6): 140.41 → 6.39, "a twenty-two-fold reduction in the test statistic follows from correcting for a mechanical 29-of-30-day overlap." This is earned by the paper's own numbers and is the strongest methodological exhibit in the manuscript.
- **Active voice throughout.** I searched for "is estimated," "was found," "are shown," "it was." The hits are confined to methods descriptions where the agent is genuinely irrelevant ("Sixty-three fixed-effect parameters are absorbed," "Missing values are dropped rather than imputed"). This is correct usage. No action needed.
- **Magnitude discipline** in most places: "under two correlation points," "changes the equity-driven share of Bitcoin's monthly return variance by about one and a half percentage points," "beta runs roughly three times correlation."
- **Figure 7's caption** ("Error bars are… descriptive and are not the inference reported in the estimation tables"). Exactly the right caption discipline.

---

## 3. Priority 1 — claim accuracy and internal consistency

These change what a reader concludes. Fix all of them before the paper leaves the building.

**P1.1 — Equation (4) omits the `+1` in the numerator and therefore contradicts the reported p-value.** §6.4 displays
`p^RI = #{|τ̂^placebo| ≥ |τ̂|} / (#placebos + 1)`.
§7.2 reports the share at 0.663 and the p-value at 0.665. With 199 placebos, 0.663 × 199 = 132, and 132/200 = 0.660, not 0.665. The reported 0.665 = (132+1)/(199+1), i.e. the numerator includes the actual assignment. The displayed equation is missing that term. Fix the display to `(1 + #{·})/(1 + #placebos)`. A referee checking the arithmetic will land on this in under a minute, and it sits in the paper's most-defended section.

**P1.2 — "the largest clustered t-statistic anywhere in this paper" is false.** §7.7, on the log volatility ratio: −0.1128/0.0297 gives t = 3.80. But `subwindow_pre_halving` is −0.2613/0.0316 → t = 8.27, and the VIX×BTC interaction is +0.0100/0.0018 → t = 5.56. Both appear in this paper, both are larger, and both are discussed in §8. The claim fails even under the narrow reading "among treatment coefficients." Either delete the superlative or restate it precisely (e.g. "the largest clustered t-statistic among the three outcome variants in Table 9").

**P1.3 — the variance-share number in the conclusion is the wrong object.** §9: "At the sample mean correlation the equity-driven share of a coin's monthly return variance is 0.184." 0.184 is the *mean of ρ²* across the panel. At the sample mean correlation (ρ̄ = 0.3507) the share is ρ̄² = 0.123. §5.4 states it correctly ("the mean variance share across the panel is only 0.184"); §9 restates it incorrectly. Fix §9 to match §5.4: "The average equity-driven share of a coin's monthly return variance is 0.184."

**P1.4 — the allocator sentence contradicts §7.8.** §9: "An allocator who revised the correlation assumption upward by a tenth on the strength of the listing was acting on a magnitude this design would have detected and did not find." §7.8 states that with 80% power the design could only have detected 0.148. A true effect of 0.10 is *below* the MDE; the design would not reliably have detected it. What is true is that the realized randomization interval (upper bound +0.086) *excludes* 0.10. Those are different statements, and the paper is scrupulous about the distinction everywhere else. Rewrite: "…was acting on a magnitude our interval excludes, though not one the design was powered to detect."

**P1.5 — the paper's final sentence rests on a quantity the paper refuses to measure.** §9: "the products gathered enormous assets and Bitcoin's equity loading did not move, and the most economical explanation for that pair of facts is that a substantial share of those assets never represented directional exposure at all." §3 states plainly that no configured source serves AUM, flows, shares outstanding or NAV, and that turnover is "emphatically not net creations." The paper therefore cannot assert the first of "that pair of facts" from its own evidence. Two further problems in the same sentence: "did not move" drops the hedging the rest of the paper maintains ("no detectable change"), and "the most economical explanation" asserts a ranking over explanations the paper has not tested. Rewrite along these lines: "Published estimates put the complex's assets in the tens of billions (\citealp{guliyev2025from}); our estimate finds no detectable change in Bitcoin's equity loading over the same window. One explanation consistent with both — and the one our framework points to — is that a substantial share of those assets never represented directional exposure."

**P1.6 — "A study running any one of these specifications on Bitcoin alone would have reported a significant result" (§9) overreaches twice.** First, one Bitcoin-alone specification *is* reported in this paper — the descriptive raw gap in §7.3 — and it returns p = 0.946. "Any one of these" is therefore false as written. Second, the two specifications that do look positive return p = 0.074 (DCC) and p = 0.072 (per-asset returns): those are 10%-level, and §9 of this paper's own house style ("significant means statistically significant") makes the unqualified "significant" misleading. Rewrite: "A study running the DCC or the per-asset returns model on Bitcoin alone would have reported a marginally significant result, and it would have been reporting 2024." The final clause is excellent; keep it.

**P1.7 — the robustness count is wrong and the exception list is wrong.** §8.4: "Across the twenty robustness rows the point estimate is negative in nineteen and never exceeds 0.05 in absolute value except in the two sub-window rows and the two alternative outcomes." Against the delivered grid: there are 21 rows once the 60- and 90-day window rows are counted; two are positive (`ctrl_vix_move` +0.0195, `placebo_bito_2021` +0.0412), so it is nineteen of twenty-one, not nineteen of twenty. And of the three sub-window rows only one exceeds 0.05 (`subwindow_pre_halving`, −0.2613); `subwindow_pre_election` is −0.0439 and `subwindow_post_election` is −0.0066. The true exception set is three rows, not four. Recount and restate.

**P1.8 — "roughly a third the width of the valid ones" holds for one of the two.** §7.2: clustered width 0.0767; randomization width 0.2428 (ratio 0.32 ✓); Conley–Taber width 0.1451 (ratio 0.53). The plural overclaims. Fix: "roughly a third the width of the randomization interval and half the width of the Conley–Taber interval."

**P1.9 — §6.6 is titled "What we specified and could not estimate" and is materially incomplete.** It reports three unestimable designs. The econometric specification lists at least six: the session DDD ✓, the flow dose–response ✓, the false-news placebo ✓, plus the staggered multi-cohort extension, the prior-halving placebo (F5), the synthetic-control companion, and Rambachan–Roth breakdown values (for which the randomization interval is substituted). The prior-halving placebo is the most damaging omission, because §6.3 identifies the halving as the design's binding residual confound and §7.6 dates the only clear 2024 break two weeks after it — a reader is entitled to know that the placebo which would test this directly was specified and is out of coverage. Rambachan–Roth is also never mentioned, though the identification strategy required its breakdown value to be the number quoted in the text. In a section whose entire purpose is completeness, three-of-six reads badly. Expand to the full list with one clause of reason each.

**P1.10 — "the bar binds" is the wrong verb.** §7.8: "Our pre-analysis committed to a bar, and the bar binds." The pre-analysis specified two thresholds (≤0.10 licenses a null claim; >0.20 forbids one) and the realized MDE of 0.148 falls in the gap between them — a region for which no rule was specified. Nothing binds; the criterion is silent, and the authors are interpolating. Say so: "Our pre-analysis set two bars, and the realized value falls between them, in a region the pre-analysis did not specify a rule for. We therefore state the finding as follows…" This is a stronger position than the current one precisely because it is more exact.

**P1.11 — "the asymptotic test rejects for every coin, treated or not" (§7.4) is not supported by the reported statistics.** The paper gives the placebo median (17.36) and maximum (84.30) but not the minimum, so the reader cannot verify that *every* placebo rejects. Report the minimum placebo F, or the share of placebos exceeding the critical value, or soften to "rejects for nearly every coin."

**P1.12 — "it agrees with the panel estimate in sign and is of the same order once scaled" (§7.5) asserts commensurability without showing it.** The DDD is −0.0798 in returns-level loading units; the panel estimate is −0.0212 in Fisher-z. "Once scaled" how? This sentence is doing real work — it is the paper's defence against the generated-outcome critique — and it currently asks the reader to take the comparability on faith. Supply the one-line conversion or drop the "same order" claim and rest on the sign agreement alone.

**P1.13 — "Five further estimators agree" (§1) is looser than the body warrants.** The DCC returns a *positive* point estimate with asymptotic p = 0.074 and only becomes a null once the control-pair distribution is applied — which is precisely the paper's point, and it is made well in §7.5. The intro flattens it. Rewrite: "Five further estimators find no Bitcoin-specific change once a control group is applied — including one, a DCC–GARCH, that reports a significant positive shift when fitted to Bitcoin alone."

---

## 4. Priority 2 — structure and flow

**P2.1 — the abstract is roughly 420 words.** Most target journals cap at 100–200. It currently carries the design, the point estimate, the p-value, the randomization interval, six estimators, three qualifications, the MDE, the pre-specified bar and the interpretation. Cut to ~180 by keeping: the event and why it identifies a clientele effect; the design in one sentence; the estimate with its randomization p and interval; the power bound; the one-sentence reading. Move the three qualifications to the introduction, where they already appear in fuller form.

**P2.2 — "half that magnitude" is ambiguous and inconsistent across three statements.** The abstract says "cannot rule out an increase of half that magnitude" (half of 0.086? of 0.148?); §1 says "cannot rule out an increase of half that size"; §7.8 says "It does not rule out an increase of 0.05." Half of 0.086 is 0.043, not 0.05. State the number in all three places and make it the same number.

**P2.3 — five results subsections open with inventory sentences rather than claims.** §7.2 "Table 3 reports the headline specification and four companions." §7.4 "Table 5 reports the binned event study." §7.5 "Tables 6, 7 and 8 report…" §8.1 "Table 11 varies the construction of the sample." §8.2 "Table 12 varies the equity leg…" Apply the first-sentence test: a reader reading only opening sentences currently learns the table inventory, not the argument. §8.3 shows the fix ("Table 14 reports the placebo grid, **and it is where the choice of inference procedure does the most visible work**"). Lead with the finding, point to the table second.

**P2.4 — §9's first two paragraphs restate §7.4–§7.5 with little new.** "every crypto asset's equity beta fell and every crypto pair's conditional correlation target rose" (§9) duplicates §7.5; "Three conventional tests in this paper reject at conventional levels… all three are artifacts" duplicates §7.4 and §7.6. The genuinely new material in §9 — the allocator translation, the two readings of the null, the scope conditions, the three follow-up questions — starts in paragraph three. Compress paragraphs 1–2 into one and give the recovered space to the allocator paragraph, which is currently the thinnest part of the section and the part practitioners will read.

**P2.5 — §6.3 announces two threats and delivers three.** "Two threats deserve to be stated here rather than deferred" … then "A third consideration is exchangeability." Either say three, or mark exchangeability explicitly as a different category ("Exchangeability is not a threat in the same sense, but…").

**P2.6 — §2's first and third paragraphs are annotated bibliographies, not arguments.** The crypto paragraph runs nine consecutive citation-led sentences ("\citet{liu2020risks} establish… \citet{liu2022common} reinforce… \citet{biais2023equilibrium} supply… \citet{hu2019cryptocurrencies} document… \citet{makarov2019trading} document… \citet{griffin2020is} establish…"). The ETF paragraph is much better because it has a thesis (the Israeli/Glosten tension resolving into a shift from idiosyncratic to systematic informativeness). Restructure the crypto paragraph the same way: two or three claim-led sentences with citations in support. The first paragraph is also eleven sentences; split it at "The subsequent literature works to close off the fundamentals channel."

**P2.7 — two literatures the paper needs are absent.** §4 opens "in the spirit of the investor-recognition tradition" with no citation; that tradition is Merton (1987) and the framework is a direct application of it. And the commodity-financialization strand — Tang–Xiong, Basak–Pavlova, Henderson–Pearson–Wang, and above all Cheng–Xiong, whose argument that index-flow effects are overstated relative to common macro shocks is *the* objection this paper's month fixed effects and control group are designed to answer — appears nowhere in §2. This is the closest structural analogue to the setting, and a referee from that literature will open with it. Add a fourth `\paragraph{}` to §2 and cite Merton in §4.

**P2.8 — no econometric method is cited.** Bai–Perron, Andrews sup-Wald, Conley–Taber, Bertrand–Duflo–Mullainathan, Engle's DCC, Newey–West and Rambachan–Roth are all named by author in the text with no `\citep{}`. Naming a method by its authors without a citation is a referee flag in itself.

---

## 5. Priority 3 — sentence level, conciseness, register

**P3.1 — pipeline register leaks into the manuscript.** These phrases belong to an internal handoff, not a journal submission:
- "not available in this build" (§3 figure caption, §4)
- "No configured data source in this project serves fund-level creations…" (§3)
- "the full delivered panel" / "the end of the delivered panel" / "The delivered daily crypto series" (§5.2, §7.1, §8.1)
Replace with plain statements: "We do not have fund-level creation and redemption data"; "in the full panel"; "the daily crypto series we use."

**P3.2 — the honesty framing is repeated about fifteen times.** A representative sample: "we state the coverage rather than imply completeness" (§3); "We flag that gap… rather than substituting a proxy for it" (§3); "so that the reading is visible as a commitment rather than as a rationalization" (§4); "Two control coins carry caveats we state rather than bury" (§5.3); "the choice is reported rather than hidden" (§5.1); "we state them rather than substituting proxies" (§6.6); "Two threats deserve to be stated here rather than deferred" (§6.3); "We state this because it cuts against our own finding" (§6.3); "we state them in the introduction rather than letting them emerge in the robustness section" (§1); "The honest statement is therefore…" (§1); "a statement about precision that we would rather make ourselves than leave to a referee" (§8.2); "We report it because we committed to reporting it" (§7.2). Keep the disclosure, delete the announcement of the disclosure. "Two control coins carry caveats we state rather than bury" → "Two control coins carry caveats." The reader can see you are stating it; you are stating it. This alone recovers several hundred words and lowers the defensiveness of the voice.

**P3.3 — one sentence is duplicated near-verbatim.** §5.6: "we pre-committed to reporting every estimated break date whether or not it flatters the hypothesis." §7.6: "We pre-committed to reporting every estimated break date whether or not it flattered the hypothesis, and this one does not." Keep the second; cut the first to "…and we report every estimated break date."

**P3.4 — body text duplicates figure captions.** §7.1: "Rolling windows overlap by construction, so a genuine level shift would appear as a 90-day ramp rather than as a jump; these panels display the time path and are not the estimation object." Figure 5 caption: "Rolling windows overlap by construction, so a true level shift appears as a 90-day ramp rather than a jump. These panels show the time path and are not the estimation object." Pick one. Captions should complement the text, not restate it.

**P3.5 — banned/throat-clearing constructions.**
- §7.1 "Two features are worth noting before any estimate." → "Two features precede any estimate:" or state them directly.
- §7.3 "It is worth seeing how much work the control group and the month fixed effects perform, because the answer is unusual." → "The control group and the month fixed effects do unusual work here."
- §3 "it is worth separating the changes from the non-changes because…" → "Separating the changes from the non-changes matters because…"
- §3 "it is emphatically not net creations" → drop "emphatically"; the sentence is stronger without it.

**P3.6 — "falls by −X" is wrong four times.** A quantity that *falls* falls **by** a positive amount.
- §7.5 "Bitcoin's equity loading fell by $-0.4148$" → "fell by 0.4148" (or "changed by −0.4148").
- §7.5 "the never-treated control coins' loadings fell too, by $-0.3221$ on average" → "by 0.3221 on average."
- §7.7 "The log volatility ratio falls by $-0.1128$" → "falls by 0.1128."
- §7.7 "monthly beta… falls by $-0.1890$" → "falls by 0.1890."

**P3.7 — "brackets" is the wrong verb, used twice.** §1: "two weeks after the April halving, which it brackets far more plausibly than it does the January listing." §7.6: "whose date it brackets far more plausibly than it does the ETF's." A single break date does not bracket anything. Use "dates" or "is far more plausibly picking up."

**P3.8 — "data" is treated as singular four times.** "not estimable on this data" (§6.6); "could have been produced from this same data" (§1 and §8.2); "On this data the answer is…" (§9). The paper gets it right elsewhere ("the data do not contradict the ordering; they do not support it either"; "the data think the break is"; "All price data are daily bars"). Economics journals still enforce the plural. Also "on this data" is unidiomatic regardless: "in these data."

**P3.9 — long sentences with wide subject–verb separation.** §1, sentence 2: "An asset that US wealth-management channels could previously reach only through a futures wrapper carrying roll costs, through a closed-end trust that had spent two years at a deep discount to its own net asset value, or by opening an account at a crypto exchange and arranging self-custody, became a line item with a CUSIP, a daily net asset value, ordinary brokerage custody, margin eligibility, and a path into model portfolios." Sixty-eight words, forty of them between "An asset" and "became." Split at the verb: "Before January 2024, US wealth-management channels could reach Bitcoin only three ways: … After it, Bitcoin was a line item with a CUSIP…" Same content, half the parsing cost, and the before/after structure reinforces the paper's argument. Similar treatment for §3: "Ten of the eleven are retrievable in our price data; the eleventh… is not, and every aggregate we report covers ten of eleven funds rather than the full complex."

**P3.10 — the swipes at unnamed prior work recur.** "a paper that wrote 'Bitcoin became a risk asset' off a correlation of 0.4 would be overstating by a wide margin" (§5.4); "Any study that runs a break test on a rolling-window series without a HAC correction is reporting an artifact" (§7.6); "A study running any one of these specifications on Bitcoin alone would have reported a significant result" (§9); "a paper claiming a positive ETF effect of this magnitude could have been produced from this same data" (§8.2). The second is earned — the paper produces the 140.41 → 6.39 demonstration itself. The others are strawmen, and cumulatively they read as scolding. Keep the Andrews one; neutralize the rest into positive statements about what this paper does.

**P3.11 — addressing referees inside the manuscript.** "A referee will reasonably observe that Yahoo's crypto quotes are…" (§5.1); "we would rather make ourselves than leave to a referee" (§8.2); "report the conventional column only because referees expect it" (§1). Three instances. The first can simply become the substantive statement ("Yahoo's crypto quotes are a cross-venue aggregate with no published methodology, and history is revised silently"). Keep at most one.

---

## 6. Priority 4 — consistency and copyedit

- **"calendar-month fixed effects" is ambiguous** and invites the month-of-year reading. Used in the abstract, §1 and §6.2. Say **year-month** fixed effects, or "calendar year-month (e.g. 2024-02)."
- **Post-period end date conflicts.** Figure 7's caption says the post-period is "2024m2--2026m8"; §7.1 and §8.1 say the panel ends 2026m7. Fix the caption.
- **Donut start date conflicts.** §1 and Figure 5's caption date the donut from "the August 29, 2023 Grayscale ruling"; §6.1 defines it as "2023m8 through 2024m1," i.e. from 1 August on a monthly panel. Twenty-eight days apart. Add one clause reconciling them, and shade the figure to match the estimation window.
- **ETP vs ETF.** The title and keywords say ETF; §1 and §3 say "exchange-traded products"; §8 says "spot-ETF." Define the term once in §3 ("we use ETF throughout for these exchange-traded products") and use it consistently.
- **Percent formatting is mixed.** "80\%" and "95\%" (abstract, §6.4) vs. "eighty percent," "five percent," "ten percent," "fifteen percent" (§6.5, §7.8). Pick one and apply it.
- **Small numbers mixed.** "540 coin-months across 10 coins" (§7.2, digits) vs. "nine coins" / "nine donors" / "ten of eleven funds" (spelled). Numbers ≤ ten should be spelled consistently.
- **Date formats mixed within one paragraph.** §7.6 runs ISO break dates ("2022-04-11, 2023-01-30, 2024-05-02") against prose dates ("the April 19--20 halving," "the January listing") in adjacent sentences. Convert the break dates to the paper's prose format.
- **Serial comma is inconsistent.** Present: "hashrate, halvings, on-chain activity, exchange failures, and a regulatory environment…"; "a Fed easing cycle, a US election…, a tariff episode, and a Bitcoin halving." Absent: "the issuance schedule, the block interval, the protocol and the continuously traded global spot market"; "custody, operational risk, mandate restrictions, tax reporting and career risk"; "co-movement, ETFs and crypto asset pricing." Choose one.
- **Terminology for the randomization floor varies.** "a coarsest attainable two-sided p-value of 0.10" (§6.4 — and "coarsest" is the wrong word; the point is that 0.10 is the *smallest attainable* value), "the smallest attainable randomization p-value is 0.10" (§7.7), "the floor imposed by nine donors" (§8.2), "one step above the floor" (§7.7). Standardize on one phrase and use it everywhere.
- **`\paragraph{}` heading style is inconsistent.** §2 and §4 use noun phrases ("Co-movement without fundamentals.", "The basis-trade wedge."); §8 uses full declarative sentences ("The macro-confounding specification is the substantively important row, and it does not behave as we anticipated."). Pick one convention.
- **§5.4 promises more than the prose delivers.** "We also report ρ² beside every correlation." In prose it is delivered once (§7.2's variance-share translation); §7.3 and §7.7 quote correlations and Fisher-z values without it. If the tables honor the promise, say "in every table"; if not, honor it or drop the claim.
- **Robustness-row reporting is not uniform.** Gold, silver and BITO get clustered *p*-values in the prose; `leg_acwx_non_us` (clustered p = 0.008), `outcome_ln_sigma_ratio` (0.004) and `excl_extreme_news` (0.061) get only the randomization p. Since §9's "three conventional tests reject" argument depends on exactly this pattern, reporting it selectively looks like curation. Decide which statistics accompany each row in prose and apply the rule uniformly — and consider whether §9's count should be "at least three."
- **§9's "three conventional tests reject" undercounts.** By the clustered column at least six robustness rows reject at 5%. The point is stronger, not weaker, if stated accurately.
- **JEL codes are out of order.** "G12, G14, G23, G11" → G11, G12, G14, G23.
- **"a shift of this size… changes the equity-driven share… by about one and a half percentage points"** (§7.2). The arithmetic in the source comment gives 1.35 pp. "About one and a third" or "about 1.4" is more accurate, and in a paper this exacting the rounding-up is noticeable.
- **"the noise level is five times the actual estimate"** (§8.3) uses the 90th percentile of the absolute placebo distribution (5.12×), not the standard deviation (2.93×). A reader will assume the SD. Name the statistic.
- **"The design is unbiased under the null"** (§8.3) overstates what a placebo mean of 0.00011 shows. "Shows no detectable bias" is the supportable claim.
- **§7.7's beta arithmetic uses the panel-mean beta (≈1.69), not Bitcoin's pre-period beta (≈1.23),** to check that −0.1128 in log volatility ratio implies ≈ −0.189 in beta. The check works at 1.69 and not at 1.23. Say which beta the arithmetic uses.
- **"both have had exchange-traded wrappers for two decades"** (§5.3): GLD 2004 ✓; SLV 2006, closer to eighteen years. "For close to two decades" is exact and costs nothing.
- **Table source ordering in §7.5** does not match discussion order: the DDD is discussed two paragraphs before `returns_ddd.tex` is input, and `returns_interacted.tex` is input before its discussion. Reorder the `\input` calls to follow the prose.
- **Label/filename mismatch to verify at build:** the text references `Table~\ref{tab:ddd}` but inputs `tables/returns_ddd.tex`, and references `Table~\ref{tab:macro}` while inputting `tables/macro_controls.tex`. Confirm the labels inside those files match.
- **Title spelling** is "Co-movement" here and "Comovement" in the companion documents. Harmonize before submission.

---

## 7. Verification checklist for the revision

Work through these against the sidecars, in this order:

1. Equation (4): restore the `+1` in the numerator; re-verify 0.663 / 0.665.
2. §7.7: recompute all clustered t-statistics and delete or correct the superlative.
3. §9: replace 0.184 with the correct object; fix the allocator/MDE contradiction; source or reframe the AUM claim; correct "any one of these specifications."
4. §8.4: recount the robustness rows, the number positive, and the set exceeding 0.05.
5. §7.2: split the interval-width comparison into its two components.
6. §6.6: expand from three unestimable designs to the full set.
7. §7.4: report the minimum placebo F.
8. Global search and fix: "falls by −", "this data", "brackets", "in this build", "delivered panel", "worth noting/seeing/separating".
9. Reconcile the donut start date and the post-period end date across body, captions and figures.
10. Add Merton (1987), the financialization strand with Cheng–Xiong as the named antagonist, and citations for every named econometric method.

---

## 8. Assessment

The prose is genuinely good and the paper's willingness to publish its own counter-evidence is its best feature. What holds it back is that the manuscript's credibility rests on precision, and roughly a dozen statements do not survive checking against the paper's own numbers — including one displayed equation, one superlative, one variance-share, and one sentence in the conclusion that contradicts the power section. These are all local fixes, none requiring new analysis, but there are enough of them, and they sit in prominent enough positions, that the paper should not go out before a systematic verification pass. The compression work (a 420-word abstract, fifteen honesty announcements, a conclusion that restates the results section) is straightforward and would improve the paper's force, not just its length.

OVERALL SCORE: 7/10
RECOMMENDATION: Major Revision
