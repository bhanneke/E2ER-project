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

import re
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
    "design_boundary": "Propose the field's boundary",
    "retrieve_boundary": "Retrieve the papers from OpenAlex",
    "review_boundary": "Boundary review",
    "citation_network": "Citation network and completeness check",
    "main_path": "Main path and key routes",
    "robustness": "Main paths of the alternative boundaries",
    "propose_lanes": "Propose lanes as questions",
    "review_lanes": "Lane review",
    "draw_map": "Map, reading list and exports",
    "write_review": "Field review draft",
    "citation_check": "Citation check",
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
    "field_boundary_designer": "Boundary of the field",
    "field_lane_mapper": "Lanes of the field map",
    "field_review_writer": "Field review",
}

#: The built-in templates.
TEMPLATES: dict[str, str] = {
    "empirical": "Empirical study",
    "empirical-preregistered": "Empirical study, pre-registered",
    "event-study-finance": "Event study in finance",
    "replication": "Replication of a published study",
    "field-map": "Map a research field",
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
    "paused_plan_limit": "Paused: the plan's usage limit was reached",
    "preregistration": "Pre-registration frozen",
    "preregistration_check": "Pre-registration compared with the plan",
    "run_identity": "e2er version recorded",
    "backend_identity": "AI provider recorded",
    "cancelled": "Cancelled",
    "failed": "Failed",
    "checks_skipped": "Checks skipped",
    "edits_failed": "Corrections could not be applied",
    "submit_failed": "Submission failed",
    "revision_not_applied": "Revision changed nothing",
    # The iterative mode: rounds of improvement, the ceiling check after each,
    # the one change of approach, and the self-critique.
    "improvement_round": "Round of improvement",
    "ceiling_check": "Ceiling check",
    "pivot": "Change of approach",
    "improvement_stopped": "Rounds ended",
    "self_critique": "Self-critique",
    "polish_applied": "Polish notes considered",
}

