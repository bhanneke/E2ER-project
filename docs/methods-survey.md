# Which empirical methods do researchers use? A survey for e2er templates

Prepared 11 October 2026 as Phase 0 of the plan to take e2er beyond economics.
The question: which empirical methods are used most across the sciences, and
which of them should e2er offer as templates (end-to-end study workflows with
specialists, checks and researcher stops)?

## How the survey was done

There is no single count of methods across all of science. The survey combines
four kinds of evidence, each with its own blind spots:

1. **Content analyses of journals.** Researchers read or coded the articles of
   a set of journals and recorded which methods each article used (medicine,
   psychology, education, ecology, information systems, management, library and
   information science, political science). These are the most direct evidence
   but cover mostly leading journals, and several are old.
2. **Text-mining studies.** Studies that search the full text or abstracts of
   many papers for method words (economics working papers, sociology abstracts,
   ecology articles, AI terms across all disciplines).
3. **Publication counts for one method family.** How many systematic reviews,
   meta-analyses or qualitative studies appear per year.
4. **Citation counts of the standard reference for a method** (for example
   Kaplan and Meier 1958 for survival curves, Bates et al. 2015 for mixed
   models in R). Authors cite these when they use the method, so the counts
   and the fields of the citing papers show where a method is used. Citations
   are an indirect measure: they mix use with discussion, older papers have had
   longer to collect them, and some methods (t-tests, OLS regression,
   descriptive statistics) have no single paper that users cite. Crossref
   counts and OpenAlex citing-field shares were retrieved on 11 October 2026.

Every reference below was checked against Crossref (DOI, authors, year,
journal); abstracts were read through OpenAlex or the publisher; numbers quoted
come from the abstract, the full text or an official press release of the
authors' universities, as marked. Claims without a checkable source were
dropped.

### Where the evidence is thin

Method-frequency studies exist mainly for medicine, psychology, education,
ecology, economics, information systems and management. For astronomy, the
earth and climate sciences, engineering and the digital humanities I found no
study that counts how often each method appears in the journals of the field.
For these fields the survey relies on citation counts of method references
and on reviews that describe growth without measuring shares. Spatial
statistics, time series methods, text analysis, network analysis and
agent-based simulation also lack direct frequency counts across fields. The
ranking below is therefore firmer at the top (descriptive statistics, group
comparisons, regression, survival analysis, systematic reviews) than in the
middle and lower part.

## Main findings

1. **Descriptive statistics and simple group comparisons are the common base
   of nearly every empirical field.** In the New England Journal of Medicine of
   1978–79, a reader who knew only percentages, means and standard deviations
   could follow the statistics of 58% of the articles; t-tests raised this to
   67% and contingency tables to 73% (Emerson & Colditz 1983). In six library
   and information science journals the three most used methods were the
   t-test, ANOVA and the chi-square test (Zhang, Zhao & Wang 2016). In 288
   recent psychology papers ANOVA was the most frequently used procedure for
   comparisons (Blanca, Alarcón & Bono 2018).
2. **Fields move from simple tests to models over time.** The average number of
   distinct statistical methods per NEJM article rose from 1.9 (1978–79) to 2.7
   (1989), 4.2 (2004–05) and 6.1 (2015), while simple methods such as the
   t-test declined (Sato et al. 2017, press release of Chiba and Tsukuba
   universities). Ecology shows the same shift across nearly 20,000 articles
   from 1990 to 2013: mixed-effects models and Bayesian statistics rose,
   ANOVA and t-tests declined (Touchon & McCoy 2016).
3. **Regression in its many forms is the main tool for relationships between
   variables.** Psychology papers most commonly examined relationships with
   regression models, led by hierarchical regression and mediation analysis
   (Blanca et al. 2018); Canadian psychology articles most often used
   t-tests, ANOVA-type comparisons and multiple regression (Counsell & Harlow
   2017); multiple regression and correlation were the most frequent
   data-analysis topics in Organizational Research Methods (Aguinis et al.
   2009).
4. **Mixed (multilevel) models have become standard in ecology and psychology.**
   lme4, the R package for these models, was the most frequently reported R
   package in more than 60,000 articles from 30 ecology journals (Lai et al.
   2019), and its reference has about 79,000 Crossref citations. Meteyard &
   Davies (2020) describe linear mixed models as set to become the default
   analysis in psychological science.
5. **Medicine is dominated by trial and cohort methods.** In NEJM 2015, sample
   size and power calculation appeared in 62% of the 238 articles, survival
   analysis in 57%, contingency-table analysis in 53% and epidemiological
   methods in 50% (Sato et al. 2017, press release). Kaplan and Meier's 1958
   paper was the highest-ranked statistics paper among the 100 most-cited
   papers of all time (rank 11), Cox's 1972 paper ranked 24 (Van Noorden,
   Maher & Nuzzo 2014).
6. **Systematic reviews and meta-analyses grew faster than almost any other
   type of study.** Estimated systematic reviews indexed in PubMed rose from
   1,432 in 2000 to 29,073 in 2019, about 80 per day (Hoffmann et al. 2021).
   Between 1991 and 2014 annual publications of systematic reviews rose
   2,728% and of meta-analyses 2,635%, against 153% for all PubMed items
   (Ioannidis 2016). The PRISMA 2020 reporting guideline has about 94,000
   Crossref citations.
7. **Experiments and quasi-experiments define recent economics, and the
   designs spread into neighbouring fields.** In NBER working papers the share
   of applied-microeconomics papers that mention an experimental or
   quasi-experimental method reached roughly 55% in 2024 (finance 38%,
   macroeconomics and other fields a little over 30%); difference-in-differences
   grew more, longer and more widely than regression discontinuity;
   instrumental variables stayed flat at roughly 30% of applied-micro papers;
   20% of applied-micro papers mentioned randomised trials or lab experiments
   in 2024; synthetic control has fallen since 2020 (Goldsmith-Pinkham 2024,
   extending Currie, Kleven & Zwiers 2020). Randomised experiments also grew
   in political science (Druckman et al. 2006).
8. **Surveys and case studies dominate information systems and management.**
   Of 1,893 articles in eight IS outlets (1991–2001), survey research was the
   most used design (41%), followed by case studies (36%); 81% of empirical
   work was positivist (Chen & Hirschheim 2004).
