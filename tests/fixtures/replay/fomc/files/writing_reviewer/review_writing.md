# Writing Review: Bank Stock Response to FOMC Target-Rate Announcements

**Paper Title**: How Do US Bank Stocks Respond to Federal Reserve Target-Rate Announcements? An Event Study of FOMC Decisions, 2015–2025

**Review Date**: 2026-09-29

**Reviewer Focus**: Academic writing clarity, argument flow, evidence-claim alignment, and economics-specific conventions

---

## Executive Summary

The paper is technically sound and generally well-written, with clear methodology and transparent reporting of null results. The core research question is well-motivated, the event-study design is appropriate, and the results are properly hedged given the non-significant findings. However, the manuscript exhibits repetitiveness in key passages, wordiness in critical sentences, and proportional imbalance between the literature review and empirical contribution. These are addressable issues that do not compromise the work's scientific integrity but would improve readability and impact.

**Recommendation**: Minor Revision

---

## Detailed Findings by Dimension

### 1. Clarity

**Strengths:**
- Research question is stated plainly: "How do US bank stocks respond to Federal Reserve target-rate announcements?"
- Technical terms (CAR, market model, abnormal return) are defined before use
- Results are reported with specific numbers and p-values (e.g., "mean CAR of −1.06%, p = 0.0603")

**Issues Identified:**

**Issue 1.1: Wordy opening sentences**
- Location: Introduction, paragraph 1
- Text: "Since the global financial crisis of 2007–2008, central banks have deployed unconventional policy measures and maintained near-zero rates for extended periods, making the timing and magnitude of rate decisions pivotal for asset valuations."
- Problem: "pivotal for asset valuations" is vague. What does "pivotal" mean here? Affects pricing? Affects returns? Affects volatility?
- Revision: "making the timing and magnitude of rate decisions critical drivers of asset prices."

**Issue 1.2: Vague pronoun reference**
- Location: Introduction, final paragraph
- Text: "This null finding is itself informative: it suggests that either (1) markets have already priced in the rate move before the announcement, (2) the announcement-day reaction is too noisy relative to the cross-sectional variation in bank returns for the effect to reach statistical significance, or (3) the offsetting forces of NIM compression and credit-risk reduction genuinely cancel in expectation."
- Problem: "This null finding" is clear, but the three-part clause is dense and hard to parse on first read. The second interpretation especially is convoluted.
- Revision: Split into sentences. "The null finding suggests that announcement-day effects may be undetectable for one of three reasons. First, markets may incorporate expected Fed moves into prices before the announcement occurs. Second, cross-sectional variation in bank returns (standard deviation ~2.5–3%) may be large relative to the mean effect, reducing statistical power. Third, offsetting economic forces—NIM compression balanced by reduced credit-risk expectations—may cancel in expectation."

**Issue 1.3: Imprecise institutional description**
- Location: Institutional Context and Mechanism section
- Text: "The Federal Reserve's policy instrument is the federal funds rate, the rate at which banks lend reserve balances to each other overnight. The Fed does not directly set this rate; instead, it sets a target range and uses open-market operations to keep the rate within that range."
- Problem: Correct but could be more direct.
- Revision: "The Fed targets the federal funds rate—the overnight rate banks lend reserves to each other—by setting a target range and conducting open-market operations."

**Issue 1.4: Unclear distinction in results**
- Location: Results section, H2 paragraph
- Text: "The pooled regression of CAR_{[-1, +1]} on the day-0 change in the 2-year Treasury yield (in basis points), estimated over all 31 events with HC1 standard errors, yields a coefficient of −0.0208 with a standard error of 0.0437."
- Problem: Clear enough, but "day-0 change" could be more explicit: "the same-day change (from t=−1 to t=0)."

---

### 2. Argument Flow

**Strengths:**
- Introduction-to-conclusion arc is logical: question → literature → methods → results → interpretation
- Each section has a clear purpose and transitions into the next
- The "Interpretation of Results" subsection under Discussion explicitly addresses why effects might be null

