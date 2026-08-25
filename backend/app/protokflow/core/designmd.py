"""DESIGN.md front matter codec with byte-faithful in-place patching.

Parses a DESIGN.md file (YAML front matter + Markdown guide) into the
normalized token shape used by the storage layer, and re-emits files by
patching the preserved original front matter so comments, blank lines,
quoting styles, and key order survive token edits (R16, KTD1).
"""

from __future__ import annotations

import io
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.events import AliasEvent
from ruamel.yaml.error import YAMLError
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
    """One normalized design_tokens-shaped token."""

    tier: str  # 'foundation' | 'component'
    token_path: str  # e.g. colors.primary, typography.body-md.fontSize
    value: str  # the storage layer's column is text (KTD4)


@dataclass(slots=True)
class ParsedDesignSystem:
    """Everything the storage layer needs from one DESIGN.md file."""

    front_matter_raw: str | None  # None = no front matter block
    closing_fence: str  # exact closing fence line including its line ending
    guide_markdown: str  # verbatim body after the closing fence
    eol: str  # document line ending: "\n" or "\r\n"
    title: str | None  # front matter 'name'
    description: str | None
    spec_version: str | None  # front matter 'version'
    front_matter_extras: dict[str, Any] = field(default_factory=dict)
    tokens: list[TokenRow] = field(default_factory=list)


def _yaml() -> YAML:
    yaml = YAML(typ="rt")
    yaml.preserve_quotes = True
    yaml.width = 4096  # never re-wrap a long scalar
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


@dataclass(frozen=True, slots=True)
class FrontMatterSplit:
    """Verbatim envelope pieces of a split DESIGN.md document."""

    front_matter_raw: str | None  # None = no front matter block
    closing_fence: str
    guide_markdown: str
    eol: str


def _reject_mixed_line_endings(text: str) -> None:
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
    """Split a document into verbatim envelope pieces; fences are excluded."""
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
    if not raw.strip():
        return CommentedMap()
    # Normalize CRLF before loading: ruamel's round-trip dump drops some
    # EOL blank lines when the input uses CRLF. The raw text is preserved
    # separately, so this only affects the in-memory tree.
    loaded = _yaml().load(io.StringIO(raw.replace("\r\n", "\n")))
    if loaded is None:
        return CommentedMap()
    if not isinstance(loaded, CommentedMap):
        raise ValueError("front matter must be a YAML mapping of top-level keys")
    return loaded


def _reject_fenced_yaml_blocks(guide_markdown: str) -> None:
    for line in guide_markdown.splitlines():
        if _FENCED_YAML_RE.match(line):
            raise FencedYamlBlockError(
                "fenced yaml block in the guide body is not a token source; "
                "move those tokens into the front matter (KTD10)"
            )


def _reject_anchors(front_matter_raw: str) -> None:
    """Reject anchors and aliases on the YAML event stream.

    The composed tree loses anchors on mapping keys and on null scalars, so
    the gate runs on events where every anchored node and alias is still
    visible, before alias resolution can hide them.
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
                    f"patching keeps references sound (KTD3)"
                )
    except YAMLError as exc:
        raise InvalidFrontMatterError(f"front matter is not valid YAML: {exc}") from exc


def _scalar_text(node: Any) -> str:
    if isinstance(node, bool):
        return "true" if node else "false"
    return str(node)


def _reject_dotted_token_name(token_path: str, name: Any) -> None:
    if "." in str(name):
        raise DottedTokenNameError(
            f"token names must not contain dots (found '{token_path}'); "
            f"dots are reserved for the flattened token path notation"
        )


def _flatten(group_name: str, group: Any, tier: str) -> list[TokenRow]:
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
    rows: list[TokenRow] = []
    for group_name in FOUNDATION_GROUPS:
        if group_name in front_matter:
            rows += _flatten(group_name, front_matter[group_name], "foundation")
    if COMPONENT_GROUP in front_matter:
        rows += _flatten(COMPONENT_GROUP, front_matter[COMPONENT_GROUP], "component")
    return rows


def _optional_text(front_matter: CommentedMap, key: str) -> str | None:
    value = front_matter.get(key)
    return None if value is None else str(value)


def parse_design_md(text: str) -> ParsedDesignSystem:
    """Parse a DESIGN.md file, rejecting anchors and fenced yaml blocks."""
    split = split_front_matter(text)
    _reject_fenced_yaml_blocks(split.guide_markdown)
    if split.front_matter_raw and split.front_matter_raw.strip():
        _reject_anchors(split.front_matter_raw)
    front_matter = _load_front_matter(split.front_matter_raw or "")

    tokens = _flatten_tokens(front_matter)

    known = set(FOUNDATION_GROUPS) | {COMPONENT_GROUP} | set(MODELED_SCALARS)
    extras = {key: value for key, value in front_matter.items() if key not in known}

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
    """Set one token in the live tree, keeping the leaf's quoting style."""
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
    """Re-resolve a plain token value the way YAML would parse it.

    A plain target emitted as a Python string would come back quoted (ruamel
    preserves str-ness), so numeric and boolean patch values are converted to
    their native scalars and stay bare in the file. Non-canonical forms fall
    back to the string and let ruamel decide whether quoting is required.
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
    """Re-emit a DESIGN.md file, patching only the requested token paths."""
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
            # An unedited document re-emits its preserved front matter verbatim.
            dumped = front_matter_raw
        output = f"{FENCE}{eol}{dumped}{closing_fence}{guide_markdown}"
    _reject_mixed_line_endings(output)
    return output
