"""``e2er reproduce <folder>`` — run a study's code again and compare the results with the published ones.

How the code is run is the study's own ``reproduce.json`` (see
``src/core/reproduce.py``). The study folder is never written to: the code
runs in a run folder of its own, in a new virtual environment with the
study's pinned requirements. Exit codes: 0 reproduced, 1 differences,
2 could not run.

The steps are the author's code. Before anything runs the command lists each
step's exact command and the requirements, says how they run (in the Docker
sandbox, or with ``--no-sandbox`` on this computer as the user), and asks;
``--yes`` answers for a script. Steps that load inputs from the web ask on their
own. Without Docker nothing runs unless ``--no-sandbox`` is given.
"""

from __future__ import annotations

import json
import shlex
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .core import reproduce as rp
from .core.safe_text import printable


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
    rebuilt = [i for i in inputs if i.get("output")]
    inputs = [i for i in inputs if not i.get("output")]
    lines += ["", "Inputs, compared with the study's own files (SHA-256):"]
    declared = [i for i in recipe.get("inputs") or [] if not (isinstance(i, dict) and i.get("output"))]
    if not declared:
        lines.append("  the study's reproduce.json lists no inputs")
    elif not inputs:
        lines.append(f"  not compared: the run stopped before the inputs were laid out ({len(declared)} listed)")
    else:
        same = [i for i in inputs if i["status"] in ("identical", rp.SAME_ROWS)]
        reordered = [i["path"] for i in inputs if i["status"] == rp.SAME_ROWS]
        close = [i["path"] for i in inputs if i["status"] == rp.SAME_NUMBERS]
        differ = [i for i in inputs if i["status"] == "differs"]
        missing = [i["path"] for i in inputs if i["status"] == "missing"]
        lines.append(f"  {len(same)} of {len(inputs)} identical")
        if reordered:
            lines.append(
                f"  {len(reordered)} with the same rows in a different order (identical content): "
                + ", ".join(reordered)
            )
        if close:
            lines.append(
                f"  {len(close)} with the same rows, every decimal number equal to {rp.NUMERIC_DIGITS} significant "
                f"digits (the last digits differ): " + ", ".join(close)
            )
        if differ:
            named = [
                i["path"] + (f" (tables {', '.join(i['tables_differ'])})" if i.get("tables_differ") else "")
                for i in differ
            ]
            lines.append(f"  {len(differ)} differ: {', '.join(named)}")
        if missing:
            lines.append(f"  {len(missing)} missing: {', '.join(missing)}")
    if rebuilt:
        lines += ["", "Files a published folder leaves out (they hold a source's rows), as the rerun wrote them:"]
        words = {
            "identical": "identical to the study's file",
            rp.SAME_ROWS: "the study's rows, in another order",
            rp.SAME_NUMBERS: f"the study's rows, decimal numbers equal to {rp.NUMERIC_DIGITS} significant digits",
            "differs": "differs from the study's file",
            "missing": "not built",
        }
        for entry in rebuilt:
            if entry["status"] == rp.NOT_COMPARED:
                lines.append(f"  {entry['path']}: {entry.get('why') or 'not compared'}")
                continue
            lines.append(f"  {entry['path']}: {words.get(entry['status'], entry['status'])}")
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
            if tables.get("not_compared"):
                lines.append(
                    f"  {len(tables['not_compared'])} not compared (they read results the rerun did not write "
                    f"again): {', '.join(sorted(tables['not_compared']))}"
                )
    notes = [n for n in recipe.get("notes") or [] if isinstance(n, str)]
    if notes:
        lines += ["", "Notes from the study's reproduce.json:"] + [f"  - {n}" for n in notes]
    lines += ["", verdict]
    return "\n".join(lines) + "\n"


