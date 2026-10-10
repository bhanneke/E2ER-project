"""Re-run a study's own code and compare what it produces with what the study published.

``e2er reproduce <folder>`` reads the folder's ``reproduce.json``, which says
how the study's code is run again:

    {
      "schema": "e2er-reproduce/1",
      "python": "3.12",                          # optional; else the Python e2er runs on
      "requirements": "code/requirements.txt",   # pinned packages, installed in a new environment
      "files": {"run_estimation.py": "code/run_estimation.py"},   # run folder <- study folder
      "steps": [{"run": ["python", "run_estimation.py"], "about": "estimate the models"}],
      "inputs": [{"path": "data/x.csv", "sha256": "…", "source": "…"}],   # + "reload": "get_data.py" when a
                                                 # step loads it again if the folder does not ship it
      "compare": [{"published": "results/estimation_results.json", "produced": "estimation_results.json"}],
      "notes": ["…"]
    }

The code runs in a run folder of its own (``files`` lays out the folder the
code was written for; without it the whole study folder is copied), inside a
new virtual environment with the pinned requirements. The study folder itself
is never written to.

Afterwards every compared JSON file is read value by value. A value is
*identical*, *the same at the published precision* (the rerun rounds to the
published number at the decimals the study printed), shows *small differences*
(within the replication path's minor tolerance and without a change of sign),
or *differs*. Inputs listed with a SHA-256 are compared with the study's own
files. When the study ships rendered tables and their spec, the tables are
rendered again from the rerun's results and compared with the paper's.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
import sysconfig
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .pipeline.reproduction import DEFAULT_MINOR_REL_TOLERANCE, _claimed_decimals, _equal_at, label_from

RECIPE_FILE = "reproduce.json"
SCHEMA = "e2er-reproduce/1"
DEFAULT_STEP_TIMEOUT_MINUTES = 60

#: Labels for one compared value, in the order the report lists them.
IDENTICAL = "identical"
AT_PRECISION = "same_at_precision"
MINOR = "small_difference"
DIFFERS = "differs"
MISSING = "missing_in_rerun"
NEW = "only_in_rerun"
LABELS = (IDENTICAL, AT_PRECISION, MINOR, DIFFERS, MISSING, NEW)
#: What a reader may call reproduced.
MATCHING = frozenset({IDENTICAL, AT_PRECISION})

LABEL_WORDS = {
    IDENTICAL: "identical",
    AT_PRECISION: "same at the published precision",
    MINOR: "small differences",
    DIFFERS: "differ",
    MISSING: "missing from the rerun",
    NEW: "only in the rerun",
}


#: A compared result file the rerun did not write.
NOT_WRITTEN = "the rerun did not write it"


class RecipeError(Exception):
    """reproduce.json is missing or does not say how to run the study."""


# ── the recipe ───────────────────────────────────────────────────────────────


def _safe_rel(path: Any) -> bool:
    if not isinstance(path, str) or not path.strip():
        return False
    p = Path(path)
    return not p.is_absolute() and ".." not in p.parts and not path.startswith(("/", "\\"))


def load_recipe(folder: Path) -> dict[str, Any]:
    """reproduce.json, checked; RecipeError says what is wrong in plain words."""
    path = folder / RECIPE_FILE
    if not path.is_file():
        from .export.reproduce_recipe import folder_reason

        why = folder_reason(folder)
        raise RecipeError(
            f"{folder} has no {RECIPE_FILE}, the file that says how to run the study's code again "
            "(which environment, which steps, which results to compare). " + (why or "See `e2er reproduce --help`.")
        )
    try:
        recipe = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise RecipeError(f"{RECIPE_FILE} cannot be read: {e}") from e
    if not isinstance(recipe, dict):
        raise RecipeError(f"{RECIPE_FILE} must hold a JSON object")
    problems: list[str] = []
    if recipe.get("schema") != SCHEMA:
        problems.append(f'"schema" must be "{SCHEMA}"')
    req = recipe.get("requirements")
    if not _safe_rel(req):
        problems.append('"requirements" must name the pinned requirements file inside the folder')
    elif not (folder / str(req)).is_file():
        problems.append(f"the requirements file {req} is not in the folder")
    files = recipe.get("files")
    if files is not None:
        if not isinstance(files, dict) or not files:
            problems.append('"files" must map run-folder paths to files in the study folder')
        else:
            reloaded = reloaded_inputs(recipe)
            for dst, src in files.items():
                if not (_safe_rel(dst) and _safe_rel(src)):
                    problems.append(f'"files": {dst!r} -> {src!r} is not a relative path inside the folder')
                elif not (folder / src).exists() and dst not in reloaded:
                    problems.append(f'"files": {src} is not in the folder')
    steps = recipe.get("steps")
    if not isinstance(steps, list) or not steps:
        problems.append('"steps" must list at least one command')
    else:
        for i, step in enumerate(steps, 1):
            run = step.get("run") if isinstance(step, dict) else None
            if not (isinstance(run, str) and run.strip()) and not (
                isinstance(run, list) and run and all(isinstance(a, str) for a in run)
            ):
                problems.append(f'step {i} has no command ("run")')
    compare = recipe.get("compare")
    if not isinstance(compare, list) or not compare:
        problems.append('"compare" must list at least one published result and the file the rerun writes')
    else:
        for c in compare:
            if not (isinstance(c, dict) and _safe_rel(c.get("published")) and _safe_rel(c.get("produced"))):
                problems.append(f'"compare": {c!r} needs a "published" and a "produced" path')
            elif not (folder / c["published"]).is_file():
                problems.append(f'"compare": {c["published"]} is not in the folder')
    for item in recipe.get("inputs") or []:
        if not (isinstance(item, dict) and _safe_rel(item.get("path")) and isinstance(item.get("sha256"), str)):
            problems.append(f'"inputs": {item!r} needs a "path" and a "sha256"')
    if problems:
        raise RecipeError(f"{RECIPE_FILE}: " + "; ".join(problems))
    return recipe


def reloaded_inputs(recipe: dict[str, Any]) -> set[str]:
    """Run-folder paths of inputs a step loads again when the folder does not ship them (``"reload"``)."""
    return {
        str(i["path"])
        for i in recipe.get("inputs") or []
        if isinstance(i, dict) and isinstance(i.get("path"), str) and i.get("reload")
    }


def step_argv(step: dict[str, Any]) -> list[str]:
    run = step["run"]
    return shlex.split(run) if isinstance(run, str) else list(run)


# ── comparing values ─────────────────────────────────────────────────────────


def flatten(doc: Any, prefix: str = "") -> dict[str, Any]:
    """Every leaf of a JSON document, by its path (``main/coefficients/x/estimate``, ``series[3]``)."""
    out: dict[str, Any] = {}
    if isinstance(doc, dict):
        if not doc and prefix:
            out[prefix] = {}
        for k, v in doc.items():
            out.update(flatten(v, f"{prefix}/{k}" if prefix else str(k)))
    elif isinstance(doc, list):
        if not doc and prefix:
            out[prefix] = []
        for i, v in enumerate(doc):
            out.update(flatten(v, f"{prefix}[{i}]"))
    else:
        out[prefix] = doc
    return out


def _is_number(x: Any) -> bool:
    return isinstance(x, int | float) and not isinstance(x, bool)


def _rounded(value: float) -> bool:
    """Was the published number stored rounded? Only a number with four or more significant digits counts:
    ``0.00285433`` was rounded at 8 decimals, while ``1.0`` or ``0.5`` may well be exact."""
    text = repr(float(value)).lower().lstrip("-")
    mantissa = text.split("e")[0].replace(".", "").lstrip("0")
    return len(mantissa.rstrip("0") if "e" not in text and "." in text else mantissa) >= 4


def compare_value(published: Any, produced: Any) -> tuple[str, float | None]:
    """(label, relative difference) for one value."""
    if _is_number(published) and _is_number(produced):
        p, q = float(published), float(produced)
        if math.isnan(p) and math.isnan(q):
            return IDENTICAL, 0.0
        if p == q:
            return IDENTICAL, 0.0
        if not (math.isfinite(p) and math.isfinite(q)):
            return DIFFERS, None
        rel = abs(q - p) / max(abs(p), abs(q), 1e-300)
        if _rounded(published) and _equal_at(q, p, _claimed_decimals(published)):
            return AT_PRECISION, rel
        label = label_from(False, rel, (p > 0 > q) or (p < 0 < q), DEFAULT_MINOR_REL_TOLERANCE)
        return (MINOR if label == "reproduced_minor" else DIFFERS), rel
    if isinstance(published, bool) != isinstance(produced, bool):
        return DIFFERS, None
    if published == produced:
        return IDENTICAL, 0.0
    return DIFFERS, None


@dataclass
class FileComparison:
    published: str
    produced: str
    counts: dict[str, int] = field(default_factory=lambda: dict.fromkeys(LABELS, 0))
    #: (relative difference or None, path, published, rerun) for every value that does not match
    differences: list[tuple[float | None, str, Any, Any]] = field(default_factory=list)
    problem: str | None = None

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    @property
    def matches(self) -> bool:
        return self.problem is None and all(self.counts[k] == 0 for k in LABELS if k not in MATCHING)

    def largest(self, n: int = 5) -> list[tuple[float | None, str, Any, Any]]:
        """The n largest differences: text and missing values first, then by relative size."""
        return sorted(self.differences, key=lambda d: (-(math.inf if d[0] is None else d[0]), d[1]))[:n]

    def as_dict(self) -> dict[str, Any]:
        return {
            "published": self.published,
            "produced": self.produced,
            "values": self.total,
            "counts": self.counts,
            "matches": self.matches,
            "problem": self.problem,
            "largest_differences": [
                {"path": p, "published": a, "rerun": b, "relative_difference": r} for r, p, a, b in self.largest(20)
            ],
        }


def compare_json(published_path: Path, produced_path: Path, published: str, produced: str) -> FileComparison:
    fc = FileComparison(published, produced)
    try:
        pub = json.loads(published_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        fc.problem = f"the published file cannot be read: {e}"
        return fc
    if not produced_path.is_file():
        fc.problem = NOT_WRITTEN
        return fc
    try:
        new = json.loads(produced_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        fc.problem = f"the rerun wrote a file that is not JSON: {e}"
        return fc
    a, b = flatten(pub), flatten(new)
    for key in a:
        if key not in b:
            fc.counts[MISSING] += 1
            fc.differences.append((None, key, a[key], None))
            continue
        label, rel = compare_value(a[key], b[key])
        fc.counts[label] += 1
        if label not in MATCHING:
            fc.differences.append((rel, key, a[key], b[key]))
    for key in b.keys() - a.keys():
        fc.counts[NEW] += 1
        fc.differences.append((None, key, None, b[key]))
    return fc


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def compare_inputs(run_dir: Path, inputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each declared input as the rerun has it: identical to the study's file, different, or missing."""
    out = []
    for item in inputs:
        path = run_dir / item["path"]
        if not path.is_file():
            status = "missing"
        else:
            status = "identical" if sha256_file(path) == item["sha256"] else "differs"
        out.append({"path": item["path"], "source": item.get("source"), "status": status})
    return out


