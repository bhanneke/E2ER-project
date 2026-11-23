# Security Policy

## Supported versions

E2ER v3 is the only actively maintained line. Earlier versions (v1, v2) are
not public and receive no security updates.

| Version | Supported          |
| ------- | ------------------ |
| 3.x     | :white_check_mark: |
| < 3.0   | :x:                |

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Open a draft advisory through GitHub Security Advisories at
<https://github.com/bhanneke/E2ER-project/security/advisories/new>.
The report stays private until a fix is published.

Please include:

- Affected version or commit SHA
- A short reproduction (PoC code, query, or steps)
- The impact you observed (data exposure, code execution, cost runaway,
  guardrail bypass, etc.)

You will receive an acknowledgement within 5 business days. We aim to
publish a fix and a coordinated advisory within 30 days for confirmed
vulnerabilities.

## Scope

The areas most relevant to security in this codebase:

- **Data module guardrails** (`src/modules/data/guardrails.py`) — bypasses
  that let an LLM-generated query skip approval, exceed time bounds, or
  exfiltrate data outside the declared `data_dictionary.json`.
- **Cost cap enforcement** (`src/modules/tracking/usage.py`) — paths
  where a paper can spend past its `max_cost_usd` cap.
- **GitHub credential handling** (`src/modules/github/`) — token
  exposure, accidental commit of secrets, repo permissions.
- **Prompt injection** in LLM tool-use loop — untrusted input causing
  unintended tool calls or guardrail evasion.
- **Pipeline state corruption** — paths that lose committed upstream
  artifacts on a downstream failure.

## Out of scope

- Issues that require an attacker to already control the host running the
  pipeline.
- Cost overruns due to a misconfigured `MAX_COST_USD` set by the
  operator (configuration, not vulnerability).
- LLM hallucinations producing incorrect research output. The pipeline
  is a research assistant, not a source of truth — all outputs require
  human review before publication or use.
