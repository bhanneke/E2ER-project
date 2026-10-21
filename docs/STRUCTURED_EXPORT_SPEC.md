# Spec — Structured paper export (DRAFT for review)

> **Status:** spec only, not implemented. Edit the layout / decisions below and
> hand it back. Separate feature from the BYOD-SQLite PR (#81).

## Problem

A run's workspace (`Tests/workspaces/<uuid>/`) is a **flat scratch dir** — throwaway
probe scripts, `.tex`, `.json`, `.md`, `data/`, `data.db`, `literature/` all dumped
together. It's load-bearing for the pipeline (specialists write artifacts by hardcoded
filename via `SPECIALIST_ARTIFACTS`; resume + context builders read them there), so we
must **not** reorganize it in place. Instead, add an **export** step that assembles a
clean, navigable project tree **in a folder the user chose**, leaving the workspace
untouched.

## Proposed layout  ← **the part to shape**

```
<OUTPUT_DIR>/<slug>/
├── README.md            generated: research question, internal quality review score, key result, how to reproduce
├── reproduce.json       how `e2er reproduce` runs the study's code again (written at export, see below)
├── paper/
│   ├── paper.pdf        compiled (if the LaTeX compile succeeded)
│   ├── paper.tex        ← paper_draft.tex
│   ├── abstract.tex
│   └── refs.bib         ← literature.bib
├── code/
│   ├── run_estimation.py
│   └── scratch/         the model's throwaway probes (_explore.py, _diag.py, profile.py, *.log)
├── data/
│   ├── data.db          the per-paper SQLite warehouse (copy or symlink — see D3)
│   ├── data_summary.md
│   └── data_dictionary.json
├── results/
│   ├── estimation_results.json
│   ├── robustness_results.json
│   ├── summary_statistics.json
│   ├── number_verification.json
│   └── figures/         figure_spec.json + any generated figures/tables
├── design/
│   ├── paper_plan.md
│   ├── identification_strategy.md
│   └── econometric_spec.md
└── reviews/
    ├── review_aggregation.json     the six scores and the combined score
    ├── review_mechanism.md
    ├── review_literature.md
    ├── review_*.md                 (technical / writing / data / identification, when present)
    ├── self_attack_report.json
    └── polish_*.md
```

### reproduce.json, written at export

`src/core/export/reproduce_recipe.py` writes the recipe from what the run
recorded, without a model and without running anything: the estimation script
(`run_estimation.py` or another name the runner looks for) and every later
script of the run that writes `estimation_results.json`, in the order the run
ran them (`.e2er-script-runs.jsonl` in the workspace, written by `e2er-run` and
by the runner; runs before 0.15.0 have none, and then the order is the one the
files were last changed in, which the recipe's notes say); every workspace file those scripts name (`data.db`,
`data/…`), laid out where they expect it, data files as inputs with their
SHA-256 and source from `data_sources.json`; `code/requirements.txt` with the
packages the scripts import at the versions of e2er's environment; and, for
Yahoo Finance and GMD data, `code/get_data.py`, which loads them again with
`e2er-data` (recorded series and dates) when the folder does not have them.
The scripts' copies in `code/` name the run folder instead of the workspace's
full path. A study without estimation results or without such a script gets no
recipe, and README.md says why; so does `e2er reproduce` on the folder.

