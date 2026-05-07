"""Pipeline DAG — defines the default specialist execution order."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Stage:
    name: str
    specialists: list[str]
    parallel: bool = False
    required: bool = True
    depends_on: list[str] = field(default_factory=list)


# Default pipeline stages (Mode 1 — single pass)
SINGLE_PASS_DAG: list[Stage] = [
    Stage("design", ["idea_developer"], parallel=False),
    Stage("literature", ["literature_scanner"], parallel=False),
    Stage("identification", ["identification_strategist"], parallel=False),
    Stage("data_architecture", ["data_architect"], parallel=False, required=False),
    Stage("econometrics", ["econometrics_specialist"], parallel=False),
    Stage("writing", ["paper_drafter"], parallel=False),
    Stage("formatting", ["latex_formatter", "abstract_writer"], parallel=True),
    Stage(
        "review",
        [
            "mechanism_reviewer",
            "technical_reviewer",
            "literature_reviewer",
            "writing_reviewer",
            "data_reviewer",
            "identification_reviewer",
        ],
        parallel=True,
    ),
]

# Extended pipeline stages (Mode 2 — iterative with V3 extensions)
ITERATIVE_DAG: list[Stage] = [
    Stage("design", ["idea_developer"], parallel=False),
    Stage("literature", ["literature_scanner"], parallel=False),
    Stage("identification", ["identification_strategist"], parallel=False),
    Stage("data_architecture", ["data_architect"], parallel=False, required=False),
    Stage("analysis", ["data_analyst", "econometrics_specialist"], parallel=True),
    Stage("writing", ["section_writer"], parallel=False),
    Stage("ceiling_check", [], parallel=False),  # handled by StrategistEngine
    Stage("self_attack", ["self_attacker"], parallel=False),
    Stage(
        "polish",
        [
            "polish_formula",
            "polish_numerics",
            "polish_institutions",
            "polish_bibliography",
            "polish_equilibria",
        ],
        parallel=True,
    ),
    Stage("abstract", ["abstract_writer"], parallel=False),
    Stage("formatting", ["latex_formatter"], parallel=False),
    Stage(
        "review",
        [
            "mechanism_reviewer",
            "technical_reviewer",
            "literature_reviewer",
            "writing_reviewer",
            "data_reviewer",
            "identification_reviewer",
        ],
        parallel=True,
    ),
    Stage("revision", ["revisor"], parallel=False, required=False),
    Stage("replication", ["replication_packager"], parallel=False),
]


def get_dag(mode: str) -> list[Stage]:
    return ITERATIVE_DAG if mode == "iterative" else SINGLE_PASS_DAG
