"""GitHub integration — create paper repos and push artifacts."""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from ...logging_config import get_logger
from .templates import LATEX_GITIGNORE, render_readme

logger = get_logger(__name__)


class GitHubClient:
    """Thin wrapper around PyGithub for paper repo management."""

    def __init__(self, token: str, username: str) -> None:
        from github import Github

        self._gh = Github(token)
        self._username = username
        self._user = self._gh.get_user()

    def create_paper_repo(
        self,
        paper_id: str,
        paper_title: str,
        private: bool = True,
    ) -> dict[str, Any]:
        """Create a new GitHub repo for a paper.

        IMPORTANT: .gitignore is committed FIRST (before README or any LaTeX content)
        so that Overleaf integration never pollutes git history with artifacts.
        """
        repo_name = _slugify(paper_title, paper_id)

        try:
            repo = self._user.create_repo(
                name=repo_name,
                description=f"E2ER v3 generated paper: {paper_title}",
                private=private,
                auto_init=False,
            )
        except Exception as e:
            if "already exists" in str(e).lower():
                logger.warning("Repo %s already exists, using existing", repo_name)
                repo = self._user.get_repo(repo_name)
            else:
                raise

        # Step 1: .gitignore as the FIRST commit — this is critical for Overleaf
        try:
            repo.create_file(
                path=".gitignore",
                message="chore: add LaTeX .gitignore (Overleaf-safe)",
                content=LATEX_GITIGNORE,
                branch="main",
            )
            logger.info("Created .gitignore in %s", repo_name)
        except Exception as e:
            logger.warning("Could not create .gitignore: %s", e)

        # Step 2: README
        readme = render_readme(paper_title, paper_id, self._username)
        try:
            repo.create_file(
                path="README.md",
                message="docs: initial README",
                content=readme,
                branch="main",
            )
        except Exception as e:
            logger.warning("Could not create README: %s", e)

        return {
            "repo_name": repo_name,
            "clone_url": repo.clone_url,
            "html_url": repo.html_url,
            "ssh_url": repo.ssh_url,
        }

    def push_file(
        self,
        repo_name: str,
        file_path: str,
        content: str | bytes,
        commit_message: str,
        branch: str = "main",
    ) -> None:
        """Create or update a file in the repo."""
        repo = self._user.get_repo(repo_name)
        if isinstance(content, str):
            encoded = content.encode()
        else:
            encoded = content

        try:
            existing = repo.get_contents(file_path, ref=branch)
            repo.update_file(
                path=file_path,
                message=commit_message,
                content=encoded,
                sha=existing.sha,
                branch=branch,
            )
        except Exception:
            repo.create_file(
                path=file_path,
                message=commit_message,
                content=encoded,
                branch=branch,
            )

    def push_directory(
        self,
        repo_name: str,
        local_dir: Path,
        remote_prefix: str = "",
        commit_message: str = "chore: push artifacts",
        extensions: list[str] | None = None,
    ) -> int:
        """Push all files from a local directory to the repo. Returns file count."""
        count = 0
        for file_path in sorted(local_dir.rglob("*")):
            if not file_path.is_file():
                continue
            if extensions and file_path.suffix not in extensions:
                continue
            relative = file_path.relative_to(local_dir)
            remote_path = f"{remote_prefix}/{relative}" if remote_prefix else str(relative)
            try:
                content = file_path.read_bytes()
                self.push_file(repo_name, remote_path, content, commit_message)
                count += 1
            except Exception as e:
                logger.warning("Could not push %s: %s", remote_path, e)
        return count

    def ensure_replication_scaffold(self, repo_name: str) -> None:
        """Create the replication/ directory scaffold if it doesn't exist."""
        stubs = {
            "replication/.gitkeep": "",
            "replication/data/.gitkeep": "",
        }
        for path, content in stubs.items():
            try:
                self.push_file(
                    repo_name, path, content,
                    "chore: scaffold replication package structure",
                )
            except Exception as e:
                logger.debug("Scaffold %s skipped: %s", path, e)


def _slugify(title: str, paper_id: str) -> str:
    """Convert paper title to a valid GitHub repo name."""
    import re

    slug = title.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug.strip())
    slug = slug[:50].rstrip("-")
    return f"paper-{slug}-{paper_id[:8]}" if slug else f"paper-{paper_id[:8]}"
