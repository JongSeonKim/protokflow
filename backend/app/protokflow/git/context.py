"""Git checkout observation adapter (U1).

Returns a single observation of a worktree's checkout state: root paths,
full symbolic ref, HEAD OID, and detached status, plus the normalized
identities from the pure core identity module (R25, R26).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backend.app.protokflow.core.identity import repository_id, worktree_id
from backend.app.protokflow.error.git import GitCommandError, GitWorktreeInvalidError
from backend.app.protokflow.git import process


@dataclass(frozen=True, slots=True)
class CheckoutContext:
    """Single observation of a Git worktree checkout state (R26)."""

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
) -> CheckoutContext:
    """Observe the checkout state of the worktree containing path."""
    try:
        toplevel, common_dir, git_dir = _worktree_paths(
            path, git_executable=git_executable
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
    )
    symbolic_ref = symbolic.stdout.strip() if symbolic.returncode == 0 else None

    head = process.run_git(
        ("rev-parse", "--verify", "--quiet", "HEAD"),
        cwd=toplevel,
        check=False,
        git_executable=git_executable,
    )
    if head.returncode == 0:
        head_oid: str | None = head.stdout.strip()
    elif head.returncode == 1:
        head_oid = None  # unborn branch: ref identity exists, no commit yet
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
) -> tuple[Path, Path, Path]:
    """Resolve toplevel, common dir, and git dir with one rev-parse call."""
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
    )
    toplevel, common_dir, git_dir = result.stdout.splitlines()[:3]
    return Path(toplevel), Path(common_dir), Path(git_dir)
