"""``e2er abstract <folder>``: write a finished study's abstract again with e2er's abstract step.

For a study exported (or published) before the abstract had a step of its own
(src/core/abstract.py). Changes only the abstract:

1. checks that the folder is what was exported or last published (the
   integrity and anchor checks of ``e2er verify``);
2. lays the study out as a workspace in a scratch folder (the final paper as
   ``paper_draft.tex``, the results, the reviews) and runs the abstract
   writer once with the configured backend (``--backend``/``--model``), then
   the abstract check, sending the writer back at most once. The run's
   database is not touched: the call's records go to a scratch database;
3. the check includes the number check: every number of the new abstract is a
   value of the study's results at the precision shown. An abstract that fails
   is reported and nothing in the folder changes;
4. puts the abstract into ``paper/paper.tex`` (in place of its abstract, or
   where one belongs), writes ``paper/abstract.tex``, recompiles
   ``paper/paper.pdf`` with tectonic and shows the abstract in
   ``report.html``;
5. records an amendment per changed file in provenance.json
   (``kind: "abstract_rewritten"``, the model, the e2er version, the reason,
   the fingerprints before and after), which the next ``e2er publish`` puts in
   the dossier;
6. runs the checks of ``e2er verify``; when they fail, every file is put back.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import html
import json
import os
import re
import shutil
import tempfile
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .core import abstract as ab

#: The files the command may change, with provenance.json last.
_CHANGED = ("paper/abstract.tex", "paper/paper.tex", "paper/paper.pdf", "report.html")


class AbstractError(Exception):
    """The abstract cannot be rewritten; the message says why. Nothing in the folder changed."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


@contextlib.contextmanager
def _scratch_database(folder: Path) -> Iterator[None]:
    """The calls' records (events, usage) go to a scratch database, never to the study's run database."""
    from . import config
    from .db import client

    before = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = f"sqlite:///{folder / 'abstract-step.db'}"
    config.get_settings.cache_clear()
    saved = (client._pool, client._backend, client._sqlite_bootstrapped)
    client._pool, client._backend, client._sqlite_bootstrapped = None, "", False
    try:
        yield
    finally:
        client._pool, client._backend, client._sqlite_bootstrapped = saved
        if before is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = before
        config.get_settings.cache_clear()