**Issues Identified:**

**Issue 2.1: Disproportionate literature section**
- The literature review occupies substantial space (5 major subsections: FOMC announcements, financial sector specificity, rate hikes vs. cuts, bank-specific responses, and heterogeneous responses) relative to the empirical contribution (two hypothesis tests, 31 events, two event windows).
- The paper could be tightened by condensing the literature review to 2–3 pages and letting the empirical results occupy more space.
- Recommendation: Consolidate "FOMC Announcements and Equity Market Reactions" (1.1, 1.2, 1.3) into a single subsection; move section 4 on heterogeneous responses to a brief mention in the discussion as motivation for future work.

**Issue 2.2: Disconnected "Future Research" section**
- Location: Discussion, final subsection
- Text: "Two specific questions warrant future investigation. First, do longer event windows reveal cumulative effects? Our 3-day and 6-day windows may be too short to capture the full adjustment if market participants gradually process the implications of the rate decision over days or weeks. Event studies with 20-day or 60-day windows (common in the literature) would test this. Second, what drives the heterogeneity in abnormal returns?"
- Problem: This section feels like leftover material rather than a natural conclusion to the empirical analysis. The second question (heterogeneity) is underdeveloped and not clearly motivated by the findings.
- Recommendation: Integrate the first question (longer windows) into the discussion of the [0, +5] secondary result. For the second question, either develop it more thoroughly or move it to a separate "Limitations and Next Steps" section.

**Issue 2.3: Repetition of key claim**
- The statement "not statistically significantly different from zero" appears in multiple forms:
  - Abstract: "not significant at the 5% level"
  - Introduction: "not statistically significantly different from zero"
  - Results: "not significant" and "This result is not significant at the conventional 5% level"
- This repetition dulls the impact. Use varied phrasing: "fails to reject the null," "lacks statistical significance," "does not significantly differ from zero," "is indistinguishable from zero at the 5% level."

---

### 3. Evidence-Claim Alignment

**Strengths:**
- Claims about magnitude are supported by reported numbers (e.g., "−1.06% mean CAR")
- Causal language is avoided; the paper uses "respond to," "associated with," and "correlate with"
- Null results are accurately described: "not significant at the 5% level" rather than "we find no evidence that the policy affects bank stocks"
- Confidence intervals are reported alongside p-values

**Issues Identified:**

**Issue 3.1: Claimed consistency with theory not fully supported**
- Location: Discussion, first paragraph
- Text: "Rate hikes compress the net interest margin (negative for bank profitability) but may reduce expected future credit losses (positive). Rate cuts expand the margin but increase credit risk. If these forces balance, the net effect on bank valuations would be zero."
- Problem: The paper does not provide direct evidence that these forces balance. The null result is consistent with this hypothesis but does not prove it.
- Revision: "This pattern is consistent with the hypothesis that rate hikes compress the net interest margin (negative) but reduce expected credit losses (positive); rate cuts have opposite effects. If these forces offset, the net announcement-day effect would be zero. However, our data cannot isolate the separate contributions of each channel."

**Issue 3.2: Secondary result framing**
- Location: Abstract and Results
- Text: "A secondary analysis of the longer [0, +5] window (not pre-registered) shows a pooled mean CAR of −1.47% (p = 0.022), significant at the 5% level."
- Problem: The labeling is correct ("not pre-registered"), but this result appears to contradict the H1 finding (no significant effect in the narrow window). The paper should clarify that this suggests cumulative effects over days 0–5, not a same-day announcement effect.
- Revision: "We examine a longer post-announcement window [0, +5] (not pre-registered) as a sensitivity check. This window yields a pooled mean CAR of −1.47% (p = 0.022), suggesting that cumulative effects may emerge over the week following the announcement, though this result was not part of the pre-registered hypothesis test."

