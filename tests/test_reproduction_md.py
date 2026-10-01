"""reproduction_report.md must agree with reproduction_report.json (src/core/pipeline/reproduction_md.py).

The fixture ``replication_demo_md/contradictory.md`` is the report the
comparer (Claude Haiku) wrote for the replication demonstration, 08af321d:
it says "16 targets" and "not_reproduced 2" while the JSON and the check have
17 numbers, 12 reproduced, 2 reproduced_minor and 3 not reproduced, and it
lists three package versions the run did not install. The reproduction check
passed it. ``replication_demo/reproduction_report.md`` is the same report with
those statements corrected.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from src.cli_verify import _run_checks
from src.core.pipeline.reproduction import CHECK_FILE, check_report, check_reproduction
from src.core.pipeline.reproduction_md import (
    BEGIN,
    END,
    markdown_problems,
    render_summary,
    split_summary,
    with_summary,
)

FIXTURES = Path(__file__).parent / "fixtures"
REPL = FIXTURES / "replication_demo"
CONTRADICTORY = (FIXTURES / "replication_demo_md" / "contradictory.md").read_text(encoding="utf-8")
CONSISTENT = (REPL / "reproduction_report.md").read_text(encoding="utf-8")
REPORT = json.loads((REPL / "reproduction_report.json").read_text(encoding="utf-8"))
LOG = json.loads((REPL / "sandbox_log.json").read_text(encoding="utf-8"))


def _ws(tmp_path: Path, md: str | None = None) -> Path:
    ws = tmp_path / "ws"
    shutil.copytree(REPL, ws)
    if md is not None:
        (ws / "reproduction_report.md").write_text(md, encoding="utf-8")
    return ws


# ── the real report ───────────────────────────────────────────────────────────


def test_the_real_report_contradicts_its_json_and_each_contradiction_is_named():
    problems = markdown_problems(CONTRADICTORY, REPORT, LOG)
    text = "\n".join(problems)
    assert "reproduction_report.md says 16 level-1 numbers" in text
    assert "reproduction_report.json has 17" in text
    assert "says 2 not_reproduced, reproduction_report.json has 3" in text
    assert "says 16 in total, reproduction_report.json has 17" in text
    assert "says 18 level-1 numbers" in text  # "14 of 18 level-1 targets"
    assert "data.table 1.18.6.1, reproduction_report.json (environment.installed) has data.table 1.18.4" in text
    assert "knitr 1.52" in text and "MatchIt 4.8.1" in text
    # "Three targets failed reproduction at level 1" is true and not reported
    assert not any("Three targets" in p for p in problems)
    assert len(problems) == 7, problems


def test_the_corrected_report_agrees():
    assert markdown_problems(CONSISTENT, REPORT, LOG) == []


def test_the_pipeline_check_fails_on_the_real_report(tmp_path: Path):
    ws = _ws(tmp_path, CONTRADICTORY)
    r = check_reproduction(ws)
    assert not r.passed
    assert any("says 16 level-1 numbers" in x and "has 17" in x for x in r.reasons)
    doc = json.loads((ws / CHECK_FILE).read_text())
    assert doc["report_text"]["agrees"] is False


def test_the_pipeline_check_writes_the_summary_and_passes_a_consistent_report(tmp_path: Path):
    ws = _ws(tmp_path)
    r = check_reproduction(ws)
    assert r.passed, r.reasons
    md = (ws / "reproduction_report.md").read_text()
    block, rest = split_summary(md)
    assert block == render_summary(REPORT, LOG)
    assert "| not_reproduced | 3 | 3 |" in block and "| Total | 17 | 11 |" in block
    assert "knitr 1.51" in block and "2026-08-30" in block
    # placed before the report's first section, after its title block
    assert md.index(BEGIN) < md.index("## Summary") and md.startswith("# Reproduction Report")
    # a second run leaves the file as it is
    check_reproduction(ws)
    assert (ws / "reproduction_report.md").read_text() == md
    assert json.loads((ws / CHECK_FILE).read_text())["report_text"] == {
        "file": "reproduction_report.md",
        "agrees": True,
        "summary_written": False,
    }


def test_the_summary_is_not_written_while_the_json_fails(tmp_path: Path):
    ws = _ws(tmp_path)
    report = json.loads((ws / "reproduction_report.json").read_text())
    report["summary"]["level_1"]["reproduced"] = 13
    (ws / "reproduction_report.json").write_text(json.dumps(report))
    assert not check_reproduction(ws).passed
    assert BEGIN not in (ws / "reproduction_report.md").read_text()


def test_a_missing_markdown_report_fails(tmp_path: Path):
    ws = _ws(tmp_path)
    (ws / "reproduction_report.md").unlink()
    r = check_reproduction(ws)
    assert not r.passed and any("reproduction_report.md is missing" in x for x in r.reasons)


def test_the_comparer_contract_reports_the_contradictions_for_its_retry(tmp_path: Path):
    ws = _ws(tmp_path, CONTRADICTORY)
    errs = check_report(ws)
    assert any("says 16 level-1 numbers" in e for e in errs)
    assert check_report(_ws(tmp_path / "b")) == []


# ── e2er verify ───────────────────────────────────────────────────────────────


def _bundle(ws: Path, tmp_path: Path) -> Path:
    from src.core.export.structured import export_paper

    return export_paper(ws, tmp_path / "out", date_str="20260929")


def test_verify_fails_a_bundle_whose_report_contradicts_its_json(tmp_path: Path):
    bundle = _bundle(_ws(tmp_path, CONTRADICTORY), tmp_path)
    check = next(c for c in _run_checks(bundle, online=False) if c.name == "reproduction")
    assert check.status == "FAIL"
    assert "reproduction_report.md" in check.detail and "has 17" in check.detail


def test_verify_passes_a_consistent_bundle_and_catches_an_edited_summary(tmp_path: Path):
    ws = _ws(tmp_path)
    assert check_reproduction(ws).passed
    bundle = _bundle(ws, tmp_path)
    check = next(c for c in _run_checks(bundle, online=False) if c.name == "reproduction")
    assert check.status == "PASS", check.detail
    assert "reproduction_report.md agrees with reproduction_report.json" in check.detail
    md = bundle / "misc" / "reproduction_report.md"
    md.write_text(md.read_text().replace("| not_reproduced | 3 | 3 |", "| not_reproduced | 2 | 3 |"))
    check = next(c for c in _run_checks(bundle, online=False) if c.name == "reproduction")
    assert check.status == "FAIL" and "summary section" in check.detail


# ── what the prose parser reads, and what it leaves alone ─────────────────────


def _one_level(
    level: str = "reproduced", published: float = 0.0194053054480327, reproduced: float = 0.0194053054480327
):
    return {
        "results": [
            {
                "id": "t7",
                "target_level": 1,
                "level": level,
                "comparisons": [
                    {"target_id": "l1_mde", "published": published, "reproduced": reproduced, "label": level},
                ],
            }
        ],
        "environment": {"installed": {"fixest": "0.14.2"}},
    }


def test_a_label_in_a_table_row_must_be_the_json_label():
    rep = _one_level("not_reproduced", reproduced=0.0173811968394429)
    md = (
        "# R\n\n## Level 1\n\n| Target | Published | Reproduced | Status |\n|---|---|---|---|\n"
        "| MDE | 0.0194053054480327 | 0.0173811968394429 | **reproduced_minor** |\n"
    )
    [p] = markdown_problems(md, rep)
    assert "labels l1_mde" in p and "'reproduced_minor'" in p and "labels it 'not_reproduced'" in p


def test_a_label_under_a_heading_applies_to_its_list_items():
    rep = _one_level("reproduced_minor", reproduced=0.0193)
    md = "# R\n\n## Not reproduced\n\n1. **MDE**\n   - Published: 0.0194053054480327\n   - Reproduced: 0.0193\n"
    [p] = markdown_problems(md, rep)
    assert "'not_reproduced'" in p and "labels it 'reproduced_minor'" in p


def test_a_bold_field_name_is_not_a_label():
    rep = _one_level("not_reproduced", reproduced=0.0173811968394429)
    md = "# R\n\n- **Published:** 0.0194053054480327, **Reproduced:** 0.0173811968394429 (not_reproduced)\n"
    assert markdown_problems(md, rep) == []


def test_a_target_id_in_the_text_identifies_the_number():
    rep = _one_level("not_reproduced", reproduced=0.0173811968394429)
    md = "# R\n\n- `l1_mde`: status: reproduced\n"
    [p] = markdown_problems(md, rep)
    assert "labels l1_mde" in p


def test_counts_need_the_level_in_the_sentence():
    rep = _one_level()
    # the level is named: checked
    assert markdown_problems("# R\n\nAt level 1, 3 targets were compared.\n", rep)
    # an exhibit's own count, without a level: left alone
    assert markdown_problems("# R\n\nThe DiD table has 24 estimates and 3 targets.\n", rep) == []
    # "Table 2 values" is not a count
    assert markdown_problems("# R\n\nLevel 1: Table 2 values are below.\n", rep) == []


def test_a_documented_version_next_to_the_installed_one_is_accepted():
    rep = _one_level()
    assert markdown_problems("# R\n\n- fixest: documented 0.12.0, installed 0.14.2\n", rep) == []
    [p] = markdown_problems("# R\n\n- fixest 0.12.0\n", rep)
    assert p == (
        "reproduction_report.md says fixest 0.12.0, reproduction_report.json (environment.installed) has fixest 0.14.2"
    )


def test_a_version_the_json_does_not_list_is_compared_with_the_sandbox_log():
    rep = _one_level()
    log = {"install": {"installed": {"fixest": "0.14.2", "janitor": "2.2.1"}}}
    [p] = markdown_problems("# R\n\njanitor 2.2.2 was installed.\n", rep, log)
    assert p == "reproduction_report.md says janitor 2.2.2, sandbox_log.json has janitor 2.2.1"


def test_with_summary_replaces_an_earlier_section():
    first = with_summary("# T\n\nintro\n\n## A\n", f"{BEGIN}\nold\n{END}")
    again = with_summary(first, f"{BEGIN}\nnew\n{END}")
    assert "old" not in again and again.count(BEGIN) == 1 and again.index("new") < again.index("## A")


# ── 2026-10-01 review: contradictions the check missed ───────────────────────
# The report on e2er.org (published.md, 2026-10-01) writes one section per
# exhibit ("**Table 5: …**") with list items ("- Published A, reproduced B",
# "- Label: not_reproduced ✗"). Each edit below contradicts the JSON.

PUBLISHED = (FIXTURES / "replication_demo_md" / "published.md").read_text(encoding="utf-8")
TABLE5 = (
    "- Published –0.0193985235407047, reproduced +0.0347239490711656\n"
    "- Sign reversal: negative published, positive reproduced\n"
    "- Relative difference: 2.79 (far exceeds tolerance)\n"
    "- Label: not_reproduced ✗"
)


def _problems(md: str) -> list[str]:
    return markdown_problems(md, REPORT, LOG, require_summary=True)


def test_the_published_report_agrees():
    assert _problems(PUBLISHED) == []


def test_a_relabelled_label_line_is_caught():
    md = PUBLISHED.replace(TABLE5, TABLE5.replace("- Label: not_reproduced ✗", "- Label: reproduced ✓"), 1)
    [p] = _problems(md)
    assert "l1_pbf_familias_att_cs_sem" in p and "'reproduced'" in p and "labels it 'not_reproduced'" in p


def test_a_changed_reproduced_number_is_caught():
    md = PUBLISHED.replace(
        "- Published –0.00364909844619658, reproduced –0.00365238597730994",
        "- Published –0.00364909844619658, reproduced –0.00364909844619658",
        1,
    )
    [p] = _problems(md)
    assert "l1_tac_att_cs_sem" in p and "has -0.00365238597730994" in p


def test_a_section_rewritten_as_reproduced_is_caught():
    md = PUBLISHED.replace(TABLE5, "- Published –0.0193985235407047, reproduced –0.0193985235407047 (reproduced ✓)", 1)
    problems = _problems(md)
    assert any("reproduced -0.0193985235407047" in p and "has 0.0347239490711656" in p for p in problems)
    assert any("labels it 'not_reproduced'" in p for p in problems)


def test_a_count_without_the_word_level_is_checked_against_its_sections_level():
    [p] = _problems(PUBLISHED.replace("12 of 17 numbers", "17 of 17 numbers", 1))
    assert "says 17 reproduced level-1 numbers" in p and "has 12 reproduced" in p
    [p] = _problems(PUBLISHED.replace("12 of 17 numbers", "12 of 18 numbers", 1))
    assert "18 level-1 numbers" in p


def test_n_of_m_must_be_one_of_the_counts_whatever_it_is_called():
    md = PUBLISHED.replace(
        "## Unassessed Targets", "## Tally\n\nWe looked at 9 of 17 numbers closely.\n\n## Unassessed Targets"
    )
    [p] = _problems(md)
    assert "9 of 17" in p and "none of the counts" in p


def test_an_appended_verdict_that_everything_reproduced_is_caught():
    md = (
        PUBLISHED.rstrip()
        + "\n\n## Verdict\n\nAll results of the paper reproduce exactly; the package is fully reproducible.\n"
    )
    problems = _problems(md)
    assert problems and all("says everything reproduced" in p for p in problems)
    # true when it is true
    ok = PUBLISHED.rstrip() + "\n\nNot all results reproduce: three diverge.\n"
    assert _problems(ok) == []


def test_the_summary_section_is_required_and_the_report_must_say_more_than_it():
    import re

    stripped = re.sub(r"<!-- e2er:summary begin.*?<!-- e2er:summary end -->\n", "", PUBLISHED, flags=re.S)
    assert any("no summary section" in p for p in _problems(stripped))
    assert _problems("") == ["reproduction_report.md is empty"]
    only = PUBLISHED[PUBLISHED.index(BEGIN) : PUBLISHED.index(END) + len(END)] + "\n"
    assert any("says nothing beyond the counts" in p for p in _problems(only))
    # the comparer's own contract check runs before e2er writes the section
    assert markdown_problems(stripped, REPORT, LOG, check_summary=False) == []
