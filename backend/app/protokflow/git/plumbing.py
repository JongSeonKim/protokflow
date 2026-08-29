"""Low-level Git plumbing operations using isolated temporary indexes and conditional ref updates.

Performs repository mutations exclusively through plumbing commands to guarantee
isolation: blobs are written with hash-object, trees are composed inside a temporary
index file, commits are generated with commit-tree, and references are updated
atomically via compare-and-swap (update-ref). The working tree stays untouched;
update_index_entry is the single deliberate writer of the repository's real
index.
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


RUNTIME_IDENTITY_NAME = "Protokflow Runtime"
RUNTIME_IDENTITY_EMAIL = "runtime@protokflow.invalid"


@dataclass(frozen=True, slots=True)
class RefUpdateResult:
    """Outcome of a conditional reference update (compare-and-swap).

    accepted is False when the reference is no longer at expected_oid (moved
    concurrently or deleted). stderr preserves the underlying failure detail
    and current_oid reports the ref's OID at classification time (None when
    the ref does not resolve), so callers can distinguish retryable
    concurrency conflicts from permanent errors.
    """

    ref: str
    accepted: bool
    expected_oid: str
    current_oid: str | None
    stderr: str


class IsolatedIndex:
    """Manages operations within an isolated temporary GIT_INDEX_FILE."""

    def __init__(
        self,
        worktree_root: Path,
        path: Path,
        git_executable: str,
        timeout: float | None,
    ) -> None:
        self._worktree_root = worktree_root
        self.path = path
        self._git_executable = git_executable
        self._timeout = timeout

    def read_tree(self, treeish: str) -> None:
        """Populate the temporary index from an existing tree-ish object."""
        self._run("read-tree", treeish)

    def update_entry(self, *, mode: str, oid: str, path: str) -> None:
        """Update or insert a single entry into the temporary index via --cacheinfo."""
        self._run("update-index", "--add", "--cacheinfo", f"{mode},{oid},{path}")

    def write_tree(self) -> str:
        """Write the temporary index to the object database and return the resulting tree OID."""
        return self._run("write-tree").stdout.strip()

    def _run(self, *args: str) -> process.GitCommandResult:
        return process.run_git(
            args,
            cwd=self._worktree_root,
            env={"GIT_INDEX_FILE": str(self.path)},
            git_executable=self._git_executable,
            timeout=self._timeout,
        )


@contextmanager
def isolated_index(
    worktree_root: str | Path,
    *,
    git_executable: str = process.DEFAULT_GIT_EXECUTABLE,
    timeout: float | None = process.DEFAULT_GIT_TIMEOUT_SECONDS,
) -> Iterator[IsolatedIndex]:
    """Context manager providing an isolated temporary index file for staging Git operations.

    Ensures every command within the scope uses an explicit temporary GIT_INDEX_FILE,
    preventing unintended leaks to or from inherited environment variables. The temporary
    index file is guaranteed to be deleted on exit, including during unhandled exceptions.
    """
    descriptor, raw_path = tempfile.mkstemp(prefix="protokflow-index-", suffix=".tmp")
    os.close(descriptor)
    index_path = Path(raw_path)
    try:
        yield IsolatedIndex(Path(worktree_root), index_path, git_executable, timeout)
    finally:
        index_path.unlink(missing_ok=True)


def create_blob(
    worktree_root: str | Path,
    content: bytes,
    *,
    git_executable: str = process.DEFAULT_GIT_EXECUTABLE,
    timeout: float | None = process.DEFAULT_GIT_TIMEOUT_SECONDS,
) -> str:
    """Write raw bytes to the Git object database as a blob and return its object ID."""
    result = process.run_git(
        ("hash-object", "-w", "--stdin"),
        cwd=worktree_root,
        input_bytes=content,
        git_executable=git_executable,
        timeout=timeout,
    )
    return result.stdout.strip()


def create_commit(
    worktree_root: str | Path,
    *,
    tree: str,
    parent: str,
    message: str,
    git_executable: str = process.DEFAULT_GIT_EXECUTABLE,
    timeout: float | None = process.DEFAULT_GIT_TIMEOUT_SECONDS,
) -> str:
    """Create a commit object pointing to the specified tree and parent commit, returning its object ID."""
    author_name, author_email = _resolve_identity(
        worktree_root, git_executable=git_executable
    )
    result = process.run_git(
        ("commit-tree", tree, "-p", parent, "-m", message),
        cwd=worktree_root,
        env={
            "GIT_AUTHOR_NAME": author_name,
            "GIT_AUTHOR_EMAIL": author_email,
            "GIT_COMMITTER_NAME": author_name,
            "GIT_COMMITTER_EMAIL": author_email,
        },
        git_executable=git_executable,
        timeout=timeout,
    )
    return result.stdout.strip()


def _resolve_identity(
    worktree_root: str | Path,
    *,
    git_executable: str,
) -> tuple[str, str]:
    """Resolve author/committer identity from git config with a fixed runtime fallback."""
    name = _config_value(worktree_root, "user.name", git_executable=git_executable)
    email = _config_value(worktree_root, "user.email", git_executable=git_executable)
    return (
        name or RUNTIME_IDENTITY_NAME,
        email or RUNTIME_IDENTITY_EMAIL,
    )


def _config_value(
    worktree_root: str | Path,
    key: str,
    *,
    git_executable: str,
) -> str | None:
    """Return the repository's local value for a git config key, or None when unset.

    Resolution is deliberately scoped to the repository's own config file so
    export identity stays deterministic and independent of the host account's
    global or system git configuration.
    """
    result = process.run_git(
        ("config", "--local", "--null", key),
        cwd=worktree_root,
        check=False,
        git_executable=git_executable,
    )
    if result.returncode != 0:
        return None
    return result.stdout.rstrip("\x00")


def update_index_entry(
    worktree_root: str | Path,
    *,
    mode: str,
    oid: str,
    path: str,
    git_executable: str = process.DEFAULT_GIT_EXECUTABLE,
    timeout: float | None = process.DEFAULT_GIT_TIMEOUT_SECONDS,
) -> None:
    """Update a single entry in the repository's real index file via update-index --cacheinfo.

    Directs updates explicitly to the repository's index path so that any inherited
    GIT_INDEX_FILE environment variable does not misdirect the modification.
    """
    git_dir = process.run_git(
        ("rev-parse", "--path-format=absolute", "--absolute-git-dir"),
        cwd=worktree_root,
        env={"GIT_INDEX_FILE": None},
        git_executable=git_executable,
        timeout=timeout,
    )
    real_index = Path(git_dir.stdout.strip()) / "index"
    process.run_git(
        ("update-index", "--add", "--cacheinfo", f"{mode},{oid},{path}"),
        cwd=worktree_root,
        env={"GIT_INDEX_FILE": str(real_index)},
        git_executable=git_executable,
        timeout=timeout,
    )


def update_ref_conditionally(
    worktree_root: str | Path,
    *,
    ref: str,
    new_oid: str,
    expected_oid: str,
    reason: str,
    git_executable: str = process.DEFAULT_GIT_EXECUTABLE,
    timeout: float | None = process.DEFAULT_GIT_TIMEOUT_SECONDS,
) -> RefUpdateResult:
    """Advance ref to new_oid only if it currently points to expected_oid.

    Uses the compare-and-swap form of update-ref. A non-zero exit is classified
    by probing the ref's current OID instead of matching git's localized stderr
    text: a current OID different from expected_oid (including a concurrently
    deleted ref) is a rejected CAS returned as accepted=False, while a ref
    still sitting at expected_oid indicates a permanent failure raised as
    GitCommandError.
    """
    result = process.run_git(
        ("update-ref", "-m", reason, "--", ref, new_oid, expected_oid),
        cwd=worktree_root,
        check=False,
        git_executable=git_executable,
        timeout=timeout,
    )
    if result.returncode == 0:
        return RefUpdateResult(
            ref=ref,
            accepted=True,
            expected_oid=expected_oid,
            current_oid=new_oid,
            stderr="",
        )
    current = _current_ref_oid(
        worktree_root, ref, git_executable=git_executable, timeout=timeout
    )
    if current != expected_oid:
        return RefUpdateResult(
            ref=ref,
            accepted=False,
            expected_oid=expected_oid,
            current_oid=current,
            stderr=result.stderr,
        )
    raise GitCommandError(
        result.command,
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )


def _current_ref_oid(
    worktree_root: str | Path,
    ref: str,
    *,
    git_executable: str,
    timeout: float | None,
) -> str | None:
    """Return the ref's current OID, or None when the ref does not resolve."""
    probe = process.run_git(
        ("rev-parse", "--verify", "--quiet", ref),
        cwd=worktree_root,
        check=False,
        git_executable=git_executable,
        timeout=timeout,
    )
    return probe.stdout.strip() if probe.returncode == 0 else None
