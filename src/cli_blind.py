"""``e2er publish --blind``, ``e2er pack --blind`` and ``e2er publish --unblind``: double-blind review.

``e2er publish <folder> --blind --to https://e2er.org`` publishes an anonymous version of a
study at ``e2er.org/r/<code>``, an address nobody can guess (160 random bits). e2er.org
keeps the account that published it to itself: the page names no author, and the version
is in no list, search, sitemap, people page or graph.

Nothing leaves this computer before the anonymisation and the leak check
(src/core/anonymise.py) passed on a copy of the folder: the copy, next to the folder
(``<folder>-anonymous-<first 8 characters of the code>``), is what is published, and
``e2er pack --blind`` writes it into the .e2er file a journal takes as supplementary
material. The folder itself is not changed. GitHub, Zenodo and every public address of
the data, the code or the paper are refused: each would name the author.

Reviewers run ``e2er verify <file.e2er> --against https://e2er.org/r/<code>`` and
``e2er reproduce <file.e2er>``.

After the review, ``e2er publish <copy> --unblind <code> --owner <handle> --project <name>``
(or the account page on e2er.org) publishes a new, normal version under the author's name;
the anonymous version stays as it is. With a named export in place of the copy, that
export is the new version's content.
"""

from __future__ import annotations

import base64
import contextlib
import io
import json
import secrets
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from .core import anonymise as an
from .core import platform_client as pc
from .core.research_object import ANONYMOUS, MANIFEST_NAME

#: Options that would put the author's name, or an address that names it, on the anonymous version.
REFUSED = (
    ("github_repo", "--github", "it pushes the files to a GitHub repository under your login"),
    ("zenodo", "--zenodo", "a Zenodo deposit names its creators"),
    ("repo", "--repo", "a repository address names its owner"),
    ("commit", "--commit", "it pins a repository, which names its owner"),
    ("path", "--path", "it names a folder in a repository"),
    ("data_url", "--data-url", "a public address of the data can name you"),
    ("code_url", "--code-url", "a public address of the code can name you"),
    ("paper_url", "--paper-url", "a public address of the paper can name you"),
    ("coauthors", "--coauthor", "an anonymous version names no author; name them when you unblind it"),
    ("orcid", "--orcid", "an anonymous version names no author; give it when you unblind it"),
    ("name", "--name", "an anonymous version names no author; give it when you unblind it"),
    ("github", "--github-login", "an anonymous version names no author; give it when you unblind it"),
    ("derived_from", "--derived-from", "it links the study to your earlier work"),
    ("offline", "--offline", "the anonymous version is published from the command line only"),
)


