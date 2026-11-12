"""What a reproduction needs, and the data with their terms (src/core/repro_requirements.py).

Owner's request, 2026-11-12: every study gets a "Required for reproduction" block (software, accounts and keys,
data access, effort, last rerun) and "Data and licences" (one row per source), generated from what e2er
already records, in the package (e2er-package.json, e2er-package/README.md), in the description sent to
e2er.org, and printed by `e2er inspect` and `e2er fetch`. Facts only from records: a missing fact is left
out. Packages made before the record are derived on the fly (the nine studies of 2026-11-12 printed sensibly).
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from src.cli_package import inspect
from src.core import prepublish as pp
from src.core import repro_requirements as rr
from src.core.export import package as pkg

GAIA_LOAD = {
    "connector": "gaia",
    "dataset": "Gaia Data Release 3 (ESA/Gaia/DPAC), Gaia ESA Archive",
    "version": "DR3",
    "retrieved_at": "2026-10-13T21:02:56Z",
    "terms_summary": "Gaia data are distributed under CC BY-NC 3.0 IGO.",
    "terms": "https://www.cosmos.esa.int/web/gaia-users/license",
    "citation": "Gaia Collaboration (2023).",
    "query": "https://gea.esac.esa.int/tap-server/tap/sync?QUERY=x",
    "saved_to": "data/gaia_dr3.csv",
    "fingerprint": {"form": "e2er-rows/1", "sha256": "ab" * 32, "rows": 3, "columns": ["a"]},
}
FRED_LOAD = {
    "connector": "fred",
    "dataset": "FRED, Federal Reserve Bank of St. Louis",
    "retrieved_at": "2026-10-01T10:00:00Z",
    "series": "CPIAUCSL",
    "table": "cpi",
    "terms_summary": "FRED's terms of use apply.",
}
GET_DATA = """\
RELOADS = [
    {"file": "data/gaia_dr3.csv", "args": ["gaia", "query", "--adql", "SELECT 1"], "what": "Gaia"},
]
"""
RECIPE = {
    "schema": "e2er-reproduce/1",
    "python": "3.12",
    "requirements": "code/requirements.txt",
    "files": {"run.py": "code/run.py", "get_data.py": "code/get_data.py", "data.db": "data/data.db"},
    "steps": [{"run": ["python", "get_data.py"]}, {"run": ["python", "run.py"]}],
    "inputs": [
        {"path": "data/gaia_dr3.csv", "reload": "get_data.py", "sha256": "0" * 64},
        {"path": "data.db"},
    ],
    "compare": [{"published": "results/estimation_results.json", "produced": "estimation_results.json"}],
}


def _reader(files: dict[str, str | dict | list]) -> rr.Reader:
    def read(rel: str) -> bytes | None:
        v = files.get(rel)
        if v is None:
            return None
        return (v if isinstance(v, str) else json.dumps(v)).encode()

    return read


def _manifest(**over: object) -> dict:
    m = {
        "contents": [{"path": p} for p in ("reproduce.json", "code/get_data.py", "code/run.py", "data/data.db",
                                           "e2er-package/requirements.lock.txt", "data/data_sources.json")],
        "left_out": [],
        "environment": {"python": "3.12", "lock": "e2er-package/requirements.lock.txt", "hashes": True},
        "study": {"e2er_version": "0.20.1"},
    }  # fmt: skip
    m.update(over)
    return m


FILES = {
    "reproduce.json": RECIPE,
    "code/get_data.py": GET_DATA,
    "data/data_sources.json": {"loads": [GAIA_LOAD, FRED_LOAD]},
    "e2er-package/requirements.lock.txt": "numpy==2.5.4 \\\n    --hash=sha256:"
    + "a" * 64
    + "\npandas==2.3.3\n# c==1\n",
}


def test_record_from_the_package_list_and_files():
    rec = rr.derive(_manifest(), _reader(FILES))
    assert rec["format"] == rr.FORMAT and rec["reproducible"] is True
    assert rec["software"] == {
        "docker": True,
        "e2er": "0.20.1",
        "python": "3.12",
        "packages": {"file": "e2er-package/requirements.lock.txt", "count": 2, "hashes": True},
    }
    gaia, fred = rec["sources"]
    # The Gaia load is not in the package and get_data.py's RELOADS loads it again, from the host it read.
    assert gaia["name"] == "ESA Gaia Archive" and gaia["reloaded"] == 1 and gaia["shipped"] == 0
    assert gaia["from"] == ["gea.esac.esa.int"] and gaia["versions"] == ["DR3"] and gaia["loaded"] == ["2026-10-13"]
    assert gaia["fingerprints"] == ["sha256:" + "ab" * 32] and gaia["fingerprints_missing"] == 0
    assert gaia["left_out_because"] == [
        "its terms allow non-commercial use only, with credit to ESA/Gaia/DPAC (CC BY-NC 3.0 IGO)"
    ]
    # FRED's table is in data.db, which the package holds: shipped, so its key is not needed for a rerun.
    assert fred["shipped"] == 1 and fred["reloaded"] == 0 and fred["fingerprints_missing"] == 1
    assert rec["accounts"] == [
        {
            "source": "fred",
            "name": "FRED",
            "setting": "FRED_API_KEY",
            "how": "Get a free key (~30s) at https://fredaccount.stlouisfed.org/apikey",
            "optional": False,
            "needed": False,
        }
    ]
    assert rec["data"]["network"] is True and rec["data"]["reload_step"] == "code/get_data.py"
    assert rec["data"]["shipped"] == ["data/data.db"]


def test_a_key_is_needed_only_when_its_data_are_loaded_again():
    files = dict(
        FILES, **{"data/data_sources.json": {"loads": [{**FRED_LOAD, "table": None, "saved_to": "data/cpi.csv"}]}}
    )
    recipe = dict(RECIPE, inputs=[{"path": "data/cpi.csv", "reload": "get_data.py"}])
    files["reproduce.json"] = recipe
    files["code/get_data.py"] = 'RELOADS = [{"file": "data/cpi.csv", "args": ["fred", "series"]}]\n'
    rec = rr.derive(_manifest(), _reader(files))
    assert rec["accounts"][0]["needed"] is True
    line = rr.accounts_line(rec)
    assert line.startswith("FRED: FRED_API_KEY (Get a free key") and "passes no API key or token" in line


def test_a_left_out_file_names_its_reason_and_tables_no_step_reads():
    left = [
        {
            "path": "data/data.db",
            "reason": "too large for GitHub (145 MB)",
            "kind": "size",
            "needed": True,
            "loads": ["texts"],
            "not_read": ["books"],
            "rebuilt_by": {"by": "code/get_data.py", "source": "x"},
        }
    ]
    loads = [
        {"connector": "gutenberg", "table": "texts", "retrieved_at": "2026-10-14T18:47:53Z",
         "query": "https://gutenberg.pglaf.org/cache/epub/1/pg1.txt"},
        {"connector": "gutenberg", "table": "books", "retrieved_at": "2026-10-14T18:05:48Z"},
    ]  # fmt: skip
    files = dict(FILES, **{"data/data_sources.json": {"loads": loads}, "code/get_data.py": "print(1)\n"})
    contents = [c for c in _manifest()["contents"] if c["path"] != "data/data.db"]
    rec = rr.derive(_manifest(contents=contents, left_out=left), _reader(files))
    (g,) = rec["sources"]
    assert (g["reloaded"], g["not_needed"], g["shipped"]) == (1, 1, 0)
    assert g["left_out_because"] == ["data/data.db: too large for GitHub (145 MB)"]
    assert rr.placement_words(g) == (
        "left out (data/data.db: too large for GitHub (145 MB)); a rerun loads 1 of them again; "
        "1 load the study's code does not read"
    )
    assert rec["data"]["left_out"][0]["path"] == "data/data.db" and rec["data"]["left_out"][0]["needed"] is True


def test_a_hand_written_get_data_py_loads_the_inputs_the_package_lacks():
    """spot-bitcoin-etf-comovement: its get_data.py has no RELOADS; reproduce takes the missing inputs as reloaded."""
    loads = [{"connector": "yfinance", "saved_to": "data/px_BTC_USD.csv", "retrieved_at": "2026-10-05T07:57:21Z"}]
    recipe = dict(RECIPE, inputs=[{"path": "data/px_BTC_USD.csv"}])
    files = dict(FILES, **{"data/data_sources.json": {"loads": loads}, "code/get_data.py": "EXTRACTS = {}\n"})
    files["reproduce.json"] = recipe
    rec = rr.derive(_manifest(), _reader(files))
    (y,) = rec["sources"]
    assert y["reloaded"] == 1 and y["left_out_because"] == ["its terms allow personal use only"]
    assert rec["accounts"] == [] and rr.accounts_line(rec) == "none"


def test_no_recipe_no_docker_and_nothing_invented():
    rec = rr.derive(_manifest(recipe={"present": False, "why": "the study has no estimation results"}), _reader({}))
    assert rec["reproducible"] is False and rec["why"] == "the study has no estimation results"
    assert rec["software"] == {"docker": False, "e2er": "0.20.1"} and rec["sources"] == []
    text = "\n".join(rr.summary_lines(rec))
    assert "not possible: the study has no estimation results" in text and "Effort" not in text
    assert "Last rerun: none recorded in the package" in text


def test_get_data_reloads_is_read_never_run(tmp_path):
    marker = tmp_path / "ran"
    src = f"open({str(marker)!r}, 'w').write('x')\nRELOADS = [{{'table': 't'}}]\n"
    assert rr.get_data_reloads(src) == [{"table": "t"}] and not marker.exists()
    assert rr.get_data_reloads("RELOADS = [__import__('os').system('true')]") is None
    assert rr.get_data_reloads("def (") is None


def test_effort_and_last_rerun_come_from_the_rerun_before_publishing():
    rerun = rr.rerun_of(
        {
            "verification": [
                {
                    "check": "reproduction",
                    "status": "PASS",
                    "reproduction": {
                        "reproduced": True,
                        "date": "2026-11-12T09:30:00Z",
                        "e2er_version": "0.21.0",
                        "verdict": "Reproduced.",
                        "seconds": 1512.3,
                        "reload_seconds": 1300.0,
                        "reloaded_sources": ["Project Gutenberg"],
                    },
                }
            ]
        }
    )
    assert rr.effort_line(962647, rerun) == (
        "downloading the package: 940.1 KB; the rerun before publishing took about 25 minutes, mostly loading "
        "data again from Project Gutenberg"
    )
    assert rr.rerun_line(rerun) == "reproduced before publishing on 2026-11-12 with e2er 0.21.0: Reproduced."
    assert rr.effort_line(None, {"reproduced": True, "date": "x"}) == ""  # no time recorded: none said


def test_prepublish_records_the_rerun_s_time():
    report = {
        "steps": [{"seconds": 247.4, "reload": True}, {"seconds": 2.1, "reload": False}, {"seconds": 2.7}],
        "sources": [{"source": "ESA Gaia Archive"}, {"source": "ESA Gaia Archive"}],
        "host": {"e2er_version": "0.21.0"},
        "exit_code": 0,
    }
    rec = pp.record_from(report)["reproduction"]
    assert (
        rec["seconds"] == 252.2 and rec["reload_seconds"] == 247.4 and rec["reloaded_sources"] == ["ESA Gaia Archive"]
    )
    assert "seconds" not in pp.record_from({"steps": [], "exit_code": 0})["reproduction"]


def _old_package(tmp_path: Path) -> Path:
    """A package as e2er 0.20 wrote it: no reproduction_requirements in its list."""
    files = {k: (v if isinstance(v, str) else json.dumps(v)).encode() for k, v in FILES.items()}
    files["data/data.db"] = b"SQLite format 3\x00"
    contents = [{"path": p, "sha256": "0" * 64, "bytes": len(b), "part": "study"} for p, b in sorted(files.items())]
    manifest = {
        "format": pkg.FORMAT,
        "e2er_version": "0.20.0",
        "study": {"title": "Old", "e2er_version": "0.17.0"},
        "contents": contents,
        "fingerprint": pkg.fingerprint(contents),
        "left_out": [],
        "environment": {"python": "3.12", "lock": "e2er-package/requirements.lock.txt", "hashes": True},
        "recipe": {"present": True},
    }
    path = tmp_path / "old.e2er"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(pkg.MANIFEST, json.dumps(manifest))
        for rel, b in files.items():
            zf.writestr(rel, b)
    return path


def test_inspect_derives_the_block_for_an_old_package(tmp_path, capsys):
    path = _old_package(tmp_path)
    rec, derived = rr.of_package(path)
    assert derived and rec is not None and rec["software"]["e2er"] == "0.17.0"
    inspect(str(path))
    out = capsys.readouterr().out
    assert "Required for reproduction (derived now from the package's files):" in out
    assert "Accounts and keys: none (the study loaded FRED with a key; a rerun does not load those data again)" in out
    assert "loaded again from ESA Gaia Archive (gea.esac.esa.int) (1 load)" in out
    assert "Data and licences:" in out and "fingerprint: abababababab" in out and rr.FINGERPRINT_WORDS in out
    assert "FRED, loaded 2026-10-01: with the package" in out
    assert "fingerprint: not recorded (e2er records it since 0.21)" in out


def test_pack_writes_the_record_and_the_package_readme(tmp_path):
    folder = tmp_path / "study"
    (folder / "code").mkdir(parents=True)
    (folder / "data").mkdir()
    (folder / "results").mkdir()
    (folder / "provenance.json").write_text(json.dumps({"run": {"e2er_version": "0.20.1", "exported_at": "20261110"}}))
    (folder / "code" / "run.py").write_text("print(1)\n")
    (folder / "code" / "get_data.py").write_text(GET_DATA)
    (folder / "code" / "requirements.txt").write_text("numpy==2.5.4\n")
    (folder / "data" / "data.db").write_bytes(b"SQLite format 3\x00")
    (folder / "data" / "data_sources.json").write_text(json.dumps({"loads": [GAIA_LOAD, FRED_LOAD]}))
    (folder / "results" / "estimation_results.json").write_text("{}")
    inputs = [
        {"path": "data/gaia_dr3.csv", "reload": "get_data.py", "sha256": "0" * 64},
        {"path": "data.db", "sha256": "1" * 64},
    ]
    (folder / "reproduce.json").write_text(json.dumps(dict(RECIPE, inputs=inputs)))
    packed = pkg.build(folder, tmp_path / "s.e2er", locker=lambda req, py, as_of: ("numpy==2.5.4\n", ""))
    rec = packed.manifest[rr.KEY]
    assert rec["software"]["packages"] == {"file": "e2er-package/requirements.lock.txt", "count": 1, "hashes": False}
    assert [s["connector"] for s in rec["sources"]] == ["gaia", "fred"]
    listed = {c["path"]: c for c in packed.manifest["contents"]}
    assert rr.README in listed and listed[rr.README]["part"] == "package"
    readme = pkg.read_member(packed.path, rr.README)
    assert readme is not None
    text = readme.decode()
    assert "## Required for reproduction" in text and "## Data and licences" in text
    assert "| ESA Gaia Archive | DR3 | 2026-10-13 |" in text and "`abababababab`" in text
    # The record in the list is the one inspect prints, not derived again.
    assert rr.of_package(packed.path) == (rec, False)


@pytest.mark.parametrize(
    ("seconds", "words"),
    [(35, "about 35 seconds"), (95, "about 2 minutes"), (1512, "about 25 minutes"), (7200, "about 2 hours")],
)
def test_duration(seconds, words):
    assert rr.duration(seconds) == words
