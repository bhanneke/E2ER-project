"""Keys and tokens: the scanner knows today's formats, one scan guards every way out, and the
credentials file is written owner-only and atomically (security review 2026-10-23, repro_patterns.py)."""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from src.core import platform_client as pc
from src.core import secret_scan as ss
from src.core import test_guard
from src.core import zenodo as zen
from tests.test_keyring_backend import REAL_KEYRING, Backend, stand_in

from .platform_help import WINDOWS, owner_only, private_dir

# Built from parts so this file itself holds no token-shaped string a scanner of the repo would flag.
SAMPLES = {
    "gh CLI oauth (gho_)": "gho_" + "A1b2" * 9,
    "gh server token (ghs_)": "ghs_" + "B2c3" * 9,
    "gh user token (ghu_)": "ghu_" + "C3d4" * 9,
    "OpenAI project key": "sk-proj-" + "a1B2" * 12,
    "OpenAI legacy key": "sk-" + "a1B2c3" * 8,
    "Gemini/Google key": "AIza" + "Sy" + "x9" * 16 + "abc",
    "FRED key in a URL": "https://api.stlouisfed.org/fred/series?api_key=" + "0123456789abcdef" * 2 + "&x=1",
    "Zenodo token in a URL": "https://zenodo.org/api/records?access_token=" + "aB3x9Q" * 8,
    "lowercase env line": "zenodo_token=" + "aB3x9Q" * 8,
    "json env": '"ZENODO_TOKEN": "' + "aB3x9Q" * 8 + '"',
    "yaml key": "fred_api_key: " + "0123456789abcdef" * 2,
    "bearer header": "Authorization: Bearer " + "abcDEF123456ghiJKL789xyz",
}
CLEAN = [
    "tokenizer_model: bert-base-uncased-v2",
    "author_orcid: 0000-0002-1825-0097",
    "token_file = path_to_the_file",
    'API_KEY = os.environ["API_KEY"]',
    "sha256: " + "ab12" * 16,
    "md5: " + "0123456789abcdef" * 2,
    "Authorization: Bearer <token>",
]


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_the_scanner_knows_the_format(name):
    text = SAMPLES[name]
    assert ss.scan_text(text), name
    assert ss.find_secrets({"x": text}), name


@pytest.mark.parametrize("text", CLEAN)
def test_ordinary_text_is_not_a_key(text):
    assert ss.scan_text(text) == []


def test_a_large_file_is_scanned_whole_and_bad_bytes_do_not_stop_it(tmp_path):
    """The GitHub check skipped files over its size limit and files that were not UTF-8."""
    p = tmp_path / "run.log"
    with p.open("wb") as f:
        f.write(b"\xff\xfe not utf-8 \x80\n")
        f.write(b"x" * (ss._CHUNK - 10))  # the key straddles the first chunk boundary
        f.write(("ANTHROPIC_API_KEY=sk-ant-" + "Q" * 30 + "\n").encode())
        f.write(b"y" * (3 * ss._CHUNK))
    assert ss.scan_file(p) and "Anthropic key" in ss.scan_file(p)
    assert ss.scan_files(tmp_path, ["run.log"]) == [f"run.log: looks like a {k}" for k in ss.scan_file(p)]


def test_the_github_push_uses_the_shared_scan(tmp_path):
    from src.core import github_files as gf

    (tmp_path / "code").mkdir()
    (tmp_path / "code" / "notes.txt").write_text("zenodo_token=" + "aB3x9Q" * 8, encoding="utf-8", newline="\n")
    (tmp_path / "code" / "big.log").write_bytes(
        b"\x80" * 10 + b"z" * (60 << 20) + b"\n" + ("gho_" + "A1b2" * 9).encode()
    )
    staged = gf.Staged(root=tmp_path, files=["code/notes.txt", "code/big.log"], left_out=[])
    hits = gf.secrets_in(staged)
    assert any(h.startswith("code/notes.txt:") for h in hits) and any(h.startswith("code/big.log:") for h in hits)


def test_a_zenodo_deposit_with_a_key_sends_nothing():
    with pytest.raises(zen.ZenodoError, match="nothing was sent"):
        zen.deposit_files([("log.txt", SAMPLES["gh CLI oauth (gho_)"].encode())], {}, "tok", client=object())


