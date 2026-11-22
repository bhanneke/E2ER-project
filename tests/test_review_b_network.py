"""Reload steps reach public hosts only; the install container runs pip unprivileged (review B, finding 17)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.core import reproduce_sandbox as rs
from src.core.pipeline.sandbox import Limits

GUARD = Path(__file__).resolve().parents[1] / "src" / "core" / "reproduce_netguard.py"

PROBE = """
import importlib.util, socket, sys, json
spec = importlib.util.spec_from_file_location("g", sys.argv[1]); g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
out = {}
for host in sys.argv[2:]:
    try:
        g._guard(host, 80); out[host] = "allowed"
    except OSError as e:
        out[host] = "refused"
print(json.dumps(out))
"""


def _probe(mode: str, log: Path, *hosts: str) -> dict[str, str]:
    env = {"E2ER_REPRODUCE_NETWORK": mode, "E2ER_REPRODUCE_NETWORK_LOG": str(log), "PATH": "/usr/bin:/bin"}
    done = subprocess.run(
        [sys.executable, "-I", "-c", PROBE, str(GUARD), *hosts], env=env, capture_output=True, text=True, check=True
    )
    return json.loads(done.stdout)


def test_a_reload_step_reaches_public_hosts_only(tmp_path: Path) -> None:
    log = tmp_path / "net.jsonl"
    seen = _probe(
        "public",
        log,
        "ghoapi.azureedge.net",
        "8.8.8.8",
        "127.0.0.1",
        "localhost",
        "host.docker.internal",
        "192.168.65.254",
        "10.0.0.1",
        "172.17.0.1",
        "169.254.169.254",
        "fd00::1",
        "::ffff:127.0.0.1",
        "metadata.google.internal",
    )
    assert seen["ghoapi.azureedge.net"] == "allowed" and seen["8.8.8.8"] == "allowed"
    refused = {h for h, v in seen.items() if v == "refused"}
    assert refused == set(seen) - {"ghoapi.azureedge.net", "8.8.8.8"}
    lines = [json.loads(x) for x in log.read_text().splitlines()]
    assert all(x["blocked"] for x in lines) and {x["host"] for x in lines} == refused  # public hosts unrecorded


def test_the_other_modes_are_unchanged(tmp_path: Path) -> None:
    assert _probe("block", tmp_path / "a", "127.0.0.1", "example.org") == {
        "127.0.0.1": "allowed",
        "example.org": "refused",
    }
    assert _probe("record", tmp_path / "b", "10.0.0.1") == {"10.0.0.1": "allowed"}


def test_install_runs_pip_as_nobody_with_few_capabilities(tmp_path: Path) -> None:
    script = rs.install_script(wheels=False, e2er_reqs=["httpx==0.28.1"])
    root, _, unprivileged = script.partition("exec setpriv")
    assert "pip" not in root and "chown -R 65534:65534" in root
    assert "--reuid=65534" in unprivileged and "pip install" in unprivileged
    req = tmp_path / "requirements.txt"
    req.write_text("numpy==2.1.0\n")
    argv = rs.install_argv("docker", "python:3.12-slim", "n", script, req, None, Limits())
    assert "--cap-drop=ALL" in argv and "--network" not in argv  # PyPI only, as before
    assert "--add-host=host.docker.internal:127.0.0.1" in argv
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    offline = rs.install_argv("docker", "python:3.12-slim", "n", rs.install_script(wheels=True, e2er_reqs=[]), req,
                              wheels, Limits())  # fmt: skip
    assert offline[offline.index("--network") + 1] == "none"


@pytest.mark.parametrize("network", [True, False])
def test_a_step_container_on_bridge_does_not_name_the_host(tmp_path: Path, network: bool) -> None:
    box = rs.Box(docker="docker", image="img", base="python:3.12-slim", python="3.12", e2er=False)
    argv = rs.run_argv(box, "n", tmp_path, ["python", "a.py"], {}, network)
    assert ("--add-host=host.docker.internal:127.0.0.1" in argv) is network
    assert argv[argv.index("--network") + 1] == ("bridge" if network else "none")


@pytest.mark.parametrize("address", ["http://e2er.org/ada/demo", "ftp://e2er.org/ada/demo", "e2er.org/ada/demo"])
def test_fetch_takes_https_addresses_only(address: str) -> None:
    from src.cli_fetch import FetchError, resolve

    with pytest.raises(FetchError, match="https://"):
        resolve(address)


def test_fetch_says_which_steps_reach_the_network(tmp_path: Path, monkeypatch, capsys) -> None:
    from src import cli_fetch

    monkeypatch.setattr(cli_fetch, "resolve", lambda a, v=None: ({}, "x", "https://e2er.example/a/b"))
    monkeypatch.setattr(cli_fetch.sp, "record_problems", lambda rec: [])
    monkeypatch.setattr(cli_fetch.sp, "file_name", lambda rec: "a.e2er")
    target = tmp_path / "a.e2er"
    target.write_bytes(b"x")
    monkeypatch.setattr(cli_fetch.sp, "download", lambda *a, **k: target)
    from src.core import repro_requirements as rr

    monkeypatch.setattr(rr, "print_summary", lambda *a, **k: None)
    rec = {"bytes": 1, "sha256": "0" * 64, "url": "https://x", "host": "github"}
    monkeypatch.setattr(cli_fetch, "resolve", lambda a, v=None: (rec, "x", "https://e2er.example/a/b"))
    assert cli_fetch.fetch("https://e2er.example/a/b", str(target)) == 0
    out = capsys.readouterr().out
    assert "no network, no folder of yours" not in out
    assert "reaches PyPI" in out and "every other step runs without network" in out
