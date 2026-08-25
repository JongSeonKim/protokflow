"""DESIGN.md front matter codec with lossless in-place patching.

Parses a DESIGN.md document (YAML front matter and Markdown guide) into the
normalized token format used by the storage layer, and re-emits files by
patching the original front matter in-place so comments, blank lines,
quoting styles, and key order are preserved across token updates.
"""

from __future__ import annotations

import io
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.error import YAMLError
from ruamel.yaml.events import AliasEvent
from ruamel.yaml.scalarstring import DoubleQuotedScalarString, SingleQuotedScalarString

from backend.app.protokflow.core.errors import (
    DottedTokenNameError,
    FencedYamlBlockError,
    InvalidFrontMatterError,
    MixedLineEndingsError,
    NonScalarTokenError,
    NullTokenValueError,
    UnknownTokenPathError,
    UnterminatedFrontMatterError,
    YamlAnchorError,
)

FOUNDATION_GROUPS = ("colors", "typography", "rounded", "spacing")
COMPONENT_GROUP = "components"
MODELED_SCALARS = ("version", "name", "description")
FENCE = "---"

_BACKTICK_RUN = chr(96) + "{3,}"
_FENCED_YAML_RE = re.compile(
    r"^ {0,3}(?:" + _BACKTICK_RUN + r"|~{3,})[ \t]*(?:yaml|yml)(?:[ \t]|$)",
    re.IGNORECASE,
)
_QUOTED_STYLES = (SingleQuotedScalarString, DoubleQuotedScalarString)


@dataclass(frozen=True, slots=True)
class TokenRow:
    """A normalized design token row representation."""

    tier: str  # 'foundation' | 'component'
    token_path: (
        str  # Dot-delimited path, e.g. 'colors.primary', 'typography.body-md.fontSize'
    )
    value: str  # Normalized token value stored as string text


@dataclass(slots=True)
class ParsedDesignSystem:
    """Parsed representation and metadata of a DESIGN.md document."""

    front_matter_raw: str | None  # Raw YAML front matter text, or None if omitted
    closing_fence: str  # Exact closing fence line including its trailing line ending
    guide_markdown: str  # Verbatim Markdown guide content following the closing fence
    eol: str  # Detected document line ending ('\n' or '\r\n')
    title: str | None  # Design system name from front matter ('name')
    description: str | None  # Design system description from front matter
    spec_version: str | None  # Specification version from front matter ('version')
    front_matter_extras: dict[str, Any] = field(default_factory=dict)
    tokens: list[TokenRow] = field(default_factory=list)


def _yaml() -> YAML:
    """Configure a round-trip YAML parser preserving quotes and indentation."""
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.width = 4096  # Prevent automatic line wrapping of long scalar values
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


@dataclass(frozen=True, slots=True)
class FrontMatterSplit:
    """Envelope components extracted from a DESIGN.md document."""

    front_matter_raw: (
        str | None
    )  # Raw front matter text, or None if no front matter block exists
    closing_fence: str  # Closing fence line including its line ending
    guide_markdown: str  # Markdown body following the front matter block
    eol: str  # Document line ending ('\n' or '\r\n')


def _reject_mixed_line_endings(text: str) -> None:
    """Validate that the document uses consistent LF or CRLF line endings throughout."""
    saw_lf = False
    saw_crlf = False
    for line in text.splitlines(keepends=True):
        if line.endswith("\r\n"):
            saw_crlf = True
        elif line.endswith("\n"):
            saw_lf = True
        elif line.endswith("\r"):
            raise MixedLineEndingsError(
                "bare CR line endings are not supported; use LF or CRLF throughout"
            )
    if saw_lf and saw_crlf:
        raise MixedLineEndingsError(
            "document mixes LF and CRLF line endings; use one style throughout"
        )


def split_front_matter(text: str) -> FrontMatterSplit:
    """Split a document into front matter and guide markdown components without altering content."""
    _reject_mixed_line_endings(text)
    eol = "\r\n" if "\r\n" in text else "\n"
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != FENCE:
        return FrontMatterSplit(None, "", text, eol)
    for index in range(1, len(lines)):
        if lines[index].rstrip("\r\n") == FENCE:
            return FrontMatterSplit(
                front_matter_raw="".join(lines[1:index]),
                closing_fence=lines[index],
                guide_markdown="".join(lines[index + 1 :]),
                eol=eol,
            )
    raise UnterminatedFrontMatterError(
        "opening '---' front matter fence has no closing '---'"
    )


