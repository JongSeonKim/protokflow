"""Subprocess execution wrapper for the Git command-line interface.

Centralizes all Git CLI interactions. Builds a sanitized child environment that
strips inherited repository, index, object, config, and discovery routing
variables, so a parent process launched inside another repository cannot
redirect child writes or reads. Sets GIT_OPTIONAL_LOCKS=0 to prevent read-only
observation commands from acquiring index locks or unintentionally refreshing
filesystem stat caches, and pins LC_ALL=C so git output stays locale-stable.
Explicit per-call entries layered on top of the sanitized base always win.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from backend.app.protokflow.error.git import (
    GitBinaryMissingError,
    GitCommandError,
    GitTimeoutError,
)

DEFAULT_GIT_EXECUTABLE = "git"
DEFAULT_GIT_TIMEOUT_SECONDS: float = 60.0

# Repository, index, object, config, and discovery controls whose ambient
# values would redirect git children away from the requested repository.
_SANITIZED_ENV_KEYS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_NAMESPACE",
    "GIT_CONFIG_GLOBAL",
    "GIT_CONFIG_SYSTEM",
    "GIT_CONFIG_COUNT",
    "GIT_CEILING_DIRECTORIES",
    "GIT_DISCOVERY_ACROSS_FILESYSTEM",
)


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
    timeout: float | None = DEFAULT_GIT_TIMEOUT_SECONDS,
) -> GitCommandResult:
    """Run git with captured streams and a controlled environment.

    Environment entries override (or, when None, remove) variables inherited
    from the parent process and always win over the sanitized base, so
    GIT_INDEX_FILE=None restores the repository's real index despite an
    inherited override. Streams are decoded as UTF-8 with replacement so
    malformed bytes never abort observation. A timeout in seconds bounds each
    invocation and an expiry raises GitTimeoutError, so a stalled network or
    FUSE mount cannot pin the calling thread forever.
    """
    command = (git_executable, *(str(argument) for argument in args))
    child_env = os.environ.copy()
    for key in _SANITIZED_ENV_KEYS:
        child_env.pop(key, None)
    child_env["GIT_OPTIONAL_LOCKS"] = "0"
    child_env["LC_ALL"] = "C"
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
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitTimeoutError(command, timeout=exc.timeout or 0.0) from exc
    except FileNotFoundError as exc:
        # Re-raise FileNotFoundError when the working directory does not exist,
        # distinguishing an invalid target path from a missing git executable.
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
