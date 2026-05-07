-- E2ER v3: papers.methodology — empirical | theoretical | mixed
-- Selectable per paper at creation. Controls which specialists the
-- strategist dispatches (theory_specialist for theoretical/mixed,
-- data/econometrics specialists skipped for theoretical).

ALTER TABLE papers
    ADD COLUMN methodology TEXT NOT NULL DEFAULT 'empirical';

ALTER TABLE papers
    ADD CONSTRAINT papers_methodology_chk
    CHECK (methodology IN ('empirical', 'theoretical', 'mixed'));

CREATE INDEX idx_papers_methodology ON papers(methodology);
