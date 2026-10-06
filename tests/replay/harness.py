"""Install the replay level into an e2er process (the server, or a command).

Called by ``python -m tests.replay.cli …`` before e2er's own ``main()``.
Every change is test-only and named here:

* the AI backend: ``get_backend`` returns :class:`ReplayBackend` for the
  scenario in ``E2ER_REPLAY_SCENARIO``, standing in for the backend and
  model the run names (so a run on ``codex`` is recorded as a run on Codex
  with its model, and overrides can vary one backend's runs);
* Zenodo: the keyless record fetch (replication template) and the deposit
  API (``e2er publish --zenodo``, ``e2er preregister deposit``) go to the
  fake server at ``E2ER_REPLAY_ZENODO_URL``;
* Docker: the replication template's sandbox runs with a fake Docker that
  writes the recorded run's output files (``scenario.json`` → ``sandbox``)
  and reports the recorded environment. No container runs;
* the network: every connection to a host other than this machine is
  refused and written to ``E2ER_REPLAY_NETLOG``, so a story can show that
  nothing reached Zenodo, GitHub, a model provider or a literature index.
"""

from __future__ import annotations

import functools
import json
import os
import socket
import subprocess
from pathlib import Path
from typing import Any

ENV_ZENODO = "E2ER_REPLAY_ZENODO_URL"
ENV_NETLOG = "E2ER_REPLAY_NETLOG"
_LOCAL = {"127.0.0.1", "::1", "localhost", "0.0.0.0", ""}


def _note_blocked(host: str) -> None:
    path = os.environ.get(ENV_NETLOG)
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{os.getpid()} {host}\n")


def _guard_network() -> None:
    real_getaddrinfo = socket.getaddrinfo
    real_connect = socket.socket.connect

    def getaddrinfo(host: Any, *args: Any, **kwargs: Any) -> Any:
        h = host.decode() if isinstance(host, bytes) else str(host or "")
        if h not in _LOCAL and not h.startswith("127."):
            _note_blocked(h)
            raise socket.gaierror(socket.EAI_NONAME, f"e2e replay: no network access to {h}")
        return real_getaddrinfo(host, *args, **kwargs)

    def connect(self: socket.socket, address: Any) -> Any:
        if self.family in (socket.AF_INET, socket.AF_INET6):
            h = str(address[0])
            if h not in _LOCAL and not h.startswith("127."):
                _note_blocked(h)
                raise ConnectionRefusedError(f"e2e replay: no network access to {h}")
        return real_connect(self, address)

    socket.getaddrinfo = getaddrinfo  # type: ignore[assignment]
    socket.socket.connect = connect  # type: ignore[method-assign]


def _patch_backend() -> None:
    from src.modules.llm import registry

    from .backend import ReplayBackend

    def get_backend(settings: Any, name: str | None = None, model: str | None = None) -> Any:
        backend = name or settings.llm_backend
        return ReplayBackend(backend=backend, model=model or settings.default_model_for(backend))

    registry.get_backend = get_backend  # type: ignore[assignment]


def _patch_zenodo(base: str) -> None:
    from src.core import zenodo as deposit
    from src.modules.data import zenodo as records

    base = base.rstrip("/")
    deposit.ZENODO_URL = base
    deposit.ZENODO_SANDBOX_URL = base + "/sandbox"
    try:
        from src.core.pipeline import preregistration

        preregistration.ZENODO_URL = base  # imported by name there
    except ImportError:
        pass

    real = records.ZenodoClient

    class FakeZenodoClient(real):  # type: ignore[misc, valid-type]
        def __init__(self, api_root: str = base + "/api", **kw: Any) -> None:
            kw.setdefault("delay", 0.0)
            super().__init__(api_root, **kw)

    records.ZenodoClient = FakeZenodoClient  # type: ignore[misc]
    records.API_ROOT = base + "/api"