def _integrity_first(root: Path, recipe: dict[str, Any]) -> tuple[str | None, str | None]:
    """(a qualifier for the verdict, or why the folder is not run): the folder must be the study as exported.

    A folder whose files are not the ones provenance.json lists (reproduce.json included) is not the study, and a
    rerun of it says nothing about the study: refused. Files may be absent where the study's own records say
    why and the rerun gets them back: a source's terms keep them out (data_terms.restricted_paths), a supported
    package declaration, or an input the recipe loads or builds again. A folder without provenance.json runs,
    and the verdict says that nothing ties it to a study.
    """
    if not (root / "provenance.json").exists():
        return (
            "This folder has no provenance.json, so nothing ties its files (reproduce.json included) to a "
            "published study: the rerun says only what this folder's code produces.",
            None,
        )
    from .cli_verify import FAIL, _check_integrity
    from .core.data_terms import restricted_paths
    from .core.export import package as pkg

    files: dict[str, Any] = recipe["files"] if isinstance(recipe.get("files"), dict) else {}
    absent_ok: dict[str, dict[str, Any]] = dict(pkg.supported_left_out(root))
    for rel, why in restricted_paths(root).items():
        absent_ok.setdefault(rel, {"path": rel, "reason": why})
    for run_path in rp.optional_inputs(recipe):
        rel = str(files.get(run_path, run_path))
        absent_ok.setdefault(rel, {"path": rel, "reason": "the study's code loads or builds it again"})
    integrity = _check_integrity(root, absent_ok)
    if integrity.status == FAIL:
        return None, (
            f"error: the folder is not the study as exported, so it is not run: {integrity.detail}. "
            "`e2er verify` shows what changed."
        )
    return None, None


def _inputs_only(recipe: dict[str, Any], inputs: list[dict[str, Any]]) -> str:
    """The inputs section alone, for a run that stopped before its steps."""
    text = render(Path(""), {**recipe, "steps": []}, None, [], inputs, [], None, "")
    start = text.find("Inputs, compared")
    return "\n" + text[start:].rstrip() + "\n" if start >= 0 else ""


def _interactive() -> bool:
    import sys

    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def _ask(question: str) -> bool:
    try:
        return input(question).strip().lower() in ("y", "yes")
    except EOFError:
        return False


def plan_text(root: Path, recipe: dict[str, Any], *, sandboxed: bool, base: str = "") -> str:
    """What will run, before it runs: every step's exact command, the requirements, and as whom."""
    lines = ["", "The study's reproduce.json runs these commands, in this order:"]
    for i, step in enumerate(recipe["steps"], 1):
        cmd = printable(shlex.join(rp.step_argv(step)), newlines=False)
        tags = []
        if rp.is_reload_step(step, recipe):
            tags.append("loads inputs from the web")
        if isinstance(step.get("when_missing"), list) and step["when_missing"]:
            tags.append("only when the folder lacks " + ", ".join(map(str, step["when_missing"])))
        about = f"  ({printable(step.get('about'), newlines=False)})" if step.get("about") else ""
        lines.append(f"  {i}. {cmd}{about}" + (f"  [{'; '.join(tags)}]" if tags else ""))
    req = root / str(recipe["requirements"])
    try:
        pins = rp.requirement_lines(req)
    except OSError:
        pins = []
    shown = ", ".join(printable(x, newlines=False) for x in pins[:40]) or "no packages"
    more = f" and {len(pins) - 40} more" if len(pins) > 40 else ""
    lines.append(f"Requirements ({printable(recipe['requirements'], newlines=False)}): {shown}{more}")
    if sandboxed:
        lines += [
            "",
            f"These commands are the author's code. They run in a Docker container ({base}): no network, a",
            "read-only system, no folder of yours but the run folder, no API key or token.",
        ]
    else:
        lines += [
            "",
            "These commands are the author's code, and with --no-sandbox they run on this computer AS YOU:",
            "they can read and change every file you can. e2er points HOME at an empty folder and passes no",
            "API key or token, but that is not a sandbox. Run a study from someone you do not know in Docker.",
        ]
    return "\n".join(lines) + "\n"


