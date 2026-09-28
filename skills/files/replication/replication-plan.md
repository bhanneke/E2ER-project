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
4. Record the published numbers to compare against (`targets`), from the paper
   itself: the PDF in the package if it ships one, otherwise the linked
   publication. For each: the value, the value exactly as printed, the
   document, the page, and the table or figure with its row and column. Prefer
   the headline numbers of each main table (the coefficient of interest, its
   standard error, the number of observations) over exhaustive transcription;
   ten to forty targets is a good range. Never infer a target from a results
   file the package ships; those are what is being tested.
5. Anything you cannot map or find goes in `missing_targets` or
   `not_reproducible`, with the reason.

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
    {"id": "t2_att_col1", "exhibit": "table_2", "label": "ATT, column 1",
     "value": -0.012, "reported": "-0.012",
     "source": {"document": "docs/paper.pdf", "page": 14, "table": "Table 2",
                "row": "ATT", "column": "(1)"}}
  ],
  "missing_targets": [{"exhibit": "figure_3", "why": "values only shown graphically"}],
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
- Each target's `exhibit` is an `exhibits` id; `value` is a number; `reported`
  is the printed string; `source` names the document and the page.

## `replication_plan.md`

For the researcher who approves the plan before anything runs: the study and
the paper; the environment and where its versions come from; the entry points
in order and what each produces; a table of exhibits → scripts → outputs; the
targets, grouped by exhibit, each with its page; what is missing and why; and
anything in the package that looks unsafe or surprising (code that writes
outside its folder, deletes files, calls the network, or runs shell commands).
