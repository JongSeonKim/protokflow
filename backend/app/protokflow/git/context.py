"""Git checkout observation adapter.

Inspects a worktree's checkout state in a single pass, capturing root directories,
symbolic branch reference, HEAD commit OID, detached HEAD status, and deterministic
repository and worktree identifiers.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backend.app.protokflow.core.identity import repository_id, worktree_id
from backend.app.protokflow.error.git import GitCommandError, GitWorktreeInvalidError
from backend.app.protokflow.git import process


@dataclass(frozen=True, slots=True)
class CheckoutContext:
    """Immutable snapshot of a Git worktree's checkout state and path identities."""

    worktree_root: Path
    git_common_dir: Path
    git_dir: Path
    symbolic_ref: str | None
    head_oid: str | None
    detached: bool
    repository_id: str
    worktree_id: str


def observe_checkout(
    path: str | Path,
    *,
    git_executable: str = process.DEFAULT_GIT_EXECUTABLE,
    timeout: float | None = process.DEFAULT_GIT_TIMEOUT_SECONDS,
) -> CheckoutContext:
    """Inspect and return the current checkout state of the Git worktree containing path."""
    try:
        toplevel, common_dir, git_dir = _worktree_paths(
            path, git_executable=git_executable, timeout=timeout
        )
    except GitCommandError as exc:
        raise GitWorktreeInvalidError(f"not a Git worktree: {Path(path)}") from exc
    except OSError as exc:
        raise GitWorktreeInvalidError(f"cannot access path: {Path(path)}") from exc

    symbolic = process.run_git(
        ("symbolic-ref", "--quiet", "HEAD"),
        cwd=toplevel,
        check=False,
        git_executable=git_executable,
        timeout=timeout,
    )
    symbolic_ref = symbolic.stdout.strip() if symbolic.returncode == 0 else None

    head = process.run_git(
        ("rev-parse", "--verify", "--quiet", "HEAD"),
        cwd=toplevel,
        check=False,
        git_executable=git_executable,
        timeout=timeout,
    )
    if head.returncode == 0:
        head_oid: str | None = head.stdout.strip()
    elif head.returncode == 1:
        head_oid = None  # Unborn branch: symbolic reference exists, but no commits yet
    else:
        raise GitCommandError(
            head.command,
            returncode=head.returncode,
            stdout=head.stdout,
            stderr=head.stderr,
        )

    return CheckoutContext(
        worktree_root=Path(toplevel),
        git_common_dir=common_dir,
        git_dir=git_dir,
        symbolic_ref=symbolic_ref,
        head_oid=head_oid,
        detached=symbolic_ref is None,
        repository_id=repository_id(common_dir),
        worktree_id=worktree_id(toplevel),
    )


def _worktree_paths(
    path: str | Path,
    *,
    git_executable: str,
    timeout: float | None,
) -> tuple[Path, Path, Path]:
    """Resolve the worktree root, common git directory, and worktree git directory in a single rev-parse call."""
    result = process.run_git(
        (
            "rev-parse",
            "--path-format=absolute",
            "--show-toplevel",
            "--git-common-dir",
            "--absolute-git-dir",
        ),
        cwd=path,
        git_executable=git_executable,
        timeout=timeout,
    )
    toplevel, common_dir, git_dir = result.stdout.splitlines()[:3]
    return Path(toplevel), Path(common_dir), Path(git_dir)
