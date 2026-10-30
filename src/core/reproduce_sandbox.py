"""``e2er reproduce`` in Docker: someone else's code runs in a container, not as the user.

The same container rules as the replication template's sandbox (src/core/pipeline/sandbox.py),
for the steps of a study's ``reproduce.json``:

1. **install** (network on unless the package brings its wheels; none of the study's code is
   mounted). A container from ``python:<version>-slim`` makes a virtual environment at
   ``/opt/study-venv`` and installs the study's requirements file into it (mounted read-only,
   nothing else of the study): from wheels only (``--only-binary=:all:``), and only when a
   package has no wheel, from its source package, still inside this container. e2er's network
   guard is put into that environment (it reports the connections Python makes; the protection
   is ``--network none``). For the steps that call ``e2er-data``, e2er's own dependencies go
   into a second environment at ``/opt/e2er-venv``. The container is committed as a local image
   (``e2er-reproduce:<hash>``), reused when the same requirements come again.

2. **steps** (``--network none``; a step that loads inputs again gets the network after its own
   question). Each step runs in its own container, in the run folder (the only writable mount,
   at ``/work/run``), as this computer's user id, with a read-only root file system, all
   capabilities dropped, no privilege escalation, CPU, memory, process and time limits, and
   ``HOME=/tmp``. No folder of this computer's user is mounted, no API key or token is passed;
   e2er's own code is mounted read-only at ``/opt/e2er-src`` for ``e2er-data``.
"""

from __future__ import annotations

import hashlib
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .pipeline.sandbox import Limits, _docker_up, _image_present, _installed, _kill, docker_binary

RUN_MOUNT = "/work/run"
E2ER_MOUNT = "/opt/e2er-src"
STUDY_VENV = "/opt/study-venv"
E2ER_VENV = "/opt/e2er-venv"
E2ER_BIN = "/opt/e2er-bin"
_REQ_MOUNT = "/e2er-install/requirements.txt"
_WHEELS_MOUNT = "/e2er-install/wheels"
_GUARD_MOUNT = "/e2er-install/e2er_reproduce_netguard.py"
_PYTHON = re.compile(r"^3\.\d{1,2}$")
_PY_PROBE = f"{STUDY_VENV}/bin/python -c 'import sys; print(\"E2ER-PYTHON\", sys.version.split()[0])'"

Runner = Any


@dataclass
class Box:
    """A built environment image and how steps run in it."""

    docker: str
    image: str
    base: str
    python: str
    #: e2er-data is available inside (Python 3.11 or newer, e2er's dependencies installed).
    e2er: bool
    limits: Limits = field(default_factory=Limits)
    #: Whether any package was built from its source package (inside the install container).
    built_from_source: bool = False


def available(runner: Runner = subprocess.run) -> tuple[str | None, str]:
    """(the docker command, "") when Docker answers; (None, why not) otherwise."""
    docker = docker_binary()
    if docker is None:
        return None, "Docker is not installed"
    down = _docker_up(runner, docker)
    if down:
        return None, down
    if _engine_os(runner, docker) == "windows":
        # Docker Desktop on Windows in its Windows-containers mode (and GitHub's Windows runners) answers, but
        # cannot start the python:<version>-slim Linux image the sandbox runs in.
        return None, (
            "Docker runs Windows containers on this computer, and the sandbox needs Linux containers: in Docker "
            'Desktop choose "Switch to Linux containers"'
        )
    return docker, ""


