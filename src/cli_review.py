"""`e2er review` and `e2er preregister deposit`: the researcher step from the command line.

    e2er review <paper_id>                         show the step and choose interactively
    e2er review <paper_id> --approve               approve and continue
    e2er review <paper_id> --instruction "TEXT"    an instruction for the following steps
    e2er review <paper_id> --edit FILE             edit one of the step's files in $EDITOR
    e2er review <paper_id> --send-back STEP --remark "TEXT"
    e2er preregister deposit <paper_id|folder> --zenodo [--sandbox]

Every action is recorded and appears in the study's dossier.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def _client() -> Any:
    import httpx

    from .cli_run import _api_root, _ensure_api_up

    ok, err = _ensure_api_up()
    if not ok:
        raise SystemExit(f"e2er review: {err}")
    return httpx.Client(base_url=_api_root(), timeout=30.0)


def _post(http: Any, paper_id: str, body: dict[str, Any]) -> int:
    r = http.post(f"/api/papers/{paper_id}/review", json=body)
    if r.status_code >= 400:
        detail = r.json().get("detail") if r.headers.get("content-type", "").startswith("application/json") else r.text
        print(f"e2er review: {detail}", file=sys.stderr)
        return 1
    rec = r.json().get("recorded", {})
    what = {
        "approve": "approved",
        "edit": f"saved {rec.get('file')}",
        "instruction": "instruction added",
        "send_back": f"sent back {rec.get('target')}",
    }
    print(f"✓ {what.get(rec.get('action'), rec.get('action'))} (recorded for the dossier)")
    if "resumed" in r.json():
        print("✓ the run continues")
    return 0


def _edit_in_editor(content: str, name: str) -> str:
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
    suffix = Path(name).suffix or ".txt"
    with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8") as fh:
        fh.write(content)
        path = fh.name
    try:
        subprocess.run([*editor.split(), path], check=False)
        return Path(path).read_text(encoding="utf-8")
    finally:
        os.unlink(path)


def review(
    paper_id: str,
    *,
    approve: bool = False,
    instruction: str | None = None,
    edit: str | None = None,
    send_back: str | None = None,
    remark: str | None = None,
) -> int:
    http = _client()
    r = http.get(f"/api/papers/{paper_id}/review")
    if r.status_code >= 400:
        print(f"e2er review: {r.text}", file=sys.stderr)
        return 1
    data = r.json()
    pending = data.get("pending")
    if not pending:
        print("The run is not stopped at a researcher step.")
        return 1
    files = {f["name"]: f for f in data.get("files", [])}

    if edit:
        if edit not in files:
            print(f"e2er review: {edit} is not one of this step's files: {', '.join(files)}", file=sys.stderr)
            return 1
        new = _edit_in_editor(files[edit]["content"], edit)
        if new == files[edit]["content"]:
            print("No change.")
            return 0
        return _post(http, paper_id, {"action": "edit", "file": edit, "content": new})
    if instruction:
        return _post(http, paper_id, {"action": "instruction", "text": instruction})
    if send_back:
        if not remark:
            print("e2er review: --send-back needs --remark", file=sys.stderr)
            return 1
        return _post(http, paper_id, {"action": "send_back", "step": send_back, "remark": remark})
    if approve:
        return _post(http, paper_id, {"action": "approve"})

    # Interactive.
    print(f"Researcher step: {pending['stage']}" + (" (pre-registration)" if pending["kind"] == "preregister" else ""))
    for name, f in files.items():
        print(f"  {name}" + ("" if f["exists"] else " (not written yet)"))
    if data.get("sendable"):
        print(f"  can be sent back: {', '.join(data['sendable'])}")
    while True:
        choice = input("[a]pprove, [e]dit a file, [i]nstruction, [s]end back, [q]uit: ").strip().lower()[:1]
        if choice == "q":
            return 0
        if choice == "a":
            return _post(http, paper_id, {"action": "approve"})
        if choice == "e":
            name = input(f"file ({', '.join(files)}): ").strip()
            if name in files:
                new = _edit_in_editor(files[name]["content"], name)
                if new != files[name]["content"]:
                    _post(http, paper_id, {"action": "edit", "file": name, "content": new})
                    files[name]["content"] = new
        elif choice == "i":
            text = input("instruction: ").strip()
            if text:
                _post(http, paper_id, {"action": "instruction", "text": text})
        elif choice == "s":
            step = input(f"step ({', '.join(data.get('sendable', []))}): ").strip()
            text = input("remark: ").strip()
            return _post(http, paper_id, {"action": "send_back", "step": step, "remark": text})


def deposit(target: str, *, zenodo: bool = False, osf: bool = False, sandbox: bool = False) -> int:
    """Deposit a frozen pre-registration with the researcher's own account."""
    from .core.pipeline.preregistration import ZENODO_SANDBOX_URL, ZENODO_URL, deposit_zenodo, load_lock

    folder = Path(target).expanduser()
    if not folder.is_dir():
        http = _client()
        r = http.get(f"/api/papers/{target}")
        if r.status_code >= 400:
            print(f"e2er preregister: no paper or folder {target!r}", file=sys.stderr)
            return 1
        folder = Path(r.json().get("workspace") or "")
    if (folder / "design").is_dir() and load_lock(folder / "design"):
        folder = folder / "design"
    if load_lock(folder) is None:
        print(
            "e2er preregister: no frozen pre-registration here; approve it at its researcher step first",
            file=sys.stderr,
        )
        return 1
    if osf:
        print(
            "e2er preregister: OSF deposit is not built yet. OSF registrations go through its "
            "registration workflow; deposit on Zenodo with --zenodo, or upload preregistration.md to OSF yourself.",
            file=sys.stderr,
        )
        return 2
    if not zenodo:
        print("e2er preregister: choose --zenodo (or --osf)", file=sys.stderr)
        return 1
    token = os.environ.get("ZENODO_SANDBOX_TOKEN" if sandbox else "ZENODO_TOKEN")
    if not token:
        print(
            f"e2er preregister: set {'ZENODO_SANDBOX_TOKEN' if sandbox else 'ZENODO_TOKEN'} to your own Zenodo token",
            file=sys.stderr,
        )
        return 1
    dep = deposit_zenodo(folder, token, base_url=ZENODO_SANDBOX_URL if sandbox else ZENODO_URL)
    print(f"✓ deposited on Zenodo: doi {dep.get('doi')}  {dep.get('url')}")
    return 0
