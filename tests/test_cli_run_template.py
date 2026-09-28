"""`e2er run --template <name>` (alias `--pipeline`): the template a run follows."""

from __future__ import annotations

import sys

import pytest

from src.__main__ import main


@pytest.fixture
def captured_run(monkeypatch):
    seen: dict = {}

    def fake_run(**kwargs):
        seen.update(kwargs)
        return 0

    monkeypatch.setattr("src.cli_run.run", fake_run)
    return seen


@pytest.mark.parametrize("flag", ["--template", "--pipeline"])
def test_the_flag_reaches_run(monkeypatch, captured_run, flag):
    monkeypatch.setattr(sys, "argv", ["e2er", "run", "Q?", flag, "event-study-finance"])
    with pytest.raises(SystemExit):
        main()
    assert captured_run["template"] == "event-study-finance"


def test_the_default_is_empirical(monkeypatch, captured_run):
    monkeypatch.setattr(sys, "argv", ["e2er", "run", "Q?"])
    with pytest.raises(SystemExit):
        main()
    assert captured_run["template"] == "empirical"


def test_an_unknown_template_stops_before_anything_starts(monkeypatch, capsys):
    from src import cli_run

    started: list[str] = []
    monkeypatch.setattr(cli_run, "_ensure_api_up", lambda: started.append("api") or (True, None))
    assert cli_run.run("Q?", template="no-such-template") == 2
    assert started == []
    err = capsys.readouterr().err
    assert "no-such-template" in err and "event-study-finance" in err


def test_the_template_is_sent_as_the_pipeline(monkeypatch):
    from src import cli_run

    sent: dict = {}

    class _Resp:
        status_code = 200

        def json(self):
            return {"paper_id": "p", "workspace": "w"}

    def fake_post(url, json, headers, timeout):
        sent.update(json)
        return _Resp()

    monkeypatch.setattr("httpx.post", fake_post)
    assert cli_run._submit_paper("Q?", "empirical", "single_pass", 1.0, template="event-study-finance")
    assert sent["pipeline"] == "event-study-finance"
