# Polish of the formulas

Checked every displayed equation in `paper_draft.tex` against the design in
`event_design.json` and the estimation script `run_estimation.py`.

1. **Market model (Section "Market Model Specification").** $R_{i,t} = \alpha_i + \beta_i R_{m,t} + \varepsilon_{i,t}$
   with SPY as $R_{m,t}$, estimated over the 238 trading days before each event
   window. Matches the script. No change.
2. **Abnormal return and CAR.** $AR_{i,t} = R_{i,t} - \hat\alpha_i - \hat\beta_i R_{m,t}$ and
   $CAR_i[\tau_1,\tau_2] = \sum_{t=\tau_1}^{\tau_2} AR_{i,t}$. The draft writes the sum over
   $[-1,+1]$ for the pre-registered window; the script sums the same three days. No change.
3. **Cross-sectional test of H1.** $t = \overline{CAR} / (s_{CAR}/\sqrt{N})$ with $N-1$ degrees
   of freedom. The draft states 30, 19 and 10 degrees of freedom for the pooled, hike and cut
   samples, which agrees with `estimation_results.json` (`df`). No change.
4. **H2 regression.** $CAR_i = \gamma_0 + \gamma_1 \Delta y^{2y}_i + u_i$ with HC1 standard
   errors. The draft calls the coefficient "basis points"; it is percent of CAR per basis
   point of the yield change. Suggest writing "per basis point" where the coefficient is
   quoted (Introduction, Discussion). Wording only; the numbers stay as they are.