def compare_tables(folder: Path, run_dir: Path, compare: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Render the paper's tables again from the rerun's results; None when the study ships none."""
    spec = folder / "results" / "table_spec.json"
    shipped = folder / "paper" / "tables"
    if not spec.is_file() or not shipped.is_dir():
        return None
    from .renderer.tables import render_tables

    ws = run_dir / ".e2er-tables"
    ws.mkdir(exist_ok=True)
    for f in (folder / "results").glob("*.json"):
        shutil.copy2(f, ws / f.name)
    for c in compare:
        produced = run_dir / c["produced"]
        if produced.is_file() and c["published"].startswith("results/"):
            shutil.copy2(produced, ws / Path(c["published"]).name)
    quiet = logging.getLogger("src.core.renderer.tables")
    level = quiet.level
    quiet.setLevel(logging.WARNING)  # the renderer's progress line is not part of the report
    try:
        report = render_tables(ws)
    finally:
        quiet.setLevel(level)
    if report.skipped_reason:
        return {"skipped": report.skipped_reason}
    identical, differ, not_shipped = [], [], []
    for name in report.rendered:
        old = shipped / name
        if not old.is_file():
            not_shipped.append(name)
        elif old.read_bytes() == (ws / "tables" / name).read_bytes():
            identical.append(name)
        else:
            differ.append(name)
    return {"rendered": len(report.rendered), "identical": identical, "differ": differ, "not_shipped": not_shipped}


# ── running ──────────────────────────────────────────────────────────────────


def _venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _run(argv: list[str], *, cwd: Path, env: dict[str, str] | None, timeout: float, log: Path) -> tuple[int, str]:
    """Run a command, write its output to ``log``; (exit code, last lines of the output)."""
    try:
        proc = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        log.write_text(f"stopped after {timeout:.0f} s\n", encoding="utf-8")
        return 124, f"stopped after {timeout / 60:.0f} minutes"
    except OSError as e:
        log.write_text(f"{e}\n", encoding="utf-8")
        return 127, str(e)
    log.write_text((proc.stdout or "") + (proc.stderr or ""), encoding="utf-8")
    tail = "\n".join(((proc.stderr or "") + (proc.stdout or "")).strip().splitlines()[-6:])
    return proc.returncode, tail


def make_environment(run_dir: Path, recipe: dict[str, Any], folder: Path, logs: Path) -> tuple[Path, dict[str, Any]]:
    """A new virtual environment with the pinned requirements; (its python, what was installed)."""
    venv = run_dir / ".venv"
    requirements = (folder / recipe["requirements"]).resolve()
    wanted = str(recipe.get("python") or "").strip()
    uv = shutil.which("uv")
    if uv:
        base = getattr(sys, "_base_executable", None) or sys.executable  # the interpreter, not e2er's own venv
        create = [uv, "venv", "--quiet", "--python", wanted or base, str(venv)]
        install = [uv, "pip", "install", "--quiet", "--python", str(_venv_python(venv)), "-r", str(requirements)]
    else:
        if wanted and not f"{sys.version_info.major}.{sys.version_info.minor}".startswith(wanted):
            raise RecipeError(
                f"the study asks for Python {wanted}, e2er runs on {sys.version.split()[0]}, and uv (which can "
                "fetch another Python) is not installed: install uv, or run e2er on Python " + wanted
            )
        create = [sys.executable, "-m", "venv", str(venv)]
        install = [str(_venv_python(venv)), "-m", "pip", "install", "--quiet", "-r", str(requirements)]
    code, tail = _run(create, cwd=run_dir, env=minimal_env(), timeout=600, log=logs / "environment-create.log")
    if code != 0:
        raise RecipeError(f"could not create the environment: {tail}")
    code, tail = _run(install, cwd=run_dir, env=minimal_env(), timeout=1800, log=logs / "environment-install.log")
    if code != 0:
        raise RecipeError(f"could not install {recipe['requirements']}: {tail}")
    py = _venv_python(venv)
    probe = (
        "import json, sys, importlib.metadata as m; "
        "print(json.dumps({'python': sys.version.split()[0], "
        "'packages': {d.metadata['Name']: d.version for d in m.distributions()}}))"
    )
    out = subprocess.run(
        [str(py), "-I", "-c", probe], cwd=run_dir, env=minimal_env(), capture_output=True, text=True, timeout=120
    )
    try:
        info = json.loads(out.stdout)
    except ValueError:
        info = {"python": "unknown", "packages": {}}
    info["installer"] = "uv" if uv else "pip"
    return py, info


#: What the study's code and its installer get from e2er's environment: where things are, the
#: language, temporary folders, proxies and certificates. No API key, token or e2er setting:
#: the code is someone else's, and it runs on this machine.
_PASSED_ON = frozenset(
    {
        "PATH", "HOME", "USER", "LOGNAME", "SHELL", "TERM", "TZ", "LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE",
        "TMPDIR", "TEMP", "TMP", "XDG_CACHE_HOME",
        "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "no_proxy", "all_proxy",
        "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
        "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "APPDATA", "LOCALAPPDATA", "USERPROFILE",
        "PROGRAMDATA", "PROGRAMFILES",
    }
)  # fmt: skip
#: The installers' own settings (an index mirror, a cache folder), unless they hold a credential.
_INSTALLER_PREFIXES = ("UV_", "PIP_")
_CREDENTIAL = re.compile(r"TOKEN|PASSWORD|SECRET|KEY|AUTH|CREDENTIAL", re.I)


def minimal_env() -> dict[str, str]:
    """The environment someone else's code (and the installation of its packages) runs with."""
    return {
        k: v
        for k, v in os.environ.items()
        if k in _PASSED_ON or (k.startswith(_INSTALLER_PREFIXES) and not _CREDENTIAL.search(k))
    }


def step_env(venv_python: Path) -> dict[str, str]:
    """The steps' environment: the minimal one (no keys), the new environment first; e2er-data from the running e2er."""
    env = minimal_env()
    venv_bin = venv_python.parent
    scripts = sysconfig.get_path("scripts") or str(Path(sys.executable).parent)
    env["PATH"] = os.pathsep.join([str(venv_bin), scripts, env.get("PATH", "")])
    env["VIRTUAL_ENV"] = str(venv_bin.parent)
    env["PYTHON_COLORS"] = "0"  # plain tracebacks in the logs and the report
    e2er_data = shutil.which("e2er-data", path=scripts) or shutil.which("e2er-data")
    if e2er_data:
        env["E2ER_DATA"] = e2er_data
    return env


def lay_out(folder: Path, run_dir: Path, recipe: dict[str, Any]) -> list[str]:
    """Lay out the run folder; returns the result files that were removed from it.

    Every file the rerun is to write (``compare`` → ``produced``) is taken out of
    the run folder before the steps run. Copied with the study, a published result
    would otherwise be there already, and a script that writes nothing would be
    compared with the published file itself and "reproduce" it.
    """
    files = recipe.get("files")
    if not files:
        shutil.copytree(folder, run_dir, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git", ".venv"))
    else:
        for dst, src in files.items():
            source, target = folder / src, run_dir / dst
            if not source.exists():
                continue  # an input the folder does not ship; a step loads it again (load_recipe checked)
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, target, dirs_exist_ok=True)
            else:
                shutil.copy2(source, target)
    removed = []
    for c in recipe.get("compare") or []:
        produced = run_dir / c["produced"]
        if produced.is_file():
            produced.unlink()
            removed.append(c["produced"])
    return removed


@dataclass
class StepResult:
    command: str
    about: str
    exit_code: int
    seconds: float
    tail: str
    log: str

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def run_steps(run_dir: Path, recipe: dict[str, Any], env: dict[str, str], logs: Path, python: Path) -> list[StepResult]:
    """Run the steps in order; stop at the first that fails. ``python`` runs every ``python …`` step."""
    results = []
    for i, step in enumerate(recipe["steps"], 1):
        argv = step_argv(step)
        if argv and argv[0] in ("python", "python3"):
            argv = [str(python), *argv[1:]]
        timeout = float(step.get("timeout_minutes") or DEFAULT_STEP_TIMEOUT_MINUTES) * 60
        log = logs / f"step-{i}.log"
        started = time.monotonic()
        code, tail = _run(argv, cwd=run_dir, env=env, timeout=timeout, log=log)
        results.append(
            StepResult(
                command=shlex.join(step_argv(step)),
                about=str(step.get("about") or ""),
                exit_code=code,
                seconds=round(time.monotonic() - started, 1),
                tail=tail if code else "",
                log=str(log),
            )
        )
        if code != 0:
            break
    return results


def verdict(
    files: list[FileComparison],
    tables: dict[str, Any] | None,
    steps: list[StepResult],
    inputs: list[dict[str, Any]] | None = None,
) -> tuple[str, int]:
    """(one plain sentence, exit code): 0 reproduced, 1 differences, 2 could not run.

    "Reproduced" needs every compared value to match, every table to render the
    same and every declared input to be the study's own file: the same results
    from other data are not a reproduction of the study.
    """
    if any(s.exit_code for s in steps):
        failed = next(s for s in steps if s.exit_code)
        return f"Could not reproduce: the step `{failed.command}` failed.", 2
    unwritten = [f.published for f in files if f.problem == NOT_WRITTEN]
    if files and len(unwritten) == len(files):
        return (
            "Not reproduced: the study's code ran but wrote none of the result files it is compared on "
            f"({', '.join(f.produced for f in files)}).",
            1,
        )
    compared = [f for f in files if f.problem is None]

    def count(label: str) -> int:
        return sum(f.counts[label] for f in compared)

    bad_files = [f.published for f in files if f.problem]
    bad_tables = len((tables or {}).get("differ") or []) + len((tables or {}).get("not_shipped") or [])
    other = [i for i in inputs or [] if i.get("status") == "differs"]
    absent = [i for i in inputs or [] if i.get("status") == "missing"]
    if (
        not any(count(k) for k in LABELS if k not in MATCHING)
        and not bad_files
        and not bad_tables
        and not (other or absent)
    ):
        tail = " and every table renders the same" if tables and tables.get("rendered") else ""
        return f"Reproduced: every compared value is identical or the same at the published precision{tail}.", 0
    parts = []
    if count(MINOR):
        parts.append(f"{count(MINOR)} value(s) show small differences")
    if count(DIFFERS):
        parts.append(f"{count(DIFFERS)} differ")
    if count(MISSING) or count(NEW):
        parts.append(f"{count(MISSING)} missing from the rerun, {count(NEW)} only in the rerun")
    if bad_files:
        parts.append(f"{len(bad_files)} result file(s) could not be compared ({', '.join(bad_files)})")
    if bad_tables:
        parts.append(f"{bad_tables} table(s) render differently")
    if other:
        parts.append(f"{len(other)} input file(s) differ from the study's ({', '.join(i['path'] for i in other[:3])})")
    if absent:
        parts.append(f"{len(absent)} input file(s) are missing ({', '.join(i['path'] for i in absent[:3])})")
    return "Not reproduced exactly: " + "; ".join(parts) + ".", 1
