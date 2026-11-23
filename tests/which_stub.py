"""A stand-in for ``shutil.which`` that still finds the sandbox for AI-written scripts.

Tests that fake the programs on this computer (no gh, no tectonic) must not hide bubblewrap or
sandbox-exec: e2er refuses to run an AI-written script without its sandbox (core/script_sandbox.py),
and a stub that answers None for every name would turn that refusal into the test's failure on a
Linux machine whose bubblewrap works (the GitHub runners).
"""

import shutil

_REAL = shutil.which
SANDBOX_PROGRAMS = ("bwrap", "sandbox-exec")


def which_only(**found: str):
    """``shutil.which`` that knows only ``found`` (name → path) and the sandbox programs."""

    def which(name, *args, **kwargs):
        if name in SANDBOX_PROGRAMS:
            return _REAL(name, *args, **kwargs)
        return found.get(name)

    return which
