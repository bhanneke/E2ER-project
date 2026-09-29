"""The `sandbox_run` step: run a replication package's entry points inside Docker.

The package's code is run only here, only inside a container, and never with
network access. Two phases:

  1. **install** (network on, package NOT mounted). A container from the
     plan's pinned official image (``rocker/r-ver:X.Y.Z`` or
     ``python:X.Y-slim``) installs the system and language packages the plan
     lists, prints what got installed, and is committed as a local image.
     Only package managers run in this phase; none of the package's code does,
     so nothing the package contains ever sees the network. The committed image
     is reused on resume (its tag is a hash of the image and install script).

  2. **run** (``--network none``). The package is copied into a separate
     output folder (``sandbox/run/``); the original stays read-only on disk and
     is also mounted read-only at ``/work/package``. Each entry point runs in
     its own container, in order, working in the copy at ``/work/run``, as an
     unprivileged user, with CPU, memory, process and time limits, a read-only
     root file system, all capabilities dropped and no privilege escalation. The home directory is
     never mounted; the only mounts are the package (read-only) and the output
     folder.

Everything is logged to ``sandbox_log.json``: the exact ``docker`` commands,
exit codes, durations, the tail of stdout and stderr (full logs in
``sandbox/logs/``), the image digest, what got installed, and the SHA-256 of
every file the run wrote or changed. After the run the original package is
re-hashed; a changed byte fails the step.

The step fails only when the sandbox itself cannot work (no Docker, no valid
plan, image not available, package modified). A script that exits non-zero is
a result — it becomes "could not be run" in the reproduction report — not a
failure of the step.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ...logging_config import get_logger
from .replication import (
    MANIFEST_FILE,
    PACKAGE_DIR,
    CheckResult,
    hash_tree,
    load_plan,
    make_writable,
    sha256_file,
    validate_plan,
)

logger = get_logger(__name__)

SANDBOX_DIR = "sandbox"
LOG_FILE = "sandbox_log.json"
RUN_MOUNT = "/work/run"
PACKAGE_MOUNT = "/work/package"
_TAIL = 4000
_COPY_STAMP = 946_684_800  # 2000-01-01T00:00:00Z
_DOCKER_CANDIDATES = ("docker", "/usr/local/bin/docker", "/Applications/Docker.app/Contents/Resources/bin/docker")

Runner = Callable[..., subprocess.CompletedProcess]


@dataclass(frozen=True)
class Limits:
    cpus: int = 2
    memory_gb: int = 4
    pids: int = 512
    timeout_minutes: int = 60
    install_timeout_minutes: int = 45
    tmp_gb: int = 2
    #: The run phase runs as an unprivileged user, never as root.
    user: str = "1000:1000"


def docker_binary() -> str | None:
    for c in _DOCKER_CANDIDATES:
        found = shutil.which(c) if "/" not in c else (c if Path(c).is_file() else None)
        if found:
            return found
    return None


def _tail(text: str | bytes | None) -> str:
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    text = text or ""
    return text if len(text) <= _TAIL else "…" + text[-_TAIL:]


# ── command construction (pure; pinned by tests without Docker) ─────────────


def install_script(plan: dict[str, Any], snapshot_date: str | None = None) -> str:
    """The shell script of the install phase, from validated names only.

    ``snapshot_date`` (YYYY-MM-DD) installs the packages as they were on that
    day: for R from Posit Package Manager's dated CRAN snapshot (the image's
    own p3m URL with ``/latest`` replaced by the date, written to
    ``Rprofile.site`` so it is also the repository inside the run), for Python
    with pip's ``--uploaded-prior-to``. None installs the newest. Versions the
    plan declares win either way: R installs them with
    ``remotes::install_version`` when the snapshot holds another, Python pins
    them with ``==``.
    """
    env = plan.get("environment") or {}
    lines = ["set -e"]
    system = [str(s) for s in env.get("system_packages") or []]
    if system:
        lines.append(
            "export DEBIAN_FRONTEND=noninteractive && apt-get update && "
            f"apt-get install -y --no-install-recommends {' '.join(shlex.quote(s) for s in system)} && "
            "rm -rf /var/lib/apt/lists/*"
        )
    pkgs = [p for p in env.get("packages") or [] if isinstance(p, dict) and p.get("name")]
    declared = [p for p in pkgs if p.get("version")]
    if plan.get("language") == "R":
        if snapshot_date:
            lines.append(
                'Rscript -e \'r <- getOption("repos")[["CRAN"]]; '
                'pat <- "/(latest|[0-9]{4}-[0-9]{2}-[0-9]{2})/?$"; '
                f'url <- if (grepl("p3m.dev|packagemanager", r) && grepl(pat, r)) sub(pat, "/{snapshot_date}", r) '
                f'else "https://p3m.dev/cran/{snapshot_date}"; '
                'cat(sprintf("options(repos = c(CRAN = \\"%s\\"))\\n", url), '
                'file = file.path(R.home("etc"), "Rprofile.site"), append = TRUE); '
                'cat("E2ER-SNAPSHOT-URL ", url, "\\n", sep = "")\''
            )
        if pkgs:
            names = ", ".join(f'"{p["name"]}"' for p in pkgs)
            lines.append(
                "Rscript -e 'pk <- c("
                + names
                + "); install.packages(pk, Ncpus = 2); "
                + "miss <- setdiff(pk, rownames(installed.packages())); "
                + 'if (length(miss)) { message("NOT INSTALLED: ", paste(miss, collapse = " ")); quit(status = 1) }\''
            )
        if declared:
            want = ", ".join(f'"{p["name"]}" = "{p["version"]}"' for p in declared)
            lines.append(
                "Rscript -e 'want <- c("
                + want
                + '); have <- installed.packages()[, "Version"]; '
                + "off <- names(want)[!(names(want) %in% names(have)) | have[names(want)] != want]; "
                + 'if (length(off)) { if (!requireNamespace("remotes", quietly = TRUE)) install.packages("remotes"); '
                + 'for (p in off) tryCatch(remotes::install_version(p, version = want[[p]], upgrade = "never", '
                + 'repos = c(getOption("repos"), ARCHIVE = "https://cloud.r-project.org")), '
                + 'error = function(e) message("E2ER-VERSION-FAILED ", p, " ", conditionMessage(e))) }\''
            )
    else:
        if pkgs:
            specs = " ".join(
                shlex.quote(f"{p['name']}=={p['version']}" if p.get("version") else str(p["name"])) for p in pkgs
            )
            if snapshot_date:
                cutoff = f"{snapshot_date}T23:59:59Z"
                lines.append('pip install --no-cache-dir --upgrade "pip>=26"')
                lines.append(f"echo E2ER-SNAPSHOT-URL pypi --uploaded-prior-to {cutoff}")
                lines.append(f"pip install --no-cache-dir --uploaded-prior-to {cutoff} {specs}")
            else:
                lines.append(f"pip install --no-cache-dir {specs}")
    return "\n".join(lines)


def environment_script(language: str) -> str:
    """Printed by a no-network container of the committed image: repository, platform, every installed version."""
    if language == "R":
        return (
            'Rscript -e \'cat("E2ER-REPOS ", getOption("repos")[["CRAN"]], "\\n", sep = ""); '
            'cat("E2ER-PLATFORM ", R.version$platform, "\\n", sep = ""); '
            'cat("E2ER-INSTALLED-BEGIN\\n"); ip <- installed.packages()[, c("Package", "Version")]; '
            "ip <- ip[!duplicated(ip[, 1]), , drop = FALSE]; "
            'cat(paste(ip[, 1], ip[, 2], sep = "=="), sep = "\\n"); cat("\\nE2ER-INSTALLED-END\\n")\''
        )
    return (
        "python -c 'import platform, sys; print(\"E2ER-PLATFORM\", platform.machine(), sys.version.split()[0])' && "
        "echo E2ER-INSTALLED-BEGIN && pip list --format=freeze && echo E2ER-INSTALLED-END"
    )


def env_tag(plan: dict[str, Any], snapshot_date: str | None = None) -> str:
    """Local tag of the committed environment: a hash of the image and the install script."""
    image = str((plan.get("environment") or {}).get("image"))
    h = hashlib.sha256(f"{image}\n{install_script(plan, snapshot_date)}".encode()).hexdigest()[:16]
    return f"e2er-sandbox:{h}"


def resolve_snapshot(setting: str, manifest: dict[str, Any]) -> tuple[str | None, str]:
    """(date or None for newest, how it was chosen) from the template's `snapshot` setting."""
    if setting == "latest":
        return None, "latest (the image's default repository)"
    if setting == "package-date":
        date = str(manifest.get("publication_date") or "")[:10]
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
            raise ValueError("snapshot = 'package-date', but the record has no publication date")
        return date, f"the Zenodo record's publication date ({date})"
    if re.match(r"^\d{4}-\d{2}-\d{2}$", setting):
        return setting, f"the date set in the template ({setting})"
    raise ValueError(f"unknown snapshot setting {setting!r}")