class RecordedDocker:
    """Answers like Docker; each entry point writes the files the recorded run wrote.

    The recorded run's ``sandbox_log.json`` gives the environment (installed
    packages, platform, package snapshot); ``files/sandbox/run/`` holds the
    output files, which an entry point writes when its ``produces`` names them.
    """

    def __init__(self, scenario_root: Path) -> None:
        self.root = scenario_root
        sb = json.loads((scenario_root / "scenario.json").read_text(encoding="utf-8")).get("sandbox") or {}
        self.installed: dict[str, str] = sb.get("installed") or {}
        self.platform: str = sb.get("platform") or "aarch64-unknown-linux-gnu"
        self.repos: str = sb.get("repos") or ""
        self.digest: str = sb.get("image_digest") or "rocker/r-ver@sha256:replay"
        self.images: set[str] = set()
        self.calls: list[list[str]] = []

    def _installed_block(self) -> bytes:
        lines = [f"{k}=={v}" for k, v in sorted(self.installed.items())]
        return ("E2ER-INSTALLED-BEGIN\n" + "\n".join(lines) + "\nE2ER-INSTALLED-END\n").encode()

    def __call__(self, argv: list[str], capture_output: bool = True, timeout: Any = None, **kw: Any) -> Any:
        self.calls.append(list(argv))
        ok = subprocess.CompletedProcess(argv, 0, b"", b"")
        sub = argv[1] if len(argv) > 1 else ""
        if argv[0] != "docker":
            raise AssertionError(f"the replay sandbox runs only docker, not {argv[0]}")
        if sub == "info":
            return ok
        if sub == "image" and len(argv) > 2 and argv[2] == "inspect":
            if "--format" in argv:
                return subprocess.CompletedProcess(argv, 0, json.dumps([self.digest]).encode(), b"")
            return ok if argv[-1] in self.images else subprocess.CompletedProcess(argv, 1, b"", b"")
        if sub in ("pull", "commit"):
            self.images.add(argv[-1])
            return ok
        if sub == "rm":
            return ok
        if sub == "run" and "--rm" not in argv:  # install phase
            out = (f"E2ER-SNAPSHOT-URL {self.repos}\n" if self.repos else "").encode() + self._installed_block()
            return subprocess.CompletedProcess(argv, 0, out, b"")
        if sub == "run" and "E2ER-INSTALLED-BEGIN" in argv[-1]:  # environment probe
            probe = (
                (f"E2ER-REPOS {self.repos}\n" if self.repos else "").encode()
                + f"E2ER-PLATFORM {self.platform}\n".encode()
                + self._installed_block()
            )
            return subprocess.CompletedProcess(argv, 0, probe, b"")
        if sub == "run":
            return self._entry_point(argv)
        raise AssertionError(f"unexpected docker call {argv}")

    def _entry_point(self, argv: list[str]) -> Any:
        # run_argv mounts the run folder; find it and the entry point's script.
        run_dir = None
        for i, a in enumerate(argv):
            if a in ("-v", "--mount") and i + 1 < len(argv):
                spec = argv[i + 1]
                for part in spec.split(","):
                    if part.startswith(("source=", "src=")) and part.rstrip("/").endswith("sandbox/run"):
                        run_dir = Path(part.split("=", 1)[1])
                if ":" in spec and spec.split(":", 1)[0].rstrip("/").endswith("sandbox/run"):
                    run_dir = Path(spec.split(":", 1)[0])
        if run_dir is None:
            raise AssertionError(f"replay sandbox: cannot find the run folder in {argv}")
        produced = 0
        src_root = self.root / "files" / "sandbox" / "run"
        script = argv[-1]
        for rel in self._produces(script):
            src = src_root / rel
            if src.is_file():
                dest = run_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists():
                    dest.chmod(0o644)
                dest.write_bytes(src.read_bytes())
                produced += 1
        return subprocess.CompletedProcess(argv, 0, f"replay: wrote {produced} file(s)\n".encode(), b"")

    def _produces(self, script: str) -> list[str]:
        sc = json.loads((self.root / "scenario.json").read_text(encoding="utf-8"))
        for ep in (sc.get("sandbox") or {}).get("entry_points") or []:
            if ep.get("script") == script:
                return list(ep.get("produces") or [])
        return []


def _patch_sandbox(scenario_root: Path) -> None:
    from src.core.pipeline import sandbox

    real = sandbox.run_sandbox
    docker = RecordedDocker(scenario_root)

    @functools.wraps(real)
    def run_sandbox(workspace: Path, **settings: Any) -> Any:
        settings.pop("runner", None)
        settings.pop("docker", None)
        return real(workspace, runner=docker, docker="docker", **settings)

    sandbox.run_sandbox = run_sandbox  # type: ignore[assignment]


def install() -> None:
    """Apply the replay level to this process (see module docstring)."""
    _guard_network()
    if os.environ.get("E2ER_REPLAY_SCENARIO"):
        from .backend import scenario_dir

        _patch_backend()
        root = scenario_dir(os.environ["E2ER_REPLAY_SCENARIO"])
        if json.loads((root / "scenario.json").read_text(encoding="utf-8")).get("sandbox"):
            _patch_sandbox(root)
    if os.environ.get(ENV_ZENODO):
        _patch_zenodo(os.environ[ENV_ZENODO])
