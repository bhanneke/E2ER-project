"""Text from someone else's package, made safe to print in a terminal.

A title, a command or a file name in a ``.e2er`` package is the author's text. With terminal
control sequences in it (``ESC[2K`` erases a line, ``ESC]8;;`` makes a hidden link, ``\\r``
returns to the start of the line) it can overwrite what e2er printed before it, "Title: Forged"
over the real title, or a harmless command over the one that runs. Bidirectional overrides
(U+202E) reorder what is shown. :func:`printable` drops all of them.
"""

from __future__ import annotations

import contextlib
import re
import sys
import unicodedata
from collections.abc import Iterator
from typing import Any, TextIO

#: C0 controls except tab and newline, DEL, C1 controls.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
#: Unicode format characters that change how text is shown: bidi embeddings, overrides, isolates.
_BIDI = re.compile(r"[‎‏‪-‮⁦-⁩؜]")


def printable(value: object, *, newlines: bool = True) -> str:
    """``value`` as text without terminal control sequences or bidi controls.

    An escape sequence is removed with its parameters (``ESC[2K``, ``ESC]8;;url BEL``), not
    only its ESC. ``newlines=False`` also turns newlines and tabs into spaces (one line).
    """
    text = str(value)
    # OSC (ESC ] … BEL or ESC \), CSI (ESC [ … final byte), other two-byte escapes.
    text = re.sub(r"\x1b\][^\x07\x1b]*(\x07|\x1b\\)?", "", text)
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    text = re.sub(r"\x1b[@-_]", "", text)
    text = re.sub(r"\x9b[0-?]*[ -/]*[@-~]", "", text)
    text = _CONTROL.sub("", text)
    text = _BIDI.sub("", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Cs")
    if not newlines:
        text = re.sub(r"[\t\n]", " ", text)
    return text


class PrintableStream:
    """A text stream that passes every write through :func:`printable` (for a command's whole output)."""

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream

    def write(self, text: str) -> int:
        self._stream.write(printable(text))
        return len(text)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


@contextlib.contextmanager
def printable_output() -> Iterator[None]:
    """Within ``with printable_output():`` stdout and stderr carry no terminal control sequences.

    For the commands that print what a package or a study folder says (`e2er inspect`,
    `e2er reproduce`, `e2er verify`, `e2er unpack`): the text is someone else's.
    """
    out, err = sys.stdout, sys.stderr
    sys.stdout = PrintableStream(out)  # type: ignore[assignment]
    sys.stderr = PrintableStream(err)  # type: ignore[assignment]
    try:
        yield
    finally:
        sys.stdout, sys.stderr = out, err