def reproduce(
    folder: str,
    *,
    keep: bool = False,
    json_out: str | None = None,
    allow_network: bool = False,
    yes: bool = False,
    sandbox: bool | None = None,
    allow_reload: bool | None = None,
) -> int:
    """`e2er reproduce`. The run folder and an unpacked package are temporary: removed when the command ends,
    also after a failure, unless ``keep`` (then the report says where they are).

    ``sandbox``: None runs the steps in Docker when Docker answers and refuses otherwise; False is
    ``--no-sandbox`` (on this computer, as the user); True requires Docker. ``yes`` answers the
    question before the steps run; ``allow_reload`` the one for the steps that load inputs from
    the web (None: asked, or ``yes``)."""
    opts: dict[str, Any] = {"yes": yes, "sandbox": sandbox, "allow_reload": allow_reload}
    from .core.export import package as pkg

    path = Path(folder).expanduser().resolve()
    if not pkg.is_package(path):
        return _reproduce_folder(path, keep=keep, json_out=json_out, allow_network=allow_network, **opts)
    # A .e2er package: unpacked into a folder of its own, every file checked against the manifest first.
    unpacked = Path(tempfile.mkdtemp(prefix="e2er-package-"))
    try:
        try:
            opened = pkg.open_package(path, unpacked / "study")
        except pkg.PackageError as e:
            print(f"error: the package is not intact: {e}")
            return 2
        print(
            f"Unpacked {printable(path.name, newlines=False)} into {opened.root}: {opened.files} file(s) match "
            f"{pkg.MANIFEST} (fingerprint {printable(opened.manifest.get('fingerprint'), newlines=False)}).",
            flush=True,
        )
        code = _reproduce_folder(
            opened.root, keep=keep, json_out=json_out, allow_network=allow_network, package=True, **opts
        )
        if keep:
            print(f"The unpacked package is kept: {opened.root}")
        return code
    finally:
        if not keep:
            shutil.rmtree(unpacked, ignore_errors=True)


def _reproduce_folder(
    root: Path,
    *,
    keep: bool,
    json_out: str | None,
    allow_network: bool,
    package: bool = False,
    yes: bool = False,
    sandbox: bool | None = None,
    allow_reload: bool | None = None,
) -> int:
    from .core.export import package as pkg

    if not root.is_dir():
        print(f"error: {root} is not a folder or a .e2er package")
        return 2
    rebuild = pkg.rebuild_steps(root)
    try:
        recipe = rp.load_recipe(root, rebuild=rebuild)
    except rp.RecipeError as e:
        print(f"error: {printable(e)}")
        return 2
    qualifier, refused = _integrity_first(root, recipe)
    if refused:
        print(refused)
        return 2
    # A left-out output the step only updates (figure_spec.json, produced by the figure step): not compared.
    from .core.derived_data import not_produced_by_step

    not_produced = not_produced_by_step(root, recipe)
    for item in recipe.get("inputs") or []:
        if isinstance(item, dict) and str(item.get("path")) in not_produced:
            item["not_compared"] = not_produced[str(item["path"])]
    try:
        own = json.loads((root / rp.RECIPE_FILE).read_text(encoding="utf-8")).get("steps") or []
    except (OSError, ValueError, AttributeError):
        own = []
    ran = {Path(a).name for st in own if isinstance(st, dict) for a in rp.step_argv(st)}
    built = sorted(
        {str(r["from"]) for r in rebuild if not r.get("written") and r.get("from") and str(r.get("script")) not in ran}
    )
    if built:
        # The recipe's own notes were written before the package left these files out.
        recipe.setdefault("notes", []).append(
            f"{pkg.MANIFEST} adds the steps that build the files it left out again: " + ", ".join(built) + "."
        )
    # Files a package left out carry the fingerprints pack recorded; an older recipe gets the numbers one.
    rp.add_numeric_fingerprints(recipe, pkg.left_out_content(root, trusted=package))
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

    try:
        rp.check_foreign(root, recipe)
    except rp.RecipeError as e:
        print(f"error: {printable(e)}")
        return 2

    # Where the steps run: the Docker sandbox when it answers; on this computer only with --no-sandbox.
    from .core import reproduce_sandbox as rs

    docker: str | None = None
    if sandbox is not False:
        docker, why = rs.available()
        if docker is None:
            print(
                f"error: nothing was run. {why}.\ne2er reproduce runs the study's code in a Docker sandbox: start "
                "Docker (or install it: https://docs.docker.com/get-docker/) and run the command again. --no-sandbox "
                "runs the code on this computer as you instead: only for a study whose code you trust."
            )
            return 2
    base = f"python:{rs.python_version(recipe)}-slim"
    print(plan_text(root, recipe, sandboxed=docker is not None, base=base), end="")
    if not yes:
        if not _interactive():
            print("Nothing was run: without a terminal to ask in, --yes runs these commands.")
            return 2
        if not _ask("Run them? [y/N] "):
            print("Nothing was run.")
            return 2
    reloads = [i for i, st in enumerate(recipe["steps"], 1) if rp.is_reload_step(st, recipe)]
    if allow_reload is None:
        if yes or not reloads:
            allow_reload = True
        else:
            allow_reload = _ask(
                f"Step(s) {', '.join(map(str, reloads))} load inputs from the web again. Let them use the network "
                "(without your API keys)? [y/N] "
            )
    if reloads and not allow_reload:
        print("The steps that load inputs run without the network; they fail when they need it.")

    run_dir = Path(tempfile.mkdtemp(prefix="e2er-reproduce-"))
    try:
        return _run_in(
            root,
            recipe,
            run_dir,
            keep=keep,
            json_out=json_out,
            allow_network=allow_network,
            docker=docker,
            allow_reload=bool(allow_reload),
            qualifier=qualifier,
        )
    finally:
        if keep:
            print(f"The run folder is kept: {run_dir}")
        else:
            shutil.rmtree(run_dir, ignore_errors=True)


