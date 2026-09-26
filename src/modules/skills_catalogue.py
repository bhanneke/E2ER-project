"""Read the RISE catalogue of skill packs, and install one.

RISE (github.com/bhanneke/RISE) indexes skill packs published by other research
projects — each with its own source repository, licence and maintainers. It is a
catalogue, not a library, and that distinction decides the design here: E2ER
*installs* packs from their source, it does not vendor them.

Copying them in would mean republishing, under E2ER's MIT licence and on PyPI,
work that is variously CC BY-NC, unlicensed, or private to its curator. Roughly
half of the catalogue's 358 skills fall into one of those. Installing on the
user's own machine raises none of those questions, keeps attribution with the
authors, and leaves RISE doing the job it was built for.

Installed packs land in ``~/.e2er/skills/<pack>/`` alongside a ``pack.json``
recording where each file came from and under what licence, so an installed tree
can always answer "whose is this?".
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..logging_config import get_logger

logger = get_logger(__name__)

#: Raw file host for GitHub blob URLs. The catalogue records human-facing
#: `blob` links; fetching needs the raw equivalent.
_GITHUB_BLOB = "https://github.com/"
_GITHUB_RAW = "https://raw.githubusercontent.com/"


class CatalogueError(RuntimeError):
    """The catalogue could not be read, or a pack could not be installed."""


@dataclass
class CatalogueSkill:
    slug: str
    name: str = ""
    description: str = ""
    category: str = ""
    field_: str = ""
    source_path: str = ""
    details_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SkillPack:
    slug: str
    name: str = ""
    source_url: str = ""
    license: str = ""
    maintainers: tuple[str, ...] = ()
    compatibility: tuple[str, ...] = ()
    notes: str = ""
    skills: list[CatalogueSkill] = field(default_factory=list)

    @property
    def redistributable(self) -> bool:
        """Whether E2ER could ship this pack, as opposed to installing it.

        Not used to block anything — installing a public file on your own
        machine is not redistribution. It exists so `skills list` can show which
        packs are safe to bundle, which is the question that made this an
        installer rather than a copy.
        """
        lic = (self.license or "").lower()
        return any(k in lic for k in ("mit", "apache", "bsd", "cc0", "cc by 4", "public domain")) and "nc" not in lic

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "name": self.name,
            "source_url": self.source_url,
            "license": self.license,
            "maintainers": list(self.maintainers),
            "compatibility": list(self.compatibility),
            "skills": [s.to_dict() for s in self.skills],
        }


# ── reading the catalogue ────────────────────────────────────────────────────


def catalogue_path(explicit: str | Path | None = None) -> Path:
    """Where the RISE checkout lives."""
    if explicit:
        return Path(explicit).expanduser()

    try:
        from ..config import get_settings

        configured = get_settings().rise_path
    except Exception:
        configured = None

    if configured:
        return Path(configured).expanduser()
    return Path.home() / "Documents" / "Projects" / "RISE"


def _pack_from(raw: dict[str, Any], slug: str) -> SkillPack:
    meta = raw.get("pack") or {}
    skills = []
    for entry in raw.get("skills") or []:
        if not isinstance(entry, dict):
            continue
        skills.append(
            CatalogueSkill(
                slug=str(entry.get("slug", "")),
                name=str(entry.get("name", "")),
                description=str(entry.get("description", "")),
                category=str(entry.get("category", "")),
                field_=str(entry.get("field", "")),
                source_path=str(entry.get("source_path", "")),
                details_url=str(entry.get("details_url", "")),
            )
        )
    return SkillPack(
        slug=str(meta.get("slug", slug)),
        name=str(meta.get("name", slug)),
        source_url=str(meta.get("source_url", "")),
        license=str(meta.get("license", "")),
        maintainers=tuple(meta.get("maintainers") or ()),
        compatibility=tuple(meta.get("compatibility") or ()),
        notes=str(meta.get("notes", "")),
        skills=skills,
    )


def read_catalogue(path: str | Path | None = None) -> list[SkillPack]:
    """Every pack in the catalogue, sorted by slug. Never raises on one bad file."""
    import yaml

    root = catalogue_path(path)
    skills_dir = root / "skills"
    if not skills_dir.is_dir():
        raise CatalogueError(
            f"no RISE catalogue at {root}. Clone github.com/bhanneke/RISE and set RISE_PATH, or pass --catalogue."
        )

    packs: list[SkillPack] = []
    for manifest in sorted(skills_dir.glob("*.yml")):
        try:
            raw = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
        except Exception as e:  # noqa: BLE001 — one malformed pack must not hide the rest
            logger.warning("skipping unreadable pack %s: %s", manifest.name, e)
            continue
        if isinstance(raw, dict) and raw.get("pack"):
            packs.append(_pack_from(raw, manifest.stem))
    return packs


def find_pack(slug: str, path: str | Path | None = None) -> SkillPack:
    for pack in read_catalogue(path):
        if pack.slug == slug:
            return pack
    raise CatalogueError(f"no pack named {slug!r} in the catalogue. `e2er skills list` shows what there is.")


# ── installing ───────────────────────────────────────────────────────────────


def install_root() -> Path:
    """Where installed packs live. Searched by the skill loader."""
    return Path.home() / ".e2er" / "skills"


def _raw_url(details_url: str) -> str:
    """Turn a GitHub blob link into a fetchable raw link."""
    if details_url.startswith(_GITHUB_BLOB) and "/blob/" in details_url:
        return details_url.replace(_GITHUB_BLOB, _GITHUB_RAW, 1).replace("/blob/", "/", 1)
    return details_url


def _candidate_urls(details_url: str) -> list[str]:
    """The raw URL, then the same path on the other default branch.

    The catalogue records `/blob/main/` for every pack, and not every
    repository uses `main` — theorist-toolbox is on `master`, so all eleven of
    its skills 404'd on the first real install. Rather than treat a
    catalogue-wide assumption as truth, try the recorded branch and then the
    obvious alternative. Two requests in the worst case, no API token needed.
    """
    primary = _raw_url(details_url)
    urls = [primary]
    for a, b in (("/main/", "/master/"), ("/master/", "/main/")):
        if a in primary:
            urls.append(primary.replace(a, b, 1))
            break

    # Same story with filename casing: the catalogue records skill.md for one
    # entry and SKILL.md for its ten siblings, and the repository has SKILL.md
    # throughout. Raw GitHub is case-sensitive, so that one 404s.
    cased: list[str] = []
    for u in urls:
        if u.endswith("/skill.md"):
            cased.append(u[: -len("skill.md")] + "SKILL.md")
        elif u.endswith("/SKILL.md"):
            cased.append(u[: -len("SKILL.md")] + "skill.md")
    return urls + cased


async def install_pack(
    pack: SkillPack,
    *,
    dest: Path | None = None,
    on_event: Any = None,
) -> dict[str, Any]:
    """Fetch a pack's skill files. Returns a report; never raises for one bad file."""
    from .fetch.http import fetch_bytes

    target = (dest or install_root()) / pack.slug
    target.mkdir(parents=True, exist_ok=True)

    written: list[dict[str, str]] = []
    failed: list[dict[str, str]] = []

    for skill in pack.skills:
        candidates = _candidate_urls(skill.details_url) if skill.details_url else []
        if not candidates:
            failed.append({"skill": skill.slug, "error": "no source URL in the catalogue"})
            continue

        data, url, last_error = None, "", ""
        for candidate in candidates:
            try:
                data = await fetch_bytes(candidate, max_bytes=2 * 1024 * 1024)
                url = candidate
                break
            except Exception as e:  # noqa: BLE001 — a private repo or moved file is normal
                last_error = str(e)[:200]

        if data is None:
            failed.append({"skill": skill.slug, "error": last_error})
            if on_event:
                on_event("fail", skill.slug, last_error[:120])
            continue

        out = target / f"{skill.slug}.md"
        out.write_bytes(data)
        written.append({"skill": skill.slug, "file": out.name, "url": url})
        if on_event:
            on_event("ok", skill.slug, out.name)

    # The provenance of an installed tree. Without this, six months later
    # nobody can say whose file this is or what licence it arrived under.
    (target / "pack.json").write_text(
        json.dumps(
            {
                "pack": pack.to_dict() | {"skills": []},
                "installed": written,
                "failed": failed,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    return {"pack": pack.slug, "installed": len(written), "failed": len(failed), "path": str(target)}


def installed_packs(dest: Path | None = None) -> list[dict[str, Any]]:
    """What is installed, read back from each pack.json."""
    root = dest or install_root()
    if not root.is_dir():
        return []

    out: list[dict[str, Any]] = []
    for pack_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        manifest = pack_dir / "pack.json"
        meta: dict[str, Any] = {}
        if manifest.is_file():
            try:
                meta = json.loads(manifest.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                meta = {}
        out.append(
            {
                "slug": pack_dir.name,
                "files": len(list(pack_dir.glob("*.md"))),
                "license": (meta.get("pack") or {}).get("license", "unknown"),
                "source_url": (meta.get("pack") or {}).get("source_url", ""),
                "path": str(pack_dir),
            }
        )
    return out


def remove_pack(slug: str, dest: Path | None = None) -> bool:
    import shutil

    target = (dest or install_root()) / slug
    if not target.is_dir():
        return False
    shutil.rmtree(target)
    return True
