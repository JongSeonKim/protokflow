"""Exception classes for DESIGN.md format and specification violations."""

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
