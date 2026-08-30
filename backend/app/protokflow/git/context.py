"""Git checkout observation adapter.

Resolves a worktree's checkout state as one observation operation, capturing root
directories, symbolic branch reference, HEAD commit OID, detached HEAD status,
and deterministic repository and worktree identifiers.
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
        toplevel = _resolve_git_path(
            path, "--show-toplevel", git_executable=git_executable, timeout=timeout
        )
        common_dir = _resolve_git_path(
            path, "--git-common-dir", git_executable=git_executable, timeout=timeout
        )
        git_dir = _resolve_git_path(
            path, "--absolute-git-dir", git_executable=git_executable, timeout=timeout
        )
    except GitCommandError as exc:
        raise GitWorktreeInvalidError(f"not a Git worktree: {Path(path)}") from exc
    except OSError as exc:
        raise GitWorktreeInvalidError(f"cannot access path: {Path(path)}") from exc

    symbolic_ref, head_oid = _head_state(
        toplevel, git_executable=git_executable, timeout=timeout
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


def _resolve_git_path(
    path: str | Path,
    flag: str,
    *,
    git_executable: str,
    timeout: float | None,
) -> Path:
    """Resolve a single absolute path value from rev-parse.

    Parses the whole stdout as one value (stripping exactly one trailing
    newline) so a worktree path containing newline characters cannot shift a
    positional multi-line parse.
    """
    result = process.run_git(
        ("rev-parse", "--path-format=absolute", flag),
        cwd=path,
        git_executable=git_executable,
        timeout=timeout,
    )

    value = result.stdout
    if value.endswith("\n"):
        value = value[:-1]

    return Path(value)


def _head_state(
    toplevel: Path,
    *,
    git_executable: str,
    timeout: float | None,
) -> tuple[str | None, str | None]:
    """Resolve the symbolic ref and HEAD OID in one rev-parse invocation.

    Emits the HEAD OID first and its symbolic full name second, since neither
    value can contain a newline. A detached HEAD reports the literal name HEAD
    and therefore no symbolic ref. On an unborn branch rev-parse fails and the
    symbolic ref still resolves through symbolic-ref, with no OID.
    """
    combined = process.run_git(
        ("rev-parse", "HEAD", "--symbolic-full-name", "HEAD"),
        cwd=toplevel,
        check=False,
        git_executable=git_executable,
        timeout=timeout,
    )
    if combined.returncode == 0:
        oid, _, symbolic = combined.stdout.partition("\n")
        symbolic_ref = symbolic[:-1] if symbolic.endswith("\n") else symbolic
        return (None if symbolic_ref == "HEAD" else symbolic_ref), oid.strip()

    fallback = process.run_git(
        ("symbolic-ref", "--quiet", "HEAD"),
        cwd=toplevel,
        check=False,
        git_executable=git_executable,
        timeout=timeout,
    )
    if fallback.returncode == 0:
        ref = fallback.stdout
        return (ref[:-1] if ref.endswith("\n") else ref), None

    raise GitCommandError(
        fallback.command,
        returncode=fallback.returncode,
        stdout=fallback.stdout,
        stderr=fallback.stderr,
    )
