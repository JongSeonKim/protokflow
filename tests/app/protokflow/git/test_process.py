"""Tests for the git subprocess wrapper (KTD3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.protokflow.error.git import GitBinaryMissingError, GitCommandError
from backend.app.protokflow.git import process
from tests.fixtures.git import TemporaryGitRepository


def test_missing_git_binary_raises_domain_exception(tmp_path: Path) -> None:
    """A missing git executable becomes a domain error preserving the cause."""
    with pytest.raises(GitBinaryMissingError) as excinfo:
        process.run_git(
            ("status", "--short"),
            cwd=tmp_path,
            git_executable="/nonexistent/protokflow-git",
        )
    assert isinstance(excinfo.value.__cause__, FileNotFoundError)


def test_failing_command_preserves_streams_and_status(
    git_repo: TemporaryGitRepository,
) -> None:
    """Non-zero exits raise a domain error carrying stderr and the argv."""
    with pytest.raises(GitCommandError) as excinfo:
        process.run_git(
            ("show", "definitely-not-a-ref"),
            cwd=git_repo.root,
        )
    error = excinfo.value
    assert error.returncode != 0
    assert "definitely-not-a-ref" in error.stderr
    assert "show" in error.command


def test_env_overrides_reach_the_child_and_unset_removes_variables(
    git_repo: TemporaryGitRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Inherited variables are forwarded; None values remove them."""
    monkeypatch.setenv("GIT_TRACE", "1")
    traced = process.run_git(("rev-parse", "HEAD"), cwd=git_repo.root)
    assert "trace:" in traced.stderr.lower()

    clean = process.run_git(
        ("rev-parse", "HEAD"),
        cwd=git_repo.root,
        env={"GIT_TRACE": None},
    )
    assert "trace:" not in clean.stderr.lower()
