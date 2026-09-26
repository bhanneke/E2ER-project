"""``e2er submit``: send a skill, template, specialist or connector to e2er.org for review.

    e2er submit skills/codebook-development --licence MIT --version 0.1.0
    e2er submit templates/gioia.toml --kind template --licence MIT --version 0.1.0 --summary "…"
    e2er submit skills/codebook-development --improves skill:ines/codebook-development --version 0.2.0 …
    e2er submit skills/codebook-development --resubmit sub-1a2b3c4d …   (a returned submission, fixed)

A skill is a folder with SKILL.md (the Agent Skills format: front matter with
``name`` and ``description``); its name and summary come from there. Other parts
are one file. The platform runs the automatic checks and answers with each one;
the same format checks run here first, so an obvious mistake is caught before
anything is sent. Under a licence that does not allow copies (CC BY-NC, for
instance) e2er.org keeps only the address: pass ``--source`` and no content is sent.

Needs ``e2er login`` (the token's ``submit`` scope).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .core import platform_client as pc
from .core.secret_scan import find_secrets

KINDS = ("skill", "template", "agent", "connector")
SEMVER = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$")
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
MAX_CONTENT = 200_000
# Licences under which e2er.org keeps the address only, as in its licence table
# (the non-commercial ones: CC BY-NC, CC BY-NC-SA, PolyForm Noncommercial).
ADDRESS_ONLY = re.compile(r"-NC(-|$)|Noncommercial", re.I)


def front_matter(text: str) -> dict[str, str] | None:
    """The ``---`` block at the top of SKILL.md as flat key: value pairs, or None."""
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n", text, re.S)
    if not m:
        return None
    out: dict[str, str] = {}
    for line in m.group(1).splitlines():
        k, sep, v = line.partition(":")
        if sep and not line.startswith((" ", "\t")):
            out[k.strip()] = v.strip().strip("\"'")
    return out


def local_checks(kind: str, slug: str, content: str) -> list[str]:
    """Format problems the platform would return; empty when there are none."""
    problems: list[str] = []
    if kind == "skill":
        fm = front_matter(content)
        if fm is None:
            return ["SKILL.md needs front matter between --- lines with name and description."]
        if fm.get("name") != slug:
            problems.append(
                f"SKILL.md names itself {fm.get('name')!r}; its folder and identifier are {slug!r}. They must match."
            )
        desc = fm.get("description", "")
        if not 20 <= len(desc) <= 1024:
            problems.append(
                "The description in SKILL.md needs 20 to 1024 characters: what the skill does and when to use it."
            )
        body = content[content.find("---", 3) + 3 :].strip()
        if len(body) < 50:
            problems.append("SKILL.md needs instructions below the front matter.")
    elif kind == "template":
        if not re.search(r'^\s*name\s*=\s*"[^"]+"', content, re.M):
            problems.append('The template file needs a line name = "…".')
        steps = re.findall(r"\[\[steps\]\]([\s\S]*?)(?=\[\[steps\]\]|$)", content)
        if not steps:
            problems.append("The template file has no [[steps]].")
        elif any(not re.search(r'^\s*kind\s*=\s*"(strategist|gate|specialists|aggregate)"', s, re.M) for s in steps):
            problems.append('Every step needs kind = "strategist", "gate", "specialists" or "aggregate".')
    if len(content.encode("utf-8")) > MAX_CONTENT:
        problems.append(f"The content is larger than {MAX_CONTENT} bytes.")
    secrets = find_secrets({"content": content})
    if secrets:
        problems.append("The content holds something that looks like a key or token; remove it.")
    return problems


def build_request(
    path: str | None,
    *,
    kind: str | None = None,
    name: str | None = None,
    slug: str | None = None,
    version: str | None = None,
    summary: str | None = None,
    licence: str | None = None,
    source: str | None = None,
    improves: str | None = None,
    handle: str | None = None,
    discipline: str | None = None,
    role: str | None = None,
    output: str | None = None,
    direction: str | None = None,
    egress: str | None = None,
    egress_note: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """The submission body and the problems found before sending."""
    problems: list[str] = []
    content = ""
    fm: dict[str, str] = {}
    if path:
        p = Path(path).expanduser()
        if p.is_dir():
            skill_md = p / "SKILL.md"
            if not skill_md.is_file():
                return {}, [f"{p} has no SKILL.md; a skill is a folder with SKILL.md."]
            kind = kind or "skill"
            content = skill_md.read_text(encoding="utf-8")
            fm = front_matter(content) or {}
            slug = slug or p.name  # Agent Skills: name must equal the folder name
        elif p.is_file():
            content = p.read_text(encoding="utf-8")
            if p.name == "SKILL.md":
                kind = kind or "skill"
                fm = front_matter(content) or {}
                slug = slug or p.parent.name
            elif p.suffix == ".toml":
                kind = kind or "template"
                m = re.search(r'^\s*name\s*=\s*"([^"]+)"', content, re.M)
                slug = slug or (m.group(1) if m else p.stem)
            slug = slug or p.stem
        else:
            return {}, [f"No such file or folder: {p}"]
    kind = kind or ""
    if kind not in KINDS:
        problems.append("Say what this is: --kind skill, template, agent (a specialist) or connector.")
    name = name or (fm.get("name", "").replace("-", " ").capitalize() if fm.get("name") else None) or (slug or "")
    summary = summary or fm.get("description") or ""
    slug = (slug or "").lower()
    if not SLUG.match(slug):
        problems.append(
            "The identifier (--slug) takes lower-case letters, digits and hyphens, e.g. codebook-development."
        )
    if not version or not SEMVER.match(version):
        problems.append("Give a version like 0.1.0 (--version).")
    if not 20 <= len(summary) <= 500:
        problems.append("Give a summary of 20 to 500 characters (--summary): what the part does and for whom.")
    if not licence:
        problems.append("Choose a licence (--licence), for instance MIT or CC-BY-4.0.")
    address_only = bool(licence and ADDRESS_ONLY.search(licence))
    if address_only:
        if not source or not source.startswith("https://"):
            problems.append(
                f"Under {licence} e2er.org keeps no copy: give the https address of the published part (--source)."
            )
        content = ""
    elif not content:
        problems.append("Give the file or folder to submit.")
    elif kind in KINDS:
        problems += local_checks(kind, slug, content)
    fields: dict[str, str] = {}
    if discipline:
        fields["discipline"] = discipline
    if kind == "agent":
        fields.update({k: v for k, v in (("role", role), ("output", output)) if v})
        if not role or not output:
            problems.append(
                "A specialist names its role (--role, a sentence) and the file it writes (--output, e.g. codebook.md)."
            )
    if kind == "connector":
        fields.update(
            {k: v for k, v in (("direction", direction), ("egress", egress), ("egressNote", egress_note)) if v}
        )
        if not (direction and egress and egress_note):
            problems.append(
                "A connector states --direction (in, out, both), --egress (what leaves the machine) and --egress-note."
            )
    body: dict[str, Any] = {
        "kind": kind,
        "name": name,
        "slug": slug,
        "version": version,
        "summary": summary,
        "licence": licence,
    }
    if content:
        body["content"] = content
    if address_only and source:
        body["content_url"] = source
    if fields:
        body["fields"] = fields
    if improves:
        body["target"] = improves
    if handle:
        body["handle"] = handle
    return body, problems


def _print_checks(checks: list[dict[str, Any]]) -> None:
    for c in checks:
        print(f"  {'✓' if c.get('ok') else '✗'} {c.get('check')}: {c.get('detail')}")


def submit(
    path: str | None,
    *,
    url: str | None = None,
    resubmit: str | None = None,
    dry_run: bool = False,
    **fields: Any,
) -> int:
    body, problems = build_request(path, **fields)
    if problems:
        print("Not sent; fix these first:")
        for p in problems:
            print(f"  ✗ {p}")
        return 1
    base = pc.base_url(url)
    method, where = ("PUT", f"/api/v1/submissions/{resubmit}") if resubmit else ("POST", "/api/v1/submissions")
    if dry_run:
        shown = dict(body)
        if "content" in shown:
            shown["content"] = f"<{len(body['content'].encode('utf-8'))} bytes>"
        print(f"{method} {base}{where}\n{json.dumps(shown, indent=2, ensure_ascii=False)}")
        print("Dry run: nothing sent.")
        return 0
    token = pc.load_token(base)
    if not token:
        print(f"Not signed in to {base}. Run `e2er login`.")
        return 1
    code, answer = pc.request(base, method, where, token=token, body=body)
    if code not in (200, 201):
        print(f"error: {answer.get('error', code)}")
        return 1
    checks = answer.get("conformance") or []
    if answer.get("state") == "returned":
        print(f"✗ {answer['id']} was returned by the automatic checks:")
        _print_checks(checks)
        print(f"Fix the items marked ✗ and send it again: e2er submit … --resubmit {answer['id']}")
        return 1
    print(f"✓ {answer['id']} passed the automatic checks and waits for an evaluation.")
    _print_checks(checks)
    if answer.get("url"):
        print(f"  Follow it at {answer['url']}")
    return 0
