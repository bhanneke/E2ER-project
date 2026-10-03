"""``e2er`` under the replay level: ``python -m tests.replay.cli <e2er arguments>``.

The same ``main()`` as the ``e2er`` command, after :func:`tests.replay.harness.install`.
Run it from the study folder (its ``.env``), with the e2er checkout on ``PYTHONPATH``.
"""

from __future__ import annotations

import sys

from .harness import install


def main() -> None:
    install()
    from src.__main__ import main as e2er_main

    sys.argv[0] = "e2er"
    e2er_main()


if __name__ == "__main__":
    main()
