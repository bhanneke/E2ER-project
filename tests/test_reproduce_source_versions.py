"""Data versions for data a study cannot ship: each load's fingerprint, and what `e2er reproduce` says about it.

The real test of 2026-11-12: road-traffic-death-rates-2021 reloaded WHO GHO data, and the study's own
clean_rs198.py stopped with "unit check failed ... values outside 0-50 per 100,000: 2". The report said only
"the step failed". Since then every load records a fingerprint of the rows it returned, a rerun compares the
reload's fingerprint with the study's, and a step that fails after the source changed names that change as the
likely cause (category "source_changed" in the JSON report).
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from types import SimpleNamespace

from src.cli_reproduce import reproduce
from src.core import reproduce as rp
from src.core import reproduce_sources as rsrc
from src.modules.data import load_record as lr
from tests.test_reproduce import _study

ROWS = [
    {"location": "AAA", "year": 2021, "value": 12.5},
    {"location": "BBB", "year": 2021, "value": 3.0},
    {"location": "CCC", "year": 2021, "value": None},
]


# ── the canonical form ───────────────────────────────────────────────────────


def test_the_fingerprint_ignores_the_order_of_rows_and_columns_and_whole_floats():
    fp = lr.fingerprint_rows(ROWS)
    assert fp is not None and fp["form"] == "e2er-rows/1" and fp["rows"] == 3
    assert fp["columns"] == ["location", "value", "year"]
    shuffled = [
        {"value": None, "location": "CCC", "year": 2021},
        {"year": 2021.0, "value": 3, "location": "BBB"},  # 2021.0 and 3: the same numbers as 2021 and 3.0
        {"value": 12.5, "year": 2021, "location": "AAA"},
    ]
    assert lr.fingerprint_rows(shuffled)["sha256"] == fp["sha256"]
    nan = [dict(r) for r in ROWS]
    nan[2]["value"] = math.nan  # NaN is written as null, as a missing value
    assert lr.fingerprint_rows(nan)["sha256"] == fp["sha256"]


def test_other_data_give_another_fingerprint():
    fp = lr.fingerprint_rows(ROWS)["sha256"]
    changed = [dict(r) for r in ROWS]
    changed[0]["value"] = 12.6
    assert lr.fingerprint_rows(changed)["sha256"] != fp
    assert lr.fingerprint_rows(ROWS[:2])["sha256"] != fp
    renamed = [{("val" if k == "value" else k): v for k, v in r.items()} for r in ROWS]
    assert lr.fingerprint_rows(renamed)["sha256"] != fp


def test_the_canonical_form_is_pinned():
    """The documented form, byte for byte: changing it would make every recorded fingerprint "different"."""
    import hashlib

    text = '["location","value","year"]\n["AAA",12.5,2021]\n["BBB",3,2021]\n["CCC",null,2021]\n'
    assert lr.fingerprint_rows(ROWS)["sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_a_load_without_rows_gets_no_fingerprint():
    assert lr.with_fingerprint({"connector": "x"}, []) == {"connector": "x"}
    assert lr.with_fingerprint({"connector": "x"}, None) == {"connector": "x"}
    assert lr.with_fingerprint({"connector": "x"}, ROWS)["fingerprint"]["rows"] == 3


def test_e2er_data_records_the_fingerprint_with_the_load(tmp_path: Path, monkeypatch):
    from src.modules.data import cli

    monkeypatch.setattr(cli, "_resolve_workspace", lambda paper_id: tmp_path)
    result = {"items": ROWS, "saved_table": "road_deaths", "saved_table_rows": 3}
    entry = {"connector": "who_gho", "retrieved_at": "2026-11-12T10:00:00Z", "request": {"command": "data"}}
    cli._record(result, SimpleNamespace(paper_id="p", specialist="researcher"), entry)
    [load] = json.loads((tmp_path / "data_sources.json").read_text(encoding="utf-8"))["loads"]
    assert load["fingerprint"] == lr.fingerprint_rows(ROWS)
    assert load["rows"] == 3 and load["retrieved_at"] == "2026-11-12T10:00:00Z" and load["request"]


def test_the_dossier_lists_the_fingerprint_and_old_loads_stay_as_they_were(tmp_path: Path):
    from src.core.dossier import _data_sources

    (tmp_path / "data").mkdir()
    old = {"connector": "who_gho", "dataset": "GHO", "table": "a"}
    new = {**old, "table": "b", "fingerprint": lr.fingerprint_rows(ROWS)}
    (tmp_path / "data" / "data_sources.json").write_text(json.dumps({"loads": [old, new]}), encoding="utf-8")
    first, second = _data_sources(tmp_path)
    assert "fingerprint" not in first
    assert second["fingerprint"] == {"form": "e2er-rows/1", "sha256": new["fingerprint"]["sha256"], "rows": 3}


# ── comparing a reload with the study's record ───────────────────────────────


def _records(folder: Path, run: Path, old: list[dict], new: list[dict]) -> None:
    (folder / "data").mkdir(parents=True, exist_ok=True)
    run.mkdir(parents=True, exist_ok=True)
    (folder / "data" / "data_sources.json").write_text(json.dumps({"loads": old}), encoding="utf-8")
    (run / "data_sources.json").write_text(json.dumps({"loads": new}), encoding="utf-8")


def _load(rows: list[dict] | None, when: str, **extra) -> dict:
    out = {"connector": "who_gho", "table": "road_deaths", "retrieved_at": when, "version": "2024-04-15", **extra}
    if rows is not None:
        out["fingerprint"] = lr.fingerprint_rows(rows)
    return out


def test_the_same_data_and_other_data_are_said_plainly(tmp_path: Path):
    folder, run = tmp_path / "study", tmp_path / "run"
    changed = [dict(r) for r in ROWS] + [{"location": "DDD", "year": 2021, "value": 55.0}]
    _records(folder, run, [_load(ROWS, "2026-10-14T08:00:00Z")], [_load(changed, "2026-11-12T09:00:00Z")])
    [entry] = rsrc.compare(folder, run)
    assert entry["status"] == rsrc.CHANGED
    assert entry["recorded"] == lr.fingerprint_rows(ROWS)["sha256"]
    assert entry["sentence"].startswith(
        "WHO Global Health Observatory (road_deaths) returned different data than on 2026-10-14 (recorded sha256:"
    )
    assert "3 rows then, 4 now" in entry["sentence"]
    _records(folder, run, [_load(ROWS, "2026-10-14T08:00:00Z")], [_load(ROWS[::-1], "2026-11-12T09:00:00Z")])
    [entry] = rsrc.compare(folder, run)
    assert entry["status"] == rsrc.SAME and "returned the same data as on 2026-10-14" in entry["sentence"]


def test_a_study_recorded_before_fingerprints_says_so(tmp_path: Path):
    folder, run = tmp_path / "study", tmp_path / "run"
    files_then = [{"url": "https://ghoapi.example/RS_198", "sha256": "a" * 64}]
    files_now = [{"url": "https://ghoapi.example/RS_198", "sha256": "b" * 64}]
    _records(
        folder,
        run,
        [_load(None, "2026-10-13T20:59:49Z", files=files_then)],
        [_load(ROWS, "2026-11-12T09:00:00Z", files=files_now)],
    )
    [entry] = rsrc.compare(folder, run)
    assert entry["status"] == rsrc.NOT_RECORDED and entry["files_differ"] is True
    assert "the source fingerprint was not recorded when the study loaded these data (2026-10-13" in entry["sentence"]
    assert "differs byte for byte from the one the study recorded" in entry["sentence"]


def test_loads_that_were_there_before_the_steps_are_not_compared(tmp_path: Path):
    folder, run = tmp_path / "study", tmp_path / "run"
    _records(folder, run, [_load(ROWS, "2026-10-14T08:00:00Z")], [_load(ROWS[:1], "2026-10-14T08:00:00Z")])
    assert rsrc.compare(folder, run, rsrc.snapshot(run)) == []


def test_a_failed_step_after_a_source_change_names_the_change_as_the_likely_cause():
    moved = [{"source": "WHO Global Health Observatory", "status": rsrc.CHANGED, "recorded_at": "2026-10-14"}]
    text, category = rsrc.judge("Could not reproduce: the step `python clean.py` failed.", 2, moved)
    assert category == rsrc.SOURCE_CHANGED
    assert text == (
        "Could not reproduce: the step `python clean.py` failed. WHO Global Health Observatory returned different "
        "data than on 2026-10-14: the change at the source is the likely cause, not the study's code."
    )
    text, category = rsrc.judge("Not reproduced exactly: 1 differ.", 1, moved)
    assert category == rsrc.SOURCE_CHANGED and text.endswith("the likely cause of the differences.")
    assert rsrc.judge("Reproduced: …", 0, moved) == ("Reproduced: …", rsrc.REPRODUCED)
    assert rsrc.judge("Could not reproduce: x.", 2, []) == ("Could not reproduce: x.", rsrc.COULD_NOT_RUN)
    same = [{"source": "S", "status": rsrc.SAME}]
    assert rsrc.judge("Not reproduced exactly: 1 differ.", 1, same)[1] == rsrc.NOT_REPRODUCED
    unknown = [{"source": "S", "status": rsrc.NOT_RECORDED}]
    text, category = rsrc.judge("Could not reproduce: x.", 2, unknown)
    assert category == rsrc.COULD_NOT_RUN and "recorded no fingerprint" in text


# ── a full rerun ─────────────────────────────────────────────────────────────

#: get_data.py as e2er-data would run it: writes the input and records the load (with today's rows).
GET_DATA = """\
import json, os
rows = {rows}
os.makedirs("data", exist_ok=True)
open("data/x.csv", "w").write("".join(str(r["value"]) + "\\n" for r in rows))
load = {{"connector": "who_gho", "saved_to": "data/x.csv", "retrieved_at": "2026-11-12T09:00:00Z"}}
fp = {fingerprint}
if fp:
    load["fingerprint"] = fp
