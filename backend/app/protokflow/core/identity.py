"""Deterministic, database-independent path identity.

Derives stable repository_id and worktree_id values from normalized
filesystem paths so clients can compute identical identifiers locally
without contacting the server. Pure Python implementation with no
database or framework dependencies.
"""

from __future__ import annotations

import functools
import hashlib
import os
import unicodedata
import uuid
from pathlib import Path

WORKTREE_ID_DOMAIN = b"protokflow:worktree\x00"
REPOSITORY_ID_DOMAIN = b"protokflow:repository\x00"


def normalize_path(
    path: str | os.PathLike[str],
    *,
    case_insensitive: bool | None = None,
) -> str:
    """Resolve symlinks and normalize a path into its canonical textual form.

    Resolves symbolic links, applies Unicode NFC normalization, and folds
    case on case-insensitive filesystems. Passing None dynamically probes
    the host filesystem for case sensitivity.
    """
    resolved = Path(path).resolve()
    normalized = unicodedata.normalize("NFC", str(resolved))
    insensitive = (
        _is_case_insensitive(resolved) if case_insensitive is None else case_insensitive
    )

    return normalized.casefold() if insensitive else normalized


def worktree_id(
    path: str | os.PathLike[str],
    *,
    case_insensitive: bool | None = None,
) -> str:
    """Return the stable SHA-256 identifier for a Git worktree root path."""
    return _stable_id(WORKTREE_ID_DOMAIN, path, case_insensitive=case_insensitive)


def repository_id(
    path: str | os.PathLike[str],
    *,
    case_insensitive: bool | None = None,
) -> str:
    """Return the stable SHA-256 identifier for a Git common directory path."""
    return _stable_id(REPOSITORY_ID_DOMAIN, path, case_insensitive=case_insensitive)


def _stable_id(
    domain: bytes,
    path: str | os.PathLike[str],
    *,
    case_insensitive: bool | None,
) -> str:
    serialized = domain + normalize_path(
        path, case_insensitive=case_insensitive
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


@functools.cache
def _is_case_insensitive(directory: Path) -> bool:
    """Probe whether the filesystem treats case as insignificant.

    Creates a uniquely named hidden marker plus its swapcase marker inside the
    directory, so the probe can never collide with a pre-existing alias and
    never depends on the directory's own name containing cased characters.
    Both markers are removed before returning; the result is cached because a
    filesystem's case behavior does not change during a process.
    """
    marker = directory / f".case-probe-{uuid.uuid4().hex}"
    case_swap_marker = marker.with_name(marker.name.swapcase())

    try:
        try:
            marker.touch()
            case_swap_marker.touch(exist_ok=False)
        except FileExistsError:
            return True
        except OSError:
            return False
        return False
    finally:
        try:
            marker.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            case_swap_marker.unlink(missing_ok=True)
        except OSError:
            pass
