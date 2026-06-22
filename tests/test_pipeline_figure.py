"""Tests for the auto-generated pipeline figure.

The figure's whole value proposition is that it is GENERATED FROM THE SOURCE
OF TRUTH (``src/core/specialists/registry.py``) and therefore can never drift
from the code. These tests enforce exactly that: they derive their
expectations from the registry imports — they do NOT hardcode specialist names
or sidecar filenames — and assert the generated DOT references those real
values. If someone renames a specialist or a sidecar, the figure changes and
so does what these tests check, automatically.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_generator():
    """Import scripts/gen_pipeline_figure.py as a module.

    The script lives under scripts/ (not an installed package), so load it by
    path. It inserts the repo root on sys.path itself for the registry import.
    """
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    spec = importlib.util.spec_from_file_location(
        "gen_pipeline_figure", _REPO_ROOT / "scripts" / "gen_pipeline_figure.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gen():
    return _load_generator()


@pytest.fixture(scope="module")
def registry():
    from src.core.specialists import registry as reg

    return reg


@pytest.fixture(scope="module")
def dot(gen) -> str:
    return gen.build_dot()


def test_dot_is_valid_digraph(dot: str) -> None:
    assert dot.startswith("// AUTO-GENERATED")
    assert "digraph e2er_pipeline {" in dot
    # Balanced braces — a smoke check that assembly didn't truncate.
    assert dot.count("{") == dot.count("}")
    assert dot.rstrip().endswith("}")


def test_depicted_specialists_are_real(gen, registry) -> None:
    """Specialists the figure depicts are all real registry names, and their
    primary-artifact sublabels match SPECIALIST_ARTIFACTS exactly."""
    dot = gen.build_dot()
    for _key, _label, specialists in gen._phases():
        for spec in specialists:
            assert spec in registry.SPECIALIST_ARTIFACTS, (
                f"{spec} depicted in the figure but absent from "
                "SPECIALIST_ARTIFACTS — the figure drifted from the registry."
            )
            # The node label carries the real specialist name.
            assert spec in dot
            # And the primary artifact is rendered next to it.
            artifact = registry.SPECIALIST_ARTIFACTS[spec]
            assert artifact in dot, f"primary artifact {artifact} for {spec} missing from DOT"


def test_reviewers_match_registry(gen, registry) -> None:
    """The review phase depicts exactly REVIEWER_SPECIALISTS, derived live."""
    review_phase = [p for p in gen._phases() if p[0] == "review"]
    assert review_phase, "review phase missing from the figure"
    _key, _label, reviewers = review_phase[0]
    assert reviewers == list(registry.REVIEWER_SPECIALISTS)
    for r in registry.REVIEWER_SPECIALISTS:
        assert r in (gen.build_dot())


def test_polish_match_registry(gen, registry) -> None:
    """The polish phase depicts exactly POLISH_SPECIALISTS, derived live."""
    polish_phase = [p for p in gen._phases() if p[0] == "polish"]
    assert polish_phase, "polish phase missing from the figure"
    _key, _label, polish = polish_phase[0]
    assert polish == list(registry.POLISH_SPECIALISTS)


def test_contracts_reference_real_sidecars(gen, registry) -> None:
    """Every JSON contract edge in the figure uses a REAL sidecar filename
    declared in SPECIALIST_SIDECAR_ARTIFACTS (or the documented optional set),
    and is attributed to a real producer specialist."""
    flows = gen._contract_flows()
    assert flows, "no artifact contracts depicted — figure would be incomplete"

    # Build the union of registry-declared sidecars (required + optional).
    declared: set[str] = set()
    for files in registry.SPECIALIST_SIDECAR_ARTIFACTS.values():
        declared.update(files)
    for files in gen._DOCUMENTED_OPTIONAL_SIDECARS.values():
        declared.update(files)

    dot = gen.build_dot()
    for producer, sidecar, consumer in flows:
        assert producer in registry.SPECIALIST_ARTIFACTS, f"contract producer {producer} not a real specialist"
        assert sidecar in declared, (
            f"contract sidecar {sidecar} not declared in the registry — the figure invented a contract."
        )
        assert sidecar in dot
        # The consumer of every contract is the deterministic gate.
        assert consumer == gen._GATE_NODE


def test_required_sidecars_are_depicted(gen, registry) -> None:
    """Every REQUIRED sidecar in SPECIALIST_SIDECAR_ARTIFACTS appears in the
    figure — so a newly added required contract can't be silently omitted."""
    flows = gen._contract_flows()
    depicted_sidecars = {f for _p, f, _c in flows}
    for specialist, files in registry.SPECIALIST_SIDECAR_ARTIFACTS.items():
        for f in files:
            assert f in depicted_sidecars, f"required sidecar {f} (from {specialist}) is missing from the figure"


def test_phase_order_matches_runner(gen) -> None:
    """The phase keys, in order, match PipelineRunner.run's execution order.

    This is the second source-of-truth anchor: the runner drives these phase
    keys via state.mark_complete(...). If the runner reorders phases, this
    test (and the figure) must be updated in lockstep.
    """
    keys = [k for k, _l, _s in gen._phases()]
    assert keys == [
        "initial",
        "iterative",
        "self_attack",
        "polish",
        "review",
        "revision",
        "replication",
    ]


def test_honest_depiction_no_invented_gate(gen) -> None:
    """Honesty constraint: verify_numbers is the ONLY programmatic gate.
    There is no verify_citations gate in the codebase, so the figure must
    not invent one."""
    dot = gen.build_dot().lower()
    assert "verify_numbers" in dot
    assert "verify_citations" not in dot
    # No cross-model reviewer claim — E2ER uses same-model reviewers.
    assert "cross-model" not in dot


def test_generate_writes_dot(gen, tmp_path: Path) -> None:
    """generate() writes a non-empty pipeline.dot to the target dir."""
    out_dir = tmp_path / "figures"
    dot_path = gen.generate(out_dir=out_dir)
    assert dot_path == out_dir / "pipeline.dot"
    assert dot_path.is_file()
    text = dot_path.read_text(encoding="utf-8")
    assert "digraph e2er_pipeline" in text
    assert len(text) > 500