9. **Qualitative research is large in the social sciences and rare in
   medical journals.** Qualitative articles were 1.2% of original research in
   67 general medical journals in 1998 and 4.1% in 2007 (Shuval et al. 2011);
   in 20 high-impact medical and health-services journals (1999–2008) they
   were 0–0.6% and 0–6.4% of empirical articles (Gagliardi & Dobrow 2011).
   Sociology journals show a lasting divide between qualitative and
   quantitative work in 8,737 abstracts from 1995 to 2017 (Schwemmer &
   Wieczorek 2020). Braun and Clarke's 2006 guide to thematic analysis has
   about 161,000 Crossref citations, more than any other method reference
   checked for this survey.
10. **Machine learning use rose across all disciplines, sharply since 2015**
    (Gao & Wang 2024, AI terms in 74.6 million papers measured against AI
    capabilities). Breiman's random forests paper has about 123,000 Crossref
    citations.
11. **Bayesian modelling is growing from a small base.** A systematic review
    found 1,579 Bayesian psychology articles from 1990 to 2015 with use
    increasing and broadening (van de Schoot et al. 2017); ecology shows the
    same rise (Touchon & McCoy 2016). In astronomy the emcee sampler paper
    (about 12,800 citations) points to wide MCMC use, but no frequency count
    exists.
12. **Open-source software spread with these methods.** The share of ecology
    articles reporting R as the primary analysis tool rose from 11.4% in 2008
    to 58.0% in 2017 (Lai et al. 2019); ecologists moved from SAS and SPSS to R
    (Touchon & McCoy 2016). This matters for e2er: methods run in R or Python
    are the ones e2er can re-run and verify.

## Ranked method families

Ranking rule: how many fields use the method heavily, weighted by how direct
the evidence is. "e2er fit" asks two questions: can the data come through an
open connector, and does the method produce numbers that e2er can check
against the code output?