def _marker(stdout: str, name: str) -> str:
    for line in stdout.splitlines():
        if line.startswith(f"{name} "):
            return line[len(name) + 1 :].strip()
    return ""


def install_argv(docker: str, image: str, name: str, script: str, limits: Limits) -> list[str]:
    """Phase 1: network on, no mounts at all, bounded, no privilege escalation."""
    return [
        docker,
        "run",
        "--name",
        name,
        f"--cpus={limits.cpus}",
        f"--memory={limits.memory_gb}g",
        f"--memory-swap={limits.memory_gb}g",
        f"--pids-limit={limits.pids}",
        "--security-opt=no-new-privileges",
        image,
        "sh",
        "-c",
        script,
    ]


def run_argv(
    docker: str,
    image: str,
    name: str,
    package_dir: Path,
    run_dir: Path,
    entry: dict[str, Any],
    limits: Limits,
) -> list[str]:
    """Phase 2: one entry point, no network, package read-only, output folder the only writable mount."""
    cwd = str(entry.get("cwd") or ".").strip("/")
    workdir = RUN_MOUNT if cwd in ("", ".") else f"{RUN_MOUNT}/{cwd}"
    return [
        docker,
        "run",
        "--rm",
        "--name",
        name,
        "--network",
        "none",
        f"--cpus={limits.cpus}",
        f"--memory={limits.memory_gb}g",
        f"--memory-swap={limits.memory_gb}g",
        f"--pids-limit={limits.pids}",
        "--user",
        limits.user,
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--read-only",
        "--tmpfs",
        f"/tmp:rw,exec,size={limits.tmp_gb}g",
        "--mount",
        f"type=bind,source={package_dir.resolve()},target={PACKAGE_MOUNT},readonly",
        "--mount",
        f"type=bind,source={run_dir.resolve()},target={RUN_MOUNT}",
        "-e",
        "HOME=/tmp",
        "-e",
        f"OMP_NUM_THREADS={limits.cpus}",
        "-w",
        workdir,
        image,
        *[str(c) for c in entry["command"]],
    ]


