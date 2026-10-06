"""``e2er reproduce <folder>`` — run a study's code again and compare the results with the published ones.

How the code is run is the study's own ``reproduce.json`` (see
``src/core/reproduce.py``). The study folder is never written to: the code
runs in a run folder of its own, in a new virtual environment with the
study's pinned requirements. Exit codes: 0 reproduced, 1 differences,
2 could not run.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .core import reproduce as rp


def _fmt(v: Any) -> str:
    if v is None:
        return "(none)"
    text = json.dumps(v) if not isinstance(v, str) else v
    return text if len(text) <= 40 else text[:37] + "..."


def _rel(r: float | None) -> str:
    if r is None:
        return ""
    return f" ({r:.2%})" if r >= 1e-4 else f" (relative {r:.1e})"


def render(
    folder: Path,
    recipe: dict[str, Any],
    env_info: dict[str, Any] | None,
    steps: list[rp.StepResult],
    inputs: list[dict[str, Any]],
    files: list[rp.FileComparison],
    tables: dict[str, Any] | None,
    verdict: str,
) -> str:
    """The plain report. Pure, for tests."""
    lines = [f"e2er reproduce: {folder}", ""]
    if env_info:
        pins = ", ".join(
            f"{k} {v}" for k, v in sorted(env_info.get("packages", {}).items(), key=lambda kv: kv[0].lower())
        )
        lines.append(
            f"Environment: Python {env_info.get('python')} in a new virtual environment "
            f"({env_info.get('installer')}), from {recipe['requirements']}: {pins or 'no packages'}"
        )
        lines.append("")
    lines.append("Steps:")
    for i, s in enumerate(steps, 1):
        state = "done" if s.exit_code == 0 else f"FAILED (exit {s.exit_code})"
        about = f" ({s.about})" if s.about else ""
        lines.append(f"  {i}. {s.command}{about}: {state} in {s.seconds:.0f} s")
        if s.exit_code:
            lines += [f"       {t}" for t in s.tail.splitlines()]
            lines.append(f"       full output: {s.log}")
    if len(steps) < len(recipe["steps"]):
        lines.append(f"  {len(recipe['steps']) - len(steps)} later step(s) not run.")
    if inputs:
        same = [i for i in inputs if i["status"] == "identical"]
        differ = [i["path"] for i in inputs if i["status"] == "differs"]
        missing = [i["path"] for i in inputs if i["status"] == "missing"]
        lines += ["", "Inputs, compared with the study's own files (SHA-256):"]
        lines.append(f"  {len(same)} of {len(inputs)} identical")
        if differ:
            lines.append(f"  {len(differ)} differ: {', '.join(differ)}")
        if missing:
            lines.append(f"  {len(missing)} missing: {', '.join(missing)}")
    if files:
        lines += ["", "Results, value by value:"]
        for f in files:
            if f.problem:
                lines.append(f"  {f.published}: not compared, {f.problem}")
                continue
            counts = ", ".join(f"{f.counts[k]} {rp.LABEL_WORDS[k]}" for k in rp.LABELS if f.counts[k])
            lines.append(f"  {f.published}: {f.total} values: {counts}")
            for r, path, a, b in f.largest(5):
                lines.append(f"      {path}: published {_fmt(a)}, rerun {_fmt(b)}{_rel(r)}")
    if tables:
        lines += ["", "Tables, rendered again from the rerun's results:"]
        if tables.get("skipped"):
            lines.append(f"  not rendered: {tables['skipped']}")
        else:
            lines.append(f"  {len(tables['identical'])} of {tables['rendered']} identical to the paper's")
            if tables["differ"]:
                lines.append(f"  {len(tables['differ'])} differ: {', '.join(sorted(tables['differ']))}")
            if tables["not_shipped"]:
                lines.append(f"  {len(tables['not_shipped'])} not in the paper: {', '.join(tables['not_shipped'])}")
    notes = [n for n in recipe.get("notes") or [] if isinstance(n, str)]
    if notes:
        lines += ["", "Notes from the study's reproduce.json:"] + [f"  - {n}" for n in notes]
    lines += ["", verdict]
    return "\n".join(lines) + "\n"


def reproduce(folder: str, *, keep: bool = False, json_out: str | None = None) -> int:
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        print(f"error: {folder} is not a folder")
        return 2
    try:
        recipe = rp.load_recipe(root)
    except rp.RecipeError as e:
        print(f"error: {e}")
        return 2

    run_dir = Path(tempfile.mkdtemp(prefix="e2er-reproduce-"))
    logs = run_dir / ".e2er-logs"
    logs.mkdir()
    print(f"Running the study's code in {run_dir} (the study folder is not changed) ...", flush=True)
    env_info: dict[str, Any] | None = None
    steps: list[rp.StepResult] = []
    inputs: list[dict[str, Any]] = []
    files: list[rp.FileComparison] = []
    tables: dict[str, Any] | None = None
    try:
        rp.lay_out(root, run_dir, recipe)  # without the results it is to write: the rerun must write them
        python, env_info = rp.make_environment(run_dir, recipe, root, logs)
        steps = rp.run_steps(run_dir, recipe, rp.step_env(python), logs, python)
    except rp.RecipeError as e:
        print(f"error: {e}\nThe run folder is kept: {run_dir}")
        return 2
    ran = bool(steps) and not any(s.exit_code for s in steps)
    if ran:
        inputs = rp.compare_inputs(run_dir, recipe.get("inputs") or [])
        files = [
            rp.compare_json(root / c["published"], run_dir / c["produced"], c["published"], c["produced"])
            for c in recipe["compare"]
        ]
        tables = rp.compare_tables(root, run_dir, recipe["compare"])
    verdict, code = rp.verdict(files, tables, steps, inputs)
    print()
    print(render(root, recipe, env_info, steps, inputs, files, tables, verdict), end="")
    if json_out:
        doc = {
            "schema": "e2er-reproduce-report/1",
            "folder": str(root),
            "environment": env_info,
            "steps": [s.as_dict() for s in steps],
            "inputs": inputs,
            "results": [f.as_dict() for f in files],
            "tables": tables,
            "verdict": verdict,
            "exit_code": code,
        }
        Path(json_out).expanduser().write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")
        print(f"Report written to {json_out}")
    if keep or code != 0:
        print(f"The run folder is kept: {run_dir}")
    else:
        shutil.rmtree(run_dir, ignore_errors=True)
    return code