#: What the ceiling check after a round of improvement decided (its ``verdict``).
CEILING_VERDICTS: dict[str, str] = {
    "continue": "another round",
    "pivot": "a change of approach",
    "proceed_to_review": "ready for review",
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
    "gemini": "Gemini CLI (not tested)",
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


def ceiling_verdict(verdict: str) -> str:
    return CEILING_VERDICTS.get(verdict) or _plain(verdict).lower()


def round_summary(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The rounds of the iterative mode in plain words, from the run's events.

    ``events`` are rows with ``event_type`` and ``payload`` (a dict or its JSON
    text), in any order: each round is found by its number. One entry per
    round: ``round``, ``specialists`` (their names as the dashboard says them),
    ``reason``, and, when recorded, ``ceiling`` (what the check decided),
    ``ceiling_reason``, ``pivot`` (the specialists of the change of approach),
    ``pivot_refused`` (those refused because they would rewrite the whole
    draft) and ``ended`` (the strategist ended the rounds here).
    """
    import json

    rounds: dict[int, dict[str, Any]] = {}
    for e in events:
        et = str(e.get("event_type") or "")
        if et not in ("improvement_round", "ceiling_check", "pivot", "improvement_stopped"):
            continue
        data = e.get("payload")
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except ValueError:
                data = {}
        if not isinstance(data, dict) or not isinstance(data.get("round"), int):
            continue
        r = rounds.setdefault(data["round"], {"round": data["round"], "specialists": [], "reason": ""})
        if et == "improvement_round":
            r["specialists"] = [specialist(str(x)) for x in data.get("specialists") or []]
            r["reason"] = str(data.get("reason") or "")
        elif et == "ceiling_check":
            r["ceiling"] = ceiling_verdict(str(data.get("verdict") or ""))
            r["ceiling_reason"] = str(data.get("reason") or "")
        elif et == "pivot":
            r["pivot"] = [specialist(str(x)) for x in data.get("specialists") or []]
            refused = [x for x in data.get("refused") or [] if isinstance(x, dict)]
            if refused:
                r["pivot_refused"] = [specialist(str(x.get("specialist") or "")) for x in refused]
        else:
            r["ended"] = True
            r["reason"] = r["reason"] or str(data.get("reason") or "")
    return [rounds[k] for k in sorted(rounds)]


def check(name: str) -> str:
    if name.startswith("backend."):
        backend = name.split(".", 1)[1]
        return f"AI provider ({BACKENDS.get(backend, _plain(backend))})"
    return CHECKS.get(name) or _plain(name)


#: Setting names in `e2er doctor`'s text, and what the dashboard calls them.
SETTINGS: dict[str, str] = {
    "LITERATURE_BIBTEX_FILE": "the .bib file",
    "LITERATURE_DIR": "the literature folder",
    "LOCAL_DATA_DIR": "the data folder",
    "LLM_BACKEND": "the AI provider",
    "ANTHROPIC_API_KEY": "the Anthropic API key",
    "OPENROUTER_API_KEY": "the OpenRouter API key",
    "FRED_API_KEY": "the FRED key",
    "ALLIUM_API_KEY": "the Allium key",
    "ZOTERO_API_KEY": "the Zotero key",
    "SEMANTIC_SCHOLAR_API_KEY": "the Semantic Scholar key",
    "OPENALEX_API_KEY": "the OpenAlex key",
    "ZENODO_TOKEN": "the Zenodo key",
    "CLAUDE_CODE_PATH": "the location of Claude Code",
    "CODEX_PATH": "the location of the Codex CLI",
    "GEMINI_PATH": "the location of the Gemini CLI",
    "DATABASE_URL": "the database address",
    "POSTGRES_URL": "the database address",
}

#: `e2er doctor`'s own sentences that the dashboard says differently: (check, start of the text) → plain text.
_DETAILS: list[tuple[str, str, str]] = [
    ("backend", "no AI access is set up", "No AI provider is set up yet. Choose one under Settings."),
    ("backend.", "API key configured", "API key saved. Billed per use."),
    ("byod.local_data_dir", "LOCAL_DATA_DIR not set", "No data folder chosen. e2er fetches public data."),
    (
        "byod.literature",
        "no LITERATURE_BIBTEX_FILE",
        "No literature chosen. e2er searches OpenAlex for literature.",
    ),
    ("data.fred.key", "FRED_API_KEY not set", "No FRED key saved."),
    ("data.fred.observations", "FRED_API_KEY not set", "No FRED key saved."),
    ("data.fred.observations", "not requested", "Not asked: the FRED key has the wrong format."),
    ("data.allium.list_tables", "ALLIUM_API_KEY not set", "No Allium key saved."),
    ("lit.zotero.library", "ZOTERO_API_KEY", "No Zotero web library set up."),
    ("skills.installed", "skill loader importable", "Found."),
]


#: What a check that could not reach its service is called in the sentence that says so.
_REACHED: dict[str, str] = {
    "data.yfinance.history": "Yahoo Finance",
    "data.fred.observations": "FRED",
    "data.gmd.versions": "The Global Macro Database",
    "data.allium.list_tables": "Allium",
    "lit.search_papers": "The literature search (OpenAlex, arXiv)",
    "lit.read_reference (OA PDF)": "The server of the open-access PDF",
    "lit.zotero.library": "The Zotero web library",
}

#: The marks of a network error in a check's text (curl, httpx, requests, DNS, a proxy).
NETWORK_ERROR = re.compile(
    r"ConnectionError|ConnectError|ConnectTimeout|connection attempts failed|Failed to connect|curl: \(\d+\)|"
    r"transport error|timed out|Name or service not known|nodename nor servname|Network is unreachable|"
    r"could not download|Temporary failure in name resolution|getaddrinfo|Max retries exceeded|"
    r"Connection refused|SSLError|ProxyError|\[Errno (?:8|49|50|51|60|61|64|65)\]",
    re.IGNORECASE,
)


def unreachable_sentence(what: str) -> str:
    return f"{what} could not be reached. Check the internet connection; e2er tries again when you start a study."


def check_detail(name: str, detail: str) -> str:
    """`e2er doctor`'s text for one check, as the dashboard says it: no setting names, no code paths.

    The terminal keeps the doctor's own text; Preflight and Setup show this one and keep the original
    under "Technical details".
    """
    text = (detail or "").strip()
    if NETWORK_ERROR.search(text):
        return unreachable_sentence(_REACHED.get(name) or check(name))
    if re.match(r"^[A-Z]\w*(Error|Exception)\(", text):
        return "This check could not run. The technical details say why."
    if name == "lit.search_papers" and re.match(r"0 papers via", text):
        return (
            "The literature search found no papers: OpenAlex and arXiv could not be reached or answered nothing. "
            "Check the internet connection; e2er tries again when you start a study."
        )
    for check_name, start, plain in _DETAILS:
        if (name == check_name or (check_name.endswith(".") and name.startswith(check_name))) and text.startswith(
            start
        ):
            return plain
    if name.startswith("backend."):
        # "CLI at /path ($0 on the subscription); signed in" → "found; signed in"
        if m := re.match(r"CLI at .+?( \(\$0 on the subscription\);|, but|;) (.*)$", text):
            return f"Found{', but' if m.group(1) == ', but' else ';'} {m.group(2)}"
        if m := re.match(r"`(\w+)` CLI not found", text):
            return (
                f"`{m.group(1)}` is not installed, or e2er cannot find it. "
                "Install it, or give its location under Settings."
            )
        if re.match(r"\w+_API_KEY not set", text):
            return "No API key saved. Add it under Settings."
    if name == "skills.installed" and (m := re.match(r"(\d+) skill files", text)):
        return f"{m.group(1)} instruction files"
    if name == "db" and text.startswith("SQLite default"):
        return "Kept on this computer" + (f" ({m.group(1)})" if (m := re.search(r"at (.+)\)$", text)) else "") + "."
    if name == "workspace.writable":
        if m := re.match(r"(.+?) (?:\(SDK backend|is outside)", text):
            return f"Studies are written to {m.group(1)}."
        text = text.replace("config tree", "settings folder")
    if name == "data.list_data_sources" and text.startswith("catalog: "):
        return "Available: " + text[len("catalog: ") :]
    text = re.sub(r"FRED_API_KEY has the format of a FRED key", "The FRED key has the right format", text)
    text = re.sub(r"FRED_API_KEY is not a FRED key", "The saved FRED key is not a FRED key", text)
    text = re.sub(r"LITERATURE_BIBTEX_FILE=(\S+) not found", r"The .bib file \1 was not found", text)
    text = re.sub(r"LOCAL_DATA_DIR=(\S+) is not a directory", r"The data folder \1 does not exist", text)
    text = re.sub(r"^literature dir (\S+) is not a directory", r"The literature folder \1 does not exist", text)
    text = re.sub(r"^bibtex \((\d+) entries\)", r".bib file with \1 entries", text)
    text = text.replace(
        "unset DATABASE_URL / POSTGRES_URL to use the SQLite default",
        "remove the database address from the settings to use the built-in one",
    )
    for setting, plain in sorted(SETTINGS.items(), key=lambda kv: -len(kv[0])):
        text = re.sub(rf"\b{setting}\b", plain, text)
    return text


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


#: Where a study's data file came from (.study_inputs.json), as the pages say it.
DATA_ORIGINS: dict[str, str] = {
    "folder": "from your data folder",
    "upload": "added for this study",
    "file": "your file",
}

#: Where one of the researcher's papers came from.
PAPER_ORIGINS: dict[str, str] = {
    "folder": "from your literature folder",
    "upload": "added for this study",
    "library": "from your Library",
}

#: What kind of paper it is.
PAPER_KINDS: dict[str, str] = {"pdf": "PDF", "bib": ".bib entry", "zotero": "Zotero", "library": "Library"}

#: A reference's e2er_source tag (literature.bib, refs.bib, the dossier).
REFERENCE_SOURCES: dict[str, str] = {"researcher": "from your papers", "web": "found on the web"}

#: Where a table of data.db came from (data_sources.json), as the pages name it.
DATA_CONNECTORS: dict[str, str] = {
    "data-folder": "your data file",
    "fred": "FRED",
    "yfinance": "Yahoo Finance",
    "gmd": "Global Macro Database",
    "allium": "Allium",
    "zenodo": "Zenodo",
}


def data_origin(origin: str) -> str:
    return DATA_ORIGINS.get(origin) or _plain(origin).lower()


def paper_origin(origin: str) -> str:
    return PAPER_ORIGINS.get(origin) or _plain(origin).lower()


def paper_kind(kind: str) -> str:
    return PAPER_KINDS.get(kind) or _plain(kind)


def reference_source(tag: str) -> str:
    return REFERENCE_SOURCES.get(tag) or "found on the web"


def data_connector(name: str) -> str:
    return DATA_CONNECTORS.get(name) or _plain(name)


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
    env.filters["data_origin_label"] = data_origin
    env.filters["paper_origin_label"] = paper_origin
    env.filters["paper_kind_label"] = paper_kind
    env.filters["reference_source_label"] = reference_source
    env.filters["connector_label"] = data_connector
