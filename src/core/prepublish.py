"""Reproduce before publishing: `e2er publish` runs the study's code again, as `e2er reproduce` does, first.

Before anything leaves the machine (``--to``, ``--zenodo``, ``--github``) or the folder is prepared for
publishing in the browser (``--offline``), publish runs the reproduction of the folder it is about to publish
in the Docker sandbox, with the same code as ``e2er reproduce --yes`` (src/cli_reproduce.py), and publishes
only when the study reproduces. ``--blind`` runs it on the anonymised copy. ``--dry-run`` runs nothing heavy:
it says that publish will reproduce first, unless ``--reproduce`` asks for the run.

``--skip-reproduce "<reason>"`` publishes without the run, and the description says so, with the reason.

The outcome goes into what publish writes and sends as one entry of the description's ``verification`` list
(e2er.json, the request to e2er.org), next to verify's checks::

    {"check": "reproduction", "status": "PASS" | "SKIP", "detail": "<one sentence>",
     "reproduction": {"reproduced": true, "date": "...", "e2er_version": "...", "platform": {...},
                      "python": "3.12.14", "sandbox": "python:3.12-slim", "verdict": "...",
                      "category": "reproduced", "exit_code": 0, "counts": {...},
                      "seconds": 1512.3, "reload_seconds": 1300.0, "reloaded_sources": ["Project Gutenberg"]}}

It lives there, not in provenance.json or the dossier: provenance.json fixes the content id (the SHA-256 of
provenance.json) and the dossier's id is the SHA-256 of its document, and both must stay the same when the
same study is published again from another computer. The site's format (docs/schemas/research-object.schema.json)
takes extra keys in a verification entry. The whole report is kept on this computer in
``.e2er/reproduction.json`` (a dotfile folder export and verify leave alone).
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CHECK = "reproduction"
#: Where publish keeps the full JSON report of the run in the study folder (never exported or published).
REPORT_FILE = ".e2er/reproduction.json"

DOCKER_HELP = (
    "e2er publish runs the study's code again in a Docker sandbox before it publishes, and {why}. Start Docker "
    "(Docker Desktop on macOS and Windows: open it and wait until it says it is running; on Linux: "
    "`sudo systemctl start docker`), or install it from https://docs.docker.com/get-docker/, and run the same "
    'command again. To publish without the run, add --skip-reproduce "<why>": the study then says that it was '
    "not reproduced before publishing, and why."
)


@dataclass
class Outcome:
    """What publish does next: go on (``ok``), with this verification entry (None: none to add)."""

    ok: bool
    record: dict[str, Any] | None = None
    #: The plain lines publish prints (the reproduction's own report is printed while it runs).
    lines: list[str] = field(default_factory=list)
    #: The full JSON report of the run, when one ran.
    report: dict[str, Any] | None = None


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _version() -> str:
    from .. import __version__

    return __version__


def skipped(reason: str) -> Outcome:
    """``--skip-reproduce "<reason>"``: published without the run, and said so."""
    why = " ".join(str(reason).split())
    record = {
        "check": CHECK,
        "status": "SKIP",
        "detail": f"not reproduced before publishing: {why}",
        "reproduction": {"reproduced": False, "skipped": why, "date": _now(), "e2er_version": _version()},
    }
    return Outcome(
        True,
        record,
        [f"warning: --skip-reproduce: the study is published without running its code again first ({why})."],
    )


def _nothing_to_run(folder: Path) -> str | None:
    """Why a folder without reproduce.json has no code to run again (None: it should have one)."""
    from .export.reproduce_recipe import folder_reason

    why = folder_reason(folder)
    if why and ("has no estimation results" in why or "has no estimation script" in why):
        return why
    return None


def counts(report: dict[str, Any]) -> dict[str, Any]:
    """The summary counts of a reproduce report (docs/reproduce-report.md)."""
    from . import reproduce as rp

    results = [r for r in report.get("results") or [] if isinstance(r, dict)]
    compared = [r for r in results if not r.get("not_compared")]
    out: dict[str, Any] = {"values": sum(int(r.get("values") or 0) for r in compared)}
    for label in rp.LABELS:
        out[label] = sum(int((r.get("counts") or {}).get(label) or 0) for r in compared)
    out["result_files"] = len(compared)
    out["result_files_not_compared"] = len(results) - len(compared)
    tables = report.get("tables") if isinstance(report.get("tables"), dict) else None
    if tables and not tables.get("skipped"):
        out["tables"] = int(tables.get("rendered") or 0)
        out["tables_identical"] = len(tables.get("identical") or [])
    inputs = [i for i in report.get("inputs") or [] if isinstance(i, dict) and not i.get("output")]
    out["inputs"] = len(inputs)
    out["inputs_identical"] = sum(1 for i in inputs if i.get("status") in ("identical", rp.SAME_ROWS))
    out["inputs_reloaded"] = sum(1 for i in inputs if i.get("reloaded"))
    return out


def record_from(report: dict[str, Any]) -> dict[str, Any]:
    """The verification entry for a run that reproduced."""

    def obj(value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    env = obj(report.get("environment"))
    sandbox = obj(env.get("sandbox"))
    host = obj(report.get("host"))
    c = counts(report)
    matched = c.get("identical", 0) + c.get("same_at_precision", 0)
    detail = (
        f"reproduced before publishing, on {str(_now())[:10]} with e2er {host.get('e2er_version') or _version()}"
        + (f" in Docker ({sandbox.get('base')})" if sandbox.get("base") else "")
        + f": {matched} of {c['values']} values identical or the same at the published precision"
    )
    if "tables" in c:
        detail += f", {c['tables_identical']} of {c['tables']} tables identical"
    return {
        "check": CHECK,
        "status": "PASS",
        "detail": detail,
        "reproduction": {
            "reproduced": True,
            "date": _now(),
            "e2er_version": str(host.get("e2er_version") or _version()),
            "platform": {k: host[k] for k in ("system", "release", "machine", "python") if k in host},
            "python": env.get("python"),
            "sandbox": sandbox.get("base"),
            "verdict": report.get("verdict"),
            "category": report.get("category"),
            "exit_code": report.get("exit_code"),
            "counts": c,
            **timing(report),
        },
    }


def timing(report: dict[str, Any]) -> dict[str, Any]:
    """How long the rerun's steps took (``seconds``), the steps that loaded data again (``reload_seconds``),
    and the sources they loaded from (``reloaded_sources``); empty when the report records no times."""
    steps = [s for s in report.get("steps") or [] if isinstance(s, dict) and isinstance(s.get("seconds"), int | float)]
    if not steps:
        return {}
    out: dict[str, Any] = {"seconds": round(sum(float(s["seconds"]) for s in steps), 1)}
    reload = [float(s["seconds"]) for s in steps if s.get("reload")]
    if reload:
        out["reload_seconds"] = round(sum(reload), 1)
        names: list[str] = []
        for src in report.get("sources") or []:
            name = src.get("source") if isinstance(src, dict) else None
            if isinstance(name, str) and name and name not in names:
                names.append(name)
        if names:
            out["reloaded_sources"] = names
    return out


def run_reproduction(folder: Path, report: dict[str, Any]) -> int:
    """`e2er reproduce --yes` on ``folder`` in the Docker sandbox; fills ``report`` (the JSON report)."""
    from ..cli_reproduce import reproduce

    return reproduce(str(folder), yes=True, sandbox=True, report=report)


def docker_missing() -> str | None:
    """Why Docker cannot run the reproduction, or None when it answers."""
    from . import reproduce_sandbox as rs

    docker, why = rs.available()
    return None if docker is not None else why


def reproduce_first(folder: Path, *, keep_report: bool = True, quiet: bool = False) -> Outcome:
    """Run the reproduction of ``folder`` before publishing it; publish goes on only when it reproduces.

    ``keep_report``: write the full JSON report into ``.e2er/reproduction.json`` of the folder (not for a
    copy that is thrown away). ``quiet``: the reproduction's own report is not printed (a dry run prints
    only the request on standard output).
    """
    folder = Path(folder)
    if not (folder / "reproduce.json").is_file():
        why = _nothing_to_run(folder)
        if why:
            record = {
                "check": CHECK,
                "status": "SKIP",
                "detail": f"nothing to run again: {why}",
                "reproduction": {
                    "reproduced": False,
                    "nothing_to_run": why,
                    "date": _now(),
                    "e2er_version": _version(),
                },
            }
            return Outcome(True, record, [f"note: no reproduction before publishing: {why}"])
        from .export.reproduce_recipe import folder_reason

        return Outcome(
            False,
            None,
            [
                "error: e2er publish runs the study's code again before it publishes, and this folder has no "
                f"reproduce.json. {folder_reason(folder) or ''}".rstrip(),
                '  To publish without the run, add --skip-reproduce "<why>". Nothing was sent.',
            ],
        )
    why = docker_missing()
    if why:
        text = DOCKER_HELP.format(why=why[0].lower() + why[1:])
        return Outcome(False, None, [f"error: {text} Nothing was sent."])
    print(
        "Running the study's code again before publishing (as `e2er reproduce` does, in Docker) ...",
        file=sys.stderr if quiet else sys.stdout,
        flush=True,
    )
    report: dict[str, Any] = {}
    out = io.StringIO()
    with contextlib.redirect_stdout(out) if quiet else contextlib.nullcontext():
        code = run_reproduction(folder, report)
    if quiet:
        print(out.getvalue(), end="", file=sys.stderr)
    if keep_report and report:
        target = folder / REPORT_FILE
        try:
            target.parent.mkdir(exist_ok=True)
            target.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8", newline="\n")
        except OSError:
            pass
    if code == 0 and report.get("exit_code") == 0:
        return Outcome(True, record_from(report), ["✓ The study reproduces: " + str(report.get("verdict"))], report)
    verdict = str(report.get("verdict") or "the reproduction did not run (see the lines above)")
    kept = f" The full report is in {REPORT_FILE}." if keep_report and report else ""
    if report.get("category") == "source_unavailable":
        # Not the study: a source did not answer while its data were loaded again.
        return Outcome(
            False,
            None,
            [
                f"error: not published yet: {verdict}",
                "  Run the same command again later. To publish now without the run, add --skip-reproduce "
                '"<why>": the study then says that it was not reproduced before publishing, and why. Nothing was '
                "sent." + kept,
            ],
            report,
        )
    return Outcome(
        False,
        None,
        [
            f"error: not published: the study does not reproduce. {verdict}",
            "  The report above says which step failed or which values and tables differ." + kept,
            "  Fix the study's code or data, export it again (`e2er export`), and publish the new folder; "
            "`e2er reproduce <folder>` runs the same check on its own.",
            '  To publish anyway, add --skip-reproduce "<why>": the study then says that it was not reproduced '
            "before publishing, and why. Nothing was sent.",
        ],
        report or None,
    )
