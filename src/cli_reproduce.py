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
    kept: bool = True,
) -> str:
    """The plain report. Pure, for tests. ``kept``: the run folder (with the steps' full output) stays."""
    lines = [f"e2er reproduce: {folder}", ""]
    if env_info:
        pins = ", ".join(
            f"{k} {v}" for k, v in sorted(env_info.get("packages", {}).items(), key=lambda kv: kv[0].lower())
        )
        lines.append(
            f"Environment: Python {env_info.get('python')} in a new virtual environment "
            f"({env_info.get('installer')}), from {recipe['requirements']}: {pins or 'no packages'}"
        )
        if env_info.get("network_guard") is False:
            lines.append(
                "  The network guard could not be put into the environment: the steps were not kept off the web."
            )
        lines.append("")
    lines.append("Steps:")
    for i, s in enumerate(steps, 1):
        if s.skipped:
            about = f" ({s.about})" if s.about else ""
            lines.append(f"  {i}. {s.command}{about}: not run, {s.skipped}")
            continue
        state = "done" if s.exit_code == 0 else f"FAILED (exit {s.exit_code})"
        about = f" ({s.about})" if s.about else ""
        lines.append(f"  {i}. {s.command}{about}: {state} in {s.seconds:.0f} s")
        why = rp.blocked_words(s)
        if why:
            lines.append(f"       It {why}.")
        web = rp.web_hosts(s)
        if web and not s.reload:
            lines.append(f"       It read from the web (allowed with --allow-network): {', '.join(web)}.")
        if s.exit_code:
            if s.missing:
                lines.append(f"       {s.missing}")
            lines += [f"       {t}" for t in s.tail.splitlines()]
            if kept:
                lines.append(f"       full output: {s.log}")
            else:
                lines.append(f"       full output: {Path(s.log).name}, removed with the run folder (--keep keeps it)")
    if len(steps) < len(recipe["steps"]):
        lines.append(f"  {len(recipe['steps']) - len(steps)} later step(s) not run.")
    lines += ["", "Inputs, compared with the study's own files (SHA-256):"]
    declared = recipe.get("inputs") or []
    if not declared:
        lines.append("  the study's reproduce.json lists no inputs")
    elif not inputs:
        lines.append(f"  not compared: the run stopped before the inputs were laid out ({len(declared)} listed)")
    else:
        same = [i for i in inputs if i["status"] in ("identical", rp.SAME_ROWS)]
        reordered = [i["path"] for i in inputs if i["status"] == rp.SAME_ROWS]
        differ = [i for i in inputs if i["status"] == "differs"]
        missing = [i["path"] for i in inputs if i["status"] == "missing"]
        lines.append(f"  {len(same)} of {len(inputs)} identical")
        if reordered:
            lines.append(
                f"  {len(reordered)} with the same rows in a different order (identical content): "
                + ", ".join(reordered)
            )
        if differ:
            named = [
                i["path"] + (f" (tables {', '.join(i['tables_differ'])})" if i.get("tables_differ") else "")
                for i in differ
            ]
            lines.append(f"  {len(differ)} differ: {', '.join(named)}")
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


def _inputs_only(recipe: dict[str, Any], inputs: list[dict[str, Any]]) -> str:
    """The inputs section alone, for a run that stopped before its steps."""
    text = render(Path(""), {**recipe, "steps": []}, None, [], inputs, [], None, "")
    start = text.find("Inputs, compared")
    return "\n" + text[start:].rstrip() + "\n" if start >= 0 else ""


def reproduce(folder: str, *, keep: bool = False, json_out: str | None = None, allow_network: bool = False) -> int:
    """`e2er reproduce`. The run folder and an unpacked package are temporary: removed when the command ends,
    also after a failure, unless ``keep`` (then the report says where they are)."""
    from .core.export import package as pkg

    path = Path(folder).expanduser().resolve()
    if not pkg.is_package(path):
        return _reproduce_folder(path, keep=keep, json_out=json_out, allow_network=allow_network)
    # A .e2er package: unpacked into a folder of its own, every file checked against the manifest first.
    unpacked = Path(tempfile.mkdtemp(prefix="e2er-package-"))
    try:
        try:
            opened = pkg.open_package(path, unpacked / "study")
        except pkg.PackageError as e:
            print(f"error: the package is not intact: {e}")
            return 2
        print(
            f"Unpacked {path.name} into {opened.root}: {opened.files} file(s) match {pkg.MANIFEST} "
            f"(fingerprint {opened.manifest.get('fingerprint')}).",
            flush=True,
        )
        code = _reproduce_folder(opened.root, keep=keep, json_out=json_out, allow_network=allow_network, package=True)
        if keep:
            print(f"The unpacked package is kept: {opened.root}")
        return code
    finally:
        if not keep:
            shutil.rmtree(unpacked, ignore_errors=True)


