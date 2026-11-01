"""uv for the replay tests' `e2er reproduce` step: skipped on a machine without it, required on CI.

On a developer machine the step runs offline from uv's own cache and Pythons and is skipped when uv
is missing or the cache lacks a requirement. CI sets ``E2ER_REQUIRE_UV=1`` (tests.yml, release.yml,
which install uv): there the step runs online, and a missing uv or a failed install fails the test
instead of skipping it. Before 0.19 CI had no uv, so the four reproduce steps were skipped on every
push and nobody saw it.
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

#: Set on CI: a reproduce step that cannot run is a failure, not a skip.
REQUIRE_ENV = "E2ER_REQUIRE_UV"


def required() -> bool:
    return os.environ.get(REQUIRE_ENV, "").strip().lower() in {"1", "true", "yes"}


def _cannot(reason: str) -> None:
    if required():
        pytest.fail(f"{reason} ({REQUIRE_ENV} is set: CI installs uv, so the reproduce step must run)")
    pytest.skip(reason)


def reproduce_env() -> dict[str, str]:
    """The variables for `e2er reproduce` (offline from the real cache), or skip/fail without uv."""
    if shutil.which("uv") is None:
        _cannot("uv is not installed; e2er reproduce would install the requirements with pip from the network")
    if required():
        return {}  # CI: online, uv's own cache
    uv_dirs = {"UV_OFFLINE": "1"}
    for var, cmd in (("UV_CACHE_DIR", "cache"), ("UV_PYTHON_INSTALL_DIR", "python")):
        # The test's HOME is a fresh folder: point uv at the real cache and Pythons.
        found = subprocess.run(
            ["uv", cmd, "dir"],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            env={**os.environ, "NO_COLOR": "1"},
        )
        if found.returncode == 0 and found.stdout.strip():
            uv_dirs[var] = found.stdout.strip()
    return uv_dirs


def check_installed(stdout: str) -> None:
    """Skip (fail on CI) when reproduce could not install the requirements or the Python."""
    if "could not install" in stdout or "could not create the environment" in stdout:
        where = "online" if required() else "offline, from uv's cache"
        _cannot(f"the requirements or Python could not be installed ({where}): " + stdout[-400:])
