"""The estimation script runs on its own: no web, no e2er tool other than a read-only query.

``e2er reproduce`` reruns the scripts that wrote ``estimation_results.json`` in
a folder of their own, with the study's data and nothing else: no API key, no
e2er workspace, and no network outside the data step (``get_data.py``). A
script that fetches web pages while it estimates (the 2026-10-10 Codex run
read 101 FOMC statements from federalreserve.gov inside ``run_estimation.py``)
or calls ``e2er-data yfinance …`` makes its results depend on what the web
serves on the day of the rerun.

This module reads those scripts (and the local modules they import) without
running them and names every such call, with its line. Allowed: reading files
and ``data.db``, and ``e2er-data query sql|tables`` (read-only, bound to the
rerun's ``data.db``). Flagged:

- importing a library that loads data over the network (requests, httpx,
  urllib.request, yfinance, pandas_datareader, fredapi, …);
- reading a URL with pandas (``pd.read_csv("https://…")``);
- running ``curl``/``wget`` or an e2er tool other than ``e2er-data query`` in a
  subprocess (``subprocess.run``, ``os.system``, …).

Deterministic and cheap: the econometrics specialist gets it as an output-contract
failure with a plain message and fixes it within its attempts.
"""

from __future__ import annotations

import ast
import re
import shlex
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .contract_check import ContractCheck

#: Modules whose import means the script loads data over the network.
NETWORK_MODULES = frozenset(
    {
        "requests",
        "httpx",
        "urllib3",
        "aiohttp",
        "http.client",
        "urllib.request",
        "ftplib",
        "yfinance",
        "pandas_datareader",
        "fredapi",
        "wbgapi",
        "wbdata",
        "quandl",
        "nasdaqdatalink",
        "alpha_vantage",
        "tweepy",
        "websocket",
        "websockets",
        "pycurl",
        "wget",
    }
)

#: Functions that read a path or a URL; flagged when the first argument is a URL literal.
_READERS = re.compile(r"^(read_\w+|urlopen|urlretrieve|open_url|get|post|request)$")
_URL = re.compile(r"^\s*(https?|ftp)://", re.I)

#: Calls that start another program.
_RUNNERS = frozenset(
    {
        "subprocess.run",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
        "subprocess.Popen",
        "subprocess.getoutput",
        "subprocess.getstatusoutput",
        "os.system",
        "os.popen",
        "os.execv",
        "os.execvp",
        "os.spawnv",
        "os.spawnvp",
    }
)
_RUNNER_NAMES = frozenset(n.rsplit(".", 1)[1] for n in _RUNNERS)
_WEB_PROGRAMS = frozenset({"curl", "wget", "aria2c", "httpie", "http", "gsutil", "aws", "rclone", "scp", "rsync"})
_E2ER_TOOL = re.compile(r"^e2er(-[a-z-]+)?$")

MESSAGE = (
    "The estimation script must read its data from data.db or files in data/; load web data in the data step. "
    "e2er reruns the estimation without the web and without e2er's tools (`e2er reproduce`), so a rerun must not "
    "depend on what a website serves that day. Read the tables with sqlite3/pandas or `e2er-data query sql` "
    "(read-only); anything the study needs from the web is loaded by the data analyst with e2er-data into data.db "
    "(or saved under data/) before estimation"
)


def _dotted(node: ast.AST) -> str:
    """``subprocess.run`` for an attribute chain, ``run`` for a name; '' otherwise."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        inner = _dotted(node.value)
        return f"{inner}.{node.attr}" if inner else node.attr
    return ""


def _strings(node: ast.AST) -> list[str]:
    """The string constants in an argument, in source order (a list literal gives its items)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.List | ast.Tuple):
        out: list[str] = []
        for e in node.elts:
            out += _strings(e)
        return out
    if isinstance(node, ast.JoinedStr):
        return ["".join(v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str))]
    return []


#: e2er-data's sources that load data (everything but ``query``).
_LOADING_SOURCES = frozenset({"allium", "yfinance", "fred", "gmd"})


def _argv_of(call: ast.Call) -> list[str]:
    """The command a subprocess call runs, as words, as far as it is literal.

    ``[E2ER_DATA, "yfinance", "history", …]`` (the program from a variable) reads as e2er-data.
    """
    arg = call.args[0] if call.args else next((kw.value for kw in call.keywords if kw.arg == "args"), None)
    if arg is None:
        return []
    words = _words(_strings(arg))
    if (
        isinstance(arg, ast.List | ast.Tuple)
        and arg.elts
        and not (isinstance(arg.elts[0], ast.Constant) and isinstance(arg.elts[0].value, str))
        and words
        and (words[0] in _LOADING_SOURCES or words[0] == "query")
    ):
        return ["e2er-data", *words]
    return words


