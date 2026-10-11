# Changelog

All notable changes to e2er are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### A new data source is one definition (connector kit)
- **One `Source` definition per source** (`src/modules/data/sources/<name>.py`): name, website,
  terms (address, summary, full text), citation and BibTeX, key setting (or none), whether a published
  study may pass the data on, politeness (spacing between requests, retries, request budget) and its
  operations, each with its arguments and a fetch function returning rows. From it e2er builds the
  `e2er-data <source> <operation>` subcommands (with `--table` and `--save-to`), the record of every
  load in `data_sources.json` (terms, citation, the request as made, the query, the release, the
  SHA-256 of every file read), the table's data dictionary entry, the citation in the study's
  `literature.bib`, the planning catalogue and `fetch_data` method, the sources and aliases the data
  architect may declare, the standalone check's loading commands, the dashboard's labels, a doctor
  reachability check, and, for a source whose terms keep its data with the source, the terms gate on
  publish and the reload in `get_data.py`. Before, a source touched about eight places.
- **Adapters for the common services** (`sources/adapters.py`): REST JSON with paging (page numbers,
  offset, next link), TAP/ADQL (astronomy archives), CSV/ZIP download cached by version and re-hashed
  with SHA-256, and SDMX-CSV (official statistics). Every request names e2er in its User-Agent, is
  spaced and retried after HTTP 429/502/503/504, and a failure names the URL and the status.
- **Recorded fixtures for tests** (`use_cassette`): a test records the source's responses once, live
  (`E2ER_RECORD_FIXTURES=1`), and replays them offline; a request the fixture does not hold fails the
  test. No live calls in CI.
- **Yahoo Finance, FRED and the Global Macro Database are defined the same way**, with no change in
  behaviour: their subcommands, arguments, printed results, load records, citations, terms gates,
  reload commands, labels and planning cards are identical (checked on 28 scenarios before and after).
  Their fetching and handlers stay their own; the definitions are the one place for everything else.
- **New source: the USGS Earthquake Catalog** (`e2er-data usgs events --start … --end …
  --min-magnitude … --bbox west,south,east,north`): earthquakes worldwide from the ANSS Comprehensive
  Catalog through the USGS FDSN event service, no key, U.S. public domain. A period with more than the
  service's 20,000 events per request is split into windows by their counts. Each load records the
  query URL, the service version and the SHA-256 of every CSV read, and adds the catalogue's citation
  (DOI 10.5066/F7MS3QZH) to the study's references.
- **Docs and generated text**: `docs/CONNECTORS.md` (how to add a source, with the USGS connector as
  the worked example); `scripts/gen_sources.py` writes the README's data source table from the
  definitions and a skill stub for a new source; a test fails when the README lists other sources.

### New data sources: astronomy and earth science
Each with its terms quoted from the source's own pages, its citation from the provider's recommended
citation or DOI record, a skill file (what is in it, typical calls, units, pitfalls), a doctor check,
and contract tests on responses recorded live once.
- **NASA Exoplanet Archive** (`e2er-data exoplanets planets|query`, no key): confirmed planets and
  host stars from the archive's TAP service, one row per planet (`pscomppars`, default) or one
  published solution per planet (`--catalogue ps`), with `--columns`, `--since`/`--until`, `--method`
  and an ADQL `--where`; `query` runs one ADQL SELECT. The archive states no licence; each load carries
  NASA's acknowledgement, the archive paper (Christiansen et al. 2025) and the table's DOI
  (10.26133/NEA13 or NEA12).
- **ESA Gaia** (`e2er-data gaia cone|query`, no key): Gaia DR3 sources in a cone (`--ra --dec
  --radius`, `--max-mag`, `--min-parallax-over-error`) or any ADQL SELECT, within the archive's
  anonymous quota (50,000 rows, 10 s). Gaia data are CC BY-NC 3.0 IGO: e2er handles them as data under
  terms (publishing asks for `--accept-data-terms gaia`, a Zenodo deposit takes a non-commercial
  licence, `get_data.py` reloads them from the fixed DR3 release); loads cite the Gaia mission and DR3
  papers.
- **NASA POWER** (`e2er-data nasa_power point|regional|parameters`, no key): daily, monthly or annual
  weather and solar parameters for a place (up to 20) or a 2–10 degree region (one), since 1981. Each
  load records the API version, community, time standard and units, and its citation names the API
  version and access date as POWER asks; POWER's fill value −999 becomes an empty cell.
- **NOAA Climate Data Online** (`e2er-data noaa daily|stations`, free token `NOAA_TOKEN`): GHCN-Daily
  station records (temperature, precipitation, snow), paged and split by year within the token's
  limits; the token travels in a header and is never recorded. Without a token the source is not
  offered and says where to get one.
- **TAP loads never cut a table**: `tap_capped` asks for one row more than the cap and stops the load
  when the result is larger; a TAP service's error VOTable (also on HTTP 400, as Gaia sends it) becomes
  the load's error with the service's message. `PoliteClient.get(ok_status=…)` lets a fetch function read
  a refusal's body (POWER's HTTP 422 messages).
- **Recording fixtures**: two loads inside one `use_cassette` block now record (each request gets its own
  transport; before, the second load failed with "Event loop is closed").
### New data sources: statistics, health, books and software
- **World Bank Open Data** (`e2er-data worldbank indicators | series`): development indicators by
  country and year through the Indicators API v2 (World Development Indicators by default, other
  World Bank databases with `--database`), no key, CC BY 4.0. Each load records every indicator's
  licence and data source from its metadata, names any indicator that is not CC BY 4.0, and cites in
  the World Bank's format ("The World Bank: Dataset name: Data source").
- **Eurostat** (`e2er-data eurostat datasets | dimensions | data`): EU statistics through the
  dissemination API, filtered by dimension, NUTS level (`--geo-level nuts2`) and period; no key. The
  citation follows Eurostat's copyright notice (the dataset's DOI and, for a filtered extract, its
  datacode link with the access date); the terms note that non-EU/EFTA/candidate-country data and
  data of other sources may be reused non-commercially only, and that Eurostat keeps no past versions.
- **Our World in Data** (`e2er-data owid search | chart`): the data behind any OWID chart with each
  indicator's origins and their licences (OWID's own data are CC BY; third-party data keep their
  producers' licences, recorded per origin and named in the note when not open); charts OWID marks
  as not redistributable are refused. The citation credits OWID and the producers, as OWID asks.
- **WHO Global Health Observatory** (`e2er-data who_gho indicators | data`): WHO health statistics
  by country, year, sex and age through the GHO OData API, no key. WHO's terms for its data allow use
  for public health purposes and no changes without WHO's written authorization, so a published study
  reloads GHO data (`get_data.py`) instead of shipping them, after the researcher confirms the terms.
- **Project Gutenberg** (`e2er-data gutenberg books | text`): the catalogue through Gutendex and
  plain texts from Project Gutenberg's own mirror (its website allows no automated access), at most 20
  books per load, two seconds apart. Texts are stored without Project Gutenberg's header, footer,
  licence and references (which leaves texts unrestricted by U.S. copyright, per its licence), and
  the load records what was cut; books still under copyright are refused.
