# Theoretical Framework: Does X Cause Y?

## Setup

Consider agents $i \in \{1, \ldots, N\}$ observed over periods $t \in \{1, \ldots, T\}$. A subset receives treatment $D_{it} \in \{0, 1\}$ beginning at period $t^*$. Define:

- $Y_{it}$: outcome of interest
- $D_{it}$: treatment indicator (absorbing: once treated, always treated)
- $\mathbf{Z}_{it}$: observable covariates

## Potential Outcomes

Each agent has potential outcomes $Y_{it}(0)$ and $Y_{it}(1)$. The observed outcome:

$$Y_{it} = D_{it} \cdot Y_{it}(1) + (1 - D_{it}) \cdot Y_{it}(0)$$

Target estimand — average treatment effect on the treated (ATT):

$$\tau_{ATT} = \mathbb{E}[Y_{it}(1) - Y_{it}(0) \mid D_{it} = 1]$$

## DiD Specification

Two-way fixed effects (TWFE) regression:

$$Y_{it} = \alpha_i + \gamma_t + \delta \cdot D_{it} + \mathbf{Z}_{it}'\beta + \varepsilon_{it}$$

where $\alpha_i$ absorbs time-invariant unit heterogeneity, $\gamma_t$ absorbs common shocks, and $\delta$ identifies the ATT under parallel trends.

## Mechanism

X operates on Y through a mediating channel. Let $m_{it}$ denote the mediating variable:

$$X_{it} \xrightarrow{\pi} m_{it} \xrightarrow{\lambda} Y_{it}$$

The reduced-form effect decomposes as $\delta = \pi \cdot \lambda$. The sign of $\delta$ is determined by the signs of both links in the chain.

## Propositions

**Proposition 1.** Under parallel trends (A1), no anticipation (A2), and SUTVA (A3), the TWFE estimator $\hat{\delta}$ consistently estimates $\tau_{ATT}$ when treatment effects are homogeneous across cohorts and event time.

**Proposition 2.** With heterogeneous treatment effects across cohorts or over event time, $\hat{\delta}_{TWFE}$ is a variance-weighted average that can assign negative weights to some group-time ATTs (Goodman-Bacon, 2021; de Chaisemartin & D'Haultfoeuille, 2020). Heterogeneity-robust estimators (Callaway & Sant'Anna, 2021; Sun & Abraham, 2021) recover interpretable group-time-specific effects.

**Proposition 3.** The sign of $\delta$ equals $\text{sgn}(\pi) \cdot \text{sgn}(\lambda)$. A positive reduced-form effect requires either both links positive or both negative.

## Comparative Statics

- $\partial \delta / \partial |\text{treatment intensity}| > 0$: stronger exposure amplifies the effect, testable via dose-response specification.
- Pre-treatment levels of $Y$ are uninformative about treatment assignment conditional on $\alpha_i$.