def _words(parts: list[str]) -> list[str]:
    if len(parts) == 1:
        try:
            return shlex.split(parts[0])
        except ValueError:
            return parts[0].split()
    return parts


def _command_problem(argv: list[str]) -> str | None:
    """Why a command may not run in the estimation; None when it may."""
    if not argv:
        return None
    program = Path(argv[0]).name
    if program in ("sh", "bash", "zsh") and len(argv) >= 3 and argv[1] == "-c":
        return _command_problem(_words([argv[2]]))
    if program in _WEB_PROGRAMS:
        return f"runs `{program}`, which loads from the web"
    if _E2ER_TOOL.match(program):
        if program == "e2er-data" and _query_only(argv[1:]):
            return None
        shown = " ".join(argv[:3])
        return f"runs `{shown}`; during estimation the only e2er tool a script may call is `e2er-data query sql|tables`"
    return None


def _query_only(args: list[str]) -> bool:
    """``e2er-data [--paper-id X] [--specialist Y] query sql|tables …``."""
    rest = list(args)
    while rest and rest[0].startswith("--"):
        flag = rest.pop(0)
        if "=" not in flag and rest:
            rest.pop(0)
    return len(rest) >= 2 and rest[0] == "query" and rest[1] in ("sql", "tables")


def _module_problems(module: str) -> bool:
    return any(module == m or module.startswith(m + ".") for m in NETWORK_MODULES)


def scan_source(source: str, name: str = "<script>") -> list[str]:
    """Every network access and e2er tool call in one script, as ``name:line: what``."""
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return [f"{name}: cannot be read as Python ({e.msg}, line {e.lineno})"]
    problems: list[str] = []
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _module_problems(alias.name):
                    problems.append(f"{name}:{line}: imports {alias.name}, which loads data over the network")
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            full = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
            hit = next((m for m in full if _module_problems(m)), None)
            if hit:
                problems.append(f"{name}:{line}: imports {hit}, which loads data over the network")
        elif isinstance(node, ast.Attribute) and _dotted(node) in ("urllib.request.urlopen", "urllib.request"):
            if not isinstance(getattr(node, "ctx", None), ast.Store):
                problems.append(f"{name}:{line}: uses urllib.request, which loads data over the network")
        elif isinstance(node, ast.Call):
            called = _dotted(node.func)
            last = called.rsplit(".", 1)[-1]
            if called in _RUNNERS or (last in _RUNNER_NAMES and called == last):
                why = _command_problem(_argv_of(node))
                if why:
                    problems.append(f"{name}:{line}: {why}")
            elif _READERS.match(last) and node.args:
                first = _strings(node.args[0])
                if first and _URL.match(first[0]):
                    problems.append(f"{name}:{line}: {last}() reads {first[0][:80]} from the web")
    # One line, one problem (an import of urllib.request also matches its attribute uses).
    seen: set[str] = set()
    out = []
    for p in sorted(set(problems), key=lambda s: (int(s.split(":")[1]) if s.split(":")[1].isdigit() else 0, s)):
        key = ":".join(p.split(":")[:2])
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def _local_imports(source: str, folder: Path) -> list[Path]:
    """The workspace's own modules a script imports (``import helpers`` → helpers.py)."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return [folder / f"{n}.py" for n in sorted(names) if (folder / f"{n}.py").is_file()]


def scan_scripts(scripts: list[Path], workspace: Path) -> list[str]:
    """The problems of these scripts and of the workspace modules they import (each file once)."""
    problems: list[str] = []
    todo = list(scripts)
    done: set[Path] = set()
    while todo:
        path = todo.pop(0)
        if path in done or not path.is_file():
            continue
        done.add(path)
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            name = str(path.relative_to(workspace))
        except ValueError:
            name = path.name
        problems += scan_source(source, name)
        todo += [p for p in _local_imports(source, path.parent) if p not in done]
    return problems


def check_estimation_standalone(workspace: Path, results_relative: str = "estimation_results.json") -> ContractCheck:
    """The output-contract check: a ContractCheck on the results, failing when the estimation chain needs the web."""
    from ..export.reproduce_recipe import estimation_chain
    from .contract_check import KIND_RELIABILITY, ContractCheck

    try:
        scripts = estimation_chain(workspace)
    except OSError:
        scripts = []
    problems = scan_scripts(scripts, workspace)
    if not problems:
        return ContractCheck(results_relative, True, "", kind=KIND_RELIABILITY)
    more = f"; and {len(problems) - 6} more" if len(problems) > 6 else ""
    return ContractCheck(
        results_relative,
        False,
        f"{MESSAGE}. Found: " + "; ".join(problems[:6]) + more + ".",
        kind=KIND_RELIABILITY,
    )
