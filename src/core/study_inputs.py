"""What a study uses: the data files and the papers the researcher chose for it.

Until 0.15.0 a study had no choice. Setup named one data folder and one
literature folder for the whole computer, and every study got everything in
them: each data file was linked into the study, each PDF ingested, and the
entries of a ``.bib`` file or a Zotero library were offered to the writers as
citable without ever being written into the study's bibliography (so citing
one failed the citation check).

Now New study lists the files of the data folder and the papers of the
literature folder, the ``.bib`` files and the Library, and the researcher ticks
what this study uses or adds files of their own (``e2er run --data …
--papers …`` does the same in a terminal). The choice is written into the
study's folder as ``.study_inputs.json`` when the study starts::

    {"data":   {"chosen": true, "files": [{"name": "prices.csv", "origin": "folder", "size": 1234}]},
     "papers": {"chosen": true, "web_search": true, "requested": ["pdf:/…/a.pdf", "bib:/…/refs.bib#key"],
                "items": [{"key": "…", "title": "…", "year": 2005, "kind": "pdf", "origin": "folder"}]}}

``chosen: false`` means no choice was made (an API client, or ``e2er run``
without ``--data``/``--papers``): the study takes everything, as before.
From then on only the study's own copy counts: the data files staged into its
``data/`` folder are what the planning check and the specialists see, and the
papers written into its ``literature.bib`` are what the writers may cite.

A paper is named by an id that says where it is:

* ``pdf:<path>``: a PDF (in the literature folder, or added for this study);
* ``bib:<path>#<key>``: one entry of a ``.bib`` file; ``bibfile:<path>``: all of them;
* ``zotero:<folder>#<item key>``: an item of a local Zotero library;
* ``library:<key>``: a paper of the Library (``e2er library``).
"""

from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..logging_config import get_logger

logger = get_logger(__name__)

#: A dot file: it names files on this computer (full paths), so the study folder that is published leaves it out.
INPUTS_FILE = ".study_inputs.json"

#: Where files added on New study wait until the study starts (then they are copied into it).
UPLOADS_FOLDER = "uploads"

#: How a researcher reads where a paper came from (New study, the run's panel).
KIND_LABELS = {
    "pdf": "PDF",
    "bib": ".bib entry",
    "zotero": "Zotero",
    "library": "Library",
}


class InputError(ValueError):
    """A chosen file or paper that cannot be used, in one plain sentence."""


# ── listing what can be chosen ──────────────────────────────────────────────


@dataclass
class DataOption:
    path: str  # absolute
    name: str  # as it is named inside the study's data folder
    size: int
    kind: str  # CSV, XLSX, …


def data_options(settings: Any) -> list[DataOption]:
    """Every data file of the data folder(s), as New study lists them."""
    from ..modules.local_corpus import DATA_EXTENSIONS, iter_corpus_files, parse_corpus_roots

    recursive = bool(getattr(settings, "local_data_dir_recursive", False))
    out: list[DataOption] = []
    seen: set[str] = set()
    roots = parse_corpus_roots(getattr(settings, "local_data_dir", None))
    for root, path in iter_corpus_files(roots, DATA_EXTENSIONS, recursive):
        rel = path.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        name = rel.as_posix() if recursive else path.name
        if name in seen:
            continue
        seen.add(name)
        try:
            size = path.stat().st_size
        except OSError:
            continue
        out.append(DataOption(str(path.resolve()), name, size, path.suffix.lstrip(".").upper()))
    return sorted(out, key=lambda d: d.name.lower())


@dataclass
class PaperOption:
    id: str
    title: str
    authors: list[str]
    year: int | None
    kind: str  # pdf | bib | zotero | library
    where: str  # the file or library it is in, for the list

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _pdf_cache_path() -> Path:
    from ..home import state_dir

    return state_dir() / "pdf_metadata_cache.json"