# ── execution ────────────────────────────────────────────────────────────────


def _exec(runner: Runner, argv: list[str], timeout: float, log_base: Path) -> dict[str, Any]:
    t0 = time.monotonic()
    timed_out = False
    try:
        cp = runner(argv, capture_output=True, timeout=timeout)
        code, out, err = cp.returncode, cp.stdout, cp.stderr
    except subprocess.TimeoutExpired as e:
        timed_out, code, out, err = True, None, e.stdout, e.stderr
    duration = round(time.monotonic() - t0, 1)
    out_s = out.decode("utf-8", "replace") if isinstance(out, bytes) else (out or "")
    err_s = err.decode("utf-8", "replace") if isinstance(err, bytes) else (err or "")
    log_base.parent.mkdir(parents=True, exist_ok=True)
    log_base.with_suffix(".stdout.log").write_text(out_s, encoding="utf-8")
    log_base.with_suffix(".stderr.log").write_text(err_s, encoding="utf-8")
    return {
        "exit_code": code,
        "timed_out": timed_out,
        "duration_seconds": duration,
        "stdout_tail": _tail(out_s),
        "stderr_tail": _tail(err_s),
        "stdout_log": log_base.with_suffix(".stdout.log").as_posix(),
        "stderr_log": log_base.with_suffix(".stderr.log").as_posix(),
    }


def _installed(stdout: str) -> dict[str, str]:
    if "E2ER-INSTALLED-BEGIN" not in stdout:
        return {}
    block = stdout.split("E2ER-INSTALLED-BEGIN", 1)[1].split("E2ER-INSTALLED-END", 1)[0]
    out: dict[str, str] = {}
    for line in block.splitlines():
        name, sep, version = line.strip().partition("==")
        if sep and name:
            out[name] = version
    return out