json.dump({{"loads": [load]}}, open("data_sources.json", "w"))
"""

CHECK = """\
vals = [float(x) for x in open("data/x.csv").read().split()]
assert all(0 <= v <= 50 for v in vals), "unit check failed: values outside 0-50 per 100,000: %d" % sum(
    1 for v in vals if not 0 <= v <= 50
)
"""


def _source_study(tmp_path: Path, *, now: list[dict], recorded: bool) -> Path:
    folder = _study(tmp_path, {"main": {"estimate": 2.333333, "n": 3, "label": "ok"}})
    (folder / "data" / "x.csv").unlink()
    then = [{"value": 1}, {"value": 2}, {"value": 4}]
    record = {"connector": "who_gho", "saved_to": "data/x.csv", "retrieved_at": "2026-10-14T08:00:00Z"}
    if recorded:
        record["fingerprint"] = lr.fingerprint_rows(then)
    (folder / "data" / "data_sources.json").write_text(json.dumps({"loads": [record]}), encoding="utf-8")
    script = GET_DATA.format(rows=repr(now), fingerprint=repr(lr.fingerprint_rows(now)))
    (folder / "code" / "get_data.py").write_text(script, encoding="utf-8", newline="\n")
    (folder / "code" / "check.py").write_text(CHECK, encoding="utf-8", newline="\n")
    recipe = json.loads((folder / rp.RECIPE_FILE).read_text(encoding="utf-8"))
    recipe["files"] = {
        "run.py": "code/run.py",
        "get_data.py": "code/get_data.py",
        "check.py": "code/check.py",
        "data/x.csv": "data/x.csv",
    }
    recipe["steps"][:0] = [
        {"run": ["python", "get_data.py"], "about": "load the inputs again"},
        {"run": ["python", "check.py"], "about": "data preparation"},
    ]
    recipe["inputs"][0].update({"reload": "get_data.py", "source": "WHO GHO"})
    (folder / rp.RECIPE_FILE).write_text(json.dumps(recipe), encoding="utf-8", newline="\n")
    return folder


def test_a_step_that_fails_after_the_source_changed_says_so(tmp_path: Path, capsys):
    now = [{"value": 1}, {"value": 2}, {"value": 4}, {"value": 55}, {"value": 70}]
    folder = _source_study(tmp_path, now=now, recorded=True)
    out_json = tmp_path / "report.json"
    assert reproduce(str(folder), json_out=str(out_json), yes=True, sandbox=False) == 2
    text = capsys.readouterr().out
    assert "Sources loaded again, compared with the study's record of each load:" in text
    assert "WHO Global Health Observatory (data/x.csv) returned different data than on 2026-10-14" in text
    assert "the change at the source is the likely cause, not the study's code." in text
    doc = json.loads(out_json.read_text(encoding="utf-8"))
    assert doc["exit_code"] == 2 and doc["category"] == "source_changed"
    [source] = doc["sources"]
    assert source["status"] == "changed" and source["rows_recorded"] == 3 and source["rows_now"] == 5
    assert doc["host"]["e2er_version"] and doc["host"]["system"] and doc["host"]["python"]


def test_a_study_recorded_before_fingerprints_says_it_cannot_tell(tmp_path: Path, capsys):
    now = [{"value": 1}, {"value": 2}, {"value": 70}]
    folder = _source_study(tmp_path, now=now, recorded=False)
    out_json = tmp_path / "report.json"
    assert reproduce(str(folder), json_out=str(out_json), yes=True, sandbox=False) == 2
    text = capsys.readouterr().out
    assert "the source fingerprint was not recorded when the study loaded these data (2026-10-14" in text
    doc = json.loads(out_json.read_text(encoding="utf-8"))
    assert doc["category"] == "could_not_run" and doc["sources"][0]["status"] == "not_recorded"


def test_the_same_data_from_the_source_reproduce(tmp_path: Path, capsys):
    folder = _source_study(tmp_path, now=[{"value": 4}, {"value": 1}, {"value": 2}], recorded=True)
    out_json = tmp_path / "report.json"
    assert reproduce(str(folder), json_out=str(out_json), yes=True, sandbox=False) == 0
    text = capsys.readouterr().out
    assert "returned the same data as on 2026-10-14" in text
    doc = json.loads(out_json.read_text(encoding="utf-8"))
    assert doc["category"] == "reproduced" and doc["sources"][0]["status"] == "same"


# ── a corpus: which texts changed; a source that did not answer ─────────────


def test_a_corpus_load_names_the_texts_that_changed(tmp_path: Path):
    folder, run = tmp_path / "study", tmp_path / "run"
    then = {"2276": {"sha256": "a" * 64}, "7987": {"sha256": "b" * 64}}
    now = {"2276": {"sha256": "a" * 64}, "7987": {"sha256": "c" * 64}}
    old = {"connector": "gutenberg", "table": "texts_c1", "retrieved_at": "2026-10-14T08:00:00Z", "texts": then}
    new = {"connector": "gutenberg", "table": "texts_c1", "retrieved_at": "2026-11-12T08:00:00Z", "texts": now}
    old["fingerprint"] = lr.fingerprint_rows([{"id": 1, "text": "x"}])
    new["fingerprint"] = lr.fingerprint_rows([{"id": 1, "text": "y"}])
    _records(folder, run, [old], [new])
    [entry] = rsrc.compare(folder, run)
    assert entry["status"] == rsrc.CHANGED and entry["parts_changed"] == ["ebook 7987"]
    assert entry["sentence"].endswith("; the texts that differ: ebook 7987.")


def test_a_corpus_recorded_before_fingerprints_names_the_files_that_changed(tmp_path: Path):
    """The weather-words study (recorded 2026-10-14): each book's file with its SHA-256, no fingerprint."""
    folder, run = tmp_path / "study", tmp_path / "run"
    url = "https://gutenberg.pglaf.org/cache/epub/{0}/pg{0}.txt"
    then = [{"url": url.format(i), "sha256": c * 64} for i, c in (("2276", "a"), ("7987", "b"))]
    now = [{"url": url.format(i), "sha256": c * 64} for i, c in (("2276", "a"), ("7987", "d"))]
    old = {"connector": "gutenberg", "table": "texts_c1", "retrieved_at": "2026-10-14T08:00:00Z", "files": then}
    new = {"connector": "gutenberg", "table": "texts_c1", "retrieved_at": "2026-11-12T08:00:00Z", "files": now}
    _records(folder, run, [old], [new])
    [entry] = rsrc.compare(folder, run)
    assert entry["status"] == rsrc.NOT_RECORDED and entry["parts_changed"] == ["ebook 7987"]
    assert "the files that differ: ebook 7987 (SHA-256, against the study's record)" in entry["sentence"]


