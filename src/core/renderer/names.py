"""The names of the files the renderers write under ``tables/`` and ``figures/``.

A name comes from a spec the model wrote (``table_spec.json``, ``figure_spec.json``), so it is one
plain file name: no ``/`` and, since a backslash is a separator on Windows, no ``\\`` either
(``..\\paper_draft.tex`` wrote over the draft there), no drive (``C:x.tex``), no hidden or
dot-only name, no control character.
"""

from __future__ import annotations


def plain_filename(name: object, suffix: str) -> bool:
    """Is ``name`` one plain file name ending in ``suffix`` (e.g. ``".tex"``)?"""
    if not isinstance(name, str) or not name.endswith(suffix) or len(name) <= len(suffix) or len(name) > 200:
        return False
    if any(c in name for c in "/\\:") or name.startswith(".") or name.strip() != name:
        return False
    return not any(ord(c) < 32 or ord(c) == 127 for c in name)