def _engine_os(runner: Runner, docker: str) -> str:
    """The containers the Docker engine runs: ``linux`` or ``windows`` (empty when Docker does not say)."""
    try:
        cp = runner([docker, "info", "--format", "{{.OSType}}"], capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    out = cp.stdout.decode("utf-8", "replace") if isinstance(cp.stdout, bytes) else (cp.stdout or "")
    return out.strip().lower() if cp.returncode == 0 else ""


def python_version(recipe: dict[str, Any]) -> str:
    """The Python the study asks for (``3.12``), else the one e2er runs on."""
    wanted = str(recipe.get("python") or "").strip()
    if _PYTHON.match(wanted):
        return wanted
    return f"{sys.version_info.major}.{sys.version_info.minor}"


def e2er_requirements() -> list[str]:
    """e2er's own dependencies (without extras), for e2er-data inside the container."""
    try:
        from importlib.metadata import requires

        reqs = requires("e2er") or []
    except Exception:  # noqa: BLE001 — a checkout without metadata: no e2er-data inside
        return []
    return sorted(r for r in reqs if "extra ==" not in r and "extra==" not in r)


def needs_e2er_data(folder: Path, recipe: dict[str, Any]) -> bool:
    """Does a step or a script of the study call e2er-data? (Only then e2er's dependencies are installed.)"""
    from .reproduce import step_argv

    steps = [st for st in recipe.get("steps") or [] if isinstance(st, dict)]
    if any("e2er-data" in a for st in steps for a in step_argv(st)):
        return True
    for f in folder.rglob("*"):
        if f.suffix.lower() not in (".py", ".sh", ".r", ".jl", ".do") or f.is_symlink() or not f.is_file():
            continue
        try:
            if f.stat().st_size > 2_000_000:
                continue
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "e2er-data" in text or "E2ER_DATA" in text:
            return True
    return False


def e2er_source() -> Path:
    """The folder of e2er's own package (``src``), mounted read-only for e2er-data."""
    return Path(__file__).resolve().parents[1]


_SHIM = (
    "#!/bin/sh\n"
    f'exec {E2ER_VENV}/bin/python -c \'import sys; sys.path.insert(0, "{E2ER_MOUNT}"); '
    'from src.modules.data.cli import main; sys.exit(main())\' "$@"\n'
)


def install_script(*, wheels: bool, e2er_reqs: list[str]) -> str:
    """The install container's script: the study's environment, the guard, e2er-data's environment."""
    offline = f" --no-index --find-links {_WHEELS_MOUNT}" if wheels else ""
    pip = f"{STUDY_VENV}/bin/pip install --no-cache-dir --disable-pip-version-check{offline}"
    lines = [
        "set -e",
        f"python -m venv {STUDY_VENV}",
        f"{pip} --only-binary=:all: -r {_REQ_MOUNT} || {{ echo E2ER-SOURCE-BUILD; {pip} -r {_REQ_MOUNT}; }}",
        f"site=$({STUDY_VENV}/bin/python -c \"import sysconfig; print(sysconfig.get_path('purelib'))\")",
        f'cp {_GUARD_MOUNT} "$site/e2er_reproduce_netguard.py"',
        'echo "import e2er_reproduce_netguard" > "$site/e2er_reproduce_netguard.pth"',
    ]
    if e2er_reqs:
        deps = " ".join(shlex.quote(r) for r in e2er_reqs)
        lines += [
            f"python -m venv {E2ER_VENV}",
            f"{E2ER_VENV}/bin/pip install --no-cache-dir --disable-pip-version-check --only-binary=:all: {deps}",
            f"mkdir -p {E2ER_BIN}",
            f"printf %s {shlex.quote(_SHIM)} > {E2ER_BIN}/e2er-data",
            f"chmod 755 {E2ER_BIN}/e2er-data",
        ]
    lines += [
        "echo E2ER-INSTALLED-BEGIN",
        f"{STUDY_VENV}/bin/pip list --format=freeze --disable-pip-version-check",
        "echo E2ER-INSTALLED-END",
        _PY_PROBE,
    ]
    return "\n".join(lines)


def install_argv(
    docker: str, base: str, name: str, script: str, requirements: Path, wheels: Path | None, limits: Limits
) -> list[str]:
    """The install container: the requirements (and wheels) read-only, nothing else of the study."""
    guard = Path(__file__).with_name("reproduce_netguard.py")
    argv = [
        docker, "run", "--name", name,
        f"--cpus={limits.cpus}", f"--memory={limits.memory_gb}g", f"--memory-swap={limits.memory_gb}g",
        f"--pids-limit={limits.pids}", "--security-opt=no-new-privileges",
    ]  # fmt: skip
    if wheels is not None:
        argv += ["--network", "none"]
    argv += [
        "--mount", f"type=bind,source={requirements.resolve()},target={_REQ_MOUNT},readonly",
        "--mount", f"type=bind,source={guard.resolve()},target={_GUARD_MOUNT},readonly",
    ]  # fmt: skip
    if wheels is not None:
        argv += ["--mount", f"type=bind,source={wheels.resolve()},target={_WHEELS_MOUNT},readonly"]
    return [*argv, base, "sh", "-c", script]


def _user() -> str:
    """This computer's user id inside the container (files the steps write stay the user's), never root."""
    if hasattr(os, "getuid") and os.getuid() != 0:
        return f"{os.getuid()}:{os.getgid()}"
    return Limits.user


def run_argv(box: Box, name: str, run_dir: Path, argv: list[str], env: dict[str, str], network: bool) -> list[str]:
    """One step's container: the run folder is the only writable mount; no network unless ``network``."""
    lim = box.limits
    out = [
        box.docker, "run", "--rm", "--name", name,
        "--network", "bridge" if network else "none",
        f"--cpus={lim.cpus}", f"--memory={lim.memory_gb}g", f"--memory-swap={lim.memory_gb}g",
        f"--pids-limit={lim.pids}", "--user", _user(),
        "--cap-drop=ALL", "--security-opt=no-new-privileges", "--read-only",
        "--tmpfs", f"/tmp:rw,exec,size={lim.tmp_gb}g",
        "--mount", f"type=bind,source={run_dir.resolve()},target={RUN_MOUNT}",
    ]  # fmt: skip
    if box.e2er:
        out += ["--mount", f"type=bind,source={e2er_source()},target={E2ER_MOUNT}/src,readonly"]
    for k, v in sorted(env.items()):
        out += ["-e", f"{k}={v}"]
    return [*out, "-w", RUN_MOUNT, box.image, *argv]


def step_env(box: Box, run_dir: Path) -> dict[str, str]:
    """The steps' environment inside the container: no key, no token, no setting of this computer."""
    path = [f"{STUDY_VENV}/bin"] + ([E2ER_BIN] if box.e2er else []) + ["/usr/local/bin", "/usr/bin", "/bin"]
    env = {
        "PATH": ":".join(path),
        "HOME": "/tmp",
        "LANG": "C.UTF-8",
        "PYTHON_COLORS": "0",
        "VIRTUAL_ENV": STUDY_VENV,
        "E2ER_PAPER_ID": run_dir.name,
        "E2ER_WORKSPACE": RUN_MOUNT,
        "E2ER_WORKSPACE_ROOT": "/work",
        "E2ER_PROJECT_DIR": "/tmp",
        "E2ER_SPECIALIST": "reproduce",
        "E2ER_REPRODUCE": "1",
    }
    if box.e2er:
        env["E2ER_DATA"] = f"{E2ER_BIN}/e2er-data"
    return env


def in_box(path: Path, run_dir: Path) -> str:
    """A path in the run folder as a step in the container sees it."""
    return f"{RUN_MOUNT}/{path.resolve().relative_to(run_dir.resolve()).as_posix()}"


def prepare(
    run_dir: Path,
    recipe: dict[str, Any],
    folder: Path,
    logs: Path,
    *,
    docker: str,
    runner: Runner = subprocess.run,
    limits: Limits | None = None,
) -> tuple[Box, dict[str, Any]]:
    """Build (or reuse) the environment image; (the box, what was installed). RecipeError when it fails."""
    from .reproduce import RecipeError

    limits = limits or Limits()
    version = python_version(recipe)
    base = f"python:{version}-slim"
    requirements = (folder / str(recipe["requirements"])).resolve()
    wheelhouse = recipe.get("wheelhouse")
    wheels = (folder / str(wheelhouse)).resolve() if wheelhouse else None
    minor = int(version.split(".")[1])
    wants_e2er = needs_e2er_data(folder, recipe)
    e2er_reqs = e2er_requirements() if minor >= 11 and wants_e2er else []
    script = install_script(wheels=wheels is not None, e2er_reqs=e2er_reqs)
    digest = hashlib.sha256()
    for part in (
        base,
        script,
        requirements.read_bytes(),
        Path(__file__).with_name("reproduce_netguard.py").read_bytes(),
    ):
        digest.update(part if isinstance(part, bytes) else part.encode())
        digest.update(b"\0")
    if wheels is not None:
        for w in sorted(wheels.rglob("*")):
            if w.is_file():
                digest.update(w.name.encode() + b"\0" + hashlib.sha256(w.read_bytes()).digest())
    tag = f"e2er-reproduce:{digest.hexdigest()[:16]}"
    info: dict[str, Any] = {"sandbox": {"image": tag, "base": base, "docker": docker}}
    built_from_source = False
    if not _image_present(runner, docker, tag):
        if not _image_present(runner, docker, base):
            pull = _call(runner, [docker, "pull", base], limits.install_timeout_minutes * 60, logs / "sandbox-pull.log")
            if pull[0] != 0:
                raise RecipeError(f"Docker could not pull {base}: {pull[1]}")
        name = f"e2er-reproduce-install-{digest.hexdigest()[:8]}-{os.getpid()}"
        _kill(runner, docker, name)
        argv = install_argv(docker, base, name, script, requirements, wheels, limits)
        code, tail, out = _call_out(runner, argv, limits.install_timeout_minutes * 60, logs / "environment-install.log")
        if code != 0:
            _kill(runner, docker, name)
            raise RecipeError(f"could not install {recipe['requirements']} in the Docker sandbox: {tail}")
        committed = runner([docker, "commit", name, tag], capture_output=True, timeout=600)
        _kill(runner, docker, name)
        if committed.returncode != 0:
            raise RecipeError("the sandbox's environment could not be committed as a Docker image")
        built_from_source = "E2ER-SOURCE-BUILD" in out
        installed = _installed(out)
        py = _marker(out, "E2ER-PYTHON") or version
    else:
        probe = [
            docker, "run", "--rm", "--network", "none", tag, "sh", "-c",
            f"echo E2ER-INSTALLED-BEGIN; {STUDY_VENV}/bin/pip list --format=freeze --disable-pip-version-check; "
            f"echo E2ER-INSTALLED-END; {_PY_PROBE}",
        ]  # fmt: skip
        code, _tail, out = _call_out(runner, probe, 300, logs / "environment-probe.log")
        installed = _installed(out)
        py = _marker(out, "E2ER-PYTHON") or version
        info["sandbox"]["reused"] = True
    box = Box(
        docker=docker, image=tag, base=base, python=py, e2er=bool(e2er_reqs), limits=limits,
        built_from_source=built_from_source,
    )  # fmt: skip
    how = f"pip in a Docker sandbox ({base}"
    how += ", packages from the package's wheels, offline" if wheels is not None else ""
    how += "; a package without a wheel was built from source inside it" if built_from_source else ""
    info.update(
        python=py,
        packages={k: v for k, v in installed.items() if k not in ("pip", "setuptools", "wheel")},
        installer=how + ")",
        network_guard=True,
    )
    if wants_e2er and not box.e2er:
        info["sandbox"]["e2er_data"] = (
            f"not available inside (e2er needs Python 3.11 or newer, the study asks {version})"
        )
    return box, info


def step_runner(box: Box, run_dir: Path, runner: Runner = subprocess.run) -> Any:
    """run_steps' runner: each step in its own container."""

    def run(argv: list[str], env: dict[str, str], timeout: float, log: Path, network: bool, i: int):
        if argv and argv[0] in ("python", "python3") or (argv and argv[0].endswith("/python")):
            argv = [f"{STUDY_VENV}/bin/python", *argv[1:]]
        name = f"e2er-reproduce-step-{os.getpid()}-{i}-{int(time.time())}"
        full = run_argv(box, name, run_dir, argv, env, network)
        code, tail, _ = _call_out(runner, full, timeout, log, kill=(box.docker, name))
        return code, tail

    return run


def _marker(text: str, name: str) -> str:
    for line in text.splitlines():
        if line.startswith(f"{name} "):
            return line[len(name) + 1 :].strip()
    return ""


def _call(runner: Runner, argv: list[str], timeout: float, log: Path) -> tuple[int, str]:
    code, tail, _ = _call_out(runner, argv, timeout, log)
    return code, tail


def _call_out(
    runner: Runner, argv: list[str], timeout: float, log: Path, kill: tuple[str, str] | None = None
) -> tuple[int, str, str]:
    """(exit code, last lines, full output) of a docker command; its output goes to ``log``."""
    try:
        cp = runner(argv, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        if kill:
            _kill(runner, *kill)
        log.write_text(f"stopped after {timeout:.0f} s\n", encoding="utf-8")
        return 124, f"stopped after {timeout / 60:.0f} minutes", ""
    except OSError as e:
        log.write_text(f"{e}\n", encoding="utf-8")
        return 127, str(e), ""
    out = cp.stdout.decode("utf-8", "replace") if isinstance(cp.stdout, bytes) else (cp.stdout or "")
    err = cp.stderr.decode("utf-8", "replace") if isinstance(cp.stderr, bytes) else (cp.stderr or "")
    log.write_text(out + err, encoding="utf-8")
    tail = "\n".join((err + out).strip().splitlines()[-6:])
    return cp.returncode, tail, out
