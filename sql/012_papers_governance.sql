-- E2ER v3: papers.governance — the governance regime the run executed under.
--
-- off | contracts | full (default). This is the treatment variable of the
-- governance experiment: it selects which verification institutions BLOCK a
-- run. In the non-`full` regimes the deterministic gates still compute their
-- verdicts and log `gate_shadow` events, so fabrication that WOULD have been
-- caught is measured. Storing the regime on the row makes each paper's
-- treatment disclosable and lets the experiment harvester group by regime.
--
-- Additive with a default so existing rows read as `full` (their behaviour).

ALTER TABLE papers
    ADD COLUMN governance TEXT NOT NULL DEFAULT 'full';
