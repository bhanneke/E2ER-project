"""The names the dashboard shows: one place for every step, specialist, template, action, event, check and status.

Internal ids (``number_check``, ``paper_drafter``, ``phase_start``,
``skills.installed``) are how the code, the database and the files refer to
things. A researcher reads the names below instead. The dashboard shows ids
only inside a folded "Technical details", where they help with a bug report.

A template file can name its own steps (``label = "…"`` on a step) and itself
(``title = "…"`` at the top); those names come first. Anything not named here
or in its template is shown with its underscores as spaces, which the
dashboard vocabulary test (tests/test_dashboard_vocabulary.py) catches for the
built-in templates.
"""

from __future__ import annotations

from typing import Any

#: Steps of the built-in templates, and the stops e2er makes on its own.
STEPS: dict[str, str] = {
    "initial": "Design, data, estimation and draft",
    "iterative": "Improve until it stops getting better",
    "estimation_gate": "Estimation check",
    "self_attack": "Self-critique",
    "polish": "Polish",
    "review": "Review panel",
    "revision": "Revision",
    "replication": "Replication package",
    "review_design": "Design review",
    "preregister": "Pre-registration",
    "review_draft": "Draft review",
    "event_window_gate": "Event-window check",
    "fetch": "Fetch and verify the package",
    "plan": "Plan the reproduction",
    "review_plan": "Plan review",
    "sandbox_run": "Run the code in Docker",
    "compare": "Compare every number",
    "reproduction_gate": "Reproduction check",
    "review_report": "Report review",
    # Stops e2er makes on its own, outside the template's steps.
    "number_check": "Number check",
    "output_contract": "Output that failed its check",
}

#: What kind of step it is, as the step list says it.
STEP_KINDS: dict[str, str] = {
    "researcher": "your review",
    "preregister": "your review, frozen on approval",
    "gate": "check",
    "strategist": "specialists",
    "specialists": "specialists",
    "aggregate": "reviewers",
}

#: Each specialist by the work it does.
SPECIALISTS: dict[str, str] = {
    "idea_developer": "Research plan",
    "literature_scanner": "Literature review",
    "identification_strategist": "Identification strategy",
    "theory_specialist": "Formal model",
    "data_architect": "Data plan",
    "data_analyst": "Data and descriptive analysis",
    "econometrics_specialist": "Estimation",
    "paper_drafter": "Paper draft",
    "section_writer": "Sections and table layout",
    "abstract_writer": "Abstract",
    "latex_formatter": "LaTeX formatting",
    "self_attacker": "Self-critique",
    "polish_formula": "Polish of the formulas",
    "polish_numerics": "Polish of the numbers",
    "polish_institutions": "Polish of the institutional detail",
    "polish_equilibria": "Polish of the equilibria",
    "polish_bibliography": "Polish of the bibliography",
    "mechanism_reviewer": "Review of the mechanism",
    "technical_reviewer": "Technical review",
    "literature_reviewer": "Review of the literature",
    "data_reviewer": "Review of the data",
    "identification_reviewer": "Review of the identification",
    "writing_reviewer": "Review of the writing",
    "revisor": "Revision",
    "patch_revisor": "Targeted corrections",
    "replication_packager": "Replication package",
    "replication_planner": "Reproduction plan",
    "reproduction_comparer": "Comparison of the reproduced numbers",
}

#: The built-in templates.
TEMPLATES: dict[str, str] = {
    "empirical": "Empirical study",
    "empirical-preregistered": "Empirical study, pre-registered",
    "event-study-finance": "Event study in finance",
    "replication": "Replication of a published study",
}

#: What a researcher did at a stop (the ``action`` of a ``researcher_action`` event).
ACTIONS: dict[str, str] = {
    "approve": "Approved",
    "edit": "Edited a file",
    "instruction": "Gave an instruction",
    "send_back": "Sent back",
    "rerun": "Ran again from a step",
    "cancel": "Cancelled the run",
}

#: Why the run stopped for you (the kind of the stop).
STOP_KINDS: dict[str, str] = {
    "researcher": "Your review",
    "preregister": "Pre-registration",
    "review_at": "A stop you asked for",
    "gate": "A check failed",
    "deviation": "The pre-registered plan changed",
    "contract": "Output that failed its check",
    "numbers": "Table numbers differ from the results",
}

#: Events of the run's log, as "what happened".
EVENTS: dict[str, str] = {
    "phase_start": "Step started",
    "phase_end": "Step finished",
    "specialist_start": "Specialist started",
    "specialist_end": "Specialist finished",
    "specialist_failed": "Specialist failed",
    "specialist_skipped": "Specialist skipped",
    "gate_halted": "Check stopped the run",
    "gate_shadow": "Check failed (recorded, the run went on)",
    "gate_enforced": "Check passed",
    "contract_failed": "Output failed its check",
    "contract_halted": "Output failed its check in every attempt",
    "contract_accepted": "Output kept as it is",
    "researcher_action": "Your action",
    "researcher_input": "Your instruction",
    "researcher_rerun": "Ran again from a step",
    "awaiting_review": "Stopped for you",
    "paper_paused": "Paused",
    "preregistration": "Pre-registration frozen",
    "preregistration_check": "Pre-registration compared with the plan",
    "run_identity": "e2er version recorded",
    "backend_identity": "AI provider recorded",
    "cancelled": "Cancelled",
    "failed": "Failed",
    "checks_skipped": "Checks skipped",
    "edits_failed": "Corrections could not be applied",
    "submit_failed": "Submission failed",
}

