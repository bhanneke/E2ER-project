"""What differs between Linux, macOS and Windows in the tests' own checks.

**Owner-only files.** On Linux and macOS e2er writes a file that holds a token or key with mode 0600
(and its folder 0700). Windows has no POSIX modes: ``os.chmod`` sets only the read-only flag, and
``stat`` reports 0o666 or 0o444. There the file is private through the access list of the user's
profile folder it is written in (``%USERPROFILE%\\.e2er``: the user, SYSTEM and Administrators), and
the tokens of ``e2er login`` go to the Windows Credential Manager first (keyring). The helpers below
check 0600/0700 where modes exist and the file's presence on Windows.

**Fake programs.** A test that puts a fake ``gh``, ``curl`` or ``e2er-data`` in front of the real one
writes a Python script with a ``#!`` line and makes it executable. Windows runs neither: the helper
writes the script and a ``.cmd`` file beside it that runs it with this interpreter, and returns the
``.cmd`` (``shutil.which`` finds it by PATHEXT; ``subprocess`` starts it).
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
    """A program at ``path`` that runs the Python ``source`` with this interpreter; the path to start it by."""
    if not WINDOWS:
        path.write_text(f"#!{sys.executable}\n{source}", encoding="utf-8")
        path.chmod(0o755)
        return path
    script = path.with_name(path.name + "-fake.py")
    script.write_text(source, encoding="utf-8")
    cmd = path.with_name(path.name + ".cmd")
    cmd.write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    return cmd