def _load_front_matter(raw: str) -> CommentedMap:
    """Parse raw front matter YAML into a round-trip CommentedMap structure."""
    if not raw.strip():
        return CommentedMap()
    # Normalize CRLF to LF before loading: ruamel.yaml round-trip dump can drop
    # blank lines when parsing CRLF. Raw text is preserved separately.
    try:
        loaded = _yaml().load(io.StringIO(raw.replace("\r\n", "\n")))
    except YAMLError as exc:
        raise InvalidFrontMatterError(f"front matter is not valid YAML: {exc}") from exc
    if loaded is None:
        return CommentedMap()
    if not isinstance(loaded, CommentedMap):
        raise InvalidFrontMatterError(
            "front matter must be a YAML mapping of top-level keys"
        )
    return loaded


def _reject_fenced_yaml_blocks(guide_markdown: str) -> None:
    """Ensure no fenced YAML blocks exist in the Markdown guide body."""
    for line in guide_markdown.splitlines():
        if _FENCED_YAML_RE.match(line):
            raise FencedYamlBlockError(
                "fenced yaml block in the guide body is not a token source; "
                "move those tokens into the front matter"
            )


def _reject_anchors(front_matter_raw: str) -> None:
    """Reject YAML anchors and aliases by scanning the raw event stream.

    Parsing at the event stream level ensures anchors on mapping keys and null
    scalars are detected before alias resolution hides them in the parsed tree.
    """
    try:
        for event in _yaml().parse(io.StringIO(front_matter_raw)):
            anchor = getattr(event, "anchor", None)
            if anchor:
                sigil = "*" if isinstance(event, AliasEvent) else "&"
                raise YamlAnchorError(
                    f"front matter must not use YAML anchors or aliases "
                    f"(found '{sigil}{anchor}'); replace them with design.md "
                    f"reference syntax such as {{colors.primary}} so in-place "
                    f"patching keeps references sound"
                )
    except YAMLError as exc:
        raise InvalidFrontMatterError(f"front matter is not valid YAML: {exc}") from exc


def _scalar_text(node: Any) -> str:
    """Convert scalar YAML values to canonical string representations."""
    if isinstance(node, bool):
        return "true" if node else "false"
    return str(node)


def _reject_dotted_token_name(token_path: str, name: Any) -> None:
    """Validate that token keys do not contain dots, which are reserved for path nesting."""
    if "." in str(name):
        raise DottedTokenNameError(
            f"token names must not contain dots (found '{token_path}'); "
            f"dots are reserved for the flattened token path notation"
        )


def _flatten(group_name: str, group: Any, tier: str) -> list[TokenRow]:
    """Flatten a token group mapping into a list of normalized TokenRow objects."""
    if not isinstance(group, dict):
        raise NonScalarTokenError(
            f"token group '{group_name}' must be a mapping of token names to values"
        )
    rows: list[TokenRow] = []
    for name, node in group.items():
        _reject_dotted_token_name(f"{group_name}.{name}", name)
        if isinstance(node, dict):
            for prop, leaf in node.items():
                token_path = f"{group_name}.{name}.{prop}"
                _reject_dotted_token_name(token_path, prop)
                if isinstance(leaf, (dict, list)):
                    raise NonScalarTokenError(
                        f"token '{token_path}' must be a scalar value"
                    )
                if leaf is None:
                    raise NullTokenValueError(
                        f"token '{token_path}' must not be null or empty"
                    )
                rows.append(
                    TokenRow(
                        tier=tier,
                        token_path=token_path,
                        value=_scalar_text(leaf),
                    )
                )
        elif isinstance(node, list):
            raise NonScalarTokenError(
                f"token '{group_name}.{name}' must be a scalar value"
            )
        elif node is None:
            raise NullTokenValueError(
                f"token '{group_name}.{name}' must not be null or empty"
            )
        else:
            rows.append(
                TokenRow(
                    tier=tier,
                    token_path=f"{group_name}.{name}",
                    value=_scalar_text(node),
                )
            )
    return rows


def _flatten_tokens(front_matter: CommentedMap) -> list[TokenRow]:
    """Extract and flatten all foundation and component token groups from front matter."""
    rows: list[TokenRow] = []
    for group_name in FOUNDATION_GROUPS:
        if group_name in front_matter:
            rows += _flatten(group_name, front_matter[group_name], "foundation")
    if COMPONENT_GROUP in front_matter:
        rows += _flatten(COMPONENT_GROUP, front_matter[COMPONENT_GROUP], "component")
    return rows


