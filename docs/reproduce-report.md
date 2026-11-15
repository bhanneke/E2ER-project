# The `e2er reproduce` report

`e2er reproduce <folder or .e2er> --json FILE` writes the report as JSON. The format is `"schema":
"e2er-reproduce-report/1"`. Fields are only ever added: a reader of an older report finds the fields it
knows, and a reader written for an older report can ignore the new ones. This page lists every field and
says since when it is there.

## Top level

| field | what it holds |
|---|---|
| `schema` | `"e2er-reproduce-report/1"` |
| `folder` | the study folder that ran (for a `.e2er` file, the temporary folder it was unpacked into) |
| `environment` | the steps' Python (`python`), the installed packages (`packages`), how they were installed (`installer`), the Docker sandbox (`sandbox`: `image`, `base`, `docker`), whether the network guard was in place (`network_guard`) |
| `steps` | one entry per step: `command`, `about`, `exit_code`, `seconds`, `tail` (the last lines of its output), `log`, `reload` (the step loads inputs again), `network`, `missing`, `skipped` |
| `inputs` | one entry per input of `reproduce.json`: `path`, `source`, `status` (`identical`, `same_rows`, `same_numbers`, `differs`, `missing`, `not_compared`), `tables_differ` for a database, `output` for a left-out output the rerun built again, and since 0.21 `reloaded: true` for an input the folder did not ship and a step loaded or built again |
| `results` | one entry per compared result file (see below) |
| `tables` | the paper's tables rendered again: `rendered`, `identical`, `differ`, `not_shipped`, `not_compared`; `null` when the study ships none |
| `verdict` | one plain sentence |
| `exit_code` | 0 reproduced, 1 differences, 2 could not run |
| `allow_network`, `sandbox`, `run_folder_kept` | how the run was set up |
| `category` (since 0.21) | what kind of outcome the verdict is, see below |
| `sources` (since 0.21) | each data load a step made, compared with the study's record of the same load, see below |
| `host` (since 0.21) | the computer the rerun ran on: `e2er_version`, `system`, `release`, `machine`, `python` (e2er's own Python; the steps' Python is `environment.python`) |

## `results`

`published`, `produced`, `values`, `counts` (`identical`, `same_at_precision`, `small_difference`,
`differs`, `missing_in_rerun`, `only_in_rerun`), `matches`, `problem`, `largest_differences`.

Since 0.21 a result file that the folder does not ship (a package leaves it out under a source's terms, as
`results/figure_spec.json` of a study on Yahoo Finance data) is listed with `"not_compared": true`,
`"left_out": "left out under Yahoo Finance's terms (rebuilt by code/scratch/build_panel.py)"` and the same
words in `problem`. Such an entry does not count in the verdict: the verdict comes from the files that were
compared.

## `category`