#: The checks of Preflight and Setup (`e2er doctor`).
CHECKS: dict[str, str] = {
    "python": "Python",
    "db": "Study database",
    "skills.installed": "Specialists' instructions",
    "workspace.writable": "Studies folder",
    "byod.local_data_dir": "Your data",
    "byod.literature": "Your literature",
    "docker": "Docker (replication only)",
    "data.list_data_sources": "Data sources",
    "data.yfinance.history": "Yahoo Finance",
    "data.fred.key": "FRED key",
    "data.fred.observations": "FRED",
    "data.gmd.versions": "Global Macro Database",
    "data.allium.list_tables": "Allium",
    "lit.search_papers": "Literature search",
    "lit.read_reference (OA PDF)": "Reading open-access PDFs",
    "lit.zotero.library": "Zotero web library",
}

#: The checks of `e2er verify` (the finish page).
VERIFY_CHECKS: dict[str, str] = {
    "integrity": "Every file matches its fingerprint",
    "anchor": "The record on e2er.org matches the folder",
    "numbers": "Every table number traces to its source",
    "tables": "The tables match the results",
    "spec": "The estimation follows the declared design",
    "citations": "Every citation is in the bibliography",
    "preregistration": "The pre-registration is unchanged",
    "reproduction": "The reproduced numbers",
    "published": "The published record",
}

#: The AI providers, as the checks name them (``backend.<name>``).
BACKENDS: dict[str, str] = {
    "claude_code": "Claude Code",
    "codex": "Codex",
    "gemini": "Gemini CLI",
    "anthropic": "Anthropic API",
    "openrouter": "OpenRouter API",
}

#: Statuses of a run as stored, beyond src/core/run_outcome.STATUS_WORDS.
_RUNNING_STATUSES = {
    "idea",
    "designing",
    "data_collection",
    "in_progress",
    "ceiling_check",
    "self_attack",
    "polish",
    "review",
    "revision",
    "replication",
}


def _plain(name: str) -> str:
    text = str(name or "").replace("_", " ").replace("-", " ").strip()
    return text[:1].upper() + text[1:] if text else ""


def step(name: str, spec: Any = None) -> str:
    """A step by name; the template's own ``label`` comes first."""
    if spec is not None:
        try:
            st = spec.step(name)
        except Exception:  # noqa: BLE001 - a spec without the step: the map below
            st = None
        if st is not None and getattr(st, "label", None):
            return str(st.label)
    return STEPS.get(name) or SPECIALISTS.get(name) or _plain(name)


def step_kind(kind: str) -> str:
    return STEP_KINDS.get(kind, _plain(kind).lower())


def specialist(name: str) -> str:
    return SPECIALISTS.get(name) or _plain(name)


def step_or_specialist(name: str, spec: Any = None) -> str:
    """What a researcher can send back: a step of the template or one specialist."""
    if name in SPECIALISTS and (spec is None or spec.step(name) is None):
        return f"{SPECIALISTS[name]} (one specialist)"
    return step(name, spec)


def template(name: str, spec: Any = None) -> str:
    if spec is not None and getattr(spec, "title", None):
        return str(spec.title)
    return TEMPLATES.get(name) or _plain(name)


def action(name: str) -> str:
    return ACTIONS.get(name) or _plain(name)


def stop_kind(kind: str) -> str:
    return STOP_KINDS.get(kind) or "Stopped for you"


def event(name: str) -> str:
    return EVENTS.get(name) or _plain(name)


def check(name: str) -> str:
    if name.startswith("backend."):
        backend = name.split(".", 1)[1]
        return f"AI provider ({BACKENDS.get(backend, _plain(backend))})"
    return CHECKS.get(name) or _plain(name)


def verify_check(name: str) -> str:
    return VERIFY_CHECKS.get(name) or _plain(name)


def backend(name: str) -> str:
    return BACKENDS.get(name) or _plain(name)


def status(stored: str) -> str:
    """A stored status as the pages show it."""
    from .run_outcome import STATUS_WORDS

    s = str(stored or "").strip().lower()
    if s in STATUS_WORDS:
        return STATUS_WORDS[s]
    if s == "rejected":
        return STATUS_WORDS["stopped"]
    if s in _RUNNING_STATUSES:
        return "running"
    return _plain(s).lower()


def file(path: str) -> str:
    """A file the way the pages name it: the file name itself is the plain name."""
    return str(path)


def register(env: Any) -> None:
    """Make these names available to the dashboard's templates as filters."""
    env.filters["step_label"] = step
    env.filters["kind_label"] = step_kind
    env.filters["specialist_label"] = specialist
    env.filters["template_label"] = template
    env.filters["action_label"] = action
    env.filters["stop_label"] = stop_kind
    env.filters["event_label"] = event
    env.filters["check_label"] = check
    env.filters["backend_label"] = backend