def _run_in(
    root: Path,
    recipe: dict[str, Any],
    run_dir: Path,
    *,
    keep: bool,
    json_out: str | None,
    allow_network: bool,
    docker: str | None = None,
    allow_reload: bool = True,
    qualifier: str | None = None,
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
        if docker is not None:
            from .core import reproduce_sandbox as rs

            box, env_info = rs.prepare(run_dir, recipe, root, logs, docker=docker)
            steps = rp.run_steps(
                run_dir,
                recipe,
                rs.step_env(box, run_dir),
                logs,
                f"{rs.STUDY_VENV}/bin/python",
                allow_network=allow_network,
                allow_reload=allow_reload,
                runner=rs.step_runner(box, run_dir),
                log_path=lambda p: rs.in_box(p, run_dir),
            )
        else:
            python, env_info = rp.make_environment(run_dir, recipe, root, logs)
            steps = rp.run_steps(
                run_dir,
                recipe,
                rp.step_env(python, run_dir),
                logs,
                python,
                allow_network=allow_network,
                allow_reload=allow_reload,
            )
    except rp.RecipeError as e:
        print(f"error: {printable(e)}")
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
    if qualifier:
        verdict = f"{qualifier} {verdict}"
    print()
    print(printable(render(root, recipe, env_info, steps, inputs, files, tables, verdict, kept=keep)), end="")
    if json_out:
        doc = {
            "schema": "e2er-reproduce-report/1",
            "folder": str(root),
            "environment": env_info,
            "steps": [s.as_dict() for s in steps],
            "inputs": inputs,
            "allow_network": allow_network,
            "sandbox": (env_info or {}).get("sandbox") if docker is not None else None,
            "results": [f.as_dict() for f in files],
            "tables": tables,
            "verdict": verdict,
            "exit_code": code,
            "run_folder_kept": keep,
        }
        Path(json_out).expanduser().write_text(json.dumps(doc, indent=2, default=str) + "\n", encoding="utf-8")
        print(f"Report written to {json_out}")
    return code