def test_pack_refuses_a_study_file_with_a_key(tmp_path):
    from src.core.export import package as pkg

    folder = tmp_path / "study"
    (folder / "code" / "scratch").mkdir(parents=True)
    (folder / "README.md").write_text("# a study\n", encoding="utf-8", newline="\n")
    (folder / "provenance.json").write_text(json.dumps({"files": {}}), encoding="utf-8", newline="\n")
    (folder / "code" / "scratch" / "run.log").write_text(
        "env: " + SAMPLES["OpenAI project key"] + "\n", encoding="utf-8", newline="\n"
    )
    with pytest.raises(pkg.PackageError, match="looks like a key or token"):
        pkg.build(folder, tmp_path / "out.e2er")
    assert not (tmp_path / "out.e2er").exists()


def test_the_export_takes_keys_out_of_scratch_logs(tmp_path):
    from src.core.export import structured

    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "explore.log").write_text(
        "GET " + SAMPLES["FRED key in a URL"] + "\nrows: 10\n", encoding="utf-8", newline="\n"
    )
    dest = tmp_path / "out" / "code" / "scratch"
    notes: list[str] = []
    structured._copy_matches(ws, dest, "*.log", None, set(), notes)
    out = (dest / "explore.log").read_text(encoding="utf-8")
    assert "0123456789abcdef0123456789abcdef" not in out and "rows: 10" in out and "[removed" in out
    assert notes and "explore.log" in notes[0]


# ── the credentials file ─────────────────────────────────────────────────────


@pytest.fixture
def creds(monkeypatch, tmp_path) -> Path:
    p = tmp_path / "e2er-home" / "credentials.json"
    monkeypatch.setenv("E2ER_CREDENTIALS", str(p))
    monkeypatch.delenv("E2ER_TOKEN", raising=False)
    monkeypatch.setattr(pc, "_keyring", REAL_KEYRING)
    monkeypatch.setattr(test_guard, "saved_logins_allowed", lambda: True)
    return p


def _mode(p: Path) -> int:
    return stat.S_IMODE(p.stat().st_mode)


def test_the_credentials_file_is_written_owner_only_through_a_temporary_file(monkeypatch, creds):
    monkeypatch.setitem(sys.modules, "keyring", None)
    replaced = []
    real_replace = os.replace

    def spy(src, dst):
        replaced.append((Path(src).name, _mode(Path(src))))
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    pc.save_token("https://e2er.org", "e2er_tok")
    assert owner_only(creds) and private_dir(creds.parent)
    assert replaced and replaced[0][0].startswith(".credentials-")
    assert WINDOWS or replaced[0][1] == 0o600, "owner-only before it takes the name (POSIX modes)"
    assert not [p for p in creds.parent.iterdir() if p.name.endswith(".tmp")]


def test_a_damaged_credentials_file_is_read_with_a_warning_and_kept(monkeypatch, creds, capsys):
    monkeypatch.setitem(sys.modules, "keyring", None)
    creds.parent.mkdir(parents=True)
    creds.write_text("{not json", encoding="utf-8", newline="\n")
    assert pc.load_token("https://e2er.org") is None
    assert zen.stored_token() == (None, None)
    assert "cannot be read" in capsys.readouterr().err
    pc.save_token("https://e2er.org", "e2er_tok")
    assert pc.load_token("https://e2er.org") == "e2er_tok"
    kept = creds.with_name("credentials.json.damaged")
    assert kept.read_text(encoding="utf-8") == "{not json" and owner_only(kept)


def test_a_token_in_the_keychain_removes_the_files_old_copy(monkeypatch, creds):
    monkeypatch.setitem(sys.modules, "keyring", None)
    pc.save_token("https://e2er.org", "old")
    zen.save_token("zen_old")
    backend = Backend(priority=1)
    monkeypatch.setitem(sys.modules, "keyring", stand_in(backend))
    assert pc.save_token("https://e2er.org", "new") == "the system keychain"
    assert zen.save_token("zen_new") == "the system keychain"
    assert json.loads(creds.read_text(encoding="utf-8")) == {}


class WriteRefused(Backend):
    """A keychain that holds the old tokens and refuses new writes (locked), but deletes."""

    refuse_writes = False

    def set_password(self, service: str, user: str, token: str) -> None:
        if self.refuse_writes:
            raise RuntimeError("locked")
        super().set_password(service, user, token)


def test_a_token_in_the_file_removes_the_keychains_old_copy(monkeypatch, creds):
    backend = WriteRefused(priority=1)
    monkeypatch.setitem(sys.modules, "keyring", stand_in(backend))
    pc.save_token("https://e2er.org", "old")
    zen.save_token("zen_old")
    assert len(backend.store) == 2
    backend.refuse_writes = True
    assert pc.save_token("https://e2er.org", "new") == str(creds)
    assert zen.save_token("zen_new") == str(creds)
    assert backend.store == {}
    assert pc.load_token("https://e2er.org") == "new" and zen.stored_token() == ("zen_new", str(creds))
