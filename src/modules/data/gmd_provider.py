"""Global Macro Database (GMD) provider: annual macro panels from versioned releases.

The GMD (Müller, Xu, Lehbib and Chen 2025, https://www.globalmacrodata.com)
publishes one file per quarterly release. This provider reads the release
files over HTTPS with httpx, the same files the official ``global_macro_data``
package reads:

- ``helpers/versions.csv``: the releases (``versions`` column, e.g. ``2026_09``)
- ``helpers/varlist.csv``: variable code, units and definition
- ``helpers/countrylist.dta``: ISO3 code and country name
- ``distribute/GMD_<version>.csv``: the panel of one release (ISO3, year, …)

Each file is tried on the GMD's S3 bucket first and on the GitHub repository
second (the release panels are on S3 only). A release panel is cached under
``~/.e2er/cache/gmd/<version>/`` and its SHA-256 is recomputed on every use,
so each load records the version, the URL and the hash of the exact file read.

Years after the last observed year hold the GMD's forecasts in the same
columns; each ``forecast_<variable>`` column (1 = forecast) is loaded next to
its variable so forecasts are never mistaken for observations.

Terms: free for academic use (research meant for publication, teaching and
theses at universities and academic research institutes); everyone else needs
written permission. The connector records the terms in the data dictionary
entry and adds the GMD citation to the study's bibliography.

Every method returns the ``{source, items, error, ...}`` envelope and never
raises into specialist code.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from ...logging_config import get_logger

logger = get_logger(__name__)

SOURCE = "gmd"
DATASET = "Global Macro Database"
BASES = (
    "https://gmd-releases.s3.ap-southeast-2.amazonaws.com/data",
    "https://raw.githubusercontent.com/KMueller-Lab/Global-Macro-Database/refs/heads/main/data",
)
#: Release panels are published on S3 only.
PANEL_BASES = BASES[:1]
ID_COLUMNS = ("ISO3", "countryname", "id", "year")
WEBSITE = "https://www.globalmacrodata.com"
TERMS_URL = "https://www.globalmacrodata.com/license.html"
LICENCE = (
    "GMD Research Use Terms (version 1.1, https://www.globalmacrodata.com/license.html): free for academic "
    "use, meaning research meant for publication, teaching and theses by students, faculty and researchers "
    "at universities and academic research institutes. Everyone else, including companies, needs written "
    "permission (commercial users: Anansi Data Analytics). Cite the GMD. Do not re-host or redistribute "
    "the data; a paper's replication package may include the data it used, labelled as coming from the "
    "GMD, with a pointer to https://www.globalmacrodata.com."
)
#: The terms in plain words, one line each (shown before the researcher confirms, and on a study page).
TERMS_PLAIN = (
    "Free for academic use: research meant for publication, teaching and theses at universities "
    "and academic research institutes. Everyone else needs written permission.",
    "A study's replication package may include the GMD data it used, labelled as GMD data.",
    "The data may not be republished anywhere else.",
)
TERMS_SUMMARY = " ".join(TERMS_PLAIN)
CITE_KEY = "GMD2025"
CITATION = (
    "Müller, K., Xu, C., Lehbib, M., & Chen, Z. (2025). The Global Macro Database: A New International "
    "Macroeconomic Dataset (NBER Working Paper No. 33714)."
)
#: Verbatim from https://www.globalmacrodata.com/research-paper.html#citation-section
BIBTEX = """@techreport{GMD2025,
  title       = {The Global Macro Database: A New International Macroeconomic Dataset},
  author      = {M{\\"u}ller, Karsten and Xu, Chenzi and Lehbib, Mohamed and Chen, Ziliang},
  institution = {National Bureau of Economic Research},
  type        = {Working Paper},
  series      = {Working Paper Series},
  number      = {33714},
  year        = {2025},
  month       = {April},
  doi         = {10.3386/w33714},
  URL         = {http://www.nber.org/papers/w33714}
}"""

_TIMEOUT = httpx.Timeout(30.0, read=300.0)
_VERSION_RE = re.compile(r"^(\d{4})_(\d{2})$")
_ISO3_RE = re.compile(r"^[A-Z]{3}$")


def default_cache_dir() -> Path:
    """``$E2ER_CACHE_DIR/gmd`` when set, else ``~/.e2er/cache/gmd``."""
    root = os.environ.get("E2ER_CACHE_DIR")
    return (Path(root) if root else Path.home() / ".e2er" / "cache") / "gmd"


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _envelope(items: list[Any] | None = None, error: str | None = None, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"source": SOURCE, "items": items or [], "error": error}
    out.update(extra)
    return out


def _sort_versions(versions: list[str]) -> list[str]:
    """Release names, newest first (``2026_09`` before ``2026_06``); malformed names are dropped."""
    ok = [v for v in versions if _VERSION_RE.match(v)]
    return sorted(set(ok), key=lambda v: (int(v[:4]), int(v[5:])), reverse=True)


def _clean(value: Any) -> Any:
    """A pandas cell as JSON: NaN → None, numpy scalars → Python numbers."""
    if value is None:
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


class GMDError(RuntimeError):
    """A GMD request that cannot be served; the message says why."""


class GMDProvider:
    """Reads GMD release files over HTTPS; caches release panels by version."""

    def __init__(self, cache_dir: Path | None = None, bases: tuple[str, ...] = BASES) -> None:
        self._cache = Path(cache_dir) if cache_dir is not None else default_cache_dir()
        self._bases = tuple(b.rstrip("/") for b in bases)

    # ── HTTP ─────────────────────────────────────────────────────────────────

    async def _get(self, rel: str, bases: tuple[str, ...] | None = None) -> tuple[bytes, str]:
        """The bytes of ``rel`` and the URL that served them; GMDError lists every URL tried."""
        errors: list[str] = []
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            for base in bases or self._bases:
                url = f"{base}/{rel}"
                try:
                    resp = await client.get(url)
                except httpx.HTTPError as e:
                    errors.append(f"{url}: {type(e).__name__}: {e}")
                    continue
                if resp.status_code == 200:
                    return resp.content, url
                errors.append(f"{url}: HTTP {resp.status_code}")
        raise GMDError(f"could not download {rel}: " + "; ".join(errors))

    async def _download_to(self, rel: str, target: Path, bases: tuple[str, ...]) -> str:
        """Stream ``rel`` into ``target`` (atomically); returns the URL that served it."""
        errors: list[str] = []
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".part")
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            for base in bases:
                url = f"{base}/{rel}"
                try:
                    async with client.stream("GET", url) as resp:
                        if resp.status_code != 200:
                            errors.append(f"{url}: HTTP {resp.status_code}")
                            continue
                        with tmp.open("wb") as f:
                            async for chunk in resp.aiter_bytes():
                                f.write(chunk)
                except httpx.HTTPError as e:
                    tmp.unlink(missing_ok=True)
                    errors.append(f"{url}: {type(e).__name__}: {e}")
                    continue
                tmp.replace(target)
                return url
        tmp.unlink(missing_ok=True)
        raise GMDError(f"could not download {rel}: " + "; ".join(errors))

    # ── helper files ─────────────────────────────────────────────────────────

    async def _versions(self) -> tuple[list[str], dict[str, Any]]:
        """Releases newest first, and the record of the versions.csv that listed them."""
        import pandas as pd

        content, url = await self._get("helpers/versions.csv")
        df = pd.read_csv(io.BytesIO(content), dtype=str)
        if "versions" not in df.columns:
            raise GMDError(f"{url} has no 'versions' column")
        versions = _sort_versions([str(v).strip() for v in df["versions"].dropna()])
        if not versions:
            raise GMDError(f"{url} lists no releases")
        return versions, {"url": url, "sha256": hashlib.sha256(content).hexdigest(), "retrieved_at": _now()}

    async def versions(self) -> dict[str, Any]:
        """The GMD releases, newest first; ``latest`` is the default for ``series``."""
        try:
            versions, rec = await self._versions()
        except (GMDError, ValueError) as e:
            return _envelope(error=str(e))
        return _envelope(
            items=[{"version": v} for v in versions],
            latest=versions[0],
            row_count=len(versions),
            source_file=rec,
        )

    async def variables(self) -> dict[str, Any]:
        """Variable codes with units and definitions (``helpers/varlist.csv``)."""
        import pandas as pd

        try:
            content, url = await self._get("helpers/varlist.csv")
            df = pd.read_csv(io.BytesIO(content), dtype=str)
        except (GMDError, ValueError) as e:
            return _envelope(error=str(e))
        col = "variables" if "variables" in df.columns else "variable"
        if col not in df.columns:
            return _envelope(error=f"{url} has no 'variables' column")
        items = [
            {
                "variable": str(r[col]).strip(),
                "units": _clean(r.get("units")),
                "definition": _clean(r.get("definition")),
            }
            for _, r in df.iterrows()
            if isinstance(r[col], str) and r[col].strip()
        ]
        return _envelope(
            items=items,
            row_count=len(items),
            source_file={"url": url, "sha256": hashlib.sha256(content).hexdigest()},
            note="Each variable also has a forecast_<variable> column (1 = forecast year); series loads it.",
        )

    async def countries(self) -> dict[str, Any]:
        """ISO3 codes and country names (``helpers/countrylist.dta``)."""
        import pandas as pd

        try:
            content, url = await self._get("helpers/countrylist.dta")
            df = pd.read_stata(io.BytesIO(content), convert_categoricals=False)
        except (GMDError, ValueError) as e:
            return _envelope(error=str(e))
        if not {"ISO3", "countryname"}.issubset(df.columns):
            return _envelope(error=f"{url} has no ISO3/countryname columns")
        items = [
            {"ISO3": str(r["ISO3"]), "countryname": str(r["countryname"])} for _, r in df.sort_values("ISO3").iterrows()
        ]
        return _envelope(
            items=items,
            row_count=len(items),
            source_file={"url": url, "sha256": hashlib.sha256(content).hexdigest()},
        )

    # ── release panel ────────────────────────────────────────────────────────

    async def _panel(self, version: str) -> tuple[Path, dict[str, Any]]:
        """The release panel file (cached by version) and its record: URL, SHA-256, bytes, retrieval."""
        rel = f"distribute/GMD_{version}.csv"
        target = self._cache / version / f"GMD_{version}.csv"
        meta_path = target.with_name(target.name + ".json")
        meta: dict[str, Any] = {}
        if target.is_file() and meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                meta = {}
        if target.is_file() and meta.get("url") and meta.get("sha256"):
            sha = _sha256_file(target)
            if sha == meta["sha256"]:
                return target, {**meta, "from_cache": True}
            logger.warning("GMD cache %s does not match its recorded hash; downloading again", target)
        url = await self._download_to(rel, target, PANEL_BASES)
        meta = {
            "url": url,
            "sha256": _sha256_file(target),
            "bytes": target.stat().st_size,
            "retrieved_at": _now(),
        }
        meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        return target, {**meta, "from_cache": False}

    async def series(
        self,
        variables: list[str],
        countries: list[str] | None = None,
        start: int | None = None,
        end: int | None = None,
        version: str | None = None,
    ) -> dict[str, Any]:
        """A country-year panel of ``variables`` from one release.

        Rows: ``ISO3, countryname, year``, each variable and its
        ``forecast_<variable>`` flag. Country-years where every requested
        variable is empty are dropped. Unknown variables, unknown countries,
        an unknown release and a failed download return an ``error`` that
        names the valid choices.
        """
        import pandas as pd

        variables = list(dict.fromkeys(v.strip() for v in variables if v and v.strip()))
        countries = list(dict.fromkeys(c.strip().upper() for c in (countries or []) if c and c.strip()))
        if not variables:
            return _envelope(error="name at least one variable (--variables rGDP,infl); list them with `variables`")
        if start is not None and end is not None and start > end:
            return _envelope(error=f"--start {start} is after --end {end}")

        # 1. The release: the one asked for, else the latest in versions.csv.
        versions_file: dict[str, Any] | None = None
        try:
            versions, versions_file = await self._versions()
        except (GMDError, ValueError) as e:
            cached = version and (self._cache / version / f"GMD_{version}.csv").is_file()
            if not cached:
                return _envelope(error=f"could not read the list of GMD releases: {e}")
            versions = [version] if version else []
            versions_file = None
        if version:
            if version not in versions:
                return _envelope(
                    error=f"GMD release {version!r} does not exist; releases: {', '.join(versions)}",
                    version=version,
                )
            chosen, how = version, "requested"
        else:
            chosen, how = versions[0], "latest release in helpers/versions.csv"

        # 2. The panel file of that release.
        try:
            path, panel = await self._panel(chosen)
        except (GMDError, OSError) as e:
            return _envelope(error=str(e), version=chosen)

        # 3. Validate against the release's own columns and countries.
        try:
            header = list(pd.read_csv(path, nrows=0).columns)
        except (OSError, ValueError) as e:
            return _envelope(error=f"cannot read {path.name}: {e}", version=chosen)
        valid_vars = [c for c in header if c not in ID_COLUMNS and not c.startswith("forecast_")]
        unknown = [v for v in variables if v not in valid_vars]
        if unknown:
            return _envelope(
                error=(
                    f"unknown GMD variable(s) {', '.join(unknown)} in release {chosen}; "
                    f"valid variables: {', '.join(valid_vars)}"
                ),
                version=chosen,
            )
        flags = [f"forecast_{v}" for v in variables if f"forecast_{v}" in header]
        usecols = ["ISO3", "countryname", "year", *variables, *flags]
        try:
            df = pd.read_csv(path, usecols=usecols, low_memory=False)
        except (OSError, ValueError) as e:
            return _envelope(error=f"cannot read {path.name}: {e}", version=chosen)
        valid_iso = sorted({str(c) for c in df["ISO3"].dropna().unique()})
        if countries:
            bad = [c for c in countries if c not in valid_iso or not _ISO3_RE.match(c)]
            if bad:
                return _envelope(
                    error=(
                        f"unknown ISO3 code(s) {', '.join(bad)} in GMD release {chosen}; "
                        f"valid codes: {', '.join(valid_iso)}"
                    ),
                    version=chosen,
                )
            df = df[df["ISO3"].isin(countries)]
        if start is not None:
            df = df[df["year"] >= start]
        if end is not None:
            df = df[df["year"] <= end]
        df = df[df[variables].notna().any(axis=1)].sort_values(["ISO3", "year"])
        df = df[usecols]

        items = [{k: _clean(v) for k, v in row.items()} for row in df.to_dict(orient="records")]
        for row in items:
            if row.get("year") is not None:
                row["year"] = int(row["year"])
            for fl in flags:
                if row.get(fl) is not None:
                    row[fl] = int(row[fl])
        record: dict[str, Any] = {
            "connector": SOURCE,
            "dataset": DATASET,
            "version": chosen,
            "version_chosen": how,
            "files": [{k: panel[k] for k in ("url", "sha256", "bytes", "retrieved_at", "from_cache") if k in panel}],
            "variables": variables,
            "countries": countries or "all",
            "start": start,
            "end": end,
            "rows": len(items),
            "licence": LICENCE,
            "terms_summary": TERMS_SUMMARY,
            "terms": TERMS_URL,
            "citation": CITATION,
            "citation_by": "source",
            "cite_key": CITE_KEY,
            "series": ",".join(variables),
        }
        if versions_file is not None:
            record["versions_file"] = versions_file
        out = _envelope(items=items, version=chosen, row_count=len(items), gmd_record=record)
        if not items:
            out["error"] = (
                f"GMD release {chosen} has no values of {', '.join(variables)} for "
                f"{', '.join(countries) if countries else 'any country'} in the years asked for"
            )
        if flags:
            out["note"] = "forecast_<variable> = 1 marks a GMD forecast year, not an observation."
        return out


# ── study records: provenance, data dictionary, citation ─────────────────────

# The record of every load is shared by all connectors (load_record.py); kept here for callers.
from .load_record import DATA_SOURCES_FILE as DATA_SOURCES_FILE  # noqa: E402
from .load_record import record_load as record_load  # noqa: E402


def record_in_dictionary(workspace: Path, table: str, record: dict[str, Any]) -> Path:
    """Update (or add) the ``tables`` entry of ``table`` in ``data_dictionary.json``.

    Sets ``source``/``series``, the release ``version``, the source files with
    their SHA-256, the licence and the citation. Other keys the data architect
    wrote (role, columns, min_non_null, …) are kept.
    """
    path = Path(workspace) / "data_dictionary.json"
    doc: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                doc = loaded
        except (OSError, ValueError):
            raise GMDError(f"{path.name} is not valid JSON; the load was not recorded in it") from None
    found = doc.get("tables")
    tables: list[Any] = found if isinstance(found, list) else []
    entry: dict[str, Any] = next((t for t in tables if isinstance(t, dict) and t.get("name") == table), {})
    if not entry:
        entry = {"name": table}
        tables.append(entry)
    entry.update(
        {
            "source": SOURCE,
            "series": ",".join(record["variables"]),
            "frequency": entry.get("frequency") or "annual",
            "version": record["version"],
            "source_files": [{"url": f["url"], "sha256": f["sha256"]} for f in record["files"]],
            "licence": LICENCE,
            "citation": CITATION,
            "cite_key": CITE_KEY,
            "provenance": f"{DATASET} ({WEBSITE}), release {record['version']}",
        }
    )
    doc["tables"] = tables
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def add_citation(workspace: Path) -> bool:
    """Add the GMD BibTeX entry to the study's ``literature.bib`` (exported as ``paper/refs.bib``).

    Returns True when the entry was added, False when the key was already there.
    """
    path = Path(workspace) / "literature.bib"
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    if re.search(r"@\w+\s*\{\s*" + re.escape(CITE_KEY) + r"\s*,", text):
        return False
    head = text.rstrip("\n") + "\n\n" if text.strip() else ""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(head + BIBTEX + "\n", encoding="utf-8")
    return True
