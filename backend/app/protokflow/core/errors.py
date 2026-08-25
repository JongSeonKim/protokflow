"""Exception classes for DESIGN.md document handling and storage-layer invariants."""

from __future__ import annotations


class DesignMdError(ValueError):
    """Base exception for DESIGN.md format and specification violations."""


class YamlAnchorError(DesignMdError):
    """Raised when front matter contains YAML anchors or aliases.

    YAML anchors and aliases are not supported in the DESIGN.md specification
    because in-place token patching cannot guarantee reference integrity.
    Use standard token reference syntax (e.g. '{colors.primary}') instead.
    """


class FencedYamlBlockError(DesignMdError):
    """Raised when the Markdown guide body contains a fenced YAML block.

    Token definitions must reside in the YAML front matter block rather than
    fenced code blocks within the guide body.
    """


class DuplicateSlugError(DesignMdError):
    """Raised when discovery yields multiple files claiming the same slug.

    This includes the root DESIGN.md and design/default.md claiming the
    default slug. Resolve the collision by renaming the sibling file or
    removing one of the duplicates.
    """


class InvalidEncodingError(DesignMdError):
    """Raised when a DESIGN.md file is not valid UTF-8 text."""


class UnterminatedFrontMatterError(DesignMdError):
    """Raised when an opening front matter fence ('---') lacks a matching closing fence."""


class UnknownTokenPathError(DesignMdError):
    """Raised when a patch targets a token path that does not exist in the front matter."""


class MixedLineEndingsError(DesignMdError):
    """Raised when a document contains inconsistent line endings or bare CR characters.

    A uniform line-ending style (LF or CRLF) is required to ensure lossless,
    byte-faithful serialization.
    """


class InvalidFrontMatterError(DesignMdError):
    """Raised when front matter contains invalid YAML syntax or is not a top-level mapping."""


class NonScalarTokenError(DesignMdError):
    """Raised when a token group or token leaf does not conform to the expected schema.

    Token groups must be mappings with at most one level of sub-group nesting,
    and all token leaves must be scalar values (strings, numbers, or booleans).
    """


class NullTokenValueError(DesignMdError):
    """Raised when a token value is an explicit YAML null or empty.

    Design tokens must have non-null, non-empty scalar values.
    """


class DottedTokenNameError(DesignMdError):
    """Raised when a token key contains a period character.

    Periods are reserved as delimiters for flattened token paths (e.g. 'colors.primary')
    and cannot be used inside individual key names.
    """


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
