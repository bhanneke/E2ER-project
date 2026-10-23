"""Checks every dashboard route shares: a run id in the path is a UUID, and nothing else.

A run's id names its folder (``<workspaces>/<id>`` for runs before 0.14.0), so an id like ``..``
(``/api/papers/%2E%2E/artifacts/.env``) reached the studies folder's ``.env`` with the API keys.
Every route that takes ``paper_id`` declares it as :data:`PaperId`; the app-wide
:func:`ids_in_path` check refuses the same ids for a route that forgets.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request

from ..home import is_run_id

is_uuid = is_run_id


def validate_uuid(paper_id: str) -> str:
    """The ``paper_id`` path parameter when it is a UUID, else 404.

    Also keeps an invalid string out of a ``uuid`` column (psycopg would raise
    InvalidTextRepresentation, surfaced as a 500).
    """
    if not is_uuid(paper_id):
        raise HTTPException(status_code=404, detail="Paper not found")
    return paper_id


#: The type of every ``paper_id`` path parameter.
PaperId = Annotated[str, Depends(validate_uuid)]

#: Path parameters that hold a run id or another e2er-made id.
_ID_PARAMS = ("paper_id",)


def ids_in_path(request: Request) -> None:
    """App-wide: a route whose path names a run id gets a 404 for anything but a UUID."""
    for name in _ID_PARAMS:
        if name in request.path_params and not is_uuid(request.path_params[name]):
            raise HTTPException(status_code=404, detail="Paper not found")
