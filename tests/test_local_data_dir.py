"""v0.8: LOCAL_DATA_DIR — the user's BYOD corpus, reusable across papers.

Single env var that holds mixed content (data files + .bib literature)
the researcher wants available to every paper they run. Two pathways:

1. Data-shape files (csv/parquet/jsonl/xlsx/tsv) are symlinked
   into the paper's `workspace/<id>/data/` at paper creation, where
   the existing `_list_user_data` context builder picks them up
   (0.15.0: when no data files were chosen for the study).
2. `.bib` files are written into the study's `literature.bib` with the
   existing `LITERATURE_BIBTEX_FILE` before any specialist runs
   (study_inputs.prepare_papers, 0.15.0), with title-year deduplication
   so the same file in both places doesn't double-list, and
   `_load_reference_summary` shows them from there.

Unset → no-op; everything that worked pre-v0.8 still works.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from src.api.app import _link_local_data_dir_into_workspace
from src.core.specialists.base import _load_reference_summary
from src.modules.local_corpus import DATA_EXTENSIONS as _LOCAL_DATA_EXTENSIONS

# ---------------------------------------------------------------------------
# Symlink staging at paper creation
# ---------------------------------------------------------------------------


class TestLinkLocalDataDir:
    def test_unset_is_noop(self, tmp_path: Path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        _link_local_data_dir_into_workspace(workspace, None)
        # Nothing was created — paper creation should not require a data/ dir
        # just because the helper ran.
        assert not (workspace / "data").exists()

    def test_empty_string_is_noop(self, tmp_path: Path):
        """Edge case: user wrote `LOCAL_DATA_DIR=` (no value) in .env.
        Pydantic-settings hands us an empty string. Don't crash."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        _link_local_data_dir_into_workspace(workspace, "")
        assert not (workspace / "data").exists()

    def test_missing_dir_is_noop_with_warning(self, tmp_path: Path, caplog):
        """If LOCAL_DATA_DIR points at a path that doesn't exist (typo
        in .env, deleted folder), don't fail paper creation — warn
        and continue."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        with caplog.at_level("WARNING"):
            _link_local_data_dir_into_workspace(workspace, "/nonexistent/path/xyz")
        assert not (workspace / "data").exists()
        assert any("not a directory" in r.message for r in caplog.records), (
            "operator must see a warning when LOCAL_DATA_DIR is misconfigured"
        )

    def test_data_files_symlinked(self, tmp_path: Path):
        """Happy path: csv / parquet / jsonl / xlsx / tsv files all get symlinked into
        workspace/data/; a .txt is not a data file (0.15.0: one list everywhere)."""
        local = tmp_path / "corpus"
        local.mkdir()
        files = ["prices.csv", "trades.parquet", "events.jsonl", "panel.xlsx", "sample.tsv"]
        for name in [*files, "notes.txt"]:
            (local / name).write_bytes(b"sample")

        workspace = tmp_path / "ws"
        workspace.mkdir()
        _link_local_data_dir_into_workspace(workspace, str(local))

        for name in files:
            link = workspace / "data" / name
            assert link.is_symlink(), f"{name} should be a symlink"
            assert link.resolve() == (local / name).resolve()
        assert not (workspace / "data" / "notes.txt").exists()

    def test_bib_files_not_symlinked(self, tmp_path: Path):
        """`.bib` files are handled separately by `_load_reference_summary`
        — they must NOT appear in `workspace/data/` (would pollute the
        data context block sent to specialists with literature
        metadata)."""
        local = tmp_path / "corpus"
        local.mkdir()
        (local / "prices.csv").write_text("a,b\n1,2\n")
        (local / "refs.bib").write_text("@article{x, title={X}}\n")

        workspace = tmp_path / "ws"
        workspace.mkdir()
        _link_local_data_dir_into_workspace(workspace, str(local))

        assert (workspace / "data" / "prices.csv").is_symlink()
        assert not (workspace / "data" / "refs.bib").exists(), (
            "`.bib` files must not be staged into workspace/data/ — they're "
            "literature metadata, picked up directly by _load_reference_summary"
        )

    def test_irrelevant_files_skipped(self, tmp_path: Path):
        """Files outside the allowlist (PDFs, images, random binaries)
        get skipped — keeps the specialist context tight."""
        local = tmp_path / "corpus"
        local.mkdir()
        (local / "paper.pdf").write_bytes(b"%PDF-1.4")
        (local / "figure.png").write_bytes(b"\x89PNG")
        (local / "archive.zip").write_bytes(b"PK")
        (local / "real_data.csv").write_text("a,b\n1,2\n")

        workspace = tmp_path / "ws"
        workspace.mkdir()
        _link_local_data_dir_into_workspace(workspace, str(local))

        # Only the .csv survives
        staged = list((workspace / "data").iterdir())
        assert [p.name for p in staged] == ["real_data.csv"]

    def test_subdirectories_ignored(self, tmp_path: Path):
        """The corpus may have nested dirs (e.g. organized by project).
        Step-1 contract: only top-level files are staged. Subdirs are
        an obvious extension but not the v0.8 scope; pinning the
        boundary here prevents accidental recursive symlinking."""
        local = tmp_path / "corpus"
        local.mkdir()
        (local / "top.csv").write_text("a\n1\n")
        nested = local / "nested"
        nested.mkdir()
        (nested / "deep.csv").write_text("b\n2\n")

        workspace = tmp_path / "ws"
        workspace.mkdir()
        _link_local_data_dir_into_workspace(workspace, str(local))

        staged = [p.name for p in (workspace / "data").iterdir()]
        assert staged == ["top.csv"]

    def test_idempotent_on_existing_file(self, tmp_path: Path):
        """If `workspace/data/prices.csv` already exists (e.g. the
        paper was created with an uploaded file before this step), the
        symlinker must NOT clobber it."""
        local = tmp_path / "corpus"
        local.mkdir()
        (local / "prices.csv").write_text("CORPUS\n")

        workspace = tmp_path / "ws"
        (workspace / "data").mkdir(parents=True)
        existing = workspace / "data" / "prices.csv"
        existing.write_text("WORKSPACE_ORIGINAL\n")

        _link_local_data_dir_into_workspace(workspace, str(local))

        # The workspace's own file is preserved; the corpus file is skipped
        assert existing.read_text() == "WORKSPACE_ORIGINAL\n"
        assert not existing.is_symlink()

    def test_extension_match_is_case_insensitive(self, tmp_path: Path):
        """Macs commonly produce .CSV (uppercase from Excel exports).
        The allowlist check must be case-insensitive."""
        local = tmp_path / "corpus"
        local.mkdir()
        (local / "loud.CSV").write_text("a\n")
        (local / "quiet.parquet").write_bytes(b"x")

        workspace = tmp_path / "ws"
        workspace.mkdir()
        _link_local_data_dir_into_workspace(workspace, str(local))

        staged = {p.name for p in (workspace / "data").iterdir()}
        assert "loud.CSV" in staged
        assert "quiet.parquet" in staged

    def test_extensions_constant_includes_expected_set(self):
        """Pin the allowlist so a refactor that drops .parquet or
        .xlsx silently is caught."""
        assert set(_LOCAL_DATA_EXTENSIONS) == {".csv", ".tsv", ".jsonl", ".parquet", ".xlsx"}


# ---------------------------------------------------------------------------
# Literature: .bib files from LOCAL_DATA_DIR
# ---------------------------------------------------------------------------


def _bib(title: str, year: int = 2024) -> str:
    """Render a minimal BibTeX entry the parser will accept."""
    key = title.lower().replace(" ", "_")
    return f"@article{{{key}, title={{{title}}}, author={{Doe, J.}}, year={{{year}}}, journal={{Test J.}}}}\n"


class TestLoadReferenceSummaryWithLocalDir:
    """The researcher's .bib files (LITERATURE_BIBTEX_FILE and any .bib in
    LOCAL_DATA_DIR) reach the writers through the study's own literature.bib.

    Before 0.15.0 `_load_reference_summary` read them afresh at every prompt and
    none was ever written into the study's bibliography, so citing one failed the
    citation check. Now `prepare_papers` writes them (no choice made: all of them)
    and the summary reads them back from the file, so every key shown exists."""

    def _settings(self, **kwargs):
        base = {
            "literature_bibtex_file": None,
            "local_data_dir": None,
            "literature_dir": None,
            "local_data_dir_recursive": False,
            "literature_max_ingest": 500,
            "literature_acquire_limit": 0,
            "zotero_api_key": None,
            "zotero_user_id": None,
            "zotero_group_id": None,
        }
        base.update(kwargs)

        class _Stub:
            def __getattr__(self, k):
                return base.get(k)

            def resolved_literature_dirs(self):
                return base["literature_dir"] or base["local_data_dir"]

        return _Stub()

    def _summary(self, tmp_path: Path, specialist: str = "paper_drafter", **kwargs) -> str:
        import asyncio
        from unittest.mock import AsyncMock

        from src.core.study_inputs import prepare_papers

        ws = tmp_path / "ws"
        ws.mkdir(exist_ok=True)
        settings = self._settings(workspace_root=str(tmp_path), **kwargs)
        with (
            patch("src.modules.literature.discovery.acquire_literature", new=AsyncMock(return_value=0)),
            patch("src.modules.literature.storage.store_paper", new=AsyncMock()),
        ):
            asyncio.run(prepare_papers(ws, "pid", settings, ["a question"]))
        with (
            patch("src.config.get_settings", return_value=settings),
            patch("src.home.find_workspace", return_value=ws),
        ):
            return _load_reference_summary(specialist, "pid")

    def test_no_sources_returns_empty(self, tmp_path: Path):
        assert self._summary(tmp_path) == ""
        assert not (tmp_path / "ws" / "literature.bib").exists()

    def test_only_literature_bibtex_file_v04_behavior(self, tmp_path: Path):
        bib = tmp_path / "curated.bib"
        bib.write_text(_bib("Alpha"))

        out = self._summary(tmp_path, literature_bibtex_file=str(bib))
        assert "The Researcher's Own Papers (1" in out
        assert "\\cite{alpha}" in out, "the researcher's own key, as it is in their .bib"
        bibtext = (tmp_path / "ws" / "literature.bib").read_text()
        assert "@article{alpha," in bibtext and "e2er_source = {researcher}" in bibtext

    def test_only_local_data_dir_picks_up_bib(self, tmp_path: Path):
        local = tmp_path / "corpus"
        local.mkdir()
        (local / "zotero_export.bib").write_text(_bib("Beta"))

        assert "Beta" in self._summary(tmp_path, local_data_dir=str(local))

    def test_both_sources_merged(self, tmp_path: Path):
        bib_curated = tmp_path / "curated.bib"
        bib_curated.write_text(_bib("Alpha"))
        local = tmp_path / "corpus"
        local.mkdir()
        (local / "zotero.bib").write_text(_bib("Beta") + _bib("Gamma"))

        out = self._summary(tmp_path, literature_bibtex_file=str(bib_curated), local_data_dir=str(local))
        for ref in ("Alpha", "Beta", "Gamma"):
            assert ref in out
            assert f"{{{ref.lower()}," in (tmp_path / "ws" / "literature.bib").read_text()

    def test_duplicate_papers_deduped_by_title_year(self, tmp_path: Path):
        local = tmp_path / "corpus"
        local.mkdir()
        shared = local / "shared.bib"
        shared.write_text(_bib("Alpha") + _bib("Beta"))

        out = self._summary(tmp_path, literature_bibtex_file=str(shared), local_data_dir=str(local))
        assert out.count("Alpha") == 1
        assert out.count("Beta") == 1
        assert "(2, chosen for this study)" in out

    def test_non_bib_extensions_in_local_dir_ignored(self, tmp_path: Path):
        local = tmp_path / "corpus"
        local.mkdir()
        (local / "real.bib").write_text(_bib("RealRef"))
        (local / "not_bib.csv").write_text("a,b\n1,2\n")
        (local / "not_bib.txt").write_text("just notes, not BibTeX")

        out = self._summary(tmp_path, local_data_dir=str(local))
        assert "RealRef" in out

    def test_unparseable_bib_skipped_gracefully(self, tmp_path: Path):
        local = tmp_path / "corpus"
        local.mkdir()
        (local / "good.bib").write_text(_bib("Survivor"))
        (local / "broken.bib").write_text("this is not bibtex at all")

        assert "Survivor" in self._summary(tmp_path, local_data_dir=str(local))

    def test_only_bib_specialists_get_the_block(self, tmp_path: Path):
        local = tmp_path / "corpus"
        local.mkdir()
        (local / "refs.bib").write_text(_bib("Alpha"))

        assert "Alpha" in self._summary(tmp_path, local_data_dir=str(local))
        assert self._summary(tmp_path, "data_analyst", local_data_dir=str(local)) == ""
