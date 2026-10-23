"""An identifier in e2er's own records of a folder (provenance.json, e2er.json) needs a new export.

Review of 2026-10-23: the blind leak check said to take such a place out with `e2er redact`, which refuses
every file provenance.json does not list (provenance.json and e2er.json never are), with a message about
"a record of an earlier publish": there was no way out but a new export, and nothing said so.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.core import redact as rd
from tests.test_blind import EMAIL, blind, platform, quiet_computer, study  # noqa: F401 - fixtures
from tests.test_redact import study as redact_study  # noqa: F401 - fixture


def test_redact_points_an_identifier_in_provenance_json_to_a_new_export(redact_study: Path):  # noqa: F811
    from tests.test_redact import EMAIL as ADA

    prov = json.loads((redact_study / "provenance.json").read_text())
    prov["run"]["model"] = f"set up by {ADA}"
    (redact_study / "provenance.json").write_text(json.dumps(prov))
    with pytest.raises(rd.RedactError) as e:
        rd.redact(redact_study, ADA)
    msg = str(e.value)
    assert "provenance.json is e2er's own record of the folder" in msg and "e2er export" in msg
    assert "earlier publish" not in msg


def test_redact_points_an_identifier_in_e2er_json_to_a_new_export(redact_study: Path):  # noqa: F811
    from tests.test_redact import EMAIL as ADA

    (redact_study / "e2er.json").write_text(json.dumps({"contact": ADA}))
    with pytest.raises(rd.RedactError) as e:
        rd.redact(redact_study, ADA)
    assert "e2er.json is e2er's own record" in str(e.value)


def test_the_blind_leak_check_says_a_record_needs_a_new_export(study, platform, capsys):  # noqa: F811
    prov = json.loads((study / "provenance.json").read_text())
    prov["run"]["model"] = f"configured by {EMAIL}"
    (study / "provenance.json").write_text(json.dumps(prov, indent=2))
    assert blind(study) == 1
    out = capsys.readouterr().out
    assert "e2er's own records of the folder would still identify you" in out
    assert "`e2er redact` cannot change them" in out and "e2er export" in out
    assert platform.blind is None
