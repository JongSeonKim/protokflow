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
