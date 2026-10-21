"""``e2er login``, ``logout``, ``whoami``, ``status`` and ``dossier push``.

    e2er login [--url https://preview.e2er.org]
    e2er login --scope study:<owner>/<slug>     # a token for CI: new versions of one study only
    e2er token create --study <owner>/<slug>    # the same, with your personal login
    e2er whoami
    e2er status [bundle]
    e2er dossier push [bundle]
    e2er logout

The URL comes from ``--url``, else ``E2ER_URL``, else https://e2er.org. A study
folder published with ``e2er publish --to`` remembers its platform in
``.e2er/link.json``, so ``e2er status`` there needs no URL.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import webbrowser
from pathlib import Path
from typing import Any

import httpx

from .core import platform_client as pc

LINK = Path(".e2er") / "link.json"


def read_link(bundle: Path) -> dict[str, Any] | None:
    p = bundle / LINK
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def write_link(bundle: Path, link: dict[str, Any]) -> Path:
    p = bundle / LINK
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(link, indent=2) + "\n", encoding="utf-8")
    return p


def _hand_over(base: str, made: dict[str, Any]) -> None:
    """The study token, printed once on standard output (and nothing else there), so it can be piped into a
    CI secret (``| gh secret set E2ER_TOKEN``); everything said about it goes to standard error."""
    err = sys.stderr
    print(
        f"✓ A token for {made['study']} on {base}: it can publish new versions of that study only (no new "
        f"studies or handles, no withdrawal), until {made.get('expires_at', 'it expires')}. e2er does not keep it.",
        file=err,
    )
    if sys.stdout.isatty():
        print(
            "  It is shown once. Store it as a secret of your CI (E2ER_TOKEN), never in a file of the repository:",
            file=err,
        )
    print(made["token"], flush=True)
    print(f"  Revoke it on {base}/account. Your personal login is unchanged.", file=err)


def login(url: str | None = None, *, open_browser: bool = True, scope: str | None = None) -> int:
    base = pc.base_url(url)
    study = None
    if scope is not None:
        try:
            study = pc.parse_study_scope(scope)
        except ValueError as e:
            print(f"error: {e}")
            return 2

    # With --scope the token goes to standard output, so the rest goes to standard error.
    out = sys.stderr if study else sys.stdout

    def announce(verify: str, code: str) -> None:
        # Flushed: the code must appear at once even when the output is piped.
        print(f"To sign in, open {verify}", file=out, flush=True)
        print(f"and confirm the code {code}", file=out, flush=True)
        if study:
            print(f"The token will only publish new versions of {study}.", file=out, flush=True)
        if open_browser and out.isatty():
            webbrowser.open(verify)
        print("Waiting for your approval…", file=out, flush=True)

    try:
        t = pc.login(base, announce=announce, study=study)
    except pc.PlatformError as e:
        print(f"error: {e}", file=out)
        return 1
    if study:
        _hand_over(base, t)
        return 0
    where = pc.save_token(base, t["token"])
    print(f"✓ Signed in to {base}. The token is kept in {where}; it lasts {90} days from its last use.")
    return 0


def token_create(study: str, *, url: str | None = None, name: str | None = None) -> int:
    """`e2er token create --study owner/slug`: a study token, made with the personal login (no browser)."""
    base = pc.base_url(url)
    try:
        slug = pc.parse_study_scope(study, scope=False)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    token = pc.load_token(base)
    if not token:
        print(f"error: not signed in to {base}; run `e2er login --url {base}` first", file=sys.stderr)
        return 1
    try:
        made = pc.create_study_token(base, token, slug, name)
    except pc.PlatformError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    _hand_over(base, made)
    return 0


def whoami(url: str | None = None) -> int:
    base = pc.base_url(url)
    token = pc.load_token(base)
    if not token:
        print(f"Not signed in to {base}. Run `e2er login`.")
        return 1
    try:
        code, body = pc.request(base, "GET", "/api/v1/me", token=token)
    except (pc.PlatformError, httpx.HTTPError) as e:
        print(f"error: could not reach {base}: {e}")
        return 1
    if code != 200:
        print(f"error: {pc.error_text(code, body)}")
        return 1
    handles = ", ".join(body.get("handles") or []) or f"none yet (add one in account settings on {base})"
    print(f"{body['name']} <{body['email']}> on {base}\nHandles: {handles}")
    if body.get("study"):
        print(f"This token can only publish new versions of {body['study']}.")
    return 0


def logout(url: str | None = None) -> int:
    base = pc.base_url(url)
    # With E2ER_TOKEN (a CI job's token for one study), that token is ended and the saved login stays.
    from_env = bool(os.environ.get("E2ER_TOKEN"))
    token = pc.load_token(base)
    if token:
        try:
            code, body = pc.request(base, "DELETE", "/api/v1/tokens/current", token=token)
        except Exception as e:  # noqa: BLE001 - offline: forget locally, say so
            code, body = 0, {"error": str(e)}
        if code not in (200, 401, 404):
            print(f"warning: the platform did not confirm the token was ended ({pc.error_text(code, body)});")
            print(f"  remove it on {base}/account")
    if from_env:
        print(f"✓ Ended the token in E2ER_TOKEN on {base}. A login saved on this computer is unchanged.")
        return 0
    pc.forget_token(base)
    print(f"✓ Signed out of {base}.")
    return 0


def _content_id(bundle: Path) -> str | None:
    p = bundle / "provenance.json"
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def status(bundle: str = ".", url: str | None = None) -> int:
    b = Path(bundle).expanduser().resolve()
    link = read_link(b)
    if not link:
        print(f"{b} is not published yet (no {LINK}). Publish it with `e2er publish --to`.")
        return 1
    base = pc.base_url(url or link.get("platform_url"))
    code, body = pc.request(base, "GET", f"/api/v1/studies/{link['owner_project']}", token=pc.load_token(base))
    if code != 200:
        print(f"error: {pc.error_text(code, body)}")
        return 1
    latest = body.get("latest") or {}
    local = _content_id(b)
    print(f"{body['id']}: {body['title']}\n  {body['url']}")
    print(f"  version {latest.get('number')} of {len(body.get('versions', []))}, dossier {latest.get('dossier_url')}")
    if local == latest.get("content_id"):
        print("  ✓ this folder is the published version")
    else:
        print("  ! this folder differs from the published version; `e2er publish --to` adds a new version")
    from .core.availability import describe

    local_manifest = b / "e2er.json"
    if local_manifest.is_file():
        av = json.loads(local_manifest.read_text(encoding="utf-8")).get("availability")
        print(f"  availability here: {describe(av)}")
    if body.get("availability"):
        print(f"  availability on the platform: {describe(body['availability'])}")
    for c in body.get("checks", []):
        print(f"  {c['status']:4}  {c['check_id']} ({c['run_by']})")
    for p in body.get("pending_confirmations", []):
        print(f"  waiting for {p['name']} to confirm ({p['roles']})")
    return 0


def dossier_push(bundle: str = ".", url: str | None = None) -> int:
    b = Path(bundle).expanduser().resolve()
    manifest_path = b / "e2er.json"
    if not manifest_path.is_file():
        print("error: no e2er.json here; run `e2er publish` first (it writes the dossier)")
        return 1
    d = json.loads(manifest_path.read_text(encoding="utf-8")).get("dossier") or {}
    if "doc" not in d:
        print("error: e2er.json has no dossier; run `e2er publish` again")
        return 1
    link = read_link(b) or {}
    base = pc.base_url(url or link.get("platform_url"))
    token = pc.load_token(base)
    if not token:
        print(f"Not signed in to {base}. Run `e2er login`.")
        return 1
    code, body = pc.request(base, "POST", "/api/v1/dossiers", token=token, body={"id": d["id"], "doc": d["doc"]})
    if code not in (200, 201):
        print(f"error: {pc.error_text(code, body)}")
        return 1
    print(f"✓ Dossier registered: {body['url']}" if code == 201 else f"✓ Dossier already registered: {body['url']}")
    return 0