**Issue 3.3: Claimed contribution vs. actual contribution**
- Location: Introduction, last paragraph
- Text: "Our contribution is methodological and empirical. First, we provide systematic event-study evidence of bank stock abnormal returns around FOMC rate announcements over a recent decade (2015–2025), documenting that announcement-day effects in a tight 3-day window are not statistically significant for either hikes or cuts."
- Problem: This frames a null result as a "contribution" in a way that may be overstated. A null result is valuable if it challenges an expected finding, but the paper does not clearly state what the prior expectation was.
- Revision: "Our empirical contribution is to document, over a comprehensive 10-year period (2015–2025), that announcement-day abnormal returns in bank stocks are not statistically significant in a 3-day window centered on FOMC rate announcements. This finding contrasts with theoretical predictions of large NIM-driven responses and suggests either that markets incorporate expected policy moves before announcement, that offsetting economic forces cancel, or that statistical power is limited by cross-sectional variation in returns."

---

### 4. Hedging Language

**Strengths:**
- Appropriate use of "suggest," "consistent with," "may," and "could"
- Null results are properly described as "not significant" rather than "prove no effect"
- The paper acknowledges uncertainty in interpretations: "One possibility is..." "A second possibility is..."

**Issues Identified:**

**Issue 4.1: Over-hedging in methodology**
- Location: Data and Event Study Design, subsection on Estimation Window
- Text: "For each event i, we use a window of 238 trading days, specifically t ∈ [−250, −12] relative to t = 0 for each event. This window provides stable parameter estimates while maintaining a 12-day gap before the event window to avoid contamination from pre-announcement leakage."
- Problem: Acceptable hedging, but the phrase "provides stable parameter estimates" is hedged without stating what "stable" means (e.g., R² > 0.85, parameter variation < 10%?).
- Revision: "A 238-trading-day window provides stable market model parameters (median R² = 0.88) while maintaining a 12-day gap to isolate announcement-day effects from pre-announcement drift."

**Issue 4.2: Under-hedging in interpretation**
- Location: Discussion, "For practitioners" paragraph
- Text: "An investor seeking to profit from the expected effect of a rate decision on bank valuations would do better to wait and observe broader macroeconomic developments (credit growth, deposit flows, loan loss provisions) rather than trading on the announcement itself."
- Problem: This is a strong claim not directly supported by the data. The paper shows announcement-day effects are not significant, but does not examine whether longer-horizon strategies are profitable.
- Revision: "These results suggest that announcement-day price reactions in bank stocks are not large enough to support short-term trading strategies based solely on the announcement; market participants may benefit from monitoring post-announcement developments (credit growth, deposit flows, loan loss provisions) as better indicators of bank profitability."

---

### 5. Passive Voice

**Strengths:**
- Generally strong use of active voice throughout
- "We conduct," "we examine," "we estimate" are used consistently
- Methods are mostly stated actively: "We estimate the market model" rather than "the market model is estimated"

**Issues Identified:**

**Issue 5.1: Unnecessary passive constructions**
- Location: Market Model Specification section (equation 1)
- Text: "The abnormal return for event i on trading day τ within an event window is then:"
- Revision: "We then calculate the abnormal return:"

**Issue 5.2: Passive voice in results**
- Location: Results section, Hypothesis 1 paragraph
- Text: "This result is not significant at the conventional 5% level."
- Revision: "We fail to reject the null hypothesis at the 5% level."

---

### 6. Paragraph Structure

**Strengths:**
- Most paragraphs begin with a topic sentence that signals the paragraph's main point
- Paragraphs are generally well-formed (3–7 sentences)
- Results paragraphs are organized logically (test statistic, then p-value, then confidence interval)

**Issues Identified:**

