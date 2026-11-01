"""`e2er publish --to`: the platform is asked first, the Zenodo DOIs are minted last, and a held version succeeds.

Found in the review of 2026-10-23:

- `--to` with `--zenodo` published the Zenodo deposits (a DOI, once minted, stays) before the platform was
  asked anything, so a missing sign-in, a handle that is not the account's or a token for another study
  left DOIs that no study names. Now the sign-in, the handle and the token's study are checked before
  anything leaves this machine, the platform registers the study first, and the deposits are published
  only after it took the request. The same check runs before `--github` pushes.
- e2er.org answers HTTP 202 (`held: true`) when it keeps a burst of publications back for the author's
  confirmation in the browser. publish reported that as an error (exit 1) and wrote no link; it is a
  success: the confirm address is printed, `.e2er/link.json` records the version as held, exit 0.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.cli_publish import publish
from src.core import carry_over as co
from src.core import platform_client as pc
from tests.test_publish_access import BASE, REPO
from tests.test_publish_zenodo_versions import Zenodo, _record, bundle, zenodo  # noqa: F401 - fixtures

URL = "https://platform.test"
PUBLIC = dict(data="public", code="public", zenodo=True, yes=True)


class Platform:
    """pc.request for a platform: who is signed in, and what POST /api/v1/studies answers."""

    def __init__(self, log: list[str], *, me: dict | None = None, answer: tuple[int, dict] | None = None) -> None:
        self.log = log
        self.me = me if me is not None else {"name": "B", "handles": ["bhanneke"]}
        self.answer = answer
        self.sent: list[dict] = []

    def __call__(self, base, method, path, token=None, body=None):
        self.log.append(f"platform {method} {path}")
        if method == "GET" and path == "/api/v1/me":
            return (200, self.me) if self.me else (401, {"error": "Unauthorized"})
        if method == "POST" and path == "/api/v1/studies":
            self.sent.append(body)
            if self.answer is not None:
                return self.answer
            oid = body["manifest"]["id"]
            return 201, {
                "id": oid,
                "owner_project": oid,
                "version": 1,
                "study_url": f"{base}/{oid}",
                "dossier_url": "d",
            }
        if method == "GET" and path.startswith("/api/v1/studies/"):
            return 404, {"error": "not found"}
        raise AssertionError(f"unexpected request {method} {path}")


@pytest.fixture
def log(zenodo: Zenodo, monkeypatch) -> list[str]:  # noqa: F811 - the fixture of test_publish_zenodo_versions
    """One log of the platform's and Zenodo's requests, in order."""
    import httpx

    from src.core import zenodo as zen

    calls: list[str] = []

    def logged(req: httpx.Request) -> httpx.Response:
        calls.append(f"zenodo {req.method} {req.url.path}")
        return zenodo(req)

    monkeypatch.setattr(
        zen, "client_factory", lambda base: httpx.Client(base_url=base, transport=httpx.MockTransport(logged))
    )
    return calls


def _platform(monkeypatch, log: list[str], **kw) -> Platform:
    p = Platform(log, **kw)
    monkeypatch.setattr(pc, "load_token", lambda base: "tok")
    monkeypatch.setattr(pc, "request", p)
    return p


def _zenodo_calls(log: list[str]) -> list[str]:
    return [c for c in log if c.startswith("zenodo")]


def test_the_platform_registers_before_a_doi_is_minted(bundle: Path, zenodo: Zenodo, log, monkeypatch, capsys):  # noqa: F811
    platform = _platform(monkeypatch, log)
    assert publish(str(bundle), to_url=URL, **BASE, **REPO, **PUBLIC) == 0, capsys.readouterr().out
    first_publish = next(i for i, c in enumerate(log) if c.endswith("/actions/publish"))
    registered = log.index("platform POST /api/v1/studies")
    assert log[0] == "platform GET /api/v1/me", "the sign-in is checked before Zenodo is asked anything"
    assert registered < first_publish, "the study is registered before a DOI is minted"
    rec = _record(bundle)["deposits"]
    assert {i: r["state"] for i, r in rec.items()} == {"data": "published", "code": "published"}
    # The registered description names the DOIs reserved for the deposits published after it.
    sent = platform.sent[0]["manifest"]["availability"]
    assert sent["data"]["doi"] == rec["data"]["doi"] and sent["code"]["doi"] == rec["code"]["doi"]


@pytest.mark.parametrize(
    "me, words",
    [
        (None, "did not accept the sign-in"),
        ({"name": "B", "handles": ["someone-else"]}, "--owner bhanneke is not one of your account's handles"),
        ({"name": "B", "study": "bhanneke/other"}, "can only publish new versions of bhanneke/other"),
    ],
)
def test_a_platform_that_would_refuse_gets_no_doi_minted(
    bundle: Path,  # noqa: F811
    zenodo: Zenodo,  # noqa: F811
    log,
    monkeypatch,
    capsys,
    me,
    words,
):
    platform = _platform(monkeypatch, log, me=me if me is not None else {})
    assert publish(str(bundle), to_url=URL, **BASE, **REPO, **PUBLIC) == 1
    out = capsys.readouterr().out
    assert words in out and "nothing was sent" in out
    assert _zenodo_calls(log) == [] and zenodo.deps == {}, "Zenodo was never asked"
    assert platform.sent == [] and not (bundle / "e2er.json").exists()


def test_a_token_for_this_study_passes(bundle: Path, zenodo: Zenodo, log, monkeypatch, capsys):  # noqa: F811
    _platform(monkeypatch, log, me={"name": "B", "study": "bhanneke/demo"})
    assert publish(str(bundle), to_url=URL, **BASE, **REPO, **PUBLIC) == 0, capsys.readouterr().out


def test_a_registration_refused_after_the_check_leaves_only_drafts(
    bundle: Path,  # noqa: F811
    zenodo: Zenodo,  # noqa: F811
    log,
    monkeypatch,
    capsys,
):
    """What the platform checks only on the request (a dossier of another study): no DOI is minted either."""
    platform = _platform(monkeypatch, log, answer=(409, {"error": "this content belongs to another study"}))
    assert publish(str(bundle), to_url=URL, **BASE, **REPO, **PUBLIC) == 1
    out = capsys.readouterr().out
    assert "Nothing was deposited on Zenodo" in out
    assert not [c for c in log if c.endswith("/actions/publish")], "no DOI was minted"
    assert all(d["state"] == "unsubmitted" for d in zenodo.deps.values())
    assert {r["state"] for r in _record(bundle)["deposits"].values()} == {"draft"}
    # Run again once the platform takes it: the same drafts are published, no new ones reserved.
    drafts = {k: v["id"] for k, v in _record(bundle)["deposits"].items()}
    platform.answer = None
    assert publish(str(bundle), to_url=URL, **BASE, **REPO, **PUBLIC) == 0, capsys.readouterr().out
    assert {k: v["id"] for k, v in _record(bundle)["deposits"].items()} == drafts
    assert {r["state"] for r in _record(bundle)["deposits"].values()} == {"published"}


HELD = {
    "id": "bhanneke/demo",
    "owner_project": "bhanneke/demo",
    "held": True,
    "status": "held: confirm in your browser",
    "hold": "h-1",
    "confirm_url": "https://platform.test/account#held",
    "study_url": "https://platform.test/bhanneke/demo",
    "version": None,
    "existing": False,
    "message": "Held: confirm in your browser. This account published more than 3 new studies within 10 minutes.",
}


def test_a_held_version_is_a_success_with_the_confirm_address(bundle: Path, monkeypatch, capsys):  # noqa: F811
    log: list[str] = []
    _platform(monkeypatch, log, answer=(202, HELD))
    assert publish(str(bundle), to_url=URL, **BASE, **REPO, data="private", code="private", yes=True) == 0
    out = capsys.readouterr().out
    assert "Held on https://platform.test" in out and "https://platform.test/account#held" in out
    link = json.loads((bundle / ".e2er" / "link.json").read_text(encoding="utf-8"))
    assert link["held"] is True and link["hold"] == "h-1" and link["version"] is None
    assert link["owner_project"] == "bhanneke/demo" and link["confirm_url"] == HELD["confirm_url"]
    m = json.loads((bundle / "e2er.json").read_text(encoding="utf-8"))
    assert link["dossier_id"] == m["dossier"]["id"] and link["content_id"] == m["content_id"]
    from src.cli_verify import PASS, _check_anchor

    assert _check_anchor(bundle).status == PASS


def test_held_with_zenodo_mints_no_doi_until_confirmed(bundle: Path, zenodo: Zenodo, log, monkeypatch, capsys):  # noqa: F811
    _platform(monkeypatch, log, answer=(202, HELD))
    assert publish(str(bundle), to_url=URL, **BASE, **REPO, **PUBLIC) == 0
    assert "stay drafts (no DOI is minted) until you confirm" in capsys.readouterr().out
    assert not [c for c in log if c.endswith("/actions/publish")]


def test_an_error_202_without_held_is_still_an_error(bundle: Path, monkeypatch, capsys):  # noqa: F811
    _platform(monkeypatch, [], answer=(202, {"error": "accepted?"}))
    assert publish(str(bundle), to_url=URL, **BASE, **REPO, data="private", code="private", yes=True) == 1
    assert not (bundle / ".e2er" / "link.json").exists()


def test_a_held_link_is_not_carried_over_until_confirmed(tmp_path: Path):
    """A later version without the run database: the held version is not public, so it is not carried over."""
    b = tmp_path / "s"
    (b / ".e2er").mkdir(parents=True)
    (b / "e2er.json").write_text(json.dumps({"dossier": {"id": "sha256:" + "a" * 64}}), encoding="utf-8", newline="\n")
    link = {"platform_url": URL, "owner_project": "bhanneke/demo", "dossier_id": "sha256:" + "a" * 64, **HELD}
    link["dossier_id"] = "sha256:" + "a" * 64
    (b / ".e2er" / "link.json").write_text(json.dumps(link), encoding="utf-8", newline="\n")

    def request(base, method, path, token=None, body=None):
        return 404, {"error": "not found"}

    with pytest.raises(co.CarryOverError, match="held on https://platform.test, waiting for your confirmation"):
        co.fetch_previous(b, "bhanneke/demo", request=request)

    def confirmed(base, method, path, token=None, body=None):
        if path == "/api/v1/studies/bhanneke/demo":
            return 200, {"latest": {"number": 1, "dossier_id": "sha256:" + "a" * 64}}
        return 404, {}

    with pytest.raises(co.CarryOverError, match="did not return the dossier"):  # confirmed: carried over as usual
        co.fetch_previous(b, "bhanneke/demo", request=confirmed)


def test_status_of_a_held_folder_says_where_to_confirm(tmp_path: Path, monkeypatch, capsys):
    from src.cli_platform import status

    b = tmp_path / "s"
    (b / ".e2er").mkdir(parents=True)
    (b / ".e2er" / "link.json").write_text(
        json.dumps({"platform_url": URL, "dossier_id": "x", **HELD}), encoding="utf-8", newline="\n"
    )
    monkeypatch.setattr(pc, "request", lambda *a, **k: (404, {"error": "not found"}))
    assert status(str(b)) == 0
    assert "held on https://platform.test, waiting for your confirmation" in capsys.readouterr().out


def test_the_dashboard_shows_a_held_version_with_its_confirm_address():
    from src.api.finish import _published_links

    out = (
        "✓ Held on https://platform.test: held: confirm in your browser\n"
        "  Confirm or discard it, signed in in the browser: https://platform.test/account#held\n"
    )
    assert _published_links(out) == {"held": True, "confirm_url": "https://platform.test/account#held"}
