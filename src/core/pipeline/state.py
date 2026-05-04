"""Pipeline execution state — persisted progress for resume-ability."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class PipelineState:
    paper_id: str
    mode: str
    completed_stages: list[str] = field(default_factory=list)
    current_stage: str = ""
    iteration: int = 0
    pivot_count: int = 0
    contributions_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def mark_complete(self, stage: str) -> None:
        if stage not in self.completed_stages:
            self.completed_stages.append(stage)
        self.current_stage = ""

    def is_complete(self, stage: str) -> bool:
        return stage in self.completed_stages

    def save(self, workspace: Path) -> None:
        path = workspace / ".pipeline_state.json"
        path.write_text(json.dumps(self.__dict__, indent=2))

    @classmethod
    def load(cls, workspace: Path, paper_id: str, mode: str) -> "PipelineState":
        path = workspace / ".pipeline_state.json"
        if path.exists():
            try:
                data = json.loads(path.read_text())
                return cls(**data)
            except Exception:
                pass
        return cls(paper_id=paper_id, mode=mode)