def _pdf_meta_cached(paths: list[Path]) -> dict[str, dict[str, Any]]:
    """Title, authors, year and DOI of each PDF, read once and kept by path, size and date.

    Reading a PDF takes a fraction of a second; a literature folder of a few
    hundred would make New study slow to open every time without this.
    """
    from ..modules.literature.local_pdf_meta import extract_pdf_metadata

    cache_file = _pdf_cache_path()
    try:
        cache = json.loads(cache_file.read_text(encoding="utf-8")) if cache_file.is_file() else {}
    except (OSError, ValueError):
        cache = {}
    if not isinstance(cache, dict):
        cache = {}
    out: dict[str, dict[str, Any]] = {}
    changed = False
    for p in paths:
        try:
            st = p.stat()
        except OSError:
            continue
        stamp = f"{st.st_size}:{int(st.st_mtime)}"
        hit = cache.get(str(p))
        if not (isinstance(hit, dict) and hit.get("stamp") == stamp):
            m = extract_pdf_metadata(p)
            hit = {"stamp": stamp, "title": m.title, "authors": m.authors, "year": m.year, "doi": m.doi}
            cache[str(p)] = hit
            changed = True
        out[str(p)] = hit
    if changed:
        try:
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache_file.with_name(f".{cache_file.name}.{os.getpid()}.tmp")
            tmp.write_text(json.dumps(cache), encoding="utf-8")
            os.replace(tmp, cache_file)
        except OSError as e:
            logger.debug("PDF metadata cache not written: %s", e)
    return out


def _bib_files(settings: Any) -> list[Path]:
    """The researcher's .bib files: the configured one, and those in the data and literature folders."""
    from ..modules.local_corpus import BIB_EXTENSIONS, iter_corpus_files, parse_corpus_roots

    paths: list[Path] = []
    if getattr(settings, "literature_bibtex_file", None):
        p = Path(settings.literature_bibtex_file).expanduser()
        if p.is_file():
            paths.append(p)
    roots = parse_corpus_roots(settings.local_data_dir) + parse_corpus_roots(getattr(settings, "literature_dir", None))
    for _root, p in iter_corpus_files(
        roots, BIB_EXTENSIONS, bool(getattr(settings, "local_data_dir_recursive", False))
    ):
        paths.append(p)
    seen: set[Path] = set()
    out = []
    for p in paths:
        r = p.resolve()
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def _literature_roots(settings: Any) -> list[Path]:
    from ..modules.local_corpus import parse_corpus_roots

    return [r.resolve() for r in parse_corpus_roots(settings.resolved_literature_dirs())]


def paper_options(settings: Any, *, library: bool = True, limit: int | None = None) -> list[PaperOption]:
    """Every paper New study can offer: PDFs and Zotero items of the literature folder, .bib entries, the Library."""
    from ..modules.literature.bibtex import parse_bibtex_file
    from ..modules.literature.local_zotero import detect_zotero, read_zotero_sqlite
    from ..modules.local_corpus import PDF_EXTENSIONS, iter_corpus_files

    cap = limit or int(getattr(settings, "literature_max_ingest", 500) or 500)
    out: list[PaperOption] = []
    pdfs: list[Path] = []
    for root in _literature_roots(settings):
        if detect_zotero(root) is not None:
            for m in read_zotero_sqlite(root):
                key = (m.raw or {}).get("zotero_key")
                if key:
                    out.append(PaperOption(f"zotero:{root}#{key}", m.title, m.authors, m.year, "zotero", root.name))
            continue
        for _r, pdf in iter_corpus_files([root], PDF_EXTENSIONS, recursive=True):
            if len(pdfs) < cap:
                pdfs.append(pdf.resolve())
    meta = _pdf_meta_cached(pdfs)
    for pdf in pdfs:
        info = meta.get(str(pdf)) or {}
        out.append(
            PaperOption(
                f"pdf:{pdf}",
                str(info.get("title") or pdf.stem),
                list(info.get("authors") or []),
                info.get("year"),
                "pdf",
                pdf.name,
            )
        )
    for bib in _bib_files(settings):
        for e in parse_bibtex_file(bib):
            if e.title and e.cite_key:
                out.append(PaperOption(f"bib:{bib}#{e.cite_key}", e.title, e.authors, e.year, "bib", bib.name))
    if library:
        out.extend(_library_options())
    return out