def test_the_gutenberg_connector_records_each_texts_fingerprint():
    import inspect

    from src.modules.data.sources import gutenberg

    assert '"texts": texts' in inspect.getsource(gutenberg)


def _failed_reload(tmp_path: Path, output: str):
    log = tmp_path / "step-1.log"
    log.write_text(output, encoding="utf-8")
    return rp.StepResult("python get_data.py", "load again", 1, 1255.0, "", str(log), reload=True)


GUTENDEX = (
    "gutenberg_texts_c3: not loaded (Gutendex, the catalogue e2er checks each book's copyright status with, did not "
    "answer within 45 s. No text was loaded; try again later.); trying again in 30 s\n"
    "Could not load:\n  gutenberg_texts_c3 (Project Gutenberg ebooks): Gutendex, the catalogue e2er checks each "
    "book's copyright status with, did not answer within 45 s. No text was loaded; try again later.\n"
)


def test_a_source_that_did_not_answer_is_neither_a_change_nor_a_code_failure(tmp_path: Path):
    step = _failed_reload(tmp_path, GUTENDEX)
    text, category = rsrc.judge("Could not reproduce: the step `python get_data.py` failed.", 2, [], [step])
    assert category == rsrc.SOURCE_UNAVAILABLE
    assert text.startswith("Could not reproduce yet: a source did not answer while `python get_data.py` loaded")
    assert "did not answer within 45 s" in text and "not a failure of the study's code" in text
    assert "run the same command again later" in text