def _workspace(bundle: Path, ws: Path, template: str) -> None:
    """The study as the abstract step reads it: the final paper, the results, the reviews."""
    from .cli_verify import _reconstruct_workspace
    from .core.research_object import _question_and_title

    _reconstruct_workspace(bundle, ws)
    shutil.copyfile(bundle / "paper" / "paper.tex", ws / "paper_draft.tex")
    for name in ("estimation_results.json", "summary_statistics.json", "figure_spec.json"):
        src = bundle / "results" / name
        if src.is_file() and not (ws / name).exists():
            shutil.copyfile(src, ws / name)
    reviews = bundle / "reviews"
    if reviews.is_dir():
        for f in [*reviews.glob("review_*.md"), reviews / "self_attack_report.json"]:
            if f.is_file():
                shutil.copyfile(f, ws / f.name)
    question, title = _question_and_title(bundle)
    manifest = _load(ws / "manifest.json") or {}
    manifest.update({"pipeline": template, "title": title, "research_question": question})
    (ws / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _report_with(report: str, text: str) -> str:
    """report.html with ``text`` as its abstract (replacing the block, or before "What was checked")."""
    block = f"<div class='abstract'><h3>Abstract</h3><p>{html.escape(text)}</p></div>"
    rx = re.compile(r"<div class='abstract'><h3>Abstract</h3><p>.*?</p></div>", re.S)
    if rx.search(report):
        return rx.sub(lambda _m: block, report, count=1)
    marker = "<h2>What was checked</h2>"
    if marker in report:
        return report.replace(marker, block + marker, 1)
    return report


def _old_words(bundle: Path) -> int:
    for rel in ("paper/abstract.tex", "paper/paper.tex"):
        p = bundle / rel
        if p.is_file():
            tex = p.read_text(encoding="utf-8", errors="replace")
            if ab.environment(tex) is not None:
                return ab.words(tex)
    return 0


def rewrite(
    folder: Path,
    *,
    backend: str | None = None,
    model: str | None = None,
    backend_factory: Callable[[str, str], Any] | None = None,
    compile_pdf: Callable[[Path], None] | None = None,
    say: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Rewrite the abstract of an exported study folder (see the module docstring). Returns a summary.

    ``backend_factory(name, model)`` builds the LLM backend (tests pass a fake one);
    ``compile_pdf(bundle)`` recompiles paper/paper.pdf (default: tectonic, as publish does).
    Raises AbstractError, with the folder unchanged, on any failure.
    """
    from . import __version__
    from .cli_publish import PublishError, _folder_problems, recompile_paper
    from .config import get_settings
    from .core.export.provenance import dump
    from .core.pipeline.components import activate, deactivate
    from .core.pipeline.result_kinds import active_economics
    from .core.pipeline.spec import PipelineError, find_spec
    from .core.strategist.findings import collect_abstract_findings, write_abstract_findings

    b = Path(folder).expanduser().resolve()
    if not (b / "provenance.json").is_file():
        raise AbstractError(f"{b} is not an exported study folder (no provenance.json)")
    if not (b / "paper" / "paper.tex").is_file():
        raise AbstractError("the folder has no paper/paper.tex")
    found = _folder_problems(b)
    if found:
        raise AbstractError("the folder is not what was exported or last published: " + "; ".join(found))
    prov = _load(b / "provenance.json") or {}
    run = prov.get("run") or {}
    template = str(run.get("template") or "empirical")
    try:
        spec = find_spec(template)
    except PipelineError as e:
        raise AbstractError(f"the study's template {template!r} is not available: {e}") from e

    settings = get_settings()
    name = backend or settings.llm_backend
    model_name = model or settings.default_model_for(name)
    old_words = _old_words(b)
    paper_id = str(run.get("paper_id") or "abstract")

    with tempfile.TemporaryDirectory() as td:
        scratch = Path(td)
        ws = scratch / "workspace"
        ws.mkdir()
        _workspace(b, ws, template)
        token = activate(spec)
        # The CLI backends run the writer in the study's workspace, found by its paper id: the scratch one.
        from . import home

        known_before = home._KNOWN.get(paper_id)
        home.remember_workspace(paper_id, ws)
        try:
            write_abstract_findings(ws, collect_abstract_findings(ws, spec.panel()))
            economics = active_economics()
            with _scratch_database(scratch):
                if backend_factory is not None:
                    llm = backend_factory(name, model_name)
                else:
                    from .modules.llm.registry import get_backend

                    llm = get_backend(get_settings(), name, model_name)

                async def execute(focus: str) -> bool:
                    from .core.specialists.contracts import WorkOrder
                    from .core.specialists.dispatcher import execute_work_order

                    order = WorkOrder(
                        paper_id=paper_id,
                        specialist="abstract_writer",
                        focus=focus,
                        context=ab.work_context(ws, paper_id),
                        output_file=ab.ABSTRACT_FILE,
                    )
                    c = await execute_work_order(order, llm, ws, model_name, None, None, name)
                    if not c.success:
                        say(f"note: the abstract writer's call reported: {(c.error or '')[:300]}")
                    return c.success

                outcome = asyncio.run(ab.write_abstract(ws, execute, resend=True, economics=economics))
        finally:
            deactivate(token)
            if known_before is None:
                home._KNOWN.pop(paper_id, None)
            else:
                home._KNOWN[paper_id] = known_before
        if not outcome.passed:
            written = ws / ab.ABSTRACT_FILE
            last = written.read_text(encoding="utf-8").strip() if written.is_file() else ""
            raise AbstractError(
                f"the new abstract failed its check after {outcome.attempts} attempt(s): "
                + "; ".join(outcome.check.problems)
                + ". Nothing in the folder changed."
                + (f"\nThe abstract of the last attempt:\n{last}" if last else "")
            )
        if not outcome.check.compared and outcome.check.numbers:
            raise AbstractError("the study has no results files to compare the abstract's numbers with")
        new_abstract = (ws / ab.ABSTRACT_FILE).read_text(encoding="utf-8")
    # The study's title is read from abstract.tex when it has one (research_object): kept as it was.
    old_abstract = b / "paper" / "abstract.tex"
    if old_abstract.is_file():
        new_abstract = ab.with_title(new_abstract, ab.title_command(old_abstract.read_text(encoding="utf-8")))

    # Apply: the files first, provenance.json last; everything is put back when a step fails.
    before = {rel: ((b / rel).read_bytes() if (b / rel).is_file() else None) for rel in (*_CHANGED, "provenance.json")}

    def restore() -> None:
        for rel, data in before.items():
            path = b / rel
            if data is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(data)

    try:
        (b / "paper" / "abstract.tex").write_text(new_abstract, encoding="utf-8")
        tex = b / "paper" / "paper.tex"
        tex.write_text(ab.insert(tex.read_text(encoding="utf-8"), new_abstract), encoding="utf-8")
        try:
            (compile_pdf or recompile_paper)(b)
        except PublishError as e:
            raise AbstractError(f"paper.pdf could not be recompiled: {e}") from e
        report = b / "report.html"
        if report.is_file():
            report.write_text(
                _report_with(report.read_text(encoding="utf-8"), ab.readable(new_abstract)), encoding="utf-8"
            )
        prov = json.loads(before["provenance.json"] or b"{}")
        listed = prov["files"]
        at = _now()
        written = []
        for rel in _CHANGED:
            path = b / rel
            if not path.is_file():
                continue
            data = path.read_bytes()
            old = before[rel]
            meta = listed.get(rel)
            if old is not None and meta is None:
                continue  # a file provenance.json does not list (an earlier publish's record): left out
            if old is not None and _sha(old) == _sha(data):
                continue
            entry = {
                "path": rel,
                "kind": ab.AMENDMENT_KIND,
                "sha256_before": (meta or {}).get("sha256") if old is not None else None,
                "sha256_after": _sha(data),
                "reason": ab.AMENDMENT_REASON,
                "at": at,
                "model": model_name,
                "backend": name,
                "e2er_version": __version__,
                "bytes_before": (meta or {}).get("bytes") if old is not None else None,
            }
            listed[rel] = {"sha256": entry["sha256_after"], "bytes": len(data)}
            prov.setdefault("amendments", []).append(entry)
            written.append(entry)
        prov["files"] = dict(sorted(listed.items()))
        (b / "provenance.json").write_text(dump(prov), encoding="utf-8")

        from .cli_verify import _run_checks, _verdict

        checks = _run_checks(b, False)
        verdict, rc = _verdict(checks)
        if rc != 0:
            raise AbstractError(f"the folder does not verify with the new abstract:\n{verdict}")
    except BaseException:
        restore()
        raise
    return {
        "old_words": old_words,
        "new_words": outcome.check.words,
        "numbers": outcome.check.numbers,
        "attempts": outcome.attempts,
        "abstract": ab.readable(new_abstract),
        "amended": [e["path"] for e in written],
        "model": model_name,
        "backend": name,
        "verdict": verdict,
    }


def abstract(folder: str, *, backend: str | None = None, model: str | None = None) -> int:
    """Entry point of ``e2er abstract``."""
    try:
        out = rewrite(Path(folder), backend=backend, model=model)
    except AbstractError as e:
        print(f"error: {e}")
        return 1
    print(f"✓ New abstract ({out['new_words']} words, before {out['old_words']}; {out['backend']} {out['model']}):")
    print(f"  {out['abstract']}")
    nums = ", ".join(out["numbers"]) or "none"
    print(f"✓ Abstract check passed on attempt {out['attempts']}; numbers: {nums}, each a value of the results")
    print(
        f'✓ Recorded {len(out["amended"])} amendment(s) in provenance.json (kind "{ab.AMENDMENT_KIND}"): '
        + ", ".join(out["amended"])
    )
    print(out["verdict"])
    print("  The next `e2er publish` shows the amendments in the dossier.")
    return 0
