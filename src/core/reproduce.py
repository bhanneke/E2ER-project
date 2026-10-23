"""Re-run a study's own code and compare what it produces with what the study published.

``e2er reproduce <folder>`` reads the folder's ``reproduce.json``, which says
how the study's code is run again:

    {
      "schema": "e2er-reproduce/1",
      "python": "3.12",                          # optional; else the Python e2er runs on
      "requirements": "code/requirements.txt",   # pinned packages, installed in a new environment
      "files": {"run_estimation.py": "code/run_estimation.py"},   # run folder <- study folder
      "steps": [{"run": ["python", "run_estimation.py"], "about": "estimate the models"}],
                                                 # + "when_missing": ["data.db"]: run only when the folder
                                                 # lacked it (data preparation after get_data.py)
      "inputs": [{"path": "data/x.csv", "sha256": "…", "source": "…"}],   # + "reload": "get_data.py" when a
                                                 # step loads it again if the folder does not ship it;
                                                 # + "rebuild": "clean.py" when a step builds it again
                                                 # from such data (a derived file the folder may lack)
      "compare": [{"published": "results/estimation_results.json", "produced": "estimation_results.json"}],
      "notes": ["…"]
    }

A .e2er package (``e2er pack``) is unpacked first; its run installs from the
package's ``e2er-package/requirements.lock.txt`` (every package with its
hashes) and, when the package carries wheels for this computer, from those
without the internet (``recipe["wheelhouse"]``, set by e2er, never read from
reproduce.json).

The code runs in a run folder of its own (``files`` lays out the folder the
code was written for; without it the whole study folder is copied), inside a
new virtual environment with the pinned requirements. The study folder itself
is never written to.

Afterwards every compared JSON file is read value by value. A value is
*identical*, *the same at the published precision* (the rerun rounds to the
published number at the decimals the study printed), shows *small differences*
(within the replication path's minor tolerance and without a change of sign),
or *differs*. Inputs listed with a SHA-256 are compared with the study's own
files; a table input whose bytes differ but whose rows are the study's (a CSV, or
every table of a SQLite database, order of rows aside) has the same content.
When the study ships rendered tables and their spec, the tables are
rendered again from the rerun's results and compared with the paper's.

The study's code is someone else's. ``e2er reproduce`` lists every step's command and the
requirements before it runs anything and asks (``--yes`` in a script). It runs the steps in a
Docker container when Docker is there (src/core/reproduce_sandbox.py: no network, a read-only
system, no capabilities, an unprivileged user, only the run folder mounted); without Docker
only with ``--no-sandbox``, and then on this computer as the user, with ``HOME`` and the
``XDG_*`` folders pointed at an empty folder and no API key, token or e2er setting. It does get
e2er's read-only access to its own database (``e2er-data query sql`` and ``e2er-data query
tables`` read the run folder's ``data.db``). Only the steps that load inputs again (``"reload"``,
e.g. ``get_data.py``) may load data from the web, after their own question, and without keys.

The network guard (reproduce_netguard.py) is a report, not a protection: it sees the
connections Python makes and records them, and in a step that may not use the network it
makes them fail with a plain message. Code that wants to get past it can (a raw socket, a
subprocess). The protection is the container's ``--network none``.

Before anything runs, the folder is refused when it holds a symbolic link (a copy would read
the file it points to, ``~/.ssh`` included), and the requirements are refused when a line is
an installer option (``--index-url``, ``-e``, ``-r``) or a URL or VCS requirement; packages
install from wheels only (``--only-binary=:all:``) on this computer, and inside the container
only fall back to building a source package.
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
#: A left-out output the rerun wrote but whose study copy another step produced: reported, not compared.
NOT_COMPARED = "not_compared"
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
#: A compared result file with no value in it: comparing it shows nothing.
EMPTY = "the published file holds no value to compare"


class RecipeError(Exception):
    """reproduce.json is missing or does not say how to run the study."""


# ── the recipe ───────────────────────────────────────────────────────────────


def _safe_rel(path: Any) -> bool:
    if not isinstance(path, str) or not path.strip():
        return False
    p = Path(path)
    return not p.is_absolute() and ".." not in p.parts and not path.startswith(("/", "\\"))


#: A requirement line: a name with extras, version specifiers and markers. No URL, path or VCS reference.
_REQUIREMENT = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*(\[[A-Za-z0-9._,\s-]*\])?\s*"
    r"((===?|~=|!=|<=|>=|<|>)\s*[A-Za-z0-9.*+!_-]+\s*(,\s*(===?|~=|!=|<=|>=|<|>)\s*[A-Za-z0-9.*+!_-]+\s*)*)?"
    r"(;\s*[^@]+)?$"
)
#: The only option a requirement line may carry: the hash of the file to install (a lock file's).
_HASH_OPTION = re.compile(r"^--hash[=\s]+(sha256|sha384|sha512):[0-9a-fA-F]+$")


def requirement_lines(path: Path) -> list[str]:
    """The requirement lines of a requirements file, continuations joined, comments and hashes dropped."""
    text = path.read_text(encoding="utf-8", errors="replace")
    joined = re.sub(r"\\\r?\n", " ", text)
    out = []
    for raw in joined.splitlines():
        line = re.sub(r"(^|\s)#.*$", "", raw).strip()
        if line:
            out.append(" ".join(t for t in line.split() if not t.startswith("--hash")).strip())
    return [x for x in out if x]


def requirements_problems(path: Path) -> list[str]:
    """Why the requirements file may not be installed ([] when every line is a plain pinned requirement).

    Someone else's requirements file can point the installer elsewhere: ``--index-url`` or
    ``--extra-index-url`` (another package index), ``-f``/``--find-links``, ``--trusted-host``,
    ``-e``/``-r``/``-c`` (editable installs, other files), and a URL, path or VCS requirement
    (``pkg @ https://…``, ``git+https://…``, ``./pkg``) all fetch or build code the lock never
    pinned. Only ``name[extras] <specifiers> ; markers`` with ``--hash`` options passes.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return [f"cannot be read ({e})"]
    problems = []
    joined = re.sub(r"\\\r?\n", " ", text)
    for n, raw in enumerate(joined.splitlines(), 1):
        line = re.sub(r"(^|\s)#.*$", "", raw).strip()
        if not line:
            continue
        tokens = line.split()
        if tokens[0].startswith("-"):
            problems.append(f"line {n}: the installer option {tokens[0]!r} is not allowed")
            continue
        options = [t for t in tokens if t.startswith("-")]
        spec = " ".join(t for t in tokens if not t.startswith("-"))
        bad_option = next((o for o in options if not _HASH_OPTION.match(o)), None)
        if bad_option is not None:
            problems.append(f"line {n}: the option {bad_option!r} is not allowed (only --hash)")
        elif "@" in spec or "://" in spec or spec.startswith((".", "/", "~", "\\")) or not _REQUIREMENT.match(spec):
            problems.append(f"line {n}: {spec[:80]!r} is not a plain package requirement (no URL, path or VCS)")
    return problems


def links_in(folder: Path, limit: int = 5) -> list[str]:
    """Symbolic links inside ``folder`` (relative paths, at most ``limit``), without following any."""
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(folder, followlinks=False):
        for name in [*dirnames, *filenames]:
            p = Path(dirpath) / name
            if p.is_symlink():
                found.append(p.relative_to(folder).as_posix())
                if len(found) >= limit:
                    return found
    return found


def check_foreign(folder: Path, recipe: dict[str, Any]) -> None:
    """Refuse what must never run: a symbolic link in the folder, an installer option or URL requirement."""
    links = links_in(folder)
    if links:
        raise RecipeError(
            "the folder holds symbolic links (" + ", ".join(links) + "); a copy of the study would read the "
            "files they point to. Replace each link with the file itself."
        )
    req = folder / str(recipe["requirements"])
    problems = requirements_problems(req)
    if problems:
        raise RecipeError(f"{recipe['requirements']} is refused: " + "; ".join(problems[:5]))


def load_recipe(folder: Path, rebuild: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """reproduce.json, checked; RecipeError says what is wrong in plain words.

    ``rebuild`` (from a .e2er package's manifest) adds the steps that build left-out derived inputs again
    (:func:`apply_rebuild`) before the recipe is checked.
    """
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
    if rebuild:
        apply_rebuild(recipe, rebuild)
        drop_stale_notes(recipe)
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
            reloaded = optional_inputs(recipe)
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


def optional_inputs(recipe: dict[str, Any]) -> set[str]:
    """Inputs the folder may lack: loaded again (``"reload"``) or built again from those (``"rebuild"``)."""
    return reloaded_inputs(recipe) | {
        str(i["path"])
        for i in recipe.get("inputs") or []
        if isinstance(i, dict) and isinstance(i.get("path"), str) and i.get("rebuild")
    }


def apply_rebuild(recipe: dict[str, Any], plan: list[dict[str, Any]]) -> None:
    """Add the steps that build derived files again (files built from data a source's terms keep out).

    Each item ``{"path": run-folder path, "script": run name, "from": folder path}`` marks the input with
    ``"rebuild"``, lays the script out and runs it after the steps that load inputs again, only when the
    folder lacked the input (``"when_missing"``). Items for inputs the recipe does not list are ignored,
    except a left-out output (``"output": true``, derived_data.rebuild_plan): it becomes an input marked
    ``"output"`` (compared with the study's file, apart from the verdict), and the script runs after the
    step its ``"after"`` names, or not at all when a step of the recipe writes it (``"written"``). Items with
    the same script share one step.
    """
    inputs = {str(i.get("path")): i for i in recipe.get("inputs") or [] if isinstance(i, dict)}
    files = recipe.setdefault("files", {}) if isinstance(recipe.get("files"), dict) else None
    steps = recipe.get("steps") if isinstance(recipe.get("steps"), list) else None
    if steps is None:
        return
    for item in plan:
        if not isinstance(item, dict):
            continue
        path, script, src = str(item.get("path")), str(item.get("script")), str(item.get("from"))
        if not (_safe_rel(path) and _safe_rel(script) and _safe_rel(src)):
            continue
        target = inputs.get(path)
        if target is None and item.get("output") and isinstance(item.get("sha256"), str):
            target = {
                "path": path,
                "sha256": item["sha256"],
                "source": f"{item.get('folder') or path}, built by the study's code from data a source's terms keep "
                "out of a published folder",
                "output": True,
            }
            content = item.get("content")
            if isinstance(content, dict):
                target.update(
                    {k: v for k, v in content.items() if k in ("rows", "content_sha256", "numeric_sha256", "tables")}
                )
            recipe.setdefault("inputs", []).append(target)
            inputs[path] = target
        if target is None or target.get("reload") or target.get("rebuild"):
            continue
        target["rebuild"] = script
        if files is not None:
            files.setdefault(script, src)
        if item.get("written"):
            target["written"] = True  # a step of the recipe writes it: no step to add
            continue
        existing = next(
            (
                st
                for st in steps
                if isinstance(st, dict)
                and isinstance(st.get("when_missing"), list)
                and any(Path(a).name == script for a in step_argv(st))
            ),
            None,
        )
        if existing is not None:
            existing["when_missing"].append(path)
            existing["about"] = (
                "data preparation: builds "
                + ", ".join(map(str, existing["when_missing"]))
                + (" again from the data loaded again")
            )
            continue
        after = item.get("after")
        named = [
            i
            for i, st in enumerate(steps)
            if isinstance(st, dict) and after and any(Path(a).name == after for a in step_argv(st))
        ]
        reload_at = [i for i, st in enumerate(steps) if isinstance(st, dict) and is_reload_step(st, recipe)]
        if named:
            at = named[-1] + 1
        else:
            at = (reload_at[-1] + 1) if reload_at else 0
        steps.insert(
            at,
            {
                "run": ["python", script],
                "about": f"data preparation: builds {path} again from the data loaded again",
                "when_missing": [path],
            },
        )


#: The note export writes for derived inputs it found no step to build again (reproduce_recipe).
_STUCK = re.compile(
    r"^(?P<paths>.+?) (?:is|are) built from data whose terms keep them out of a published study, and no recorded "
    r"step builds them again from data the rerun can load: a folder without them cannot be run again\.$"
)


def drop_stale_notes(recipe: dict[str, Any]) -> None:
    """Take out of the export's note "… no recorded step builds them again" the files a step now builds again
    (a package's ``rebuild`` list, :func:`apply_rebuild`): the note was written before that list existed."""
    raw = recipe.get("files")
    files: dict[str, Any] = raw if isinstance(raw, dict) else {}
    covered: set[str] = set()
    for i in recipe.get("inputs") or []:
        if isinstance(i, dict) and isinstance(i.get("path"), str) and (i.get("rebuild") or i.get("reload")):
            covered |= {i["path"], str(files.get(i["path"], i["path"]))}
    notes = recipe.get("notes")
    if not isinstance(notes, list) or not covered:
        return
    kept: list[Any] = []
    for note in notes:
        m = _STUCK.match(note) if isinstance(note, str) else None
        if m is None:
            kept.append(note)
            continue
        left = [p for p in m.group("paths").split(", ") if p not in covered]
        if left:
            kept.append(
                f"{', '.join(left)} {'is' if len(left) == 1 else 'are'} built from data whose terms keep them out of "
                "a published study, and no recorded step builds them again from data the rerun can load: a folder "
                "without them cannot be run again."
            )
    recipe["notes"] = kept


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
    ``0.00285433`` was rounded at 8 decimals, while ``1.0`` or ``0.5`` may well be exact. A whole number
    (``1234.0``, ``4321``) is never taken as rounded: a count or a total must match exactly."""
    if float(value).is_integer():
        return False
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
    if not any(not isinstance(v, dict | list) for v in a.values()):
        # Nothing to compare (an empty file, or empty lists and objects only): it reproduces nothing.
        fc.problem = EMPTY
        return fc
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


# ── comparing inputs by content ──────────────────────────────────────────────
#
# A source reloaded by get_data.py can return the same rows in another order (an
# ADQL query without ORDER BY: the Gaia demo of 2026-10-13 got 14,066 identical
# rows back, and its CSV differed by SHA-256). Inputs that are tables (a CSV, a
# table of data.db) are therefore also fingerprinted by content: a hash of the
# multiset of their rows, which ignores the order of the rows.

#: The status of an input whose bytes differ but whose rows are the same (in another order).
SAME_ROWS = "same_rows"
#: The status of an input whose rows are the same once every decimal number is written with NUMERIC_DIGITS
#: significant digits: a file the study's own preparation step builds again, whose numbers differ only in the
#: last binary digits (the Gaia demo of 2026-10-13: pandas wrote -0.0005179820886653808 in the run and
#: -0.0005179820886653 in the rerun, from the same text in the reloaded rows).
SAME_NUMBERS = "same_numbers"
NUMERIC_DIGITS = 12
_DECIMAL = re.compile(r"^\s*[-+]?(?:\d+\.\d*|\.\d+|\d+(?:\.\d*)?[eE][-+]?\d+)\s*$")
#: Table files fingerprinted by content.
_TABLE_SUFFIXES = frozenset({".csv", ".tsv"})
_DB_SUFFIXES = frozenset({".db", ".sqlite", ".sqlite3"})
_MOD = 1 << 256


def _at_digits(v: Any) -> Any:
    """A decimal number (a float, or text that is one) with NUMERIC_DIGITS significant digits; else as it is."""
    if isinstance(v, float):
        return format(v, f".{NUMERIC_DIGITS}g")
    if isinstance(v, str) and _DECIMAL.match(v):
        try:
            return format(float(v), f".{NUMERIC_DIGITS}g")
        except ValueError:
            return v
    return v


def _row_digest(row: list[Any], rounded: bool = False) -> int:
    def norm(v: Any) -> Any:
        if rounded:
            v = _at_digits(v)
        if isinstance(v, bytes):
            return {"bytes": v.hex()}
        if isinstance(v, float):
            return repr(v)
        return v

    text = json.dumps([norm(v) for v in row], ensure_ascii=False, separators=(",", ":"))
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16)


def _rows_fingerprint(header: list[Any], rows: Any) -> dict[str, Any]:
    """{"rows": n, "content_sha256": …, "numeric_sha256": …}: the header and the multiset of rows (any order
    gives the same hash); ``numeric_sha256`` the same with every decimal number at NUMERIC_DIGITS digits."""
    acc, num, n = 0, 0, 0
    for row in rows:
        cells = list(row)
        acc = (acc + _row_digest(cells)) % _MOD
        num = (num + _row_digest(cells, rounded=True)) % _MOD
        n += 1

    def digest(total: int) -> str:
        h = hashlib.sha256()
        h.update(json.dumps([str(c) for c in header], ensure_ascii=False).encode("utf-8"))
        h.update(total.to_bytes(32, "big"))
        h.update(str(n).encode())
        return h.hexdigest()

    return {"rows": n, "content_sha256": digest(acc), "numeric_sha256": digest(num)}


def content_fingerprint(path: Path) -> dict[str, Any] | None:
    """A table file's content, order of rows aside: ``{"rows", "content_sha256"}`` for a CSV/TSV,
    ``{"tables": {name: {"rows", "content_sha256"}}}`` for a SQLite database; None for other files
    or one that cannot be read."""
    import csv
    import sqlite3

    suffix = path.suffix.lower()
    try:
        if suffix in _TABLE_SUFFIXES:
            with path.open(newline="", encoding="utf-8", errors="replace") as f:
                reader = csv.reader(f, delimiter="\t" if suffix == ".tsv" else ",")
                header = next(reader, [])
                return _rows_fingerprint(header, reader)
        if suffix in _DB_SUFFIXES:
            con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                names = [
                    str(r[0])
                    for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
                    if not str(r[0]).startswith("sqlite_")
                ]
                tables = {}
                for name in names:
                    cur = con.execute('SELECT * FROM "' + name.replace('"', '""') + '"')
                    header = [d[0] for d in cur.description or ()]
                    tables[name] = {**_rows_fingerprint(header, cur), "columns": [str(c) for c in header]}
            finally:
                con.close()
            return {"tables": tables}
    except (OSError, UnicodeError, sqlite3.Error, csv.Error):
        return None
    return None


def _match(want: Any, have: dict[str, Any]) -> str:
    """ "rows" (the same rows), "numbers" (the same at NUMERIC_DIGITS digits) or "" for one recorded fingerprint."""
    if not isinstance(want, dict) or not isinstance(want.get("content_sha256"), str):
        return ""
    if have.get("content_sha256") == want["content_sha256"]:
        return "rows"
    if isinstance(want.get("numeric_sha256"), str) and have.get("numeric_sha256") == want["numeric_sha256"]:
        return "numbers"
    return ""


def _on_columns(path: Path, table: str, columns: list[str]) -> dict[str, Any]:
    """The fingerprint of ``table`` in the database ``path`` on ``columns`` only (in that order); {} on failure."""
    import sqlite3

    q = ", ".join('"' + c.replace('"', '""') + '"' for c in columns)
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            cur = con.execute(f'SELECT {q} FROM "' + table.replace('"', '""') + '"')
            return _rows_fingerprint(columns, cur)
        finally:
            con.close()
    except sqlite3.Error:
        return {}


def _extra_columns(want: Any, have: dict[str, Any]) -> list[str]:
    """The columns a reloaded table has beyond the study's (a connector that now records more), or []."""
    if not isinstance(want, dict) or not isinstance(want.get("columns"), list):
        return []
    mine, theirs = [str(c) for c in want["columns"]], [str(c) for c in have.get("columns") or []]
    if mine == theirs or not set(mine) < set(theirs):
        return []
    return [c for c in theirs if c not in mine]


def _same_content(item: dict[str, Any], path: Path) -> tuple[str, list[str]]:
    """(SAME_ROWS, SAME_NUMBERS or DIFFERS, the tables that differ) for an input with a recorded content fingerprint."""
    found = content_fingerprint(path)
    if found is None:
        return DIFFERS, []
    if isinstance(item.get("tables"), dict):
        have = found.get("tables") or {}
        # Tables no step reads (reproduce.json's "not_read"): a rerun that built the database again lacks them.
        skip = {str(t) for t in item.get("not_read") or [] if str(t) not in have}
        matches = {t: _match(want, have.get(t) or {}) for t, want in sorted(item["tables"].items()) if t not in skip}
        for t, m in matches.items():
            want = item["tables"][t]
            # A reload whose table has more columns than the study's (the connector records more since): the
            # study's input is the same when its own columns hold the same rows.
            if not m and _extra_columns(want, have.get(t) or {}):
                matches[t] = _match(want, _on_columns(path, t, [str(c) for c in want["columns"]]))
        differ = [t for t, m in matches.items() if not m]
        if differ:
            return DIFFERS, differ
        return (SAME_NUMBERS if "numbers" in matches.values() else SAME_ROWS), []
    m = _match(item, found)
    return {"rows": SAME_ROWS, "numbers": SAME_NUMBERS}.get(m, DIFFERS), []


def compare_inputs(run_dir: Path, inputs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each declared input as the rerun has it: identical to the study's file, the same rows in another order
    (``same_rows``, when the recipe recorded its content), the same rows with decimal numbers equal to
    NUMERIC_DIGITS significant digits (``same_numbers``), different, or missing."""
    out = []
    for item in inputs:
        path = run_dir / item["path"]
        entry: dict[str, Any] = {"path": item["path"], "source": item.get("source")}
        if item.get("output"):
            entry["output"] = True  # a left-out output the rerun built again: reported, not an input
        if item.get("output") and isinstance(item.get("not_compared"), str):
            # Not the step that produced the study's copy (derived_data.not_produced_by_step): nothing to compare.
            status = NOT_COMPARED
            entry["why"] = item["not_compared"]
        elif not path.is_file():
            status = "missing"
        elif sha256_file(path) == item["sha256"]:
            status = "identical"
        elif "tables" in item or "content_sha256" in item:
            status, differ = _same_content(item, path)
            if differ:
                entry["tables_differ"] = differ
        else:
            status = "differs"
        entry["status"] = status
        out.append(entry)
    return out


def add_numeric_fingerprints(recipe: dict[str, Any], recorded: dict[str, dict[str, Any]]) -> list[str]:
    """Give inputs of an older recipe the numbers fingerprint that a package recorded for them (left out).

    ``recorded``: folder path -> the content fingerprint pack recorded for a file it left out. A fingerprint
    is taken only where its exact content hash is the recipe's own (reproduce.json, which provenance.json
    fixes), so it describes the same file. Returns the inputs that got one.
    """
    files = recipe.get("files") or {}
    out = []
    for item in recipe.get("inputs") or []:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            continue
        rec = recorded.get(str(files.get(item["path"], item["path"])))
        if not isinstance(rec, dict):
            continue
        added = False
        if isinstance(item.get("tables"), dict) and isinstance(rec.get("tables"), dict):
            for t, want in item["tables"].items():
                got = rec["tables"].get(t)
                if (
                    isinstance(want, dict)
                    and "numeric_sha256" not in want
                    and isinstance(got, dict)
                    and got.get("content_sha256") == want.get("content_sha256")
                    and isinstance(got.get("numeric_sha256"), str)
                ):
                    want["numeric_sha256"] = got["numeric_sha256"]
                    added = True
        elif (
            "numeric_sha256" not in item
            and isinstance(item.get("content_sha256"), str)
            and rec.get("content_sha256") == item["content_sha256"]
            and isinstance(rec.get("numeric_sha256"), str)
        ):
            item["numeric_sha256"] = rec["numeric_sha256"]
            added = True
        if added:
            out.append(item["path"])
    return out


def compare_tables(folder: Path, run_dir: Path, compare: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Render the paper's tables again from the rerun's results; None when the study ships none.

    Only the rerun's own outputs go in (and the table spec): a table that reads a results file the rerun did
    not write again is not compared (``not_compared``), never rendered from the published file.
    """
    spec = folder / "results" / "table_spec.json"
    shipped = folder / "paper" / "tables"
    if not spec.is_file() or not shipped.is_dir():
        return None
    from .renderer.tables import render_tables, table_sources

    ws = run_dir / ".e2er-tables"
    ws.mkdir(exist_ok=True)
    shutil.copy2(spec, ws / "table_spec.json")
    rerun: set[str] = set()
    for c in compare:
        produced = run_dir / c["produced"]
        if produced.is_file() and c["published"].startswith("results/"):
            name = Path(c["published"]).name
            shutil.copy2(produced, ws / name)
            rerun.add(name)
    published = {p.name for p in (folder / "results").glob("*.json")}
    reads = table_sources(ws)
    quiet = logging.getLogger("src.core.renderer.tables")
    level = quiet.level
    quiet.setLevel(logging.WARNING)  # the renderer's progress line is not part of the report
    try:
        report = render_tables(ws)
    finally:
        quiet.setLevel(level)
    if report.skipped_reason:
        return {"skipped": report.skipped_reason}
    identical, differ, not_shipped, not_compared = [], [], [], []
    for name in report.rendered:
        old = shipped / name
        if (reads.get(name, set()) & published) - rerun:
            not_compared.append(name)  # it reads a published results file the rerun did not write again
        elif not old.is_file():
            not_shipped.append(name)
        elif old.read_bytes() == (ws / "tables" / name).read_bytes():
            identical.append(name)
        else:
            differ.append(name)
    return {
        "rendered": len(report.rendered) - len(not_compared),
        "identical": identical,
        "differ": differ,
        "not_shipped": not_shipped,
        "not_compared": not_compared,
    }


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
    if not requirements.is_relative_to(folder.resolve()):
        raise RecipeError(f"{recipe['requirements']} is outside the study folder")
    wanted = str(recipe.get("python") or "").strip()
    uv = shutil.which("uv")
    # A .e2er package with wheels for this computer (``e2er pack --offline``): installed without the internet.
    wheelhouse = recipe.get("wheelhouse")
    offline = ["--no-index", "--find-links", str((folder / str(wheelhouse)).resolve())] if wheelhouse else []
    if uv:
        base = getattr(sys, "_base_executable", None) or sys.executable  # the interpreter, not e2er's own venv
        create = [uv, "venv", "--quiet", "--python", wanted or base, str(venv)]
        install = [uv, "pip", "install", "--quiet", "--python", str(_venv_python(venv)), *offline,
                   "--only-binary", ":all:", "-r", str(requirements)]  # fmt: skip
    else:
        if wanted and not f"{sys.version_info.major}.{sys.version_info.minor}".startswith(wanted):
            raise RecipeError(
                f"the study asks for Python {wanted}, e2er runs on {sys.version.split()[0]}, and uv (which can "
                "fetch another Python) is not installed: install uv, or run e2er on Python " + wanted
            )
        create = [sys.executable, "-m", "venv", str(venv)]
        install = [str(_venv_python(venv)), "-m", "pip", "install", "--quiet", *offline, "--only-binary=:all:",
                   "-r", str(requirements)]  # fmt: skip
    code, tail = _run(create, cwd=run_dir, env=minimal_env(), timeout=600, log=logs / "environment-create.log")
    if code != 0:
        raise RecipeError(f"could not create the environment: {tail}")
    code, tail = _run(install, cwd=run_dir, env=minimal_env(), timeout=1800, log=logs / "environment-install.log")
    if code != 0:
        raise RecipeError(
            f"could not install {recipe['requirements']} from wheels (on this computer e2er installs no source "
            f"package: building one runs its code; the Docker sandbox can): {tail}"
        )
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
    info["installer"] = ("uv" if uv else "pip") + (", offline from the package's wheels" if wheelhouse else "")
    try:
        info["network_guard"] = install_network_guard(py)
    except (OSError, subprocess.SubprocessError):
        info["network_guard"] = False
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
    """The environment someone else's code (and the installation of its packages) runs with.

    A proxy setting that carries a user and password (``http://user:pass@proxy``) is left out.
    """
    return {
        k: v
        for k, v in os.environ.items()
        if (k in _PASSED_ON or (k.startswith(_INSTALLER_PREFIXES) and not _CREDENTIAL.search(k)))
        and not ("proxy" in k.lower() and "@" in v)
    }


#: The folders a program finds its user's settings in: pointed at an empty folder for the steps.
_HOME_VARS = (
    "HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR",
    "USERPROFILE", "APPDATA", "LOCALAPPDATA",
)  # fmt: skip


def empty_home(run_dir: Path) -> Path:
    """An empty folder that stands in for the user's home in the steps (``<run>/.e2er-home``)."""
    home = run_dir / ".e2er-home"
    home.mkdir(exist_ok=True)
    return home


#: Set in every step: e2er-data knows it runs inside a rerun (no audit record in e2er's own database).
REPRODUCE_ENV = "E2ER_REPRODUCE"
#: Set in the steps that do not load inputs again: e2er-data answers read-only queries only.
DATA_READ_ONLY_ENV = "E2ER_DATA_READ_ONLY"
#: ``block`` or ``record``: what the network guard does in a step (see reproduce_netguard.py).
NETWORK_ENV = "E2ER_REPRODUCE_NETWORK"
#: Where the guard and e2er-data record what a step tried to reach.
NETWORK_LOG_ENV = "E2ER_REPRODUCE_NETWORK_LOG"


def step_env(venv_python: Path, run_dir: Path | None = None) -> dict[str, str]:
    """The steps' environment: the minimal one (no keys), the new environment first; e2er-data from the running e2er.

    With ``run_dir``, e2er-data is bound to the run folder: ``e2er-data query sql/tables`` read
    its ``data.db``, never a workspace of this machine.
    """
    env = minimal_env()
    venv_bin = venv_python.parent
    scripts = sysconfig.get_path("scripts") or str(Path(sys.executable).parent)
    env["PATH"] = os.pathsep.join([str(venv_bin), scripts, env.get("PATH", "")])
    env["VIRTUAL_ENV"] = str(venv_bin.parent)
    env["PYTHON_COLORS"] = "0"  # plain tracebacks in the logs and the report
    e2er_data = shutil.which("e2er-data", path=scripts) or shutil.which("e2er-data")
    if e2er_data:
        env["E2ER_DATA"] = e2er_data
    if run_dir is not None:
        # Never the user's home: ~/.ssh, ~/.e2er/credentials.json, ~/.netrc, the CLIs' logins.
        home = str(empty_home(run_dir))
        for var in _HOME_VARS:
            if var in env or var in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
                env[var] = home
        env.pop("XDG_RUNTIME_DIR", None)
        # e2er-data finds no settings of this computer (no .env, no API key): its studies folder is the empty home.
        env["E2ER_PROJECT_DIR"] = home
        env["E2ER_PAPER_ID"] = run_dir.name
        env["E2ER_WORKSPACE"] = str(run_dir)
        env["E2ER_WORKSPACE_ROOT"] = str(run_dir.parent)
        env["E2ER_SPECIALIST"] = "reproduce"
        env[REPRODUCE_ENV] = "1"
    return env


def install_network_guard(venv_python: Path) -> bool:
    """Put the network guard into the new environment (it acts only in steps that set E2ER_REPRODUCE_NETWORK)."""
    probe = subprocess.run(
        [str(venv_python), "-I", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
        capture_output=True,
        text=True,
        timeout=120,
        env=minimal_env(),
    )
    site = Path(probe.stdout.strip()) if probe.returncode == 0 and probe.stdout.strip() else None
    if site is None or not site.is_dir():
        return False
    shutil.copy2(Path(__file__).with_name("reproduce_netguard.py"), site / "e2er_reproduce_netguard.py")
    (site / "e2er_reproduce_netguard.pth").write_text("import e2er_reproduce_netguard\n", encoding="utf-8")
    return True


def lay_out(folder: Path, run_dir: Path, recipe: dict[str, Any]) -> list[str]:
    """Lay out the run folder; returns the result files that were removed from it.

    Every file the rerun is to write (``compare`` → ``produced``) is taken out of
    the run folder before the steps run. Copied with the study, a published result
    would otherwise be there already, and a script that writes nothing would be
    compared with the published file itself and "reproduce" it.
    """
    files = recipe.get("files")
    if not files:
        # symlinks=True: a link is copied as a link, never as the file it points to (check_foreign refuses links).
        shutil.copytree(
            folder, run_dir, dirs_exist_ok=True, symlinks=True, ignore=shutil.ignore_patterns(".git", ".venv", ".env")
        )
    else:
        for dst, src in files.items():
            source, target = folder / src, run_dir / dst
            if not source.exists():
                continue  # an input the folder does not ship; a step loads it again (load_recipe checked)
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_symlink() or not source.resolve().is_relative_to(folder.resolve()):
                raise RecipeError(f'"files": {src} is a link or leads outside the study folder')
            if source.is_dir():
                shutil.copytree(source, target, dirs_exist_ok=True, symlinks=True)
            else:
                shutil.copy2(source, target, follow_symlinks=False)
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
    #: Whether the step loads inputs again (``"reload"`` in the recipe): the only steps that may use the web.
    reload: bool = False
    #: What the step tried to reach on the network, or to load with e2er-data: {"host"/"command", "blocked"}.
    network: list[dict[str, Any]] = field(default_factory=list)
    #: A failed step's missing package, in a sentence ("The recipe does not pin openpyxl, ..."); empty otherwise.
    missing: str = ""
    #: Not run: the step rebuilds what the folder already had (``"when_missing"`` in the recipe).
    skipped: str = ""

    @property
    def blocked(self) -> list[dict[str, Any]]:
        return [n for n in self.network if n.get("blocked")]

    def as_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        d["network"] = list(self.network)
        return d


def is_reload_step(step: dict[str, Any], recipe: dict[str, Any]) -> bool:
    """Does the step run a script that loads inputs again (an input's ``"reload"``)?"""
    names = {
        Path(str(i["reload"])).name
        for i in recipe.get("inputs") or []
        if isinstance(i, dict) and isinstance(i.get("reload"), str)
    }
    return any(Path(a).name in names for a in step_argv(step))


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _read_network_log(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        key = json.dumps(row, sort_keys=True)
        if key not in seen:
            seen.add(key)
            out.append(row)
    return out


_OPTIONAL_DEPENDENCY = re.compile(r"Missing optional dependency '([\w.\-]+)'")
_NO_MODULE = re.compile(r"(?:ModuleNotFoundError|ImportError): No module named '([\w.]+)'")
_SITE_PACKAGE = re.compile(r'File "[^"]*[/\\]site-packages[/\\]([A-Za-z_]\w*)[/\\]')
#: Import name → distribution, where they differ (what to name in the recipe).
_DISTRIBUTION_OF = {
    "sklearn": "scikit-learn", "yaml": "PyYAML", "bs4": "beautifulsoup4", "PIL": "Pillow",
    "cv2": "opencv-python", "dateutil": "python-dateutil", "dotenv": "python-dotenv", "Bio": "biopython",
    "skimage": "scikit-image", "attr": "attrs", "google": "google-api-python-client", "docx": "python-docx",
    "pptx": "python-pptx", "calamine": "python-calamine", "odf": "odfpy", "xlsxwriter": "XlsxWriter",
}  # fmt: skip
#: What a package that another loads only when needed is for (the end of "which pandas needs ...").
_NEEDED_FOR = {
    "openpyxl": "to read and write Excel files (.xlsx)",
    "xlrd": "to read old Excel files (.xls)",
    "XlsxWriter": "to write Excel files",
    "odfpy": "to read OpenDocument spreadsheets",
    "pyarrow": "to read and write Parquet and Feather files",
    "fastparquet": "to read and write Parquet files",
    "lxml": "to read XML and HTML",
    "beautifulsoup4": "to read HTML tables",
    "html5lib": "to read HTML tables",
    "tabulate": "to write Markdown tables",
    "jinja2": "to write LaTeX and styled tables",
    "pyreadstat": "to read SPSS files",
    "tables": "to read and write HDF5 files",
    "SQLAlchemy": "to read and write databases",
    "sqlalchemy": "to read and write databases",
}


def missing_dependency(output: str) -> str:
    """A plain sentence when a step failed because the recipe left a package out; empty otherwise.

    Reads the step's output for pandas' "Missing optional dependency 'X'" and Python's
    "No module named 'X'"; names the package that needed it when the traceback shows one.
    """
    m = _OPTIONAL_DEPENDENCY.findall(output) or _NO_MODULE.findall(output)
    if not m:
        return ""
    module = m[-1].split(".")[0]
    dist = _DISTRIBUTION_OF.get(module, module)
    # The library that asked for it: the innermost site-packages frame of the last traceback.
    last = output[output.rfind("Traceback (most recent call last)") :] if "Traceback" in output else output
    needers = [p for p in _SITE_PACKAGE.findall(last) if p != module and p not in ("importlib",)]
    if needers:
        purpose = _NEEDED_FOR.get(dist, "")
        need = f", which {needers[-1]} needs" + (f" {purpose}" if purpose else "")
    else:
        need = ", which the study's code imports"
    return f"The recipe does not pin {dist}{need}."


#: How a step runs: (argv, env, timeout seconds, log file, may use the network, step number) -> (exit, tail).
StepRunner = Any


def run_steps(
    run_dir: Path,
    recipe: dict[str, Any],
    env: dict[str, str],
    logs: Path,
    python: Path | str,
    *,
    allow_network: bool = False,
    allow_reload: bool = True,
    runner: StepRunner = None,
    log_path: Any = None,
) -> list[StepResult]:
    """Run the steps in order; stop at the first that fails. ``python`` runs every ``python …`` step.

    A step that loads inputs again may use the web and every e2er-data command, unless
    ``allow_reload`` is False (the researcher said no): then it runs like any other step. Every
    other step gets e2er-data's read-only queries only, and no network unless ``allow_network``
    (then its connections are recorded). ``runner`` runs one step (default: a process on this
    computer; the Docker sandbox passes its own), ``log_path`` turns a log file on this computer
    into the path the step sees (inside a container).
    """
    if runner is None:

        def runner(argv: list[str], step_env: dict[str, str], timeout: float, log: Path, network: bool, i: int):
            return _run(argv, cwd=run_dir, env=step_env, timeout=timeout, log=log)

    seen_as = log_path or str
    results = []
    # What the folder did not ship (before any step loads it again): a step marked "when_missing" (the data
    # preparation after get_data.py) runs only when one of its inputs had to be loaded again.
    absent = {p for p in optional_inputs(recipe) if not (run_dir / p).exists()}
    for i, step in enumerate(recipe["steps"], 1):
        when = step.get("when_missing")
        if isinstance(when, list) and when and not absent.intersection(map(str, when)):
            results.append(
                StepResult(
                    command=shlex.join(step_argv(step)),
                    about=str(step.get("about") or ""),
                    exit_code=0,
                    seconds=0.0,
                    tail="",
                    log="",
                    skipped=f"the folder has {', '.join(map(str, when))}",
                )
            )
            continue
        argv = step_argv(step)
        if argv and argv[0] in ("python", "python3"):
            argv = [str(python), *argv[1:]]
        timeout = float(step.get("timeout_minutes") or DEFAULT_STEP_TIMEOUT_MINUTES) * 60
        log = logs / f"step-{i}.log"
        net_log = logs / f"step-{i}-network.jsonl"
        reload = is_reload_step(step, recipe)
        web = reload and allow_reload
        step_environment = dict(env)
        if not web:
            step_environment[DATA_READ_ONLY_ENV] = "1"
            step_environment[NETWORK_ENV] = "record" if allow_network else "block"
            step_environment[NETWORK_LOG_ENV] = seen_as(net_log)
        started = time.monotonic()
        code, tail = runner(argv, step_environment, timeout, log, web or allow_network, i)
        results.append(
            StepResult(
                command=shlex.join(step_argv(step)),
                about=str(step.get("about") or ""),
                exit_code=code,
                seconds=round(time.monotonic() - started, 1),
                tail=tail if code else "",
                log=str(log),
                reload=reload,
                network=_read_network_log(net_log),
                missing=missing_dependency(_read_text(log)) if code else "",
            )
        )
        if code != 0:
            break
    return results


def blocked_words(step: StepResult) -> str:
    """What a step was stopped from doing, as the end of a sentence; empty when nothing was stopped."""
    hosts = sorted({str(n["host"]) for n in step.blocked if n.get("host")})
    commands = sorted({str(n["command"]) for n in step.blocked if n.get("command")})
    parts = []
    if hosts:
        parts.append(
            f"tried to reach the web ({', '.join(hosts[:5])}), which a rerun allows only in the step that loads "
            "the inputs again"
        )
    if commands:
        parts.append(
            "called " + ", ".join(f"`e2er-data {c}`" for c in commands[:5]) + ", which loads data from the web; "
            "during a rerun the study's code can only read its own data (e2er-data query)"
        )
    return " and ".join(parts)


def web_hosts(step: StepResult) -> list[str]:
    """The machines a step reached (allowed with --allow-network)."""
    return sorted({str(n["host"]) for n in step.network if n.get("host") and not n.get("blocked")})


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
        why = blocked_words(failed)
        if why:
            return f"Could not reproduce: the step `{failed.command}` {why}.", 2
        if failed.missing:
            return f"Could not reproduce: the step `{failed.command}` failed. {failed.missing}", 2
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

    if not sum(f.total for f in compared):
        # "Reproduced" says that values matched: with none compared, nothing was reproduced.
        named = ", ".join(f"{f.published} ({f.problem})" for f in files if f.problem) or "none"
        return f"Not reproduced: no value was compared (result files: {named}).", 1

    bad_files = [f.published for f in files if f.problem]
    bad_tables = len((tables or {}).get("differ") or []) + len((tables or {}).get("not_shipped") or [])
    # Left-out outputs the rerun built again (a figure's data) are reported apart: they are not what the
    # study's results are compared on.
    inputs = [i for i in inputs or [] if not i.get("output")]
    other = [i for i in inputs if i.get("status") == "differs"]
    absent = [i for i in inputs if i.get("status") == "missing"]
    if (
        not any(count(k) for k in LABELS if k not in MATCHING)
        and not bad_files
        and not bad_tables
        and not (other or absent)
    ):
        tail = " and every table renders the same" if tables and tables.get("rendered") else ""
        skipped = (tables or {}).get("not_compared") or []
        if skipped:
            tail += (
                f"; {len(skipped)} table(s) not compared, since they read results the rerun did not write again "
                f"({', '.join(sorted(skipped)[:3])})"
            )
        close = [i["path"] for i in inputs or [] if i.get("status") == SAME_NUMBERS]
        if close:
            tail += (
                f"; {', '.join(close[:3])} {'has' if len(close) == 1 else 'have'} the study's rows with every decimal "
                f"number equal to {NUMERIC_DIGITS} significant digits"
            )
        web = sorted({h for s in steps if not s.reload for h in web_hosts(s)})
        if web:
            tail += (
                f"; the study's code read from the web while it ran ({', '.join(web[:5])}), so a later rerun "
                "can differ when those pages change"
            )
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
    web = sorted({h for s in steps if not s.reload for h in web_hosts(s)})
    if web:
        parts.append(f"the study's code read from the web while it ran ({', '.join(web[:5])})")
    return "Not reproduced exactly: " + "; ".join(parts) + ".", 1
