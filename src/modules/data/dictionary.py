"""Data dictionary — defines the minimal data footprint for a paper."""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, field_validator


class DataDictionaryEntry(BaseModel):
    name: str
    description: str
    data_type: str  # e.g. "timestamp", "address", "numeric", "text"
    source_table: str
    is_required: bool = True


class TimeFilter(BaseModel):
    start_date: str   # ISO format
    end_date: str
    column: str       # the timestamp/date column used for filtering


class DataDictionary(BaseModel):
    """Pre-specified minimal data footprint. Agent writes this BEFORE any queries."""

    unit_of_observation: str        # "transaction" | "block" | "address" | "daily_aggregate"
    fields: list[DataDictionaryEntry]
    time_filter: Optional[TimeFilter] = None
    chains: list[str] = []          # e.g. ["ethereum", "polygon"]
    additional_filters: dict[str, str] = {}   # extra WHERE clause scopes
    identification_rationale: str = ""  # why this data design serves the ID strategy
    granularity_justification: str = ""  # required if unit_of_observation is transaction/event

    @property
    def allowed_field_names(self) -> set[str]:
        return {f.name for f in self.fields}

    @field_validator("fields")
    @classmethod
    def at_least_one_field(cls, v: list[DataDictionaryEntry]) -> list[DataDictionaryEntry]:
        if not v:
            raise ValueError("DataDictionary must define at least one field")
        return v
