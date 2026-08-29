"""Tests for the Git subprocess execution wrapper."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from backend.app.protokflow.error.git import (
    GitBinaryMissingError,
    GitCommandError,
    GitTimeoutError,
)
from backend.app.protokflow.git import process
from tests.fixtures.git import TemporaryGitRepository


def test_missing_git_binary_raises_domain_exception(tmp_path: Path) -> None:
    """A missing git executable raises a GitBinaryMissingError preserving the underlying cause."""
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
    """Non-zero exit codes raise a GitCommandError preserving stderr, stdout, and argument vector."""
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
    """Forwarded environment variables reach the subprocess and None values remove inherited variables."""
    monkeypatch.setenv("GIT_TRACE", "1")
    traced = process.run_git(("rev-parse", "HEAD"), cwd=git_repo.root)
    assert "trace:" in traced.stderr.lower()

    clean = process.run_git(
        ("rev-parse", "HEAD"),
        cwd=git_repo.root,
        env={"GIT_TRACE": None},
    )
    assert "trace:" not in clean.stderr.lower()


def test_timeout_expiry_raises_domain_error(
    git_repo: TemporaryGitRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An expired subprocess timeout raises GitTimeoutError preserving the command and bound."""

    def expired_run(
        *args: object, **kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        raise subprocess.TimeoutExpired(cmd=args, timeout=kwargs.get("timeout"))

    monkeypatch.setattr(process.subprocess, "run", expired_run)

    with pytest.raises(GitTimeoutError) as excinfo:
        process.run_git(("status", "--short"), cwd=git_repo.root)

    assert excinfo.value.timeout == process.DEFAULT_GIT_TIMEOUT_SECONDS
    assert "status" in excinfo.value.command


def test_ambient_routing_variables_do_not_redirect_children(
    git_repo: TemporaryGitRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Inherited GIT_DIR/GIT_WORK_TREE/GIT_INDEX_FILE never redirect git children."""
    monkeypatch.setenv("GIT_DIR", str(git_repo.root / "elsewhere.git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(git_repo.root / "elsewhere"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(git_repo.root / "foreign-index"))

    result = process.run_git(
        ("rev-parse", "--path-format=absolute", "--show-toplevel"),
        cwd=git_repo.root,
    )

    assert Path(result.stdout.strip()) == git_repo.root.resolve()