**Issue 6.1: Very long paragraph in Institutional Context**
- Location: Institutional Context and Mechanism, final paragraph
- Text: The paragraph beginning "A second channel is credit risk..." extends to 6 sentences covering three separate transmission channels (credit risk, asset valuations, financial stability).
- Problem: Combines three ideas, should be split.
- Revision: Create three separate paragraphs, one per channel, each with a single idea and supporting evidence.

**Issue 6.2: Topic sentence missing**
- Location: Results section, Hypothesis 2 paragraph
- Text: Begins directly with the regression results rather than a topic sentence.
- Revision: Begin with "Hypothesis 2 examines whether abnormal returns correlate with the magnitude of Treasury yield surprise. The pooled regression yields..."

---

### 7. Conciseness

**Strengths:**
- Generally avoids filler phrases ("in order to" → "to," "due to the fact that" → "because")
- Sentences are mostly direct (e.g., "Rate hikes yield a mean CAR of −1.06%")

**Issues Identified:**

**Issue 7.1: Wordiness in key summary sentence**
- Location: Introduction, main finding paragraph
- Text: "Our main finding is straightforward: in the pre-registered three-day window centered on FOMC announcements, the mean cumulative abnormal return is not statistically significantly different from zero for rate hikes (−1.06%, p = 0.0603) or rate cuts (−0.08%, p = 0.9295)."
- Problem: "not statistically significantly different from zero" is wordy.
- Revision: "The mean cumulative abnormal returns are statistically insignificant: −1.06% for rate hikes (p = 0.0603) and −0.08% for rate cuts (p = 0.9295)."

**Issue 7.2: Redundant phrase**
- Location: Introduction and Results (multiple places)
- Text: "not statistically significantly different from zero" appears 4 times
- Problem: Repetition weakens impact
- Revision: Use varied phrasing: "fail to reject the null," "lack statistical significance," "indistinguishable from zero," "not significant at the 5% level"

**Issue 7.3: Overly complex relative clause**
- Location: Related Literature section
- Text: "Prior work has documented that monetary policy surprises—deviations between expected and actual policy moves—do move equity prices, with the effect differing across asset classes (stocks with high leverage and long duration of cash flows respond more than defensive equities, for example)."
- Problem: The parenthetical is too long and complex.
- Revision: "Prior work has documented that monetary policy surprises move equity prices, with effects differing across asset classes. Stocks with high leverage and long duration (such as banks) respond more than defensive equities."

**Issue 7.4: Unnecessary throat-clearing**
- Location: Conclusion, opening sentence
- Text: "We conduct an event study of 31 FOMC target-rate announcements from December 2015 through December 2025 to examine abnormal returns in the KBE banking sector ETF."
- Problem: This is a summary of what the reader has already read. The conclusion should move forward, not backward.
- Revision: Start directly with findings: "The mean cumulative abnormal returns in the KBE banking sector ETF around FOMC announcements are statistically insignificant in the three-day window: −1.06% for rate hikes (p = 0.0603) and −0.08% for rate cuts (p = 0.9295)."

---

### 8. Consistency

**Strengths:**
- Terminology is consistent: CAR, abnormal return, market model
- Tense is mostly consistent (present tense for methods/general statements, past tense for results)
- Number formatting is consistent (percentages, p-values to 4 decimal places)

**Issues Identified:**

**Issue 8.1: Inconsistent tense in methods**
- Location: Market Model Specification section
- Text: "We estimate (present) ... we interpret (present) ... we compute (present)" but then "is then (passive present): $$AR_{i,\tau} = R_{i,\tau}^{\text{KBE}} - ...$$ $$The abnormal return for event i on trading day τ within an event window is then:$$"
- Problem: Mixed active and passive voice in same methodological section
- Revision: Standardize to active voice throughout: "We then compute the abnormal return as..."

