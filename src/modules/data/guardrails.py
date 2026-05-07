"""Data module — 5-rule guardrail layer enforced before every query execution."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .dictionary import DataDictionary


@dataclass
class ValidationResult:
    valid: bool
    rejection_reason: str = ""
    warnings: list[str] = field(default_factory=list)


class QueryValidator:
    """Enforces all 5 guardrails from the grant application."""

    # ── Rule 1: No SELECT * ───────────────────────────────────────────────────
    _SELECT_STAR = re.compile(r"SELECT\s+(\*|[a-zA-Z_]+\.\*)", re.IGNORECASE)

    @staticmethod
    def validate_no_select_star(sql: str) -> ValidationResult:
        if QueryValidator._SELECT_STAR.search(sql):
            return ValidationResult(
                valid=False,
                rejection_reason=(
                    "Query uses SELECT * or table.*. All queries must explicitly list "
                    "required fields. Revise the query to select only the columns defined "
                    "in your data_dictionary.json."
                ),
            )
        return ValidationResult(valid=True)

    # ── Rule 2: Fields in data dictionary ────────────────────────────────────
    @staticmethod
    def validate_fields_in_dictionary(
        fields_requested: list[str],
        dictionary: DataDictionary,
    ) -> ValidationResult:
        allowed = dictionary.allowed_field_names
        disallowed = [f for f in fields_requested if f not in allowed]
        if disallowed:
            return ValidationResult(
                valid=False,
                rejection_reason=(
                    f"Fields not in data_dictionary.json: {disallowed}. "
                    f"Allowed fields: {sorted(allowed)}. "
                    "Add missing fields to the dictionary first, then resubmit."
                ),
            )
        return ValidationResult(valid=True)

    # ── Rule 3: Time-bound WHERE clause ───────────────────────────────────────
    _DATE_PATTERNS = [
        re.compile(
            r"WHERE.*?\b(date|timestamp|time|block_time|evt_block_time|created_at|block_date)\b",
            re.IGNORECASE | re.DOTALL,
        ),
        re.compile(r"WHERE.*?[><=!]+\s*'?\d{4}-\d{2}-\d{2}", re.IGNORECASE | re.DOTALL),
        re.compile(r"WHERE.*?BETWEEN\s+", re.IGNORECASE | re.DOTALL),
        re.compile(r"WHERE.*?DATE_TRUNC\s*\(", re.IGNORECASE | re.DOTALL),
    ]

    @staticmethod
    def validate_time_bound(sql: str) -> ValidationResult:
        if not any(p.search(sql) for p in QueryValidator._DATE_PATTERNS):
            return ValidationResult(
                valid=False,
                rejection_reason=(
                    "Query does not contain a time-bound WHERE clause. All queries "
                    "must filter by a date or timestamp column matching the time_filter "
                    "in your data_dictionary.json. Add a WHERE clause like: "
                    "WHERE block_time BETWEEN 'YYYY-MM-DD' AND 'YYYY-MM-DD'."
                ),
            )
        return ValidationResult(valid=True)

    # ── Rule 4: Aggregation level justification ───────────────────────────────
    @staticmethod
    def validate_aggregation_level(
        aggregation_level: str,
        granularity_justification: str,
        dictionary: DataDictionary,
    ) -> ValidationResult:
        if aggregation_level in ("transaction", "event"):
            warnings = ["Transaction/event-level query — will be flagged in human review."]
            if not granularity_justification and not dictionary.granularity_justification:
                warnings.append(
                    f"No granularity_justification provided for '{aggregation_level}' level. "
                    "Consider aggregating to daily/weekly unless transaction-level is essential."
                )
            return ValidationResult(valid=True, warnings=warnings)
        return ValidationResult(valid=True)

    # ── Rule 5: Feasibility-first ─────────────────────────────────────────────
    @staticmethod
    async def validate_feasibility_first(
        query_type: str,
        paper_id: str,
        table: str,
    ) -> ValidationResult:
        if query_type != "production":
            return ValidationResult(valid=True)

        from ...db.client import fetch_one

        row = await fetch_one(
            """
            SELECT id FROM data_query_records
            WHERE paper_id = %(pid)s
              AND query_type = 'feasibility'
              AND validation_status = 'approved'
              AND query_sql ILIKE %(table_pattern)s
            LIMIT 1
            """,
            {"pid": paper_id, "table_pattern": f"%{table}%"},
        )
        if not row:
            return ValidationResult(
                valid=False,
                rejection_reason=(
                    f"No approved feasibility query found for table '{table}'. "
                    "Submit a feasibility query (LIMIT 1000) first. Production queries "
                    "may only run after a feasibility check has been approved."
                ),
            )
        return ValidationResult(valid=True)

    # ── Combined validation ────────────────────────────────────────────────────
    @staticmethod
    async def validate_all(
        sql: str,
        query_type: str,
        fields_requested: list[str],
        aggregation_level: str,
        granularity_justification: str,
        dictionary: DataDictionary,
        paper_id: str,
        primary_table: str = "",
    ) -> ValidationResult:
        checks = [
            QueryValidator.validate_no_select_star(sql),
            QueryValidator.validate_fields_in_dictionary(fields_requested, dictionary),
            QueryValidator.validate_time_bound(sql),
            QueryValidator.validate_aggregation_level(aggregation_level, granularity_justification, dictionary),
        ]
        for c in checks:
            if not c.valid:
                return c

        feasibility = await QueryValidator.validate_feasibility_first(query_type, paper_id, primary_table)
        if not feasibility.valid:
            return feasibility

        all_warnings = [w for c in checks for w in c.warnings]
        return ValidationResult(valid=True, warnings=all_warnings)
