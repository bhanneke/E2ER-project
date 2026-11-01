"""Anonymising a study for double-blind review (``e2er publish --blind``, ``e2er pack --blind``).

A study published for double-blind review must not name its author anywhere: not in
the paper, the code, the logs, the dossier or the request that publishes it.
``e2er publish --blind`` therefore works on a copy of the exported folder and, before
anything is sent:

1. **collects what identifies the author** (:func:`collect`): the e2er.org account's
   name, e-mail address, handles, GitHub login, ORCID iD and affiliations (``GET
   /api/v1/me``), the git author names and e-mail addresses of this computer and of the
   repository the study sits in, the user name and host name of this computer, and
   whatever the author adds (``--blind-identifier``, ``E2ER_BLIND_IDENTIFIERS``,
   ``E2ER_AFFILIATION``);
2. **anonymises the copy** (:func:`anonymise`), with the same machinery as ``e2er
   redact``: every change is recorded in provenance.json as an amendment of kind
   ``"anonymised"`` that names the rules applied and how many replacements of each kind it
   made (since 0.19.0 not where they sit: offsets and a fingerprint confirm a guess), never
   the text that was taken out. Earlier amendments of ``e2er redact`` lose their offsets,
   sizes and the fingerprint before (:func:`_blind_earlier_amendments`). The rules: the paper's author, affiliation and
   acknowledgement blocks become "Anonymous author(s)"; home-directory paths
   (``/Users/<name>``, ``/home/<name>``, ``C:\\Users\\<name>``) become ``~``; every
   identifier becomes ``[anonymised]``;
3. **checks for leaks** (:func:`leak_check`): every text file, every PDF (its text from
   pdftotext and its raw bytes), every other file's bytes (zip members and gzip files
   opened), and any extra text (the dossier, the request body) is searched for every
   identifier, case-insensitively, also URL-encoded, HTML- and JSON-escaped, with LaTeX
   accents, folded to ASCII, written in reverse ("Quarry, Imogen"), with initials, split
   over lines, and for e-mail addresses with "at" and "dot". Anything left is listed by
   file and line, and publishing is refused.

Names in a citation are not anonymised: a paper may cite its author's earlier work in
the third person. A name in a bibliography file, in the references of a PDF, in a
citation key or next to a year ("Quarry (2024)") counts as a citation; such places, the
bibliography entries that name the author and phrases such as "our previous work"
(:func:`self_citations`) are listed, and the author confirms them after reading
(``--blind-ack-self-citations``).

The fingerprint a file had before it was anonymised could confirm a guess of the text
taken out (put the guessed name back, hash, compare). So an anonymised file's amendment
records no ``sha256_before``, and :func:`withhold` takes the old fingerprints out of the
dossier. A pre-registered plan file is the exception: its frozen fingerprint is in
design/preregistration.lock.json, so publish names it as a file that could confirm a
guess.
"""

from __future__ import annotations

import getpass
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import socket
import subprocess
import unicodedata
import zipfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, quote_plus

KIND = "anonymised"
REASON = "identifying details removed for double-blind review"
MARK = "[anonymised]"
AUTHOR_BLOCK = "Anonymous author(s)"
ACK_TEXT = "Removed for double-blind review."
#: What the acknowledgements say once they are taken out.
#: e2er's own public repositories: every dossier names them for the parts it pins, so they are no trace of the author.
INFRASTRUCTURE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:github\.com|raw\.githubusercontent\.com|codeload\.github\.com)/bhanneke/"
    r"(?:E2ER-project|e2er-site|RISE)(?![A-Za-z0-9_-])",
    re.I,
)
#: User and host names that name nobody.
GENERIC_USERS = frozenset(
    {
        "root",
        "user",
        "admin",
        "administrator",
        "runner",
        "ubuntu",
        "ec2-user",
        "vagrant",
        "docker",
        "jovyan",
        "guest",
        "test",
        "tester",
        "me",
        "codespace",
        "codespaces",
        "vscode",
        "node",
        "app",
        "worker",
        "build",
        "builder",
        "nobody",
        "default",
        "shared",
        "public",
    }
)
GENERIC_HOSTS = re.compile(
    r"^(?:localhost|local|mac|macbook(?:-pro|-air)?|imac|mac-?mini|mac-?studio|mac-?pro|ubuntu|debian|fedora|"
    r"raspberrypi|desktop|laptop|pc|computer|workstation|runner|host|server|[0-9a-f]{12}|fv-az[0-9a-z-]+)$",
    re.I,
)
#: Local part of an e-mail address that names nobody (``info@…``).
GENERIC_MAIL = frozenset({"info", "admin", "contact", "mail", "office", "research", "hello", "noreply", "no-reply"})
#: Records publish keeps on this computer only; never part of the study, never searched.
_LOCAL = (".e2er/",)

#: Kinds of identifier, as the refusals name them.
LABELS = {
    "name": "your name",
    "email": "your e-mail address",
    "email-user": "the user part of your e-mail address",
    "handle": "one of your e2er.org handles",
    "github": "your GitHub login",
    "orcid": "your ORCID iD",
    "affiliation": "your affiliation",
    "user": "this computer's user name",
    "host": "this computer's name",
    "extra": "an identifier you named (--blind-identifier)",
    "home": "a home-directory path",
}
#: Kinds whose value may stand in a citation of the author's own work ("Quarry (2024)").
NAME_LIKE = frozenset({"name", "extra"})


class AnonymiseError(Exception):
    """The folder cannot be anonymised as it is; the message says why. Nothing was sent."""


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── what identifies the author ───────────────────────────────────────────────


@dataclass(frozen=True)
class Identifier:
    kind: str
    value: str
    source: str

    @property
    def label(self) -> str:
        return f"{LABELS.get(self.kind, self.kind)} ({self.source})"


