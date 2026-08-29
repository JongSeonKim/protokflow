"""Subprocess wrapper around the git binary (KTD3).

All Git observation and plumbing flows through run_git. Observation commands
must not refresh or lock the index as a side effect, so every child process
runs with GIT_OPTIONAL_LOCKS=0 regardless of the command mode.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from backend.app.protokflow.error.git import GitBinaryMissingError, GitCommandError

DEFAULT_GIT_EXECUTABLE = "git"


@dataclass(frozen=True, slots=True)
class GitCommandResult:
    """Captured result of a single git subprocess invocation."""

    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


def run_git(
    args: Sequence[str],
    *,
    cwd: str | os.PathLike[str],
    env: Mapping[str, str | None] | None = None,
    input_bytes: bytes | None = None,
    check: bool = True,
    git_executable: str = DEFAULT_GIT_EXECUTABLE,
) -> GitCommandResult:
    """Run git with captured streams and a controlled environment.

    Environment entries override (or, when None, remove) variables inherited
    from the parent process, so GIT_INDEX_FILE=None restores the repository's
    real index despite an inherited override. Streams are decoded as UTF-8
    with replacement so malformed bytes never abort observation.
    """
    command = (git_executable, *(str(argument) for argument in args))
    child_env = os.environ.copy()
    child_env["GIT_OPTIONAL_LOCKS"] = "0"
    for key, value in (env or {}).items():
        if value is None:
            child_env.pop(key, None)
        else:
            child_env[key] = value
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=child_env,
            input=input_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except FileNotFoundError as exc:
        # A missing working directory is a caller contract violation, not a
        # missing binary; surface it unchanged for the caller to classify.
        if not Path(cwd).exists():
            raise
        raise GitBinaryMissingError(
            f"git executable not found: {git_executable!r}"
        ) from exc
    result = GitCommandResult(
        command=command,
        returncode=completed.returncode,
        stdout=completed.stdout.decode("utf-8", errors="replace"),
        stderr=completed.stderr.decode("utf-8", errors="replace"),
    )
    if check and result.returncode != 0:
        raise GitCommandError(
            command,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
    return result
