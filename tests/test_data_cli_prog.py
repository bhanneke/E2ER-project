"""`e2er-data <source> --help` names e2er-data, not the old e2er-allium-query (2026-10-13 demos)."""

from __future__ import annotations

import pytest

from src.modules.data.cli import main


@pytest.mark.parametrize("argv", [["--help"], ["yfinance", "--help"], ["allium", "--help"]])
def test_help_names_e2er_data(argv, capsys):
    with pytest.raises(SystemExit) as e:
        main(argv)
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert out.startswith("usage: e2er-data")
    assert "e2er-allium-query" not in out
