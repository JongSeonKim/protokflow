"""Pytest fixtures for temporary Git repositories and linked worktrees.

Provides TemporaryGitRepository, an isolated repository helper with
a deterministic default branch and local identity configuration, plus helpers
for staging changes, creating commits, detaching HEAD, and attaching linked
worktrees. All state lives under pytest's per-test tmp_path so parallel
xdist workers never share repositories.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from backend.app.protokflow.git import process

if TYPE_CHECKING:
    from collections.abc import Generator

DEFAULT_BRANCH = "main"

DESIGN_MD_CONTENT = "---\ncolors:\n  primary: '#3366ff'\n---\n\n# Guide\n"

# Host-independent git config: ambient global/system configuration, hooks
# paths, and signing defaults must not leak into test repositories.
SANITIZED_GIT_ENV: dict[str, str | None] = {
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}


class TemporaryGitRepository:
    """Helper wrapping a temporary Git worktree for tests."""

    def __init__(self, root: Path) -> None:
        self.root = root

    @classmethod
    def init(
        cls,
        root: Path,
        *,
        with_initial_commit: bool = True,
    ) -> TemporaryGitRepository:
        """Initialize a repository with a local identity and a DESIGN.md file."""
        repo = cls(root)
        root.mkdir(parents=True)
        repo.run("init", "--initial-branch", DEFAULT_BRANCH)
        repo.run("config", "user.name", "Protokflow Tests")
        repo.run("config", "user.email", "tests@protokflow.invalid")
        repo.run("config", "commit.gpgsign", "false")
        repo.write_file("DESIGN.md", DESIGN_MD_CONTENT)
        if with_initial_commit:
            repo.commit_all("initial commit")
        return repo

    def run(
        self,
        *args: str,
        check: bool = True,
        input_bytes: bytes | None = None,
        env: dict[str, str | None] | None = None,
    ) -> process.GitCommandResult:
        """Run a git command inside the repository worktree."""
        return process.run_git(
            args,
            cwd=self.root,
            check=check,
            input_bytes=input_bytes,
            env={**SANITIZED_GIT_ENV, **(env or {})},
        )

    def git_stdout(self, *args: str) -> str:
        """Run a git command and return its stripped standard output."""
        return self.run(*args).stdout.strip()

    def write_file(self, relpath: str, content: str) -> Path:
        """Write a UTF-8 text file inside the worktree."""
        path = self.root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def stage(self, *relpaths: str) -> None:
        """Stage the given worktree paths."""
        self.run("add", "--", *relpaths)

    def commit_all(self, message: str) -> str:
        """Commit every pending change and return the new HEAD OID."""
        self.run("add", "-A")
        self.run("commit", "-m", message)
        return self.head_oid()

    def head_oid(self) -> str:
        """Return the current HEAD commit OID."""
        return self.git_stdout("rev-parse", "HEAD")

    def head_tree(self) -> str:
        """Return the tree OID of the current HEAD commit."""
        return self.git_stdout("rev-parse", "HEAD^{tree}")

    def tree_entries(self, treeish: str) -> dict[str, tuple[str, str]]:
        """List a tree recursively as a mapping of path to (mode, oid)."""
        entries: dict[str, tuple[str, str]] = {}
        for line in self.git_stdout("ls-tree", "-r", treeish).splitlines():
            meta, entry_path = line.split("\t", 1)
            mode, _object_type, oid = meta.split()
            entries[entry_path] = (mode, oid)
        return entries

    def index_entries(self) -> dict[str, tuple[str, str]]:
        """List entries in the repository's real index as a mapping of path to (mode, oid).

        Explicitly unsets GIT_INDEX_FILE so this helper always inspects the
        repository's real index, mirroring update_index_entry.
        """
        result = self.run("ls-files", "-s", env={"GIT_INDEX_FILE": None})
        entries: dict[str, tuple[str, str]] = {}
        for line in result.stdout.strip().splitlines():
            meta, entry_path = line.split("\t", 1)
            mode, oid, _stage = meta.split()
            entries[entry_path] = (mode, oid)
        return entries

    def commit_object(self, oid: str) -> str:
        """Return the raw commit object text for the given OID."""
        return self.git_stdout("cat-file", "commit", oid)

    def set_ref(self, ref: str, oid: str) -> None:
        """Point the ref at the OID without any expectation check."""
        self.run("update-ref", ref, oid)

    def detach(self) -> None:
        """Detach HEAD at the current commit."""
        self.run("checkout", "--detach")

    def add_worktree(self, name: str) -> TemporaryGitRepository:
        """Attach a linked worktree on a new branch and return its handle."""
        worktree_root = self.root.parent / name
        self.run("worktree", "add", "-b", name, str(worktree_root))
        return TemporaryGitRepository(worktree_root)


@pytest.fixture
def git_repo(tmp_path: Path) -> Generator[TemporaryGitRepository, None, None]:
    """Provide a temporary repository holding one initial DESIGN.md commit."""
    yield TemporaryGitRepository.init(tmp_path / "repo")