| # | Method family | Fields where it dominates | Evidence (source: what it measured) | Typical data | Typical outputs | Typical checks | e2er fit |
|---|---|---|---|---|---|---|---|
| 1 | Descriptive statistics | All empirical fields; the whole of many astronomy, earth-science and official-statistics papers | Emerson & Colditz 1983: 58% of NEJM articles readable with descriptives alone; part of every content analysis below | Any table: catalogues, indicators, registers, surveys | Counts, means, medians, shares, distributions, cross-tabs, maps, figures | Sample definition and exclusions, missing values, units, outliers, totals adding up | **High.** Open data plenty (World Bank, Eurostat, NASA, USGS, WHO); every number traceable to code |
| 2 | Group comparisons: t-tests, chi-square, ANOVA, non-parametric tests | Psychology, education, medicine, LIS, ecology (declining) | Zhang et al. 2016: top 3 in LIS; Blanca et al. 2018: ANOVA most used in psychology; Touchon & McCoy 2016: decline in ecology | Experimental groups, survey groups | Test statistics, p-values, effect sizes, confidence intervals | Assumptions (normality, equal variance), multiple comparisons, effect sizes reported | **High** as part of other templates; too small for a template of its own |
| 3 | Linear and generalised regression (OLS, logistic, Poisson; correlation) | Social sciences, psychology, education, IS, management, economics, public health | Blanca et al. 2018; Counsell & Harlow 2017; Aguinis et al. 2009; e2er's current contract is built on it | Cross-sections, surveys, registers, panels | Coefficients, standard errors, fit, marginal effects | Specification, robust/clustered SEs, collinearity, influential points, robustness | **High.** Today's `empirical` template |
| 4 | Survival (time-to-event) analysis | Clinical medicine, epidemiology; also engineering reliability, firm and policy durations | Sato et al. 2017: 57% of NEJM 2015 articles; Kaplan–Meier rank 11 and Cox rank 24 of the all-time top-100 papers (Van Noorden et al. 2014) | Patient cohorts, trials, registers, durations | Survival curves, hazard ratios, median survival | Censoring, proportional-hazards test, competing risks | **Low–medium.** Methods are checkable, but patient-level data are rarely open |
| 5 | Systematic review and meta-analysis | Medicine and health; growing in psychology, education, ecology, management | Hoffmann et al. 2021: about 80 systematic reviews a day in 2019; Ioannidis 2016: +2,728% (SR) and +2,635% (MA) 1991–2014; Bastian et al. 2010 | Published studies (bibliographic databases, full texts) | PRISMA flow counts, table of extracted effects, pooled estimate, heterogeneity (I²), forest and funnel plots | Search reproducibility, double screening and agreement (kappa), extraction checked against source, risk of bias, publication bias | **High.** Literature connectors exist (OpenAlex, Crossref, arXiv); every extracted number can be checked against its source paper |
| 6 | Experiment and RCT analysis (incl. power analysis) | Medicine, psychology, behavioural and development economics, political science | Sato et al. 2017: power calculation in 62% of NEJM 2015 articles; Goldsmith-Pinkham 2024: 20% of applied-micro papers mention RCTs/lab experiments; Druckman et al. 2006; Blanca et al. 2018: experimental studies most prevalent with correlational ones | Own trial or lab data; published replication packages | Balance table, treatment effects with CIs, power | Randomisation balance, attrition, pre-registered vs reported outcomes, multiple outcomes | **Medium.** Methods are a good fit; open data mainly through replication packages (Zenodo, Dataverse, OSF) |
| 7 | Quasi-experimental designs: difference-in-differences and event studies, IV, regression discontinuity, synthetic control | Economics (applied micro, increasingly finance), public policy, health policy, political science | Goldsmith-Pinkham 2024; Currie et al. 2020: NBER text mining; DiD the largest and most persistent growth | Panels of units over time, policy dates | Treatment effect, event-study plot, pre-trend test | Parallel pre-trends, staggered-timing estimators, placebo dates/units, clustering | **High** for country/region panels from World Bank, Eurostat, OECD |
| 8 | Mixed (multilevel) models | Ecology, psychology, education, linguistics, medicine (repeated measures) | Lai et al. 2019: lme4 top R package in ecology; Touchon & McCoy 2016; Meteyard & Davies 2020; Blanca et al. 2018 (HLM rising) | Nested or repeated data: pupils in schools, plots in sites, trials per participant | Fixed effects, variance components, intra-class correlation | Random-effects structure, convergence, singular fits | **Medium–high** as an option of the regression contract |
| 9 | Latent-variable models: factor analysis, SEM, reliability | Psychology, management, IS, education, marketing | Blanca et al. 2018: SEM and CFA rising; Aguinis et al. 2009; Hu & Bentler 1999 has about 90,000 citations, Cronbach 1951 about 31,000 | Questionnaires | Loadings, fit indices, path coefficients, reliability | Fit cut-offs, measurement invariance, common-method bias | **Low–medium.** Questionnaire data rarely open |
| 10 | Qualitative coding (thematic analysis, case studies, grounded theory) | Sociology, IS, management, education, health services, anthropology | Chen & Hirschheim 2004: case studies 36% of IS research; Schwemmer & Wieczorek 2020; Braun & Clarke 2006 about 161,000 citations | Interviews, documents, field notes | Themes, codebooks, quotations | Coder agreement, saturation, member checks, audit trail | **Low** for verifiable numbers; interviews are rarely shareable. Possible for public documents |
| 11 | Machine-learning prediction and classification | Computer science, then biology, medicine, physics, astronomy, earth sciences, increasingly social science | Gao & Wang 2024: AI use rose across disciplines, sharply since 2015; Breiman 2001 about 123,000 citations | Large tables, images, spectra, text | Held-out accuracy or error, feature importance, predictions | Train/test separation, leakage, baselines, seeds, calibration | **Medium–high.** Data plentiful; results checkable when splits and seeds are fixed |
| 12 | Time series analysis and forecasting (trend tests, ARIMA/ETS, unit roots) | Macroeconomics, finance, climate and hydrology, energy, epidemiology | No content analysis found. Indirect: Mann 1945 and Sen 1968 trend-test papers about 15,000 and 13,600 citations, heavily from earth and environmental sciences; Dickey & Fuller 1979 about 7,000 | Regular series: temperatures, prices, counts, indicators | Trend estimates, decomposition, forecasts with intervals, out-of-sample errors | Stationarity, autocorrelation in residuals, structural breaks, out-of-sample evaluation | **High.** Open series abundant (NASA POWER, NOAA, FRED, World Bank, USGS) |
| 13 | Bayesian modelling and MCMC | Astronomy and cosmology, ecology, cognitive psychology, epidemiology | van de Schoot et al. 2017; Touchon & McCoy 2016; emcee 2013 about 12,800 citations, Stan 2017 about 6,000; astronomy evidence descriptive only | As for the model it estimates | Posterior distributions, credible intervals, model comparison | Convergence (R-hat, effective sample size), prior sensitivity, posterior predictive checks | **Medium** as an estimation option across templates; seeds make it reproducible |
| 14 | Spatial statistics and GIS | Geography, ecology, epidemiology, earth sciences, regional economics, urban studies | No frequency count found. Indirect: Anselin 1995 (LISA) about 10,600 citations, Moran 1950 about 5,600, Matheron 1963 about 3,900; Dormann et al. 2007 review of methods for spatial autocorrelation | Points, regions, rasters with coordinates | Maps, spatial autocorrelation (Moran's I), hot spots, kriged surfaces, spatial regressions | Projection and boundary choice, spatial autocorrelation in residuals, scale (modifiable areal unit problem) | **High.** Open data plenty (Eurostat NUTS, USGS, Natural Earth, Gaia sky positions) |
| 15 | Text analysis (dictionaries, topic models, embeddings, language models) | Political science, sociology, economics, digital humanities, linguistics, communication | No frequency count found; used as a measuring tool in Currie et al. 2020, Schwemmer & Wieczorek 2020, Gao & Wang 2024; Grimmer & Stewart 2013 about 2,500 citations | Corpora: books, speeches, news, abstracts | Word frequencies, topic shares, classifications | Pre-processing recorded, hand-coded validation sample, stability across seeds and settings | **Medium–high.** Gutenberg and OpenAlex abstracts are open; counts are exactly reproducible |
| 16 | Network analysis | Physics, sociology, biology, information science, economics | No frequency count found; Newman 2003 about 14,300 citations, Louvain method 2008 about 17,800 | Edge lists: citations, collaborations, trade, interactions | Degree distributions, centrality, communities, main paths | Boundary of the network, robustness to sampling, null models | **Medium.** e2er's `field-map` already covers citation networks |
| 17 | Simulation and agent-based models | Ecology, epidemiology, social simulation, engineering, physics | No frequency count found; ODD protocol (Grimm et al. 2006) about 2,400 citations | Model parameters, calibration data | Simulated distributions, scenarios, sensitivity analyses | Verification of code, calibration, sensitivity, replication with different seeds | **Low–medium.** Reproducible with seeds; little open data needed, but outputs are model-specific |

Two widely cited method references fall outside the families above:
Benjamini and Hochberg's false discovery rate (1995; about 96,500 citations,
mostly genomics and other high-dimensional biology) and Bland and Altman's
agreement analysis (1986; about 38,700 citations, measurement studies in
medicine). Both are checks that templates can include (multiple testing,
agreement between measurements) and do not need templates of their own.

### Where the method references are cited

Citation counts retrieved on 11 October 2026 from Crossref and OpenAlex. The
two counts differ because each database sees a different set of citing
documents; neither is complete. The field shares are the shares of OpenAlex
citing works by the primary field OpenAlex assigns to each citing work (top
three fields shown). They show where a method is used and say little about how
often it is used per paper.

What the table adds to the content analyses: trend tests (Mann, Sen) are cited
mainly from environmental and earth sciences; lme4 mainly from environmental,
biological sciences and psychology; Astropy and the emcee sampler almost only
from physics and astronomy; Moran's I and LISA spread across environmental
science, economics and the social sciences; the DiD, synthetic-control and RD
references stay within economics, the social sciences and business; thematic
analysis, Cohen's kappa and Cronbach's alpha are cited across the social
sciences, psychology and medicine.

