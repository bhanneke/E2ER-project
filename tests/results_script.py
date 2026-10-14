"""Test helper: give a hand-made workspace the script that writes its results, run through the script log.

e2er holds a results file to the script that computes it (contract_check.check_results_from_code,
`e2er verify` "results from code"); a fixture that only writes estimation_results.json has no code behind it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

NAME = "run_estimation.py"


def write_results_script(ws: Path, results: dict[str, Any] | None = None, *, run: bool = True) -> Path:
    """Write run_estimation.py that writes ``results`` (default: the workspace's estimation_results.json) and,
    with ``run``, run it recorded in the script log (so the results come from the code)."""
    if results is None:
        results = json.loads((ws / "estimation_results.json").read_text(encoding="utf-8"))
    script = ws / NAME
    script.write_text(
        "import json\n"
        f"RESULTS = json.loads({json.dumps(json.dumps(results))})\n"
        'with open("estimation_results.json", "w", encoding="utf-8") as f:\n'
        "    json.dump(RESULTS, f)\n",
        encoding="utf-8",
    )
    if run:
        from src.core.specialists.post_execution import _run_recorded

        assert _run_recorded(ws.resolve(), ws.resolve() / NAME, 60, by="e2er-run") == 0
    return script
