"""Text generated from the source definitions: the README's data source table and a skill stub.

``scripts/gen_sources.py`` writes both: it replaces the README block between
``<!-- sources:start -->`` and ``<!-- sources:end -->`` and writes
``skills/files/data/<name>.md`` for a source that has no skill file yet (a stub
to edit, never overwritten). tests/data/contract/test_connector_kit.py fails
when the README lists other sources than the registry.
"""

from __future__ import annotations

from .base import Source

START, END = "<!-- sources:start -->", "<!-- sources:end -->"

#: Allium is not a kit source (its SQL warehouse has its own guarded tool); the table lists it after the kit's.
_ALLIUM_ROW = "| Allium | On-chain blockchain data | `ALLIUM_API_KEY` (paid query credits) |"


def readme_block(sources: list[Source]) -> str:
    """The README's data source table, between its markers."""
    rows = [f"| {s.label}{_name_note(s)} | {s.coverage} | {s.setting_cell()} |" for s in sources]
    n = len(sources) + 1
    lines = [
        START,
        f"Specialists can also draw on {_number(n)} sources:",
        "",
        "| Source | Coverage | Setting |",
        "|---|---|---|",
        *rows,
        _ALLIUM_ROW,
        END,
    ]
    return "\n".join(lines)


def _name_note(s: Source) -> str:
    """``(e2er-data name)`` after the label when the label does not say it."""
    return "" if s.name.lower() in s.label.lower().replace(" ", "") else f" (`{s.name}`)"


def _number(n: int) -> str:
    words = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve"]
    return words[n] if n < len(words) else str(n)


def replace_block(text: str, block: str) -> str:
    """``text`` with its marked block replaced (ValueError when the markers are missing)."""
    if START not in text or END not in text:
        raise ValueError(f"no {START} … {END} block")
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    return head + block + tail


def skill_stub(s: Source) -> str:
    """A skill file for a new source, from its definition: what it is, its terms, its subcommands.

    The stub is a start: add what a specialist needs to choose well (which
    series answer which questions, the source's pitfalls, a worked call).
    """
    key = (
        "No key is needed."
        if s.key is None
        else f"It needs `{s.key.env}` ({'optional' if s.key.optional else 'required'}). {s.key.how_to_get}"
    )
    lines = [
        f"# {s.label} via `e2er-data {s.name}`",
        "",
        f"{s.use} Website: {s.website}. {key}",
        "",
        "## Terms of use",
        "",
        *[f"- {p}" for p in s.plain],
        f"- Full terms: {s.terms_url}",
    ]
    if not s.redistribution:
        lines.append(
            "- A published study may not pass these data on: publishing asks the researcher to confirm the "
            "terms, and the replication package loads the data again (get_data.py) instead of shipping them."
        )
    if s.citation:
        cite = f"`{s.cite_key}`, added to the study's literature.bib on the first load" if s.cite_key else "the load"
        lines += ["", f"Cite: {s.citation} (BibTeX key {cite})."]
    lines += ["", "## Subcommands", "", "```"]
    for op in s.operations:
        args = " ".join(f"--{a.name} <{a.key}>" if a.type != "flag" else f"[--{a.name}]" for a in op.args if a.required)
        lines.append(f"e2er-data {s.name} {op.name} {args}".rstrip() + f"    # {op.help}")
    lines += ["```", ""]
    for op in s.operations:
        if not op.args:
            continue
        lines.append(f"`{op.name}` options:")
        lines.append("")
        lines += [f"- `--{a.name}`{' (required)' if a.required else ''}: {a.help}" for a in op.args]
        if op.loads:
            lines.append(
                "- `--table NAME` loads the rows into the study's data.db as the table declared in "
                "data_dictionary.json; `--save-to FILE.csv` also writes them under data/."
            )
        lines.append("")
    lines += [
        "## What e2er records",
        "",
        "Every load that returns rows is recorded in the study's `data_sources.json`: the source, its terms, "
        "the citation, the request as made"
        + (", the query sent and the SHA-256 of every file read" if s.is_kit else "")
        + ", and when it ran. A table also gets its entry in `data_dictionary.json`. A load that fails or "
        "returns no rows leaves data.db unchanged and exits non-zero; read the error and fix the request.",
        "",
    ]
    return "\n".join(lines)
