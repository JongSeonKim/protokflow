"""Deterministic, database-independent path identity.

Derives stable repository_id and worktree_id values from normalized
filesystem paths so clients can compute identical identifiers locally
without contacting the server. Pure Python implementation with no
database or framework dependencies.
"""

from __future__ import annotations

import hashlib
import os
import unicodedata
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


def _is_case_insensitive(directory: Path) -> bool:
    """Probe whether the host filesystem treats case-variant paths as identical."""
    swapped = directory.name.swapcase()
    if swapped == directory.name:
        return False
    probe = directory.with_name(swapped)
    try:
        return probe.exists() and os.path.samefile(probe, directory)
    except OSError:
        return False