def _git(args: list[str], cwd: Path | None = None) -> list[str]:
    exe = shutil.which("git")
    if exe is None:
        return []
    try:
        proc = subprocess.run(
            [exe, *args],
            cwd=cwd,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            env={**os.environ, "GIT_PAGER": "cat"},
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    return [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]


def _split_list(text: str | None) -> list[str]:
    return [x.strip() for x in re.split(r"[;\n]", text or "") if x.strip()]


def collect(
    me: dict[str, Any] | None,
    *,
    folders: Iterable[Path] = (),
    extra: Iterable[str] = (),
    environ: dict[str, str] | None = None,
    local: bool = True,
) -> list[Identifier]:
    """Everything that identifies the author: the platform account (``me``, GET /api/v1/me), this computer's git
    identity and user and host name (``local``), the git authors of the repositories ``folders`` sit in, and the
    identifiers the author adds (``extra``; E2ER_BLIND_IDENTIFIERS and E2ER_AFFILIATION, ``;``-separated)."""
    env = dict(os.environ if environ is None else environ)
    out: list[Identifier] = []

    def add(kind: str, value: Any, source: str) -> None:
        if not isinstance(value, str):
            return
        v = re.sub(r"\s+", " ", value).strip().strip("@")
        if kind == "github" or kind == "handle":
            v = v.lower()
        if kind == "orcid":
            v = v.removeprefix("https://orcid.org/").removeprefix("http://orcid.org/").strip()
        if len(v) < 3:
            return
        if kind in ("user", "handle", "github") and v.lower() in GENERIC_USERS:
            return
        if kind == "host" and GENERIC_HOSTS.match(v.split(".")[0]):
            return
        if kind == "name" and len(v) < 5 and " " not in v:
            return
        out.append(Identifier(kind, v, source))
        if kind == "email" and "@" in v:
            local_part = v.split("@", 1)[0]
            if len(local_part) >= 4 and local_part.lower() not in GENERIC_MAIL:
                out.append(Identifier("email-user", local_part, source))

    if me:
        add("name", me.get("name"), "e2er.org account")
        add("email", me.get("email"), "e2er.org account")
        for h in me.get("handles") or []:
            add("handle", h, "e2er.org account")
        profile: dict[str, Any] = me["profile"] if isinstance(me.get("profile"), dict) else {}
        add("name", profile.get("name"), "e2er.org profile")
        add("github", profile.get("github"), "e2er.org profile")
        add("orcid", profile.get("orcid"), "e2er.org profile")
        for a in profile.get("affiliations") or []:
            add("affiliation", a, "e2er.org profile")
    if local:
        for v in _git(["config", "--global", "--get-all", "user.name"]):
            add("name", v, "git config")
        for v in _git(["config", "--global", "--get-all", "user.email"]):
            add("email", v, "git config")
        try:
            add("user", getpass.getuser(), "this computer")
        except Exception:  # noqa: BLE001 - no user name to be found
            pass
        home = Path(env.get("HOME") or Path.home())
        if home.parent.as_posix().lower() in ("/users", "/home") or home.parent.name.lower() == "users":
            add("user", home.name, "this computer")
        host = socket.gethostname()
        add("host", host, "this computer")
        add("host", host.split(".")[0], "this computer")
    for folder in folders:
        top = _git(["rev-parse", "--show-toplevel"], cwd=Path(folder))
        if not top:
            continue
        for v in _git(["config", "--get-all", "user.name"], cwd=Path(top[0])):
            add("name", v, "git config of the study's repository")
        for v in _git(["config", "--get-all", "user.email"], cwd=Path(top[0])):
            add("email", v, "git config of the study's repository")
        for line in _git(["log", "-n", "500", "--format=%an%x09%ae%x09%cn%x09%ce"], cwd=Path(top[0])):
            parts = line.split("\t")
            for n in (0, 2):
                if n < len(parts):
                    add("name", parts[n], "git history of the study's repository")
            for n in (1, 3):
                if n < len(parts) and not parts[n].endswith("users.noreply.github.com"):
                    add("email", parts[n], "git history of the study's repository")
    for v in _split_list(env.get("E2ER_AFFILIATION")):
        add("affiliation", v, "E2ER_AFFILIATION")
    for v in _split_list(env.get("E2ER_BLIND_IDENTIFIERS")):
        add("extra", v, "E2ER_BLIND_IDENTIFIERS")
    for v in extra:
        add("extra", v, "--blind-identifier")
    seen: set[tuple[str, str]] = set()
    unique = []
    for i in out:
        key = (i.kind, i.value.lower())
        if key not in seen:
            seen.add(key)
            unique.append(i)
    # A handle or user name that is also a word of the author's name reads like a name (cite keys, "Quarry (2024)").
    words = {w.lower() for i in unique if i.kind == "name" for w in i.value.split()}
    return [
        Identifier("name", i.value, i.source) if i.kind in ("user", "handle") and i.value.lower() in words else i
        for i in unique
    ]


# ── the patterns: every way an identifier can be written ─────────────────────

_LATEX_ACCENT = {
    "\u0308": '"',
    "\u0301": "'",
    "\u0300": "`",
    "\u0302": "^",
    "\u0303": "~",
    "\u0327": "c",
    "\u030a": "r",
    "\u030c": "v",
    "\u0304": "=",
    "\u0307": ".",
    "\u0306": "u",
    "\u030b": "H",
}
_SPECIAL = {
    "ß": ["ss", r"\ss{}", r"{\ss}", r"\ss"],
    "ø": ["o", r"\o{}", r"{\o}", r"\o"],
    "Ø": ["O", r"\O{}", r"{\O}", r"\O"],
    "æ": ["ae", r"\ae{}", r"{\ae}", r"\ae"],
    "Æ": ["AE", r"\AE{}", r"{\AE}"],
    "œ": ["oe", r"\oe{}", r"{\oe}"],
    "ł": ["l", r"\l{}", r"{\l}"],
    "Ł": ["L", r"\L{}", r"{\L}"],
    "đ": ["d", r"\dj{}"],
    "ı": ["i", r"\i{}"],
}
_HTML_NAMED = {
    "\u0308": "uml",
    "\u0301": "acute",
    "\u0300": "grave",
    "\u0302": "circ",
    "\u0303": "tilde",
    "\u0327": "cedil",
    "\u030a": "ring",
}


def _char_alternatives(ch: str) -> list[str]:
    """Every way one letter can be written in a text file (regex sources)."""
    if ch.isascii():
        return [re.escape(ch)]
    alts = {re.escape(ch)}
    code = ord(ch)
    alts.add(re.escape(f"&#{code};"))
    alts.add(f"&#x0*{code:x};")
    alts.add(re.escape(f"\\u{code:04x}"))
    alts.add(re.escape(f"\\u{code:04X}"))
    alts.add("".join(f"%{b:02x}" for b in ch.encode("utf-8")))
    nfd = unicodedata.normalize("NFD", ch)
    if ch in _SPECIAL:
        alts.update(re.escape(x) for x in _SPECIAL[ch])
    elif len(nfd) >= 2 and nfd[0].isascii():
        base, marks = nfd[0], nfd[1:]
        alts.add(re.escape(nfd))  # decomposed form
        alts.add(re.escape(base))  # folded to ASCII
        if marks == "\u0308" and base.lower() in "aou":
            alts.add(re.escape(base + "e"))  # ö → oe
        if marks in _HTML_NAMED:
            alts.add(re.escape(f"&{base}{_HTML_NAMED[marks]};"))
        cmd = _LATEX_ACCENT.get(marks[0])
        if cmd and len(marks) == 1:
            sep = " " if cmd.isalpha() else ""
            for form in (
                f"\\{cmd}{sep}{base}",
                f"\\{cmd}{{{base}}}",
                f"{{\\{cmd}{sep}{base}}}",
                f"{{\\{cmd}{{{base}}}}}",
            ):
                alts.add(re.escape(form))
    return sorted(alts, key=len, reverse=True)


def _word(word: str) -> str:
    return "".join(f"(?:{'|'.join(_char_alternatives(c))})" if not c.isascii() else re.escape(c) for c in word)


#: Between the words of a name: spaces and line breaks, TeX's ~ and \, and their URL forms.
_SEP = r"(?:[\s~]|\\[ ,]|%20|\+|&nbsp;|\\u00a0)+"
_LETTER_BEFORE = r"(?<![^\W\d_])"
_LETTER_AFTER = r"(?![^\W\d_])"
_ALNUM_BEFORE = r"(?<![A-Za-z0-9])"
_ALNUM_AFTER = r"(?![A-Za-z0-9])"


#: Between the words of a name in a file name, an identifier or CamelCase: "imogen_quarry", "imogen.quarry",
#: "imogen-quarry", "ImogenQuarry" (security review 2026-10-23: all four were missed).
_NAME_JOIN = r"(?:[\s~]|\\[ ,]|%20|\+|&nbsp;|\\u00a0|[_.\-])*"


def _name_sources(value: str) -> list[str]:
    words = [w for w in re.split(r"[\s~]+", value) if w]
    if len(words) == 1:
        return [_LETTER_BEFORE + _word(words[0]) + _LETTER_AFTER]
    fwd = _NAME_JOIN.join(_word(w) for w in words)
    last, first = words[-1], words[:-1]
    out = [fwd, _word(last) + r"\s*,\s*" + _SEP.join(_word(w) for w in first)]
    # Hyphenated over a line break: "Quar-\nry".
    if len(last) >= 6:
        cuts = [_word(last[:i]) + r"-\s*\n\s*" + _word(last[i:]) for i in range(2, len(last) - 1)]
        out.append(_SEP.join(_word(w) for w in first) + _SEP + "(?:" + "|".join(cuts) + ")")
    if len(last) >= 4:
        initials = _SEP.join(_word(w[0]) + r"\.?" for w in first)
        out.append(initials + _SEP + _word(last))
        out.append(_word(last) + r"\s*,\s*" + initials)
    return [_LETTER_BEFORE + "(?:" + s + ")" + _LETTER_AFTER for s in out]


_AT = r"(?:@|%40|&#64;|&#x40;|\\u0040|\s*[\[\(\{<]\s*at\s*[\]\)\}>]\s*|\s+at\s+)"
_DOT = r"(?:\.|%2e|&#46;|\s*[\[\(\{<]\s*dot\s*[\]\)\}>]\s*|\s+dot\s+)"


def _email_sources(value: str) -> list[str]:
    local, _, domain = value.partition("@")
    lp = re.escape(local).replace(r"\.", _DOT).replace(r"\+", r"(?:\+|%2b)")
    dom = _DOT.join(re.escape(p) for p in domain.split("."))
    return [
        _ALNUM_BEFORE + lp + r"\s*" + _AT + r"\s*" + dom + _ALNUM_AFTER,
        _ALNUM_BEFORE + re.escape(quote(value, safe="")) + _ALNUM_AFTER,
    ]


def _orcid_sources(value: str) -> list[str]:
    groups = re.findall(r"[\dXx]{4}", value.replace("-", ""))
    if len(groups) != 4:
        return [re.escape(value)]
    sep = r"(?:\s*(?:-|‐|–|%2d)\s*|\s+)?"
    return [r"(?<![\d])" + sep.join(re.escape(g).replace("X", "[Xx]") for g in groups) + r"(?![\dXx])"]


def _token_sources(value: str) -> list[str]:
    """A login, handle, user or host name: the whole token, not part of a longer one."""
    alts = {re.escape(value), re.escape(quote(value, safe=""))}
    return [_ALNUM_BEFORE + "(?:" + "|".join(sorted(alts, key=len, reverse=True)) + ")" + _ALNUM_AFTER]


def _phrase_sources(value: str) -> list[str]:
    words = [w for w in re.split(r"\s+", value) if w]
    alts = [_SEP.join(_word(w) for w in words), re.escape(quote_plus(value)), re.escape(quote(value, safe=""))]
    return [_LETTER_BEFORE + "(?:" + "|".join(alts) + ")" + _LETTER_AFTER]


def sources(i: Identifier) -> list[str]:
    """The regex sources that find ``i`` in any of the forms it can be written in."""
    if i.kind in ("name",):
        return _name_sources(i.value)
    if i.kind == "email":
        return _email_sources(i.value)
    if i.kind == "orcid":
        return _orcid_sources(i.value)
    if i.kind in ("affiliation",) or (i.kind == "extra" and " " in i.value):
        return _phrase_sources(i.value)
    if i.kind == "extra":
        return (
            [_LETTER_BEFORE + _word(i.value) + _LETTER_AFTER]
            if i.value.replace("-", "").isalpha()
            else _token_sources(i.value)
        )
    return _token_sources(i.value)


#: Home-directory paths of anyone: the user name is the part that identifies.
HOME_PATH = re.compile(
    r"(?<![\w.~-])(?:/Users|/home)/(?!Shared(?:/|$|\b))[^/\s\"'\\<>:;,)\]}]+"
    r"|(?<![\w])[A-Za-z]:(?:\\\\|\\|/)Users(?:\\\\|\\|/)(?!Public\b|Default\b|All Users\b)[^\\/\s\"'<>:;,)\]}]+",
    re.I,
)


@dataclass
class Patterns:
    """The compiled patterns of a list of identifiers."""

    identifiers: list[Identifier]
    compiled: list[tuple[Identifier, re.Pattern[str]]] = field(default_factory=list)

    def __post_init__(self) -> None:
        for i in self.identifiers:
            try:
                self.compiled.append((i, re.compile("|".join(f"(?:{s})" for s in sources(i)), re.I)))
            except re.error:
                self.compiled.append((i, re.compile(re.escape(i.value), re.I)))

    def find(self, text: str) -> list[tuple[int, int, Identifier]]:
        """Every place an identifier or a home path sits in ``text``: (start, end, identifier)."""
        masked = INFRASTRUCTURE.sub(lambda m: "\x00" * len(m.group(0)), text)
        hits: list[tuple[int, int, Identifier]] = []
        for i, rx in self.compiled:
            hits += [(m.start(), m.end(), i) for m in rx.finditer(masked) if m.end() > m.start()]
        hits += [(m.start(), m.end(), Identifier("home", m.group(0), "a path")) for m in HOME_PATH.finditer(masked)]
        return sorted(hits, key=lambda h: (h[0], -h[1]))


# ── citations: the author's own work, named in the third person ──────────────

_BIB_FILE = (".bib", ".bbl", ".bst")
_CITE_BEFORE = re.compile(r"\\(?:[a-zA-Z]*cite[a-zA-Z]*\*?|nocite|bibitem)(?:\[[^\]]*\])*\{[^}]*$")
_YEAR_AFTER = re.compile(r"^(?:[^\n]{0,8}?\s*(?:et\s*al\.?)?\s*(?:,|\(|\[|\s)\s*(?:19|20)\d\d[a-z]?\b)")
_KEY_AFTER = re.compile(r"^[_:-]?(?:19|20)?\d\d[a-z]?\b")
_REFERENCES_HEAD = re.compile(
    r"^\s*(?:\d+\.?\s*)?(?:References|Bibliography|Works Cited|Literature Cited|Literatur)\s*$", re.I | re.M
)


def references_start(text: str) -> int | None:
    """Where the references of a paper's text (from its PDF) begin: after the last such heading."""
    last = None
    for m in _REFERENCES_HEAD.finditer(text):
        last = m.end()
    return last


def is_citation(rel: str, text: str, start: int, end: int, i: Identifier, refs_from: int | None = None) -> bool:
    """Does the name at ``text[start:end]`` stand in a citation (only names do): in a bibliography file, after the
    references heading of a PDF's text, in a citation command or key, or right before a year ("Quarry (2024)")?"""
    if i.kind not in NAME_LIKE:
        return False
    if rel.lower().endswith(_BIB_FILE):
        return True
    if refs_from is not None and start >= refs_from:
        return True
    line_start = text.rfind("\n", 0, start) + 1
    if _CITE_BEFORE.search(text[line_start:start]):
        return True
    after = text[end : end + 80]
    return bool(_KEY_AFTER.match(after) or _YEAR_AFTER.match(after))


_SELF_PHRASES = re.compile(
    r"\b(?:our|my)\s+(?:own\s+)?(?:previous|prior|earlier|recent|related|companion|forthcoming|other)\s+"
    r"(?:work|works|paper|papers|study|studies|article|articles|research|findings|analysis|analyses|book)\b"
    r"|\bwe\s+(?:have\s+)?(?:previously|earlier|already|elsewhere)\s+(?:show|showed|shown|find|found|propose|proposed|"
    r"argue|argued|document|documented|demonstrate|demonstrated|report|reported|establish|established)\b"
    r"|\b(?:as\s+)?we\s+(?:showed|have\s+shown|demonstrated|found|argued|proposed|documented|reported)\s+(?:in|elsewhere)\b"
    r"|\bin\s+(?:our|my)\s+(?:previous|prior|earlier|own|recent|companion)\b"
    r"|\b(?:see|cf\.?)\s+(?:our|my)\b"
    r"|\b(?:our|my)\s+(?:own\s+)?(?:\\cite|\\citet|\\citep)",
    re.I,
)
_BIB_ENTRY = re.compile(r"@(\w+)\s*\{\s*([^,\s]+)\s*,", re.I)
_TEX_CITE = re.compile(r"\\[a-zA-Z]*cite[a-zA-Z]*\*?(?:\[[^\]]*\])*\{([^}]*)\}")


@dataclass
class Finding:
    """One place: the file (or the request, the dossier), the line, and what is there (never the identifier)."""

    where: str
    line: int
    what: str

    def __str__(self) -> str:
        return f"{self.where}:{self.line}: {self.what}" if self.line else f"{self.where}: {self.what}"


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _field(entry: str, name: str) -> str:
    m = re.search(rf"\b{name}\s*=\s*", entry, re.I)
    if not m:
        return ""
    rest = entry[m.end() :]
    if rest.startswith("{"):
        depth = 0
        for k, c in enumerate(rest):
            depth += c == "{"
            depth -= c == "}"
            if depth == 0:
                return rest[1:k]
        return rest[1:]
    if rest.startswith('"'):
        end = rest.find('"', 1)
        return rest[1:end] if end > 0 else rest[1:]
    return rest.split(",", 1)[0]


def _surnames(identifiers: Iterable[Identifier]) -> list[str]:
    out = []
    for i in identifiers:
        if i.kind in ("name", "extra") and i.value.strip():
            last = re.split(r"[\s~]+", i.value.strip())[-1]
            if len(last) >= 3:
                out.append(last)
    return sorted(set(out), key=str.lower)


def self_citations(folder: Path, identifiers: list[Identifier]) -> list[Finding]:
    """What may cite the author's own work, for the author to read before publishing blind: bibliography entries
    whose authors or editors carry the author's surname, citation keys that carry it, and phrases such as "our
    previous work" or "we showed in" in the paper's text."""
    folder = Path(folder)
    surnames = _surnames(identifiers)
    sur_rx = [re.compile(_LETTER_BEFORE + _word(s) + _LETTER_AFTER, re.I) for s in surnames]
    key_rx = [re.compile(re.escape(_fold(s).lower())) for s in surnames]
    out: list[Finding] = []
    for rel in _files(folder):
        path = folder / rel
        low = rel.lower()
        if not low.endswith((".bib", ".tex", ".md", ".txt", ".bbl")):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if low.endswith(".bib"):
            starts = [m for m in _BIB_ENTRY.finditer(text)]
            for k, m in enumerate(starts):
                body = text[m.start() : starts[k + 1].start() if k + 1 < len(starts) else len(text)]
                people = _field(body, "author") + " and " + _field(body, "editor")
                if any(rx.search(people) for rx in sur_rx):
                    out.append(
                        Finding(
                            rel,
                            _line_of(text, m.start()),
                            f"@{m.group(1)}{{{m.group(2)}}} is by an author with your surname",
                        )
                    )
            continue
        if low.endswith(".tex"):
            for m in _TEX_CITE.finditer(text):
                for key in m.group(1).split(","):
                    cite = key.strip()
                    if cite and any(rx.search(_fold(cite).lower()) for rx in key_rx):
                        out.append(Finding(rel, _line_of(text, m.start()), f"cites {cite}, a key with your surname"))
        if low.endswith((".tex", ".md", ".txt")) and (low.startswith("paper/") or low.endswith(".tex")):
            for m in _SELF_PHRASES.finditer(text):
                out.append(
                    Finding(rel, _line_of(text, m.start()), f'"{" ".join(m.group(0).split())}" may name your own work')
                )
    return out


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


# ── the LaTeX blocks that name the author ────────────────────────────────────

_AUTHOR_CMDS = (
    "author",
    "affil",
    "affiliation",
    "institute",
    "institution",
    "address",
    "email",
    "orcid",
    "thanks",
    "corref",
    "authornote",
    "authorinfo",
    "IEEEauthorblockN",
    "IEEEauthorblockA",
)
_CMD = re.compile(r"\\(" + "|".join(_AUTHOR_CMDS) + r")\*?(?:\[[^\]]*\])?\s*\{")
_ACK_SECTION = re.compile(
    r"\\(?:section|subsection|paragraph|chapter)\*?\s*\{\s*"
    r"(?:Acknowledge?ments?|Acknowledgements?|Funding|Funding and acknowledgements?)\s*\}",
    re.I,
)
_ACK_ENV = re.compile(r"\\begin\{(acknowledge?ments?|acks)\}", re.I)
_ACK_CMD = re.compile(r"\\(?:acknowledge?ments?|acks|ack)\s*\{", re.I)
_SECTION_END = re.compile(
    r"\\(?:section|chapter|appendix|bibliography|printbibliography|end\{document\}|begin\{thebibliography\})", re.I
)


def _balanced(text: str, open_at: int) -> int | None:
    """The index just after the brace that closes the one at ``open_at``, or None."""
    depth = 0
    k = open_at
    while k < len(text):
        c = text[k]
        if c == "\\":
            k += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return k + 1
        k += 1
    return None


def latex_blocks(text: str) -> list[tuple[int, int, str, str]]:
    """The author, affiliation and acknowledgement blocks of a LaTeX text: (start, end, replacement, rule)."""
    out: list[tuple[int, int, str, str]] = []
    k = 0
    while True:
        m = _CMD.search(text, k)
        if not m:
            break
        end = _balanced(text, m.end() - 1)
        if end is None:
            break
        cmd = m.group(1)
        # Never an empty replacement: each one is recorded where it sits, so verify sees every change.
        if cmd == "author":
            out.append((m.start(), end, f"\\author{{{AUTHOR_BLOCK}}}", "author block"))
        elif cmd == "thanks":
            out.append((m.start(), end, f"\\thanks{{{MARK}}}", "author block"))
        else:
            out.append((m.start(), end, f"\\{cmd}{{{MARK}}}", "affiliation"))
        k = end
    for m in _ACK_SECTION.finditer(text):
        stop = _SECTION_END.search(text, m.end())
        end = stop.start() if stop else len(text)
        out.append((m.end(), end, f"\n{ACK_TEXT}\n\n", "acknowledgements"))
    for m in _ACK_ENV.finditer(text):
        close = re.compile(r"\\end\{" + re.escape(m.group(1)) + r"\}", re.I).search(text, m.end())
        if close:
            out.append((m.end(), close.start(), f"\n{ACK_TEXT}\n", "acknowledgements"))
    for m in _ACK_CMD.finditer(text):
        end = _balanced(text, m.end() - 1)
        if end is not None:
            out.append((m.end(), end - 1, ACK_TEXT, "acknowledgements"))
    # Inner blocks (a \thanks inside \author) go with the outer one.
    out.sort(key=lambda b: (b[0], -b[1]))
    kept: list[tuple[int, int, str, str]] = []
    for b in out:
        if kept and b[0] < kept[-1][1]:
            continue
        kept.append(b)
    return kept


# ── the folder ───────────────────────────────────────────────────────────────


def _files(folder: Path) -> list[str]:
    return sorted(
        p.relative_to(folder).as_posix()
        for p in Path(folder).rglob("*")
        if p.is_file() and not p.is_symlink() and not p.relative_to(folder).as_posix().startswith(_LOCAL)
    )


def _is_text(data: bytes) -> bool:
    if b"\x00" in data[:8192]:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


PdfText = Callable[[Path], str | None]


def pdf_text(path: Path) -> str | None:
    """A PDF's text (pdftotext), or None when pdftotext is not installed or cannot read it."""
    exe = shutil.which("pdftotext")
    if exe is None:
        return None
    try:
        proc = subprocess.run([exe, "-q", "-enc", "UTF-8", str(path), "-"], capture_output=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout.decode("utf-8", errors="replace") if proc.returncode == 0 else None


def prereg_paths(folder: Path) -> set[str]:
    """The pre-registered files (the pre-registration and its plan files): their frozen fingerprints are kept."""
    try:
        lock = json.loads((Path(folder) / "design" / "preregistration.lock.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    if not isinstance(lock, dict):
        return set()
    names = [str(lock.get("file") or "preregistration.md"), *map(str, (lock.get("plan_files") or {}).keys())]
    return {f"design/{n}" for n in names}


@dataclass
class Result:
    """What anonymising changed."""

    #: rel → the rules that changed it
    changed: dict[str, list[str]] = field(default_factory=dict)
    #: Fingerprints the changed files had: withheld from the dossier (:func:`withhold`), never stored.
    withheld: set[str] = field(default_factory=set)
    #: Files not listed in provenance.json, taken out of the copy (records of an earlier publish).
    removed: list[str] = field(default_factory=list)
    #: Pre-registered files that were anonymised: their frozen fingerprint stays in the lock file.
    prereg: list[str] = field(default_factory=list)
    #: Binary files that hold an identifier (they cannot be changed in place).
    binary: list[str] = field(default_factory=list)


def _edit(text: str, rel: str, pats: Patterns, latex: bool) -> tuple[str, list[str], dict[str, list[int]]]:
    """The anonymised text, the rules applied and where each replacement sits (byte offsets in the new text)."""
    spans: list[tuple[int, int, str, str]] = []
    if latex:
        spans += latex_blocks(text)
    taken = [(s, e) for s, e, _r, _n in spans]
    refs = None
    for s, e, i in pats.find(text):
        if any(a <= s < b or a < e <= b for a, b in taken):
            continue
        if is_citation(rel, text, s, e, i, refs):
            continue
        if i.kind == "home":
            spans.append((s, e, "~", "home directory"))
        else:
            spans.append((s, e, MARK, i.kind))
        taken.append((s, e))
    spans.sort(key=lambda b: (b[0], -b[1]))
    merged: list[tuple[int, int, str, str]] = []
    for b in spans:
        if merged and b[0] < merged[-1][1]:
            continue
        merged.append(b)
    out: list[str] = []
    offsets: dict[str, list[int]] = {}
    rules: set[str] = set()
    at = 0
    size = 0
    for s, e, rep, rule in merged:
        piece = text[at:s]
        out.append(piece)
        size += len(piece.encode("utf-8"))
        if not rep:
            raise AnonymiseError(f"{rel}: an empty replacement for the {rule} would not be recorded")
        offsets.setdefault(rep, []).append(size)
        out.append(rep)
        size += len(rep.encode("utf-8"))
        rules.add(rule)
        at = e
    out.append(text[at:])
    return "".join(out), sorted(rules), offsets


def anonymise(folder: Path, identifiers: list[Identifier], *, at: str | None = None) -> Result:
    """Anonymise the exported study ``folder`` (a copy: it is changed in place) and record each change.

    Files provenance.json does not list (an earlier publish's e2er.json, .e2er/ records) are taken out. Every
    listed text file gets the rules; a binary file that holds an identifier cannot be changed in place, so it is
    named in ``Result.binary`` (the caller refuses). PDFs are left to the leak check: e2er publish builds
    paper/paper.pdf again from the anonymised paper.tex.
    """
    from .export.provenance import dump

    folder = Path(folder)
    prov_path = folder / "provenance.json"
    try:
        prov = json.loads(prov_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise AnonymiseError(f"provenance.json cannot be read: {e}") from e
    listed: dict[str, Any] = prov.get("files") or {}
    links = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_symlink())
    if links:
        # A link's target is outside the copy: anonymising "the copy" wrote through it into the original file.
        raise AnonymiseError(
            "the folder holds symbolic links, which point outside it: "
            + ", ".join(links[:10])
            + ". Replace them with the files themselves (or take them out) and export again; nothing was changed."
        )
    pats = Patterns(identifiers)
    result = Result()
    shutil.rmtree(folder / ".e2er", ignore_errors=True)
    for rel in [
        r for r in sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file() or p.is_symlink())
    ]:
        if rel != "provenance.json" and rel not in listed:
            (folder / rel).unlink()
            result.removed.append(rel)
    frozen = prereg_paths(folder)
    when = at or _now()
    _blind_earlier_amendments(prov, frozen, result)
    for rel in sorted(listed):
        path = folder / rel
        if not path.is_file():
            continue
        data = path.read_bytes()
        if rel.lower().endswith(".pdf"):
            continue
        if not _is_text(data):
            if any(True for _ in _byte_hits(data, rel, pats)):
                result.binary.append(rel)
            continue
        text = data.decode("utf-8")
        latex = rel.lower().endswith((".tex", ".ltx", ".sty", ".cls", ".diff", ".patch")) or "\\author" in text
        new, rules, offsets = _edit(text, rel, pats, latex)
        if new == text:
            continue
        after = new.encode("utf-8")
        path.write_bytes(after)
        before = (listed.get(rel) or {}).get("sha256")
        keep = rel in frozen
        earlier = [a for a in prov.get("amendments") or [] if isinstance(a, dict) and a.get("path") == rel]
        if keep:
            result.prereg.append(rel)
        elif isinstance(before, str) and not earlier:
            result.withheld.add(before)
        entry = {
            "path": rel,
            "kind": KIND,
            # The fingerprint before could confirm a guess of the text taken out; a pre-registered file keeps it,
            # since its frozen fingerprint is in design/preregistration.lock.json anyway. After an earlier
            # amendment of the file, "before" is that amendment's "after" (already in the record): the chain links.
            "sha256_before": before if keep or earlier else None,
            "sha256_after": _sha(after),
            "reason": REASON,
            "at": when,
            "anonymisation": {
                "rules": rules,
                "count": sum(len(v) for v in offsets.values()),
                # Where each replacement sits is withheld too: with the offsets and a fingerprint, a guess of the
                # text taken out can be put back and compared. Verify counts the replacements in the file.
                "replacements": [{"text": t, "count": len(o)} for t, o in sorted(offsets.items())],
                "offsets": "withheld: with them a guess of the text taken out could be put back in place",
                **({} if keep else {"fingerprint_before": "withheld: it could confirm a guess of the text taken out"}),
            },
        }
        listed[rel] = {"sha256": entry["sha256_after"], "bytes": len(after)}
        prov.setdefault("amendments", []).append(entry)
        result.changed[rel] = rules
    prov["files"] = dict(sorted(listed.items()))
    prov_path.write_text(dump(prov), encoding="utf-8", newline="\n")
    return result


def _blind_earlier_amendments(prov: dict[str, Any], frozen: set[str], result: Result) -> None:
    """Take out of the copy's earlier amendments what could confirm a guess of a text taken out before.

    An earlier ``e2er redact`` recorded the file's fingerprint before, the replacement's offsets and the length of
    the text: together they confirm a guessed author name in milliseconds. A file's first amendment loses its
    fingerprint before (withheld from the dossier too) unless the file is pre-registered; a later one keeps it,
    since it is the earlier amendment's "after", already in the record. Offsets and sizes go everywhere.
    """
    seen: set[str] = set()
    for a in prov.get("amendments") or []:
        if not isinstance(a, dict) or not isinstance(a.get("path"), str):
            continue
        rel = a["path"]
        first = rel not in seen
        seen.add(rel)
        before = a.get("sha256_before")
        if first and rel not in frozen and before is not None:
            if isinstance(before, str) and not before.startswith("hmac-"):
                result.withheld.add(before)
            a["sha256_before"] = None
            a["fingerprint_before"] = "withheld for double-blind review: it could confirm a guess of the text taken out"
        a.pop("bytes_before", None)
        red = a.get("redaction")
        if isinstance(red, dict) and ("offsets" in red or "removed_bytes" in red or "bytes_before" in red):
            for key in ("offsets", "removed_bytes", "bytes_before"):
                red.pop(key, None)
            red["withheld"] = "offsets and sizes, for double-blind review: they could confirm a guess"
        anon = a.get("anonymisation")
        if isinstance(anon, dict) and isinstance(anon.get("replacements"), list):
            anon["replacements"] = [
                {
                    "text": r.get("text"),
                    "count": len(r["offsets"]) if isinstance(r.get("offsets"), list) else r.get("count"),
                }
                for r in anon["replacements"]
                if isinstance(r, dict)
            ]


def record_problem(entry: dict[str, Any], data: bytes | None) -> str | None:
    """Why an anonymisation amendment does not describe the file ``data`` (its current bytes), or None: each
    replacement it records sits at each of its offsets, or (offsets withheld, since 0.19.0) occurs in the file
    at least as often as recorded."""
    path = entry.get("path")
    rec = entry.get("anonymisation")
    if not isinstance(rec, dict) or not isinstance(rec.get("replacements"), list):
        return f"{path}: the anonymisation record is missing"
    if data is None:
        return f"{path} is missing"
    total = 0
    spans: list[tuple[int, int]] = []
    for r in rec["replacements"]:
        if isinstance(r, dict) and "offsets" not in r and isinstance(r.get("count"), int) and r["count"] >= 0:
            if not isinstance(r.get("text"), str) or not r["text"]:
                # An empty replacement occurs everywhere: it would vouch for any change.
                return f"{path}: the anonymisation record has an empty replacement"
            t = r["text"].encode("utf-8")
            if data.count(t) < r["count"]:
                return (
                    f"{path}: the anonymisation record does not match the file (fewer {r.get('text')!r} than recorded)"
                )
            total += r["count"]
            continue
        if not isinstance(r, dict) or not isinstance(r.get("offsets"), list):
            return f"{path}: the anonymisation record is incomplete"
        if not isinstance(r.get("text"), str) or not r["text"]:
            # An empty replacement sits everywhere: it would vouch for any change.
            return f"{path}: the anonymisation record has an empty replacement"
        t = r["text"].encode("utf-8")
        for o in r["offsets"]:
            if not isinstance(o, int) or isinstance(o, bool) or o < 0 or data[o : o + len(t)] != t:
                return f"{path}: the anonymisation record does not match the file (no {r.get('text')!r} at byte {o})"
            spans.append((o, len(t)))
            total += 1
    if rec.get("count") != total:
        return f"{path}: the anonymisation record counts {rec.get('count')} replacements, it lists {total}"
    ordered = sorted(spans)
    if any(a[0] + a[1] > b[0] for a, b in zip(ordered, ordered[1:], strict=False)):
        return f"{path}: the anonymisation record's replacements overlap"
    from .redact import kept_problem

    return kept_problem(entry, rec.get("kept"), data, spans)


def withhold(doc: Any, fingerprints: set[str]) -> Any:
    """A copy of ``doc`` (the dossier) in which every fingerprint in ``fingerprints`` is None: the run recorded the
    files before they were anonymised, and those fingerprints could confirm a guess of what was taken out."""
    bare = {f.removeprefix("sha256:") for f in fingerprints}
    if isinstance(doc, str):
        return None if doc.removeprefix("sha256:") in bare else doc
    if isinstance(doc, list):
        return [withhold(v, fingerprints) for v in doc]
    if isinstance(doc, dict):
        out = {k: withhold(v, fingerprints) for k, v in doc.items()}
        if any(isinstance(doc.get(k), str) and out[k] is None for k in ("sha256", "sha256_at_export")):
            # A step's output (or a file supplied) says why it has no fingerprint (dossier.WITHHELD_AFTER).
            if out.get("sha256_at_export", "") is None:
                del out["sha256_at_export"]  # a hash or absent, in the dossier format
            out.setdefault("withheld", "anonymised after the step")
        return out
    return doc


# ── the leak check ───────────────────────────────────────────────────────────


@dataclass
class Report:
    leaks: list[Finding] = field(default_factory=list)
    citations: list[Finding] = field(default_factory=list)
    #: Files the check could not read (a PDF without pdftotext, a compressed format): it refuses them too.
    unread: list[Finding] = field(default_factory=list)
    #: Places that may name the author but may as well not (the surname alone, "Imogen Q."): shown to the author,
    #: who confirms them as citations are confirmed (``--blind-ack-self-citations``).
    confirm: list[Finding] = field(default_factory=list)
    searched: int = 0

    @property
    def clean(self) -> bool:
        return not self.leaks and not self.unread


#: Characters that render as nothing: a name with one inside ("Im\u200bogen") reads as the name.
_INVISIBLE = re.compile("[\u00ad\u034f\u061c\u115f\u1160\u17b4\u17b5\u180b-\u180f\u200b-\u200f\u202a-\u202e"
                        "\u2060-\u206f\u3164\ufe00-\ufe0f\ufeff\uffa0]")  # fmt: skip


def _readings(text: str) -> list[str]:
    """Other ways ``text`` reads: NFKC (full-width letters), invisible characters taken out, HTML entities
    and %-escapes undone. Only those that differ from ``text``."""
    import html
    from urllib.parse import unquote

    out = []
    plain = _INVISIBLE.sub("", unicodedata.normalize("NFKC", text))
    for t in (plain, html.unescape(plain), unquote(plain)):
        if t != text and t not in out:
            out.append(t)
    return out


def _weak_patterns(identifiers: Iterable[Identifier]) -> list[tuple[Identifier, re.Pattern[str]]]:
    """The surname alone and "First L." of every name with two words or more: places to confirm, not leaks."""
    out = []
    for i in identifiers:
        if i.kind not in ("name",):
            continue
        words = [w for w in re.split(r"[\s~]+", i.value.strip()) if w]
        if len(words) < 2 or len(words[-1]) < 3:
            continue
        first, last = words[:-1], words[-1]
        srcs = [
            _LETTER_BEFORE + _word(last) + _LETTER_AFTER,
            _LETTER_BEFORE + _SEP.join(_word(w) for w in first) + _SEP + _word(last[0]) + r"\.",
        ]
        try:
            out.append((i, re.compile("|".join(f"(?:{x})" for x in srcs), re.I)))
        except re.error:
            continue
    return out


def _scan_text(
    where: str,
    text: str,
    pats: Patterns,
    report: Report,
    refs_from: int | None = None,
    weak: list[tuple[Identifier, re.Pattern[str]]] | None = None,
) -> None:
    spans: list[tuple[int, int]] = []
    for s, e, i in pats.find(text):
        f = Finding(where, _line_of(text, s), i.label if i.kind != "home" else LABELS["home"])
        (report.citations if is_citation(where, text, s, e, i, refs_from) else report.leaks).append(f)
        spans.append((s, e))
    for reading in _readings(text):
        hits = pats.find(reading)
        if len(hits) <= len(spans):
            continue  # the same places, read another way
        for s, _e, i in hits:
            label = (i.label if i.kind != "home" else LABELS["home"]) + " (written with escapes or hidden characters)"
            report.leaks.append(Finding(where, _line_of(reading, s), label))
    for i, rx in weak or []:
        for m in rx.finditer(text):
            if any(a <= m.start() < b for a, b in spans) or is_citation(where, text, m.start(), m.end(), i, refs_from):
                continue
            report.confirm.append(Finding(where, _line_of(text, m.start()), f"the surname or initial of {i.label}"))


def _byte_hits(data: bytes, where: str, pats: Patterns) -> Iterable[Finding]:
    for enc in ("utf-8", "utf-16-le", "utf-16-be", "latin-1"):
        for shift in (0, 1) if enc.startswith("utf-16") else (0,):
            try:
                text = data[shift:].decode(enc, errors="ignore") if enc != "latin-1" else data.decode("latin-1")
            except LookupError:
                continue
            for s, _e, i in pats.find(text):
                yield Finding(
                    where, 0, (i.label if i.kind != "home" else LABELS["home"]) + f" (in the file's bytes, {enc})"
                )


_COMPRESSED = (".parquet", ".feather", ".arrow", ".zst", ".bz2", ".xz", ".7z", ".rar", ".npz")
_PDF_STREAM = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)
_PDF_HEX = re.compile(rb"<([0-9A-Fa-f\s]{8,})>")


def pdf_meta(path: Path) -> str | None:
    """A PDF's document information and XMP metadata (pdfinfo, from poppler), or None without pdfinfo."""
    exe = shutil.which("pdfinfo")
    if exe is None:
        return None
    out = []
    for args in ([exe, "-enc", "UTF-8", str(path)], [exe, "-meta", str(path)]):
        try:
            proc = subprocess.run(args, capture_output=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired):
            return None
        out.append(proc.stdout.decode("utf-8", errors="replace"))
    return "\n".join(out)


def _pdf_inner(data: bytes) -> Iterable[bytes]:
    """What a PDF holds out of plain sight: its compressed streams (Flate) and its hex strings (UTF-16BE titles)."""
    import zlib

    for m in _PDF_STREAM.finditer(data):
        try:
            yield zlib.decompressobj().decompress(m.group(1), 64 * 1024 * 1024)
        except zlib.error:
            continue
    for m in _PDF_HEX.finditer(data):
        raw = re.sub(rb"\s", b"", m.group(1))
        try:
            yield bytes.fromhex(raw.decode("ascii") + ("0" if len(raw) % 2 else ""))
        except ValueError:
            continue


def _png_text(data: bytes) -> Iterable[bytes]:
    """The text chunks of a PNG (tEXt, zTXt, iTXt), decompressed: an author or a path in the metadata."""
    import struct
    import zlib

    pos = 8
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        kind = data[pos + 4 : pos + 8]
        body = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if kind == b"tEXt":
            yield body
        elif kind == b"zTXt":
            key, _, rest = body.partition(b"\x00")
            try:
                yield key + b" " + zlib.decompress(rest[1:])
            except zlib.error:
                yield key
        elif kind == b"iTXt":
            key, _, rest = body.partition(b"\x00")
            flag = rest[:1]
            parts = rest[2:].split(b"\x00", 2)
            text = parts[2] if len(parts) == 3 else b""
            if flag == b"\x01":
                try:
                    text = zlib.decompress(text)
                except zlib.error:
                    pass
            yield key + b" " + b" ".join(parts[:2]) + b" " + text
        elif kind == b"IEND":
            break


def _scan_bytes(
    where: str,
    data: bytes,
    pats: Patterns,
    report: Report,
    pdf: PdfText,
    depth: int = 0,
    meta: PdfText | None = None,
    weak: list[tuple[Identifier, re.Pattern[str]]] | None = None,
) -> None:
    low = where.lower()
    if zipfile.is_zipfile(io.BytesIO(data)) and depth < 3:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for info in zf.infolist():
                    _scan_text(f"{where}!{info.filename} (its name)", info.filename, pats, report, weak=weak)
                    if info.is_dir():
                        continue
                    _scan_bytes(f"{where}!{info.filename}", zf.read(info), pats, report, pdf, depth + 1, meta, weak)
                return
        except (zipfile.BadZipFile, OSError, RuntimeError):
            pass
    if data[:2] == b"\x1f\x8b" and depth < 3:
        try:
            _scan_bytes(where.removesuffix(".gz"), gzip.decompress(data), pats, report, pdf, depth + 1, meta, weak)
            return
        except (OSError, EOFError):
            pass
    report.searched += 1
    if low.endswith(".pdf") or data[:5] == b"%PDF-":
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".pdf") as tf:
            tf.write(data)
            tf.flush()
            text = pdf(Path(tf.name))
            pdf_info = (meta or pdf_meta)(Path(tf.name))
        if text is None:
            report.unread.append(
                Finding(where, 0, "a PDF whose text could not be read (install pdftotext, from poppler)")
            )
        else:
            _scan_text(where, text, pats, report, references_start(text), weak=weak)
        if pdf_info:
            _scan_text(f"{where} (its metadata)", pdf_info, pats, report)
        report.leaks += list(_byte_hits(data, where, pats))
        for inner in _pdf_inner(data):
            report.leaks += [
                Finding(f.where, 0, f.what.replace("the file's bytes", "the PDF's compressed or hex-coded content"))
                for f in _byte_hits(inner, where, pats)
            ]
        return
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        for chunk in _png_text(data):
            report.leaks += [
                Finding(f.where, 0, f.what.replace("the file's bytes", "the image's text metadata"))
                for f in _byte_hits(chunk, where, pats)
            ]
    if _is_text(data):
        _scan_text(where, data.decode("utf-8"), pats, report, weak=weak)
        return
    report.leaks += list(_byte_hits(data, where, pats))
    if low.endswith(_COMPRESSED):
        report.unread.append(
            Finding(where, 0, "a compressed file the check cannot read inside; take it out or check it")
        )


def leak_check(
    folder: Path | None,
    identifiers: list[Identifier],
    *,
    texts: dict[str, str] | None = None,
    files: dict[str, bytes] | None = None,
    pdf: PdfText | None = None,
    meta: PdfText | None = None,
) -> Report:
    """Search every file of ``folder`` (.e2er/ records aside), its file names, every extra text (``texts``: the
    dossier, the request body) and every extra file (``files``: a package's members) for every identifier and
    home path. ``meta`` reads a PDF's metadata (default: pdfinfo)."""
    pats = Patterns(identifiers)
    weak = _weak_patterns(identifiers)
    report = Report()
    pdf = pdf or pdf_text
    if folder is not None:
        for rel in _files(Path(folder)):
            _scan_text(f"{rel} (its name)", rel, pats, report, weak=weak)
            _scan_bytes(rel, (Path(folder) / rel).read_bytes(), pats, report, pdf, meta=meta, weak=weak)
    for where, data in (files or {}).items():
        _scan_text(f"{where} (its name)", where, pats, report, weak=weak)
        _scan_bytes(where, data, pats, report, pdf, meta=meta, weak=weak)
    for where, text in (texts or {}).items():
        report.searched += 1
        _scan_text(where, text, pats, report, weak=weak)
        # A JSON text: also as its strings read (escapes undone), so \u00f6 and \/ are seen as the letters.
        try:
            value = json.loads(text)
        except ValueError:
            continue
        plain = json.dumps(value, ensure_ascii=False, indent=1)
        if plain != text:
            _scan_text(f"{where} (as read)", plain, pats, report, weak=weak)
    report.leaks = _unique(report.leaks)
    report.citations = _unique(report.citations)
    report.confirm = _unique(report.confirm)
    return report


def _unique(found: list[Finding]) -> list[Finding]:
    seen: set[str] = set()
    out = []
    for f in found:
        if str(f) not in seen:
            seen.add(str(f))
            out.append(f)
    return out


def json_text(value: Any) -> str:
    """A JSON value as the leak check reads it: ASCII-escaped, as it is sent."""
    return json.dumps(value, ensure_ascii=True, indent=1)