def _optional_text(front_matter: CommentedMap, key: str) -> str | None:
    """Safely retrieve an optional text value from front matter mapping."""
    value = front_matter.get(key)
    return None if value is None else str(value)


def _json_safe_extras(value: Any) -> Any:
    """Convert front matter extras into values supported by JSON serialization."""
    if isinstance(value, dict):
        return {str(key): _json_safe_extras(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe_extras(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def parse_design_md(text: str) -> ParsedDesignSystem:
    """Parse a DESIGN.md document into normalized token rows and metadata."""
    split = split_front_matter(text)
    _reject_fenced_yaml_blocks(split.guide_markdown)
    if split.front_matter_raw and split.front_matter_raw.strip():
        _reject_anchors(split.front_matter_raw)
    front_matter = _load_front_matter(split.front_matter_raw or "")

    tokens = _flatten_tokens(front_matter)

    known = set(FOUNDATION_GROUPS) | {COMPONENT_GROUP} | set(MODELED_SCALARS)
    extras = _json_safe_extras(
        {key: value for key, value in front_matter.items() if key not in known}
    )

    return ParsedDesignSystem(
        front_matter_raw=split.front_matter_raw,
        closing_fence=split.closing_fence,
        guide_markdown=split.guide_markdown,
        eol=split.eol,
        title=_optional_text(front_matter, "name"),
        description=_optional_text(front_matter, "description"),
        spec_version=_optional_text(front_matter, "version"),
        front_matter_extras=extras,
        tokens=tokens,
    )


def _set_token(front_matter: CommentedMap, token_path: str, value: str) -> None:
    """Update a single token in the CommentedMap tree while preserving original quoting style."""
    parts = token_path.split(".")
    cursor: Any = front_matter
    for part in parts[:-1]:
        cursor = cursor[part]
    leaf = parts[-1]
    previous = cursor[leaf]
    if isinstance(previous, _QUOTED_STYLES):
        cursor[leaf] = type(previous)(value)
    else:
        cursor[leaf] = _plain_yaml_scalar(value)


def _plain_yaml_scalar(value: str) -> Any:
    """Convert unquoted string token values into native Python types for YAML serialization.

    Converts boolean and numeric strings back to native Python bool/int/float types
    so ruamel.yaml emits them as unquoted scalars rather than quoted strings.
    """
    if value in ("true", "false"):
        return value == "true"
    try:
        as_int = int(value)
    except ValueError:
        as_int = None
    if as_int is not None and str(as_int) == value:
        return as_int
    try:
        as_float = float(value)
    except ValueError:
        return value
    if repr(as_float) == value:
        return as_float
    return value


def serialize_design_md(
    *,
    front_matter_raw: str | None,
    closing_fence: str,
    guide_markdown: str,
    eol: str,
    token_patches: Mapping[str, str] | None = None,
) -> str:
    """Re-serialize a DESIGN.md document, applying in-place patches to specified token paths."""
    if eol not in ("\n", "\r\n"):
        raise MixedLineEndingsError("line ending must be LF or CRLF")
    patches = token_patches or {}
    _reject_fenced_yaml_blocks(guide_markdown)
    if front_matter_raw is not None and front_matter_raw.strip():
        _reject_anchors(front_matter_raw)
    if front_matter_raw is None:
        if patches:
            raise UnknownTokenPathError(
                f"token path not in front matter: {next(iter(patches))}"
            )
        output = guide_markdown
    else:
        front_matter = _load_front_matter(front_matter_raw)
        valid_paths = {row.token_path for row in _flatten_tokens(front_matter)}
        for token_path in patches:
            if token_path not in valid_paths:
                raise UnknownTokenPathError(
                    f"token path not in front matter: {token_path}"
                )
        for token_path, value in patches.items():
            _set_token(front_matter, token_path, value)
        if patches:
            buffer = io.StringIO()
            _yaml().dump(front_matter, buffer)
            dumped = buffer.getvalue()
            if eol == "\r\n":
                dumped = dumped.replace("\n", "\r\n")
        else:
            # If no patches were applied, re-emit the original front matter verbatim.
            dumped = front_matter_raw
        output = f"{FENCE}{eol}{dumped}{closing_fence}{guide_markdown}"
    _reject_mixed_line_endings(output)
    return output
