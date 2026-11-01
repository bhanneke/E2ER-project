"""An exclusive lock on an open lock file, across processes, on every system.

POSIX systems lock with ``fcntl.flock``; Windows has no fcntl and locks the file's first
byte with ``msvcrt.locking`` instead. Before 2026-10-30 the export lock (export/current.py)
fell back to a thread lock on Windows, so two e2er processes could export the same run at once.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Iterator
from typing import IO, Any


@contextlib.contextmanager
def exclusive(fh: IO[Any]) -> Iterator[None]:
    """Hold an exclusive lock on ``fh`` (a file opened for writing) while the block runs; wait for it."""
    try:
        import fcntl
    except ImportError:  # Windows
        fcntl = None  # type: ignore[assignment]
    if fcntl is not None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        return
    import msvcrt

    fh.seek(0)
    while True:
        try:
            # LK_LOCK itself retries for about 10 seconds, then raises; a long export is waited for.
            msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)  # type: ignore[attr-defined]
            break
        except OSError:
            time.sleep(0.05)
    try:
        yield
    finally:
        fh.seek(0)
        with contextlib.suppress(OSError):
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