def _reproduce_folder(
    root: Path, *, keep: bool, json_out: str | None, allow_network: bool, package: bool = False
) -> int:
    from .core.export import package as pkg

    if not root.is_dir():
        print(f"error: {root} is not a folder or a .e2er package")
        return 2
    try:
        recipe = rp.load_recipe(root, rebuild=pkg.rebuild_steps(root))
    except rp.RecipeError as e:
        print(f"error: {e}")
        return 2
    # Never from reproduce.json itself: only e2er sets where the wheels are, for an unpacked package.
    recipe.pop("wheelhouse", None)
    if package or pkg.package_manifest(root) is not None:
        source = pkg.install_source(root, recipe)
        if source.get("requirements"):
            recipe["requirements"] = source["requirements"]
        if source.get("wheelhouse"):
            recipe["wheelhouse"] = source["wheelhouse"]
        if source.get("wheelhouse_skipped"):
            print(f"Note: {source['wheelhouse_skipped']}.")

    run_dir = Path(tempfile.mkdtemp(prefix="e2er-reproduce-"))
    try:
        return _run_in(root, recipe, run_dir, keep=keep, json_out=json_out, allow_network=allow_network)
    finally:
        if keep:
            print(f"The run folder is kept: {run_dir}")
        else:
            shutil.rmtree(run_dir, ignore_errors=True)


def _run_in(
    root: Path, recipe: dict[str, Any], run_dir: Path, *, keep: bool, json_out: str | None, allow_network: bool
) -> int:
    logs = run_dir / ".e2er-logs"
    logs.mkdir()
    where = str(run_dir) if keep else f"a temporary folder ({run_dir}, removed afterwards; --keep keeps it)"
    print(f"Running the study's code in {where}; the study folder is not changed ...", flush=True)
    env_info: dict[str, Any] | None = None
    steps: list[rp.StepResult] = []
    inputs: list[dict[str, Any]] = []
    files: list[rp.FileComparison] = []
    tables: dict[str, Any] | None = None
    try:
        rp.lay_out(root, run_dir, recipe)  # without the results it is to write: the rerun must write them
        python, env_info = rp.make_environment(run_dir, recipe, root, logs)
        steps = rp.run_steps(run_dir, recipe, rp.step_env(python, run_dir), logs, python, allow_network=allow_network)
    except rp.RecipeError as e:
        print(f"error: {e}")
        inputs = rp.compare_inputs(run_dir, recipe.get("inputs") or [])
        print(_inputs_only(recipe, inputs), end="")
        return 2
    # The inputs are compared also when a step failed: the reader sees what the rerun had.
    inputs = rp.compare_inputs(run_dir, recipe.get("inputs") or [])
    ran = bool(steps) and not any(s.exit_code for s in steps)
    if ran:
        files = [
            rp.compare_json(root / c["published"], run_dir / c["produced"], c["published"], c["produced"])
            for c in recipe["compare"]
        ]
        tables = rp.compare_tables(root, run_dir, recipe["compare"])
    verdict, code = rp.verdict(files, tables, steps, inputs)
    print()
    print(render(root, recipe, env_info, steps, inputs, files, tables, verdict, kept=keep), end="")
    if json_out:
        doc = {
            "schema": "e2er-reproduce-report/1",
            "folder": str(root),
            "environment": env_info,
            "steps": [s.as_dict() for s in steps],
            "inputs": inputs,
            "allow_network": allow_network,
            "results": [f.as_dict() for f in files],
            "tables": tables,
            "verdict": verdict,
            "exit_code": code,
            "run_folder_kept": keep,
        }
        Path(json_out).expanduser().write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")
        print(f"Report written to {json_out}")
    return code
