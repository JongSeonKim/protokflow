"""Tests for Git checkout observation (U1 context adapter, R26)."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.protokflow.core import identity
from backend.app.protokflow.error.git import GitError, GitWorktreeInvalidError
from backend.app.protokflow.git import context
from tests.fixtures.git import DEFAULT_BRANCH, TemporaryGitRepository


def test_attached_head_returns_full_symbolic_ref_and_oid(
    git_repo: TemporaryGitRepository,
) -> None:
    """Attached HEAD observation exposes the full ref and commit OID."""
    observation = context.observe_checkout(git_repo.root)
    assert observation.detached is False
    assert observation.symbolic_ref == f"refs/heads/{DEFAULT_BRANCH}"
    assert observation.head_oid == git_repo.head_oid()


def test_detached_head_reports_unsupported_state(
    git_repo: TemporaryGitRepository,
) -> None:
    """Detached HEAD is explicit and carries no checkout identity (R26)."""
    git_repo.detach()
    observation = context.observe_checkout(git_repo.root)
    assert observation.detached is True
    assert observation.symbolic_ref is None
    assert observation.head_oid == git_repo.head_oid()


def test_linked_worktree_splits_common_and_worktree_git_dirs(
    git_repo: TemporaryGitRepository,
) -> None:
    """Linked worktrees share the common dir but keep distinct identities."""
    sibling = git_repo.add_worktree("sibling")
    main = context.observe_checkout(git_repo.root)
    other = context.observe_checkout(sibling.root)

    assert main.git_common_dir == other.git_common_dir
    assert main.git_dir != other.git_dir
    assert main.repository_id == other.repository_id
    assert main.worktree_id != other.worktree_id

    # The bundled identities match independent pure-core computation (R25).
    assert main.worktree_id == identity.worktree_id(main.worktree_root)
    assert main.repository_id == identity.repository_id(main.git_common_dir)


def test_unborn_head_observes_symbolic_ref_without_oid(tmp_path: Path) -> None:
    """A repository without commits has a ref identity but no HEAD OID."""
    repo = TemporaryGitRepository.init(tmp_path / "unborn", with_initial_commit=False)
    observation = context.observe_checkout(repo.root)
    assert observation.detached is False
    assert observation.symbolic_ref == f"refs/heads/{DEFAULT_BRANCH}"
    assert observation.head_oid is None


def test_invalid_repository_directory_is_rejected(tmp_path: Path) -> None:
    """Observation outside a Git worktree raises the domain exception."""
    plain = tmp_path / "not-a-repo"
    plain.mkdir()
    with pytest.raises(GitWorktreeInvalidError) as excinfo:
        context.observe_checkout(plain)
    assert isinstance(excinfo.value, GitError)
    assert excinfo.value.__cause__ is not None
