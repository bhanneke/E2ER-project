# Identification Strategy Reasoning

Before any regression, answer these questions in writing:

## 1. What is the causal claim?
State: "We claim that X → Y because [mechanism]."
Not: "X is associated with Y."

## 2. What is the identifying variation?
Explain the source of variation in X that is plausibly exogenous.
Examples:
- Regulatory change that affected some units but not others
- Timing discontinuity (RDD)
- Instrumental variable with first-stage F > 10
- Natural experiment (weather, geography, algorithm assignment)

## 3. What are the threats?
For each identification strategy, name the 2-3 most plausible threats:
- Omitted variables
- Reverse causality  
- Sample selection
- Measurement error

## 4. How do you address each threat?
For each threat: placebo test, robustness check, or theoretical argument.

## 5. What is the LATE?
If using IV: what is the local average treatment effect?
Who are the compliers? Does this population matter for the research question?

## Minimum credibility bar
A paper needs at least one of:
- Difference-in-differences with parallel trends test
- IV with strong first stage (F > 10) and exclusion restriction argument
- RDD with density test and bandwidth sensitivity
- Panel fixed effects with theory for why time-varying confounders are ruled out
