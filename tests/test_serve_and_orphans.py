"""Two things a person outside a terminal needs: the app opens, and it is honest.

`e2er` used to start a server, print uvicorn's log, and leave the user to know
that a browser and 127.0.0.1:8280 were the next step — and to exit 0 when the
port was taken, so a failed start looked like a successful one.

And a run lives in the server process. Reboot, and the database still says
`designing` forever: a paper that looks busy and will never move. Coming back
to that, the reasonable conclusion is that the tool is broken.
"""

from __future__ import annotations

import socket

import pytest

from src import __main__ as cli


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_a_foreign_process_on_the_port_is_a_failure(monkeypatch):
    """It exited 0 while serving nothing, so scripts saw success."""
    port = _free_port()
    holder = socket.socket()
    holder.bind(("127.0.0.1", port))
    holder.listen(1)
    try:
        monkeypatch.setattr(cli, "_already_serving", lambda h, p: False)
        code = cli._serve(host="127.0.0.1", port=port, reload=False, no_browser=True)
        assert code != 0, "a bind failure must not report success"
    finally:
        holder.close()


def test_an_e2er_already_there_is_reused_not_fought(monkeypatch):
    """Two dashboards on one port helps nobody; open the one that exists."""
    opened: list[str] = []
    monkeypatch.setattr(cli, "_already_serving", lambda h, p: True)

    code = cli._serve(host="127.0.0.1", port=8280, reload=False, no_browser=True)
    assert code == 0
    assert not opened  # no_browser respected


def test_browser_opening_never_breaks_the_server(monkeypatch):
    """Headless machines and containers have no browser, which is not an error."""

    def _boom(_url):
        raise RuntimeError("no display")

    import webbrowser

    monkeypatch.setattr(webbrowser, "open", _boom)
    monkeypatch.setattr(cli, "_already_serving", lambda h, p: True)

    assert cli._serve(host="127.0.0.1", port=8280, reload=False, no_browser=False) == 0


def test_every_in_flight_status_is_reconcilable():
    """The orphan list must cover the statuses a run can be interrupted in.

    A status missing from it leaves that paper reading `designing` forever.
    """
    from src.api.app import _ORPHANABLE
    from src.core.strategist.state import PaperStatus

    terminal = {
        PaperStatus.COMPLETED,
        PaperStatus.FAILED,
        PaperStatus.CANCELLED,
        PaperStatus.REJECTED,
        PaperStatus.PAUSED,
        PaperStatus.DATA_APPROVAL,  # waits on a human, not on the process
    }
    in_flight = {s.value for s in PaperStatus} - {s.value for s in terminal}

    missing = sorted(in_flight - set(_ORPHANABLE))
    assert not missing, f"these statuses would be stranded by a restart: {missing}"


@pytest.mark.asyncio
async def test_reconciliation_survives_an_unreachable_database(monkeypatch):
    """A database that is not up at boot must not stop the server starting."""
    from src.api import app as appmod

    async def _boom(*_a, **_k):
        raise RuntimeError("db down")

    monkeypatch.setattr("src.db.client.fetch_all", _boom)
    await appmod._reconcile_orphans()  # must not raise
