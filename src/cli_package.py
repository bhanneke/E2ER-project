"""`e2er pack`, `e2er unpack`, `e2er inspect`: a study as one .e2er file (src/core/export/package.py)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .core.export import package as pkg


def _report(packed: pkg.Packed) -> None:
    m = packed.manifest
    print(f"Packed → {packed.path}")
    print(f"  {len(m['contents'])} file(s), {pkg.human_size(packed.size)}; fingerprint {m['fingerprint']}")
    for item in m.get("left_out") or []:
        print(f"  left out: {item['path']} ({item['reason']}); {pkg.rerun_words(item)}")
    env = m.get("environment") or {}
    if env.get("lock"):
        print(f"  packages: pinned with their hashes for Python {env.get('python')} ({env['lock']})")
    wheels = m.get("wheels")
    if wheels:
        print(
            f"  offline install: {wheels['files']} wheel(s) for {wheels['platform']} "
            f"({pkg.human_size(int(wheels['bytes']))})"
        )
    for note in packed.notes:
        print(f"  note: {note}")


def pack_folder(folder: Path, out: str | None, *, offline: bool, no_data: bool) -> int:
    if offline:
        print("Downloading the wheels for this computer: this can add hundreds of MB to the package ...", flush=True)
    try:
        packed = pkg.build(folder, Path(out) if out else None, offline=offline, no_data=no_data)
    except pkg.PackageError as e:
        print(f"error: {e}")
        return 1
    _report(packed)
    return 0


def pack(target: str, out: str | None = None, *, offline: bool = False, no_data: bool = False) -> int:
    """`e2er pack <study id | exported folder>`: an exported folder is packed as is; a study is exported first."""
    path = Path(target).expanduser()
    if path.is_dir():
        return pack_folder(path, out, offline=offline, no_data=no_data)
    from .cli_export import ExportLookupError, _recorded_template, resolve_workspace
    from .config import get_settings
    from .core.export.structured import export_paper

    settings = get_settings()
    try:
        paper_id, workspace = resolve_workspace(target, settings)
    except ExportLookupError as e:
        print(f"error: {target} is not an exported study folder, and {e}")
        return 1
    try:
        folder = export_paper(
            workspace,
            settings.resolved_output_root(),
            date_str=datetime.now().strftime("%Y%m%d"),
            template=_recorded_template(paper_id),
        )
    except Exception as e:  # noqa: BLE001
        print(f"error: export failed: {e}")
        return 1
    print(f"Exported → {folder}")
    return pack_folder(folder, out, offline=offline, no_data=no_data)


def unpack(package: str, dest: str | None = None) -> int:
    """`e2er unpack <file.e2er> [folder]`: every file checked against the manifest; nothing is run."""
    path = Path(package).expanduser()
    if not path.is_file():
        print(f"error: {package} is not a file")
        return 1
    name = path.name[: -len(pkg.SUFFIX)] if path.name.lower().endswith(pkg.SUFFIX) else path.stem
    target = Path(dest).expanduser() if dest else Path.cwd() / name
    try:
        opened = pkg.open_package(path, target)
    except pkg.PackageError as e:
        print(f"error: the package is not intact: {e}")
        return 1
    print(f"Unpacked → {opened.root}")
    print(f"  {opened.files} file(s) match {pkg.MANIFEST}; fingerprint {opened.manifest.get('fingerprint')}")
    for item in opened.manifest.get("left_out") or []:
        print(f"  left out: {item['path']} ({item.get('reason')})")
    print(f"  Next: e2er verify {opened.root}    e2er reproduce {opened.root}")
    return 0


def inspect(package: str) -> int:
    """`e2er inspect <file.e2er>`: what the package holds, from its manifest (nothing is unpacked)."""
    path = Path(package).expanduser()
    if not path.is_file():
        print(f"error: {package} is not a file")
        return 1
    try:
        manifest = pkg.read_manifest(path)
    except pkg.PackageError as e:
        print(f"error: {e}")
        return 1
    from .core.safe_text import printable

    try:
        print(f"{printable(path.name, newlines=False)}\n")
        print(pkg.summary(manifest, path.stat().st_size), end="")
    except (TypeError, ValueError, AttributeError, KeyError) as e:
        print(f"error: the package's list of files is malformed ({type(e).__name__})")
        return 1
    print("\n" + "\n".join(pkg.archive_steps(path)))
    print("\nRead from the package's list of files; `e2er verify` checks every file against it.")
    return 0