def new_code() -> str:
    """An address code nobody can guess: 160 random bits, 32 characters of a-z and 2-7."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").lower()


def refused_options(kw: dict[str, Any]) -> str | None:
    """Why an option given with --blind cannot be used, or None."""
    for key, flag, why in REFUSED:
        if kw.get(key):
            return f"--blind cannot go with {flag}: {why}. Leave out {flag}; nothing was sent."
    if kw.get("paper") == "public":
        return (
            "--blind keeps the paper private: the journal has your submission, and reviewers get the paper in the "
            ".e2er file. Leave out --paper public; nothing was sent."
        )
    if kw.get("stamp") is False:
        return (
            "--blind needs the stamp: the paper's first page names the anonymous version's address, and the PDF is "
            "built again from the anonymised source. Leave out --no-stamp; nothing was sent."
        )
    return None


def _me(base: str, token: str | None) -> tuple[dict[str, Any] | None, str]:
    if not token:
        return None, f"not signed in to {base}"
    try:
        code, body = pc.request(base, "GET", "/api/v1/me", token=token)
    except Exception as e:  # noqa: BLE001 - network errors are the user's to see
        return None, f"could not reach {base}: {e}"
    if code != 200:
        return None, f"{base} did not accept the sign-in ({pc.error_text(code, body)})"
    if body.get("study"):
        return None, (
            f"this token can only publish new versions of {body['study']}; an anonymous version needs your "
            "personal login (`e2er login`)"
        )
    return body, ""


def _print_findings(head: str, found: list[an.Finding], limit: int = 60) -> None:
    print(head)
    for f in found[:limit]:
        print(f"  {f}")
    if len(found) > limit:
        print(f"  … and {len(found) - limit} more")


def copy_path(bundle: Path, code: str) -> Path:
    return bundle.parent / f"{bundle.name}-anonymous-{code[:8]}"


def publish_blind(
    bundle: str,
    *,
    to_url: str | None,
    dry_run: bool,
    yes: bool,
    interactive: bool,
    identifiers: list[str] | None = None,
    ack_self_citations: bool = False,
    **kw: Any,
) -> int:
    """`e2er publish <folder> --blind`: anonymise a copy, check it for leaks, publish it at e2er.org/r/<code>."""
    from . import cli_publish as cp

    b = Path(bundle).expanduser().resolve()
    why = refused_options(kw)
    if why:
        print(f"error: {why}")
        return 2
    for key in [k for k, _f, _w in REFUSED] + [
        "github_path",
        "owner",
        "project",
        "site",
        "out",
        "roles",
        "zenodo_sandbox",
    ]:
        kw.pop(key, None)
    if not dry_run and not to_url:
        print(
            "error: --blind publishes on a platform: add --to https://e2er.org (after `e2er login`), or --dry-run to "
            "see what would be sent. Nothing was sent."
        )
        return 2
    if not (b / "provenance.json").is_file():
        print(f"error: {b} is not an exported study folder (no provenance.json); run `e2er export` first")
        return 1
    found = cp._folder_problems(b)
    if found:
        print("error: the folder is not what was exported; nothing was copied or sent:")
        for p in found:
            print(f"  {p}")
        return 1
    if not dry_run and not yes and not interactive:
        print(
            "error: e2er publish sends the study only after you confirm it. Run it in a terminal to be asked, "
            "or add --yes (scripts, CI). --dry-run shows what would be sent. Nothing was sent."
        )
        return 1

    base = pc.base_url(to_url)
    token = pc.load_token(base)
    me, why_not = _me(base, token)
    if me is None:
        if not dry_run:
            print(f"error: {why_not}; run `e2er login --url {base}`. Nothing was sent.")
            return 1
        print(
            f"note: {why_not}: this dry run checks the identifiers of this computer only, not your account's "
            "name, e-mail address and handles",
            file=sys.stderr,
        )
    study_folder = kw.get("study_folder") or cp._study_folder(b)
    kw["study_folder"] = study_folder
    folders = [b] + ([study_folder] if study_folder else [])
    ids = an.collect(me, folders=folders, extra=identifiers or [])

    # The run's database belongs to the real folder: found here, so the copy (elsewhere on disk) uses it.
    if not kw.get("no_db"):
        try:
            paper_id = (json.loads((b / "provenance.json").read_text(encoding="utf-8")).get("run") or {}).get(
                "paper_id"
            )
        except (OSError, ValueError, AttributeError):
            paper_id = None
        run_db, _why = cp.find_run_db(b, kw.get("db"), paper_id)
        if run_db is not None:
            kw["db"] = str(run_db)

    code = new_code()
    url = f"{base}/r/{code}"
    work = Path(tempfile.mkdtemp(prefix="e2er-blind-"))
    try:
        copy = work / f"anonymous-{code[:8]}"
        shutil.copytree(b, copy, symlinks=True)
        try:
            result = an.anonymise(copy, ids)
        except an.AnonymiseError as e:
            print(f"error: {e}")
            return 1
        if result.binary:
            print(
                "error: these files hold something that identifies you, and they are not text files, so e2er cannot "
                "take it out in place. Build them again without it (or leave them out of the export); nothing was "
                "sent:"
            )
            for rel in result.binary:
                print(f"  {rel}")
            return 1
        log = io.StringIO()
        with contextlib.redirect_stdout(log):
            rc, manifest = cp._describe(
                str(copy),
                owner=ANONYMOUS,
                project=code,
                remote=True,
                site=base,
                blind={"code": code, "url": url, "withheld": sorted(result.withheld)},
                **kw,
            )
        if rc or manifest is None:
            print(log.getvalue().rstrip())
            print("error: the anonymised copy could not be prepared; nothing was sent")
            return rc or 1
        body = cp.request_body(manifest, copy)
        # An anonymous version names no repository, not even an empty one.
        body.pop("repository", None)
        if not body["manifest"].get("repository"):
            body["manifest"].pop("repository", None)
        body["blind"] = {"code": code}
        refusals = cp.problems(body)
        if refusals:
            print("error: the request contains something that must not leave this machine; nothing was sent:")
            for p in refusals:
                print(f"  {p}")
            return 1

        # The final leak check: every file of the copy, the dossier and the request, as they would be sent.
        report = an.leak_check(
            copy,
            ids,
            texts={"the request": an.json_text(body), "the dossier": an.json_text(manifest["dossier"]["doc"])},
        )
        if not report.clean:
            _print_findings(
                "error: the anonymous version would still identify you; nothing was sent. Take these out of the "
                "exported folder (`e2er redact`, or edit the source and export again) and publish again:",
                report.leaks + report.unread,
            )
            return 1
        cites = an.self_citations(copy, ids) + report.citations
        if (cites or report.confirm) and not ack_self_citations:
            if cites:
                _print_findings(
                    "error: the study may cite your own work. Whether a citation gives you away cannot be judged "
                    "mechanically: read these places (cite your work in the third person, or leave it out), then "
                    "publish again with --blind-ack-self-citations. Nothing was sent:",
                    cites,
                )
            if report.confirm:
                _print_findings(
                    "error: these places hold your surname alone or your first name with an initial ('Imogen Q.'), "
                    "which may name you or someone else. Read them, take out what names you, then publish again with "
                    "--blind-ack-self-citations. Nothing was sent:",
                    report.confirm,
                )
            return 1
        for line in log.getvalue().splitlines():
            if line.startswith(("note:", "warning:", "WARNING:")):
                print(line)
        if cites or report.confirm:
            _print_findings(
                "note: you confirmed these places that may cite your own work or name you:",
                cites + report.confirm,
                limit=20,
            )
        if result.prereg:
            print(
                "warning: these pre-registered files were anonymised: "
                + ", ".join(result.prereg)
                + ". Their fingerprints from before stay in design/preregistration.lock.json and the dossier (the "
                "pre-registration needs them), so someone who guesses the exact text taken out could confirm the "
                "guess. Remove your name from plan files before you freeze them."
            )
        changed = ", ".join(f"{rel} ({', '.join(rules)})" for rel, rules in list(result.changed.items())[:12])
        print(
            f"✓ Anonymised a copy of the folder: {len(result.changed)} file(s) changed"
            + (f": {changed}" if changed else "")
            + (" …" if len(result.changed) > 12 else "")
        )
        print(
            f"✓ Leak check passed: {report.searched} file(s) and texts searched for {len(ids)} identifier(s) "
            "(your name, e-mail addresses, handles, ORCID iD, GitHub login, git authors, this computer's user and "
            "host name, home-directory paths)"
        )
        if dry_run:
            print(json.dumps(body, indent=2, ensure_ascii=False))
            print("dry run: nothing was written or sent", file=sys.stderr)
            return 0

        title = str(manifest.get("title") or b.name)
        short = title if len(title) <= 120 else title[:117] + "…"
        question = (
            f"Publish '{short}' to {base} as an anonymous version for double-blind review? e2er.org shows no "
            "author; it keeps your account private."
        )
        print("\nWhat goes where:")
        print(f"  {url}: the description, the dossier and the file fingerprints, without your name")
        print(f"  {copy_path(b, code)}: the anonymised copy (on this computer), for `e2er pack --blind`")
        if yes:
            print(f"{question} yes (--yes)")
        elif not cp._confirm(question):
            print("Not published: nothing was sent.")
            return 1
        dest = copy_path(b, code)
        shutil.move(str(copy), str(dest))
        try:
            status, resp = pc.request(base, "POST", "/api/v1/blind", token=token, body=body)
        except Exception as e:  # noqa: BLE001 - network errors are the user's to see
            shutil.rmtree(dest, ignore_errors=True)
            print(f"error: could not reach {base}: {e}; nothing was published")
            return 1
        if status == 404 and "blind" not in json.dumps(resp).lower():
            shutil.rmtree(dest, ignore_errors=True)
            print(f"error: {base} does not take anonymous versions yet; nothing was published")
            return 1
        if status not in (200, 201, 202):
            shutil.rmtree(dest, ignore_errors=True)
            print(f"error: {pc.error_text(status, resp)}")
            for p in resp.get("found") or resp.get("problems") or []:
                print(f"  {p}")
            return 1
        if resp.get("held"):
            print(f"✓ Held: {resp.get('message') or 'confirm it in your browser'}")
        else:
            word = "already published as" if resp.get("existing") else "published as"
            print(f"✓ {word} an anonymous version for double-blind review: {resp.get('url') or url}")
        print(f"  anonymised copy: {dest}")
        print(f"  For the journal: e2er pack --blind {dest}")
        print(f"  Reviewers check it: e2er verify <file.e2er> --against {resp.get('url') or url}")
        print("                     e2er reproduce <file.e2er>")
        print(
            f"  After the review: e2er publish {dest} --unblind {code} --owner <your handle> --project <name> "
            f"--to {base} (or on your account page)"
        )
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ── the file for the journal ─────────────────────────────────────────────────


def anonymous_code(folder: Path) -> str | None:
    """The code of the anonymous version the folder is (its e2er.json id anonymous/<code>), or None."""
    try:
        m = json.loads((folder / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    mid = str(m.get("id") or "") if isinstance(m, dict) else ""
    owner, _, code = mid.partition("/")
    return code if owner == ANONYMOUS and code else None


def find_copy(target: Path) -> tuple[Path | None, str]:
    """The anonymised copy to pack: ``target`` itself, or the one copy next to it (``<folder>-anonymous-…``)."""
    if anonymous_code(target):
        return target, ""
    copies = sorted(p for p in target.parent.glob(f"{target.name}-anonymous-*") if p.is_dir() and anonymous_code(p))
    if len(copies) == 1:
        return copies[0], ""
    if copies:
        return None, "there are several anonymised copies of this folder; name the one to pack:\n  " + "\n  ".join(
            str(p) for p in copies
        )
    return None, (
        f"{target} has no anonymised copy: publish it first with `e2er publish {target} --blind --to …`; the file "
        "for the journal must hold exactly the files the anonymous version names"
    )


def pack_blind(target: str, out: str | None, *, offline: bool = False, no_data: bool = False) -> int:
    """`e2er pack --blind`: the anonymised copy as one .e2er file, checked for leaks once more."""
    from .core.export import package as pkg

    folder, why = find_copy(Path(target).expanduser().resolve())
    if folder is None:
        print(f"error: {why}")
        return 1
    code = anonymous_code(folder) or ""
    dest = Path(out).expanduser() if out else folder.parent / f"anonymous-{code[:8]}{pkg.SUFFIX}"
    if dest.is_dir():
        dest = dest / f"anonymous-{code[:8]}{pkg.SUFFIX}"
    try:
        packed = pkg.build(folder, dest, offline=offline, no_data=no_data, anonymous=True)
    except pkg.PackageError as e:
        print(f"error: {e}")
        return 1
    try:
        url = str((json.loads((folder / MANIFEST_NAME).read_text(encoding="utf-8")).get("dossier") or {}).get("url"))
    except (OSError, ValueError):
        url = ""
    base = url.split("/r/")[0] if "/r/" in url else pc.base_url(None)
    me, why_not = _me(base, pc.load_token(base))
    if me is None:
        print(f"note: {why_not}: the file is checked for the identifiers of this computer only")
    ids = an.collect(me, folders=[folder])
    report = an.leak_check(None, ids, files={packed.path.name: packed.path.read_bytes()})
    if report.confirm:
        _print_findings("note: your surname alone or with an initial is in these places; check them:", report.confirm)
    if not report.clean:
        packed.path.unlink(missing_ok=True)
        _print_findings("error: the file would identify you; it was deleted:", report.leaks + report.unread)
        return 1
    print(f"Packed → {packed.path}")
    print(
        f"  {len(packed.manifest['contents'])} file(s), {pkg.human_size(packed.size)}; fingerprint "
        f"{packed.manifest['fingerprint']}; no author named; leak check passed ({report.searched} files searched)"
    )
    for item in packed.manifest.get("left_out") or []:
        print(f"  left out: {item['path']} ({item['reason']}); {pkg.rerun_words(item)}")
    print(f"  Reviewers: e2er verify {packed.path.name} --against {url or '<the anonymous address>'}")
    return 0


# ── after the review ─────────────────────────────────────────────────────────


def parse_code(spec: str) -> str | None:
    """The code of ``spec``: the code itself or an address …/r/<code>."""
    s = spec.strip().rstrip("/")
    code = s.rsplit("/r/", 1)[-1] if "/r/" in s else s
    return code if len(code) == 32 and all(c in "abcdefghijklmnopqrstuvwxyz234567" for c in code) else None


def unblind(
    bundle: str,
    spec: str,
    *,
    to_url: str | None,
    yes: bool,
    interactive: bool,
    owner: str,
    project: str,
    contributors: list[dict[str, Any]],
    named: dict[str, Any] | None = None,
) -> int:
    """POST /api/v1/blind/<code>/unblind: a new, normal version under ``owner/project``; the anonymous one stays.

    ``named`` (the request of a named export, built by publish): that export becomes the new version's content.
    """
    code = parse_code(spec)
    if code is None:
        print(f"error: --unblind {spec!r}: give the anonymous version's code or its address (…/r/<code>)")
        return 2
    base = pc.base_url(to_url or (spec.split("/r/")[0] if "/r/" in spec else None))
    token = pc.load_token(base)
    me, why_not = _me(base, token)
    if me is None:
        print(f"error: {why_not}; run `e2er login --url {base}`. Nothing was sent.")
        return 1
    what = "the named export in this folder" if named else "the files of the anonymous version"
    question = (
        f"Publish a version of {base}/r/{code} with its authors as {owner}/{project}, with {what}? Your name is "
        "then shown to everyone; the anonymous version stays as it is."
    )
    if not yes and not interactive:
        print("error: unblinding needs your confirmation: run it in a terminal, or add --yes. Nothing was sent.")
        return 1
    if yes and named:
        pass  # asked before the named export was described
    elif yes:
        print(f"{question} yes (--yes)")
    else:
        from .cli_publish import _confirm

        if not _confirm(question):
            print("Not unblinded: nothing was sent.")
            return 1
    body: dict[str, Any] = {"owner": owner, "project": project}
    if contributors:
        body["contributors"] = contributors
    if named:
        body.update(named)
    try:
        status, resp = pc.request(base, "POST", f"/api/v1/blind/{code}/unblind", token=token, body=body)
    except Exception as e:  # noqa: BLE001 - network errors are the user's to see
        print(f"error: could not reach {base}: {e}")
        return 1
    if status not in (200, 201):
        print(f"error: {pc.error_text(status, resp)}")
        for p in resp.get("problems") or []:
            print(f"  {p}")
        return 1
    print(f"✓ Unblinded: {resp.get('owner_project')}, version {resp.get('version')}: {resp.get('study_url')}")
    print(f"  The anonymous version {base}/r/{code} stays as it was published and links to it.")
    if bundle and named and resp.get("id"):
        from .cli_platform import write_link

        write_link(
            Path(bundle).expanduser().resolve(),
            {
                "platform_url": base,
                "id": resp["id"],
                "owner_project": resp["owner_project"],
                "version": resp["version"],
                "dossier_id": (named.get("dossier") or {}).get("id"),
                "content_id": (named.get("manifest") or {}).get("content_id"),
            },
        )
    return 0
