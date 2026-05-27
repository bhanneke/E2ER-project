# Modularization plan — pluggable data & library providers

**Status:** active design doc (2026-05-28). **Supersedes the roadmap in
`docs/NEXT_STEPS.md`** (that doc is May-12 vintage and frames everything
around an Allium blocker that no longer reflects reality).

## Goal

Make the **library/literature module (Lane B)** and the **data module
(Lane C)** properly pluggable, then add integrations as providers:

1. Formalize a provider interface + registry in each lane.
2. **Zotero** as the first reference-manager integration.
3. **Citavi** and other reference/data APIs as further providers.

The `LOCAL_DATA_DIR` feature (PR #40) was step 0: "select a local folder
containing data + bibtex files." Zotero is the live-synced successor to
its local-`.bib` path.

## Non-goals (for now)

- **No standalone app / container UI yet.** Decision on record: build the
  functionality in the modules first, transfer to an "app container like
  program" later. This doc stops at clean module APIs that such an app
  would later call.
- No change to Lane A (pipeline) contracts. Providers stay behind the
  existing `ToolHandler` seam.

---

## Current architecture (honest assessment)

### The template that already works: LLM lane

`src/modules/llm/registry.py` → `get_backend(settings) -> LLMBackend`:
string-dispatch with lazy imports, backed by the `LLMBackend` ABC in
`base.py`. Five backends register cleanly. **This is the pattern both
other lanes should copy.**

### Lane B — literature (`src/modules/literature/`)

| File | Role |
|------|------|
| `openalex.py`, `arxiv.py`, `semantic_scholar.py` | Web search sources |
| `bibtex.py` | Parse local `.bib` (now fed by `LOCAL_DATA_DIR`) |
| `models.py` | `PaperMetadata`, `SearchResult` — the shared contract |
| `tools.py` | `LITERATURE_TOOLS` + `LiteratureToolHandler` |
| `storage.py` | Persistence |

- **An interface already exists implicitly**: every source exposes
  `async search_papers(query, limit) -> SearchResult` and
  `async fetch_by_doi(doi) -> PaperMetadata | None`. It's just not
  declared as an ABC/Protocol.
- **Fallback chains are hardcoded** in `LiteratureToolHandler._search`
  (openalex → arxiv) and `_fetch` (openalex → s2). Adding a source means
  editing the handler.
- Always-on (OpenAlex needs no key); wired in `app.py::_run_pipeline`.

### Lane C — data (`src/modules/data/`)

| File | Role |
|------|------|
| `allium.py`, `allium_developer.py` | `AlliumProvider` (SQL warehouse, 4-step async) |
| `fred_provider.py`, `yfinance_provider.py` | Series fetchers |
| `tools.py` | `ALLIUM_TOOLS` + `AlliumToolHandler` / `DeferredAlliumToolHandler` |
| `guardrails.py`, `audit.py`, `dictionary.py` | 5-rule validator, audit log, data dictionary |
| `cli.py` | `e2er-data` wrapper |

- **Split personality**: only **Allium** is exposed as in-loop agent
  tools. `fred_provider` / `yfinance_provider` are reachable **only via
  the `e2er-data` CLI** — the specialist tool loop can't call them.
- `Settings.data_module_enabled` is literally `allium_api_key is not
  None`. "Data module" currently *means* Allium.
- Guardrails (`guardrails.py`) are Allium-specific and enforced inside
  the handler. **Any generalization must keep them firing** — this is a
  load-bearing safety property, not incidental.

### Config (`src/config.py`)

Per-credential flags: `allium_api_key`, `fred_api_key`,
`semantic_scholar_api_key`, `literature_bibtex_file`, `local_data_dir`.
No `zotero_*` / `citavi_*` yet. Enablement is ad-hoc per provider.

---

## Target architecture

### Lane B: `LiteratureProvider` + registry

Two distinct **capabilities** — don't force them into one method:

- **Search source** (web discovery): `search(query, limit)`,
  `fetch(doi)`. OpenAlex / arXiv / S2.
- **Reference library** (the user's own corpus): `entries() -> list[PaperMetadata]`.
  Zotero, Citavi, and the local-`.bib`/`LOCAL_DATA_DIR` reader. This is
  what `_load_reference_summary` should consume, instead of reaching into
  files directly.

```python
class LiteratureProvider(Protocol):
    name: str
    def available(self, settings: Settings) -> bool: ...

class SearchSource(LiteratureProvider):
    async def search(self, query: str, limit: int) -> SearchResult: ...
    async def fetch(self, doi: str) -> PaperMetadata | None: ...

class ReferenceLibrary(LiteratureProvider):
    async def entries(self) -> list[PaperMetadata]: ...   # the user's refs
```

Registry: `literature_search_sources(settings)` and
`reference_libraries(settings)` return ordered, available providers.
`LiteratureToolHandler` iterates the search-source list (no hardcoded
fallback); `_load_reference_summary` merges across reference libraries
(local `.bib`, Zotero, …), keeping the existing `(title, year)` dedup.

### Lane C: `DataProvider` + registry (capability-based)

Heterogeneous backends, so capability-typed rather than one fat interface:

- **Queryable warehouse**: `query(sql) -> rows` + guardrail hook. Allium.
- **Series fetcher**: `series(id, start, end) -> frame`. FRED, yfinance.
- **Local files**: the `LOCAL_DATA_DIR` data files (already staged into
  `workspace/data/`).

Bringing FRED/yfinance into the **tool loop** (not just the CLI) is the
substantive win here. `data_module_enabled` becomes "≥1 data provider
available" instead of "allium key present."

**Guardrail invariant:** the warehouse capability keeps the 5-rule
validator + approval flow + audit log. New providers either reuse it or
declare their own; none bypass it.

---

## Milestones

| # | Scope | Risk | Tests |
|---|-------|------|-------|
| **M1** | **Lane B interface + registry refactor.** Declare `SearchSource`/`ReferenceLibrary`, make openalex/arxiv/s2 implement `SearchSource`, wrap local-`.bib` as a `ReferenceLibrary`. Handler iterates registry; `_load_reference_summary` consumes libraries. **No behavior change.** | Low — pure refactor over an existing implicit interface | Existing Lane B suite stays green; add registry tests |
| **M2** | **Zotero `ReferenceLibrary` provider.** Pull the user's library into `PaperMetadata`; feeds the same merge path as local `.bib`. New `zotero_*` config. | Med — first external API; needs the M1 seam | New `tests/lit/` cases, mocked HTTP |
| **M3** | **Lane C interface + registry.** Unify Allium + FRED + yfinance + local-files behind capability types; expose FRED/yfinance as in-loop tools; generalize `data_module_enabled`. Preserve guardrails. | Med-High — touches the guardrail path | Lane C suite green; new tool-loop tests for FRED/yfinance; guardrail regression tests must still pass |
| **M4** | **Citavi + further providers** on the proven interfaces. | Low per provider | Per-provider mocked tests |
| **M5** | *(Deferred)* App container consuming these module APIs. | — | — |

Per `AGENTS.md`, M1–M2 are Lane B, M3 is Lane C — largely independent,
path-filtered CI. Each milestone lands with a CHANGELOG entry under
`## Unreleased` in its lane.

---

## Decisions (locked 2026-05-28)

1. **Zotero access = Web API.** `zotero_api_key` + `user_id`/`group_id`;
   works anywhere, always current. The local-`.bib`/`LOCAL_DATA_DIR`
   reader (already shipped) covers the offline/export case — no fragile
   Better-BibTeX/SQLite reader.
2. **Capability sub-types**, not one fat interface: `SearchSource` /
   `ReferenceLibrary` (Lane B), `Warehouse` / `SeriesFetcher` (Lane C).
   Honest about what each backend can do; no `NotImplementedError` stubs.
3. **FRED/yfinance become in-loop tools in M3** (not CLI-only) — the
   point of modularizing the data module is to let specialists reach
   public data.
4. **Config stays flat** per-key (`zotero_api_key`, etc.) for now;
   revisit a `providers:` block only if the list grows past ~6.

---

## Invariants to preserve (don't regress)

- The 5 Allium guardrails fire on every warehouse query (`guardrails.py`).
- No bare `Bash` in `_DEFAULT_ALLOWED_TOOLS` (CLI gatekeeper).
- `PaperMetadata` / `SearchResult` stay the Lane-B contract; providers
  normalize *to* them.
- `_load_reference_summary`'s `(title, year)` dedup across sources.
- Lane independence + per-lane CHANGELOG discipline (`AGENTS.md`).