| Family | Method reference | Paper | Crossref citations | OpenAlex citations | Top fields of citing papers (OpenAlex) |
|---|---|---|---|---|---|
| Survival | Kaplan-Meier estimator | Kaplan & Meier 1958 | 77,040 | 39,462 | Medicine 70%; Biochemistry, Genetics and Molecular Biology 8%; Mathematics 7% |
| Survival | Cox proportional hazards | Cox 1972 | 37,300 | 39,736 | Medicine 50%; Mathematics 16%; Biochemistry, Genetics and Molecular Biology 8% |
| Mixed models | lme4 mixed models | Bates et al. 2015 | 79,318 | 86,956 | Environmental Science 23%; Agricultural and Biological Sciences 19%; Psychology 15% |
| Regression | Generalized linear models (Nelder & Wedderburn) | Nelder & Wedderburn 1972 | 5,620 | 7,258 | Mathematics 27%; Environmental Science 13%; Agricultural and Biological Sciences 9% |
| Regression | Heteroskedasticity-robust SE (White) | White 1980 | 18,711 | 26,353 | Economics, Econometrics and Finance 38%; Business, Management and Accounting 27%; Social Sciences 11% |
| Systematic review / meta-analysis | Random-effects meta-analysis (DerSimonian & Laird) | DerSimonian & Laird 1986 | 34,154 | 39,421 | Medicine 70%; Biochemistry, Genetics and Molecular Biology 8%; Decision Sciences 4% |
| Systematic review / meta-analysis | Heterogeneity I² (Higgins & Thompson) | Higgins & Thompson 2002 | 32,662 | 36,602 | Medicine 65%; Psychology 6%; Biochemistry, Genetics and Molecular Biology 6% |
| Systematic review / meta-analysis | PRISMA 2009 | Moher et al. 2009 | 59,613 | 63,911 | Medicine 52%; Psychology 8%; Social Sciences 7% |
| Systematic review / meta-analysis | PRISMA 2020 | Page et al. 2021 | 93,768 | 105,244 | Medicine 53%; Psychology 7%; Social Sciences 6% |
| Qualitative coding | Thematic analysis (Braun & Clarke) | Braun & Clarke 2006 | 160,863 | 191,712 | Social Sciences 33%; Medicine 18%; Psychology 14% |
| Qualitative coding | Cohen’s kappa | Cohen 1960 | 33,292 | 42,294 | Medicine 20%; Computer Science 15%; Psychology 13% |
| Machine learning | Random forests (Breiman) | Breiman 2001 | 122,972 | 132,539 | Computer Science 22%; Environmental Science 19%; Engineering 15% |
| Machine learning | Deep learning (LeCun, Bengio, Hinton) | LeCun et al. 2015 | 78,167 | 84,485 | Computer Science 38%; Engineering 21%; Medicine 9% |
| Quasi-experimental | DiD standard errors (Bertrand, Duflo, Mullainathan) | Bertrand et al. 2004 | 8,872 | 10,932 | Economics, Econometrics and Finance 33%; Social Sciences 25%; Business, Management and Accounting 19% |
| Quasi-experimental | Staggered DiD (Callaway & Sant’Anna) | Callaway & Sant’Anna 2021 | 8,488 | 9,042 | Economics, Econometrics and Finance 31%; Social Sciences 25%; Business, Management and Accounting 20% |
| Quasi-experimental | Synthetic control (Abadie et al.) | Abadie et al. 2010 | 4,694 | 5,632 | Economics, Econometrics and Finance 31%; Social Sciences 29%; Mathematics 13% |
| Quasi-experimental | Regression discontinuity guide (Imbens & Lemieux) | Imbens & Lemieux 2008 | 2,943 | 3,823 | Social Sciences 41%; Economics, Econometrics and Finance 19%; Mathematics 14% |
| Time series | Unit-root test (Dickey & Fuller) | Dickey & Fuller 1979 | 6,991 | 23,236 | Economics, Econometrics and Finance 74%; Social Sciences 5%; Business, Management and Accounting 4% |
| Time series | Automatic forecasting (Hyndman & Khandakar) | Hyndman & Khandakar 2008 | 2,612 | 3,538 | Decision Sciences 22%; Environmental Science 13%; Computer Science 13% |
| Time series | Trend test (Mann 1945) | Mann 1945 | 14,939 | 17,198 | Environmental Science 72%; Earth and Planetary Sciences 13%; Agricultural and Biological Sciences 6% |
| Time series | Trend slope (Sen 1968) | Sen 1968 | 13,592 | 13,679 | Environmental Science 70%; Earth and Planetary Sciences 15%; Agricultural and Biological Sciences 5% |
| Spatial | Moran’s I | Moran 1950 | 5,578 | 7,359 | Environmental Science 26%; Economics, Econometrics and Finance 18%; Social Sciences 12% |
| Spatial | Local indicators of spatial association (Anselin) | Anselin 1995 | 10,636 | 12,961 | Social Sciences 22%; Economics, Econometrics and Finance 22%; Environmental Science 22% |
| Multiple testing | False discovery rate (Benjamini & Hochberg) | Benjamini & Hochberg 1995 | 96,499 | 108,912 | Biochemistry, Genetics and Molecular Biology 25%; Medicine 24%; Neuroscience 10% |
| Latent variables / SEM | Mediation (Baron & Kenny) | Baron & Kenny 1986 | 73,457 | 71,657 | Business, Management and Accounting 27%; Psychology 22%; Social Sciences 21% |
| Latent variables / SEM | SEM fit cutoffs (Hu & Bentler) | Hu & Bentler 1999 | 90,295 | 108,490 | Psychology 32%; Social Sciences 24%; Business, Management and Accounting 14% |
| Latent variables / SEM | Cronbach’s alpha | Cronbach 1951 | 30,886 | 43,940 | Social Sciences 20%; Psychology 17%; Business, Management and Accounting 16% |
| Experiments (power) | G*Power | Faul et al. 2007 | 56,681 | 65,839 | Medicine 27%; Psychology 24%; Neuroscience 14% |
| Bayesian | Stan | Carpenter et al. 2017 | 6,060 | 7,872 | Mathematics 17%; Environmental Science 13%; Medicine 10% |
| Bayesian | MCMC convergence (Gelman & Rubin) | Gelman & Rubin 1992 | 13,635 | 16,696 | Environmental Science 18%; Mathematics 16%; Physics and Astronomy 12% |
| Bayesian | emcee sampler | Foreman-Mackey et al. 2013 | 12,786 | 12,413 | Physics and Astronomy 94%; Engineering 1%; Mathematics 1% |
| Astronomy software | Astropy | Astropy Collaboration 2013 | 14,002 | 14,591 | Physics and Astronomy 98%; Computer Science 1%; Engineering 1% |
| Network analysis | Community detection (Louvain, Blondel et al.) | Blondel et al. 2008 | 17,752 | 21,134 | Physics and Astronomy 24%; Computer Science 19%; Biochemistry, Genetics and Molecular Biology 11% |
| Network analysis | Structure and function of complex networks (Newman) | Newman 2003 | 14,306 | 18,792 | Physics and Astronomy 42%; Computer Science 18%; Social Sciences 6% |
| Simulation / ABM | ODD protocol for agent-based models (Grimm et al.) | Grimm et al. 2006 | 2,439 | 2,995 | Environmental Science 33%; Medicine 9%; Agricultural and Biological Sciences 9% |
| Measurement agreement | Bland-Altman agreement | Bland & Altman 1986 | 38,662 | 48,017 | Medicine 72%; Engineering 5%; Health Professions 3% |
| Text analysis | Text as data (Grimmer & Stewart) | Grimmer & Stewart 2013 | 2,536 | 3,315 | Social Sciences 65%; Computer Science 11%; Business, Management and Accounting 5% |
| Text analysis | BERT language model | Devlin et al. 2019 | 10,359 | 33,959 | Computer Science 83%; Social Sciences 5%; Biochemistry, Genetics and Molecular Biology 3% |
| Spatial | Geostatistics/kriging (Matheron 1963) | Matheron 1963 | 3,908 | 4,891 | Environmental Science 26%; Engineering 17%; Earth and Planetary Sciences 15% |

