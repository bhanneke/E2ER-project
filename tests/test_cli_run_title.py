"""`e2er run` titles the run with the first sentence of the research question."""

from __future__ import annotations

import pytest

from src.cli_run import derive_title


@pytest.mark.parametrize(
    ("rq", "title"),
    [
        ("Do stablecoins crowd out deposits? We use bank data.", "Do stablecoins crowd out deposits"),
        ("Stablecoins crowd out deposits. We use bank data.", "Stablecoins crowd out deposits"),
        ("Stablecoins crowd out deposits.", "Stablecoins crowd out deposits"),
        ("No punctuation at all", "No punctuation at all"),
        # A DOI's full stops are not sentence ends (it was cut to "... Brazil (10").
        (
            "Replicate Pix adoption in Brazil (10.1016/j.jfineco.2020.01.001). Use the Zenodo package.",
            "Replicate Pix adoption in Brazil (10.1016/j.jfineco.2020.01.001)",
        ),
        ("Does a 0.5 pp rate cut move prices? Evidence.", "Does a 0.5 pp rate cut move prices"),
        ("Do U.S. banks hold more reserves", "Do U.S. banks hold more reserves"),
    ],
)
def test_first_sentence(rq, title):
    assert derive_title(rq) == title


def test_long_titles_are_truncated():
    title = derive_title("word " * 40)
    assert len(title) == 80 and title.endswith("...")


def test_a_question_that_starts_with_punctuation_keeps_its_text():
    assert derive_title("?") == "?"


def test_the_submitted_title_keeps_the_doi(monkeypatch):
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
    rq = "Replicate the payment study for Brazil (10.5281/zenodo.1234567)."
    assert cli_run._submit_paper(rq, "empirical", "single_pass", 1.0)
    assert sent["title"] == "Replicate the payment study for Brazil (10.5281/zenodo.1234567)"
