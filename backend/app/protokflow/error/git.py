"""Exception classes for Git adapter subprocess and plumbing failures."""

from __future__ import annotations

import shlex
from collections.abc import Sequence


class GitError(ValueError):
    """Base exception for Git adapter failures."""


class GitBinaryMissingError(GitError):
    """Raised when the git executable cannot be found or executed.

    The original OSError is preserved as __cause__ so callers can inspect
    the underlying errno while higher layers only catch GitError.
    """


class GitCommandError(GitError):
    """Raised when a git subprocess exits with a non-zero status.

    Preserves the exact argument vector, exit status, and captured streams
    so callers can distinguish retryable concurrency conflicts from
    permanent command failures.
    """

    def __init__(
        self,
        command: Sequence[str],
        *,
        returncode: int,
        stdout: str,
        stderr: str,
    ) -> None:
        self.command = tuple(command)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        detail = stderr.strip() or "no stderr output"
        super().__init__(
            "git " + shlex.join(self.command) + " failed with exit code "
            f"{returncode}: {detail}"
        )


class GitWorktreeInvalidError(GitError):
    """Raised when the target directory is not a usable Git working tree."""