## Template recommendation

### The four chosen templates

| Template | Verdict | Why |
|---|---|---|
| Descriptive data study | **Confirm, build first.** | The one method family every field uses (finding 1). It is also the natural template for the astronomy, earth-science and official-statistics demos, where many papers describe a sample before they model it. |
| Policy evaluation (difference-in-differences with pre-trends and event-study plot) | **Confirm.** | The fastest-growing design in economics and spreading to finance and policy fields (finding 7). Country and region panels from World Bank, Eurostat and OECD give it open data. Outside the social sciences it is rare, so it serves the social-science side of e2er. |
| Time series and forecasting | **Confirm, with a note.** | Usage is not measured by any content analysis I found; support comes from citation counts of trend tests in the earth and environmental sciences and from economics and finance practice. Its strength for e2er is data: open regular series are the most plentiful kind of open data. |
| Spatial analysis | **Confirm, with the same note.** | No frequency study, but standard in geography, ecology, epidemiology and regional economics, and open spatial data (Eurostat regions, USGS, Natural Earth) suit verification. |

### Further candidates, ranked

1. **Systematic review and meta-analysis.** Strongest growth evidence of any
   family (finding 6) and the best fit with what e2er already has: literature
   connectors, `field-map`, and checks that compare extracted numbers with the
   source text. Result contract: PRISMA flow counts (records found, screened,
   included), a table of extracted effects with the page or table each came
   from, pooled estimate with confidence interval, I² and tau², forest and
   funnel plots. Checks: the search can be re-run and gives the same records
   (or the difference is reported); a sample of extracted numbers is read
   against the source; double screening agreement (kappa); small-study and
   publication-bias tests; leave-one-out.
2. **Experiment and RCT analysis.** Heavily used in medicine, psychology and
   economics (findings 5 and 7). Fits `empirical-preregistered`. Open data come
   mainly from replication packages, so the first demos would re-analyse
   published experiments. Result contract: arms and sample sizes, balance
   table, effect estimates with confidence intervals, attrition by arm, power.
   Checks: balance, differential attrition, pre-registered versus reported
   outcomes, correction for multiple outcomes.
3. **Survey and cross-sectional regression** (linear, logistic, with survey
   weights). Covers the large middle of psychology, education, sociology,
   public health and IS (findings 3 and 8). Today's regression contract
   covers most of it; it needs survey weights, design-based standard errors
   and a measurement section (scale reliability). Data: open survey releases
   (for example the European Social Survey and the General Social Survey) after
   checking their terms; some require registration.
4. **Machine-learning prediction.** Rising across all fields (finding 10).
   Result contract: data split, held-out metrics, comparison with a simple
   baseline, feature importance. Checks: no leakage between training and test
   data, fixed seeds, the metric recomputed from saved predictions.
5. **Text analysis.** Little frequency evidence, growing use in the social
   sciences and humanities, and the planned Gutenberg demo needs it. Result
   contract: corpus statistics (documents, tokens, dates), pre-processing
   record, dictionary or model, results by group or period. Checks: counts
   recomputed from the corpus, a hand-checked validation sample for any
   classifier, stability across seeds.
6. **Mixed (multilevel) models.** Very common in ecology and psychology
   (finding 4) but closer to an option of the regression and descriptive
   templates than to a separate workflow. Contract additions: group counts,
   variance components, intra-class correlation, convergence status.
7. **Survival analysis.** Dominant in clinical medicine (finding 5); placed low
   because patient-level data are rarely open. Possible later with open
   duration data (firm survival, policy spells, equipment failure). Contract:
   number at risk and events, Kaplan–Meier curves, hazard ratios; checks:
   censoring, proportional hazards.

Not recommended as templates for now: latent-variable models and qualitative
coding (data rarely open), Bayesian modelling (an estimation option across
templates), network analysis (covered for citation networks by `field-map`),
agent-based simulation (outputs too model-specific for a shared contract).

### What the result contracts have in common

Every family above produces some mix of four kinds of checkable output:
summary tables (counts, means, shares), effect estimates with uncertainty
(coefficients, hazard ratios, pooled effects, treatment effects), model
diagnostics (fit, convergence, assumption tests) and figures built from saved
data. A discipline-neutral contract (plan Phase 1) can define these four blocks
once and let each template require the blocks it needs. The coefficient block
that e2er requires today then becomes one block among four.

## Sources by field

