# Limitations

## 1. Synthetic data — no external validity

All results derive from a synthetic DGP with known parameters (δ=2.5, Gaussian errors, balanced panel). The clean recovery of the treatment effect validates the estimation pipeline but carries zero information about empirical phenomena. Production runs with real data may encounter: (a) weaker or null effects, (b) non-Gaussian error distributions, (c) missing data and attrition, (d) treatment effect heterogeneity that complicates TWFE interpretation (de Chaisemartin and d'Haultfoeuille, 2020; Goodman-Bacon, 2021).

## 2. Identification: parallel trends assumption is untestable post-treatment

The pre-trend diagnostics (placebo p=0.27, flat event-study leads) and the placebo group falsification (run_4: coef=0.20, p=0.34) jointly support the identification strategy, but neither can guarantee parallel trends hold post-treatment. In the synthetic DGP, parallel trends hold by construction. In real data, time-varying confounders correlated with treatment assignment could violate A1 without leaving pre-treatment traces — particularly if confounders activate simultaneously with treatment.

## 3. SUTVA may not hold in production settings

The synthetic data has no spillover channels by construction (units are independent draws). Real economic settings typically involve market interactions, geographic proximity, or network effects that violate SUTVA (Assumption A3). If treated units' outcomes affect control units' outcomes (e.g., through competitive dynamics), the estimated ATT conflates the direct treatment effect with equilibrium spillovers.

## 4. Two post-treatment periods limit dynamic analysis

With only t=3 and t=4 available post-treatment, the event-study can identify the immediate effect and one-period persistence but cannot characterize medium- or long-run dynamics. The apparent strengthening from 2.15 to 2.39 could reflect genuine accumulation, mean-reversion noise, or compositional effects. Longer panels are needed to distinguish transient from permanent treatment effects.

## 5. H2 (dose-response) remains only indirectly tested

Run_3 adds a heterogeneity analysis splitting the sample by median x (threshold=5.12), yielding nearly identical treatment effects for high-x (2.37) and low-x (2.41) subgroups. This provides no evidence of effect heterogeneity along x, but does not constitute a proper dose-response test: x is a covariate, not treatment intensity. Treatment remains binary with no dose variation. The TWFE_with_log_x specification in run_2 and run_4 transforms the covariate, not the treatment, and similarly does not test H2. A genuine test requires either a continuous intensity measure derived from the treatment mechanism or an instrument for treatment exposure.

## 6. Single covariate — omitted variable risk in production

The only control variable (x) is randomly generated and adds negligible explanatory power (R² increases from 0.307 to 0.3071 when included). The log-transformed version (run_2/run_4, TWFE_with_log_x) similarly adds no information (coef=2.3911 vs. baseline 2.3904). In production, omitted time-varying confounders are the primary threat to identification. The pipeline should accommodate richer covariate sets, including pre-treatment outcome levels, industry/sector indicators, and macro controls.

## 7. Limited heterogeneity analysis

Run_3 introduces a covariate-based sample split (high-x vs. low-x), finding homogeneous effects. However, this single dimension is insufficient. Production analyses should explore heterogeneity along treatment-relevant dimensions (e.g., pre-treatment outcome levels, sector, size). The TWFE estimator, when applied to settings with staggered adoption or heterogeneous effects, can produce estimates that are variance-weighted averages of group-specific ATTs — potentially with negative weights (Goodman-Bacon, 2021). The current uniform-adoption design avoids this problem, but production applications with staggered treatment should employ heterogeneity-robust estimators (Callaway and Sant'Anna, 2021; Sun and Abraham, 2021).

## 8. Clustered SEs may be conservative or anti-conservative

Standard errors are clustered at the unit level (CR1, confirmed across runs). With 200 clusters, asymptotic approximations are reasonable, but in production panels with fewer clusters (<50), the CR1 estimator can under-reject. Wild cluster bootstrap or the approach of Cameron, Gelbach, and Miller (2008) would provide more reliable inference in small-cluster settings.

## 9. Slight downward bias in point estimate

The estimated ATT of 2.39 is 4.4% below the true parameter of 2.5. While this falls within the 95% CI and is consistent with finite-sample variation, the direction of the bias is worth monitoring in production. If systematic, it could indicate attenuation from measurement error in the treatment variable or outcome — a concern that grows with real-world data where measurement is noisier than in synthetic panels.

## 10. Placebo group test has limited power

The run_4 placebo group test (coef=0.20, SE=0.208, p=0.34) fails to reject the null but has wider standard errors than the main specification (0.208 vs. 0.122). The minimum detectable effect at 80% power for this test is approximately 0.58 — the test can rule out large spurious effects but cannot exclude modest placebo effects in the range [0, 0.6]. In production, increasing placebo group sample size or using multiple placebo groups would sharpen this falsification test.
