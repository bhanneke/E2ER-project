"""The nightly drift check: a login page is not drift, and the same drift is reported once."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
_spec = importlib.util.spec_from_file_location(
    "check_allium_drift", Path(__file__).resolve().parents[3] / "scripts" / "check_allium_drift.py"
)
assert _spec and _spec.loader
drift = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(drift)


def _fixture(url: str) -> bytes:
    name = url.rsplit("/", 1)[1]
    return (FIXTURES / name).read_bytes()


def test_identical_specs_match():
    assert drift.compare(FIXTURES, _fixture)["status"] == "match"


def test_a_login_redirect_is_unavailable_not_drift():
    out = drift.compare(FIXTURES, lambda url: b"Redirecting...")
    assert out["status"] == "unavailable" and out["fingerprint"] == ""
    assert len(out["unavailable"]) == 4


def test_a_changed_spec_is_drift_with_a_stable_fingerprint():
    def changed(url: str) -> bytes:
        doc = json.loads(_fixture(url))
        if url.endswith("prices-api.json"):
            doc["info"]["version"] = "9.9.9"
        return json.dumps(doc).encode()

    first = drift.compare(FIXTURES, changed)
    second = drift.compare(FIXTURES, changed)
    assert first["status"] == "drift" and first["drifted"] == ["prices-api"]
    assert first["fingerprint"] and first["fingerprint"] == second["fingerprint"]
    assert "9.9.9" in first["diffs"]["prices-api"]
