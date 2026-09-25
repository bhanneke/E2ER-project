"""``e2er login``, ``logout``, ``whoami``, ``status`` and ``dossier push``.

    e2er login [--url https://preview.e2er.org]
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
import sys
import webbrowser
from pathlib import Path
from typing import Any

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


def login(url: str | None = None, *, open_browser: bool = True) -> int:
    base = pc.base_url(url)

    def announce(verify: str, code: str) -> None:
        # Flushed: the code must appear at once even when the output is piped.
        print(f"To sign in, open {verify}", flush=True)
        print(f"and confirm the code {code}", flush=True)
        if open_browser and sys.stdout.isatty():
            webbrowser.open(verify)
        print("Waiting for your approval…", flush=True)

    try:
        t = pc.login(base, announce=announce)
    except pc.PlatformError as e:
        print(f"error: {e}")
        return 1
    where = pc.save_token(base, t["token"])
    print(f"✓ Signed in to {base}. The token is kept in {where}; it lasts {90} days from its last use.")
    return 0


def whoami(url: str | None = None) -> int:
    base = pc.base_url(url)
    token = pc.load_token(base)
    if not token:
        print(f"Not signed in to {base}. Run `e2er login`.")
        return 1
    code, body = pc.request(base, "GET", "/api/v1/me", token=token)
    if code != 200:
        print(f"error: {body.get('error', code)}")
        return 1
    handles = ", ".join(body.get("handles") or []) or "none yet (your first publication creates one)"
    print(f"{body['name']} <{body['email']}> on {base}\nHandles: {handles}")
    return 0


def logout(url: str | None = None) -> int:
    base = pc.base_url(url)
    token = pc.load_token(base)
    if token:
        try:
            code, body = pc.request(base, "DELETE", "/api/v1/tokens/current", token=token)
        except Exception as e:  # noqa: BLE001 - offline: forget locally, say so
            code, body = 0, {"error": str(e)}
        if code not in (200, 401, 404):
            print(f"warning: the platform did not confirm the token was ended ({body.get('error', code)});")
            print(f"  remove it on {base}/account")
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
        print(f"error: {body.get('error', code)}")
        return 1
    latest = body.get("latest") or {}
    local = _content_id(b)
    print(f"{body['id']}: {body['title']}\n  {body['url']}")
    print(f"  version {latest.get('number')} of {len(body.get('versions', []))}, dossier {latest.get('dossier_url')}")
    if local == latest.get("content_id"):
        print("  ✓ this folder is the published version")
    else:
        print("  ! this folder differs from the published version; `e2er publish --to` adds a new version")
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
        print(f"error: {body.get('error', code)}")
        return 1
    print(f"✓ Dossier registered: {body['url']}" if code == 201 else f"✓ Dossier already registered: {body['url']}")
    return 0
