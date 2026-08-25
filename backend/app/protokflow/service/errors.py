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