def _library_options() -> list[PaperOption]:
    from ..modules.literature import corpus

    path = corpus.corpus_path()
    if not path.is_file():
        return []
    try:
        with corpus.connect(path) as conn:
            rows = corpus.list_papers(conn, limit=5000)
    except Exception as e:  # noqa: BLE001 — a broken Library must not break New study
        logger.warning("New study: the Library could not be read: %s", e)
        return []
    return [PaperOption(f"library:{r.key}", r.title, r.authors, r.year, "library", "Library") for r in rows if r.title]


# ── files added on New study ────────────────────────────────────────────────


def uploads_root() -> Path:
    from ..home import state_dir

    return state_dir() / UPLOADS_FOLDER


def new_upload_folder() -> Path:
    folder = uploads_root() / uuid.uuid4().hex
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def is_upload(path: Path) -> bool:
    try:
        Path(path).resolve().relative_to(uploads_root().resolve())
        return True
    except ValueError:
        return False


# ── checking a choice before the study starts ───────────────────────────────


def check_data_files(paths: list[str]) -> list[Path]:
    """The chosen data files as absolute paths; a missing or unreadable one is refused in one sentence."""
    from ..modules.local_corpus import not_a_data_file

    out: list[Path] = []
    for raw in paths:
        p = Path(str(raw)).expanduser()
        if not p.is_absolute():
            raise InputError(f"{raw} is not a full path to a file. Give the whole path, for instance ~/data/{p.name}.")
        if why := not_a_data_file(p.name):
            raise InputError(why)
        if not p.is_file():
            raise InputError(f"{p} does not exist (or is not a file).")
        out.append(p.resolve())
    return list(dict.fromkeys(out))


def paper_id_for_path(raw: str) -> str:
    """``e2er run --papers`` names files; New study sends ids. A file path becomes its id."""
    if raw.split(":", 1)[0] in {"pdf", "bib", "bibfile", "zotero", "library"} and ":" in raw:
        return raw
    p = Path(raw).expanduser()
    if p.suffix.lower() == ".pdf":
        return f"pdf:{p.resolve()}"
    if p.suffix.lower() == ".bib":
        return f"bibfile:{p.resolve()}"
    raise InputError(f"{p.name} is not a paper e2er can read. Use a .pdf or a .bib file.")


def check_paper_ids(ids: list[str]) -> list[str]:
    """The chosen papers; a file that is missing, or an id e2er does not know, is refused in one sentence."""
    out: list[str] = []
    for raw in ids:
        pid = paper_id_for_path(str(raw).strip())
        kind, _, rest = pid.partition(":")
        if kind in {"pdf", "bibfile"}:
            p = Path(rest)
            if not p.is_absolute():
                raise InputError(f"{rest} is not a full path to a file.")
            want = ".pdf" if kind == "pdf" else ".bib"
            if p.suffix.lower() != want:
                raise InputError(f"{p.name} is not a {want} file.")
            if not p.is_file():
                raise InputError(f"{p} does not exist (or is not a file).")
        elif kind in {"bib", "zotero"}:
            where = rest.rsplit("#", 1)[0]
            if "#" not in rest or not Path(where).exists():
                raise InputError(f"{where} does not exist any more. Open New study again to see what is there.")
        elif kind == "library":
            if not rest:
                raise InputError("A Library paper was chosen without its name.")
        out.append(pid)
    return list(dict.fromkeys(out))


# ── staging and the record ──────────────────────────────────────────────────