| Field | Source | What it measured |
|---|---|---|
| Medicine | Emerson & Colditz 1983 | Methods in 760 NEJM articles, vols 298–301 (1978–79) |
| Medicine | Horton & Switzer 2005 | Update of the NEJM survey for 2004–05 (figures not quoted here: full text not accessible) |
| Medicine | Sato et al. 2017 | All 238 NEJM articles of 2015; numbers quoted from the authors' universities' press release (13 March 2017) |
| Medicine | Strasak et al. 2007 | NEJM vol. 350 vs Nature Medicine vol. 10: 94.5% and 82.4% of articles used inferential statistics |
| Medicine | Shuval et al. 2011; Gagliardi & Dobrow 2011 | Share of qualitative studies in medical journals |
| Medicine / health | Bastian et al. 2010; Ioannidis 2016; Hoffmann et al. 2021 | Numbers of trials, systematic reviews and meta-analyses |
| Psychology | Blanca et al. 2018 | 288 papers, 663 data-analysis procedures |
| Psychology | Counsell & Harlow 2017 | Quantitative methods in Canadian psychology journals |
| Psychology | van de Schoot et al. 2017 | 1,579 Bayesian psychology articles, 1990–2015 |
| Psychology | Meteyard & Davies 2020 | Survey of 163 researchers and review of 400 papers using linear mixed models |
| Education and psychology | Troncoso Skidmore & Thompson 2010 | Synthesis of 11 earlier reviews: 17,698 techniques in 12,012 articles, 1948–2001 |
| Ecology | Touchon & McCoy 2016 | Nearly 20,000 articles 1990–2013 plus 154 doctoral curricula |
| Ecology | Low-Décarie et al. 2014 | More than 18,000 articles: rising statistical complexity, falling R² |
| Ecology | Lai et al. 2019 | R packages in more than 60,000 articles, 30 journals, 2008–2017 |
| Ecology | Dormann et al. 2007 | Review of methods for spatial autocorrelation (no frequency count) |
| Economics | Hamermesh 2013 | Methods of articles in three top journals, one year per decade 1960s–2010s |
| Economics | Currie, Kleven & Zwiers 2020; Goldsmith-Pinkham 2024 | Method words in NBER working papers (28,397 papers, 1982–2024 in the update) |
| Political science | Bennett, Barth & Rutherford 2003 | Methods in more than 2,200 articles of 10 journals and in the curricula of top 30 departments |
| Political science | Druckman et al. 2006 | Experiments in the first 100 volumes of the APSR |
| Sociology | Schwemmer & Wieczorek 2020 | 8,737 abstracts of generalist sociology journals, 1995–2017 |
| Information systems | Chen & Hirschheim 2004; Palvia et al. 2004 | 1,893 articles in 8 outlets (1991–2001); 7 MIS journals (1993–2003) |
| Management | Scandura & Williams 2000; Aguinis et al. 2009 | Research strategies in AMJ, ASQ, JOM (1985–87 vs 1995–97); 193 ORM articles |
| Library and information science | Zhang, Zhao & Wang 2016 | Statistical methods in six LIS journals |
| All disciplines | Gao & Wang 2024 | AI terms in 74.6 million papers |
| All disciplines | Van Noorden, Maher & Nuzzo 2014 | The 100 most-cited papers (Web of Science, October 2014) |
| Astronomy, earth sciences, engineering, digital humanities | none found | No method-frequency study located; see "Where the evidence is thin" |

## References

Aguinis, H., Pierce, C. A., Bosco, F. A., & Muslin, I. S. (2009). First decade of Organizational Research Methods: Trends in design, measurement, and data-analysis topics. *Organizational Research Methods*, 12(1), 69–112. https://doi.org/10.1177/1094428108322641

Bastian, H., Glasziou, P., & Chalmers, I. (2010). Seventy-five trials and eleven systematic reviews a day: How will we ever keep up? *PLoS Medicine*, 7(9), e1000326. https://doi.org/10.1371/journal.pmed.1000326

Bennett, A., Barth, A., & Rutherford, K. R. (2003). Do we preach what we practice? A survey of methods in political science journals and curricula. *PS: Political Science & Politics*, 36(3), 373–378. https://doi.org/10.1017/S1049096503002476

Blanca, M. J., Alarcón, R., & Bono, R. (2018). Current practices in data analysis procedures in psychology: What has changed? *Frontiers in Psychology*, 9, 2558. https://doi.org/10.3389/fpsyg.2018.02558

Chen, W., & Hirschheim, R. (2004). A paradigmatic and methodological examination of information systems research from 1991 to 2001. *Information Systems Journal*, 14(3), 197–235. https://doi.org/10.1111/j.1365-2575.2004.00173.x

Counsell, A., & Harlow, L. L. (2017). Reporting practices and use of quantitative methods in Canadian journal articles in psychology. *Canadian Psychology*, 58(2), 140–147. https://doi.org/10.1037/cap0000074

Currie, J., Kleven, H., & Zwiers, E. (2020). Technology and big data are changing economics: Mining text to track methods. *AEA Papers and Proceedings*, 110, 42–48. https://doi.org/10.1257/pandp.20201058

Dormann, C. F., McPherson, J. M., Araújo, M. B., Bivand, R., et al. (2007). Methods to account for spatial autocorrelation in the analysis of species distributional data: A review. *Ecography*, 30(5), 609–628. https://doi.org/10.1111/j.2007.0906-7590.05171.x

Druckman, J. N., Green, D. P., Kuklinski, J. H., & Lupia, A. (2006). The growth and development of experimental research in political science. *American Political Science Review*, 100(4), 627–635. https://doi.org/10.1017/S0003055406062514

Emerson, J. D., & Colditz, G. A. (1983). Use of statistical analysis in The New England Journal of Medicine. *New England Journal of Medicine*, 309(12), 709–713. https://doi.org/10.1056/NEJM198309223091206

Gagliardi, A. R., & Dobrow, M. J. (2011). Paucity of qualitative research in general medical and health services and policy research journals: Analysis of publication rates. *BMC Health Services Research*, 11, 268. https://doi.org/10.1186/1472-6963-11-268

Gao, J., & Wang, D. (2024). Quantifying the use and potential benefits of artificial intelligence in scientific research. *Nature Human Behaviour*, 8(12), 2281–2292. https://doi.org/10.1038/s41562-024-02020-5

Goldsmith-Pinkham, P. (2024). Tracking the credibility revolution across fields. arXiv:2405.20604. https://arxiv.org/abs/2405.20604 (also NBER Working Paper 35051, https://doi.org/10.3386/w35051)