def test_a_failed_reload_without_a_time_out_is_not_called_unavailable(tmp_path: Path):
    step = _failed_reload(tmp_path, "Traceback ...\nKeyError: 'value'\n")
    assert rsrc.judge("Could not reproduce: x.", 2, [], [step])[1] == rsrc.COULD_NOT_RUN
    later = rp.StepResult("python clean.py", "prepare", 1, 1.0, "timed out reading", "", reload=False)
    assert rsrc.judge("Could not reproduce: x.", 2, [], [later])[1] == rsrc.COULD_NOT_RUN


def test_a_reload_into_a_file_matches_the_studys_load_into_a_table_and_that_file(tmp_path: Path):
    """The Gaia study recorded a table and data/gaia_dr3.csv; its get_data.py saves the file alone."""
    folder, run = tmp_path / "study", tmp_path / "run"
    old = {"connector": "gaia", "table": "gaia_dr3", "saved_to": "data/gaia_dr3.csv", "retrieved_at": "2026-10-13"}
    new = {"connector": "gaia", "saved_to": "data/gaia_dr3.csv", "retrieved_at": "2026-11-12T09:00:00Z"}
    new["fingerprint"] = lr.fingerprint_rows(ROWS)
    _records(folder, run, [old], [new])
    [entry] = rsrc.compare(folder, run)
    assert entry["status"] == rsrc.NOT_RECORDED and entry["loaded_into"] == "data/gaia_dr3.csv"


