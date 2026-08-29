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
        toplevel = _rev_parse(path, "--show-toplevel", git_executable=git_executable)
        common_dir = Path(
            _rev_parse(
                path,
                "--path-format=absolute",
                "--git-common-dir",
                git_executable=git_executable,
            )
        )
        git_dir = Path(
            _rev_parse(
                path,
                "--path-format=absolute",
                "--absolute-git-dir",
                git_executable=git_executable,
            )
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
        ("rev-parse", "HEAD"),
        cwd=toplevel,
        check=False,
        git_executable=git_executable,
    )
    if head.returncode == 0:
        head_oid: str | None = head.stdout.strip()
    elif _is_unknown_revision(head.stderr):
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


def _rev_parse(
    path: str | Path,
    *args: str,
    git_executable: str,
) -> str:
    result = process.run_git(
        ("rev-parse", *args),
        cwd=path,
        git_executable=git_executable,
    )
    return result.stdout.strip()


def _is_unknown_revision(stderr: str) -> bool:
    return "unknown revision" in stderr or "ambiguous argument" in stderr
