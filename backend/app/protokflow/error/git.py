"""Exception hierarchy for Git adapter subprocess execution and plumbing failures."""

from __future__ import annotations

import shlex
from collections.abc import Sequence


class GitError(ValueError):
    """Base exception for all Git adapter failures."""


class GitBinaryMissingError(GitError):
    """Raised when the git executable cannot be located or executed.

    Preserves the underlying OSError as __cause__ so callers can inspect
    specific operating system error codes while catching GitError.
    """


class GitCommandError(GitError):
    """Raised when a git subprocess terminates with a non-zero exit code.

    Preserves the argument vector, exit code, and captured stdout/stderr streams
    so callers can diagnose failures or differentiate retryable conflicts.
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


class GitTimeoutError(GitError):
    """Raised when a git subprocess exceeds its allowed wall-clock time.

    Preserves the argument vector and the configured timeout so callers can
    log the stalled command or retry with a larger bound.
    """

    def __init__(self, command: Sequence[str], *, timeout: float) -> None:
        self.command = tuple(command)
        self.timeout = timeout
        super().__init__(
            "git " + shlex.join(self.command) + f" timed out after {timeout} seconds"
        )


class GitWorktreeInvalidError(GitError):
    """Raised when the target directory is not a valid or accessible Git working tree."""
