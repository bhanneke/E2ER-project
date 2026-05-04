# Data Module — Allium Query Flow

Every SQL query from a specialist passes through 5 guardrails before reaching the Allium
HTTP API. Production queries additionally require human researcher approval.

```mermaid
sequenceDiagram
    participant Spec as Specialist (LLM)
    participant Handler as AlliumToolHandler
    participant GR as Guardrails (5 rules)
    participant DB as Audit Log (PostgreSQL)
    participant API as Researcher (REST API)
    participant Allium as Allium HTTP API

    Spec->>Handler: query_allium(sql, query_type, fields, ...)

    Handler->>GR: Rule 1 — No SELECT *
    GR-->>Handler: pass / fail

    Handler->>GR: Rule 2 — Fields in data_dictionary.json
    GR-->>Handler: pass / fail

    Handler->>GR: Rule 3 — Time-bound WHERE clause
    GR-->>Handler: pass / fail

    Handler->>GR: Rule 4 — Aggregation level check
    GR-->>Handler: pass / warn

    Handler->>GR: Rule 5 — Feasibility-first check (production only)
    GR-->>Handler: pass / fail

    alt Any rule fails
        Handler-->>Spec: "Query rejected: [reason]"
    else All rules pass
        Handler->>DB: log_query() → query_id

        alt query_type = feasibility
            Handler->>Handler: enforce LIMIT 1000
            Handler->>DB: mark_approved(auto_feasibility)
            Handler->>Allium: POST /explorer/query/run
            Allium-->>Handler: rows (≤1000)
            Handler->>DB: mark_executed(row_count)
            Handler-->>Spec: "Feasibility: N rows\nSample: [...]"
        else query_type = production
            Handler->>DB: create_approval_request()
            Handler-->>Spec: "Pending approval\nquery_id: XYZ\nUse check_approval()"

            Note over API,DB: Researcher reviews at<br/>GET /api/papers/{id}/pending-queries

            API->>DB: POST /api/queries/{id}/approve
            DB-->>API: status updated

            Spec->>Handler: check_approval(query_id)
            Handler->>DB: get_approval_status()

            alt approved
                Handler->>Allium: POST /explorer/query/run
                Allium-->>Handler: full result set
                Handler->>DB: mark_executed(row_count)
                Handler-->>Spec: Full results
            else rejected
                Handler-->>Spec: "Rejected — revise and resubmit"
            else pending
                Handler-->>Spec: "Still pending — check back later"
            end
        end
    end
```