**Issue 8.2: Inconsistent terminology**
- "Rate increase" vs. "rate hike" vs. "tightening" — used interchangeably
- "Rate decrease" vs. "rate cut" vs. "easing" — used interchangeably
- Problem: Minor but potentially confusing
- Revision: Choose one term per concept and use consistently. Recommend: "rate hikes" and "rate cuts" (matches paper's own phrasing in tables).

**Issue 8.3: Inconsistent acronym use**
- Location: Throughout
- "CAR" sometimes expanded, sometimes not
- "DGS2" sometimes explained, sometimes assumed known
- Recommendation: Expand first use in each major section; thereafter use acronym only.

---

### 9. Economics-Specific Writing Issues

**Strengths:**
- "Significant" is used correctly to mean statistically significant throughout
- "Affects" (verb) vs. "effect" (noun) usage is correct: "rate decisions affect bank valuations" vs. "the effect of rate decisions"
- "Fewer" vs. "less": Check—"fewer observations" should be "fewer observations" (correct); "less variation" should be "less variation" (correct)

**Issues Identified:**

**Issue 9.1: Vague use of "spread"**
- Location: Institutional Context, NIM discussion
- Text: "the spread between lending and deposit rates (the net interest margin)"
- Problem: This is correct but the terminology conflates "spread" (difference in rates) with "margin" (difference as a percentage of assets). For precision in economics:
- Revision: "the net interest margin (NIM): the spread between average rates on loans and deposits, expressed as a percentage of assets"

**Issue 9.2: Imprecise use of "mechanism"**
- Location: Institutional Context
- Text: "For bank stocks, the primary channel of monetary policy transmission is the net interest margin..."
- Problem: "Channel" and "mechanism" are used interchangeably, which is acceptable but imprecise in monetary economics. Recommendation: standardize to "channel" (used in Federal Reserve context).

**Issue 9.3: Missing economic interpretation**
- Location: Results, H2 section
- Text: "a coefficient of −0.0208 basis points (p = 0.6368)"
- Problem: The coefficient is in basis points, but the unit is unclear. Does this mean: for every 1 bps increase in DGS2, CAR decreases by 0.0208 bps? That would be a tiny effect.
- Clarification needed: "For every 100 basis point increase in the 2-year Treasury yield, KBE abnormal returns decrease by 2.08 basis points (statistically insignificant)"

---

### 10. Anti-Slop Writing Standards

**Strengths:**
- Avoids banned phrases ("plays a crucial role," "it is worth noting," "interestingly," "future research could")
- Numbers are contextualized: "mean CAR of −1.06% (t = -1.998, p = 0.0603)" includes units and test statistics
- Each paragraph carries one main idea

**Issues Identified:**

**Issue 10.1: Imprecise claim in abstract**
- Location: Abstract, first sentence of main findings
- Text: "Rate hikes (20 events) yield a mean CAR of −1.06% (t = -1.998, p = 0.0603), not significant at the 5% level."
- Problem: "Yield" is vague — the announcement does not "yield" the return; rather, the market produces this return around the announcement.
- Revision: "Around rate-hike announcements (20 events), the mean CAR is −1.06% (t = -1.998, p = 0.0603), not significant at the 5% level."

**Issue 10.2: Vague framing in introduction**
- Location: Introduction, "Against this background" section
- Text: "Against this background, this paper asks a straightforward empirical question: How do US bank stocks respond to Federal Reserve target-rate announcements?"
- Problem: "Against this background" is a transition phrase that assumes prior context; in the introduction, the background has just been established in the preceding sentence, making the transition weak.
- Revision: Delete "Against this background" and begin directly with the question, or restructure: "These offsetting considerations motivate our empirical question: How do US bank stocks respond to Federal Reserve target-rate announcements?"

**Issue 10.3: Hedging language in abstract**
- Location: Abstract, interpretation section
- Text: "These results suggest that any announcement-day effect in the narrow window is small and not consistently signed; the cumulative effect over the broader window merits investigation in future work. The absence of a relationship between yield surprise and abnormal returns indicates that the announcement-day reaction, if any, is not proportional to the magnitude of the rate move."
- Problem: This is appropriate hedging, but "if any" is weak. The data show no evidence; state that directly.
- Revision: "These results indicate that announcement-day abnormal returns are not proportional to the magnitude of the Treasury yield surprise, suggesting that announcement-day price movements reflect either prior market incorporation of expected Fed moves or offsetting economic forces."

---

## Summary of Key Recommendations

### High Priority (Affect Clarity)
1. **Tighten the three-interpretation paragraph** in Discussion (Issue 2.2): Split into separate sentences to improve readability.
2. **Reduce literature review length** (Issue 2.1): The 5-section literature review is disproportionate; consolidate to 2–3 pages.
3. **Fix repeated phrases** (Issue 2.3): Vary language for "not significantly different from zero."
4. **Clarify H2 coefficient units** (Issue 9.3): State the economic magnitude in dollars or percentages, not basis points.

### Medium Priority (Improve Flow)
5. **Add topic sentence to H2 results** (Issue 6.2): Begin with motivation, then results.
6. **Restructure "Future Research"** (Issue 2.2): Integrate longer-window question into discussion of [0, +5] result.
7. **Fix "Against this background"** (Issue 10.2): Remove weak transition or restructure.

### Lower Priority (Polish)
8. **Trim wordiness** in key sentences (Issues 7.1, 7.2, 7.4).
9. **Standardize terminology** (Issue 8.2): Use "rate hikes" and "rate cuts" consistently.
10. **Enhance economic interpretation** (Issue 9.1): Clarify NIM terminology.

---

## Strengths to Retain

1. **Transparent reporting of null results**: The paper clearly states that findings are "not significant" rather than claiming absence of effects.
2. **Proper hedging of causal claims**: Uses "respond to," "correlate with," and "consistent with" rather than causal language.
3. **Clear methodology**: The market model specification and event windows are precisely defined.
4. **Honest interpretation**: The Discussion section addresses why null effects might emerge (efficiency, offsetting forces, power), rather than dismissing the findings.
5. **Appropriate disclosure**: The machine-generated analysis is clearly flagged with a disclosure statement.

---

## Minor Issues (Acceptable as-is but could be improved)

- Some long paragraphs in Institutional Context section (break into 3 paragraphs per channel)
- "Not statistically significantly different from zero" repeated 4 times (vary phrasing)
- Proportional imbalance between literature review and empirical section (tighten literature)

---

## Verdict

The paper is **ready for publication with minor revisions**. The research design is sound, the null results are properly reported and interpreted, and the writing is generally clear and well-structured. The identified issues are addressable through targeted editing and do not compromise the scientific integrity of the work. The paper would benefit from:

1. Tightening key summary statements for conciseness
2. Reducing the literature review to emphasize the empirical contribution
3. Varying hedging language to avoid repetition
4. Adding economic interpretation of regression coefficients

These revisions would enhance readability and impact without altering the substance of the findings.

---

## Scoring Rationale

**Scoring Dimensions** (out of 10 points):
- Clarity (8/10): Generally clear but some wordy passages and dense paragraphs
- Argument Flow (8/10): Good structure but literature review dominates; some disconnects in Discussion
- Evidence-Claim Alignment (9/10): Proper hedging, null results accurately reported
- Hedging & Causal Language (9/10): Appropriate qualification of claims
- Conciseness (7/10): Some unnecessarily long sentences; repetition in key phrases
- Consistency (9/10): Terminology and tense mostly consistent
- Economics Writing (8/10): Correct use of technical terms; could improve economic interpretation
- Anti-Slop Standards (8/10): Avoids most banned phrases; some imprecision in motivation

**Average Score**: (8+8+9+9+7+9+8+8) / 8 = 8.25 / 10

Rounding to nearest half-point: **8/10**

This reflects a well-written, technically sound paper with room for editorial improvement in conciseness, flow, and proportionality of sections.

---

OVERALL SCORE: 8/10
RECOMMENDATION: Minor Revision
