"""The dashboard's htmx is the published 1.9.12 file, and the browser checks it (security review 2026-10-23).

scripts/vendor_htmx.sh fetched it from a CDN without any check; the page loaded it without `integrity`.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HTMX = ROOT / "src/api/static/htmx.min.js"
SCRIPT = ROOT / "scripts/vendor_htmx.sh"


def test_the_shipped_file_matches_the_pinned_hashes():
    body = HTMX.read_bytes()
    pinned = re.search(r'^SHA256="([0-9a-f]{64})"', SCRIPT.read_text(encoding="utf-8"), re.M)
    assert pinned and hashlib.sha256(body).hexdigest() == pinned.group(1)
    sri = "sha384-" + base64.b64encode(hashlib.sha384(body).digest()).decode()
    base = (ROOT / "src/api/templates/base.html").read_text(encoding="utf-8")
    assert f'src="/static/htmx.min.js" integrity="{sri}"' in base


@pytest.mark.skipif(os.name == "nt", reason="a bash script")
def test_a_download_with_another_hash_replaces_nothing(tmp_path):
    """The script with a fake curl that 'downloads' other bytes: it fails and the shipped file stays."""
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "src/api/static").mkdir(parents=True)
    (repo / "scripts/vendor_htmx.sh").write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    dest = repo / "src/api/static/htmx.min.js"
    dest.write_bytes(b"original")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    curl = bin_ / "curl"
    curl.write_text(
        '#!/bin/sh\nwhile [ "$1" != "-o" ]; do shift; done\nprintf "alert(1)" > "$2"\n', encoding="utf-8", newline="\n"
    )
    curl.chmod(0o755)
    env = {"PATH": f"{bin_}:/usr/bin:/bin", "TMPDIR": str(tmp_path)}
    proc = subprocess.run(
        ["bash", str(repo / "scripts/vendor_htmx.sh")], env=env, capture_output=True, encoding="utf-8", errors="replace"
    )
    assert proc.returncode != 0 and "expected" in proc.stderr
    assert dest.read_bytes() == b"original"