A folder may come without `data.db` (a source's terms, or too large for GitHub),
so the recipe records how to get it back. `get_data.py` lists the loads of every
table a step reads, open sources too (Project Gutenberg, World Bank; when a source
with terms loaded a table, every table a source loaded), and loads one only when
the folder lacks it; that needs the internet and takes about as long as the run's
loads, which the recipe's notes say. The recipe then runs the data preparation:
the scripts that built the tables the estimation reads, and the tables those read,
in the order the run ran them. Those steps carry `"when_missing": ["data.db"]` and
run only when the folder lacks data.db. Who wrote a table comes from the script
log: since 0.17.1 each run records the tables of `data.db` it created, changed or
dropped (`tables: {"written": [...], "dropped": [...]}`, from the database before
and after the run, kept current in `.e2er-db-tables.json`), so a table written
under a name the code computes (`for name, t in [("corpus", corpus), …]:
t.to_sql(name, con)`) is traced too. For older runs the scripts' code answers:
`to_sql("t")`, `to_sql(f"t_{c}")`, `CREATE TABLE`/`INSERT INTO`, or `to_sql(name)`
with the table's name in a string of the script; tables read through an f-string
(`f"select … from gutenberg_texts_{c}"`) count as read. `reproduce.json`'s
`database` maps every table: `how` (`loaded`, `built`, `unknown`), `source` or `by`
(the script), `evidence` (`data_sources.json`, `script log`, `the scripts' code`),
`read` (a step reads it) and `back` (how a rerun without data.db gets it:
`get_data.py`, the preparation script, or null). A table no step reads (a
catalogue the study drew its sample from) is not loaded again; the `data.db` input
lists it in `not_read`, and a rebuilt database is compared without it. A small data
file a step reads (`data/sample_ids_v2.csv`) ships with the folder; when the script
log says which script made it, the input carries `made_by` (`script`, `file` in the
folder, `seeded` for a script that sets a random seed, `from`: the files it read that
other scripts made), and the notes say that the rerun reads the file rather than
drawing it again.
Table inputs (CSV/TSV, and each table of a SQLite database) also carry their
content (`rows`, `content_sha256`, or `tables`), order of rows aside: a reload
with the same rows in another order is the study's input. `numeric_sha256` is the
same fingerprint with every decimal number written with 12 significant digits: a
file the study's own preparation step builds again whose numbers differ only in
their last digits (pandas writing a parsed float back) is reported as "the same
rows, every decimal number equal to 12 significant digits" and counts as the
study's input; integers and text are compared exactly. A recipe written before
this field gets it from the package's record of the left-out file (below), only
where that record's `content_sha256` is the recipe's own.

`provenance.json` records under `run.results_from_code` which run of which
script wrote each results file (the script log's output hashes); `e2er verify`
checks the folder against it ("results from code").

### The .e2er package (format `e2er-package/1`)

`e2er pack <study id | exported folder> [-o PATH] [--offline] [--no-data]` writes an
exported folder into one file, `<slug>.e2er` (next to the folder unless `-o` says
otherwise); `e2er export --package` does the same after an export, and the finish page
offers it as "Download package (.e2er)". `e2er verify`, `e2er reproduce`, `e2er unpack
<file> [folder]` and `e2er inspect <file>` read it. Code: `src/core/export/package.py`.

**Container.** A zip archive, every entry compressed with deflate (level 6). The first
entry is `e2er-package.json`; every other entry follows in sorted order of its path.
Every entry carries the timestamp 1980-01-01 00:00:00 and the permissions `0644` of a
regular file; there are no directory entries, links or other kinds of entry. The same
folder therefore packs to the same bytes, wherever it lies and whatever its file times.

**Paths.** Relative, POSIX, NFC, inside the package: no absolute path or drive letter,
no `..` or `.` segment, no empty segment, no backslash, no control character
(`bundle_files.key_problem`), and no two paths that differ only in case.

**Contents.** The exported folder as `e2er verify` reads it (`bundle_files.walk`), without
dotfiles, operating-system clutter and `.e2er/` (local publishing records), plus the
package's own files under `e2er-package/`:

| Path | What |
|---|---|
| everything of the export | paper, code, results, design, reviews, `README.md`, `provenance.json`, `reproduce.json`, `report.html`, `e2er.json` when published, and the data (see below) |
| `e2er-package/requirements.lock.txt` | every package the code needs (the study's pins and what they need), one version each, with the SHA-256 of every file an installer may use (`uv pip compile --generate-hashes --universal`), resolved for the recipe's Python with releases up to the day after the export (`--exclude-newer`), so packing again later gives the same lock |
| `e2er-package/wheels/<platform>/*.whl` | `--offline` only: the wheels of the locked set for this computer (`pip download --only-binary=:all:`); `<platform>` is `<sys.platform>-<machine>-py<X.Y>`, e.g. `darwin-arm64-py3.14` |

**Data.** A data file (under `data/`, with a data ending: `.db`, `.csv`, `.parquet`, …)
from a source whose terms do not allow passing the data on (`data_terms.uses`: the GMD,
Yahoo Finance, the WHO GHO, Gaia, …) is left out; `--no-data` leaves out every data file
and every input the recipe lists. **Data built from such data are restricted too**
(`src/core/derived_data.py`): a data file a script writes after reading a restricted file or
table (directly or through module-level constants, `os.path.join`, `Path / "x"`; and, in a
workspace, every file its script-log runs recorded as `outputs`) inherits the restriction,
transitively. Export records them in `provenance.json` (`run.derived_data`: path, the
connectors, the scripts that write them), so the record holds also when a script is not
shipped; pack, publish and verify read that record and the folder's scripts. Such a file is
left out with the reason "built from ESA Gaia Data Release 3 (Gaia) data, whose terms do not
allow passing it on"; `e2er publish` treats it like the source's own data (the same
confirmation for public data) and warns when no recorded step builds it again. The records of the data (`data_sources.json`,
`data_dictionary.json`, `data_summary.md`) stay. A left-out file that the recipe lists as
an input with `"reload"` is rebuilt by `e2er reproduce`: `code/get_data.py` loads it again
and the data-preparation steps (`"when_missing"`) build the study's own tables. One that
the recipe cannot reload is named in the manifest's notes ("a rerun of the package cannot
rebuild it"); one the code does not read at all is left out without a note. A left-out
derived input is built again by the script that wrote it, when every restricted file or table
that script reads is loaded again by the recipe: export writes that step into the recipe
(`"rebuild": "clean_gaia.py"` on the input, a step with `"when_missing"` after `get_data.py`);
for a recipe written before, the package carries it in the manifest's `rebuild` list and
`e2er reproduce` adds it to the recipe it runs.

**Results built from restricted data** (`src/core/derived_rows.py`). Not only data files:
any output a script writes after reading restricted data (a results table, a weights list,
the data behind a figure, under `results/`, `misc/` or `paper/`; `.csv`, `.json`, `.txt`,
`.npy`, …) is built from it, and so is `results/figure_spec.json` in a study that loaded
restricted data, whoever wrote it. Such a file is left out like the source's data unless it
is an **aggregate**: a format e2er reads here (CSV/TSV, `.txt`/`.dat` columns, JSON,
JSONL, SQLite; Parquet, Excel, NumPy and pickle files count as row-level), at most
`row_limit` rows (a tenth of the source's rows, at most 50), no JSON array of more than
`point_limit` numbers or coordinate pairs (1% of the source's rows, at least 10, at most
50, never above `row_limit`) or more than `row_limit` records, no JSON object that is a set
of more than `row_limit` records, and no identifier of the source anywhere (a value of a
column whose values are all distinct, such as Gaia's `source_id` or a region's name; values
the study also loaded from a source without such terms, such as NUTS codes, are not the
source's). Lists of labels (the region codes of a cluster) are not point arrays. Gaia's
14,066 rows give 50 and 50, GISCO's 299 regions 29 rows and 10 points. A file under `data/`
is left out whatever it holds; rendered output (PDF, PNG, LaTeX tables) is never classified
and stays. The left-out reason says what holds the rows: "built from ESA Gaia Data
Release 3 (Gaia) data and holds them row by row (an array of 9,863 values at
figures[2].y); its terms do not allow passing them on". Export records for each derived
file whether it held the source's rows (`run.derived_data[].holds_rows`), so a copy without
the file can tell rows that were left out from an aggregate that must be there; for a
folder exported before, a missing derived file counts as left out.

A left-out output is rebuilt by `e2er reproduce` with the rest (the manifest's `rebuild`
list, `"output": true`): a file a step of the recipe writes needs nothing (`"written":
true`); a file a step reads (the units table the estimation reads) is built first by a
script that writes it without reading it, after the data are loaded again; any other is
built by its writer after the last step that writes a file it reads (`"after"`). Each such
file becomes an input marked `"output"` with its SHA-256 and content fingerprint, so the
report compares it with the study's file ("Files a published folder leaves out …, as the
rerun wrote them"); it does not change the verdict. In a folder that lacks such a file,
`e2er verify` counts it as left out (not missing) when the folder's own records say it
holds restricted rows; a check that needs it is skipped and says so: "needs
results/spatial_units.csv, left out under GISCO terms; run `e2er reproduce` to rebuild it"
(or "no recorded step rebuilds it").

**`e2er-package.json`.**

```json
{
  "format": "e2er-package/1",
  "e2er_version": "0.16.1",                 // the e2er that packed it
  "created": "20261014",                    // the export's date (provenance.json run.exported_at), not the packing time
  "study": {"id": "…", "title": "…", "question": "…", "authors": ["…"], "folder": "<slug>",
            "template": "…", "exported_at": "20261014", "e2er_version": "0.16.0", "purpose": "…"},
  "contents": [{"path": "code/run_estimation.py", "sha256": "…", "bytes": 27761, "part": "study"},
               {"path": "e2er-package/requirements.lock.txt", "sha256": "…", "bytes": 9120, "part": "package"}],
  "fingerprint": "sha256:…",                // SHA-256 of the canonical JSON of [{path, sha256, bytes}], sorted by path
  "left_out": [{"path": "data/data.db", "reason": "the terms of the Global Macro Database (GMD) do not allow passing the data on",
                "source": "gmd", "rebuilt_by": {"by": "code/get_data.py", "source": "…"},
                "needed": true,                 // needed: the recipe lists it as an input or lays it out (the code reads it)
                "loads": ["gmd_panel"],         // tables (or the file) get_data.py loads again from their sources
                "builds": [{"by": "code/scratch/clean.py", "what": ["panel_clean"]}],  // the study's own steps
                "not_built": [],                // tables no step loads or builds (a rerun cannot get them)
                "content": {"tables": {"gmd_panel": {"rows": 120, "content_sha256": "…", "numeric_sha256": "…"}}},
                "kind": "terms"},               // why: "terms" (a source's terms), "no_data" (--no-data), "size"
               {"path": "data/texts.db", "reason": "too large for GitHub (145 MB)", "kind": "size",
                "host": "GitHub", "bytes": 145076224, "rebuilt_by": {"by": "code/get_data.py", "source": "…"},
                "loads": ["…"], "builds": [], "needed": true}],
                // "size": only in a package made for a host (`e2er publish --github`): a data file larger than
                // the host takes that a recorded step loads or builds again (otherwise the publish is refused).
                // In a folder, `e2er verify` accepts it only when provenance.json records the file larger than
                // the host's limit (GitHub: 100 MiB).
  "rebuild": [{"path": "data/gaia_clean.csv", "script": "clean_gaia.py", "from": "code/scratch/clean_gaia.py"},
              {"path": "spatial_units.csv", "script": "build_data.py", "from": "code/scratch/build_data.py",
               "output": true, "folder": "results/spatial_units.csv", "sha256": "…",
               "content": {"rows": 236, "content_sha256": "…", "numeric_sha256": "…"}},
              {"path": "spatial_weights_knn8.csv", "script": "run_estimation.py", "from": "code/run_estimation.py",
               "output": true, "written": true, "folder": "results/spatial_weights_knn8.csv", "sha256": "…"}],
  "recipe": {"present": true, "python": "3.12", "requirements": "code/requirements.txt",
             "steps": [{"run": ["python", "get_data.py"], "about": "…"}, …],
             "inputs": [{"path": "data.db", "source": "…", "reload": "get_data.py"}],
             "compare": ["results/estimation_results.json"]},
  "environment": {"python": "3.12", "lock": "e2er-package/requirements.lock.txt", "hashes": true,
                  "resolved_as_of": "2026-10-15", "note": "…"},
  "wheels": {"platform": "darwin-arm64-py3.12", "python": "3.12", "folder": "e2er-package/wheels/darwin-arm64-py3.12",
             "files": 15, "bytes": 50331648},   // null without --offline
  "notes": ["…"]
}
```

The manifest is not listed in `contents`; the fingerprint covers every other file. The
canonical JSON is `json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`
in UTF-8. Without the internet the lock cannot be resolved: `environment.lock` is `null`,
`environment.note` says so, and a rerun installs from the recipe's own pins (without hashes).

**Opening a package** (`verify`, `reproduce`, `unpack`; `inspect` reads the manifest only).
Nothing in the package is run. In order: the manifest must be present, at most 32 MB,
valid JSON without duplicate keys, in format `e2er-package/1`, and its fingerprint must
match its own contents list. Then, before anything is written: every entry name is checked
(see Paths), a link entry is refused, every entry must be listed in the manifest with its
size and every listed file must be present, a file that unpacks to more than 1000 times
its packed size (and more than 1 MB) is refused, and so are more than 200,000 entries or
more than 64 GB in all (`E2ER_PACKAGE_MAX_BYTES`). Files are then written one by one into
a new or empty folder (never executable, never following a link), hashed as they are
written; a file larger than listed or with another SHA-256 stops the unpacking with its
name ("README.md does not match e2er-package.json: it was changed after packing") and the
folder is removed. `e2er-package.json` is written into the folder last.

**Verify and reproduce on a package.** `e2er verify` adds a first check, "package"
(every file matches the manifest), then verifies the unpacked folder as any folder:
`e2er-package.json` and `e2er-package/` are not part of the study's evidence
(`bundle_files.not_evidence`), and a data file the manifest declares left out is reported
in the integrity check instead of failing it (data files only). In a plain folder (an
unpacked package, or any folder with an `e2er-package.json` in it) the file is only a file:
a declaration counts only for a data file the folder's own records say a source's terms keep
out (`data_terms.restricted_paths`); any other missing file fails the check. `e2er reproduce` installs
from `e2er-package/requirements.lock.txt` (the installers check every hash) and, when the
package carries wheels for this computer's platform and the recipe's Python, from those
with `--no-index --find-links` (no internet); wheels for another computer are not used, and
the report says the packages are downloaded. The location of the wheels is set by e2er,
never read from `reproduce.json`.

**Versions.** A reader refuses a package whose `format` it does not know and says to update
e2er. A later `e2er-package/2` may add fields; `e2er-package/1` readers ignore unknown fields.

### Artifact → folder mapping (driven by `SPECIALIST_ARTIFACTS`, registry.py)

| Source artifact(s) | → destination |
|---|---|
| `paper_draft.tex`, `abstract.tex`, `literature.bib`, compiled PDF | `paper/` |
| `run_estimation.py`; `_*.py`, `profile.py`, `*.log` | `code/`, `code/scratch/` |
| `data.db`, `data_summary.md`, `data_dictionary.json` | `data/` |
| `estimation_results.json`, `robustness_results.json`, `summary_statistics.json`, `number_verification.json`, `figure_spec.json`, `table_spec.json` | `results/` |
| `paper_plan.md`, `identification_strategy.md`, `econometric_spec.md`, `model_spec.md` | `design/` |
| `review_*.md`, `review_aggregation.json`, `self_attack_report.json`, `polish_*.md`, `citation_integrity.json` | `reviews/` |
| `manifest.json` + internal quality review score + key coef | synthesized into `README.md` |

Mapping lives in one dict so it's trivial to re-shape; anything unmatched falls into a
`misc/` folder rather than being dropped (no silent loss).

## Locked decisions

- **D1 — Output location.** `OUTPUT_DIR` env if set, else `<studies folder>/exports/<slug>/` (0.14.0; before,
  `<LOCAL_DATA_DIR>/e2er_papers/<slug>/`, else `~/e2er-papers/<slug>/`).
- **D2 — Slug.** `<title-kebab>-<YYYYMMDD>-<NN>`, where `NN` is a 2-digit version counter — the smallest
  unused number for that `<title>-<date>` prefix. So same-day re-exports increment
  (`routing-around-royalties-20260627-01`, `-02`, `-03`, …). This makes each export a new, versioned
  folder and **subsumes D5** (no overwrite — re-running just bumps `NN`).
- **D3 — `data.db` handling.** **Copy** (portable deliverable; ~1 GB is fine). Never symlink — the
  folder must survive being moved/shared and the workspace being cleaned up.
- **D4 — When it runs.** Both: **auto** at terminal status (completed, stopped by a check, or failed), plus a
  manual CLI `e2er export <paper_id> [--to DIR]` for on-demand / re-export.
- **D5 — Re-export.** Handled by D2's `NN` version counter — each export is a fresh `-NN` folder; nothing
  is overwritten.
- **D6 — Folder names.** As proposed: `paper/ code/ (+code/scratch/) data/ results/ design/ reviews/`.
  Probe scripts kept under `code/scratch/` for reproducibility.
- **D7 — Partial runs.** Yes — best-effort over whatever artifacts exist, so a stopped/failed run still
  yields its reviews + draft.

## Implementation sketch (once the layout is fixed)

- New module `src/core/export/structured.py`: pure function `export_paper(workspace, dest, manifest) ->
  Path` that walks the mapping, copies/symlinks, and renders `README.md`. No pipeline coupling — it just
  reads the finished workspace.
- New runner phase `_run_export_phase()` (sibling to `_run_github_push_phase`) invoked at terminal
  status; gated on `OUTPUT_DIR`/`EXPORT_ENABLED`.
- New CLI `e2er export <paper_id> [--to DIR]` for on-demand / re-export.
- Reuses `SPECIALIST_ARTIFACTS` + the artifact registry so the mapping stays in sync as specialists
  change. Tests: mapping correctness on a synthetic workspace, missing-artifact tolerance, README render.

## Non-goals
- Restructuring the internal workspace (too invasive; breaks resume/artifact contracts).
- Changing how specialists name or write artifacts.
