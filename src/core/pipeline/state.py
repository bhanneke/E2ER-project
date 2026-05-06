"""Pipeline execution state — persisted progress for resume-ability."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_STATE_FILENAME = ".pipeline_state.json"
_BACKUP_FILENAME = ".pipeline_state.json.bak"
_TMP_FILENAME = ".pipeline_state.json.tmp"


@dataclass
class PipelineState:
    paper_id: str
    mode: str
    completed_stages: list[str] = field(default_factory=list)
    current_stage: str = ""
    iteration: int = 0
    pivot_count: int = 0
    contributions_count: int = 0
    last_status: str = "in_progress"
    metadata: dict[str, Any] = field(default_factory=dict)

    def mark_complete(self, stage: str) -> None:
        if stage not in self.completed_stages:
            self.completed_stages.append(stage)
        self.current_stage = ""

    def is_complete(self, stage: str) -> bool:
        return stage in self.completed_stages

    def save(self, workspace: Path) -> None:
        # Atomic write + backup of previous good state. Without this, a crash
        # mid-write corrupts the only state file and ALL upstream progress is
        # lost on resume — re-running every specialist burns API tokens.
        path = workspace / _STATE_FILENAME
        tmp = workspace / _TMP_FILENAME
        bak = workspace / _BACKUP_FILENAME

        tmp.write_text(json.dumps(self.__dict__, indent=2))
        if path.exists():
            path.replace(bak)
        tmp.replace(path)

    @classmethod
    def load(cls, workspace: Path, paper_id: str, mode: str) -> "PipelineState":
        # Try main file first, fall back to .bak if main is corrupted.
        for name in (_STATE_FILENAME, _BACKUP_FILENAME):
            p = workspace / name
            if p.exists():
                try:
                    data = json.loads(p.read_text())
                    return cls(**data)
                except Exception:
                    continue
        return cls(paper_id=paper_id, mode=mode)
