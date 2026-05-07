"""GitHub push hooks — called at pipeline stage transitions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...logging_config import get_logger

logger = get_logger(__name__)


async def push_latex_draft(
    paper_id: str,
    workspace: Path,
    stage: str,
) -> dict[str, Any] | None:
    """Push the current LaTeX draft to GitHub after a pipeline stage completes."""
    from ...config import get_settings
    from ...db.client import fetch_one
    from .client import GitHubClient

    settings = get_settings()
    if not settings.github_enabled:
        return None

    row = await fetch_one(
        "SELECT github_repo FROM papers WHERE id = %(id)s",
        {"id": paper_id},
    )
    if not row or not row.get("github_repo"):
        return None

    repo_name = row["github_repo"]
    client = GitHubClient(settings.github_token, settings.github_username)

    pushed = client.push_directory(
        repo_name=repo_name,
        local_dir=workspace,
        remote_prefix="",
        commit_message=f"feat: {stage} stage artifacts",
        extensions=[".tex", ".bib", ".sty", ".cls"],
    )
    logger.info("Pushed %d LaTeX files to %s after %s", pushed, repo_name, stage)
    return {"pushed_files": pushed, "stage": stage, "repo": repo_name}


async def push_replication_package(
    paper_id: str,
    replication_dir: Path,
) -> dict[str, Any] | None:
    """Push the replication package to GitHub (SQL queries, estimation code, audit log)."""
    from ...config import get_settings
    from ...db.client import fetch_one
    from .client import GitHubClient

    settings = get_settings()
    if not settings.github_enabled:
        return None

    row = await fetch_one(
        "SELECT github_repo FROM papers WHERE id = %(id)s",
        {"id": paper_id},
    )
    if not row or not row.get("github_repo"):
        return None

    repo_name = row["github_repo"]
    client = GitHubClient(settings.github_token, settings.github_username)
    client.ensure_replication_scaffold(repo_name)

    pushed = client.push_directory(
        repo_name=repo_name,
        local_dir=replication_dir,
        remote_prefix="replication",
        commit_message="feat: add replication package",
    )
    logger.info("Pushed %d replication files to %s", pushed, repo_name)
    return {"pushed_files": pushed, "repo": repo_name}
