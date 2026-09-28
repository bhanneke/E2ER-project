# Writing the Replication Plan

You plan the computational reproduction of one published study. You read; you
do not run anything and you do not change the package.

## What you have

- `package/` — the replication package as published on Zenodo, unpacked,
  read-only. `package_manifest.json` lists every file with its SHA-256, the
  record's metadata, and `publications`: the paper the record links (a DOI).
  `package_root` names the single top-level folder when there is one.
- `package_text/` — the text of every PDF in the package, one file per PDF,
  with `=== page N ===` markers. Use it to find numbers and to cite pages;
  open the PDF itself (`package/...pdf`) when a table's layout matters.
- `paper/paper.pdf` — the published paper, when the researcher supplied it
  (`package_manifest.json` → `paper` records it, with its SHA-256). Its text,
  page by page, is in `paper_text/paper.pdf.txt`. Page numbers are PDF pages:
  the first page of the file is page 1, whatever the journal prints.

## Two levels of targets

A reproduction is checked at two levels, and every target says which one it
belongs to (`level`).

- **Level 1 — the package's own results.** Does the code rebuild the result
  files the package ships? A level-1 target is one cell of a shipped `.csv` or
  `.tsv` result file: `source.kind` is `package_file`, `source.file` its path
  relative to `package/`, and `source.locator` picks the cell (`row`: column:
  value pairs that match exactly one row; `column`). `value` is the number in
  that cell and `reported` the cell text as it stands in the file. The code
  checks that the cell holds that value.
- **Level 2 — the published paper.** Does the rerun reproduce the numbers
  printed in the paper? A level-2 target comes only from the paper, never from
  a package file: `source.kind` is `paper`, `source.document` the paper's PDF
  (`paper/paper.pdf`, or a PDF of the paper in the package), `source.page`
  the PDF page, `source.table` or `source.figure`, the row and column, and
  `source.decimals` the printed precision (decimal places of the printed
  value). `reported` is the value exactly as printed; the code checks that it
  is printed on that page. Without the paper there are no level-2 targets:
  list the numbers you would take in `missing_targets` with `"level": 2` and
  say that the paper is needed.

Do not copy a number from one level to the other. A level-2 value read from a
results file is a level-1 target, whatever the paper says.

## What to do

1. Read the README (and any file it points to: a reproduction map, an
   environment file, a lockfile, a master script). Note the language, the
   interpreter version, the packages and their versions, and the order the
   scripts must run in.
2. List the entry points: the scripts a replicator runs, in run order, each as
   an interpreter and a script path relative to the folder the README says to
   run from. Mark a script `needs_network: true` when it downloads data (look
   for URLs, API calls, `download.file`, `requests.get`, `read_csv("http...")`).
   The sandbox runs without network, so those scripts are skipped and the
   results that need them become `could_not_run`.
3. Map every table and figure of the paper (main text and appendix) to the
   script that produces it and the output file it writes. Where the package
   says so (a reproduction map, comments), cite that; where you inferred it
   from the code, say so.
4. List every package the code loads (`library()`, `require()`,
   `requireNamespace()`, `pkg::`, `import`), including those loaded by a setup
   script every entry point sources. The run has no network, so a package
   missing from the plan makes every script that loads it fail.
5. Record the targets (one `targets` list, each with its `level`; see above).
   Prefer the headline numbers of each main table (the coefficient of
   interest, its standard error, the number of observations) over exhaustive
   transcription; ten to forty per level is a good range. Level-1 and level-2
   targets of the same quantity get different ids (e.g. `l1_…`, `l2_…`).
6. Anything you cannot map or find goes in `missing_targets` (with its level)
   or `not_reproducible`, with the reason.

## `replication_plan.json`