| value | exit code | meaning |
|---|---|---|
| `reproduced` | 0 | every compared value is identical or the same at the published precision, and every table renders the same |
| `not_reproduced` | 1 | values or tables differ |
| `could_not_run` | 2 | a step failed, and nothing points to a source |
| `source_changed` | 1 or 2 | values differ, or a step failed, after a source returned other data than when the study loaded it (another fingerprint, or, for a study recorded before fingerprints, another version by the source's own account): the change at the source is the likely cause, not the study's code |
| `source_unavailable` | 2 | the step that loads the data again failed because a source did not answer (a time-out, a server error): a later try may succeed; this says nothing about whether the study reproduces |

A reader that knows only `exit_code` reads these as before.

Since 0.21 reloaded inputs that differ byte for byte from the study's files no longer make a study "not
reproduced" when every result matches: the verdict is "Reproduced …; the reloaded inputs differ byte for
byte from the study's (…)", exit code 0. An input the folder shipped that differs still counts.

## `sources`

One entry per load that a step made during the rerun (get_data.py loads the data a study could not ship
with `e2er-data`, which records each load in the run folder's `data_sources.json`) and that the study's
`data/data_sources.json` records too (the same table, else the same saved file, else the same source and
series):

| field | what it holds |
|---|---|
| `source` | the source's name ("WHO Global Health Observatory") |
| `connector` | the e2er-data connector (`who_gho`) |
| `loaded_into` | the table or file the load went into |
| `recorded_at` | the day the study loaded it |
| `reloaded_at` | when the rerun loaded it (UTC) |
| `version_recorded`, `version_now` | the source's own version, release or last-updated value, where it gives one |
| `status` | `same`, `changed` or `not_recorded` |
| `recorded`, `now` | the two fingerprints (SHA-256, see below) |
| `rows_recorded`, `rows_now` | the row counts |
| `parts_kind` | `texts` (each text's own SHA-256, since 0.21) or `files` (the files the source served) |
| `parts_changed` | for a corpus source (Project Gutenberg texts): the parts that differ, by name ("ebook 2276") |
| `files_differ` | for a study recorded before 0.21: whether a file the source served differs from the one recorded (SHA-256) |
| `sentence` | the line the text report prints |

## The fingerprint of a load

Since 0.21 every load `e2er-data` and `fetch_data` record in `data_sources.json` carries
`"fingerprint": {"form": "e2er-rows/1", "sha256": "…", "rows": n, "columns": […]}`, a SHA-256 of the rows
the load returned. The canonical form (`src/modules/data/load_record.py`, `fingerprint_rows`):

1. the columns are the names of every row's keys, sorted by Unicode code point;
2. each row is a JSON array of its values in that column order (a missing key is `null`); a number whose
   value is whole (`3.0`) is written as an integer (`3`), other floats in Python's shortest round-trip form,
   NaN and infinities as `null`, dates as ISO text, nested objects with their keys sorted;
3. each array is written as compact JSON (`ensure_ascii=False`, `sort_keys=True`, separators `,` and `:`),
   and the lines are sorted by Unicode code point, so the order of the rows does not count;
4. the hash is SHA-256 over the UTF-8 bytes of the column list written the same way, a newline, and each
   sorted row line followed by a newline.

The same load also records the source (`connector`, `dataset`), the request (`request`, `query`), the time
(`retrieved_at`, UTC), the row count (`rows`) and the source's version where its interface gives one
(`version`: the WHO GHO's latest update date, the World Bank's `lastupdated`, the Gaia data release; NASA
POWER's API version; `service_version` of the USGS service; FRED's `last_updated`). Yahoo Finance gives
none. A Project Gutenberg load also records `texts`: for each book its SHA-256 (of the text without
Project Gutenberg's header, footer and licence) and its length, so a rerun can name the books that changed.
The dossier lists the fingerprint with each source (`data_sources[].fingerprint`: `form`, `sha256`, `rows`).
A study recorded before 0.21 has none, and its dossier stays as it was.

## The reproduction before publishing

`e2er publish` runs the same reproduction before it publishes (docs/publishing.md). Its outcome is one entry
of the description's `verification` list (`e2er.json` and the request to e2er.org):

```json
{"check": "reproduction", "status": "PASS",
 "detail": "reproduced before publishing, on 2026-11-12 with e2er 0.21.0 in Docker (python:3.12-slim): 930 of 930 values identical or the same at the published precision, 3 of 3 tables identical",
 "reproduction": {"reproduced": true, "date": "2026-11-12T10:00:00Z", "e2er_version": "0.21.0",
                  "platform": {"system": "Darwin", "release": "…", "machine": "arm64", "python": "3.12.12"},
                  "python": "3.12.14", "sandbox": "python:3.12-slim",
                  "verdict": "Reproduced: …", "category": "reproduced", "exit_code": 0,
                  "counts": {"values": 930, "identical": 917, "same_at_precision": 13, "small_difference": 0,
                             "differs": 0, "missing_in_rerun": 0, "only_in_rerun": 0, "result_files": 1,
                             "result_files_not_compared": 0, "tables": 3, "tables_identical": 3,
                             "inputs": 2, "inputs_identical": 0, "inputs_reloaded": 2},
                  "seconds": 252.2, "reload_seconds": 247.4, "reloaded_sources": ["ESA Gaia Archive"]}}
```

`seconds` is how long the rerun's steps took together, `reload_seconds` how long the steps that loaded data
again took, and `reloaded_sources` the sources they loaded from (from the report's `steps` and `sources`;
left out when the report records no times). The study page and `e2er inspect` show them as the effort of a
rerun ("Required for reproduction", docs/publishing.md).

With `--skip-reproduce "<reason>"`: `"status": "SKIP"`, `"detail": "not reproduced before publishing:
<reason>"`, `"reproduction": {"reproduced": false, "skipped": "<reason>", "date", "e2er_version"}`. A study
without code to run (no estimation results or script): `"status": "SKIP"`, `"detail": "nothing to run
again: …"`, `"reproduction": {"reproduced": false, "nothing_to_run": "…"}`. A publish that did not
reproduce sends nothing, so no entry says FAIL.
