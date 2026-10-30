"""UTF-8 output on every computer.

e2er prints file names, titles and authors as they are (``Prüfung 文献``) and marks
results with ``✓`` and ``→``. Python writes to a pipe or a file in the computer's
locale encoding, which on Windows is a code page such as cp1252: printing ``✓``
there raised UnicodeEncodeError, so ``e2er verify … > report.txt`` or a CI log on
Windows stopped with a traceback. A Windows console window is not affected
(Python writes to it in UTF-16), nor is a macOS or Linux terminal (UTF-8).

``utf8_stdio()`` switches stdout and stderr to UTF-8 when their encoding is
anything else, unless PYTHONIOENCODING says what the user wants. A character the
stream still cannot take is replaced, never a reason to stop.
"""

from __future__ import annotations

import codecs
import os
import sys


def _is_utf8(encoding: str | None) -> bool:
    try:
        return codecs.lookup(encoding or "").name == "utf-8"
    except LookupError:
        return False


def utf8_stdio() -> None:
    """stdout and stderr write UTF-8 (see the module's docstring)."""
    if os.environ.get("PYTHONIOENCODING"):
        return
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None or _is_utf8(getattr(stream, "encoding", None)):
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):  # a stream that cannot change any more: leave it as it is
            continue


def shell_arg(value: object) -> str:
    """``value`` as one argument of a command e2er prints for the reader to paste.

    A path with a space (``downloads ü/study.e2er``, ``C:\\Users\\Ann Lee\\study.e2er``) is quoted, so the
    printed command works as it is: in double quotes on Windows (cmd and PowerShell), with shlex's
    quoting elsewhere. A plain word stays as it is.
    """
    text = str(value)
    if sys.platform == "win32":
        import subprocess

        return subprocess.list2cmdline([text])
    import shlex

    return shlex.quote(text)