def read_record(workspace: Path) -> dict[str, Any]:
    try:
        data = json.loads((Path(workspace) / INPUTS_FILE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def section(record: dict[str, Any], name: str) -> dict[str, Any]:
    """One part of the record ("data" or "papers"), {} when absent."""
    value = record.get(name)
    return value if isinstance(value, dict) else {}


def write_record(workspace: Path, record: dict[str, Any]) -> None:
    path = Path(workspace) / INPUTS_FILE
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _data_name(path: Path, settings: Any) -> str:
    """The file's name inside the study: its path inside the data folder (with subfolders), else its name."""
    from ..modules.local_corpus import parse_corpus_roots

    if getattr(settings, "local_data_dir_recursive", False):
        for root in parse_corpus_roots(settings.local_data_dir):
            try:
                return path.relative_to(root.resolve()).as_posix()
            except ValueError:
                continue
    return path.name


def _in_data_folder(path: Path, settings: Any) -> bool:
    from ..modules.local_corpus import parse_corpus_roots

    for root in parse_corpus_roots(settings.local_data_dir):
        try:
            path.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


def stage_chosen_data(workspace: Path, chosen: list[Path], settings: Any) -> list[dict[str, Any]]:
    """Put exactly the chosen data files into the study's ``data/`` folder; returns what the record says of them.

    A file from the data folder is linked (copied where links are not allowed);
    a file added on New study is copied, because its upload folder is removed
    once the study has started.
    """
    from ..modules.local_corpus import link_or_copy

    dest = Path(workspace) / "data"
    dest.mkdir(parents=True, exist_ok=True)
    files: list[dict[str, Any]] = []
    for src in chosen:
        name = _data_name(src, settings)
        target = dest / name
        n = 2
        while target.exists() or target.is_symlink():
            target = target.with_name(f"{Path(name).stem}_{n}{Path(name).suffix}")
            n += 1
        target.parent.mkdir(parents=True, exist_ok=True)
        upload = is_upload(src)
        if upload:
            shutil.copy2(src, target)
        else:
            link_or_copy(src, target)
        files.append(
            {
                "name": target.relative_to(dest).as_posix(),
                "origin": "upload" if upload else ("folder" if _in_data_folder(src, settings) else "file"),
                "size": src.stat().st_size,
            }
        )
    return files


def staged_data_files(workspace: Path) -> list[dict[str, Any]]:
    """The data files in the study's ``data/`` folder (when no choice was made: what the folder gave it)."""
    from ..modules.local_corpus import DATA_EXTENSIONS

    data = Path(workspace) / "data"
    if not data.is_dir():
        return []
    out = []
    for p in sorted(data.rglob("*")):
        rel = p.relative_to(data)
        if p.is_file() and p.suffix.lower() in DATA_EXTENSIONS and not any(x.startswith(".") for x in rel.parts):
            out.append({"name": rel.as_posix(), "origin": "folder", "size": p.stat().st_size})
    return out


def copy_uploaded_papers(workspace: Path, ids: list[str]) -> list[str]:
    """Copy the PDFs and .bib files added on New study into the study; their ids then name the copies."""
    lit = Path(workspace) / "literature"
    out: list[str] = []
    for pid in ids:
        kind, _, rest = pid.partition(":")
        if kind in {"pdf", "bibfile"} and is_upload(Path(rest)):
            lit.mkdir(parents=True, exist_ok=True)
            src = Path(rest)
            target = lit / src.name
            n = 2
            while target.exists():
                target = lit / f"{src.stem}_{n}{src.suffix}"
                n += 1
            shutil.copy2(src, target)
            out.append(f"{kind}:{target.resolve()}")
        else:
            out.append(pid)
    return out


def origin_of_id(pid: str, workspace: Path | None = None) -> str:
    """``upload`` (added for this study), ``library``, or ``folder`` (the researcher's literature folder or a file)."""
    kind, _, rest = pid.partition(":")
    if kind == "library":
        return "library"
    if workspace is not None and kind in {"pdf", "bibfile"}:
        try:
            Path(rest).relative_to((Path(workspace) / "literature").resolve())
            return "upload"
        except ValueError:
            pass
    return "folder"


# ── resolving the chosen papers ─────────────────────────────────────────────


@dataclass
class ResolvedPapers:
    items: list[Any] = field(default_factory=list)  # PaperMetadata
    origins: dict[str, str] = field(default_factory=dict)  # bibtex key -> folder | upload | library
    kinds: dict[str, str] = field(default_factory=dict)  # bibtex key -> pdf | bib | zotero | library
    missing: list[str] = field(default_factory=list)  # ids that no longer resolve


def resolve_papers(ids: list[str], workspace: Path) -> ResolvedPapers:
    """The chosen papers as metadata (PDFs and Zotero items with their file, .bib entries with their own key)."""
    from ..modules.literature.bibtex import parse_bibtex_file
    from ..modules.literature.local_pdf_meta import extract_pdf_metadata
    from ..modules.literature.local_zotero import read_zotero_sqlite

    out = ResolvedPapers()
    bib_cache: dict[str, list[Any]] = {}
    zot_cache: dict[str, list[Any]] = {}
    library_keys: list[str] = []
    pending: list[tuple[str, Any]] = []
    for pid in ids:
        kind, _, rest = pid.partition(":")
        if kind == "pdf":
            p = Path(rest)
            if not p.is_file():
                out.missing.append(pid)
                continue
            m = extract_pdf_metadata(p)
            m.raw = {**(m.raw or {}), "source_pdf": str(p)}
            pending.append((pid, m))
        elif kind in {"bib", "bibfile"}:
            path, _, key = rest.rpartition("#") if kind == "bib" else (rest, "", "")
            if path not in bib_cache:
                bib_cache[path] = parse_bibtex_file(Path(path)) if Path(path).is_file() else []
            entries = [e for e in bib_cache[path] if kind == "bibfile" or e.cite_key == key]
            if not entries:
                out.missing.append(pid)
            pending.extend((pid, e) for e in entries if e.title)
        elif kind == "zotero":
            root, _, key = rest.rpartition("#")
            if root not in zot_cache:
                zot_cache[root] = read_zotero_sqlite(Path(root))
            hits = [m for m in zot_cache[root] if (m.raw or {}).get("zotero_key") == key]
            if not hits:
                out.missing.append(pid)
            pending.extend((pid, m) for m in hits)
        elif kind == "library":
            library_keys.append(rest)
    if library_keys:
        from ..modules.literature import corpus
        from ..modules.literature.models import PaperMetadata

        try:
            with corpus.connect(corpus.corpus_path()) as conn:
                rows = corpus.get_papers(conn, library_keys)
        except Exception as e:  # noqa: BLE001
            logger.warning("the Library could not be read for the chosen papers: %s", e)
            rows = {}
        for key in library_keys:
            row = rows.get(key)
            if row is None:
                out.missing.append(f"library:{key}")
                continue
            m = PaperMetadata(
                title=row.title,
                authors=list(row.authors),
                year=row.year,
                doi=row.doi,
                source="library",
                raw={"library_key": key, "e2er_origin": "researcher"},
            )
            pending.append((f"library:{key}", m))
    for pid, m in pending:
        m.raw = {**(m.raw or {}), "e2er_origin": "researcher", "e2er_id": pid}
        out.items.append(m)
    return out


def unique_keys(items: list[Any], taken: set[str] | None = None) -> None:
    """Give two different papers that derive the same key (smith2020market twice) their own: …b, …c."""
    seen: set[str] = set(taken or ())
    for m in items:
        key = m.bibtex_key
        if key not in seen:
            seen.add(key)
            continue
        for suffix in "bcdefghijklmnopqrstuvwxyz":
            if key + suffix not in seen:
                m.cite_key = key + suffix
                seen.add(m.cite_key)
                break


def dedupe(items: list[Any]) -> list[Any]:
    """One entry per paper: by DOI, else by title and year (the same paper as a PDF and in the .bib).

    The first one is kept, with the other's PDF when it has none: a .bib entry
    keeps the researcher's key and gains the PDF of the same paper.
    """
    out: list[Any] = []
    by_mark: dict[str, Any] = {}
    for m in items:
        marks = {f"doi:{m.doi.lower().strip()}"} if m.doi else set()
        marks.add(f"t:{' '.join(m.title.lower().split())}|{m.year or ''}")
        kept = next((by_mark[k] for k in marks if k in by_mark), None)
        if kept is not None:
            pdf = (m.raw or {}).get("source_pdf")
            if pdf and not (kept.raw or {}).get("source_pdf"):
                kept.raw = {**(kept.raw or {}), "source_pdf": pdf}
            for k in marks:
                by_mark.setdefault(k, kept)
            continue
        for k in marks:
            by_mark[k] = m
        out.append(m)
    return out


def everything_offered(settings: Any) -> list[Any]:
    """With no choice made: every paper the researcher's folders and libraries hold, as before 0.15.0.

    The literature folder (PDFs or a Zotero folder), the .bib files and the
    Zotero web library. Before 0.15.0 the last two were shown to the writers as
    citable and never written into the study's bibliography; now they are.
    """
    from ..modules.literature.discovery import discover_corpus
    from ..modules.literature.registry import reference_libraries

    items: list[Any] = []
    try:
        items.extend(discover_corpus(_literature_roots(settings), int(settings.literature_max_ingest or 500)))
    except Exception as e:  # noqa: BLE001 — best-effort, as the ingest always was
        logger.warning("the literature folder could not be read: %s", e)
    for library in reference_libraries(settings):
        try:
            items.extend(library.entries())
        except Exception as e:  # noqa: BLE001
            logger.warning("%s could not be read: %s", getattr(library, "name", library), e)
    for m in items:
        m.raw = {**(m.raw or {}), "e2er_origin": "researcher"}
    return items


def _kind_of(m: Any) -> str:
    pid = str((m.raw or {}).get("e2er_id") or "")
    if pid:
        kind = pid.partition(":")[0]
        return "bib" if kind == "bibfile" else kind
    return {"bibtex": "bib", "byod_pdf": "pdf", "zotero_local": "zotero", "zotero": "zotero"}.get(m.source, "library")


async def prepare_papers(workspace: Path, paper_id: str, settings: Any, queries: list[str]) -> int:
    """Write the study's papers into its ``literature.bib`` before any specialist runs; then the web search.

    The chosen papers (or, without a choice, every paper of the researcher's
    folders and libraries) are staged (their PDFs into ``literature/``),
    completed from CrossRef/OpenAlex where a PDF says little about itself,
    stored for ``search_papers`` and written into ``literature.bib`` with the
    keys the writers are shown, tagged ``e2er_source = {researcher}``. The web
    search runs in addition unless the researcher ticked "Use only my papers";
    its entries are tagged ``web``. Returns the number of the researcher's papers.
    Never raises.
    """
    from ..modules.literature.discovery import _enrich_one, _write_literature_bib, acquire_literature, stage_pdf
    from ..modules.literature.storage import store_paper

    workspace = Path(workspace)
    record = read_record(workspace)
    papers = section(record, "papers")
    chosen = bool(papers.get("chosen"))
    web_search = papers.get("web_search", True) is not False
    try:
        if chosen:
            resolved = resolve_papers(list(papers.get("requested") or []), workspace)
            items, missing = resolved.items, resolved.missing
        else:
            items, missing = everything_offered(settings), []
        for item in items:
            stage_pdf(workspace, item)
        thin = [i for i in items if i.source == "byod_pdf" or (i.raw or {}).get("source_pdf")]
        for item in thin:
            await _enrich_one(item)
        items = dedupe(items)
        unique_keys(items)
        for item in items:
            try:
                await store_paper(item, paper_id)
            except Exception as e:  # noqa: BLE001 — the bibliography matters more than the store
                logger.debug("store_paper failed for %r: %s", item.title[:60], e)
        _write_literature_bib(workspace, items)
        papers = {
            **papers,
            "chosen": chosen,
            "web_search": web_search,
            "items": [
                {
                    "key": i.bibtex_key,
                    "title": i.title,
                    "authors": list(i.authors[:6]),
                    "year": i.year,
                    "kind": _kind_of(i),
                    "origin": origin_of_id(str((i.raw or {}).get("e2er_id") or ""), workspace),
                    **({"pdf": i.pdf_path} if i.pdf_path else {}),
                }
                for i in items
            ],
            **({"missing": missing} if missing else {}),
        }
        write_record(workspace, {**record, "papers": papers})
        if items:
            logger.info("study %s: %d of the researcher's papers in literature.bib", paper_id, len(items))
    except Exception as e:  # noqa: BLE001 — a study without its papers is worse, a crashed start worst
        logger.warning("the researcher's papers could not be prepared for %s: %s", paper_id, e)
        items = []
    await acquire_literature(
        workspace,
        paper_id,
        queries,
        settings,
        limit=settings.literature_acquire_limit,
        web_search=web_search,
        chosen=items if chosen else None,
    )
    return len(items)
