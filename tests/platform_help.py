"""What differs between Linux, macOS and Windows in the tests' own checks.

**Owner-only files.** On Linux and macOS e2er writes a file that holds a token or key with mode 0600
(and its folder 0700). Windows has no POSIX modes: ``os.chmod`` sets only the read-only flag, and
``stat`` reports 0o666 or 0o444. There the file is private through the access list of the user's
profile folder it is written in (``%USERPROFILE%\\.e2er``: the user, SYSTEM and Administrators), and
the tokens of ``e2er login`` go to the Windows Credential Manager first (keyring). The helpers below
check 0600/0700 where modes exist and the file's presence on Windows.

**Fake programs.** A test that puts a fake ``gh``, ``curl`` or ``e2er-data`` in front of the real one
writes a Python script with a ``#!`` line and makes it executable. Windows runs neither: the helper
writes the script and a ``<name>.exe`` launcher beside it (see ``fake_program``), and returns the .exe.
"""

from __future__ import annotations

import stat
import sys
from pathlib import Path

WINDOWS = sys.platform == "win32"


def owner_only(p: Path) -> bool:
    """The file is readable by its owner only: mode 0600 (on Windows: it exists; see the module docstring)."""
    if WINDOWS:
        return p.is_file()
    return stat.S_IMODE(p.stat().st_mode) == 0o600


def private_dir(p: Path) -> bool:
    """The folder is its owner's only: mode 0700 (on Windows: it exists)."""
    if WINDOWS:
        return p.is_dir()
    return stat.S_IMODE(p.stat().st_mode) == 0o700


def fake_program(path: Path, source: str) -> Path:
    """A program at ``path`` that runs the Python ``source`` with this interpreter; the path to start it by.

    On Windows: setuptools' console launcher copied to ``<name>.exe``, which runs ``<name>-script.py``
    beside it with the interpreter its first line names (the way pip-installed commands ran before
    distlib). A real .exe passes every argument as it is; a .cmd file would hand them to cmd.exe.
    """
    if not WINDOWS:
        path.write_text(f"#!{sys.executable}\n{source}", encoding="utf-8", newline="\n")
        path.chmod(0o755)
        return path
    import platform
    import shutil

    import setuptools

    arch = "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "64"
    exe = path.with_name(path.name + ".exe")
    shutil.copyfile(Path(setuptools.__file__).with_name(f"cli-{arch}.exe"), exe)
    script = path.with_name(path.name + "-script.py")
    script.write_text(f'#!"{sys.executable}"\n{source}', encoding="utf-8", newline="\n")
    return exe


def rmtree(path: Path) -> None:
    """shutil.rmtree that also removes read-only files (Git's objects on Windows, where rmtree stops at them)."""
    import os
    import shutil
    import stat as st

    def clear(func, p, _exc):  # noqa: ANN001 - shutil's callback
        os.chmod(p, st.S_IWRITE)
        func(p)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=clear)
    else:
        shutil.rmtree(path, onerror=clear)


def checkout_command(name: str) -> Path:
    """The command ``name`` (e2er-run, e2er-lit, e2er-check-tables) as a test runs it.

    ``scripts/<name>`` is the bash wrapper of a source checkout; Windows has no bash. There the test runs
    the console script the editable install made (``pip install -e .``), which calls the same function
    in src/wrappers.py.
    """
    root = Path(__file__).resolve().parents[1]
    if not WINDOWS:
        return root / "scripts" / name
    import sysconfig

    return Path(sysconfig.get_path("scripts")) / f"{name}.exe"
