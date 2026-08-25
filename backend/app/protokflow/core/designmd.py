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
from ruamel.yaml.scalarstring import (
    DoubleQuotedScalarString,
    SingleQuotedScalarString,
)

from backend.app.protokflow.core.errors import (
    FencedYamlBlockError,
    UnknownTokenPathError,
    UnterminatedFrontMatterError,
    YamlAnchorError,
)

FOUNDATION_GROUPS = ("colors", "typography", "rounded", "spacing")
COMPONENT_GROUP = "components"
MODELED_SCALARS = ("version", "name", "description")
FENCE = "---"

_MARKDOWN_FENCE = chr(96) * 3
_FENCED_YAML_RE = re.compile(
    r"^ {0,3}" + _MARKDOWN_FENCE + r"[ \t]*(?:yaml|yml)(?:[ \t]|$)",
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

    front_matter_raw: str  # verbatim text between the fences
    guide_markdown: str  # verbatim body after the closing fence
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


def split_front_matter(text: str) -> tuple[str, str]:
    """Return (front_matter_raw, guide_markdown); fences are excluded."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != FENCE:
        return "", text
    for index in range(1, len(lines)):
        if lines[index].rstrip("\r\n") == FENCE:
            return "".join(lines[1:index]), "".join(lines[index + 1 :])
    raise UnterminatedFrontMatterError(
        "opening '---' front matter fence has no closing '---'"
    )


def _load_front_matter(raw: str) -> CommentedMap:
    if not raw.strip():
        return CommentedMap()
    loaded = _yaml().load(io.StringIO(raw))
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


def _reject_anchors(node: Any) -> None:
    anchor = getattr(node, "yaml_anchor", None)
    if callable(anchor):
        found = anchor()
        name = getattr(found, "value", None)
        if name:
            raise YamlAnchorError(
                f"front matter must not use YAML anchors or aliases "
                f"(found '&{name}'); replace them with design.md reference "
                f"syntax such as {{colors.primary}} so in-place patching "
                f"keeps references sound (KTD3)"
            )
    if isinstance(node, dict):
        for child in node.values():
            _reject_anchors(child)
    elif isinstance(node, list):
        for child in node:
            _reject_anchors(child)


def _scalar_text(node: Any) -> str:
    if isinstance(node, bool):
        return "true" if node else "false"
    if node is None:
        return ""
    return str(node)


def _flatten(group_name: str, group: Any, tier: str) -> list[TokenRow]:
    rows: list[TokenRow] = []
    if not isinstance(group, dict):
        return rows
    for name, node in group.items():
        if isinstance(node, dict):
            for prop, leaf in node.items():
                rows.append(
                    TokenRow(
                        tier=tier,
                        token_path=f"{group_name}.{name}.{prop}",
                        value=_scalar_text(leaf),
                    )
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


def _optional_text(front_matter: CommentedMap, key: str) -> str | None:
    if key not in front_matter or front_matter[key] is None:
        return None
    return str(front_matter[key])


def parse_design_md(text: str) -> ParsedDesignSystem:
    """Parse a DESIGN.md file, rejecting anchors and fenced yaml blocks."""
    front_matter_raw, guide_markdown = split_front_matter(text)
    _reject_fenced_yaml_blocks(guide_markdown)
    front_matter = _load_front_matter(front_matter_raw)
    _reject_anchors(front_matter)

    tokens: list[TokenRow] = []
    for group_name in FOUNDATION_GROUPS:
        if group_name in front_matter:
            tokens += _flatten(group_name, front_matter[group_name], "foundation")
    if COMPONENT_GROUP in front_matter:
        tokens += _flatten(COMPONENT_GROUP, front_matter[COMPONENT_GROUP], "component")

    known = set(FOUNDATION_GROUPS) | {COMPONENT_GROUP} | set(MODELED_SCALARS)
    extras = {key: value for key, value in front_matter.items() if key not in known}

    return ParsedDesignSystem(
        front_matter_raw=front_matter_raw,
        guide_markdown=guide_markdown,
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
        if not isinstance(cursor, dict) or part not in cursor:
            raise UnknownTokenPathError(f"token path not in front matter: {token_path}")
        cursor = cursor[part]
    leaf = parts[-1]
    if not isinstance(cursor, dict) or leaf not in cursor:
        raise UnknownTokenPathError(f"token path not in front matter: {token_path}")
    previous = cursor[leaf]
    if isinstance(previous, _QUOTED_STYLES):
        cursor[leaf] = type(previous)(value)
    else:
        cursor[leaf] = value


def serialize_design_md(
    *,
    front_matter_raw: str,
    guide_markdown: str,
    token_patches: Mapping[str, str] | None = None,
) -> str:
    """Re-emit a DESIGN.md file, patching only the requested token paths."""
    front_matter = _load_front_matter(front_matter_raw)
    for token_path, value in (token_patches or {}).items():
        _set_token(front_matter, token_path, value)
    buffer = io.StringIO()
    _yaml().dump(front_matter, buffer)
    return f"{FENCE}\n{buffer.getvalue()}{FENCE}\n{guide_markdown}"
