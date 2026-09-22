"""A pipeline read from a file, and made to agree with the runner.

The test that earns this file is `test_the_builtin_spec_predicts_the_runners_
sequence`: `pipelines/empirical.toml` says what should happen, the runner does
what it does, and the two lists must be identical. Two independent derivations
of the same sequence — one data, one code — is what makes it safe to later
delete the code one.

Everything else here is about failing at load rather than at runtime. A typo in
a pipeline file should cost a clear message, not forty minutes of model calls
and a half-written paper.
"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from src.core.pipeline.spec import (
    MANDATORY_CHECKS,
    SCHEMA_PATH,
    PipelineError,
    available,
    find_spec,
    load_spec,
    spec_from_dict,
)

BUILTIN = Path(__file__).resolve().parents[1] / "pipelines" / "empirical.toml"

# Lifted from tests/test_pipeline_sequence.py, which pins these against the real
# runner. Duplicated deliberately: if someone changes one, the other should not
# quietly follow.
SINGLE_PASS = ["initial", "estimation_gate", "review", "revision", "replication"]
ITERATIVE = [
    "initial",
    "iterative",
    "estimation_gate",
    "self_attack",
    "polish",
    "review",
    "revision",
    "replication",
]


def _minimal(**over) -> dict:
    base = {"name": "p", "steps": [{"kind": "strategist", "name": "initial"}]}
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# The one that matters
# ---------------------------------------------------------------------------


def test_the_builtin_spec_predicts_the_runners_sequence():
    """empirical.toml and PipelineRunner.run() must agree, in both modes.

    If this fails after the runner is changed to read the spec, the refactor
    altered behaviour rather than relocating it.
    """
    spec = load_spec(BUILTIN)

    assert spec.sequence_for("single_pass") == SINGLE_PASS
    assert spec.sequence_for("iterative") == ITERATIVE


def test_the_builtin_spec_predicts_resume_behaviour():
    spec = load_spec(BUILTIN)

    resumed = spec.sequence_for("iterative", {"initial", "iterative"})
    assert resumed == ["estimation_gate", "self_attack", "polish", "review", "revision", "replication"]


def test_the_estimation_gate_is_not_resumable_in_the_spec_either():
    """The property the sequence test pins in code, pinned again in data."""
    spec = load_spec(BUILTIN)
    gate = spec.step("estimation_gate")

    assert gate is not None
    assert gate.resumable is False
    assert "estimation_gate" in spec.sequence_for("iterative", {"estimation_gate"})


def test_finalize_is_not_a_step():
    """Teardown runs however the run ended, so it cannot be sequenced."""
    spec = load_spec(BUILTIN)

    assert "compile" not in spec.sequence_for("iterative")
    assert set(spec.finalize) == {"compile", "audit_export", "github_push", "structured_export"}


def test_the_builtin_validates_against_the_published_schema():
    import tomllib

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    cls = jsonschema.validators.validator_for(schema)
    cls.check_schema(schema)
    cls(schema).validate(tomllib.loads(BUILTIN.read_text(encoding="utf-8")))


# ---------------------------------------------------------------------------
# Failing at load, not at runtime
# ---------------------------------------------------------------------------


def test_an_unknown_step_kind_is_rejected():
    with pytest.raises(PipelineError, match="unknown kind"):
        spec_from_dict(_minimal(steps=[{"kind": "summon", "name": "x"}]))


def test_an_unknown_check_is_rejected():
    with pytest.raises(PipelineError, match="unknown check"):
        spec_from_dict(_minimal(steps=[{"kind": "gate", "name": "g", "check": "vibes"}]))


def test_a_gate_without_a_check_is_rejected():
    with pytest.raises(PipelineError, match="no check"):
        spec_from_dict(_minimal(steps=[{"kind": "gate", "name": "g"}]))


def test_a_specialists_step_with_nobody_to_run_is_rejected():
    """Silently dispatching nobody would look like a phase that did nothing."""
    with pytest.raises(PipelineError, match="no specialists"):
        spec_from_dict(_minimal(steps=[{"kind": "specialists", "name": "s"}]))


def test_an_unknown_key_is_rejected():
    """A typo is a mistake, not an extension point.

    `specialists = [...]` where `run = [...]` was meant would otherwise produce
    a step that dispatches nobody and reports success.
    """
    with pytest.raises(PipelineError, match="unknown key"):
        spec_from_dict(_minimal(steps=[{"kind": "specialists", "name": "s", "specialists": ["x"]}]))


def test_a_top_level_setting_written_inside_a_step_says_so(tmp_path):
    """The mistake I made writing the first pipeline file.

    TOML binds a bare key-value following a table array to that table, so
    `finalize = [...]` at the foot of the file becomes a key of the last step.
    The file looks right. "unknown key: finalize" is a baffling thing to be told,
    so the error names the cause and the fix.
    """
    bad = tmp_path / "p.toml"
    bad.write_text('name = "p"\n\n[[steps]]\nkind = "strategist"\nname = "initial"\n\nfinalize = ["compile"]\n')

    with pytest.raises(PipelineError, match="top-level setting"):
        load_spec(bad)


def test_an_unknown_top_level_key_is_rejected():
    with pytest.raises(PipelineError, match="unknown top-level key"):
        spec_from_dict(_minimal(phases=[]))


def test_an_empty_pipeline_is_rejected():
    with pytest.raises(PipelineError, match="no steps"):
        spec_from_dict({"name": "p", "steps": []})


def test_a_duplicate_step_name_is_rejected():
    """Stage names are the resume key: a duplicate is skipped forever."""
    with pytest.raises(PipelineError, match="duplicate step name"):
        spec_from_dict(
            _minimal(
                steps=[
                    {"kind": "strategist", "name": "initial"},
                    {"kind": "strategist", "name": "initial"},
                ]
            )
        )


def test_an_unknown_mode_is_rejected():
    with pytest.raises(PipelineError, match="unknown mode"):
        spec_from_dict(_minimal(steps=[{"kind": "strategist", "name": "i", "modes": ["turbo"]}]))


def test_an_unknown_finalize_action_is_rejected():
    with pytest.raises(PipelineError, match="unknown finalize"):
        spec_from_dict(_minimal(finalize=["tweet_about_it"]))


def test_malformed_toml_names_the_file(tmp_path):
    bad = tmp_path / "broken.toml"
    bad.write_text('name = "x"\nsteps = [[[\n')

    with pytest.raises(PipelineError, match="broken.toml"):
        load_spec(bad)


def test_a_missing_file_is_reported_with_its_path(tmp_path):
    with pytest.raises(PipelineError, match="cannot read"):
        load_spec(tmp_path / "absent.toml")


# ---------------------------------------------------------------------------
# The floor
# ---------------------------------------------------------------------------


def test_a_pipeline_that_declares_no_gates_still_carries_the_floor():
    """Otherwise "the gates are not yours" dies the moment anyone writes one."""
    spec = spec_from_dict(_minimal())

    assert spec.declared_checks() == []
    assert set(spec.checks()) >= MANDATORY_CHECKS


def test_declared_and_inherited_checks_are_distinguishable():
    """A report should be able to say which checks the author asked for."""
    spec = spec_from_dict(
        _minimal(
            steps=[
                {"kind": "strategist", "name": "initial"},
                {"kind": "gate", "name": "n", "check": "numbers"},
            ]
        )
    )

    assert spec.declared_checks() == ["numbers"]
    assert set(spec.checks()) == {"numbers"} | MANDATORY_CHECKS


def test_a_theory_pipeline_can_declare_claims_and_omit_numbers():
    """The case the whole exercise is for: a process with nothing to count."""
    spec = spec_from_dict(
        {
            "name": "theory",
            "steps": [
                {"kind": "specialists", "name": "conceptualisation", "run": ["theory_specialist"]},
                {"kind": "gate", "name": "claims_gate", "check": "claims", "on_fail": "retry"},
            ],
        }
    )

    assert spec.declared_checks() == ["claims"]
    assert "numbers" not in spec.checks()
    assert spec.sequence_for("single_pass") == ["conceptualisation", "claims_gate"]


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def test_the_builtin_is_findable_by_name():
    assert find_spec("empirical").name == "empirical"


def test_project_local_beats_the_builtin(tmp_path):
    local = tmp_path / "pipelines"
    local.mkdir()
    (local / "empirical.toml").write_text('name = "empirical"\n[[steps]]\nkind = "strategist"\nname = "mine"\n')

    spec = find_spec("empirical", project=tmp_path)

    assert spec.sequence_for("iterative") == ["mine"], "a paper must be able to ship its own pipeline"


def test_a_missing_pipeline_names_everywhere_it_looked(tmp_path):
    with pytest.raises(PipelineError) as e:
        find_spec("nonesuch", project=tmp_path)

    message = str(e.value)
    assert "nonesuch" in message
    assert "pipelines" in message
    assert message.count("\n") >= 2, "list the locations, so the fix is obvious"


def test_available_lists_the_builtin():
    assert "empirical" in available()
