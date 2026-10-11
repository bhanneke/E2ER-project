"""Bridges for connectors written before the kit (Yahoo Finance, FRED, the GMD).

Their ``e2er-data`` handlers stay in cli.py and their fetchers in providers.py;
the definitions point at them by name, imported when first used (cli.py
imports the definitions, so the definitions may not import cli.py).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


def cli_handler(name: str) -> Callable[[Any], Awaitable[str]]:
    """The handler ``cli.<name>`` (``async (argparse.Namespace) -> str``), looked up when called."""

    async def run(args: Any) -> str:
        from .. import cli

        result: str = await getattr(cli, name)(args)
        return result

    run.__name__ = name
    return run


def doctor_check(name: str) -> Callable[[Any], Awaitable[Any]]:
    """The doctor's own check ``doctor.<name>`` (``async (settings) -> Check``), looked up when called."""

    async def run(settings: Any) -> Any:
        from .... import doctor

        return await getattr(doctor, name)(settings)

    run.__name__ = name
    return run
