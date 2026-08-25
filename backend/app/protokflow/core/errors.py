"""Rejection errors raised while parsing or patching DESIGN.md files."""

from __future__ import annotations


class DesignMdError(ValueError):
    """Base error for DESIGN.md contract violations."""


class YamlAnchorError(DesignMdError):
    """Front matter contains a YAML anchor or alias (KTD3).

    Anchors and aliases are outside the design.md spec, and in-place patching
    would silently corrupt their reference integrity, so indexing rejects the
    whole document instead of loading a damaged state.
    """


class FencedYamlBlockError(DesignMdError):
    """Guide body contains a fenced yaml block (KTD10).

    Fenced yaml in the body is a non-normative extension; tokens must live in
    the front matter so a single serialization path owns the file.
    """


class UnterminatedFrontMatterError(DesignMdError):
    """Opening front matter fence has no matching closing fence."""


class UnknownTokenPathError(DesignMdError):
    """A patch references a token path absent from the front matter."""


class MixedLineEndingsError(DesignMdError):
    """Document mixes LF and CRLF line endings, or uses bare CR.

    One line-ending style per document is required so re-emission stays
    byte-faithful instead of silently rewriting every line.
    """


class InvalidFrontMatterError(DesignMdError):
    """Front matter is not valid YAML syntax or not a top-level mapping."""


class NonScalarTokenError(DesignMdError):
    """A token group or token leaf does not have the required scalar shape.

    Token groups must be mappings, nesting is limited to one level below the
    group, and leaves must be scalar values; anything else would be indexed
    as a lossy Python representation.
    """


class NullTokenValueError(DesignMdError):
    """A token value is an explicit YAML null or an empty value.

    Null is not a meaningful design token value and cannot be distinguished
    from an empty string after normalization, so it is rejected up front.
    """


class DottedTokenNameError(DesignMdError):
    """A token name contains a dot.

    Dots are reserved for the flattened token path notation; a dotted YAML
    key would produce a path that can never be patched.
    """