Hamermesh, D. S. (2013). Six decades of top economics publishing: Who and how? *Journal of Economic Literature*, 51(1), 162–172. https://doi.org/10.1257/jel.51.1.162

Hoffmann, F., Allers, K., Rombey, T., Helbach, J., et al. (2021). Nearly 80 systematic reviews were published each day: Observational study on trends in epidemiology and reporting over the years 2000–2019. *Journal of Clinical Epidemiology*, 138, 1–11. https://doi.org/10.1016/j.jclinepi.2021.05.022

Horton, N. J., & Switzer, S. S. (2005). Statistical methods in the Journal. *New England Journal of Medicine*, 353(18), 1977–1979. https://doi.org/10.1056/NEJM200511033531823

Ioannidis, J. P. A. (2016). The mass production of redundant, misleading, and conflicted systematic reviews and meta-analyses. *The Milbank Quarterly*, 94(3), 485–514. https://doi.org/10.1111/1468-0009.12210

Lai, J., Lortie, C. J., Muenchen, R. A., Yang, J., & Ma, K. (2019). Evaluating the popularity of R in ecology. *Ecosphere*, 10(1), e02567. https://doi.org/10.1002/ecs2.2567

Low-Décarie, E., Chivers, C., & Granados, M. (2014). Rising complexity and falling explanatory power in ecology. *Frontiers in Ecology and the Environment*, 12(7), 412–418. https://doi.org/10.1890/130230

Meteyard, L., & Davies, R. A. I. (2020). Best practice guidance for linear mixed-effects models in psychological science. *Journal of Memory and Language*, 112, 104092. https://doi.org/10.1016/j.jml.2020.104092

Palvia, P., Leary, D., Mao, E., Midha, V., Pinjani, P., & Salam, A. F. (2004). Research methodologies in MIS: An update. *Communications of the Association for Information Systems*, 14, 24. https://doi.org/10.17705/1CAIS.01424

Sato, Y., Gosho, M., Nagashima, K., Takahashi, S., Ware, J. H., & Laird, N. M. (2017). Statistical methods in the Journal — an update. *New England Journal of Medicine*, 376(11), 1086–1087. https://doi.org/10.1056/NEJMc1616211. Figures quoted from the press release of Chiba University and the University of Tsukuba, 13 March 2017: https://www.tsukuba.ac.jp/journal/images/pdf/170316gosho.pdf

Scandura, T. A., & Williams, E. A. (2000). Research methodology in management: Current practices, trends, and implications for future research. *Academy of Management Journal*, 43(6), 1248–1264. https://doi.org/10.2307/1556348

Schwemmer, C., & Wieczorek, O. (2020). The methodological divide of sociology: Evidence from two decades of journal publications. *Sociology*, 54(1), 3–21. https://doi.org/10.1177/0038038519853146

Shuval, K., Harker, K., Roudsari, B., Groce, N. E., Mills, B., Siddiqi, Z., & Shachak, A. (2011). Is qualitative research second class science? A quantitative longitudinal examination of qualitative research in medical journals. *PLoS ONE*, 6(2), e16937. https://doi.org/10.1371/journal.pone.0016937

Troncoso Skidmore, S., & Thompson, B. (2010). Statistical techniques used in published articles: A historical review of reviews. *Educational and Psychological Measurement*, 70(5), 777–795. https://doi.org/10.1177/0013164410379320

Strasak, A. M., Zaman, Q., Marinell, G., Pfeiffer, K. P., & Ulmer, H. (2007). The use of statistics in medical research: A comparison of The New England Journal of Medicine and Nature Medicine. *The American Statistician*, 61(1), 47–55. https://doi.org/10.1198/000313007X170242

Touchon, J. C., & McCoy, M. W. (2016). The mismatch between current statistical practice and doctoral training in ecology. *Ecosphere*, 7(8), e01394. https://doi.org/10.1002/ecs2.1394

van de Schoot, R., Winter, S. D., Ryan, O., Zondervan-Zwijnenburg, M., & Depaoli, S. (2017). A systematic review of Bayesian articles in psychology: The last 25 years. *Psychological Methods*, 22(2), 217–239. https://doi.org/10.1037/met0000100

Van Noorden, R., Maher, B., & Nuzzo, R. (2014). The top 100 papers. *Nature*, 514(7524), 550–553. https://doi.org/10.1038/514550a

Zhang, J., Zhao, Y., & Wang, Y. (2016). A study on statistical methods used in six journals of library and information science. *Online Information Review*, 40(3), 416–434. https://doi.org/10.1108/OIR-07-2015-0247

### Method references used for citation counts

Abadie et al. (2010). Synthetic Control Methods for Comparative Case Studies: Estimating the Effect of California’s Tobacco Control Program. *Journal of the American Statistical Association*, 105(490), 493-505. https://doi.org/10.1198/jasa.2009.ap08746

Anselin (1995). Local Indicators of Spatial Association—LISA. *Geographical Analysis*, 27(2), 93-115. https://doi.org/10.1111/j.1538-4632.1995.tb00338.x

Astropy Collaboration (2013). Astropy: A community Python package for astronomy. *Astronomy & Astrophysics*, 558, A33. https://doi.org/10.1051/0004-6361/201322068

Baron & Kenny (1986). The moderator–mediator variable distinction in social psychological research: Conceptual, strategic, and statistical considerations. *Journal of Personality and Social Psychology*, 51(6), 1173-1182. https://doi.org/10.1037/0022-3514.51.6.1173

Bates et al. (2015). Fitting Linear Mixed-Effects Models Using lme4. *Journal of Statistical Software*, 67(1). https://doi.org/10.18637/jss.v067.i01

Benjamini & Hochberg (1995). Controlling the False Discovery Rate: A Practical and Powerful Approach to Multiple Testing. *Journal of the Royal Statistical Society Series B: Statistical Methodology*, 57(1), 289-300. https://doi.org/10.1111/j.2517-6161.1995.tb02031.x

Bertrand et al. (2004). How Much Should We Trust Differences-In-Differences Estimates? *The Quarterly Journal of Economics*, 119(1), 249-275. https://doi.org/10.1162/003355304772839588

