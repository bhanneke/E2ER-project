"""e2er submit against a fake platform: local checks, the request, returned and resubmitted submissions."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from src import cli_submit
from src.core import platform_client as pc

URL = "https://platform.test"
SKILL = """---
name: codebook-development
description: Develop, test and freeze a qualitative codebook before coding interview transcripts.
---

# Codebook development

1. Read a sample of transcripts and draft codes with definitions, inclusion and exclusion rules.
2. Code the sample twice, compare, and revise the codebook until agreement holds.
"""
TEMPLATE = 'name = "gioia-coding"\n\n[[steps]]\nkind = "specialists"\nname = "code"\nrun = ["interview_coder"]\n'


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    monkeypatch.setattr(pc, "_keyring", lambda: None)
    monkeypatch.setenv("E2ER_CREDENTIALS", str(tmp_path / "credentials.json"))
    monkeypatch.delenv("E2ER_TOKEN", raising=False)
    monkeypatch.delenv("E2ER_URL", raising=False)


class FakePlatform:
    """POST and PUT /api/v1/submissions, answering as e2er-site does."""

    def __init__(self, state: str = "in progress"):
        self.state = state
        self.requests: list[tuple[str, str, dict, str | None]] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content) if req.content else {}
        self.requests.append((req.method, req.url.path, body, req.headers.get("authorization")))
        if req.url.path == "/api/v1/submissions" and req.method == "POST":
            ok = self.state != "returned"
            return httpx.Response(
                201,
                json={
                    "id": "sub-1a2b3c4d",
                    "stage": "Evaluate" if ok else "Conformance",
                    "state": self.state,
                    "conformance": [
                        {"check": "licence", "ok": True, "detail": "MIT License"},
                        {
                            "check": "skill format",
                            "ok": ok,
                            "detail": "name matches" if ok else "description too short",
                        },
                    ],
                    "url": f"{URL}/review#sub-1a2b3c4d",
                },
            )
        if req.url.path == "/api/v1/submissions/sub-1a2b3c4d" and req.method == "PUT":
            return httpx.Response(
                200,
                json={"id": "sub-1a2b3c4d", "stage": "Evaluate", "state": "in progress", "conformance": []},
            )
        return httpx.Response(404, json={"error": "no such endpoint"})


@pytest.fixture
def platform(monkeypatch) -> FakePlatform:
    fake = FakePlatform()
    monkeypatch.setattr(
        pc, "client_factory", lambda url: httpx.Client(base_url=url, transport=httpx.MockTransport(fake))
    )
    return fake


@pytest.fixture
def skill(tmp_path: Path) -> Path:
    d = tmp_path / "codebook-development"
    d.mkdir()
    (d / "SKILL.md").write_text(SKILL, encoding="utf-8")
    return d


def signed_in() -> None:
    pc.save_token(URL, "e2er_test_token")


def test_a_skill_folder_takes_name_identifier_and_summary_from_skill_md(skill):
    body, problems = cli_submit.build_request(str(skill), version="0.1.0", licence="MIT")
    assert problems == []
    assert body["kind"] == "skill" and body["slug"] == "codebook-development"
    assert body["summary"].startswith("Develop, test and freeze")
    assert body["content"] == SKILL


def test_the_agent_skills_shape_is_checked_before_sending(tmp_path):
    d = tmp_path / "codebook-development"
    d.mkdir()
    (d / "SKILL.md").write_text(SKILL.replace("name: codebook-development", "name: codebook"), encoding="utf-8")
    _, problems = cli_submit.build_request(str(d), version="0.1.0", licence="MIT")
    assert any("must match" in p for p in problems)
    (d / "SKILL.md").write_text("# no front matter\n", encoding="utf-8")
    _, problems = cli_submit.build_request(str(d), version="0.1.0", licence="MIT", slug="codebook-development")
    assert any("front matter" in p for p in problems)


def test_a_template_file_is_checked_for_its_steps(tmp_path):
    f = tmp_path / "gioia.toml"
    f.write_text(TEMPLATE, encoding="utf-8")
    body, problems = cli_submit.build_request(
        str(f), version="0.1.0", licence="MIT", summary="Grounded theory with the Gioia method."
    )
    assert problems == [] and body["kind"] == "template" and body["slug"] == "gioia-coding"
    f.write_text(TEMPLATE.replace('kind = "specialists"', 'kind = "magic"'), encoding="utf-8")
    _, problems = cli_submit.build_request(
        str(f), version="0.1.0", licence="MIT", summary="Grounded theory with the Gioia method."
    )
    assert any("Every step" in p for p in problems)


def test_missing_licence_version_and_specialist_fields_are_named(tmp_path):
    f = tmp_path / "coder.md"
    f.write_text("You code interview transcripts against a frozen codebook and write codes.csv.", encoding="utf-8")
    _, problems = cli_submit.build_request(
        str(f), kind="agent", summary="Codes interview transcripts against a codebook."
    )
    text = " ".join(problems)
    assert "licence" in text and "version" in text and "--role" in text


def test_a_non_commercial_licence_sends_the_address_and_no_content(skill):
    body, problems = cli_submit.build_request(str(skill), version="0.1.0", licence="CC-BY-NC-4.0")
    assert any("--source" in p for p in problems)
    body, problems = cli_submit.build_request(
        str(skill), version="0.1.0", licence="CC-BY-NC-4.0", source="https://github.com/example/codebook"
    )
    assert problems == [] and "content" not in body and body["content_url"] == "https://github.com/example/codebook"


def test_a_key_in_the_content_is_caught_before_sending(tmp_path):
    d = tmp_path / "codebook-development"
    d.mkdir()
    (d / "SKILL.md").write_text(
        SKILL + "\nUse sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789 for the model.\n", encoding="utf-8"
    )
    _, problems = cli_submit.build_request(str(d), version="0.1.0", licence="MIT")
    assert any("key or token" in p for p in problems)


def test_submit_sends_with_the_token_and_reports_the_checks(skill, platform, capsys):
    signed_in()
    code = cli_submit.submit(
        str(skill), url=URL, version="0.2.0", licence="MIT", improves="skill:ines/codebook-development", handle="tomas"
    )
    out = capsys.readouterr().out
    assert code == 0 and "sub-1a2b3c4d passed the automatic checks" in out and "✓ skill format" in out
    method, path, body, auth = platform.requests[-1]
    assert (method, path, auth) == ("POST", "/api/v1/submissions", "Bearer e2er_test_token")
    assert body["target"] == "skill:ines/codebook-development" and body["handle"] == "tomas"


def test_a_returned_submission_exits_1_and_says_how_to_resend(skill, platform, capsys):
    signed_in()
    platform.state = "returned"
    code = cli_submit.submit(str(skill), url=URL, version="0.1.0", licence="MIT")
    out = capsys.readouterr().out
    assert code == 1 and "✗ skill format" in out and "--resubmit sub-1a2b3c4d" in out
    code = cli_submit.submit(str(skill), url=URL, version="0.1.0", licence="MIT", resubmit="sub-1a2b3c4d")
    assert code == 0 and platform.requests[-1][:2] == ("PUT", "/api/v1/submissions/sub-1a2b3c4d")


def test_dry_run_and_signed_out_send_nothing(skill, platform, capsys):
    assert cli_submit.submit(str(skill), url=URL, version="0.1.0", licence="MIT", dry_run=True) == 0
    out = capsys.readouterr().out
    assert "POST https://platform.test/api/v1/submissions" in out and "bytes>" in out and "Dry run" in out
    assert cli_submit.submit(str(skill), url=URL, version="0.1.0", licence="MIT") == 1
    assert "e2er login" in capsys.readouterr().out
    assert platform.requests == []


def test_local_problems_stop_the_request(tmp_path, platform, capsys):
    signed_in()
    assert cli_submit.submit(str(tmp_path / "missing"), url=URL, version="0.1.0", licence="MIT") == 1
    assert "Not sent" in capsys.readouterr().out and platform.requests == []