def _docker_up(runner: Runner, docker: str) -> str | None:
    try:
        cp = runner([docker, "info", "--format", "{{.ServerVersion}}"], capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"Docker is not available: {e}"
    if cp.returncode != 0:
        return "Docker is not running (docker info failed); start Docker Desktop, then resume"
    return None


def _image_present(runner: Runner, docker: str, image: str) -> bool:
    cp = runner([docker, "image", "inspect", image], capture_output=True, timeout=60)
    return cp.returncode == 0


def _digest(runner: Runner, docker: str, image: str) -> str:
    cp = runner(
        [docker, "image", "inspect", "--format", "{{json .RepoDigests}}", image], capture_output=True, timeout=60
    )
    if cp.returncode != 0:
        return ""
    try:
        raw = cp.stdout.decode() if isinstance(cp.stdout, bytes) else cp.stdout
        digests = json.loads(raw or "[]")
        return digests[0] if digests else ""
    except ValueError:
        return ""


def _kill(runner: Runner, docker: str, name: str) -> None:
    try:
        runner([docker, "rm", "-f", name], capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        pass


def run_sandbox(
    workspace: Path,
    *,
    cpus: int = Limits.cpus,
    memory_gb: int = Limits.memory_gb,
    timeout_minutes: int = Limits.timeout_minutes,
    install_timeout_minutes: int = Limits.install_timeout_minutes,
    snapshot: str = "package-date",
    runner: Runner = subprocess.run,
    docker: str | None = None,
) -> CheckResult:
    workspace = Path(workspace)
    limits = Limits(
        cpus=int(cpus),
        memory_gb=int(memory_gb),
        timeout_minutes=int(timeout_minutes),
        install_timeout_minutes=int(install_timeout_minutes),
    )
    package = workspace / PACKAGE_DIR
    if not (workspace / MANIFEST_FILE).is_file() or not package.is_dir():
        return CheckResult(False, ("the package has not been fetched (package_manifest.json is missing)",))
    plan, why = load_plan(workspace)
    if plan is None:
        return CheckResult(False, (why,))
    errors = validate_plan(plan, package, workspace)
    if errors:
        return CheckResult(False, tuple(f"replication_plan.json: {e}" for e in errors[:15]))
    docker = docker or docker_binary()
    if docker is None:
        return CheckResult(False, ("the docker command is not installed",))
    down = _docker_up(runner, docker)
    if down:
        return CheckResult(False, (down,))

    manifest = json.loads((workspace / MANIFEST_FILE).read_text(encoding="utf-8"))
    recorded = {f["path"]: f["sha256"] for f in manifest.get("package_files") or []}
    try:
        snapshot_date, snapshot_basis = resolve_snapshot(snapshot, manifest)
    except ValueError as e:
        return CheckResult(False, (str(e),))
    image = plan["environment"]["image"]
    box = workspace / SANDBOX_DIR
    logs = box / "logs"
    run_dir = box / "run"
    stamp = hashlib.sha256(str(workspace).encode()).hexdigest()[:8]
    log: dict[str, Any] = {
        "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "image": image,
        "limits": limits.__dict__,
        "network": {"install": "default bridge, package not mounted", "run": "none"},
    }

    # pull the pinned image
    if not _image_present(runner, docker, image):
        pull = _exec(runner, [docker, "pull", image], limits.install_timeout_minutes * 60, logs / "pull")
        log["pull"] = {"argv": [docker, "pull", image], **pull}
        if pull["exit_code"] != 0:
            _write_log(workspace, log)
            return CheckResult(False, (f"the image {image} could not be pulled: {pull['stderr_tail'][-300:]}",))
    log["image_digest"] = _digest(runner, docker, image)

    # phase 1: install into a committed environment image
    tag = env_tag(plan, snapshot_date)
    script = install_script(plan, snapshot_date)
    install_out = ""
    if _image_present(runner, docker, tag):
        log["install"] = {"reused": tag, "script": script}
    else:
        name = f"e2er-install-{stamp}"
        _kill(runner, docker, name)
        argv = install_argv(docker, image, name, script, limits)
        res = _exec(runner, argv, limits.install_timeout_minutes * 60, logs / "install")
        if res["timed_out"]:
            _kill(runner, docker, name)
            _write_log(workspace, {**log, "install": {"argv": argv, **res}})
            return CheckResult(
                False, (f"installing the environment timed out after {limits.install_timeout_minutes} min",)
            )
        commit = runner([docker, "commit", name, tag], capture_output=True, timeout=600)
        _kill(runner, docker, name)
        log["install"] = {"argv": argv, "script": script, "committed": tag, **res}
        if commit.returncode != 0:
            _write_log(workspace, log)
            return CheckResult(False, ("the installed environment could not be committed as an image",))
        install_out = Path(res["stdout_log"]).read_text(encoding="utf-8") + Path(res["stderr_log"]).read_text(
            encoding="utf-8"
        )

    # what the committed environment actually holds, read from the image itself
    # (no network), whether it was just built or reused
    probe = _exec(
        runner,
        [docker, "run", "--rm", "--network", "none", tag, "sh", "-c", environment_script(plan["language"])],
        300,
        logs / "environment",
    )
    probe_out = Path(probe["stdout_log"]).read_text(encoding="utf-8")
    installed = _installed(probe_out)
    log["install"]["installed"] = installed
    log["install"]["platform"] = _marker(probe_out, "E2ER-PLATFORM")
    url = _marker(install_out, "E2ER-SNAPSHOT-URL") or (
        _marker(probe_out, "E2ER-REPOS") if plan["language"] == "R" else ""
    )
    log["snapshot"] = {
        "setting": snapshot,
        "date": snapshot_date,
        "basis": snapshot_basis,
        "url": url or ("https://pypi.org/simple" if snapshot_date is None else ""),
    }
    log["declared_versions"] = [
        {
            "name": p["name"],
            "declared": str(p["version"]),
            "installed": installed.get(p["name"]),
            "matches": installed.get(p["name"]) == str(p["version"]),
        }
        for p in plan["environment"].get("packages") or []
        if isinstance(p, dict) and p.get("version")
    ]
    failed_pins = [
        line.split(" ", 2)[1] for line in install_out.splitlines() if line.startswith("E2ER-VERSION-FAILED ")
    ]
    if failed_pins:
        log["install"]["declared_versions_not_installable"] = failed_pins

    # phase 2: run each entry point on a fresh copy of the package
    if run_dir.exists():
        make_writable(run_dir)
        shutil.rmtree(run_dir)
    shutil.copytree(package, run_dir, symlinks=False)
    make_writable(run_dir)
    # Stamp the copy with an old time, so a file the run rewrites — even with
    # identical bytes — is recognisable by its modification time, whatever the
    # clock skew between the host and Docker's VM.
    for f in run_dir.rglob("*"):
        if f.is_file() and not f.is_symlink():
            os.utime(f, (_COPY_STAMP, _COPY_STAMP))
    before = {p: v["sha256"] for p, v in hash_tree(run_dir).items()}
    runs: list[dict[str, Any]] = []
    for i, ep in enumerate(plan["entry_points"]):
        rec: dict[str, Any] = {"id": ep["id"], "command": ep["command"], "cwd": ep.get("cwd", ".")}
        if ep.get("needs_network"):
            rec.update(status="skipped", reason="needs network access, which the run phase does not have")
            runs.append(rec)
            continue
        name = f"e2er-run-{stamp}-{i}"
        _kill(runner, docker, name)
        argv = run_argv(docker, tag, name, package, run_dir, ep, limits)
        minutes = min(float(ep.get("timeout_minutes") or limits.timeout_minutes), float(limits.timeout_minutes))
        res = _exec(runner, argv, minutes * 60, logs / f"{i:02d}-{ep['id']}")
        if res["timed_out"]:
            _kill(runner, docker, name)
        status = "timed_out" if res["timed_out"] else ("ok" if res["exit_code"] == 0 else "failed")
        rec.update(argv=argv, status=status, **res)
        runs.append(rec)
        logger.info("sandbox %s: %s (exit %s, %.0fs)", ep["id"], status, res["exit_code"], res["duration_seconds"])
    log["runs"] = runs

    # what the run wrote, and whether the original package is intact
    outputs = []
    for rel, v in hash_tree(run_dir).items():
        mtime = (run_dir / rel).stat().st_mtime
        state = "new" if rel not in before else ("changed" if before[rel] != v["sha256"] else "unchanged")
        written = state != "unchanged" or mtime > _COPY_STAMP + 86_400
        if written:
            outputs.append(
                {
                    "path": rel,
                    "size": v["size"],
                    "sha256": v["sha256"],
                    "state": state,
                    "written_by_run": True,
                    "same_as_package": recorded.get(rel) == v["sha256"],
                }
            )
    log["outputs"] = outputs
    log["run_dir"] = run_dir.relative_to(workspace).as_posix()
    log["finished_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    changed = [p for p, d in recorded.items() if not (package / p).is_file() or sha256_file(package / p) != d]
    log["package_intact"] = not changed
    _write_log(workspace, log)
    if changed:
        return CheckResult(False, (f"the original package changed during the run: {', '.join(changed[:5])}",))
    counts = {s: sum(1 for r in runs if r["status"] == s) for s in ("ok", "failed", "timed_out", "skipped")}
    return CheckResult(
        True,
        notes=tuple(f"{r['id']}: {r['status']}" for r in runs if r["status"] != "ok")[:10],
        stats={"entry_points": len(runs), **counts, "files_written": len(outputs)},
    )


def _write_log(workspace: Path, log: dict[str, Any]) -> None:
    (workspace / LOG_FILE).write_text(json.dumps(log, indent=2, default=str) + "\n", encoding="utf-8")