Blondel et al. (2008). Fast unfolding of communities in large networks. *Journal of Statistical Mechanics: Theory and Experiment*, 2008(10), P10008. https://doi.org/10.1088/1742-5468/2008/10/P10008

Braun & Clarke (2006). Using thematic analysis in psychology. *Qualitative Research in Psychology*, 3(2), 77-101. https://doi.org/10.1191/1478088706qp063oa

Breiman (2001). Random Forests. *Machine Learning*, 45(1), 5-32. https://doi.org/10.1023/A:1010933404324

Callaway & Sant’Anna (2021). Difference-in-Differences with multiple time periods. *Journal of Econometrics*, 225(2), 200-230. https://doi.org/10.1016/j.jeconom.2020.12.001

Carpenter et al. (2017). Stan: A Probabilistic Programming Language. *Journal of Statistical Software*, 76(1). https://doi.org/10.18637/jss.v076.i01

Cohen (1960). A Coefficient of Agreement for Nominal Scales. *Educational and Psychological Measurement*, 20(1), 37-46. https://doi.org/10.1177/001316446002000104

Cox (1972). Regression Models and Life-Tables. *Journal of the Royal Statistical Society Series B: Statistical Methodology*, 34(2), 187-202. https://doi.org/10.1111/j.2517-6161.1972.tb00899.x

Cronbach (1951). Coefficient Alpha and the Internal Structure of Tests. *Psychometrika*, 16(3), 297-334. https://doi.org/10.1007/BF02310555

DerSimonian & Laird (1986). Meta-analysis in clinical trials. *Controlled Clinical Trials*, 7(3), 177-188. https://doi.org/10.1016/0197-2456(86)90046-2

Devlin et al. (2019). BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding. *Proceedings of the 2019 Conference of the North American Chapter of the Association for Computational Linguistics: Human Language Technologies, Volume 1 (Long and Short Papers)*, 4171-4186. https://doi.org/10.18653/v1/N19-1423

Dickey & Fuller (1979). Distribution of the Estimators for Autoregressive Time Series with a Unit Root. *Journal of the American Statistical Association*, 74(366a), 427-431. https://doi.org/10.1080/01621459.1979.10482531

Faul et al. (2007). G*Power 3: A flexible statistical power analysis program for the social, behavioral, and biomedical sciences. *Behavior Research Methods*, 39(2), 175-191. https://doi.org/10.3758/BF03193146

Foreman-Mackey et al. (2013). emcee : The MCMC Hammer. *Publications of the Astronomical Society of the Pacific*, 125(925), 306-312. https://doi.org/10.1086/670067

Gelman & Rubin (1992). Inference from Iterative Simulation Using Multiple Sequences. *Statistical Science*, 7(4). https://doi.org/10.1214/ss/1177011136

Grimm et al. (2006). A standard protocol for describing individual-based and agent-based models. *Ecological Modelling*, 198(1-2), 115-126. https://doi.org/10.1016/j.ecolmodel.2006.04.023

Grimmer & Stewart (2013). Text as Data: The Promise and Pitfalls of Automatic Content Analysis Methods for Political Texts. *Political Analysis*, 21(3), 267-297. https://doi.org/10.1093/pan/mps028

Higgins & Thompson (2002). Quantifying heterogeneity in a meta‐analysis. *Statistics in Medicine*, 21(11), 1539-1558. https://doi.org/10.1002/sim.1186

Hu & Bentler (1999). Cutoff criteria for fit indexes in covariance structure analysis: Conventional criteria versus new alternatives. *Structural Equation Modeling: A Multidisciplinary Journal*, 6(1), 1-55. https://doi.org/10.1080/10705519909540118

Hyndman & Khandakar (2008). Automatic Time Series Forecasting: The forecast Package for R. *Journal of Statistical Software*, 27(3). https://doi.org/10.18637/jss.v027.i03

Imbens & Lemieux (2008). Regression discontinuity designs: A guide to practice. *Journal of Econometrics*, 142(2), 615-635. https://doi.org/10.1016/j.jeconom.2007.05.001

Kaplan & Meier (1958). Nonparametric Estimation from Incomplete Observations. *Journal of the American Statistical Association*, 53(282), 457-481. https://doi.org/10.1080/01621459.1958.10501452

LeCun et al. (2015). Deep learning. *Nature*, 521(7553), 436-444. https://doi.org/10.1038/nature14539

Mann (1945). Nonparametric Tests Against Trend. *Econometrica*, 13(3), 245. https://doi.org/10.2307/1907187

Bland & Altman (1986). STATISTICAL METHODS FOR ASSESSING AGREEMENT BETWEEN TWO METHODS OF CLINICAL MEASUREMENT. *The Lancet*, 327(8476), 307-310. https://doi.org/10.1016/S0140-6736(86)90837-8

Matheron (1963). Principles of geostatistics. *Economic Geology*, 58(8), 1246-1266. https://doi.org/10.2113/gsecongeo.58.8.1246

Moher et al. (2009). Preferred Reporting Items for Systematic Reviews and Meta-Analyses: The PRISMA Statement. *PLoS Medicine*, 6(7), e1000097. https://doi.org/10.1371/journal.pmed.1000097

Moran (1950). NOTES ON CONTINUOUS STOCHASTIC PHENOMENA. *Biometrika*, 37(1-2), 17-23. https://doi.org/10.1093/biomet/37.1-2.17

Nelder & Wedderburn (1972). Generalized Linear Models. *Journal of the Royal Statistical Society. Series A (General)*, 135(3), 370. https://doi.org/10.2307/2344614

Newman (2003). The Structure and Function of Complex Networks. *SIAM Review*, 45(2), 167-256. https://doi.org/10.1137/S003614450342480

Page et al. (2021). The PRISMA 2020 statement: an updated guideline for reporting systematic reviews. *BMJ*, n71. https://doi.org/10.1136/bmj.n71

Sen (1968). Estimates of the Regression Coefficient Based on Kendall's Tau. *Journal of the American Statistical Association*, 63(324), 1379-1389. https://doi.org/10.1080/01621459.1968.10480934

White (1980). A Heteroskedasticity-Consistent Covariance Matrix Estimator and a Direct Test for Heteroskedasticity. *Econometrica*, 48(4), 817. https://doi.org/10.2307/1912934
