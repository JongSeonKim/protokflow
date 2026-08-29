"""Isolated-index commit and conditional ref plumbing (KTD4).

Export-grade Git mutations avoid porcelain commands: blobs are written with
hash-object, trees are composed against a temporary index, commits are
created with commit-tree, and refs move only when an expected OID still
matches (update-ref compare-and-swap). The user's real index and staged
state are never touched by temporary-index work (R19).
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from backend.app.protokflow.error.git import GitCommandError
from backend.app.protokflow.git import process


@dataclass(frozen=True, slots=True)
class RefUpdateResult:
    """Outcome of an expected-OID conditional ref update (R19).

    accepted is False when the ref moved concurrently; stderr and cause
    preserve the original failure evidence so callers can separate
    retryable concurrency conflicts from permanent failures.
    """

    ref: str
    accepted: bool
    expected_oid: str
    current_oid: str
    stderr: str
    cause: GitCommandError | None


class IsolatedIndex:
    """Handle over one temporary GIT_INDEX_FILE inside a single scope."""

    def __init__(self, worktree_root: Path, path: Path, git_executable: str) -> None:
        self._worktree_root = worktree_root
        self.path = path
        self._git_executable = git_executable

    def read_tree(self, treeish: str) -> None:
        """Load a tree-ish into the temporary index."""
        self._run("read-tree", treeish)

    def update_entry(self, *, mode: str, oid: str, path: str) -> None:
        """Replace a single index entry through --cacheinfo."""
        self._run("update-index", "--add", "--cacheinfo", f"{mode},{oid},{path}")

    def write_tree(self) -> str:
        """Materialize the temporary index into a tree object."""
        return self._run("write-tree").stdout.strip()

    def _run(self, *args: str) -> process.GitCommandResult:
        return process.run_git(
            args,
            cwd=self._worktree_root,
            env={"GIT_INDEX_FILE": str(self.path)},
            git_executable=self._git_executable,
        )


@contextmanager
def isolated_index(
    worktree_root: str | Path,
    *,
    git_executable: str = process.DEFAULT_GIT_EXECUTABLE,
) -> Iterator[IsolatedIndex]:
    """Isolate temporary-index commands behind an explicit GIT_INDEX_FILE.

    Every command in the scope explicitly sets GIT_INDEX_FILE, so an
    inherited override cannot leak in or out. The temporary file is removed
    on every exit path, including exceptions (KTD4).
    """
    descriptor, raw_path = tempfile.mkstemp(prefix="protokflow-index-", suffix=".tmp")
    os.close(descriptor)
    index_path = Path(raw_path)
    try:
        yield IsolatedIndex(Path(worktree_root), index_path, git_executable)
    finally:
        index_path.unlink(missing_ok=True)


def create_blob(
    worktree_root: str | Path,
    content: bytes,
    *,
    git_executable: str = process.DEFAULT_GIT_EXECUTABLE,
) -> str:
    """Write content as a blob object and return its OID (R19)."""
    result = process.run_git(
        ("hash-object", "-w", "--stdin"),
        cwd=worktree_root,
        input_bytes=content,
        git_executable=git_executable,
    )
    return result.stdout.strip()


def create_commit(
    worktree_root: str | Path,
    *,
    tree: str,
    parent: str,
    message: str,
    git_executable: str = process.DEFAULT_GIT_EXECUTABLE,
) -> str:
    """Create a commit object on top of parent and return its OID (KTD4)."""
    result = process.run_git(
        ("commit-tree", tree, "-p", parent, "-m", message),
        cwd=worktree_root,
        git_executable=git_executable,
    )
    return result.stdout.strip()


def update_index_entry(
    worktree_root: str | Path,
    *,
    mode: str,
    oid: str,
    path: str,
    git_executable: str = process.DEFAULT_GIT_EXECUTABLE,
) -> None:
    """Replace one entry in the repository's real index (R19).

    The update runs against the explicit real index path so an inherited
    GIT_INDEX_FILE cannot redirect it, and git's index lock serializes
    concurrent writers.
    """
    git_dir = process.run_git(
        ("rev-parse", "--path-format=absolute", "--absolute-git-dir"),
        cwd=worktree_root,
        env={"GIT_INDEX_FILE": None},
        git_executable=git_executable,
    )
    real_index = Path(git_dir.stdout.strip()) / "index"
    process.run_git(
        ("update-index", "--add", "--cacheinfo", f"{mode},{oid},{path}"),
        cwd=worktree_root,
        env={"GIT_INDEX_FILE": str(real_index)},
        git_executable=git_executable,
    )


def update_ref_conditionally(
    worktree_root: str | Path,
    *,
    ref: str,
    new_oid: str,
    expected_oid: str,
    reason: str,
    git_executable: str = process.DEFAULT_GIT_EXECUTABLE,
) -> RefUpdateResult:
    """Move ref to new_oid only while it still equals expected_oid.

    Uses the compare-and-swap form of update-ref. A stale expectation is
    reported as a dedicated RefUpdateResult instead of a command error so
    callers can identify retryable concurrency conflicts (R19, KTD4).
    """
    result = process.run_git(
        ("update-ref", "-m", reason, "--", ref, new_oid, expected_oid),
        cwd=worktree_root,
        check=False,
        git_executable=git_executable,
    )
    if result.returncode == 0:
        return RefUpdateResult(
            ref=ref,
            accepted=True,
            expected_oid=expected_oid,
            current_oid=new_oid,
            stderr="",
            cause=None,
        )
    cause = GitCommandError(
        result.command,
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )
    if "but expected" not in result.stderr:
        raise cause
    return RefUpdateResult(
        ref=ref,
        accepted=False,
        expected_oid=expected_oid,
        current_oid=_current_ref_oid(worktree_root, ref, git_executable=git_executable),
        stderr=result.stderr,
        cause=cause,
    )


def _current_ref_oid(
    worktree_root: str | Path,
    ref: str,
    *,
    git_executable: str,
) -> str:
    probe = process.run_git(
        ("rev-parse", "--verify", "--quiet", ref),
        cwd=worktree_root,
        check=False,
        git_executable=git_executable,
    )
    return probe.stdout.strip() if probe.returncode == 0 else ""
