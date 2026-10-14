"""E2ER v3 — Structured logging configuration."""

from __future__ import annotations

import logging
import sys
from functools import cache

#: Where log lines go. stdout by default; a command that prints JSON on stdout moves them to stderr.
_STREAM = {"to": "stdout"}


def logs_to_stderr() -> None:
    """Send every e2er log line to stderr, so stdout carries only a command's machine-readable output.

    `e2er verify --json` printed "… | INFO | src.core.renderer.tables | render_tables: …" before its
    JSON, and the report could not be parsed (2026-10-13).
    """
    _STREAM["to"] = "stderr"
    for name in list(logging.root.manager.loggerDict):
        logger = logging.getLogger(name)
        for h in logger.handlers:
            if isinstance(h, logging.StreamHandler) and getattr(h, "stream", None) is sys.stdout:
                h.setStream(sys.stderr)


@cache
def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr if _STREAM["to"] == "stderr" else sys.stdout)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger
