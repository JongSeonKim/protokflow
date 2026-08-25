"""Exception classes for design-system storage-layer invariants."""

from __future__ import annotations


class StorageLayerError(ValueError):
    """Base exception for storage-layer invariant violations."""


class UnknownDesignSystemError(StorageLayerError):
    """Raised when an operation names a design system slug that is not indexed."""


class UnbackedDesignSystemError(StorageLayerError):
    """Raised when an operation requires a source DESIGN.md file the system does not have."""


class MissingSourceFileError(StorageLayerError):
    """Raised when a design system's linked DESIGN.md file no longer exists."""


class TokenReparentingError(StorageLayerError):
    """Raised when token replacement would silently reparent tokens across systems."""


class ConcurrentModificationError(StorageLayerError):
    """Raised when a design system's source file was modified concurrently or externally."""


class UnsupportedSourceLinkError(StorageLayerError):
    """Raised when a DESIGN.md source is a symlink or hard link.

    Atomic file replacement via rename modifies directory entries directly,
    which would replace symlinks with regular files or break hard links.
    """


class SourceWriteError(StorageLayerError):
    """Raised when a disk failure prevents the atomic write of a DESIGN.md source.

    The original OSError is preserved as __cause__ so callers can inspect the
    underlying errno while adapters only need to catch StorageLayerError.
    """


class SourceRootMismatchError(StorageLayerError):
    """Raised when a patch targets a repository root other than the indexed one.

    source_path is relative to the repository root recorded at index time;
    resolving it against a different root would read and patch an unrelated
    file. Re-index against the current root to rebind the system.
    """
