"""`e2er export <paper_id> [--to DIR]` — assemble a structured project folder.

On-demand / re-export counterpart to the runner's auto-export at terminal
status. Each invocation produces a fresh versioned folder (``…-NN``).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


def export(paper_id: str, to: str | None = None) -> int:
    from .config import get_settings
    from .core.export.structured import export_paper

    settings = get_settings()
    workspace = Path(settings.workspace_root) / paper_id
    if not workspace.is_dir():
        print(f"error: no workspace for paper {paper_id} at {workspace}")
        return 1

    dest_root = Path(to).expanduser() if to else settings.resolved_output_root()
    date_str = datetime.now().strftime("%Y%m%d")
    try:
        out = export_paper(workspace, dest_root, date_str=date_str)
    except Exception as e:  # noqa: BLE001
        print(f"error: export failed: {e}")
        return 1
    print(f"Exported → {out}")
    return 0