- **GitHub** (`e2er-data github repos | repo | releases`): public repositories' metadata (search by
  query, topic, language, stars and creation date; details, languages, contributor count; releases),
  never their contents. Keyless within GitHub's limits; an optional `GITHUB_TOKEN` setting raises them
  (the machine's `gh` login is never used). GitHub allows research use only with open-access
  publications and grants no licence to pass the metadata on, so a published study reloads them.
- **Connector kit**: recorded fixtures replay redirects and `Link` headers, and recording works across
  several `e2er-data` calls in one test; a definition whose argument is one of e2er-data's own names
  (`source`, `table`, …) is refused.

### A core without economics assumptions (for 0.16.0)
- **A template declares the kind of results its study reports.** `results = "regression"` (the
  default, e2er's contract as before), `"descriptive"`, `"timeseries"`, `"spatial"` or `"text"`. The
  estimation check holds `estimation_results.json` to that kind's contract
  (`src/core/pipeline/result_kinds.py`): descriptive (summary statistics with ordered quantiles,
  distributions whose counts add up to their n, figures declared in `figure_spec.json`), time series
  (models with fit statistics, forecasts inside their intervals, out-of-sample RMSE and MAE, MAE never
  above RMSE), spatial (units, spatial statistics with their weights, Moran's I expectation
  -1/(n - 1), p-values that follow from z, map specifications), text (corpus counts, term
  frequencies whose per-10,000 values follow from the counts, text-model outputs). A results file of
  these kinds starts with `"result_kind"`; one script and one file serve every kind, so rerun, export
  and `e2er reproduce` are unchanged. Each kind has a schema skill
  (`skills/files/data/<kind>-results-schema.md`) that the analysis specialist reads in place of the
  econometrics skills, and whose example the tests check against the contract.
- **The number check reads the kind's files**, and `e2er verify` adds a `results contract` check for a
  study whose results are not a regression (none for regression studies, whose output is unchanged).
- **Tables of statistics, categories and periods.** `table_spec.json` takes `"layout": "records"`: rows
  are entries of the results (variables, bins, forecast periods, spatial statistics, terms) at a
  `path` in the results or `summary_statistics.json`, columns are their fields; filled by lookup like
  the regression layout, with unresolved paths, rows and fields reported by `e2er-check-tables` and
  the repair round. Figures gain `scatter` and `histogram`.
- **`causal = false`**: no `identification_spec.json` is required or asked for, and a regression need
  not implement one. Default: causal for regression results, not for every other kind.
- **Template-declared panel, weights and polish.** The review step scores the reviewers the template's
  `aggregate` step names (until now the six economics reviewers ran whatever the template said) with
  `review_weights` in place of the default weights; the mechanism rule applies only to a panel with a
  mechanism reviewer. Two discipline-neutral reviewers can join a panel: `methods_reviewer` (skill
  `review/methods-review`) and `plausibility_reviewer` (`review/domain-plausibility`). Polish runs only
  the polish specialists the template's `polish` step lists.
- **Persona and data skills from the template.** `base_skill = "base/researcher"` replaces
  `base/economist` wherever a specialist reads it (`base/researcher` now speaks of the study's own
  field); `data_skills = [...]` replaces the blockchain, DeFi and Allium skills of the data architect
  and analyst (the general connector skills stay).
- What a template changes is recorded in the `template_components` event (`core`) and shown to every
  specialist and the strategist as a short template block; the declared skills in a study's
  description follow the same merge. Templates that set none of this run exactly as before (tests
  hold every shipped template to the registry's skills, panel and polish).
- Tests: a descriptive template replays end to end on a synthetic exoplanet radius–period dataset
  (`tests/fixtures/replay/exoplanet`, `tests/test_neutral_core_replay.py`): no regression or
  identification is asked for, the estimation gate passes on the descriptive contract, the number
  check traces the records tables, the five-reviewer panel scores with its weights, and the export
  verifies with `e2er verify` (all 36 table cells at the precision shown). Contract tests per kind in `tests/test_result_kinds.py`, records
  tables and the new figures in `tests/test_records_tables.py`.

## [0.15.3] — 2026-10-11

### A subscription plan's usage limit pauses the run
- **Codex, Claude Code and Gemini: a used-up plan pauses the run instead of failing it.** On
  2026-10-11 (0.15.2, Codex with gpt-6-astra) a run failed with "All specialists failed in parallel
  batch: idea_developer: Codex failed (exit 1): You’ve hit your usage limit. Upgrade to Pro …". Nothing
  was broken: the ChatGPT plan's limit was used up. The CLI backends now recognise their plan-limit
  messages (Codex: "You’ve hit your usage limit", `usage_limit_reached`; Claude Code: "Claude AI usage
  limit reached|<time>", "Claude usage limit reached … reset at 2pm", "5-hour limit reached ∙ resets
  3pm", "You've hit your limit · resets …", weekly and Opus limits; Gemini: a used-up daily quota, not a
  per-minute rate limit) and raise `PlanLimitReachedError`, with the reset time when the CLI states one.
  No retry is spent on it (`src/modules/llm/plan_limit.py`).
- **The run pauses like at the spending limit.** The runner records `paused_plan_limit` (backend,
  reset time, the interrupted specialist, the status sentence), saves its state and sets the study to
  paused with "Your ChatGPT plan's usage limit is reached (resets at 14:30). The run is paused; press
  Resume when the limit has reset." (Claude: "Your Claude plan's usage limit …"). No step is marked
  failed and the interrupted specialist's attempt does not count towards its three attempts or the
  circuit breaker. Resume picks up at the first step that has not finished and runs the interrupted
  specialist again; in the first step, work orders that finished are kept, as after a spending-limit
  pause.
- **Parallel batches finish first.** When one specialist of a parallel batch hits the limit, the
  others run to their end (the ones that succeed keep their output; they usually hit the same limit at
  their next call), then the run pauses. No specialist is stopped half-way.
- **Where it shows.** The run page shows the whole sentence with the Resume button and the event
  "Paused: the plan's usage limit was reached"; the studies list and the study page show the sentence
  and a Resume button for such a run; `e2er status` prints the sentence and `e2er resume <id>`; the
  dossier records the `paused_plan_limit` event among the run's events.

## [0.15.2] — 2026-10-11

### Stale tables are set aside; a draft that cites nothing is caught
- **The renderer sets aside tables the spec no longer declares.** In the 2026-10-10 Haiku run
  section_writer cut `table_spec.json` from four tables to two; the two dropped tables (`---` in every
  cell) stayed in `tables/` and shipped in the export's `paper/tables/`. A table an earlier render
  wrote and the current spec drops now moves to the hidden `.history/tables/` (listed as `set_aside`
  in `table_render_report.json`). Tables the renderer did not write (field-map tables, `\input` stubs)
  stay. The export also leaves out of `paper/tables/` any table that is neither rendered nor included
  by the paper, which covers workspaces from before this change.
- **A draft for a study with references must cite them.** The same run's draft cited none of the 21
  entries of `literature.bib`, and the citation check, which checks the cites a draft makes, skipped
  itself. The output contract of the paper drafter and of the field review writer now fails such a
  draft with "The draft cites no work; cite the papers in literature.bib where they support the text";
  after the last attempt the run stops at the contract as usual. The study's references are the
  entries of `literature.bib` and `user_refs.bib`, or the papers chosen for it.
- **The citation check says why it checked nothing**: "no references: the draft cites no work and the
  study has no bibliography", or "the draft cites none of the N work(s) in the study's bibliography",
  in `citation_integrity.json` and the run's gate record. `e2er verify` fails a paper that cites none
  of the works in its `refs.bib`, and says "no references" when the bundle has no bibliography.

### The number check stops when no table cell was checked
- **A paper with rendered results tables and no traced table cell no longer passes the number
  check.** In the 2026-10-10 E2E-01 run on Claude Haiku the renderer wrote two tables from the results
  files, the draft `\input`-ed neither, and the number check, which reads the draft, compared 0 table
  cells, checked the prose numbers and reported a pass. The run went on to the reviewers and the export,
  and `e2er verify` then failed the export (no table_cell edges, 0 cells traced). The tables traced in
  full once included (25 of 25 cells), so the tracing itself was not at fault.
- **Under governance `full` the run now stops at the number check** and says why in plain words: which
  rendered tables the paper leaves out, and the `\input` lines it needs. Edit the draft, give an
  instruction or send back the drafter or the table layout, and the check runs again; or approve to
  continue without the table check, recorded in the dossier as your decision (`e2er verify` still
  fails such a paper). Under `contracts` and `off` the finding is recorded in `number_check.json` and
  the run notes, and the run continues.
- **The drafter's output contract checks that every table declared in `table_spec.json` is
  `\input` in the draft**, so a drafter that leaves its tables out gets the missing `\input` lines as
  feedback and another attempt before the run reaches the number check.
- `number_verification.json` records the rendered tables, those the draft leaves out, and
  `tables_untraced` with its reason. `e2er verify` gives the same reason when it fails the numbers check
  for 0 traced cells.

### Studies reproduce on their own
- **`e2er reproduce` gives the study's code e2er's read-only data access.** `e2er-data query sql` and
  `e2er-data query tables` now work inside a rerun and read the run folder's `data.db`. Before, a
  script that checked an aggregate with `e2er-data query sql` stopped with exit 2 ("paper_id
  missing"): the E2E-01 run with Codex on 0.15.1 passed `e2er verify` and failed `e2er reproduce`
  for this reason. The steps still get no API key and no e2er setting, and a rerun's queries are not
  written to e2er's own database.
- **No web outside the data step.** Only the step that loads inputs again (`get_data.py`) may use the
  network and e2er-data's loaders. In every other step a connection to another machine fails with a
  plain message, and `e2er-data yfinance|fred|gmd|allium …` exits 5 with one; the report says which
  step tried to reach what. `e2er reproduce --allow-network` lets the steps through and names the
  sites they read in the report and the verdict. The guard sees connections made by Python (a small
  module in the rerun's environment); a program started from the script (`curl`) is caught by the
  estimation contract below.
- **The estimation script is checked for web access at the estimation step.** The runner reads the
  scripts that write `estimation_results.json` (and the local modules they import) without running
  them, and flags network libraries (requests, httpx, urllib.request, yfinance, pandas_datareader,
  fredapi, …), URLs read with pandas, `curl`/`wget` in a subprocess and e2er tools other than
  `e2er-data query`. A finding is an output-contract failure for the econometrics specialist, with
  the file and line and the message "The estimation script must read its data from data.db or files
  in data/; load web data in the data step", so the specialist fixes it within its attempts; after
  the last attempt the run stops as for any contract failure. The econometrics and data skills say
  the same. The FOMC replay fixture's estimation script lost its pandas-datareader fallback, which
  this check flags.
- **The reproduce report always lists the inputs**, also when a step fails or the environment cannot
  be made, so the reader sees what the rerun had; a recipe without inputs says so.
- On the E2E-01 Codex export, the rerun now runs to the end with `--allow-network`: every estimate and
  all 15 tables are identical; the 276 differing values are the provenance of the 101 statements the
  script reads from federalreserve.gov while it estimates (retrieval times, page hashes, 16 URLs).
  Without `--allow-network` it stops at that fetch and says so.

### Gemini: not tested, API key only
- **Full runs are tested on Claude (Claude Code) and OpenAI (Codex CLI with a ChatGPT plan).** Google
  ended Gemini CLI sign-in for individual accounts in October 2026: `gemini` 0.63.0 answers "This
  client is no longer supported for Gemini Code Assist for individuals" and points to Antigravity. The
  Gemini backend therefore needs a Gemini API key (`GEMINI_API_KEY`) and is not tested. The code stays.
- **The setup page lists Gemini under "Other providers (not tested)"**, with a field for the Gemini
  API key and no sign-in command. Its note no longer says Gemini runs on a subscription. A Gemini key
  saved there is written to `.env` as `GEMINI_API_KEY`.
- **`e2er doctor` and `e2er init`.** A Gemini sign-in file no longer counts as ready; only
  `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) does, from the environment or `.env`. The check names the
  backend as not tested. `e2er init` offers Gemini last, as "Other provider, not tested", and checks
  for the key.
- **`e2er run-matrix` leaves Gemini out of its default backends.** It runs only when `--backends`
  names it.
- **Spending limit texts.** For a Gemini study, the new-study form and the run page say that Google
  bills the Gemini API key and e2er does not count the cost; they no longer call it a subscription.
- README, docs/BACKENDS.md and the command help say the same.

### OpenRouter with an open model, run live
- **First live study on OpenRouter with an open model (DeepSeek V4 Pro).** The OpenRouter backend had
  only been tested with mocks. A whole single-pass study now runs on it; what the live run showed is
  fixed below.
- **Costs are what OpenRouter bills (fix).** The cost table had no entry for open models, so every
  DeepSeek call was priced at the $3/$15-per-million guess, 10 to 40 times the bill, and the spending
  limit would have stopped a study that had spent cents. e2er now records the cost OpenRouter reports
  for each call (`usage.cost`), counts cached prompt tokens as cache reads, and for a call without a
  reported cost uses OpenRouter's published price list, read at the start of a run and kept for a day
  in `~/.e2er/cache/openrouter-models.json` (the fixed table, now with DeepSeek, when offline). On the
  live run e2er's recorded cost and OpenRouter's account differed by under a cent.
- **Calls go to the provider that is cheapest for a study (new setting `OPENROUTER_PROVIDER_SORT`,
  default `price`).** A model on OpenRouter is served by several providers at very different prices.
  Left to OpenRouter's balancing, DeepSeek calls went to a provider charging about 8 times the cheapest;
  OpenRouter's own "cheapest" ranks by fresh input and picked one that charges 9 times more for cached
  input and 10 times more for output, and a study's calls are mostly cached input. e2er now reads the
  model's providers from OpenRouter's public list (kept a day), ranks them by what a study's mix of
  calls costs there, and asks for them in that order with fallback. `throughput`, `latency` or empty
  (OpenRouter's balancing) are the other choices.
- **The spending limit holds inside a specialist (fix).** It was checked between specialists only;
  one specialist ran on while the study passed its $3 limit ($3.48 billed). The Anthropic and
  OpenRouter backends now check before every call, counting the specialists still running.
- **Stopping a run keeps the cost of the specialist that was working (fix).** Its calls were billed
  but never recorded, so a stopped study showed $2.85 where OpenRouter had billed $3.48. The Anthropic
  and OpenRouter backends now record what a loop used when its run is stopped.
- **Setup offers every OpenRouter model that can use tools, with its price** ("DeepSeek V4 Pro (open
  model, low price): $0.23 in / $0.46 out per million tokens"), suggestions first; offline, the fixed
  suggestions. A model already chosen stays selected, also in e2er's spelling (`claude-sonnet-4-5` for
  OpenRouter's `claude-sonnet-4.5`).
- **A reviewer that answers instead of writing its file (fix).** DeepSeek returned a whole review as
  its reply without calling `write_file`, and the retry cost a new review. On the Anthropic and
  OpenRouter backends a missing Markdown output is now filled with the final answer (300 characters or
  more) and the log says so; JSON, LaTeX and scripts never are.
- **Source notes no longer print in the paper, and drafts no longer write their own tables (fix).** The
  `cite-numbers-by-source` skill, loaded by the drafter, section writer, abstract writer and revisor,
  taught HTML comments (`<!-- src: ... -->`) for source notes, which LaTeX printed into the PDF, and
  showed a results table written in the draft, which the drafter's contract rejects: every live run on
  DeepSeek lost its first draft to "inline tabular", as a Claude Code run had on 2026-09-11. The skill
  now teaches `% src:` notes on a line of their own and `\input{tables/<name>.tex}` for tables;
  compiling removes any HTML comment from `paper_draft.tex` and `abstract.tex`, and the number check
  reads neither kind of note as a claim.
- **The number check skips LaTeX comments in tables (fix).** DeepSeek annotated each table row with a
  `% src:` comment naming the JSON keys (`pre_tightening_2015_2021`); read as cells they gave 15021 and
  22023, and `e2er verify` failed the exported study.
- **The number check reads `$-$0.93` as -0.93 and "2015--Feb 2022" as a period (fix).** A table with a
  minus typeset in math had its minimum of -0.93 read as 0.93, and the 2015 of a year-to-month span read
  as a value; both failed `e2er verify` on numbers that were right.
- **A call that stalls is asked again after two minutes, not ten (fix).** Each of the three live studies
  lost 10 to 11 minutes to one OpenRouter call that never answered and ran into the SDK's 600-second
  timeout. Calls are now streamed: one that sends nothing for 120 seconds (240 before its first data)
  is dropped and asked again, as is one whose provider fails mid-answer.
- **Smaller fixes in the OpenRouter loop:** a response with no answer (an upstream provider failed) is
  retried twice; tool arguments that are not valid JSON go back to the model as an error instead of
  running the tool with no arguments; empty arguments and arguments in a code fence are accepted.

## [0.15.1] — 2026-10-10

### Iterative mode, run end to end
- **The iterative mode now runs at the replay level, from the question to the finished study.** A new
  replay scenario (`tests/fixtures/replay/fomc-iterative`, on top of the FOMC one) scripts two rounds
  of improvement, a ceiling check that asks for another round and then for a change of approach, a
  self-critique with one serious finding, the polish notes and their correction, the review panel and the revision. Before,
  the replay answered "nothing further" to every round, so the rounds, the ceiling check, the change
  of approach and the self-critique's corrections had never run on the current engine. The replay
  backend takes per-round answers (`iterations`, `ceiling_checks`, `self_attack`) and per-call
  recordings (`calls`) for a specialist that runs more than once.
- **Each round is recorded (fix).** The run's log showed the specialists of the rounds one after
  another, with no sign of where a round began, what the ceiling check decided or which step was the
  change of approach. The runner now records each round (`improvement_round`), the ceiling check after
  it (`ceiling_check`: another round, a change of approach, ready for review; a second change of
  approach is refused and recorded as such), the change of approach (`pivot`), the strategist ending
  the rounds (`improvement_stopped`) and the self-critique (`self_critique`: findings, serious ones,
  corrections made).
- **The run page shows "Rounds of improvement"**: each round with its specialists, the ceiling check
  after it and the change of approach in plain words; the step says "2 rounds, then a change of
  approach", and the self-critique step its findings and corrections.
- **The dossier lists the rounds** (`run.rounds`: each round's specialists with their names, the
  ceiling check's decision and reason, the change of approach), and every step of a round says which
  round it belongs to (`round`, `pivot`). A run without rounds adds nothing, so its dossier (and its
  id) is unchanged.
- **The self-critique's corrections are kept (fix).** They were written to `paper_draft.tex.edits.json`
  and `paper_draft.tex.applied.diff`, which the revision after the review panel writes again: the
  export kept only the revision's edits, and nothing showed what the self-critique changed in the
  draft. They are now kept in `self_attack_corrections.json` (findings, edits, diff), exported with
  the reviews.
- **A change of approach runs under the same rules as a round (fix).** Its work orders went straight to the
  specialists, past the guard against rewriting the whole draft after round 1 and past the circuit breaker.
  They now run like a round's: a pivot that would rewrite the whole draft (paper drafter, revisor) is not run,
  and the record and the run page say so in a sentence; a specialist that has failed its attempts stops the
  run as in a round, and the pivot's failures count.
- **The polish notes change the paper or say why not (fix).** The notes (`polish_*.md`) were exported and read
  by no later step. Now they go to the targeted corrections, as the self-critique's findings do: the patch
  revisor edits the draft where a note asks for it, or writes no edit. The number check guards it: corrections
  that make more table or text numbers differ from the results are undone. What became of the notes is in
  `polish_corrections.json` (exported with the reviews), the `polish_applied` event and the run page
  ("Polish: 2 notes; 1 change made in the draft").
- **A ceiling verdict other than the three no longer fails the run (fix).** "stop", "Continue" or no
  JSON at all failed the check's model and with it the whole run; it is now read as "ready for
  review" (case and spaces ignored).

## [0.15.0] — 2026-10-10

### Choose the data and papers a study uses
- **New study lists your data files and papers.** The files of the data folder (name, type, size;
  search; select all or none) and the papers of the literature folder, your .bib files and the
  Library (title, authors, year). The study uses what you tick. Before, every study took everything
  in both folders and the page offered no choice. Ticked at first: the data files and the papers of
  the literature folder and .bib files (what a study took before); the Library's papers are offered
  unticked.
- **Add files before the run starts.** "Add files" takes data files, "Add PDFs or a .bib file" takes
  papers; they are copied into the study and kept with it only. One list of data file types
  everywhere (.csv, .tsv, .jsonl, .parquet, .xlsx); any other file is refused in one sentence. A
  .txt is no longer staged as data.
- **Only the chosen files count.** They are staged into the study's `data/` folder and imported into
  its `data.db` (an added file is recorded in `data_sources.json` as added by the researcher); the
  planning check, the specialists' context and the list of available sources read only the study's
  own folder, never the live data folder. The choice is recorded in `.study_inputs.json` (left out of the exported folder: it names files on this computer).
- **The researcher's papers are in the bibliography (fix).** Entries of the .bib file, a local Zotero
  library and the Zotero web library were shown to the writers as citable but never written into
  `literature.bib`, so citing one failed the citation check (missing from the bibliography). Now
  every paper offered to the writers is written into `literature.bib` before the first step, with
  the key the prompt shows; a .bib entry keeps its own key and fields.
- **Web search in addition, marked.** The literature search for the research question runs beside
  your papers (before, a .bib or Zotero library switched it off without a word). Every entry says
  where it came from (`e2er_source = {researcher}` or `{web}`); none replaces one of yours.
  "Use only my papers" turns the search off and limits the Library's evidence to the chosen papers.
- **The run page shows "Data and papers"**: the chosen files, the tables the study reads with their
  rows and source, your papers and the papers found on the web. The finish page shows "What the
  study used": data used and every reference the paper cites, marked "from your papers" or "found
  on the web". The dossier lists the cited references with their source (`references`; a study
  exported before has none, so its dossier is unchanged).
- **Readable titles.** New study, the run page and the finish page show titles without braces, LaTeX,
  author footnote marks (∗ † ‡) or "Accepted Version" banners; a title that is a file name, a page
  header or a journal citation ("J Evol Econ (2013) 23:925–953") is replaced by its DOI record's
  title, else shown as "(title not readable)". The Library's papers are a folded group of their own,
  "Your Library (N)", with its own search, below the folder's papers and .bib entries.
- **Off-topic web hits stay out.** A search hit joins the bibliography only when it shares enough of
  the research question's content words: with an abstract, 2 in the title and a third (2 to 4) in title
  and abstract; title only, a fifth (2 to 3) (`is_relevant` in `modules/literature/discovery.py`). The
  live run's 53 hits for a mortgage question (solar bonds, the federal budget, …) all stay out; the study
  records what it left out in `literature/web_search.json`, and the run page says how many. The
  panel lists the web papers the draft cites first and folds the rest.
- **Library: Add papers.** The Library page takes PDFs or a folder and reads them in the background
  with the importer of `e2er library add`.
- **`e2er run --data FILE… --papers FILE… [--only-my-papers]`** does the same in a terminal (a
  folder stands for the files in it). Without them a study takes everything, as before.

### Replication, credit, commands and the field map
- **Fixed: an installed e2er could not run the specialists' commands.** Before 0.15.0 a pip or
  `uv tool install` installation had only `e2er`, `e2er-data` and `e2er-fieldmap`. `e2er-run`,
  `e2er-lit`, `e2er-check-tables` and `e2er-allium-query` existed only in a source checkout, while
  the specialists were told to use them. On an installed e2er, specialists on the CLI backends
  (Claude Code, Codex, Gemini) could therefore not run their own scripts while writing them, not
  search or record literature, and not check their table specs; the runner still ran the
  estimation script itself after the step. All six are now console commands of the package
  (`src/wrappers.py`; the `scripts/` files of a checkout call the same code). The wheel check
  installs the package with an empty home folder and runs each of them.
- **`e2er reproduce` for every study.** `e2er export` now writes `reproduce.json` from what the run
  recorded: the estimation script and every later script of the run that wrote
  `estimation_results.json`, in the order the run ran them (`e2er-run` and the runner now record
  every script run in the workspace; for older runs the order comes from file times, and the recipe
  says so); the files they read, laid out
  where they expect them, with data files as inputs (SHA-256 and source from `data_sources.json`);
  `code/requirements.txt` with the packages they import at the versions of the run's environment;
  the estimation results (and robustness results) to compare, with the tables rendered again; and
  `code/get_data.py`, which loads Yahoo Finance and GMD data again with `e2er-data` when the folder
  does not have them. The exported scripts name the run folder instead of the workspace's full
  path. The FOMC demonstration study reproduces with it: 162 of 162 values identical and both
  tables the same, in a new environment. A study without an estimation script or without results
  gets no recipe, and its README and `e2er reproduce` say why. `e2er-data yfinance` records the
  request (ticker, dates, interval) with each load, so the reload asks for the same rows.
- **Stata packages are refused before any model call.** The replication template's download step
  now refuses a package that has no R or Python file and whose code is in Stata (`.do`, `.ado`,
  `.dta`), MATLAB, Julia, SAS, SPSS, GAMS, EViews, Mathematica or Ox. The refusal names the files and
  stops the run before the planner reads the package, so nothing is spent.
- **Template credit in the dossier.** A run records its template's `[[credit]]` in the
  `template_components` event, and the dossier of a published run carries it as `credit`
  (`{"template": …, "entries": [...]}`, the entries as the template file wrote them). Dossiers of
  templates without credit are unchanged, and so are their ids.
- **Co-authors from the terminal.** `e2er publish --coauthor "Name|github=login|orcid=…|role=…"`
  (repeatable) lists co-authors after the publisher in `e2er.json`; each needs a GitHub login or an
  ORCID iD, so e2er.org can ask them to confirm the credit. A malformed entry is refused with a
  sentence that says what is missing.
- **Skill texts without internal names.** `synthesis/context-builder` and `writing/scoped-revision`
  name the specialists in words ("the paper drafter", "targeted corrections").
- **Every terminal command is in the README**: `e2er serve`, `skills sync` (and `install-skills`),
  `verify-citations`, `preregister deposit`, `whoami`, `logout`, `dossier push`, `skills installed`
  and `remove`, and the `library` commands `list`, `stats`, `topics list`, `topics remove`, `export`
  and `remove`. A test reads every command and subcommand from the code and fails when the README
  does not name it.
- **Field-map completeness stops calibrated.** The citation-network check now stops above 50% of
  papers without internal links (before 60%) and above 40% without references (before 25%). The
  values come from five boundaries (scientometrics, information systems, economics and two niches);
  the old 25% would have stopped the information-systems and economics literatures, whose main
  paths have 18 papers. The table is in the `synthesis/main-path-analysis` skill and in
  docs/templates.md.
- **Fixed: the number check read period labels as numbers.** A table with rows labelled `2004--06`,
  `2015--18` and `2022--23` (live run 2026-10-10, mortgage pass-through study) was read as 2004
  and -06, 2015 and -18, 2022 and -23; the run stopped at the number check on two of them and
  `e2er verify` failed six cells of a correct table. Spans of years (`2004-06`, `2007–2009`,
  `1998--02`), quarters and months (`2022Q3`, `Q3 2022`, `2004m6`), decades (`1990s`), fiscal years
  (`FY2019`) and month-and-year dates (`Jan 2020`) are now labels, in table cells and in the text,
  for the run's check and for `e2er verify` alike. A dash right after a digit is a range dash, not a
  minus sign: the upper bound of `0.12--0.15` is 0.15. Negative values, standard errors in
  parentheses and bare years are read as before.

## [0.14.1] — 2026-10-08

- 0.14.1 is 0.14.0 as it was meant to ship. The tag v0.14.0 exists, but its release run stopped at a test that only read the [Unreleased] part of this file, so 0.14.0 was never published on PyPI. That test now reads the whole file.

## [0.14.0] — 2026-10-08

The local dashboard works end to end on 127.0.0.1, and every page reads plainly.

### Studies folder
- **One home for studies.** Setup asks once for a studies folder (default `~/e2er-studies`) and
  remembers it in `~/.e2er/settings.json`. `e2er` started from any folder uses it: its `.env`, its
  studies (`workspaces/`) and its exports (`exports/`). A folder with its own `.env` still works as a
  project of its own, exactly as before; Setup offers to make it the studies folder. Studies made
  before keep working from anywhere (the database records their folders). The foot of every page
  says which folder is in use.
- **Readable folder names.** A new run's folder is named after the date and the title
  (`2026-10-08-fomc-and-bank-stocks`); the run's id is in its `manifest.json`. The AI providers'
  commands get the folder in `E2ER_WORKSPACE`.
- **Exports never land in the data folder.** Without `OUTPUT_DIR` they go to `exports/` in the
  studies folder (before: `e2er_papers/` inside the data folder).

### Fixed
- **Publishing from the browser no longer hangs.** With public data and a data source's terms box
  unticked, the server asked `[y/N]` on its own terminal. The server never asks; the finish page
  says next to each unticked box what is missing.
- **A tab left open across a restart keeps working.** The session secret is made once per computer
  (`~/.e2er/session-secret`, mode 600) and the cookie lasts a year; a `localhost` page is sent to
  `127.0.0.1`, so one tab never holds two sessions. The session file a second `e2er` reads is written
  only once this server has the port.
- **No silent failures.** A wrong address, a refused form or an error shows a page with one plain
  sentence and "Back to your studies"; the API keeps answering JSON. A button or the live panel that
  cannot reach e2er shows a notice saying so.
- **The Zenodo key saved under Settings is used** for deposits (it was read from the environment
  only). Setup has a field for it, and one for the GitHub login used as owner when publishing.
- **"Also stop for you after these steps" lists the chosen template's own steps** (it showed the
  empirical steps for every template, and the replication steps were refused).
- **"Open it there"** for a run in another e2er says how to open that dashboard signed in.

### Plain pages
- One set of names for steps, specialists, templates, actions, events, checks and statuses
  (`src/core/labels.py`; a template can name itself with `title` and its steps with `label`). Ids
  appear only under "Technical details".
- The stop page leads with the decision: why the run stopped, the table of differences, the
  button; then send back, instruction, and the files, folded and readable, with "Edit this file".
  A stop you asked for lists the files the step wrote.
- One vocabulary: study, run, step, specialist, stopped for you, spending limit, files, "Download
  all files" (every file of the run, without its hidden ones).
- The publish result links to the study and its dossier; what `e2er publish` printed is folded.
- Setup shows the exact command that signs in Claude Code, Codex or Gemini, with a copy button
  (the full path for the Codex inside the ChatGPT app).
- Subscription providers show "No spending limit" in place of a $0 meter; one default limit.
- Earlier versions of rewritten outputs go to the hidden `.history/` folder (before:
  `<file>.previous` next to the output); backups, lock files and `.previous` files are never
  exported.
- `/docs` names e2er and its version; styles for the Library, Skills and Workflow pages, the status
  colours and the study page.

### Mapping a research field

- **New template `field-map`: map a research field by main path analysis.** A specialist proposes
  the boundary (search terms with the topic's older names, a journal set, years, and two to six
  alternative boundaries); the researcher approves it with the paper counts. Code retrieves the
  papers from OpenAlex (paged, cached in the study, with a request ceiling, `OPENALEX_API_KEY` as
  a bearer token when set; every load recorded in `data_sources.json` as OpenAlex, CC0), builds
  the network of citations inside the boundary with a completeness report (papers without
  internal links or references, short reference lists, duplicates, notices, broken cycles),
  computes search path count weights (exact integers), the global and local main paths and the
  key routes, and repeats this on the alternative boundaries to show which papers are on every
  main path. A specialist names lanes as questions; the researcher approves them; code draws the
  map by year and lane and writes the reading list, Pajek, GEXF, VOSviewer and CSV exports, two
  LaTeX tables and `field_map_results.json`. A specialist drafts a short field review, and the
  number check and the citation check run on it as steps of their own. Nothing is estimated: the
  template has no estimation gate and no econometrics step.
- The workflow follows Michal Hron's article "Map a research field with Claude: main path
  analysis, step by step" (LinkedIn Pulse, 8 October 2026,
  https://www.linkedin.com/pulse/map-research-field-claude-main-path-analysis-step-michal-hron-jm2ge/,
  shared by Björn Hanneke); this implementation is independent and uses OpenAlex. Adopted: the
  six-step workflow and the pitfalls it lists. e2er's own: the code, the OpenAlex retrieval, the
  cycle handling, the exports, the template's steps and stops, and the number-checked review.
  The methods: Hummon and Doreian (1989), Batagelj (2003), Liu and Lu (2012).
- **New skill `synthesis/main-path-analysis`**: the method step by step, the choices and what they
  change, the pitfalls, how to read the map, and the sources.
- **New specialists** `field_boundary_designer`, `field_lane_mapper` and `field_review_writer`, and
  the command `e2er-fieldmap` (count, sources, boundary, network, mainpath, robustness, papers,
  map, export, all), allow-listed for those three.
- **Templates can credit the work they are based on** in `[[credit]]` tables (creator, role,
  relation, title, address, publication and access dates, where it was found), checked when the
  template loads. `credits.json` lists the credit of e2er's own parts for the catalogue of
  e2er.org.
- The checks `numbers` and `citations` can run as steps of their own in a template without a
  review step.

## [0.13.9] — 2026-10-07

- **A review run again is scored from its own files.** The reviewers now rewrite their files whole:
  before a reviewer runs again (after a deep revision, or a rerun from the review step) its earlier
  review is moved to `<file>.previous`, and only each reviewer's latest reply can stand in for a
  missing file. Before, a reviewer that wrote nothing in the second round was scored from the
  first round's file, and the "no reviewer produced a score" check could not fire.
- **The deep revision survives a stop.** Its round and whether its research or its re-review is
  under way are kept in the run's state file. A resume after a stop inside the re-review (the
  number check, say) runs the review again and decides; it no longer repeats the whole deep
  revision. A finished deep revision is not repeated on a resume. `e2er rerun` from the revision
  step or earlier allows one again.
- **Approving output that failed its contract works in every phase.** In the revision, an
  iteration or a pivot, the approved specialist is not run again when the phase is planned anew
  on resume; its output stands (each approval is used once and lapses when its phase ends). A
  second contract stop while the first is being settled keeps the researcher step to come back to.
- **`e2er rerun` withdraws the approvals at the checks it runs again**: table numbers continued
  with at the number check (when the review step runs again), outputs kept as they are at a
  contract stop (in the steps that run again). `e2er verify` now accepts a table cell the
  researcher continued with only for the same cell, value and source key, as the run does
  (records written before the run kept a source key: cell and value).
- **`e2er reproduce` no longer reports "Reproduced" when the study's code wrote nothing.** The
  files the rerun is to write are taken out of the run folder before the steps run, so a published
  file is never compared with itself; a rerun that writes none of them is "Not reproduced". An
  input file that differs from the study's, or is missing, now counts against "Reproduced". The
  study's code and the installation of its packages run with a minimal environment (PATH, HOME,
  language, temporary folder, proxies and certificates, the installers' own settings without
  credentials): no API key, token or e2er setting reaches someone else's code.
- **The number check reads every data row of a table ruled with `\hline`.** The header rows are
  the rows above the first full rule that follows a row (a rule at the very top or one that only
  closes the table sets nothing apart); `\cmidrule` between header rows ends nothing. Before, a
  table with `\hline` rules and a `\midrule` lower down lost every data row above the `\midrule`.
- **`data_sources.json` keeps every load when data are loaded in parallel**: each write holds a
  lock and replaces the file whole, with the previous version as `.data_sources.json.bak`. A file
  that cannot be read is kept as `.data_sources.json.unreadable-<time>` and the record continues
  from the backup, instead of starting again empty (a lost GMD or Yahoo entry defeated their terms
  checks at publish).
- **The AI CLIs stop with everything they started.** Claude Code now runs in its own process group
  like Codex and Gemini, and on a timeout the whole group is killed. A cancelled run kills the CLI's
  process group on all three backends; before, the CLI (and a script it had started) ran on.
- **The model's shell gets no credentials it does not need.** The Claude Code, Codex and Gemini
  CLIs, and the shell commands they run, get the data and literature keys the e2er wrappers read
  (FRED, Allium, Semantic Scholar, Zotero, the database password) and the CLI's own sign-in only;
  other providers' API keys, GitHub, Zenodo and e2er.org tokens and anything else named like a
  credential are left out.
- **Starting, steering or stopping a run needs this server's session token.** `POST /api/papers`,
  resume, cancel, review, rerun, file uploads, query approvals, the new-study form and skill
  installation now need the session token `e2er` makes at start (the dashboard's cookie from the
  link `e2er` opens, or the `X-E2ER-Token` header the `e2er` commands send, read from
  `~/.e2er/session-<port>.json` or `E2ER_SESSION_TOKEN`), or the bearer `API_AUTH_TOKEN` when one
  is set. Before, they were open to any process on the computer, a run's own model shell included
  (which never gets the token). A request without it is refused with a note on how to open the
  dashboard from the link `e2er` printed.
- **Small fixes.** A data source is normalised before its other names are looked up
  ("Yahoo-Finance" is yfinance), and files in subfolders of the data folder count as available
  (`raw/x.csv`). `e2er compare` no longer counts "not reported" as a value runs agree on. Codex
  usage is the sum over its retries of a call.

## [0.13.8] — 2026-10-06

- **Claude Code runs made with 0.13.7 can be published again.** 0.13.7 recorded where the CLI is
  installed (`/Users/<name>/.local/bin/claude`) in the run's `backend_identity` event, the dossier
  copied the event as it was, and `e2er publish` refused every Claude Code run with "the dossier
  names a path on this machine". The Claude Code, Codex and Gemini backends now record the CLI's
  name and version only (`"cli": "claude"`). When the dossier is built, any path on this machine
  in what the run recorded (events, failed steps, the run's last error, researcher steps) is cut
  to its last part (`…/claude`, `…/data.csv`), so runs recorded before this release publish too.
  A record without such a path reads exactly as before, so dossiers already issued keep their
  address. A path anywhere else in the dossier (for example in `data/data_sources.json`) still
  stops publish.
- **The replay level can stand in for a named backend and model** (tests only, for the end-to-end
  story E2E-20: `e2er run-matrix` on two backends, then `e2er compare`). Under `tests/replay` the
  replayed backend now takes the backend and model the run names, so a run on `codex` with
  `--models codex=gpt-6-luna` records `codex` and `gpt-6-luna` in its `backend_identity` event, as
  a real Codex run does (before, the replay ignored both and recorded no model). Replay overrides
  under `"backends"` apply only to the runs on that backend, so two runs of one question can
  differ. `tests/fixtures/replay/fomc/two-backends.json` is the variation the story uses: the
  run on `claude_code` reports the declared treatment term with its standard error, the run on
  `codex` reports three means and names another outcome, as the live runs of 2026-10-05 did.

## [0.13.7] — 2026-10-06

- **Yahoo Finance data get the GMD's treatment.** Yahoo's terms allow personal use only, so data
  loaded with `e2er-data yfinance` are now a source with terms for `e2er publish`, beside the
  GMD. The description names Yahoo Finance and its terms (from the yfinance load record) on the
  data files that hold Yahoo data. If the data stay private, the reader note says "The data come
  from Yahoo Finance, whose terms allow personal use only, so readers on e2er.org see a link to
  the source instead of a request button." and there is no nudge to publish them. `--data public`
  needs `--accept-data-terms yfinance` or a yes to "Publish the Yahoo Finance data with the study
  although Yahoo's terms allow personal use only?". A Zenodo deposit of Yahoo data is refused
  before anything is written or sent: no Zenodo licence fits personal use only. Yahoo publishes
  no citation format, so publish asks for no BibTeX entry. The finish page says the same. A study
  with GMD and Yahoo data names both sources in one reader note, and a data file holding both
  (`data/data.db`) names both sources and their terms in the description. See `docs/publishing.md`.

- **The Codex backend works.** Validated live on a ChatGPT plan with codex-cli 0.155 (October
  2026): single calls, a whole study (`e2er run --demonstration`, empirical template) and the
  end-to-end story E2E-01. Before, `codex exec` ran read-only (no specialist could write a file),
  refused to start outside a git repository (every study folder), had no network for
  `e2er-data`/`e2er-lit`, could not write the run database, ran under the user's own Codex
  configuration (model, effort, plugins, MCP servers, notify hooks) and kept session history.
  It now runs with `-s workspace-write` (setting `CODEX_SANDBOX`), `--skip-git-repo-check`,
  network on, `--add-dir` for the run database's folder, the whole environment passed to shell
  commands, no login shell, and `--ignore-user-config --ignore-rules --ephemeral`; sign-in still
  comes from `~/.codex`. Output is read from `--json` events and `-o`: the final message, token
  usage (cached input recorded as cache reads) and the number of commands and file changes. A
  timeout stops the CLI and everything it started; a dropped connection or a server error is
  tried twice more, a used-up plan limit is not. Prompts name Codex's own tools (`apply_patch`),
  as they name Claude Code's.
- **Codex cannot be limited to e2er's commands, and the docs now say so.** Claude Code runs with
  an allowlist; Codex's command rules can only be set in the user's own `~/.codex`, which e2er
  does not change. Under Codex the model can run any shell command; writes stay inside the
  workspace, the run database's folder and the temporary folder. See `docs/BACKENDS.md`.
- **The CLI is found where it is.** `e2er doctor`, `e2er init` and the setup page used to look for
  `codex`/`gemini`/`claude` on PATH only, ignoring `CODEX_PATH` and the other path settings. They
  now use the configured path, and find the `codex` inside the ChatGPT desktop app when it is not
  on PATH. The setup page lists the models the signed-in ChatGPT plan offers.
- **A run records the model and CLI version that answered.** Without `CODEX_MODEL`, Codex runs
  were labelled `codex-cli-default`; e2er now passes the first model of the CLI's own list
  explicitly and records it. A new `backend_identity` event records backend, model, reasoning
  effort and CLI version per run. `e2er run --model` (and `run-matrix --models`) now reach the
  backend; before, the per-paper model only labelled the run while the backend ran its configured
  one.
- **Settings in the study's `.env` reach e2er's commands.** `e2er-data`, `e2er-lit` and the other
  wrappers run in the workspace (or the e2er checkout) and read their own folder's `.env`, so a
  FRED key or a study-local database set only in the study's `.env` never reached them. The CLI
  backends now pass on that `.env` and the run database, as an absolute path. Applies to Claude
  Code too.
- **Gemini backend: same fixes, not validated live.** Absolute workspace root, the wrappers on
  PATH, the run database, the tool name `replace`, JSON output with token counts and tool calls,
  a help probe that no longer pins old flags after a slow start, and a sign-in hint that names a
  command that exists. The Gemini CLI was not installed where this was tested.
- **`e2er run-matrix` takes `--template`, `--review-at`, `--demonstration` and `--models
  backend=model,...`.** Without `--backends` it runs the subscription CLIs that are ready on this
  computer, not all three. `matrix.json` and `e2er compare` name each run's model.
- `e2er-data fred series --help` crashed on a `%` in its help text; a model that asked for help
  got a traceback.
- **A deep revision round no longer fails the run when the revised analysis renames its result
  keys.** Seen live on Claude Code (Sonnet): the re-run econometrics specialist wrote
  `pooled_hac_lag_20` where `table_spec.json` still asked for `hac_lag_20`, and the render check
  failed the run before the section writer, which repairs `table_spec.json`, could run. The
  writer is now told which references no longer resolve, and the check comes after it.
- The CLI backends no longer pass e2er's own control settings (the dashboard session token, the
  API token and address, the e2er.org sign-in file) to the AI CLI; no e2er command a specialist
  runs needs them.
- `e2er run` said it started the server "on :8280" whatever port was configured.
- **`e2er` refuses to run inside a study's AI step.** Seen live on Codex: while a study was in
  its review step, a reviewer's shell started a second study on the same server with `e2er run`.
  Every AI CLI call now carries `E2ER_AI_STEP`, and `e2er` exits with a one-line message under it.
  The step's own commands (`e2er-data`, `e2er-lit`, `e2er-run`, `e2er-check-tables`) are separate
  and unaffected.
- **A re-done analysis that fails its output contract stops the run for the researcher.** In the
  deep revision round the data analyst and the econometrics specialist got one attempt and their
  contract result was ignored; seen live on Codex, the revised `estimation_results.json` lacked
  `n_clusters`, the study completed, and `e2er verify` failed the export. They now get the usual
  attempts and, if those fail, the same stop as everywhere else.
- Codex: "Selected model is at capacity" is retried.
- **`e2er compare` no longer sets different quantities against each other.** When a run does not
  report the treatment term its design declares, the first coefficient it reports is shown with a
  mark and a note, and it is left out of the dispersion of the estimate. A field one run reports
  and another does not now counts as a difference (it read as full agreement). Seen in the first
  live Claude Code (Sonnet) vs Codex comparison, where Codex reported three means and no
  `year_2023` term.

- **`e2er reproduce <study folder>` runs a study's code again and compares the results.** A
  study's `reproduce.json` names the pinned requirements, the steps, the inputs with their
  SHA-256 and the result files to compare. The code runs in a run folder of its own, inside a new
  virtual environment (uv when installed, else venv); the study folder is not changed. Every
  result value is compared with the published one (identical, the same at the published
  precision, small differences under the replication path's 10% tolerance, or different), the
  inputs with the study's own files, and the paper's tables are rendered again from the rerun's
  results. Exit code 0 reproduced, 1 differences, 2 could not run; `--json` writes the report.
  Export ships `reproduce.json`, `code/requirements.txt` and `code/get_data.py` when the workspace
  has them, and the README's "Reproduce" section now says what the folder supports: it promised
  `data/data.db` and `cd code && python run_estimation.py`, which could not run.

- **The showcase study can be run again.** `examples/showcase` is re-exported with this version:
  `code/get_data.py` reloads its 37 Yahoo Finance extracts with `e2er-data` (Yahoo's terms allow
  personal use only, so the extracts are not shipped; `data/data_sources.json` records the reload),
  `code/requirements.txt` pins numpy and pandas, and `reproduce.json` holds the SHA-256 of every
  original extract. With the study's own extracts the estimation and robustness results come out
  byte for byte; with today's Yahoo and Ken French data, `e2er reproduce examples/showcase` reports
  which values moved. The publish tests now copy `tests/fixtures/showcase_export`, the showcase as
  it was exported before publishing.

- **`.parquet` and `.xlsx` files in the data folder load.** The README offered both, but the
  packages pandas needs to read them (pyarrow, openpyxl) were not installed with e2er, so such
  files were skipped with a warning in the log. Both are now dependencies, and if one is missing
  anyway, e2er prints which file was not loaded and the command that installs the reader.

- **`e2er doctor` says what it can and cannot know.** Without any AI access chosen (no
  `LLM_BACKEND` and no `.env`), it no longer reports a missing `ANTHROPIC_API_KEY`: it says that
  nothing is set up yet, names Claude Code when it is installed, and points to the setup page or
  `e2er init --defaults`. A Claude Code, Codex or Gemini CLI that is not signed in fails the check,
  and one whose sign-in cannot be read is reported as "couldn't check" instead of "Ready". The
  Docker check now asks the Docker daemon whether it runs; an installed but stopped Docker is no
  longer reported as available.

- **`e2er skills list` and `e2er skills install` work without a local RISE checkout.** The
  default catalogue was a folder on the maintainer's computer (`~/Documents/Projects/RISE`). e2er
  now downloads the pack list from the public catalogue at github.com/bhanneke/RISE into
  `~/.e2er/cache/rise` (refreshed once a day; an older copy is used when GitHub cannot be
  reached). `RISE_PATH` and `--catalogue` still point to a local clone, and when neither works
  the error says how to set one.

- **`e2er init` copies skill files only for the chosen AI access, and asks first.** It used to
  copy all of e2er's skill files into `~/.claude`, `~/.codex` and `~/.gemini` without asking,
  whichever CLI was chosen. The wizard now asks before copying into the chosen CLI's folder and
  copies nothing for the API backends; `--defaults` copies into `~/.claude/skills` only. Both say
  where the files went. The `.env` header names the current e2er version instead of "e2er v3".

- **`e2er export <id>` works from any folder and takes a short id.** It looked for the workspace
  only under `workspaces/` in the current folder. It now uses the workspace the database records
  for the paper (new studies record the full path), falls back to `WORKSPACE_ROOT`, and accepts
  the first characters of the id (at least 4) when they match one paper. When the workspace
  cannot be found, the error says where it looked and what to do.
- **Exported studies are no longer read back in as data.** The default export folder is
  `<data folder>/e2er_papers`; with recursive staging, the next study picked up the earlier
  studies' files as its own data. Folders named `e2er_papers` are now skipped.
- **On Windows without Developer Mode, data files and PDFs are copied into the study.** Linking
  them fails there, and the files used to be left out with only a line in the log. e2er now
  copies them and says once in the terminal that copies do not follow later edits, and how
  Developer Mode lets it link instead.

- **`--methodology mixed` runs the estimation check.** It applied to empirical papers only, so
  a mixed paper with a data warehouse could reach the draft with a broken or empty estimation
  file. Mixed papers are now checked and repaired like empirical ones.

- **`e2er-data` runs on Python 3.14.** A `%` in the help of `e2er-data fred series --units`
  made Python 3.14's argparse refuse to build the command, so every `e2er-data` call failed there.
- **The nightly Allium check stops reporting the same thing every night.** Allium's OpenAPI
  files at docs.allium.so now redirect to a login page; the check read that page as a changed
  API and commented on issue #2 every night (141 comments). It now tells a spec it cannot fetch
  (a warning in the run, no comment) from a real change, fingerprints a real change, and comments
  only when the change differs from the one already reported (`scripts/check_allium_drift.py`).
  The fixtures stay as they are: the current specs are not publicly available to refresh them.

- **Internal planning notes moved to `docs/internal/`.** Version plans, run diagnoses and reviews
  sat next to the user documentation; they are now in `docs/internal/` with a note on what they
  are, and references point there. `docs/NEW_USER_WALKTHROUGH.md` no longer shows paths from the
  maintainer's computer. `docker/` has a README saying it is an optional Postgres stack for
  development, not needed to use e2er.

- **Tracebacks from estimation scripts reach the model in plain text.** On Python 3.13 and 3.14,
  with `FORCE_COLOR` set (Claude Code and uv set it), Python coloured the traceback, and the
  escape codes split the error line the specialist reads to fix its script. `e2er-run` and the
  post-step execution now turn the colours off.
- **README:** the replication template works with Zenodo packages and R or Python code only; the
  spending limit applies to the API backends, since studies on Claude Code, Codex and Gemini CLI
  cost $0 in e2er's records; e2er works with Python 3.11 to 3.14 (the automated tests now run on
  all four); `e2er --version` prints the installed version (new flag).

## [0.13.6] — 2026-10-05

- **The paper can be published with the study, and publish says what readers see for what stays
  private.** `e2er publish --paper public --paper-url <address of the PDF>` (default address with
  `--repo` and `--commit`: `paper/paper.pdf` in the repository at that commit) puts the link into
  `e2er.json` and the publish request as `access`, and e2er.org links the PDF on the study page.
  The address is not part of the dossier, so it changes no fingerprint. For each of the paper,
  the data and the code that stays private, `e2er publish` and the dashboard's finish page say in
  one sentence that readers on e2er.org see a button to ask you for it, and which flag publishes
  it. Data from the Global Macro Database get no such note: its terms do not allow passing them on
  outside the study's replication package, and readers on e2er.org are sent to the GMD. The
  finish page has the paper choice and its address.

## [0.13.5] — 2026-10-04

- **Every data connector records what it loaded, with the source's terms and citation.** Before,
  only the Global Macro Database connector wrote `data_sources.json`. Now FRED, Yahoo Finance
  (yfinance), Allium, a Zenodo record fetched by the replication template and the researcher's
  data folder write an entry for every load too, through `e2er-data` and through `fetch_data`
  (the API backends). Each entry names the source, what was loaded (series, ticker, variables,
  query or file), where it went, the release or the date it was read, the source's terms in a
  sentence or two and in full with their address, and the citation: FRED's own format from the
  series' Cite tab (with the series title and source, read from FRED), Zenodo's format for a
  record, and for Yahoo Finance and Allium, which publish no citation format, one that e2er
  suggests (`citation_by: e2er`). A file from the data folder is recorded with its SHA-256.
  The dossier keeps the new keys (`series`, `retrieved_at`, `terms_summary`, `citation_by`,
  `link`, `doi`) and lists data-folder files by `path`; e2er.org shows them as the study's
  "Data used". Studies published before this record no entries for these sources.

- **Every researcher action is in the dashboard too.** The study page runs a study again from a
  step of its template with a remark (`e2er rerun`), resumes a failed or stopped study as well as a
  paused one (`e2er resume`), resumes with a higher spending limit after the limit was reached
  (`e2er resume --max-cost`; the plain Resume, which would stop again at once, is not offered
  then), deposits the frozen pre-registration on Zenodo (`e2er preregister deposit --zenodo`),
  approves or refuses data queries waiting for approval, and shows "Demonstration or test run" on
  a demonstration study. The new-study page has the stops after a step (`e2er run --review-at`)
  and takes a spending limit in cents. Each stop page says what continuing means for its kind
  ("Keep the output as it is and continue", "Continue with these mismatches", "Approve the
  deviation and continue", "Continue: run the check again", "Approve and freeze"). The finish
  page has where public data and code live, the Zenodo deposit, name, ORCID iD, roles, licence,
  repository, commit and path, what the study builds on, `--online` citation checks, and the
  terms of a data source the study used: publishing GMD data as public needs the box that
  confirms them, as `--accept-data-terms gmd` does.
- **`e2er rerun` works after a run failed or stopped.** Before, it refused a step that had not
  been marked done (the step a run failed in) and a run stopped at a researcher step or a check.
  Now any template step of the study's mode can be the start: a step the failed run never
  reached is accepted, and the run picks up at its first unfinished step; at a stop the rerun
  takes the place of the stop (recorded as `replaces`), and the checks run again on the way. A
  step run again runs all of its specialists. `e2er resume` works as before.
- **A dossier with an approved deviation from the pre-registration is accepted by e2er.org.**
  The researcher step listed the approved changes as records under `deviations`, which the
  dossier format keeps for text; the text stays there and the records (file, SHA-256 frozen and
  approved) are under `approved_deviations`.

- **A failed number check stops the run for the researcher.** When the numbers in the paper's
  tables still differ from the results files after the automatic correction (governance `full`),
  the run stops at the researcher step `number_check`. It names each mismatch: the table cell,
  the value in the table, the value in the results and the source key, and offers the draft and
  the results files. Edit them, give an instruction, or send back `paper_drafter`,
  `section_writer` (table layout) or `econometrics_specialist`, and the check runs again; or
  approve to continue with these mismatches, recorded in the dossier as your decision. The
  reviewers run after that. Before, the check marked the run stopped, a `--review-at review`
  pause hid it, and the review step was then counted as done without a single reviewer. Under
  `contracts` and `off` the mismatches are recorded and the run continues, and `e2er status`
  and the dossier say so (`number_check.json`). The export carries the record
  (`reviews/number_check.json`); `e2er verify` passes a cell that differs only when the researcher
  continued with exactly that cell, and names it.
- **The number check no longer reads column headers and row labels as results.** All three
  critical mismatches of the live run were header cells ("Scaled, day 15 or earlier",
  "120-day window", a placebo shift of -20 days): the rows above the first `\midrule` and a row's
  label ("Surprise (25 bp)") are skipped; a bare number in the first column is still checked.
- **A dossier with output kept at a contract stop is accepted by e2er.org.** The researcher
  step listed the kept outputs under `accepted`, which the dossier format reserves for a yes/no;
  they are now under `kept`.
- **A step that fails stops the run and says why.** A review step that ends without a reviewer
  score, a revision step without its patch file, or the citation check now ends the run with the
  reason in `last_error`; no later step runs (the live run went on to the replication step), and
  the step is not counted as done, so `e2er resume` runs it again. No failed or stopped status is
  written without a reason.
- **patch_revisor's empty patch is an answer.** `[]` ("nothing I can fix by editing the draft")
  no longer counts as a contract violation, as its skill already said; a missing or unreadable
  patch file gets the usual attempts with the violation fed back. The automatic correction runs
  once per set of mismatches: a resume after the researcher's decision does not pay for it again.
- **Output that fails its check after the last attempt stops the run for the researcher.** Before,
  the run ended `failed`. Now it stops at the researcher step `output_contract`, which lists each
  attempt's violations and the files involved (`e2er status`, `e2er review`, the dashboard's
  review page). The researcher keeps the output as it is (recorded in the dossier; the step that
  wrote it is marked `approved_by_researcher` with `contract_failed`), edits a file, gives an
  instruction, or sends the specialist back with a remark for new attempts. `e2er resume` alone
  gives new attempts and never keeps failed output. Specialists in the same batch that passed
  keep their output. Crashes and an unavailable backend still fail the run.
- **A specialist no longer runs beside the one whose output it reads.** The live run had the
  econometrics specialist in the data analyst's batch, estimating before any data were loaded.
  The dispatcher now moves such an order behind its producer (`SPECIALIST_NEEDS`), and the
  strategist's example plan no longer shows it.
- **The data architect plans only tables an available source can load**: yfinance and GMD, FRED
  with `FRED_API_KEY`, Allium with `ALLIUM_API_KEY`, or a file in the study's data folder. Its
  prompt lists exactly these; any other table is a contract violation that names the table, its
  source and why it is unavailable.
- **`e2er run --demonstration`** marks a demonstration or test run from the start (manifest.json
  `purpose`); export, publish, the paper footnote, the reproduction report and the dossier take
  it from there. New disclaimer wording: "Demonstration. This study was produced with e2er as a
  demonstration or test run and is published as is. It is not presented as a research
  contribution, and its author does not vouch for its findings."

## [0.13.4] — 2026-10-03

Fixes found by the new end-to-end stories (e2er-site `npm run test:e2e`, 15 research processes
replayed from two recorded runs).

- **A plan change after the pre-registration is frozen stops the run.** The estimation check
  pauses for the researcher and lists each changed plan file with its SHA-256 at the freeze and
  now. Approving records the deviation as the researcher's decision in the dossier and in
  `preregistration.lock.json` (`approved_deviations`); `e2er verify` passes an approved deviation
  and reports it, and fails an unapproved one. Before, the deviation was only disclosed.
- **Public data or code at a fixed commit can be published.** The availability address of public
  code no longer contains the commit, so the paper footnote, `provenance.json` and the dossier
  are the same with and without `--commit`, and e2er.org's check at the commit passes. The
  commit is recorded in `e2er.json` and the publish request.
- **A contributed skill keeps its pack id** (`skill:<pack>/<skill>`), so the dossier links the part
  listed on e2er.org and its author is credited. e2er's own skills keep `skill:e2er/…`.
- **Resume after a spending-limit pause skips completed work**, also in the initial phase.
- **`LITERATURE_ACQUIRE_LIMIT=0` sends no literature request.**
- **`e2er publish --to <platform>`** uses that platform's address for the dossier link, in the
  paper footnote, `e2er.json`, the Zenodo description and the output.

## [0.13.3] — 2026-10-03

- **Global Macro Database (GMD) connector.** `e2er-data gmd versions | variables | countries |
  series` reads the GMD's release files over HTTPS (no key). `series --variables rGDP,infl
  --countries USA,DEU --start 2000 --end 2024 --table gmd_macro` loads a country-year panel with a
  `forecast_<variable>` flag per variable; the newest release is the default and `--version` pins
  one. Each load records the release, the URL and the SHA-256 of the file read in
  `data_sources.json` and in the table's `data_dictionary.json` entry (with the GMD's terms of
  use), and adds the GMD citation (`GMD2025`) to `literature.bib`. Release files are cached in
  `~/.e2er/cache/gmd/<release>/` and hashed again on every use. An unknown variable, country or
  release, or a failed download, exits non-zero and leaves data.db unchanged.
- **Export and dossier:** `data_sources.json` ships as `data/data_sources.json`; the dossier of a
  study that has it lists each load under `data_sources` (connector, release, table, file URLs and
  SHA-256). Dossiers of studies without it are unchanged.
- `e2er doctor` checks that the GMD release list is reachable (`data.gmd.versions`).

## [0.13.2] — 2026-10-02

- **The internal quality review gives a score, nothing else.** Six reviewer specialists each
  score the draft from one angle (data, identification, literature, mechanism, technical,
  writing); the score is their weighted average and decides whether the draft is revised. A run
  that finishes its steps is now `completed` whatever its score; up to 0.13.1 a low score stored
  `rejected`, which read as a peer-review decision (the FOMC demonstration study's dossier said
  "Outcome: Rejected" for a run that finished every step).
- **Dossier:** `run.outcome.status` says whether the run finished (`completed`, `failed`,
  `cancelled`, `paused`, `stopped` by a check). The new `run.internal_review` records the score
  (`score`, `scale`, `combined`, each reviewer's score in `reviewers`, their `weights`, `rounds`).
  A run stored as `rejected` reads as `completed` when it reached its review, else `stopped`.
- **Visible wording:** the dashboard, `e2er status`/`list`/`run`, the export's README and
  report.html show the status in plain words ("stopped by a check" for a check that stopped the
  run) and "e2er's internal quality review: 6.1 of 10", never a review verdict.
- **Revision round that applies no edit** completes the run and records a
  `revision_not_applied` event; a revision round that writes no patch file fails the run
  (resumable). Before, both stored `rejected`.

## [0.13.1] — 2026-10-02

- **README rewritten in plain language.** It opens with the description and the texts of the
  e2er.org About page, and every command and option it names exists. Wrong statements were
  removed: a $25 cost default (it is $5), `python -m e2er`, `.txt` as a data format, outdated
  counts of skills and specialists, an example folder that does not exist.
- **Description:** "e2er is the open infrastructure for publishing, verifying, reproducing and
  reusing AI-enabled research." in the package metadata, the CLI help and the citation metadata.

## [0.13.0] — 2026-10-02

### Name and publishing format

- **Name.** The package, the CLI and the citation metadata say "e2er (End-to-End Research)".
- **Publish matches e2er.org's format.** The study description no longer carries an
  `amendments` field, which e2er.org refused; the amendments stay in provenance.json and in
  the dossier. `docs/schemas/research-object.schema.json` is synced with the site's copy, and
  a test validates a real publish against it.

### Integrity of published studies (review of 2026-10-01)

- **Publish needs the run.** `e2er publish` finds the study's run database
  (`--db`, the study folder's `DATABASE_URL`, e2er's default) and refuses one
  that does not hold the exported paper's run, or none. Both studies published
  on 2026-10-01 had dossiers without steps. `--no-db` publishes anyway and the
  dossier and footnote say the steps are not recorded.
- **Nothing changes in an edited folder.** Publish checks the folder against
  `provenance.json` before it changes anything; each change it then makes is an
  amendment (path, fingerprint before and after, reason), so the exported hash
  is never lost. A PDF publish compiles is fingerprinted.
- **Zenodo.** The dossier is built from a copy of the final availability and
  its id from the final document; deposits are published after everything that
  can fail; reserved deposits are kept in `.e2er/zenodo.json` and reused, so a
  retry makes no new deposits and gives the same dossier.
- **The dossier says what the run recorded**: every segment of the run with its
  commit and version, components pinned at each commit they ran on (unresolved
  ones say so), the specialists and skills that ran, one researcher step per
  researcher action with every field, the runner's reruns on the steps they
  caused, the outcome, halts, pauses, failures and set-asides, UTC times, and
  bundle-relative paths only. The runner now records what each step wrote and
  the skills it read. Dossiers built from a run are `e2er-dossier/0.6`.
- **Canonical JSON** is RFC 8785, as e2er.org computes it (floats, large
  integers, NaN, key order); the four published dossiers keep their addresses.
- **`e2er verify`** never follows a link, reads `provenance.json` strictly,
  checks every file but the root `provenance.json`, `e2er.json` and `.e2er/`
  records (report.html included), compares sizes, recomputes the derivation
  edges, ignores `.DS_Store`/`Thumbs.db`/`._*` (and says so), checks
  `e2er.json` and `.e2er/link.json` against the folder, and with `--against`
  against what e2er.org published. Checks the study's record requires fail
  when their input is missing; checks over nothing are skipped, never passed;
  every table cell must be a source value at the precision shown.
- **The reproduction report** must keep e2er's summary section, and its
  sections, "N of M" counts and overall verdicts must agree with the JSON.
- **Export** creates its folder atomically, never copies dotfiles, key files or
  links that leave the workspace, never lets one file overwrite another's
  target (and says which PDF is `paper/paper.pdf`), and fingerprints
  `report.html`.
- The demonstration disclaimer is a delimited block: a new wording replaces it,
  a study without a purpose loses it, and a purpose recorded on the study is
  honoured. The paper gets the dossier link without `--name` too.

### `e2er rerun`: send a finished study back to one of its steps

- `e2er rerun <id> --from STEP --remark "…"` (and `POST
  /api/papers/{id}/rerun`) reruns a template step and every step after it in
  a study that is not stopped at a researcher step, a completed one included.
  The approvals from that step on are withdrawn, the remark goes to
  `researcher_instructions.md` and is recorded as the researcher's action
  (`researcher_action`, action `rerun`, in the dossier), and the run stops at
  the next researcher step for approval. A researcher step cannot be the
  start, nor a step that has not run; at a pending researcher step the
  send-back does this. Nothing in the workspace is deleted.

### `e2er publish` takes the template from the export

- The export records the template the study was run with in
  `provenance.json` (`run.template`): the runner passes its template, `e2er
  export` and the browser's export the papers row's `pipeline`, otherwise
  `manifest.json`'s. `e2er publish` uses it; `--template` (no longer defaulting
  to `empirical`) may only repeat it, and a different one is refused with the
  recorded name. An export made before this records nothing: publish then takes
  `--template`, else `empirical`, and says so. The FOMC study had been
  published as `empirical`; a replication now gets the replication disclaimer.
- A server answer without an error text (a proxy page, Cloudflare D1 over its
  daily read limit, an empty body) printed an empty `error:`. `e2er publish`,
  `login`, `whoami`, `status`, `dossier push` and `submit` now print the HTTP
  status and the first 200 characters of the body (`pc.error_text`).

### The written reproduction report agrees with its JSON

- The replication demonstration's `reproduction_report.md` said "16 targets"
  and "not_reproduced 2" while `reproduction_report.json` and the check had 17
  numbers, 12 reproduced, 2 reproduced_minor and 3 not reproduced, and it
  listed package versions the run did not install. Nothing compared the two.
- e2er now writes the counts and the environment into the Markdown itself:
  once the JSON checks out, the reproduction check puts a section "Counts and
  environment" (delimited by `<!-- e2er:summary … -->` comments) before the
  report's first `##` heading, rendered from `reproduction_report.json` and
  `sandbox_log.json`.
- The reproduction check (the pipeline's `reproduction_gate` and `e2er
  verify`) and the comparer's contract fail when the prose contradicts the
  JSON, and name the contradiction ("reproduction_report.md says 16 level-1
  numbers (…), reproduction_report.json has 17"): counts that name their level,
  tables of counts per label, the label stated for a number that can be
  matched to one compared number (by target id, or published and reproduced
  value), and a package version stated after its name. A missing Markdown
  report, or an edited summary section, fails too. New module
  `src/core/pipeline/reproduction_md.py`.

### Replication: packages as of the package date, strict labels

- A specialist that writes its files whole (the planner, the comparer) starts
  each attempt with its earlier files moved to `<name>.previous`; any other
  specialist is told which of its files exist and to read them before writing.
  The CLI's write tool refuses to overwrite an unread file, which made every
  retry of the comparer fail in the live rerun.

- The sandbox installs packages as of the Zenodo record's publication date by
  default (`snapshot = "package-date" | "latest" | "YYYY-MM-DD"`): R from Posit
  Package Manager's dated CRAN snapshot, Python with pip's
  `--uploaded-prior-to`; declared versions still win (`remotes::install_version`,
  `==`). The snapshot date and URL, the platform and every installed version,
  dependencies included, are read from the committed image and recorded in
  `sandbox_log.json`, also when the environment is reused.
- Labels follow the protocol's thresholds exactly, stated in
  `reproduction-protocol.md` and enforced by the check: `reproduced` only when
  equal at the target's own precision (1e-9 relative for package cells),
  `reproduced_minor` up to 10 % with the same sign, `not_reproduced` beyond; a
  result takes its worst number's label. The check and the comparer's
  contract refuse reason texts that contradict the numbers or state a cause as
  established, and require the report's environment block (snapshot, and the versions it
  names) to match the log; the full list of installed versions is written by
  code into `reproduction_check.json`, not transcribed by the model.

### Checks

- **Every pre-registered hypothesis has a result.** The preregister step now
  ends `preregistration.md` with a machine-readable block: the hypotheses the
  plan declares (`[{"id": "H1", "statement": …, "parts": ["H1a", "H1b"]}]`)
  and the sample size the design fixes (the events of `event_design.json`, or
  a `sample_size` in `identification_spec.json`). The researcher may correct
  it; on approval it is frozen into `preregistration.lock.json`. The
  estimation check and `e2er verify`'s `preregistration` check then require at
  least one result entry per hypothesis (entries name it in a `hypothesis`
  field; a part such as H1a counts for H1) and fail with the list of missing
  ones. The headline estimate's `n_observations` must equal the registered
  sample size unless `exclusions`, each with a reason, account for the
  difference; the declared exclusions are reported. A lock frozen before this
  release falls back to the hypotheses its frozen text declares.
- **p-values follow from the test statistic.** The estimation check and
  `e2er verify`'s numbers check recompute, for every coefficient with an
  estimate, standard error, t and p: t = estimate / se (allowing for
  rounding), and the p-value from t with the stated `df`, G − 1 to the normal
  for clustered errors, `df_residual`, n − k, or n − 1 for a one-sample mean
  test, within 0.005 (more when `rounding` is declared). When df is unknown the
  p-value must lie between the normal and the t with the fewest df the entry
  allows, and the check says df was unknown. One-sided tests
  (`alternative`) are checked one-sided; p-values from bootstrap or
  permutation (`p_value_method`) are left out and listed. A mismatch fails and
  names the coefficient. The t distribution is computed from the regularized
  incomplete beta function (no scipy dependency) and tested against closed
  forms and published critical values.
- **Replications verify offline.** A replication export now carries
  `sandbox/logs/` and, under `sandbox/run/`, the output files the entry points
  wrote and every file `reproduction_report.json` reads a number from, all
  hashed in `provenance.json`. `e2er verify` has a `reproduction` check for
  bundles with a reproduction report: it re-reads every compared number from
  those files at its locator, recomputes each number's label with the
  pipeline's own reproduction code and the tolerance the run used, and
  confirms the report's summary counts. A replication bundle can now be
  verified. Paper bundles are unchanged.
- The reproduction check (pipeline and verify) recomputes a label per
  compared number, fails on a stated `label` that differs, and checks the
  report's `summary` counts (numbers by label, or results by level).
- **Declared tables hold values, not only rows.** The data contract now
  fails when a value column of a declared table is less than 90% non-null
  (or the `min_non_null` share the data dictionary declares for the table or
  column), e.g. `dgs2.value: 0 of 2765 non-null (needs 90%)`. It checks the
  columns a table's entry declares, else every column that is not a date;
  tables the researcher supplied only where columns are declared.
- **Statistics come from a library.** scipy and statsmodels are now
  dependencies: the estimation runner executes `run_estimation.py` with
  e2er's own interpreter, which had neither, and the FOMC study's specialist
  wrote its own t distribution (p = 0.208 for t = -2.00 with 19 df). The
  econometrics skills require `scipy.stats` or the fitted
  `statsmodels`/`linearmodels` result for every distribution function and
  forbid hand-written approximations; entries carry `hypothesis` and `df`.

### Keys and connectors

- Settings strip surrounding whitespace from every key, token, secret and
  password, whether read from `.env` or the environment; the FRED connector
  and the Zenodo token do the same, and the setup page strips a key it keeps
  from the previous file. A FRED key pasted with a leading space was sent as
  " <key>", which FRED rejects with HTTP 400.
- `e2er-data … --table` fails with exit code 4 and leaves `data.db`
  untouched when the connector reports an error, returns no rows, or returns
  rows without a single value. Before, a failed load was reported only in the
  JSON the model reads.
- `e2er doctor` checks the FRED key's format (32 lower-case letters and
  digits) before requesting anything, and says when the key had whitespace
  around it.

### Fixed

- `event_design.json` is exported to `design/` with the other plan files. It
  went to `misc/`, so `e2er verify` reported a pre-registered event study's
  design as missing.

- The pre-registration check now recognises result files as estimation output:
  csv, tsv, parquet, json or xlsx outside `data/` and the declared data tables,
  named as results (result, estimat, car, abnormal, ar_, regression, coef) or
  with result columns (car, car_*, abnormal*, ar_*, coef*, estimate*, t_stat,
  p_value, alpha_*, beta_*). Plan and description files are never results.
  After a send-back from a blocked pre-registration the check runs again and,
  once clean, the researcher sees the pre-registration.
- A send-back no longer overwrites a file the researcher edited: the specialist
  is not asked for it, and if it rewrites it anyway the researcher's version is
  put back and the specialist's kept in `set_aside/`, recorded as
  `researcher_edit_restored`.

## [0.12.1] — 2026-09-29

### Studies and versions

- **A study is a group of attempts.** Running a question again adds an
  attempt to its study instead of a new row in the list. Attempts with the
  same research question (spacing, case and trailing punctuation ignored) and
  the same template belong to one study; each attempt is a version (v1, v2, …
  by start time), and the study takes the latest attempt's title.
- **The studies list** shows one row per study: title, template, the number
  of attempts, a status summary ("3 completed · 4 rejected · 13 failed") and
  the latest attempt's status and date. It is sorted by last activity and has
  a search box.
- **The attempts page** (`/studies/<key>`) lists a study's attempts with
  version, status, start and update dates, model and backend, and a link to
  each paper page. The paper page says which study and version it is
  ("v3 of 9").
- **Move to study…** on an attempt puts it into another study, or splits it
  off into one of its own, for questions that were grouped wrongly.

### Archiving

- An attempt, or a whole study, can be archived: it is hidden from the lists
  and nothing else changes. No record, file or workspace is deleted, and
  running and paused attempts are refused, with the reason.
- **Archive failed and cancelled attempts** shows the count and the list in
  the page before it archives, and archives only what was shown.
- **Show archived (n)** brings archived attempts back into view, with an
  Unarchive button per study and per attempt.
- On the command line: `e2er list` (`--attempts`, `--archived`, `--search`),
  `e2er archive <paper_id>`, `e2er archive --study <key|id>`,
  `e2er archive --failed` (a dry run unless `--yes`) and
  `e2er unarchive <paper_id>` (or `--study`). The first 8 characters of an id
  are enough.
- New columns `papers.study_key`, `study_override` and `archived_at`. SQLite
  databases gain them on start-up and existing attempts are grouped
  automatically; Postgres gets `sql/015_papers_study_versions.sql`. Both are
  safe to run again. The new endpoints need the dashboard session, like the
  setup and finish pages.
- The list no longer shows a cost column; the cost is on each paper page.

### Cancel a paused attempt

- A paused attempt (stopped by the budget or the circuit breaker, or waiting
  at a researcher step) can be ended with **Cancel attempt** on the attempts
  page and on the paper page, or with `e2er cancel <paper_id>`. Before, a
  paused attempt could only be resumed, so it could never be archived.
- Its status becomes cancelled and the cancellation is recorded as a
  researcher step ("cancelled by the researcher", with the time and whether it
  came from the dashboard or the command line), so the dossier of a later
  export shows it. The workspace is kept, and the attempt can then be archived
  like any cancelled one.
- Refused when another running e2er process owns the attempt, and for
  attempts that are running or already over.

### Fixed: a second e2er process paused a study another process was running

- Two e2er servers on one database: when the second one started, its start-up
  recovery paused every paper that looked "running", including a paper the
  first server was still running (recorded as "interrupted — the server
  stopped while this paper was running").
- A run now records its owner (host, PID, process start time, port and an
  instance id) when it starts or resumes, and refreshes a heartbeat every
  minute. Start-up recovery pauses a paper only when the owner process is
  gone, or when its PID now belongs to a different process. A paper owned by a
  live process is left alone and logged ("running on another e2er process
  (PID …, port …)"). For attempts started by an older e2er, which have no
  owner recorded, recovery waits until there has been no activity for 10
  minutes.
- The paper page shows such a paper as "Running in another e2er process",
  with a link to that one and without Resume or Cancel; the resume and cancel
  endpoints refuse it (409).
- New columns `papers.run_owner` and `heartbeat_at`
  (`sql/016_papers_run_owner.sql` for Postgres). Changes to these columns and
  to the study columns no longer move `updated_at`, so archiving or a
  heartbeat does not reorder the list.

## [0.12.0] — 2026-09-29

### Fixed: templates missing from the 0.11.0 package

- The 0.11.0 package on PyPI did not contain the templates (`pipelines/`).
  After `pip install e2er` no study could start: every template name failed
  with "no pipeline named 'empirical'". 0.12.0 ships all four templates
  (empirical, empirical-preregistered, event-study-finance, replication).
  Upgrade with `pip install -U e2er`.
- CI now builds the wheel, installs it into a fresh virtualenv outside the
  checkout, and checks that `e2er --help` runs, that the four templates and the
  skill files resolve, and that `e2er verify` passes on a copy of
  `examples/showcase` (`scripts/check_wheel.sh`, job `package` in
  `.github/workflows/tests.yml`). Run against the 0.11.0 wheel, the check fails.

### e2er in the browser

- **`e2er` alone opens the browser.** It starts the dashboard on 127.0.0.1 and
  opens it when started from a terminal (`--no-browser` turns that off); the
  address is always printed. When e2er is already running on the port, it opens
  that one. `e2er --port N` picks another port.
- **Setup page (`/setup`)**, shown automatically while no settings exist and
  under Settings afterwards. One card each for the AI provider (the installed
  claude/codex/gemini CLIs and whether they are signed in, API keys; a model per
  provider with the cheapest labelled), literature, data folder, Docker and
  optional keys (FRED, Allium, Semantic Scholar). With no AI provider found it
  lists the ways to get one, with links; without Docker it says only the
  replication template needs it. Saving writes the same `.env` as `e2er init`,
  owner-only (mode 600), keeps settings it does not manage, shows stored keys
  only as their last four characters, optionally creates `data/` and
  `literature/`, then runs the doctor checks.
- **Folder browser** for literature and data, served by the local server:
  folders plus .bib and .pdf (or data) files, hidden files left out. A .bib
  file, a Zotero export (a .bib with a `files/` folder), a Zotero library or a
  folder of PDFs is recognised and its references and PDFs counted. It needs the
  session token from the launch URL (traded for an HttpOnly, SameSite=Strict
  cookie), answers only to loopback clients with a local Host header and no
  foreign Origin, never adds CORS headers, stays inside the home folder (extra
  roots only via `E2ER_BROWSE_ROOTS`) and does not follow symlinks out of it.
- **New study page:** the research question, template cards read from
  `pipelines/*.toml` (description and the steps where each one stops for you),
  a demonstration box (recorded for that one study) and the rest under More
  options. A refused start is shown on the form with what was typed kept.
- **Progress:** the study's page lists its template's steps with their state,
  the current step, the specialists done and the checks passed or failed, and
  links to the review screen at each pause (offered once the run has actually
  stopped, so approving is never refused).
- **Finish page** (`/papers/<id>/finish`): prepares the exported folder, runs
  the five `e2er verify` checks, and publishes to e2er.org with the fields of
  `e2er publish`: a dry-run preview of the request first, sign-in through the
  device flow, then publish.

### Command line

- **Forgiving paths.** One helper cleans every path typed at a prompt or given
  as a flag: a leading prompt glyph (❯ › $ % > #), surrounding quotes,
  drag-and-drop backslash escapes, `file://` and `~`. `e2er init` accepts a
  folder holding one .bib ("That is a folder. It contains My Library.bib — use
  it? [Y/n]"), a Zotero export or a folder of PDFs, and says what it expected
  and what it found.
- `e2er doctor` checks the Python version and reports Docker (optional), and
  points to the install instructions when Python is too old or the claude CLI
  is missing. The `.env` from `e2er init` is written owner-only.
- README: install with uv (Python 3.12 pinned), or pip in a virtualenv.

### Other fixes

- `e2er review` without a terminal exited with an EOFError traceback; it now
  names the flags and the dashboard page to use instead.
- `e2er status` showed "single_pass / empirical" for every study; it now shows
  the study's template.
- The `empirical` template's description says "e2er's default" (was "E2ER's").

## [0.11.0] — 2026-09-29

### Templates

- **event-study-finance** (`pipelines/event-study-finance.toml`): abnormal-return
  event studies around announcements. A fork of `empirical-preregistered` that
  checks the design before estimation. The identification strategist declares
  events and windows in `event_design.json` (schema
  `docs/schemas/event_design.schema.json`, specified in
  `skills/files/econometrics/event-study.md`); the pre-registration includes it
  and treats a later change as a deviation. `docs/proposals/event-study-demo.md`
  proposes a first study (FOMC target-rate changes and bank stocks, 2015–2025),
  not yet run.
- **replication** (`pipelines/replication.toml`): reruns a published study from
  its Zenodo replication package and compares every reported number with the
  rerun. Steps: `fetch` (keyless Zenodo download, each file checked against
  Zenodo's checksum, hashed with SHA-256 and unpacked read-only), `plan` (new
  specialist `replication_planner`), `review_plan` (researcher), `sandbox_run`
  (Docker: dependencies installed with network and without the package, then
  each script run with `--network none`, CPU, memory, process and time limits,
  read-only root, no capabilities, non-root, the package mounted read-only and
  outputs in a separate folder, everything logged with hashes), `compare` (new
  specialist `reproduction_comparer`: reproduced / minor differences / not
  reproduced / could not be run), `reproduction_gate` and `review_report`
  (researcher). The product is the reproduction report and the dossier.
  - Targets have two levels: 1 = a cell of a result file the package ships,
    2 = a number printed in the paper, taken only from the paper (page, table or
    figure, printed decimals).
  - The researcher can supply the paper (`PAPER_PDF`,
    `<LOCAL_DATA_DIR>/paper.pdf` or the workspace's `data/paper.pdf`). The fetch
    step, which runs at every start, stages it read-only as `paper/paper.pdf`,
    fingerprints it, extracts its text page by page for the planner, and records
    it in the dossier as researcher-supplied (`supplied_input`).
  - `src/modules/data/zenodo.py`: keyless Zenodo connector (record metadata,
    linked publications, paced downloads, checksum verification).
  - Skills `replication/reproduction-protocol` (after the Institute for
    Replication and Brodeur et al., 2025), `replication/replication-plan`,
    `replication/reproduction-report`; schemas
    `docs/schemas/replication_plan.schema.json` and
    `docs/schemas/reproduction_report.schema.json`.
- Templates can add skills and machine-readable files to a specialist for their
  own runs (`[skills]`, `[sidecars]`), merged after the registry's; the merged
  skills are recorded in the study's description and dossier.
- Gate steps accept `after = [...]`, like researcher steps: the check runs
  inside the initial phase, after those specialists and before the econometrics
  specialist. `[steps.settings]` holds a check's parameters. A `specialists`
  step without a phase of its own dispatches its `run` list with the registry's
  default work order; a template without a `revision` step completes after its
  last step.

### Checks

- **event_window** (event-study-finance): reads `event_design.json` and stops
  the run when the estimation window is too short (default 120 trading days) or
  too close to the event window (default gap 10), when events of the same asset
  overlap in their event windows without a declared treatment (drop, cluster,
  aggregate), or when an event date is not a trading day in the data. Rule (d):
  when the design names the researcher's own event table (`events_source`), its
  event dates must be exactly that table's dates (non-trading days move to the
  next trading day, reported in the verdict); missing, extra and shifted dates
  are each listed. The calendar must be a table the data dictionary declares and
  the data analyst loaded. The limits are settings of the template; each verdict
  is recorded and appears in the dossier.
- **No estimation before the pre-registration freezes** (check
  `preregistration`, every template with a `preregister` step): estimation
  output in the workspace at that point stops the run with the list. Approving
  does not pass it; sending back the specialist that produced it moves the
  output to `set_aside/` with a manifest, recorded in the dossier.
- **Data-analyst tables**: the data analyst loads, cleans and describes data and
  never estimates. It loads the tables `data_dictionary.json` declares under
  `tables` into data.db (`e2er-data ... --table <name>`), and its contract fails
  when one is missing or empty or `data_summary.md` does not give its actual row
  count (skill `data/data-tables`).
- **reproduction** (replication): re-reads every compared number from the run's
  own output files, reads level-1 numbers from the rebuilt copy of the target's
  own file, and counts each level separately. It follows the governance regime.
  Two further checks, `package_integrity` and `sandbox`, block in every regime
  (the package could not be fetched and verified, or the sandbox could not run).
  The planner's and comparer's JSON files are part of their output contract.
- A failed check stops the run with its reasons and runs again on resume.

### Command line

- `e2er run "<question>" --template <name>` (alias `--pipeline`) chooses the
  template; an unknown name is refused before anything is started.
- `e2er review` shows why a check stopped the run.

### Publishing

- `e2er publish --demonstration`, or `E2ER_PURPOSE=demonstration` in the
  environment or the study folder's `.env`, records `purpose: "demonstration"`
  in e2er.json and the dossier (a dossier without it hashes as before). Studies
  made with the replication template also record `kind: "replication"`.
- For a demonstration, the paper stamp adds the disclaimer as a second
  first-page footnote, and the replication template's reproduction report
  carries the replication wording at the top. The wording is kept in
  `src/core/demonstration.py`.

### Fixed

- `e2er run` cut the title at the first "." anywhere in the question, so a DOI
  or a decimal ended it ("… Brazil (10"). The title is now the first sentence.
- The runner no longer runs another specialist's script on the data analyst's
  behalf (in the 2026-09-28 event study it ran `run_estimation.py`, and
  abnormal returns existed before the pre-registration).

## [0.10.0] — 2026-09-26

### Publishing on e2er.org, with a dossier on every paper

`e2er publish <bundle>` verifies an exported bundle offline and writes its
description (`e2er.json`, schema `e2er-research-object/0.1`,
`docs/schemas/research-object.schema.json`): contributors with GitHub login and
ORCID, backend and models, template and mode, the cited literature with DOIs,
data and outputs with their hashes, and the verification result. Its content id
is the SHA-256 of `provenance.json`.

Publishing also builds the study's **dossier**: every step of the run in order,
the specialist and model that carried it out, the file it produced and the
checks it passed or failed, and every template, specialist, skill and connector
pinned by content hash. The dossier's address is the SHA-256 of its canonical
JSON; the paper gets the author line "<name> with e2er" and a first-page
footnote linking the dossier, and is recompiled. Existing dossier addresses are
unchanged by this release (new fields only appear in dossiers that use them).

- `e2er login`, `logout`, `whoami`: device-code sign-in to e2er.org; the token is
  kept in the system keychain, or in `~/.e2er/credentials.json` (mode 0600)
  when the keychain refuses.
- `e2er publish --to URL` sends the description (never files or AI keys; a scan
  refuses anything that looks like a key or a home-directory path);
  `--dry-run` prints the exact request and changes nothing; `--offline` writes
  the description for publishing from a folder in the browser.
- `e2er status <folder>` and `e2er dossier push` (register a dossier for a
  private study so the paper's footnote resolves).
- `e2er submit` sends a skill, template, specialist or connector for review.
- `e2er verify --json`, for GitHub Actions reporting to e2er.org with OIDC
  (`examples/github-actions/e2er-verify.yml`).

### The researcher decides where the process stops

A template step of kind `researcher` stops the run; the researcher approves,
edits a file, gives an instruction that every later specialist receives, or
sends an earlier step back with a remark (`e2er review`, or the dashboard).
Each action is recorded and appears in the dossier as the researcher's step,
with the file's fingerprints before and after an edit.

### Pre-registration as a template option

A `preregister` step assembles the question, hypotheses, design and analysis
plan and, once the researcher approves it, freezes it with its SHA-256 and the
time. The estimation is compared with the frozen plan; a deviation is reported,
and `e2er verify` shows it. `e2er preregister deposit --zenodo` deposits it
with a DOI from the researcher's own Zenodo account.
`pipelines/empirical-preregistered.toml` uses both steps; `empirical` is
unchanged.

### Data and code, public or private

`e2er publish --data public|private --code public|private` (default private)
records availability in the description and the dossier; for private material
e2er.org receives only fingerprints. `--zenodo` deposits the public data and
code in the researcher's own Zenodo account and records the DOIs.

### Fixed

- Papers compile from their own bundle: the export ships `literature.bib` as
  `refs.bib` and now points `\bibliography` at it (before, a recompile turned
  every citation into "?"); `&`, `%` and `#` in BibTeX text fields are escaped;
  publish refuses a recompile that leaves a citation unresolved, and `verify`
  fails when the paper names a bibliography the bundle lacks.

### Changed

- The name is written lowercase, "e2er", in all visible text (CLI help and
  output, dashboard, documentation). Identifiers, `E2ER_*` settings and the
  citation title are unchanged.

## [0.9.1] — 2026-09-18

### A corpus of what papers claim, not just that they exist

A literature search returns titles and abstracts. A drafter given thirty BibTeX
entries can cite plausibly and nothing more — it has read the metadata and is
guessing at the content, which is how a related-work section ends up describing
papers nobody read.

`e2er corpus` builds a local library of *claims* instead. Each entry is an
extracted statement plus the verbatim sentence it came from, checked against the
paper's full text; a claim whose quote cannot be located is discarded rather
than flagged. That is the numbers gate one level up — a table cell must trace to
a sidecar key, a claim must trace to a sentence, and neither check asks a model
whether it is telling the truth.

```
e2er corpus add ~/papers/                  every PDF in a folder
e2er corpus add "10.1257/aer.20201397"     one paper by DOI
e2er corpus topics add "stablecoin runs"   a standing interest
e2er corpus refresh                        re-run topics, extract only what is new
e2er corpus search "null effects of listing"
```

The library lives at `~/.e2er/corpus.db` (`CORPUS_DB` to move it), outside any
workspace, and accumulates across projects. `refresh` checks coverage before
downloading or calling a model, so running it on a schedule is cheap.

A paper run reads the PDFs staged in its own `literature/` folder into the
corpus before drafting, then writes the matching claims to
`literature/corpus_evidence.md` and seeds `literature.bib` from them — so what
the drafter quotes is what it can cite. `CORPUS_AUTOINGEST=false` disables it.
With no corpus, nothing changes.

The record format is published as
[`docs/schemas/structured_review.schema.json`](docs/schemas/structured_review.schema.json)
and specified in [docs/STRUCTURED_REVIEWS.md](docs/STRUCTURED_REVIEWS.md), so
another tool can produce records E2ER reads or read records E2ER produces. It is
validated against what the code emits in CI, because a format published as
implementable is a promise and an unchecked promise drifts.

### Two thirds of the "fabrications" were the checker

`e2er corpus stats` reports how often the extractor supplied a quote that was
not in the paper — fabrication measured under the least favourable conditions
for fabricating, since the prompt states the quotes are checked mechanically.

On the first real corpus that read 1.1%. Re-downloading every paper and
re-checking each rejected quote showed **four of six were true verbatim quotes**,
failing on artefacts of PDF extraction: hyphenated line breaks arriving as
hyphen+space, and an `fi` ligature. The real rate was closer to 0.4%.

`normalize()` now folds ligatures, and quote matching falls back to a
whitespace- and hyphen-free comparison when the strict match fails — dropping
exactly what those artefacts are made of, while wording and word order still
have to match exactly. A paraphrase, a reordering and an invented sentence are
all still rejected, and there are tests for each.

The prediction this replaced was also wrong: `limitations` was expected to be
the most-invented field, being diffuse and easy to reconstruct. It produced 129
claims and zero rejections.

### Fixed

* **`e2er corpus refresh` was not incremental for preprints.** Coverage was
  checked by DOI, and arXiv assigns none — so every preprint was re-downloaded
  and re-extracted on every refresh, forever. Papers now carry a title-and-year
  key used only for the coverage check.
* **One provider could take the whole search budget.** Five OpenAlex records
  filled a limit of five, every one of their "open access" URLs was a publisher
  landing page, and arXiv — which serves real PDFs — was never reached. Sources
  are interleaved round-robin.
* **A landing page was reported as a scanned PDF.** Resolvers routinely return
  HTML at a URL ending in `.pdf`; the failure now names what actually arrived
  instead of sending the reader after an OCR problem that does not exist.
* **A local PDF was titled by its filename.** `extract_pdf_metadata()` existed
  and was not called, so a paper was stored as `1-s2.0-S0378426619301234-main`
  with no authors, year or DOI. Its title heuristic also stopped at the first
  line, truncating any title that wrapped — and a truncated title deduplicates
  against nothing.
* **The same paper could be stored twice**, once from a PDF and once from the
  web. An arXiv stamp is now read as the DOI arXiv mints from it, and a title
  that is the beginning of another counts as covered — used only to decide
  whether to skip a paper, never to decide which record a review is written to.

## [0.9.0] — 2026-09-13

### A bibliography exists before the drafter writes

Literature acquisition runs as a pipeline stage, before any specialist, and
writes `literature.bib` from the paper's own research question and title. It
self-skips when a bibliography already exists, so a researcher's own library
always wins.

It is a stage rather than a tool deliberately. The drafter already had a
`save_bibtex` tool and a skill file telling it to use one — and `tool_loop`
ignores SDK tools on every CLI backend, so the drafter cited from memory
against a `references.bib` that did not exist. Granting a capability and
instructing a model to use it does not make it used.

Also fixes the OpenAlex provider, which returned 400 for any query containing
`?` or `*`. A research question normally ends in `?`, so the provider was
failing outright and acquisition silently fell through to a weaker source.

### Verification now checks what it claims to

Four defects, found by producing the first completed run rather than by
reading the code:

* **The export dropped `tables/`.** The renderer writes one `.tex` per table
  and the draft `\input`s each; `figures/` and `replication/` were copied and
  `tables/` was not, so the bundle carried two `.tex` files against thirteen
  `\input` directives and could not compile.
* **The numbers gate never saw them.** It scanned only the draft, found no
  `tabular`, and reported a pass having traced zero cells — a green tick
  indistinguishable from one that checked every number. Expanding `\input`
  before scanning takes it from 0 traced cells to 346.
* **The provenance graph was empty.** Edges are derived from the run's gate
  report, which recorded no matched cells, so the bundle asserted that every
  number traces to a file while carrying no trace for any number. Now 385
  edges: 346 `table_cell`, 33 citation, 5 figure, 1 estimation.
* **Severity was decided by proximity.** A cell's fate depended on distance to
  the closest value anywhere in the source JSON, so a tampered cell was graded
  "major" rather than critical and did not gate.

New `tables` check: `e2er verify` re-renders the declared tables with the
renderer itself and compares bytes. A difference means the shipped table is
not what the sidecars produce, which needs no heuristic to answer. Coverage is
part of the verdict — tables the paper includes that the renderer does not
produce are named, not implied.

`integrity` now fails a bundle that ships rendered tables and records no
`table_cell` edge, and reports how many cells the graph traces.

### `examples/showcase/`

A real bundle, from the first completed run under `--governance full`: a DiD
on a coin-month panel around the January 2024 spot-ETF approval, with an event
study, a daily rolling-window DiD, a returns-level triple difference, and Chow
and Bai-Perron break tests. 69 files hash-verified, 346 traced cells, 33/33
citations. The test suite now asserts against it rather than against fixtures
the developer invented — which is how all four defects above survived 1341
tests.

### Fixed

* SSRF guard rejected public hosts on NAT64/DNS64 networks, where a public
  hostname resolves to `64:ff9b::<ipv4>` and Python reports the whole prefix
  as reserved. NAT64 and IPv4-mapped addresses are now unwrapped to the
  address the packet actually reaches — which also tightens the guard, since
  `64:ff9b::192.168.0.1` is blocked on the merits of the embedded address.
* `e2er doctor` reported an empty fallback directory as an active literature
  mode, appending "no PDFs/.bib found" to an otherwise-clean pass.
* Version strings drifted: `CITATION.cff` and the README BibTeX still said
  0.8.0, two releases behind PyPI.


### The researcher workflow — bring your own data and papers, branch across models, verify everything

This is the release's headline: E2ER stops being "a pipeline you configure"
and becomes a workflow a researcher directs. Four pillars, each with a
first-class command.

**(a) Bring your own data and your own papers.** `e2er init` now scaffolds
`data/` and `literature/` with READMEs explaining what each accepts, writes
`LOCAL_DATA_DIR` / `LITERATURE_DIR` into `.env`, and gained `--defaults` for
non-interactive/CI setup. `e2er doctor` gained two pure-local checks
(`byod_local_data`, `byod_literature`) that report what E2ER can actually see
— file counts by type, recursion, the three literature modes — so "why isn't
my data being used?" is answerable without a run. Fixed `e2er init`
environment drift: it wrote backend keys the config rejects (`codex_cli`,
`gemini_cli` instead of `codex`, `gemini`) and a `DATA_MODULE_ENABLED` toggle
that hasn't existed since data-module enablement became a computed property.
A test now instantiates `Settings(llm_backend=key)` for every key `init` can
write, so that class of drift can't come back.

**(b) Create a research question.** New `e2er rq --draft "<rough question>"`:
gathers the project's available data sources and local literature, makes one
backend call, and returns a structured `rq.json` — research question,
rationale, candidate variables, identification options, feasibility notes.
It is **advisory only and never creates a paper** (test-pinned): the
researcher reads it, edits it, and decides. `e2er run --rq-file rq.json`
consumes the result.

**(c) Different models, different versions, one comparison.** New
`e2er run-matrix "<RQ>" --backends a,b,c --repeats N` runs the same question
across k backends × n repeats into labeled sibling papers plus a
`matrix.json`. New `e2er compare <matrix.json|bundles>` then diffs what the
models actually *decided*: a design-choice matrix over `identification_spec.json`,
per-field agreement (modal share for scalars, mean pairwise Jaccard for sets),
within- vs between-backend variance, and divergent-field flags. The report
leads with the point: this is **measurement, not selection** — no run is
promoted, nothing is auto-picked, and the preamble says so, because the value
is seeing the solution space, not shopping for a result.

Human-in-the-loop: `e2er run --review-at STAGE` (repeatable) pauses the run
after any pipeline stage. Inspect or edit the workspace, then
`e2er resume <paper_id>` approves that checkpoint and continues — built on the
existing pause/resume + `.pipeline_state.json` machinery, with a Resume button
in the web UI.

**(d) Everything verifiable.** Every export bundle now carries
`provenance.json`: a SHA-256 inventory of every file plus a derivation graph
reconstructed from the gate reports already in the bundle — table cells → the
source JSON key they trace to, citations → registry + DOI, figures → the
figure spec, estimation → the executed script and its log, data → the recorded
queries. Schema at `docs/schemas/provenance.schema.json`.

New `e2er verify <bundle>` is the reviewer's cheap-verification moment:
offline, keyless, sub-second. It re-hashes every file against the manifest,
**recomputes** the numbers and spec checks from the bundled artifacts (the
recomputation is authoritative — an edited report is caught, not trusted), and
resolves every `\cite` against `refs.bib`, treating the bundled registry
result as a snapshot. `--online` re-queries the live registries. A tampered
number, a tampered report, a deleted file, and a broken citation are each
caught. Export also now includes `identification_spec.json` (under `design/`)
and the `replication/` directory, without which the spec check had nothing to
check.

### Governance regimes — the institutions became a switch, so their effect is measurable

- **`--governance off | contracts | full`** (also `GOVERNANCE` in `.env`,
  persisted per paper). `full` is the existing behaviour; `contracts` keeps
  only the specialist output contracts; `off` blocks on nothing.
- **Shadow mode.** A mechanism that isn't enforced still **runs**: it computes
  its verdict and logs `gate_shadow` instead of `gate_enforced`. So an
  ungoverned run doesn't merely fail differently — what the institutions
  *would* have caught is recorded, which is what makes fabrication measurable
  rather than absent. The regime is disclosed in the export bundle's README
  and in `provenance.json`, so a bundle can't quietly hide how it was produced.
- **New `src/core/governance.py`** holds the single enforcement matrix, read by
  both the strategist runner (the three deterministic gates) and the specialist
  layer (output contracts + cascade guard). Unknown regime strings fail closed
  to `full`.
- **Experiment driver** (`scripts/experiment_driver.py` + a YAML config, e.g.
  `experiments/governance_pilot.yaml`): runs the same RQs across regimes × N
  repeats and harvests per-run fabrication counts (critical number mismatches +
  citations missing from the bib + unverifiable citations), completion, and
  shadow/enforced gate failures into `results.csv` + `summary.md`.

### Cross-pipeline citation audit

- New `scripts/verify_external_paper.py` / `src/core/external_verify.py` runs
  E2ER's citation-verification chain (OpenAlex → Semantic Scholar → Crossref)
  over papers E2ER did not write, from their `.bib` reference lists, producing
  per-paper and aggregate "X% of citations verify" reports. Lets the same
  mechanical check be pointed at other pipelines' output.

### Per-paper backend and model override

- `e2er run --backend <name> [--model <id>]` overrides the LLM backend for a
  single paper without restarting the server (the backend used to be
  process-global via cached settings). This is the enabler for `run-matrix`
  and the governance experiment. `papers.backend` column added, with an
  idempotent SQLite backfill for existing databases.

### Fixed — the governance experiment's own measuring instrument

Found by running the pilot (3 regimes × 3 repeats) for the first time. The
metric would have reported **zero fabrication on a run carrying 166 fabricated
numbers**, so a successful-looking experiment would have produced a confidently
wrong null.

- **Prose numbers were invisible to `fabrication_count`.** The harvester counted
  only table cells (`mismatches[].severity == "critical"`). Pilot run `ab95fcba`
  reported `total_values_in_tables: 0` with an empty `mismatches` list — and
  `prose_total: 278`, `prose_mismatched: 166`. Measured fabrication: 0.
  `prose_mismatched` is now counted and reported as its own column.
- **Skipped checks were counted as clean ones.** A citation check that finds no
  bibliography writes `passed: true, total_cites: 0, skipped_reason: …`; the
  harvester read the zeros as "no fabrication". Same skipped-is-not-verified
  error as B-4 in `e2er verify`. Rows now carry `checks_skipped` and `measured`,
  and per-regime means are taken over measured runs only.
- **Non-completed runs contributed structural zeros.** Bundles are exported only
  when a run completes, so `rejected`/`failed` runs — exactly the ones most
  likely to carry fabrication — harvested nothing and averaged in as 0. This
  biased the experiment *toward the null it exists to test*. Harvesting now
  falls back to the paper's workspace, which holds the same reports.

### Fixed — five bugs found by a full review of the above

- **The `contracts` regime was dead code, and `off` still blocked.** The regime
  reached the three deterministic gates but not the specialist-contract layer,
  which is where output contracts are actually enforced. Under `--governance
  off` a missing canonical artifact still raised (run FAILED) and a hollow one
  still flipped the specialist to failure, tripping the circuit breaker after
  three attempts (run PAUSED). `off` and `contracts` were therefore
  indistinguishable, and the experiment's control cell was not a control. The
  regime is now threaded runner → dispatcher → `run_specialist`; under `off`
  the contract check still runs and logs `gate_shadow`, but does not flip
  success, write coaching feedback, or raise. Operational limits (budget cap,
  backend errors, the circuit breaker itself) remain regime-independent — they
  are not verification institutions.
- **Per-paper backend override picked the wrong model.** The model default was
  resolved against the process-global backend, so `--backend openrouter`
  without an explicit `--model` sent a bare `claude-sonnet-4-5` to OpenRouter
  (which needs the `anthropic/` prefix) and every specialist call failed — on
  exactly the multi-backend path `run-matrix` and the experiment use. Adds
  `Settings.default_model_for(backend)`; `default_model` is now defined as
  `default_model_for(llm_backend)`, so the two cannot drift.
- **`provenance.json` recorded `source: null` for every table cell.**
  `verify_numbers` records source keys prefixed with the source *filename*;
  the provenance builder re-flattened the JSON without that prefix, so the
  lookup never matched and per-cell attribution — the headline of the
  provenance work — was null 100% of the time. Now matches the filename
  prefix. (The original test used an unprefixed key and so passed against the
  bug; it now runs the real producer.)
- **`e2er verify` claimed success when it had checked almost nothing.** The
  verdict counted only failures, so a partial bundle — export is best-effort
  and can omit `paper.tex` — printed "Bundle verified — hashes, numbers, spec,
  and citations are internally consistent" and exited 0 having verified only
  hashes. A skip is not a pass: the verdict now names what ran and what was
  skipped, and exits non-zero when no content check ran at all.
- **`e2er run --rq "<RQ>"` crashed with a traceback.** argparse prefix-expanded
  `--rq` to `--rq-file` and tried to open the research question as a filename.
  `run` and `run-matrix` now take an explicit `--rq`, and an unreadable
  `--rq-file` reports one line instead of a stack trace.

### README reframed around the workflow

- The README now leads with the four-pillar workflow and the verification
  thesis rather than a feature list, adds a command table and a "For reviewers"
  section (a keyless, $0 path from install to a verified bundle), and surfaces
  the BYOD scaffolding and the three literature modes.

### Deep revision loop — referees can send the research back, not just the prose

- **`MECHANISM_FAIL` re-does the research instead of terminating.** When the
  mechanism reviewer rejected a paper's *research* (mechanism not computed /
  not convincing — score < 5), the verdict was a **terminal REJECTED**. The
  only review-driven loop that existed, `patch_revisor`, edits prose — it
  cannot recompute an out-of-sample test or re-source a dataset — so the
  referee's substantive findings (sequential validation surfaced exactly this:
  real papers rejected on "the decisive OOS test was never computed") had
  nowhere to go. `_run_revision_phase` now treats `MECHANISM_FAIL` as a trigger:
  it re-dispatches the **research specialists** (`data_analyst` →
  `econometrics_specialist`) and the writer with the **referee reports as
  guidance**, re-renders the deterministic tables, re-drafts, then **re-runs the
  full review** (gates + reviewers) and re-decides — the way a researcher
  responds to a referee.
- **Bounded and terminating.** One deep round (`_MAX_DEEP_REVISIONS = 1`); the
  re-review re-enters the revision phase with the budget spent, so a verdict the
  round can't lift falls through to REJECTED. No infinite loop (regression-
  tested). `MAJOR_REVISION` keeps its existing light prose-patch path unchanged;
  `HARD_REJECT` stays terminal (unsalvageable).
- Tests: +2 (`test_patch_revision_wiring.py`) — MECHANISM_FAIL → research
  re-dispatch with referee feedback → re-review → COMPLETED; and the bounding
  guarantee (exactly one deep round → REJECTED). All existing revision tests
  unchanged.

### Post-execution error feedback — specialists fix their own script crashes

- **Recovers E2ER v1's self-debugging loop inside v3's sandbox.** v1's
  analysis workers had `Bash(python3:*)` and iterated write→run→see-error→fix
  within their turn, so codegen bugs (a bad pandas/numpy idiom) were fixed
  silently. v3 sandboxes execution (no general code tool — the runner runs the
  script post-hoc), so a bug like `'numpy.ndarray' has no attribute 'values'`
  crashed the script, left `estimation_results.json` empty, and failed the
  paper — the model never saw the traceback (it wrote the script blind). This
  is what failed the capstone run (`c141a277`).
- **Fix:** `post_execution.read_execution_error()` reads the crash captured in
  the convention's audit log (`run_estimation.log`) — non-zero exit + empty
  sidecar — and `run_specialist` injects that traceback into the specialist's
  **next** attempt's prompt ("your script crashed: …, fix this bug, don't write
  `{}`"). The model still never runs code; the runner does and just reports
  back, so the security model is unchanged. Turns "write blind → crash → fail"
  into "write → see the traceback → fix → succeed".
- Self-limiting: returns `None` once the sidecar is populated (success) or the
  last run exited cleanly. Covers `econometrics_specialist` + `data_analyst`
  (the specialists with execution conventions).
- Tests: +5 (`test_post_execution.py`) — feedback on crash, none on clean exit /
  populated sidecar / missing log / no convention, plus an end-to-end check
  that the traceback reaches the retry prompt and the fixed script succeeds.

### patch_revisor: partial revision is progress, not rejection

- **A MAJOR_REVISION no longer rejects the paper when only some edits land.**
  The M5 validation run (`0495a50d`) cleared every gate — populated tables,
  `verify_numbers` passed — then was REJECTED in revision because
  `patch_revisor` emitted one over-reaching `paper:full` edit alongside two
  good in-scope ones. The merger correctly dropped the out-of-scope edit (its
  scope-enforcement job — whole-document edits are exactly what the pipeline
  guards against), but `_run_patch_revision` treated *any* non-applied edit as
  fatal (`fully_applied` → else REJECTED), throwing away a near-complete paper.
- **Fix:** complete on progress. If at least one edit applied,
  `_run_patch_revision` transitions to COMPLETED and logs the dropped edits
  (out-of-scope or unmatchable) as non-fatal — mirroring the self-attack
  path's tolerance. REJECTED only when the patch achieved nothing (zero edits
  applied) or no patch file was produced (both unchanged). The merger and the
  scope-enforcement invariant are untouched.
- Tests: +1 (`test_patch_revision_wiring.py`) — in-scope edit applies +
  out-of-scope `paper:full` dropped → COMPLETED with the in-scope edit landed.
  Existing zero-applied → REJECTED cases still hold.

### Closed-loop table_spec key fix

- **Results tables no longer ship with blank cells.** When a `table_spec`
  reference can't be resolved even after the renderer's order-insensitive
  normalization (a genuinely wrong/abbreviated name — e.g. the drafter wrote
  `cw_stat` where the JSON has `clark_west_stat`), `PipelineRunner` now
  dispatches ONE `section_writer` fix with the unresolved references and the
  EXACT keys/fields available in `estimation_results.json` /
  `robustness_results.json`, then re-renders. Runs in `_run_review_phase`
  right before the verify gate; one attempt, then any still-unresolved refs
  stay `---` (and visible in `table_render_report.json`). Closes the loop the
  PR-2 feedback opened — normalization handles the common case, this handles
  the long tail.
- Tests: +4 (`test_table_spec_closed_loop.py`) — feedback lists available keys,
  no-op when nothing's unresolved, dispatch + fix lands the value.

### Table key-resolution + non-gating prose check (PR-2)

- **Cross-specialist key drift is auto-resolved.** The PR-1 validation run
  completed but its results tables came out **blank**: the econometrics
  specialist named specs `full_dp` while the drafter's `table_spec.json`
  referenced `dp_full`, so every column rendered `---`. The renderer now does
  **order-insensitive token matching** (`dp_full` ≡ `full_dp`) for `spec_key`,
  coefficient `var`, and stat `field`, resolving the drift deterministically.
  It matches only when exactly one candidate's token set is equal — never
  guesses on ambiguity or genuinely-different names (`cw_stat` ≠
  `clark_west_stat`). Resolutions are recorded in `table_render_report.json`
  (`normalized`).
- **Key-resolution feedback.** References still unresolved after normalization
  (a truly wrong/abbreviated/missing name) are surfaced by `verify_numbers`
  into `number_verification.json` (`table_spec_unresolved`), annotated with the
  available spec keys, so the drafter can correct `table_spec.json`. The
  `data/table-spec` skill now tells the drafter to read `estimation_results.json`
  and copy its exact keys, and to reconcile against the render report.
- **Prose-number check ("text = table number").** `verify_numbers` now also
  checks numbers in prose (outside tables) against the JSON sources.
  **Deliberately non-gating:** prose mismatches live in their own
  `prose_mismatches` list, are capped at `major` (never `critical`), and only
  flag *near-misses* — a prose number close to but off from a source value.
  Incidental numbers (years, section refs, %s) with no close source are
  ignored, so it reintroduces no false positives; it cannot reject a paper.
- Tests: +4 renderer (token normalization, ambiguity refusal, genuinely-
  different-name stays unresolved), +5 `verify_numbers` (prose match / major-
  not-critical near-miss / unrelated-ignored / non-gating / feedback surfaced).
- **Follow-up:** a closed-loop re-dispatch (auto-fix `table_spec.json` from the
  feedback) is left for later; deterministic normalization already covers the
  validated case, and the feedback makes the rest visible.

### Deterministic results tables — render numbers from JSON, not by hand (PR-1)

- **Results-table numbers are now generated, not transcribed.** New
  `src/core/renderer/tables.py::render_tables()` reads a declarative
  `table_spec.json` (which specs are columns, which coefficients/statistics are
  rows) and fills the cells straight from `estimation_results.json` /
  `robustness_results.json` into `tables/<name>.tex`, which the draft
  `\input`s. A results-table number can no longer be fabricated or
  mis-transcribed — the failure mode the `verify_numbers` gate exists to catch,
  removed at the source. First-party deterministic code called by the runner;
  no LLM in the number path.
- **The model authors only the spec.** New `data/table-spec` skill (mirrors
  `data/figure-spec`); wired into `paper_drafter` / `section_writer`.
  `table_spec.json` is a best-effort sidecar (`SPECIALIST_OPTIONAL_SIDECARS`) —
  theory / design-without-estimates papers legitimately have none.
  `latex/tables` and `writing/cite-numbers-by-source` updated to route numeric
  tables through the spec (prose numbers still governed by cite-by-source).
- **`verify_numbers` false positives fixed.** The gate no longer reads LaTeX
  *structure* as data: `\multicolumn` rows (column-group headers, panel labels)
  are skipped and `\cmidrule` range args are stripped. This is exactly what
  rejected the M5 re-run (`92626bf8`) — `\multicolumn{6}`→"6",
  "Post-2008"→"2008", "Rolling 120"→"120" flagged as mismatches. Genuine
  fabrications in plain data rows are still caught (regression-tested).
- **Renderer is defensive + auditable.** Never raises; dynamic coefficient
  names, optional `forecast_evaluation`/`first_stage`, `null` fields, and
  empty-`coefficients` combination specs all render `---`. A `table_spec`
  reference to a missing key renders `---` AND is recorded in
  `table_render_report.json` (a *detectable* missing reference, not a silent
  wrong number). A pre-compile `ensure_input_stubs` guard backfills any
  dangling `\input{tables/...}` so a missing table can't abort compilation.
  Runner re-renders before both the verify gate and compile (idempotent).
- Tests: +19 `test_table_renderer.py`, +3 `verify_numbers` regression
  (multicolumn/cmidrule not extracted; fabrication still critical).
- **Follow-up (PR-2, not in this change):** retarget `verify_numbers` to check
  *prose* numbers ("text = table number") with conservative matching.

### Post-specialist execution — script discovery + output normalization (M5 re-run fix)

- **Hardens the runner-side execution from the previous entry** after the
  M5 re-run failed in the design phase
  ([`docs/internal/M4_RERUN_FINDINGS.md`](docs/internal/M4_RERUN_FINDINGS.md)). The first
  version keyed on a single hardcoded `run_estimation.py` /
  `estimation_results.json`; the re-run's specialist named its script
  `analyze.py` writing `analysis_output.json`, so the runner found
  nothing and no-op'd. The brittleness had moved from *"did the model run
  the script?"* to *"did the model name it canonically?"* — still a
  model-judgment dependency.
- **Script discovery** (`_discover_script`): an ordered list of canonical
  candidate names is tried first, then a `*.py` glob keeping the script
  whose source references the target sidecar or a declared alternate
  output. `ExecutionConvention` now carries `script_candidates` +
  `output_candidates` instead of a single `script`.
- **Output normalization** (`_normalize_output`): if the discovered
  script writes a populated alternate output (`analysis_output.json`)
  rather than the canonical sidecar, the runner copies it onto the
  canonical name so M4.3 sees it. Recorded in the audit log and on
  `ExecutionAttempt.normalized_from` / `.discovered`.
- **`data_analyst` execution convention** added (script →
  `summary_statistics.json`), same discovery/normalization machinery.
- **`figure_spec.json` is now a best-effort sidecar**
  (`registry.SPECIALIST_OPTIONAL_SIDECARS`): still prompted and checked
  by verify_numbers when present, but no longer hard-gated by M4.3 at the
  data-design boundary — it has no deterministic producer there (its
  values derive from analysis the model can't run). This is what
  unblocks the parallel design-phase batch.
- **Skill nudge** (`econometrics/estimation-results-schema.md`): explains
  the specialist has no code-execution tool, so the way to run estimation
  is to write `run_estimation.py` → `estimation_results.json` and let the
  runner execute it. Best-effort fast-path; discovery is the backstop.
- Tests: +6 in `test_post_execution.py` (glob discovery, output
  normalization, `data_analyst` convention) and +1 in
  `test_contract_check.py` (best-effort `figure_spec.json` not gated).
  Full suite green (841).

### Runner-side post-specialist execution (M5 prerequisite)

- **New `src/core/specialists/post_execution.py`** runs a specialist's
  declared script via `subprocess.run` before M4.3's contract check
  fires, when the script is on disk but the sidecar is empty. Closes
  the load-bearing M5 prerequisite identified in
  [`docs/internal/M4_DIAGNOSIS.md`](docs/internal/M4_DIAGNOSIS.md): in the M4 paper run,
  the econometrics specialist wrote a correct `run_estimation.py` and
  then chose to write `estimation_results.json` as `{}` (per the
  skill file's *"don't fabricate, write empty"* rule), so the paper
  shipped without findings and the mechanism reviewer correctly
  rejected it.
- **Mechanical, not prompt-based**: the runner executes via
  `subprocess.run`, not via the model's tool call. Backend-agnostic
  (works on every backend, even ones without code-execution tools
  exposed to the model). Idempotent (no-op when the sidecar is
  already populated). Auditable via `run_estimation.log` (subprocess
  exit code + full stdout/stderr).
- **Composes with M4.3 (not a replacement)**: post-exec is the
  positive path *"make the right thing happen"*; M4.3 stays the
  negative path *"refuse the wrong thing"*. If post-exec also fails
  (script error, timeout, data-shape mismatch), the sidecar stays
  empty and M4.3 flips the specialist to `success=False` exactly as
  today.
- **Registry-driven**: `EXECUTION_CONVENTIONS` maps specialist →
  script + sidecar + audit log + timeout. Starts narrow with
  `econometrics_specialist` + `run_estimation.py` +
  `estimation_results.json` (the M4 case). Extending to
  `data_analyst` (`build_panel.py` → `summary_statistics.json`) and
  `replication_packager` is a single-line addition after the first
  re-run validates the convention.
- Tests: 16 new in `tests/test_post_execution.py` — the M4 case
  (script writes populated JSON, sidecar gets populated, M4.3
  passes), script-errors path (audit log captures traceback, M4.3
  still rejects), exit-zero-without-writing path (M4.3 catches the
  silent failure), idempotency (populated sidecar = no-op),
  specialist without convention = no-op, plus six unit tests on
  the `_is_sidecar_populated` JSON-rules helper.

## v0.8.2 — 2026-06-10

Cumulative bugfix + capability release on the v0.8 line. Contains the
seven milestones (M1-M3 + M4.1-M4.3) that were developed against the
v0.9 plan in [`docs/internal/V0.9_PLAN.md`](docs/internal/V0.9_PLAN.md). They ship in
v0.8.2 because **the v0.9.0 tag is now gated on M5 producing a paper
that survives review under real conditions** — the v0.9 plan's own
*"install → trust loop closed"* bar. M1-M4.x are necessary but not
sufficient for that gate: the orchestration layer caught its own
failures correctly in the M4 live run, but the pipeline has never
produced a successful end-to-end paper. See
[`docs/internal/VERSIONING_RESET.md`](docs/internal/VERSIONING_RESET.md) for the
argument and [`docs/internal/M4_FINDINGS.md`](docs/internal/M4_FINDINGS.md) for the
live-run findings the M4.x fixes close.

The `Mi (v0.9 plan)` subsection headings below preserve the
cross-reference to the v0.9 plan document; the work itself ships on
the v0.8 line.

### M4.3 (v0.9 plan) — Specialist output-contract enforcement

- **New `src/core/specialists/contract_check.py`** validates that a
  specialist's declared artifact (primary + any sidecars in
  `SPECIALIST_SIDECAR_ARTIFACTS`) has non-trivial content before
  `run_specialist` returns success. Rules per file extension:
  - `.json` — must parse, and parsed value must not be `{}` / `[]` /
    `null`. Empty containers are the M4 failure mode.
  - `.md` / `.tex` / `.py` / `.txt` — at least 100 non-whitespace
    characters. A real specialist output is always a paragraph or more.
  - Other extensions — exists with size > 0.
- **Wired into `run_specialist`**: when the tool_loop returns
  `success=True` but contract check fails, the result is flipped to
  `success=False` with the error prefixed `contract violation: …`.
  The circuit breaker then trips after `_MAX_SPECIALIST_ATTEMPTS=3`
  consecutive failures, halting the run with `PAUSED` instead of
  paying the rest of the pipeline.
- **Closes M4 finding #4 — the biggest of the three follow-ups**: in
  the M4 paper run `econometrics_specialist` returned `success=True`
  but `estimation_results.json` was literally `{}`. The pipeline then
  burned 13.7M tokens / 29 specialist calls writing a paper around a
  hollow result before the mechanism reviewer caught it. Post-M4.3
  that single empty JSON file flips the econometrics specialist to
  failure and the run pauses at the contract boundary instead.
- **Tests**: 21 in `tests/test_contract_check.py` covering the M4
  regression (`estimation_results.json == "{}"`), empty list/null/
  whitespace JSON, invalid JSON, short prose/code, whitespace-only
  files, missing files, nested relative paths, unknown extensions,
  primary + sidecar combinations per specialist, and an
  integration test that runs `run_specialist` with a fake backend
  that writes a hollow sidecar and confirms the result is flipped
  to `success=False` with the right error.
- **Conftest mocks bulked**: pre-M4.3 the mock specialist outputs
  were short stubs (e.g. `"Formula check passed."` = 22 chars). The
  contract check would have false-tripped on them. Updated all
  mocks in `_SPECIALIST_OUTPUTS` to be paragraph-length so they
  match what a real (skill-driven) specialist emits at minimum
  substance; mock sidecars added (`summary_statistics.json`,
  `figure_spec.json`, `estimation_results.json`) so reflexive
  mocks of `econometrics_specialist` / `data_analyst` still pass.

### M4.2 (v0.9 plan) — `verify_citations` parses `\bibitem` bodies

- **New `parse_bibitem_entries(tex)`** in `src/core/pipeline/verify_citations.py`:
  parses the text between consecutive `\bibitem` commands (and between
  the last `\bibitem` and `\end{thebibliography}`) into a bib-shaped
  dict `{cite_key: {title, year, doi}}`. Extracts:
  - **DOI** anywhere in the body (`10.xxxx/yyyy`, with optional `doi:`
    / `https://doi.org/` prefix; trailing punctuation stripped).
  - **Year** from the first `(YYYY)` in the body, falling back to the
    `\bibitem[label]` year when the body uses an unparenthesised form.
  - **Title** between the closing `(YYYY).` of the author block and
    the start of the `\textit{...}` / `\emph{...}` block that wraps
    the journal name. Falls back to "first sentence after the year"
    when no italic journal marker is present.
- **Replaces the degenerate fallback** in `verify()` that constructed
  `{key: {"title": ""}}` for `\bibitem`-only papers. Pre-M4.2 every
  cite came back `unverifiable` with explanation *"bib entry has
  neither title nor DOI — nothing to verify"* — the M2 gate was
  silent on exactly the class of paper most likely to ship
  hallucinated cites.
- **Live-validated on the actual M4 paper draft**:
  - Before: `verified=0 unverifiable=9 missing_in_bib=0 total=9` →
    false-pass under warn-only default.
  - After: `verified=9 unverifiable=0 missing_in_bib=0 total=9` →
    real pass; every Welch-Goyal-replication cite (welch2008,
    clarkwest2007, campbell2008, rapach2010, goyal2024, paye2006,
    timmermann2008, stambaugh1999, cochrane2008) resolves via
    OpenAlex title-search.
- Closes M4 finding #2. 8 new tests including the M4 regression
  (exact Welch-Goyal `\bibitem` format), DOI extraction (raw + URL
  form), label-only year fallback, multi-entry, no-journal-marker
  fallback, end-to-end verify, and empty-body unverifiable
  preservation.

### M4.1 (v0.9 plan) — Cost tracker zeros for flat-rate CLI backends

- **`compute_cost(model, usage, backend=...)`** now returns
  `Decimal("0")` when `backend` is `claude_code`, `codex`, or `gemini`.
  The CLI help and v0.9 plan promise *"$0 if on the Claude Code /
  Codex / Gemini CLI backends"*; this is the implementation that
  makes that promise true. Closes M4 finding #1.
- Updated three call sites to pass `backend`:
  `core/specialists/base.py`, `modules/tracking/usage.py`,
  `core/strategist/runner.py` (`_in_memory_spent` for the budget
  cap's in-memory fallback). Test suite (`test_costs.py`) extended
  to pin the new contract: identical 2M-token usage costs $18.00 on
  `anthropic` and $0 on `claude_code`; unknown backend literals fall
  back to SDK pricing (defensive — a config typo surfaces as
  "expensive", not "free"); `backend=None` preserves legacy behaviour
  exactly.
- Background: in the M4 run, the default `--max-cost 5` cap tripped
  after the first heavy specialist on the `claude_code` backend
  (~$5.25 in fake compute_cost) — forcing an interactive
  `resume --max-cost 100` to keep the paper moving. With M4.1, the
  budget cap stays inactive on the $0 backends.

### M3 (v0.9 plan) — Open-access full-text reach

- **New OA-PDF resolver chain** (`src/modules/literature/oa_resolvers.py`)
  separate from the metadata-fetch chain. One job: produce an OA PDF
  URL for a DOI. Default order: **Unpaywall → OpenAlex → Crossref →
  Semantic Scholar**. Each adapter returns `str | None`; first hit
  wins. Closes M3 of the v0.9 plan.
- **`src/modules/literature/unpaywall.py`** — keyless polite-pool
  resolver. `find_oa(doi, email)` returns full `PaperMetadata`;
  `find_oa_pdf(doi, email)` is the chain entry point. Walks
  `best_oa_location.url_for_pdf` → `best_oa_location.url` → the
  full `oa_locations[]` list, so a paper with a green-OA copy in a
  non-default repository still surfaces.
- **`src/modules/literature/crossref.py`** — extended with
  `find_oa_pdf(doi)` that scans the `message.link[]` array for
  publisher-deposited `content-type: application/pdf` links. Catches
  cases where the publisher's own DOI record points at a PDF that
  Unpaywall hasn't indexed.
- **New `unpaywall_email` setting** (default `research@e2er.app`)
  identifies this client to the OpenAlex / Crossref / Unpaywall
  polite pools — all keyless, all require a contact in every request.
- **`LiteratureToolHandler._read_reference` falls through.** When the
  metadata chain (`doi_fetch_sources`) returns a paper with no
  `pdf_url`, the OA-PDF resolver chain runs. Per-handler-instance
  cache (`_oa_pdf_cache: dict[str, str | None]`): same DOI asked
  twice in a paper run pays the chain **once**; known-misses cache
  too, so retries don't keep hammering Unpaywall + Crossref + OpenAlex.
- **Live-validated** end-to-end: LeCun *Deep learning* (Nature 2015)
  surfaces via Unpaywall (`hal.science`) and Crossref
  (`nature.com/.../nature14539.pdf`); paywalled Science 2007 correctly
  returns no OA URL across all four resolvers.
- Tests: 24 in `tests/test_oa_resolvers.py` covering Unpaywall's
  4-step URL preference, Crossref's PDF-link picker (case-insensitive,
  missing-field, no-PDF), all four OA-resolver adapters (success +
  miss + exception), default chain order, the per-handler-instance
  cache (hit + miss + short-circuit-after-first-hit), and the
  `_read_reference` fall-through path.

### M2 (v0.9 plan) — Citation-integrity gate

- **New `e2er verify-citations` command + pre-review gate.** Mechanical,
  deterministic anti-hallucination for references: parses every
  `\cite`/`\citep`/`\citet`/`\citeauthor`/`\citeyear`/`\autocite`/
  `\textcite`/`\parencite` (plus starred variants and `\bibitem` for
  hand-rolled bibliographies) from the draft, then for each cited key
  verifies the bib entry exists via OpenAlex → Semantic Scholar →
  Crossref by DOI, then by fuzzy title+year match across the same
  three sources. Emits `citation_integrity.json` with per-key status,
  verifier source, matched DOI/title, plus a coverage report
  (cited-but-not-bibbed, bibbed-but-not-cited).
- **Verdict policy** (open question from the v0.9 plan, M2): default
  is **hard-block on `missing_in_bib`** (cite key not in
  `references.bib` — LaTeX would also fail, unambiguous bug) and
  **warn-only on `unverifiable`** (working papers, conference posters,
  industry whitepapers legitimately aren't in OpenAlex/S2/Crossref).
  Flip to hard-block on unverifiable with
  `E2ER_STRICT_CITATION_INTEGRITY=true`.
- **Title-match heuristic, year-gate graduated by match strength:**
  fuzzy matches (0.85 ≤ sim < 0.99) require year within ±1 to reject
  unrelated papers from different decades; exact-title matches
  (sim ≥ 0.99) accept any year. Live-test surfaced the failure mode
  this fixes: OpenAlex's top hit for "Attention Is All You Need" was
  a 2025 reprint; with a strict ±1 gate the canonical 2017 paper
  would never verify.
- **New `src/modules/literature/crossref.py`** — keyless Crossref
  provider (`fetch_by_doi`, `search_papers`) mirroring the existing
  OpenAlex / S2 modules. Joins the verifier chain for citation
  integrity now; M3 will extend it for OA full-text resolution.
- **Wired into the pre-review gate** in `strategist/runner.py` right
  after `verify_numbers`: a paper with hallucinated cites (or, under
  strict mode, unverifiable ones) is rejected before reviewer
  specialists spend tokens — same gating pattern, same `REJECTED`
  terminal status.
- Tests: 29 new in `tests/test_verify_citations.py` covering parse
  (8 cite-command variants + comments + escaped `\\%`), normalization
  (DOI URL prefixes, accented titles, LaTeX braces), title-match
  graduated year-gate, end-to-end happy path, missing-in-bib fail,
  unverifiable warn-vs-strict, DOI-chain fallthrough to title search,
  persistence to `citation_integrity.json`, and CLI registration.

### M1 (v0.9 plan) — `e2er doctor` user-facing preflight

- **New `e2er doctor` command.** Answers "am I ready to spend a paper run?"
  before the user does — checks the LLM backend (CLI on PATH for `$0`
  backends, API key set for SDK backends), bundled skill files, DB (SQLite
  default or Postgres reachable), and probes every configured data +
  literature provider with a one-line "what this paper would have access
  to." Verdict: ✅ Ready / ⚠️ Partial (paper runs work, some providers
  unavailable) / ❌ Blocked (backend, DB, or skills missing — exact fix
  surfaced). `--json` for scripting. Closes M1 of the v0.9 plan.
- **Fast, quiet DB probe.** The Postgres reachability check uses a direct
  `psycopg.AsyncConnection.connect(connect_timeout=5)` instead of going
  through the runtime connection pool — preflight now fails in ~5s instead
  of hanging 30s with retry spam when `DATABASE_URL` points at a Postgres
  that isn't running. Error message includes the actionable hint: unset
  `DATABASE_URL` / `POSTGRES_URL` to fall back to the zero-config SQLite
  default.
- **`scripts/live_check.py` refactored to a thin shim** over the new
  `src.doctor.run_provider_checks` engine. Dev harness and user-facing
  command now share the same probe code (DRY); live-check stays for nightly
  CI and for catching provider drift before users do.

## v0.8.1 — 2026-05-30

## v0.8.1 — 2026-05-30

Stability + corpus extensions. Bug fixes from a full code review —
**safety** (Allium guardrails no longer bypassed without a
`data_dictionary.json`; SQLite Allium-approval workflow works; SSRF
hostname resolution), **Lane-A robustness** (strategist JSON guards,
mechanism-gate, resume-status, single-order cascade), **Lane B/C wins**
(storage citations; OpenAlex/S2 null crash; `e2er run --acknowledge-
unproven`; FileToolHandler sandbox; OpenRouter `content=""`). Plus
user-driven additions: structured GitHub issue templates for data-source
and literature-provider requests, and `LOCAL_DATA_DIR` extensions
(comma-separated roots, recursive walk, PDFs staged into
`workspace/literature/` with `read_reference(path=…)`).

### Cross-lane

- **Structured GitHub issue templates** for the most common asks:
  `data_source_request` (provider, auth, coverage, example RQ) and
  `literature_provider_request` (capability, gap, auth). Both routed by
  `lane-*` / `provider-request` labels. Generic feature requests still go
  via `feature_request.md`.

### Lane A — Pipeline

- **Fix: malformed strategist JSON no longer crashes the paper.**
  `ceiling_check` and `run_self_attack` did a bare `json.loads` on LLM
  output — truncated/invalid JSON raised and failed the whole run. They now
  use the tolerant `extract_json` and skip malformed `WorkOrder`/finding
  items instead of raising.
- **Fix: a missing mechanism-reviewer score can no longer be silently
  accepted.** The Rule-1 mechanism gate no-op'd when the mechanism score was
  absent, letting a paper ACCEPT on the other reviewers' average. A missing
  (but expected) mechanism score now forces `MAJOR_REVISION`.
- **Fix: resume tolerates a bad/legacy persisted status.** `PaperStatus(
  state.last_status)` could raise `ValueError` and wedge a completed paper
  into FAILED on resume; it's now coerced with a safe fallback.
- **Fix: tier-0 context builder handles explicit-null manifest fields**
  (`datasets: null` / `research_question: null`) instead of `TypeError`.

### Lane B — Literature

- **Fix: `store_paper` persists citation counts.** `citations` was in the
  `ON CONFLICT DO UPDATE` clause but missing from the INSERT column list, so
  inserts dropped the count and conflict-updates zeroed it. Added to the
  insert.
- **`LOCAL_DATA_DIR` extensions.** Accepts a **comma-separated list** of
  roots, an opt-in **`LOCAL_DATA_DIR_RECURSIVE=true`** to walk
  subdirectories (paths under `workspace/data/` are preserved), and now
  also **stages `*.pdf` into `workspace/literature/`**. The bib-relevant
  specialists' reference summary lists those local PDFs so they can be
  read via the new `read_reference(path=...)`. New
  `src/modules/local_corpus.py` consolidates parsing/walking;
  `LocalBibLibrary` uses it for `.bib` discovery across multiple roots.
- **`read_reference`** accepts a new **`path`** argument (workspace-
  relative) for the staged local PDFs — no download, no auth, sandboxed
  under the workspace root.

### Lane C — Data

- **Fix (safety): guardrails no longer fully bypassed without a data
  dictionary.** `_query_allium` only ran `validate_all` when a
  `data_dictionary.json` was present, so a production query with no
  dictionary ran with ZERO validation. Now the structural rules (no
  `SELECT *`, time-bound) and feasibility-first/approval gate always fire;
  only the field-whitelist (Rule 2) is dictionary-gated (skipped with a
  warning).
- **Fix: audit inserts generate app-side UUIDs.** `log_query` /
  `create_approval_request` relied on a DB id default; SQLite has none, so
  `id` was NULL and the approval-request join silently never surfaced
  pending production queries on the default SQLite DB. Now both generate a
  `uuid4()` client-side — the Allium approval workflow works on SQLite.

### Cross-lane

- **Fix: cost-estimate labeling for the codex/gemini backends.** `app.py`
  checked `codex_cli`/`gemini_cli`, but the real backend literals are
  `codex`/`gemini`, so synthetic cost figures were mislabeled as real.
- **Fix: `literature_kb_enabled` honors `DATABASE_URL`.** It keyed off
  legacy `postgres_url`/`db_password`, leaving the pgvector KB silently off
  for the documented `DATABASE_URL=postgresql://…` path. Now derived from
  the resolved DB URL.
- **Fix (security): SSRF guard resolves hostnames.** `_check_url` only
  blocked literal private IPs; a hostname (e.g. `metadata.google.internal`
  → 169.254.x, or `localhost`) slipped past. It now resolves the host and
  blocks if any resolved address is private/loopback/link-local.
- **Fix: `e2er run --acknowledge-unproven` flag.** The CLI hardcoded
  `acknowledge_unproven_tuple=True`, silently disabling the $1 first-run
  floor (and the README documented a flag that didn't exist). The flag now
  exists (default off → floor enforced for metered backends); the $0
  flat-rate CLI backends (claude_code/codex/gemini) auto-acknowledge.
- **Fix: single-order dispatch gets the cascade guard.** The missing-
  canonical-artifact check ran only in `execute_parallel`; a lone specialist
  could "succeed" without its artifact and starve downstream work. Extracted
  `assert_artifacts_written`, now applied to both paths.
- **Fix: `FileToolHandler` sandbox uses path containment, not a string
  prefix** (a sibling workspace with a prefix name could escape).
- **Fix: OpenRouter tool-only turns send `content=""`** instead of `null`
  (some OpenAI-compatible servers reject `null` content + tool_calls).

## v0.8.0 — 2026-05-28

Pluggable data & literature providers. Specialists now **discover** data
sources in light of the research question — FRED and yfinance reach the
tool loop via `list_data_sources` + a unified `fetch_data`, and Allium sits
behind a `Warehouse` capability (its 5 guardrails unchanged). They also
pull the researcher's own reference library (local `.bib`, `LOCAL_DATA_DIR`,
and **Zotero** via the Web API) and read **full-text PDFs** (`read_reference`).
Both lanes are now registry-pluggable, so new providers are drop-in.

### Cross-lane

- **`scripts/live_check.py` — live smoke harness.** Exercises the real
  data/literature provider paths (yfinance, FRED, Allium connectivity,
  OpenAlex search, `read_reference` on an OA PDF, Zotero library) against
  live services, auto-skipping providers without credentials. No LLM calls
  (free). Complements `make smoke` (offline/mocked) and `make smoke-paid`
  (full LLM run). Run: `python scripts/live_check.py`.

### Lane C — Data

- **Allium folded behind a `Warehouse` capability (M3b of
  `docs/internal/MODULARIZATION_PLAN.md`).** Allium is now a first-class registered
  provider: `AlliumWarehouse` owns its `card()`, `tools()` (→ `ALLIUM_TOOLS`)
  and `handler()` (→ `DeferredAlliumToolHandler`); `_run_pipeline` assembles
  it by iterating `warehouses(settings)` instead of hardcoding, and the
  catalog builds its card from the warehouse. Pure refactor — same condition
  (Allium key present), same tools, **the 5 `QueryValidator` guardrails and
  approval flow are untouched**, and `has_allium`/`data_module_enabled` are
  unchanged. Completes the Lane-C registry (series + warehouse).
- **Series data in the agent loop + RQ-aware discovery (M3a of
  `docs/internal/MODULARIZATION_PLAN.md`).** FRED and yfinance are no longer
  CLI-only — specialists reach them in the tool loop. New `SeriesFetcher`
  capability + data registry (`providers.py`, `registry.py`) mirror the
  Lane-B pattern. Two new tools: `list_data_sources` (serves the registry
  catalog so the agent picks the right source for the research question)
  and a unified `fetch_data(provider, method, params)`. Allium is unchanged
  — it keeps its guarded `query_allium` tool and is advertised in the
  catalog (the 5 guardrails are untouched). Series tools are always on
  (yfinance needs no key); budgeted (`_MAX_FETCHES=20`). M3b will fold
  Allium behind a `Warehouse` capability into the same registry.

### Lane B — Literature

- **Fix: literature search crashed on OpenAlex/S2 explicit nulls.** A live
  search returned 0 papers because `openalex._parse` raised
  `'NoneType' object has no attribute 'get'` on a result whose
  `primary_location.source` (or `open_access` / `authorships`) was an
  explicit `null` — `.get(k, default)` doesn't apply the default for a
  present-but-null value. Both parsers now guard with `or {}` / `or []`.
  Regression tests added (the mocked payloads previously only used
  well-formed fields, so the bug only surfaced live).
- **Full-text `read_reference` tool (M2.5 of `docs/internal/MODULARIZATION_PLAN.md`).**
  Specialists can now read a reference's PDF in full to deepen the lit
  review, not just its abstract. New `read_reference` literature tool takes
  a `pdf_url` (surfaced in search/fetch results and on `[PDF]`-marked
  reference-list entries, incl. Zotero attachments) or a `doi` (resolves an
  open-access PDF). Downloads (auth'd for Zotero hrefs, `/file/view` →
  `/file`), extracts text via **pypdf** (`pdf.py`), and returns it
  truncated to ~20K chars. Tightly budgeted (`_MAX_READS=6` + per-read char
  cap) given the prior 522K-token literature blowup. `fetch_bytes` gained a
  `max_bytes` override (PDFs exceed the 2 MB default). New `pypdf` dep. New
  `ZoteroLibrary` `ReferenceLibrary` reads the researcher's Zotero library
  via the Web API's native JSON (`zotero.py`), maps items to
  `PaperMetadata`, and captures each item's primary PDF attachment href
  (for the planned on-demand `read_reference` tool, M2.5). Config:
  `ZOTERO_API_KEY` + one of `ZOTERO_USER_ID` / `ZOTERO_GROUP_ID`; merged
  into the reference summary after local `.bib`, deduped by (title, year).
  Unset → no-op. Sync `fetch_text_sync` helper added for the (sync)
  reference-library path. Degrades to `[]` on any Zotero error — can't
  break paper creation.
- **Provider interface + registry (M1 of `docs/internal/MODULARIZATION_PLAN.md`).**
  Formalized the de-facto interface the source modules already shared into
  capability sub-types — `SearchSource` (web discovery; OpenAlex, arXiv,
  Semantic Scholar) and `ReferenceLibrary` (the researcher's own corpus;
  `LocalBibLibrary` over `LITERATURE_BIBTEX_FILE` + `LOCAL_DATA_DIR`) — in
  new `providers.py` / `registry.py`. `LiteratureToolHandler` and
  `_load_reference_summary` now iterate the registry instead of hardcoding
  provider names. Pure refactor: the search (OpenAlex→arXiv) and DOI-fetch
  (OpenAlex→S2) fallback chains are reproduced exactly; +13 tests, no
  behaviour change. This is the seam Zotero (M2) and Citavi (M4) plug into.

## v0.7.3 — 2026-05-26

Fix the patch_revisor section-target resolution bug surfaced by
the v0.7.2 live re-validation on paper `7f4f2363`. The drafter
got a paper all the way through to the revision phase (v0.7.0's
verify_numbers parser fix worked), but the patch_revisor emitted
edits targeting canonical section names (`section:results`,
`section:mechanism`) that didn't exist in the actual draft. The
merger reported "target region not found" with no hint and the
paper REJECTED on parser bugs, not real hallucinations — for the
second release in a row.

### Lane A — Pipeline

- **Merger emits "did you mean..." suggestions on section/table
  not-found.** When `apply_edit` can't resolve a `section:` or
  `table:` target, the error message now appends the list of
  available section titles or labelled tables in the document.
  Example before/after:
  - Before: `target region 'section:results' not found in document`
  - After: `target region 'section:results' not found in document (available sections: 'Introduction', 'Identification Strategy', 'Empirical Strategy', 'Discussion')`
  Two new public helpers: `list_section_titles(text)` and
  `list_table_labels(text)`. Suggestions are suppressed when the
  list is empty (avoids the misleading
  `(available sections: )` suffix on minimal LaTeX skeletons).
  Universal targets (`paper:full` / `abstract` / `references`)
  don't get suggestions.
- **`writing/scoped-revision.md` skill update.** New section
  ("Before you compose any edits — list the draft's actual
  targets") instructs the patch_revisor to grep the draft for
  `\section{...}` and `\label{tab:...}` lines before composing
  patches. Explains the case-insensitive substring matching the
  merger uses, the common failure mode (canonical-name vs
  actual-heading mismatch), and the `paper:full` fallback for
  findings that don't have a dedicated section.

### Test counts

- Mocked suite: 598 passed (was 590 in v0.7.2; +8 here).
- 8 new tests in `tests/pipeline/test_patch_merger.py`:
  - 4 for `list_section_titles` and `list_table_labels` helpers.
  - 4 for the extended error: section suggestions, table
    suggestions, no suggestion for non-section/table targets, no
    misleading suffix when the list is empty.

## v0.7.2 — 2026-05-26

Closes the v0.7.1-noted follow-up: a CLI command to resume
paused / failed / zombie papers. Completes the status / cancel /
resume trio so the operator never has to drop down to curl.

### Cross-lane

- **`e2er resume <paper_id>`** — restart a paused or failed
  paper from the terminal. Optional `--max-cost N` raises the
  cap atomically with the resume (sent through to the v0.5+
  `ResumeRequest` body). Surfaces the paper's title + previous
  status + cap delta + `last_error` before issuing the POST, so
  the operator knows what they're restarting. Unlike `status`
  and `cancel`, this command DOES auto-start uvicorn — the user
  is asking the paper to start running again, so the server
  needs to be up.
  - 200 → prints the new transient status (`resuming`) +
    dashboard URL, optionally tails to terminal via `--tail`
  - 400 → surfaces the validation detail (e.g. non-positive
    cap) directly so the user can fix and retry
  - 409 → "already running" with a hint to `e2er cancel` first
  - 404 → "paper not found"
- **9 new regression tests** in `tests/test_cli_status.py`
  covering: no-cap-change happy path, cap-raise happy path,
  completed-paper short-circuit, 400 / 409 / 503 / 404 error
  paths, `--tail` integration, the API-unreachable branch.

### Test counts

- Mocked suite: 590 passed (was 581 in v0.7.1; +9 here).

## v0.7.1 — 2026-05-26

Two new lightweight CLI commands surfaced by the v0.7.0
fresh-install UX test: when `e2er run`'s tailer times out (or
the user ^C's it), there was no scripted way to re-attach,
inspect the current state, or cancel a runaway paper without
opening the dashboard.

### Cross-lane

- **`e2er status <paper_id>`** — one-shot snapshot of a paper:
  status, mode/methodology, cost meter (with the
  `cost_is_estimate` marker on CLI backends), specialist call
  count, token total, workspace path, dashboard URL. Shows
  `last_error` verbatim when present so the user can diagnose
  REJECTED / PAUSED / FAILED without parsing the events log.
  With `--tail`, re-uses the same polling loop `e2er run` uses
  so the user can re-attach after ^C. Short-circuits on already-
  terminal status (no wasted polls). Hits the local API by
  default; respects `E2ER_API_URL` for remote inspection.
- **`e2er cancel <paper_id>`** — POSTs the `/cancel` endpoint
  with a confirmation prompt (skippable via `--yes`). Surfaces
  the title + current status + spend-so-far before the user
  confirms so they don't cancel by accident. Terminal-status
  short-circuit. Treats post-cancel 404 as success (the paper
  finished while we were asking; that's what the user wanted).
  Brief post-cancel poll so the user sees the CANCELLED
  transition land before the shell returns.
- **Cost output now formats with two decimals.** Pre-fix
  `e2er status` showed `$8.462921999999999`; now `$8.46`. Float
  noise was reaching the user-facing string when the API
  returned high-precision cost totals.
- **`_poll_status` now treats `rejected` as terminal.** Pre-fix
  the `e2er run` tailer kept polling forever on REJECTED papers
  (a v0.5+ status it didn't know about). Observed during fresh-
  install testing on paper 2ca473aa.

### Test counts

- Mocked suite: 581 passed (was 554 in v0.7.0; +27 cli_status).
- 27 new tests in `tests/test_cli_status.py` covering
  formatters, exit codes, the unreachable-API branch, the
  confirmation prompt, and the post-cancel-404 race handling.

### Known follow-up (v0.7.2 candidate)

- `e2er resume <paper_id>` — natural complement to `cancel`.
  PAUSED papers can be resumed via `curl POST /resume` today;
  a CLI command would close the same UX gap that `status` and
  `cancel` close. Out of scope for v0.7.1.

## v0.7.0 — 2026-05-24

Better onboarding + a verify_numbers parser fix, bundled.
Surfaced by direct user feedback ("pip install e2er and then
what?") and by the v0.6.1 live run on paper `f79b7cd9` that hit
two false-positive critical mismatches caused by parser bugs.

### Cross-lane

- **New `e2er init` command — guided first-paper setup wizard.**
  Closes the post-`pip install e2er` onboarding gap. Walks the
  user through 4 steps (LLM backend pick + prereq check, data
  module on/off, optional BibTeX path, optional Postgres
  `DATABASE_URL`), an optional GitHub-integration prompt, then
  writes `./.env` (with confirm-overwrite), runs `e2er
  install-skills`, and prints three concrete example research
  questions to copy. Hand-rolled stdin wizard — no new
  dependencies (no `click` / `prompt_toolkit`). TTY-detected so
  non-interactive invocations exit with a helpful one-line guide
  instead of blocking on `input()`. Secrets discipline: GitHub
  PATs and API keys collected during the wizard are written to
  `.env` as comments, never as live env vars. 24 new unit tests
  in `tests/test_cli_init.py`. README quickstart updated to lead
  with `e2er init`.

### Lane A — Pipeline

- **Fix two `verify_numbers` false-positives**: ISO date strings
  in column headers (`2021-03-01`) were being parsed as the bare
  year `2021`, false-positive-mismatching against unrelated
  source values; and LaTeX brace-protected thousands separators
  (`1{,}573.89` — the form that survives math mode) were being
  split into two bogus numbers (`1` and `573.89`). Both surfaced
  on the v0.6.1 live-validation paper `f79b7cd9`, which was
  REJECTED entirely on parser bugs rather than real
  hallucinations. New `_normalize_cell(cell)` helper runs
  before `_NUMBER_RE` on each tabular cell: normalizes `{,}` →
  `,` so the existing thousands branch picks the value up
  intact, then strips ISO / slash / US date patterns so years
  inside dates don't leak as numeric claims. Bare years outside
  date context (e.g. `Sample size & 2021`) still extract — the
  fix is targeted at dates, not all four-digit numbers. 5 new
  regression tests in `tests/pipeline/test_verify_numbers.py`.

### Test counts

- Mocked suite: 554 passed (was 525 in v0.6.1; +24 wizard +5
  verify_numbers fix).

## v0.6.1 — 2026-05-23

Hot-fix on v0.6.0 closing the known follow-up surfaced by the
v0.6.0 live run on paper `3bc58e8d`.

### Lane A — Pipeline

- **Iterative-phase guard extended to drop the legacy `revisor`**
  on iterations 2+, alongside `paper_drafter`. Both specialists
  rewrite `paper_draft.tex` from scratch every time they run, so
  the same drift argument that motivated step 6's
  `paper_drafter` guard applies to `revisor`. v0.6.0's live run
  showed the strategist dispatching `revisor` during iterative
  phase even though `paper_drafter` was correctly skipped — the
  guard only filtered one. v0.6.1 closes the same door for both.
- **Strategist system prompt updated** to name `revisor`
  explicitly alongside `paper_drafter` in the iterative-phase
  rule, and to point at `patch_revisor` (dispatched automatically
  by the runner's revision phase) as the legitimate path for
  scoped revisions. Removes the v0.6.0 ambiguity where the prompt
  said "use `revisor` only when upstream artifacts are updated"
  but the runner now expects no `revisor` calls in iterative
  phase at all.
- **`test_section_writer_not_dropped_on_iteration_2` renamed** to
  `test_legitimate_specialists_not_dropped_on_iteration_2` and
  updated to reflect the v0.6.1 contract (was asserting `revisor`
  survives the guard, now asserts only the legitimate specialists
  do).
- **4 new regression tests** in `test_iterative_phase_guard.py`
  pinning the extended-guard contract.

Full mocked suite: 525 passed (was 521 in v0.6.0; +4 here).

## v0.6.0 — 2026-05-23

**Targeted-revision discipline.** Closes the three drift sources
identified in `docs/internal/V0.6_PLAN.md`: full-rewrite `revisor` on
MAJOR_REVISION, parallel-`revisor` write race in self-attack, and
unconstrained `paper_drafter` re-dispatch in the iterative phase.
Validated end-to-end on paper `3bc58e8d` (2026-05-22, 38 min,
$12.36 est., Sonnet via Claude Code CLI).

### Lane A — Pipeline

- **New `patch_revisor` specialist + deterministic merger.**
  Replaces the pre-v0.6 `revisor` in every dispatch site. Writes
  structured edits to `paper_draft.tex.edits.json`; the merger
  (`src/core/strategist/patch_merger.py`) validates each edit's
  `target` against the work order's `Finding` list, applies
  in-scope edits to `paper_draft.tex`, and emits
  `paper_draft.tex.applied.diff` as a unified-diff audit
  artifact. One edit type supported in v0.6: `replace_text`
  with `find` / `replace` / `find_must_be_unique`. Target
  schema: `section:<name>` / `table:<label>` / `references` /
  `abstract` / `paper:full`. Edits whose target isn't in the
  findings are rejected before any text is touched.
- **Structured `Finding` dataclass + three collectors.** New
  `src/core/strategist/findings.py` introduces the
  `Finding(source, source_detail, target, severity, problem,
  suggested_fix)` frozen dataclass that every revision source
  emits: `collect_self_attack_findings`,
  `collect_verify_numbers_findings`, `collect_review_findings`.
  `combine_findings` sorts severity-desc with source priority
  (verify_numbers > self_attack > review on ties — numerical
  mismatches are the most mechanical to fix).
- **MAJOR_REVISION wired through `patch_revisor`.** Replaces the
  pre-v0.6 free-text-rationale path. Combines review findings +
  (when present) verify_numbers findings, serialises them as a
  JSON block in the work order's `focus`, dispatches
  `patch_revisor`, calls `merge_patch_file`. fully_applied →
  COMPLETED; missing patch file or failed edits → REJECTED with
  the first 3 failures named in `last_error`. Edge case:
  MAJOR_REVISION with no actionable findings short-circuits to
  COMPLETED without dispatching (avoids wasted spend).
- **Self-attack critical findings wired through `patch_revisor`.**
  Eliminates the pre-v0.6 parallel-revisor write race. Top-3
  critical findings are batched into ONE patch_revisor call.
  Patch failures at this phase are advisory (logged, do NOT
  REJECT) — the downstream review phase catches what remains.
- **`verify_numbers` auto-patch loop (proactive gate).** Pre-v0.6
  the gate was defensive: critical mismatch → REJECTED. v0.6
  closes the detect → patch → re-detect loop: critical mismatch →
  dispatch `patch_revisor` with the mismatch findings → re-run
  `verify_numbers` on the patched draft → REJECTED only if the
  second pass still has criticals. Bounded by
  `_VERIFY_NUMBERS_AUTO_PATCH_BUDGET = 1` (single attempt) so a
  drafter that consistently disagrees with the source JSON
  doesn't loop. The persisted `number_verification.json`
  reflects the post-patch state.
- **Iterative-phase guard against `paper_drafter` re-dispatch.**
  Two-layer defence:
  - Soft: strategist's system prompt instructs it to use
    `section_writer` (scoped to a `section:<name>` focus) on
    iterations 2+, never `paper_drafter`. Validated on the live
    run — strategist used `section_writer` 3× in iter 2.
  - Hard: `_dispatch` drops `paper_drafter` work orders when
    `self._iteration >= 2`, logging a warning. Catches the
    strategist if it ignores the soft instruction. iteration 0
    (initial) and iteration 1 (first iterative) still allow
    `paper_drafter` legitimately.
- **`patch_revisor` loads three skills.** `writing/scoped-revision`
  (new — defines the patch-file shape with worked examples for
  verify_numbers and self_attack findings),
  `writing/cite-numbers-by-source` (v0.5 — same discipline as
  the drafter), `writing/personal-style`, `reasoning/anti-slop`.
- **Five architecture invariants pinned.** Each step has a
  primary regression test; `tests/pipeline/integration/test_v0_6_invariants.py`
  documents all five in one place and adds cross-step
  assertions (legacy `revisor` never dispatched by v0.6 runner
  paths; both source types reach `patch_revisor`'s focus when
  review + verify_numbers both have findings; merger
  scope-enforcement holds across dispatch sites).

### Test counts

- Mocked suite: 521 passed (was 422 in v0.5.0; +99 in v0.6).
- New test modules: `test_findings.py`, `test_patch_merger.py`,
  `test_patch_revision_wiring.py`, `test_self_attack_patch_wiring.py`,
  `test_verify_numbers_auto_patch.py`, `test_iterative_phase_guard.py`,
  `test_v0_6_invariants.py`.

### Known follow-ups (deferred to v0.6.1)

- The legacy `revisor` specialist is no longer dispatched by v0.6
  runner code paths, but the strategist may still freely dispatch
  it from `_run_iterative_phase`. Surfaced by the 2026-05-22 live
  run (one revisor call in iterative phase). Candidate fix:
  extend the iterative-phase guard to also drop `revisor` on
  iterations 2+, OR update the strategist prompt to discourage
  it explicitly.

## v0.5.0 — 2026-05-21

**Anti-hallucination & methodology-aware pipeline.** Full design
record at `docs/internal/V0.5_PLAN.md`. Motivated by v0.4.5 live tests on
papers `a6182f08`, `cbe8048f`, `eea5379b`, and validated end-to-end
against fresh live runs on 2026-05-20 (`234a11ea`, `fd6bf64d`) and
2026-05-21 (`525fa03c`) — see `docs/internal/V0.5_LIVE_VALIDATION.md`.

### Lane A — Pipeline

- **Programmatic anti-hallucination gate before review** (new file
  `src/core/pipeline/verify_numbers.py`, 357 lines). Scans every number
  in `\begin{tabular}` blocks of `paper_draft.tex` and matches each
  against the flat numeric values from `summary_statistics.json`,
  `estimation_results.json`, `robustness_results.json`, and
  `figure_spec.json`. Tolerance 0.5% relative; integers ≥10 must be
  exact; signs must match. Critical mismatches (relative error >10%
  vs the closest source value) → status `REJECTED` and reviewers
  never spawn. Persists `number_verification.json` at workspace root
  on every run. Live-test paper `a6182f08`'s "log realized variance
  falls by 0.41 ($t=-3.9$)" hallucination was caught by
  `technical_reviewer` only after 6 reviewers had run; this gate
  catches it deterministically, at $0, before any reviewer spends a
  token. Graceful skip when no source JSON files are present (warn +
  pass), so papers from before the analyst contract was tightened
  don't regress.
- **Methodology-aware phase routing.** `PipelineRunner.__init__` now
  accepts `methodology: str = "empirical"`, propagated from
  `papers.methodology` through `_run_pipeline` and `resume_paper` in
  the API. For `methodology == "theoretical"`,
  `_reviewers_for_methodology()` drops `data_reviewer` from the
  6-reviewer panel and `_run_replication_phase()` early-returns.
  Live-test paper `cbe8048f` burned ~$0.34 on a `data_reviewer` stub
  over an empty contract plus ~$0.43 on a replication packager with
  no replication artifacts — both wasted, both gone in v0.5.
- **New status `PaperStatus.REJECTED`, distinct from `FAILED`.**
  `FAILED` is reserved for crashes; `REJECTED` means the pipeline
  ran successfully and the quality gate (verify_numbers,
  HARD_REJECT, MECHANISM_FAIL) returned a negative verdict.
  Resumable: transitions back to IDEA / IN_PROGRESS / REVIEW /
  REVISION / CANCELLED. `_run_revision_phase`'s HARD_REJECT and
  MECHANISM_FAIL branches updated to emit REJECTED instead of
  FAILED. New IN_PROGRESS → REJECTED transition for the
  verify_numbers gate path.
- **`BudgetExceededError` → `PAUSED`, resumable.** New `except
  BudgetExceededError` branch in `PipelineRunner.run()`, alongside
  the existing `CircuitBreakerError` handler. Persists state, logs a
  `paused_budget` event with `{spent, cap}`, returns a structured
  `{status: "paused", reason: "budget_exhausted", ...}` payload.
  The operator raises `--max-cost` and POSTs
  `/api/papers/{id}/resume`; existing resume-from-disk logic picks
  up at the first incomplete phase. Previously a budget exhaustion
  was indistinguishable from a crash.
- **`PAUSED` and `REJECTED` rows now persist `last_error`** on the
  `papers` table. Pre-v0.5, only FAILED and CANCELLED rows carried
  the error/reason; PAUSED and REJECTED dropped it at the SQL layer,
  leaving the dashboard with `last_error=NULL` and no way to render
  the budget breakdown, circuit-breaker specialist, or review-gate
  rationale. `_update_status` now treats PAUSED and REJECTED the
  same way as FAILED and CANCELLED for error preservation.
  Discovered while writing the v0.5 budget-pause regression test.
- **`POST /api/papers/{id}/resume` accepts `max_cost_usd` in the
  request body.** Pre-v0.5 the endpoint silently ignored the body and
  read the cap from the DB row, so raising the cap on a budget-paused
  paper required a manual `UPDATE papers SET max_cost_usd = ...`
  beforehand (the workaround surfaced during the 2026-05-20 live
  validation). The endpoint now accepts an optional `ResumeRequest`
  body; a positive `max_cost_usd` is validated and persisted on the
  row atomically with the status reset, then passed to the runner.
  Zero or negative values 400. Calls without a body preserve the
  pre-v0.5 behaviour (use the existing row value).
- **`paper_drafter`, `section_writer`, `abstract_writer`, and
  `revisor` load a new `writing/cite-numbers-by-source` skill** that
  teaches the cite-by-JSON-key discipline: every numeric value in
  the paper must trace to a value in `summary_statistics.json`,
  `estimation_results.json`, `robustness_results.json`, or
  `figure_spec.json`. HTML-comment markers (`<!-- src: file#key -->`)
  let `verify_numbers` mismatches name the exact source path the
  drafter should have used. Reduces hallucination rate in the first
  place; complements the post-hoc gate. Includes the "empty sidecar
  → no quantitative claims" rule so the design-without-estimates
  pathway is explicit.
- **Test-mock fix:** `MockLLMBackend._detect_specialist` now matches
  on the canonical `You are the <Name> specialist` role line in the
  system prompt rather than searching for any specialist name
  substring. The old heuristic silently misrouted calls whenever a
  skill referenced another specialist by name (e.g. the new
  `writing/cite-numbers-by-source` mentions "econometrics
  specialist" → paper_drafter calls were routed to the econometrics
  output → paper_draft.tex was never produced). Now matches one
  occurrence per prompt with no skill-content interference.
- **Machine-readable JSON sidecar contract for verify_numbers.**
  Pre-v0.5 every specialist was told to write EXACTLY ONE file, so
  even when a skill described a JSON sidecar (e.g. `data/figure-spec`),
  the system prompt overrode it and the JSON never appeared. The
  2026-05-20 live runs confirmed this empirically: both papers wrote
  `number_verification.json` with `skipped_reason="no source JSON
  files found"` — the gate was effectively a no-op. v0.5 adds a
  `SPECIALIST_SIDECAR_ARTIFACTS` registry, a `sidecar_artifacts` field
  on `WorkOrder` (auto-populated by `_inject_context`), and a
  multi-file "Required Output" prompt block that lists every required
  file with its role + JSON validity rules. `data_analyst` now emits
  `summary_statistics.json` and `figure_spec.json`;
  `econometrics_specialist` now emits `estimation_results.json`
  (with optional `robustness_results.json`). Two new schema skill
  files (`data/summary-statistics-schema`,
  `econometrics/estimation-results-schema`) teach the JSON shapes and
  the "write `{}` instead of omitting when data was unavailable"
  rule that distinguishes "honest empty" from "missing" for the gate.

## v0.4.5 — 2026-05-19

Bug pack rolling up findings from the v0.4.4 live test (paper eea5379b)
that completed end-to-end on a fresh `pip install e2er`. The pipeline
itself works; these are correctness + clarity fixes around it.

### Lane C — Data

- **Fix nested workspace path on `--save-to`** (Lane C, replication
  correctness). The data_analyst subprocess runs with cwd at the paper's
  workspace dir; `_resolve_workspace` then resolved the relative default
  `workspace_root="workspaces"` against THAT cwd, so the CSV landed at
  `workspaces/<id>/workspaces/<id>/data/`. The model worked around this
  by emitting a `_candidate_csv_paths` fallback in estimation.py — a
  prompt-engineered band-aid for a pipeline bug. Fix: `_resolve_workspace`
  now prefers `$E2ER_WORKSPACE_ROOT` (claude_code injects the absolute
  path) over the relative settings default.
- **Inject absolute workspace_root into the claude_code subprocess env**
  (`E2ER_WORKSPACE_ROOT`) and use an absolute path as the subprocess cwd.
  Without both, the relative `workspaces` string can re-resolve at any
  nested call site.

### Lane A — Pipeline

- **Accept `pipeline_mode` as an alias for `mode`** in `CreatePaperRequest`.
  `e2er run --mode single_pass` reached the API as `pipeline_mode`,
  which Pydantic silently dropped → server fell back to the default
  `"iterative"` → first-run log line falsely reported the wrong mode.
  Also fix `src/cli_run.py` to send the canonical `mode` field.
- **Reword the first-run cap log line.** "override=True" read like the
  server overrode the user's cap; it actually meant the user acknowledged
  the unproven (model, methodology, mode) tuple so the $1 floor was
  lifted to their requested cap. New format spells it out:
  `cap=$20.00 (user_ack_unproven=True, first_run_floor=$1.00)`.

### Cross-lane

- **Label CLI-backend costs as estimates.** Anyone running on
  `claude_code` / `codex_cli` / `gemini_cli` sees Sonnet-rate synthetic
  dollars even though the Max plan absorbs the actual cost. Startup log
  now warns once when a flat-rate backend is selected; the `/api/papers/<id>`
  usage payload carries a `cost_is_estimate` flag so dashboards can
  render the number with the right hedge.
- **`e2er migrate` works on pip-installed wheels.** Old code pointed at
  `scripts/migrate.py` which is excluded from the wheel. Moved to
  `src/db/migrate.py` (importable, ships in the wheel), reads SQL files
  via `importlib.resources("sql")` with a dev-checkout fallback.
- **Drop the stale `_SCRIPTS_DIR` PATH entry on pip installs.** Guarded
  with `.exists()` so the resolved PATH doesn't carry a non-existent
  `site-packages/scripts/` directory that confused `which`-style probes
  inside the claude_code sandbox.

## v0.4.4 — 2026-05-19

Hot-fix over v0.4.3. The PATH-propagation logic added in v0.4.3 used
`Path(sys.executable).resolve().parent` to find the venv bin/ where pip
puts the `e2er-data` entry-point shim. On macOS framework venvs this is
wrong — `bin/python` in the venv is a symlink to the underlying
`Python.framework/Versions/3.12/Resources/Python.app/Contents/MacOS/Python`,
and `.resolve()` follows it, so `.parent` lands in
`.../Python.framework/Versions/3.12/bin/` — which does *not* contain the
venv's entry-point shims. Live test on run `3f921299` confirmed
`e2er-data` was still `command not found` even though the shim existed
at `/tmp/<venv>/bin/e2er-data`.

### Lane C — Data

- **Use `sysconfig.get_path("scripts")`** instead of `Path(sys.executable).resolve().parent`.
  `sysconfig.get_path("scripts")` is the canonical Python API for the
  current-install entry-point dir and returns the venv's own `bin/` on
  Linux, macOS framework venvs, and Windows alike. Verified: on the same
  venv where `.resolve().parent` returned the framework Python's bin,
  `sysconfig.get_path("scripts")` returns the venv's bin and the
  `e2er-data` shim exists there.

## v0.4.3 — 2026-05-19

Hot-fix over v0.4.2. The 0.4.2 wheel boots and the pipeline runs end-to-end,
but the `data_analyst` specialist hits `command not found: e2er-data` and
no data is ever fetched — so papers reach `paper_draft.tex` without any
real data behind them. Trace from run `62526787-da0b-4ebd-8cf9-cf4f3e682a04`
on the v0.4.2 PyPI wheel showed `which e2er-data` → not found inside the
claude_code subprocess, with PATH containing the venv's `site-packages/scripts/`
but not `bin/`. The skill files (`data/yfinance.md`, `data/fred.md`,
`data/allium*.md`) all instruct the model to invoke `e2er-data ...`.

### Lane C — Data

- **Register `e2er-data` as an entry point** in `pyproject.toml [project.scripts]`
  pointing at `src.modules.data.cli:main`. pip now installs a `e2er-data` shim
  next to `e2er` in the venv's `bin/`, so the bash wrapper from the dev
  checkout is no longer required on pip-installed systems.
- **Prepend the venv `bin/` to the subprocess PATH** in `claude_code.py`
  (after the dev `scripts/` dir, before the inherited PATH). Without this
  the entry-point shim is unreachable from the claude_code subprocess
  even after the shim is installed.

## v0.4.2 — 2026-05-18

Hot-fix over v0.4.1. The 0.4.1 wheel shipped only `.py` files + skill
markdown, but the runtime needs three other on-disk asset bundles: the
FastAPI static directory, the Jinja2 templates, and `sql/sqlite/schema.sql`
for the SQLite bootstrap. Without them, `e2er run` on a fresh
`pip install e2er` crashed at uvicorn startup with `RuntimeError:
Directory '.../src/api/static' does not exist`.

### Cross-lane

- **Ship runtime assets in the wheel**: `pyproject.toml` now declares
  `src.api` package-data (`static/*`, `templates/*`) and `sql` / `sql.sqlite`
  package-data (`*.sql`). Empty `sql/__init__.py` and `sql/sqlite/__init__.py`
  make `sql/` discoverable by `setuptools.packages.find`. Verified by
  fresh-venv install + `uvicorn src.api.app:app` boot, `GET /static/style.css`
  serving 5,182 bytes, and an end-to-end `e2er run` reaching terminal
  `failed` status (cost-cap test) with `~/.e2er/papers.db` and the
  workspace directory both created via the SQLite zero-config path.

## v0.4.1 — 2026-05-18

Lifecycle patch over v0.4.0. Three resume/shutdown bugs that surfaced
during the v0.4 SQLite live test.

### Lane A — Pipeline

- **Graceful shutdown** (closes #5): `@app.on_event("shutdown")` now
  cancels in-flight runner tasks and transitions papers to `paused`.
  Skips state.json-says-completed papers. Stops the "zombie row at
  designing/revision after every uvicorn restart" failure mode.
- **Resume writes terminal status** (closes #6): when resume runs on a
  paper whose state.json already has every stage complete, the runner
  now mirrors `state.last_status` back to the DB before returning.
  Previously the DB row stayed at `designing` (the entry value).
- **Resume accepts zombies** (closes #7): `/api/papers/{id}/resume` no
  longer requires status to be `paused`/`failed`. Any non-terminal
  status with no live runner task in `_RUNNING` is resumable. Combined
  with #5, this removes the manual-UPDATE workaround entirely.
- **SQLite translation extensions** (closes nothing — caught by live
  SQLite smoke after v0.4.0 shipped, fixed before tagging):
  `NOW()` → `CURRENT_TIMESTAMP`, plus `::int`/`::bigint`/`::numeric`/
  `::float` casts stripped alongside the existing type/json/interval
  casts. Without these, status UPDATEs silently failed and usage
  aggregations crashed SQLite with "unrecognized token: ':'".

### Tests

- `tests/pipeline/integration/test_graceful_shutdown.py` — 3 new.
- `tests/pipeline/integration/test_resume_terminal_status.py` — 1 new.
- `tests/pipeline/integration/test_resume_api.py` — 4 new + 1 rewritten.

Test count: 326 → 333.

## v0.4.0 — 2026-05-18

The **"actually usable by a stranger"** release. `pip install e2er`
followed by a one-command `e2er run "<RQ>"` now starts a local server,
submits the paper, and tails the run to terminal — zero database setup,
zero `.env` editing required to get to a first paper.

### Cross-lane — User journey

- **Zero-setup default**: `e2er serve` no longer requires Postgres. The
  DB client dispatches to SQLite at `~/.e2er/papers.db` by default; set
  `DATABASE_URL=postgresql://…` to opt into the production stack
  (pgvector + concurrent writes + literature KB).
- **`e2er run "<RQ>"`** subcommand: starts uvicorn in the background if
  needed, POSTs `/api/papers`, tails status to terminal, prints the
  paper's workspace + dashboard URL on completion. ^C is safe — the
  run keeps going.
- **README rewrite**: leads with the 5-minute quickstart + the BYO-CLI
  cost matrix. Architecture / artifact list moved below.
- **GitHub repo description + topics** filled in for discoverability.

### Lane C — Data

- **Raw-data persistence**: every data-pulling subcommand
  (`yfinance history`, `yfinance fundamentals`, `yfinance dividends`,
  `fred series`) gains a `--save-to <rel/path>.csv` flag. The wrapper
  writes the response rows to `workspace/data/<rel/path>` so the
  replication package is runnable offline. Skill files updated to
  mandate `--save-to` on every meaningful extraction. Closes #11.

### Internals

- **DB-client dispatch**: `src/db/client.py` now routes SQLite vs Postgres
  by URL scheme. Postgres ``%(name)s`` parameter style translates to
  SQLite ``:name`` on the fly; Postgres ``::type`` casts are stripped.
  Existing call sites need zero changes.
- **`sql/sqlite/schema.sql`** ships a SQLite-compatible schema with the
  core tables (papers, events, contributions, llm_usage, data_query_records,
  data_approval_requests). pgvector-dependent tables (literature_files,
  knowledge_chunks) are NOT created — KB feature degrades to "disabled"
  on SQLite, as designed.
- **`aiosqlite>=0.20.0`** added to dependencies.

### Tests

- New: `tests/data/contract/test_db_dispatch.py` — 9 tests pinning the
  parameter translation, cast stripping, and path resolution.

## v0.3.0 — 2026-05-16

The **stability sprint**. Five-phase overhaul focused on making v3
*actually* stable for users beyond the maintainer. Adopted patterns
from `Davidvandijcke/coarse` (branching model, slash commands, headless
CLI backends, OIDC PyPI publishing). Test count: 221 → 290.

### Cross-lane — Foundation & process

- **dev/main branch model**: `dev` is now the default integration branch;
  `main` is released-only and branch-protected (PR required, no force
  push, no deletion). All feature work goes through PRs into `dev`.
- **`AGENTS.md`** (new) codifies the three-lane split (Pipeline / Lit /
  Data), the public contracts each lane owns, hard rules (no live runs
  from `dev` without smoke-pass, cross-lane changes need explicit flag),
  and the tag-driven release procedure.
- **`.claude/hooks/session-brief.sh`** runs at SessionStart to dump
  branch, recent commits, CI status, and in-flight paper runs into
  every new Claude Code session.
- **`scripts/release_audit.py` + `make release-audit`**: hard-gates
  (version match between `pyproject.toml` and `src/__init__.py`, clean
  tree, CHANGELOG has entries, no `TODO(release)`, pytest passes) + soft
  gates (on-main, CI green). Required before tagging.
- **`.github/workflows/release.yml`** (new) tag-driven (`push:tags:v*`).
  Enforces tag↔pyproject↔__init__.py version triple-match, runs tests,
  builds wheel, creates GH release. Publishes to PyPI via OIDC trusted
  publishing — no API token secret.
- **Path-filtered per-lane CI** (`ci-pipeline.yml`, `ci-lit.yml`,
  `ci-data.yml`): each lane runs only its own tests; full `tests.yml`
  runs on every dev/main merge.
- **CHANGELOG per-lane organisation**: entries under `## Unreleased` use
  `### Lane A`, `### Lane B`, `### Lane C`, `### Cross-lane` sub-headings.

### Lane A — Pipeline (Phase 2-5)

- **Specialist circuit breaker** (`src/core/strategist/runner.py` +
  `state.py`): tracks consecutive failures per non-tolerant specialist.
  After 3 failures, the runner raises `CircuitBreakerError`, marks the
  paper `PAUSED` (new state), logs a `circuit_breaker_tripped` event,
  and returns cleanly. Tolerant specialists (reviewers, polish) are
  exempt — their failure is non-blocking. Fixes the run #14 failure
  mode where data_analyst was re-dispatched 3+ times when Allium was
  unrecoverable, burning 13 specialists before manual cancel.
- **Resume from last completed stage** (`POST /api/papers/{id}/resume`):
  re-enters the pipeline at the first phase whose canonical artifact is
  missing. Eligible from `paused` or `failed`. Avoids re-running phases
  that already succeeded after fixing a downstream issue.
- **Turn-budget signal in specialist prompts** (`src/core/specialists/base.py`):
  the system prompt opens with a "Turn Budget" section telling the
  model its max_turns and to write a first version of the canonical
  artifact within the first half. Fixes the run #16 failure where
  data_analyst saved write_file for the last turn and hit max_turns
  mid-pagination.
- **`SPECIALIST_SKILLS` consolidation**: previously two parallel dicts
  (`registry.py` and `loader.py`) that drifted whenever someone added a
  skill to one but not the other. Now one source of truth in
  `registry.SPECIALIST_SKILLS` with full paths (`data/cleaning`); loader
  resolves them.
- **Codex headless backend** (`LLM_BACKEND=codex`, src/modules/llm/codex.py)
  for ChatGPT Plus/Pro subscriptions. Shells out to `codex exec` — same
  pattern as the existing Claude Code backend. Adapted from coarse.
- **Gemini headless backend** (`LLM_BACKEND=gemini`, src/modules/llm/gemini.py)
  for Google AI Pro/Ultra. Probes `--approval-mode` vs legacy `--yolo`
  at startup. Adapted from coarse.
- **Skills bundled in the wheel** (`pyproject.toml` + `skills/__init__.py`):
  all 49 skill .md files ship in the e2er wheel. `e2er install-skills
  [--backend claude|codex|gemini|all] [--force]` copies them to the
  per-CLI skills dir (`~/.{backend}/skills/`).
- **Pre-run safety**: PR-time contract tests for specialist artifacts
  (every specialist in `SPECIALIST_ARTIFACTS` has registered skills,
  every skill path resolves to a real .md file, reviewer/polish lists
  stay aligned with registries) and integration smoke (theoretical
  pipeline end-to-end via MockLLMBackend, FastAPI POST surface,
  cascade-detection halt).
- **`POST /api/papers/{id}/resume`** (new endpoint, see above).
- **`GET /api/papers/{id}/failure-bundle`** (new): single-call
  diagnostic returning paper status + last_error (untruncated), every
  pipeline event with full payload, per-specialist drill-down
  (untruncated error_msg), workspace artifact listing (present vs
  missing), and the data_summary.md excerpt. Replaces the
  4-endpoint scavenger hunt diagnosis used to require.
- **Slash commands** (`.claude/commands/*.md`): `/pre-pr`,
  `/diagnose-run`, `/run-paper`, `/release-audit`.

### Lane B — Literature (Phase 2)

- **Provider contract tests** (`tests/lit/contract/test_provider_shapes.py`):
  first dedicated Lane B tests. For OpenAlex, Semantic Scholar, and
  arXiv, mock the documented response payloads and verify parsers
  handle standard shape, empty results, and network errors without
  crashing or raising into specialist code.

### Lane C — Data (Phase 2-3, 5)

- **Live OpenAPI contract tests** (`tests/data/contract/test_allium_developer_schema.py`):
  validates `AlliumDeveloperProvider` method kwargs against Allium's
  published OpenAPI specs (snapshots cached in
  `tests/data/fixtures/`). Catches required-param drift, list-vs-object
  body-shape mismatches, and silently-ignored unknown params. Run
  #14-#18's wrapper bugs would have been red CI checks instead of
  burning real specialist invocations.
- **Nightly schema-drift workflow** (`.github/workflows/schema-drift.yml`):
  re-fetches Allium's live OpenAPI at 03:30 UTC, diffs against the
  cached fixtures, opens a labelled issue with the unified-diff
  artifact if anything changed upstream.
- **Data-layer degradation breaker** (`src/modules/data/allium_developer.py`):
  tracks a sliding window of recent call outcomes. If >50% of the last
  6 calls errored, subsequent calls short-circuit with a structured
  "data layer degraded" envelope BEFORE hitting the network. Stops a
  specialist from draining its turn budget on dozens of 429 retries.
  Self-clears on the next successful call.
- **`GET /api/papers/{id}/data-queries`** (new): every Allium-style
  query the run submitted, with validation/approval status, executed
  timestamps, row counts, plus a rolled-up summary. Replaces the
  manual `cat audit_log.csv | grep` workflow.

### Fixed — Real bugs from the May 2026 NFT-marketplace live run

**Root cause (the hard lesson):** v3 made an architectural change v1/v2 didn't have — instead of delegating to the Claude Code CLI subprocess, it owns the tool-use loop directly via the Anthropic / OpenRouter SDKs (so `AlliumToolHandler` can intercept every tool call for guardrail validation). That introduced a class of bugs the unit-test suite never covered: the layer was never pressure-tested with realistic specialist output sizes. `MockLLMBackend` returns short canned outputs, so unit tests never saw the failure modes that hit on the first live run.

The May 2026 run lost ~$8 across two attempts before the diagnosis: `data_architect` writing `data_dictionary.json` as a single tool call exceeded `max_tokens_per_call=16384`, the model's output was truncated mid-write (`finish_reason=length`), the tool_loop correctly bailed (looping is futile — same wall every retry), the specialist was marked failed, and downstream specialists silently cascaded.

- `src/config.py`: `max_tokens_per_call` default bumped 16384 → 32768. Both Sonnet 4.6 and Haiku 4.5 support 64K out; 32K is a safe floor for the largest single tool argument any specialist emits.
- `src/core/specialists/base.py`: `_MAX_TURNS` 25 → 40. Independent issue from the same run — Sonnet specialists with Allium tools needed 29-38 turns to converge; 25 was tight enough that `idea_developer` hit the cap.
- `src/core/specialists/dispatcher.py`: cascade detection added to `execute_parallel`. After each batch, any non-tolerant specialist (anything not a reviewer / polish specialist) whose canonical artifact is missing now raises `RuntimeError` immediately — preventing downstream specialists from running on absent inputs and looping. Reviewer / polish specialists are still tolerant of partial failure (the aggregator handles gaps).
- `src/api/app.py`: invalid UUIDs on `/papers/{id}` and `/api/papers/{id}` now return 404 instead of 500. Previously a typo'd URL surfaced as `psycopg.InvalidTextRepresentation` → 500.

### Added — Stress tests for the tool-loop layer

`tests/test_tool_loop_stress.py` — five tests covering the failure modes mocked unit tests miss:
- 30 KB JSON tool argument forwarded to handler intact (the NFT-paper repro).
- 100 KB tool result threaded back into the message history verbatim.
- `finish_reason="length"` produces an actionable error referencing the setting to fix (so devs don't chase `max_turns` like I did).
- `max_tokens_per_call` default >= 32K (config-level floor).
- 25-turn message accumulation with correct token-usage summing.

Plus `tests/test_security_review_fixes.py` regression test for the cascade-detection behaviour above (`test_execute_parallel_raises_on_missing_canonical_artifact`).

### Added (P3 engineering hygiene)
- **mypy in CI.** `mypy src/` runs after `ruff` in `.github/workflows/tests.yml`.
  Config in `pyproject.toml` is pragmatic (catches real bugs without grinding
  on annotation completeness): `no_implicit_optional`, `strict_equality`,
  `warn_redundant_casts`. Per-module strictness can be ratcheted up later.
- **Pre-commit hooks.** `.pre-commit-config.yaml` runs ruff (with --fix),
  ruff-format, mypy, and standard hygiene hooks (trailing whitespace, large
  file check, merge-conflict markers, **detect-private-key**) on every commit.
  Install with `make hooks`.
- `Makefile` gains `typecheck` and `hooks` targets; help output updated.
- CONTRIBUTING.md gains a "Pre-commit hooks (recommended)" section and a
  "Local checks before pushing" cheat sheet.

### Fixed (real bugs surfaced by mypy)
- `src/modules/literature/bibtex.py` was calling `bibtexparser.load(f, parser=...)`
  which **does not exist** in bibtexparser v2 (project pins `>=2.0.0b7`).
  Any user with a `LITERATURE_BIBTEX_FILE` set would have hit
  `AttributeError: module has no attribute 'load'` at runtime. Migrated to
  `bibtexparser.parse_file()` and the v2 `Entry.fields_dict` API, with a
  glue layer keeping `_entry_to_metadata`'s dict interface unchanged.
- `src/modules/literature/arxiv.py`: `el.text` was accessed on an
  `Optional[Element]` without a None check — would raise `AttributeError`
  on author entries with missing `<atom:name>` tags.
- `src/modules/github/client.py`: `Github.get_user()` returns
  `NamedUser | AuthenticatedUser`; only `AuthenticatedUser` has `create_repo`.
  Cast added so type narrowing works without breaking tests that mock the
  user with MagicMock.
- `src/modules/github/push.py` and `src/api/app.py`: `GitHubClient(token, user)`
  was constructed with `Optional[str]` arguments that the constructor types
  as `str`. Added explicit None check (returns early when github is configured
  but token/username are missing) plus assert in push paths.
- `src/api/app.py`: `for e in events` shadowed the `except Exception as e`
  variable on the line above, which Python 3 deletes after the except block
  closes. Renamed to `exc` / `ev` to remove the deleted-variable read that
  mypy correctly flagged.
- `src/modules/llm/base.py` `tool_loop` typed `tool_handler: ToolHandler`,
  but engine.py was calling it with `tool_handler=None` for tool-less
  strategist decisions. Widened the abstract signature (and both concrete
  backends) to `ToolHandler | None`, with explicit None handling that
  surfaces a clear error if the model nonetheless requests a tool.
- `src/modules/data/tools.py`: `result` was reassigned from `ValidationResult`
  to `dict[str, Any]` in the same function, which mypy correctly flagged as
  a type confusion. Renamed the second binding to `query_result`.

### Added
- **Methodology selector** — papers now accept a `methodology` field at
  creation time: `empirical` (default, unchanged), `theoretical` (formal
  model only, no data/econometrics specialists), `mixed` (formal model +
  empirical test). Surfaced in the dashboard form and `POST /api/papers`.
- New `theory_specialist` (writes `model_spec.md`) ported from E2ER v2.
  Dispatched by the strategist when methodology is `theoretical` or
  `mixed`. Skill bundle: `base/economist`, `modeling/game-theory`,
  `modeling/asset-pricing`, `math/proof-strategies`,
  `reasoning/identification`.
- `sql/009_papers_methodology.sql` — adds `methodology` column to the
  `papers` table with a CHECK constraint.
- `tests/test_methodology.py` — 12 tests pinning the registry, prompt
  contract, manifest persistence, API validation, and specialist
  invocation.
- GitHub Actions CI: ruff lint + format + pytest on Python 3.11 and 3.12,
  triggered on push to `main` and all PRs.
- Branch protection on `main` requiring both pytest matrix jobs to pass
  before PR merges.
- `Makefile` with `make smoke` (free, ~10s, all 155 mocked tests) and
  `make smoke-paid` (~$0.50 Haiku end-to-end test).
- Issue templates (bug report, feature request) and PR template under
  `.github/`.
- `tests/test_pipeline_resilience.py` — 18 tests guarding against upstream
  result loss when downstream phases fail (crash injection per phase,
  resume-without-redo, artifact persistence, GitHub push idempotence,
  state-file atomicity, no-op replay).
- `SECURITY.md` and `CHANGELOG.md`.

### Changed
- `PipelineState.save()` now writes atomically (tmp + rename) and keeps a
  `.bak`. Previously a crash mid-write could corrupt the only state file
  and lose all upstream progress on resume.
- `PaperStatus` and `PipelineMode` now inherit from `StrEnum`, matching
  the pattern used in E2ER v2.
- Renamed `BudgetExceeded` → `BudgetExceededError` (PEP 8 exception
  naming).
- `src/api/app.py`: `TemplateResponse` calls migrated to the
  `(request, name, context)` signature for current Starlette.

### Fixed
- `tests/test_regressions.py`: removed hardcoded absolute path that
  would have failed on every CI runner.
- `src/modules/data/audit.py` and `tools.py`: missing top-level
  `from pathlib import Path` (worked at runtime only via `from __future__
  import annotations`).
- `src/modules/literature/bibtex.py`: removed unused `doi_index` dead
  code that hid an incomplete dedup intention.

## [3.0.0] — Initial public release

The first open-source release of E2ER. Differs from the private v1/v2
which were tied to internal infrastructure.

### Architecture
- Standalone package — no shared/ imports, no Docker network dependencies
  on private services.
- BYOK for all external services: `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`,
  `ALLIUM_API_KEY`, `GITHUB_TOKEN`.
- Owns its tool-use loop in Python (no Claude Code CLI subprocess) so
  every tool call can be intercepted for guardrail validation.
- Two LLM backends: Anthropic API (with prompt caching) and OpenRouter
  (OpenAI-compatible). Switch via `LLM_BACKEND=anthropic|openrouter`.

### Pipeline
- Two modes: `single_pass` (fast draft) and `iterative` (full loop with
  ceiling detection, self-attack, polish stack).
- New phases vs v2: ceiling check, adversarial self-attack with severity
  scoring, parallel polish stack (formula, numerics, institutions,
  bibliography, equilibria), mechanical 3-rule review aggregation.
- Full pipeline state persistence and resume-from-crash support.

### Data module
- Allium integration with 5 hard guardrails (no `SELECT *`, fields must be
  in `data_dictionary.json`, time-bound `WHERE` required, transaction
  granularity requires justification, production queries require prior
  feasibility run).
- Two-phase workflow: feasibility (auto-approved sample) → production
  (researcher approval required).
- Full audit log persisted as `audit_log.csv` in the replication package.
- Module is optional: set `DATA_MODULE_ENABLED=false` for literature-only
  or manually-provided-data papers.

### GitHub integration
- Auto-creates a per-paper repo with `.gitignore` as the FIRST commit
  (so Overleaf import never pollutes git history with build artifacts).
- Pushes the LaTeX draft, replication package, and audit bundle.

### Cost tracking
- Per-call usage recorded in `llm_usage` table.
- Per-paper hard cost cap enforced at every phase boundary.
- Audit bundle export (`.tar.gz`) includes `usage.json` with full cost
  breakdown.

[Unreleased]: https://github.com/bhanneke/E2ER-project/compare/v3.0.0...HEAD
[3.0.0]: https://github.com/bhanneke/E2ER-project/releases/tag/v3.0.0