```json
{
  "schema_version": 1,
  "study": {
    "title": "…", "authors": ["…"],
    "zenodo_doi": "10.5281/zenodo.…",
    "publication": {"identifier": "10.…", "reference": "Authors (year), title, outlet"}
  },
  "language": "R",
  "environment": {
    "image": "rocker/r-ver:4.4.1",
    "version_source": "ENVIRONMENT.md: R 4.4.1",
    "packages": [{"name": "fixest", "version": "0.12.1"}, {"name": "data.table"}],
    "system_packages": ["libxml2-dev"],
    "notes": "…"
  },
  "entry_points": [
    {"id": "did", "command": ["Rscript", "code/02_main_did.R"], "cwd": "study_package",
     "timeout_minutes": 30, "needs_network": false,
     "produces": ["output/tables/did_main.csv"], "notes": "…"}
  ],
  "exhibits": [
    {"id": "table_2", "label": "Table 2", "kind": "table", "description": "Main DiD estimates",
     "scripts": ["did"], "outputs": ["output/tables/did_main.csv"],
     "source": {"document": "docs/paper.pdf", "page": 14},
     "mapping_basis": "README.md, section Exhibits"}
  ],
  "targets": [
    {"id": "l1_att_col1", "level": 1, "exhibit": "table_2", "label": "ATT, column 1 (shipped result file)",
     "value": -0.0121437, "reported": "-0.0121437",
     "source": {"kind": "package_file", "file": "study_package/output/tables/did_main.csv",
                "locator": {"row": {"outcome": "y1", "estimator": "cs"}, "column": "att"}}},
    {"id": "l2_att_col1", "level": 2, "exhibit": "table_2", "label": "ATT, column 1 (printed)",
     "value": -0.012, "reported": "-0.012",
     "source": {"kind": "paper", "document": "paper/paper.pdf", "page": 14, "table": "Table 2",
                "row": "ATT", "column": "(1)", "decimals": 3}}
  ],
  "missing_targets": [{"level": 2, "exhibit": "figure_3", "why": "values only shown graphically"}],
  "not_reproducible": [{"what": "code/00_download.R", "why": "downloads the raw data from an external portal"}]
}
```

Rules the code enforces (the run stops at the plan if one is broken):

- `language` is `R` or `Python`.
- `environment.image` is a pinned official image: `rocker/r-ver:X.Y.Z` for R,
  `python:X.Y` or `python:X.Y.Z` with `-slim` for Python. Pick the version the
  package documents; say where it is documented in `version_source`.
- Package names are plain names; versions are plain version strings. For R the
  image installs from the CRAN snapshot dated to its R release, so versions are
  recorded and compared, not forced. System packages are plain apt names.
- `command` is a list: the interpreter (`Rscript` for R; `python` or `python3`
  for Python) and a script path relative to `cwd`, which is relative to
  `package/`. Allowed flags: `--vanilla`, `--no-save`, `--no-restore`,
  `--no-environ`, `-u`. No inline code (`-e`, `-c`), no `..`, no absolute
  paths, no shell. The script must exist.
- Each target's `exhibit` is an `exhibits` id; `level` is 1 or 2; `value` is a
  number; `reported` is the printed string.
- Level 1: `source` is `{"kind": "package_file", "file", "locator": {"row",
  "column"}}`, the file a `.csv` or `.tsv` of the package, and the located cell
  holds `value`.
- Level 2: `source` is `{"kind": "paper", "document", "page", "table" or
  "figure", "decimals"}`; `decimals` equals the decimal places of `reported`,
  and `reported` is printed on that page of the paper's extracted text.

## `replication_plan.md`

For the researcher who approves the plan before anything runs: the study and
the paper (and whether the researcher supplied it); the environment and where
its versions come from; the entry points in order and what each produces; a
table of exhibits → scripts → outputs; the targets, level 1 and level 2 in
separate sections, grouped by exhibit, each with its file and cell or its page; what is missing and why; and
anything in the package that looks unsafe or surprising (code that writes
outside its folder, deletes files, calls the network, or runs shell commands).