def test_a_new_version_by_the_sources_own_account_counts_as_a_change_without_a_fingerprint():
    """road-traffic-death-rates-2021 (recorded 2026-10-13, no fingerprint): the WHO GHO now names 2026-10-15
    as its latest update, the study loaded the 2024-04-15 data; clean_rs198.py's unit check then failed."""
    unknown = [
        {
            "source": "WHO Global Health Observatory",
            "status": rsrc.NOT_RECORDED,
            "recorded_at": "2026-10-13",
            "version_recorded": "2024-04-15",
            "version_now": "2026-10-15",
        }
    ]
    text, category = rsrc.judge("Could not reproduce: the step `python clean_rs198.py` failed.", 2, unknown)
    assert category == rsrc.SOURCE_CHANGED
    assert text.endswith(
        "WHO Global Health Observatory now gives version 2026-10-15 of its data; the study loaded version "
        "2024-04-15 on 2026-10-13: the change at the source is the likely cause, not the study's code."
    )


def test_a_version_that_is_only_the_day_of_the_load_is_not_a_source_version():
    assert rsrc._version({"version": "2026-11-12", "retrieved_at": "2026-11-12T08:00:00Z"}) == ""
    assert rsrc._version({"version": "DR3", "retrieved_at": "2026-11-12T08:00:00Z"}) == "DR3"


def test_many_loads_of_one_source_without_fingerprints_share_one_line():
    from src.cli_reproduce import rsrc_lines

    yahoo = [
        {"source": "Yahoo Finance", "status": "not_recorded", "loaded_into": f"data/px_{t}.csv",
         "recorded_at": "2026-10-05", "sentence": f"Yahoo Finance (data/px_{t}.csv): ..."}
        for t in ("BTC", "ETH", "SOL", "XRP", "SPY", "QQQ")
    ]  # fmt: skip
    who = {"source": "WHO", "status": "changed", "sentence": "WHO returned different data than on 2026-10-14."}
    lines = rsrc_lines([*yahoo, who])
    assert lines == [
        "Yahoo Finance (6 loads: data/px_BTC.csv, data/px_ETH.csv, data/px_SOL.csv, data/px_XRP.csv and 2 more): the "
        "source fingerprint was not recorded when the study loaded these data (e2er records it since 0.21; "
        "2026-10-05), so e2er cannot say whether the source now returns other data.",
        "WHO returned different data than on 2026-10-14.",
    ]
