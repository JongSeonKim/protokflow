"""Byte-level round-trip and rejection tests for the DESIGN.md codec."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.protokflow.core.designmd import (
    ParsedDesignSystem,
    parse_design_md,
    serialize_design_md,
)
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
from ruamel.yaml.error import YAMLError

FIXTURE_DIR = Path(__file__).parents[3] / "fixtures" / "design_md"
MARKDOWN_FENCE = chr(96) * 3
_FOUR_BACKTICKS = MARKDOWN_FENCE + chr(96)

ROUND_TRIP_FIXTURES = (
    "doc-assumed.md",
    "spec-canonical.md",
    "adversarial.md",
    "team-authored.md",
)


def _read_fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_bytes().decode()


def _parse_fixture(name: str) -> ParsedDesignSystem:
    return parse_design_md(_read_fixture(name))


def _serialize(parsed: ParsedDesignSystem) -> str:
    return serialize_design_md(
        front_matter_raw=parsed.front_matter_raw,
        closing_fence=parsed.closing_fence,
        guide_markdown=parsed.guide_markdown,
        eol=parsed.eol,
    )


@pytest.mark.parametrize("name", ROUND_TRIP_FIXTURES)
def test_round_trip_without_edits_is_byte_identical(name: str) -> None:
    original = _read_fixture(name)
    parsed = parse_design_md(original)

    assert _serialize(parsed) == original


def test_no_front_matter_yields_zero_tokens_and_markdown_body() -> None:
    original = _read_fixture("no-front-matter.md")

    parsed = parse_design_md(original)

    assert parsed.tokens == []
    assert parsed.front_matter_raw is None
    assert parsed.guide_markdown == original
    assert parsed.title is None
    assert parsed.description is None
    assert parsed.spec_version is None
    assert parsed.front_matter_extras == {}


def test_no_front_matter_round_trip_is_byte_identical() -> None:
    original = _read_fixture("no-front-matter.md")
    parsed = parse_design_md(original)

    assert _serialize(parsed) == original


def test_present_but_empty_front_matter_round_trips() -> None:
    text = "---\n---\n# Guide\n"

    parsed = parse_design_md(text)

    assert parsed.front_matter_raw == ""
    assert parsed.tokens == []
    assert _serialize(parsed) == text


def test_whitespace_only_front_matter_round_trips() -> None:
    text = "---\n\n  \n---\n# Guide\n"

    parsed = parse_design_md(text)

    assert parsed.tokens == []
    assert _serialize(parsed) == text


def test_comment_only_front_matter_round_trips() -> None:
    text = "---\n# only a comment\n---\n# Guide\n"

    parsed = parse_design_md(text)

    assert parsed.tokens == []
    assert parsed.front_matter_extras == {}
    assert _serialize(parsed) == text


def test_crlf_document_round_trips_byte_identically() -> None:
    original = _read_fixture("team-authored.md").replace("\n", "\r\n")

    parsed = parse_design_md(original)

    assert parsed.eol == "\r\n"
    assert _serialize(parsed) == original


def test_crlf_patch_changes_exactly_one_line() -> None:
    original = _read_fixture("team-authored.md").replace("\n", "\r\n")
    parsed = parse_design_md(original)

    patched = serialize_design_md(
        front_matter_raw=parsed.front_matter_raw,
        closing_fence=parsed.closing_fence,
        guide_markdown=parsed.guide_markdown,
        eol=parsed.eol,
        token_patches={"colors.primary": "#3AA6B9"},
    )

    original_lines = original.splitlines(keepends=True)
    patched_lines = patched.splitlines(keepends=True)
    assert len(original_lines) == len(patched_lines), "patch must not change line count"
    changed = [
        (left, right)
        for left, right in zip(original_lines, patched_lines, strict=True)
        if left != right
    ]
    assert len(changed) == 1
    assert "#3AA6B9" in changed[0][1]


def test_missing_final_newline_after_closing_fence_round_trips() -> None:
    text = "---\ncolors:\n  primary: '#111111'\n---"

    parsed = parse_design_md(text)

    assert parsed.closing_fence == "---"
    assert _serialize(parsed) == text


def test_patches_on_front_matter_less_document_raise() -> None:
    with pytest.raises(UnknownTokenPathError, match="colors.primary"):
        serialize_design_md(
            front_matter_raw=None,
            closing_fence="",
            guide_markdown="# Guide\n",
            eol="\n",
            token_patches={"colors.primary": "#FFFFFF"},
        )


def test_patches_on_empty_front_matter_raise() -> None:
    with pytest.raises(UnknownTokenPathError, match="colors.primary"):
        serialize_design_md(
            front_matter_raw="",
            closing_fence="---\n",
            guide_markdown="# Guide\n",
            eol="\n",
            token_patches={"colors.primary": "#FFFFFF"},
        )


def test_mixed_line_endings_are_rejected_at_parse() -> None:
    text = "---\nname: Mixed\r\n---\n# Guide\n"

    with pytest.raises(MixedLineEndingsError):
        parse_design_md(text)


def test_serialize_rejects_output_with_mixed_line_endings() -> None:
    with pytest.raises(MixedLineEndingsError):
        serialize_design_md(
            front_matter_raw="name: Mixed\r\n",
            closing_fence="---\n",
            guide_markdown="# Guide\n",
            eol="\n",
        )


def test_serialize_rejects_anchored_front_matter() -> None:
    with pytest.raises(YamlAnchorError):
        serialize_design_md(
            front_matter_raw="colors:\n  primary: &ink '#0B0E14'\n  overlay: *ink\n",
            closing_fence="---\n",
            guide_markdown="# Guide\n",
            eol="\n",
            token_patches={"colors.primary": "#FFFFFF"},
        )


def test_serialize_rejects_fenced_yaml_in_guide() -> None:
    guide = (
        "# Guide\n\n"
        + MARKDOWN_FENCE
        + "yaml\ncolors:\n  primary: '#0B0E14'\n"
        + MARKDOWN_FENCE
        + "\n"
    )

    with pytest.raises(FencedYamlBlockError):
        serialize_design_md(
            front_matter_raw="name: Has Guide\n",
            closing_fence="---\n",
            guide_markdown=guide,
            eol="\n",
        )


@pytest.mark.parametrize("front_matter", [True, False])
def test_fenced_yaml_block_is_rejected_with_guidance(front_matter: bool) -> None:
    heading = "---\nname: Rejected\n---\n" if front_matter else ""
    fenced_yaml = (
        MARKDOWN_FENCE + "yaml\ncolors:\n  primary: '#0B0E14'\n" + MARKDOWN_FENCE
    )
    text = f"{heading}# Guide\n\n{fenced_yaml}\n"

    with pytest.raises(FencedYamlBlockError) as excinfo:
        parse_design_md(text)

    assert "front matter" in str(excinfo.value)


def test_unterminated_front_matter_fence_is_a_parse_error() -> None:
    with pytest.raises(UnterminatedFrontMatterError):
        parse_design_md("---\nname: Broken\ncolors:\n  primary: '#0B0E14'\n")


@pytest.mark.parametrize(
    "front_matter",
    [
        "colors:\n  &brand primary: '#FFFFFF'\n",
        "colors:\n  primary: &nil null\n",
        "omitted:\n  - &first spacing\n",
        "typography:\n  body-md:\n    fontFamily: &face Inter\n",
    ],
    ids=["anchored-key", "anchored-null", "anchored-list-item", "deep-nesting"],
)
def test_anchor_positions_are_rejected(front_matter: str) -> None:
    text = f"---\n{front_matter}---\n# Guide\n"

    with pytest.raises(YamlAnchorError):
        parse_design_md(text)


@pytest.mark.parametrize(
    "fence",
    [
        MARKDOWN_FENCE + "yaml",
        MARKDOWN_FENCE + "yml",
        _FOUR_BACKTICKS + "yaml",
        "~~~yaml",
        "~~~yml",
        "  " + MARKDOWN_FENCE + "yaml",
    ],
    ids=[
        "three-backticks",
        "three-backticks-yml",
        "four-backticks",
        "tildes",
        "tildes-yml",
        "indented",
    ],
)
def test_fenced_yaml_spelling_variants_are_rejected(fence: str) -> None:
    text = f"# Guide\n\n{fence}\ncolors:\n  primary: '#0B0E14'\n"

    with pytest.raises(FencedYamlBlockError):
        parse_design_md(text)


def test_non_yaml_fences_are_allowed() -> None:
    text = (
        "# Guide\n\n"
        + MARKDOWN_FENCE
        + 'json\n{"a": 1}\n'
        + MARKDOWN_FENCE
        + "\n\n"
        + MARKDOWN_FENCE
        + "\nplain block\n"
        + MARKDOWN_FENCE
        + "\n"
    )

    parsed = parse_design_md(text)

    assert parsed.guide_markdown == text


def test_malformed_yaml_raises_invalid_front_matter_error() -> None:
    with pytest.raises(InvalidFrontMatterError) as excinfo:
        parse_design_md("---\nname: [unclosed\n---\n# Guide\n")

    assert isinstance(excinfo.value.__cause__, YAMLError)


def test_token_tiers_cover_foundation_and_component() -> None:
    parsed = _parse_fixture("spec-canonical.md")

    paths = {(row.tier, row.token_path) for row in parsed.tokens}

    assert {tier for tier, _ in paths} == {"foundation", "component"}
    assert ("foundation", "colors.primary") in paths
    assert ("component", "components.button-primary.backgroundColor") in paths


@pytest.mark.parametrize(
    ("front_matter", "path"),
    [
        ("colors: []\n", "colors"),
        ("colors: red\n", "colors"),
        ("colors:\n  primary: [one, two]\n", "colors.primary"),
        (
            "colors:\n  primary:\n    nested:\n      deep: '#FFFFFF'\n",
            "colors.primary.nested",
        ),
        ("components:\n  button: [a, b]\n", "components.button"),
    ],
    ids=[
        "list-group",
        "scalar-group",
        "sequence-leaf",
        "depth-four",
        "component-sequence",
    ],
)
def test_non_scalar_token_shapes_are_rejected(front_matter: str, path: str) -> None:
    text = f"---\n{front_matter}---\n# Guide\n"

    with pytest.raises(NonScalarTokenError, match=path):
        parse_design_md(text)


@pytest.mark.parametrize(
    "value_line",
    ["  primary: null\n", "  primary: ~\n", "  primary:\n"],
    ids=["explicit-null", "tilde-null", "empty-value"],
)
def test_null_token_values_are_rejected(value_line: str) -> None:
    text = f"---\ncolors:\n{value_line}---\n# Guide\n"

    with pytest.raises(NullTokenValueError, match="colors.primary"):
        parse_design_md(text)


@pytest.mark.parametrize(
    "front_matter",
    [
        "colors:\n  brand.primary: '#FFFFFF'\n",
        "typography:\n  body.md:\n    fontSize: 16px\n",
    ],
    ids=["shallow-name", "nested-name"],
)
def test_dotted_token_names_are_rejected(front_matter: str) -> None:
    text = f"---\n{front_matter}---\n# Guide\n"

    with pytest.raises(DottedTokenNameError):
        parse_design_md(text)


def test_depth_three_token_paths_are_extracted() -> None:
    parsed = _parse_fixture("spec-canonical.md")

    values = {row.token_path: row.value for row in parsed.tokens}

    assert values["typography.body-md.fontSize"] == "16px"


def test_yaml_numbers_are_extracted_as_strings() -> None:
    parsed = _parse_fixture("spec-canonical.md")

    values = {row.token_path: row.value for row in parsed.tokens}

    assert values["typography.body-md.fontWeight"] == "400"
    assert values["typography.body-md.lineHeight"] == "1.6"
    assert values["typography.headline-lg.fontWeight"] == "600"


def test_omitted_and_unknown_keys_are_preserved_in_extras() -> None:
    parsed = _parse_fixture("adversarial.md")

    extras = parsed.front_matter_extras

    assert set(extras) == {"omitted", "iconography"}
    assert extras["omitted"] == [
        "spacing",
        {"section": "rounded", "reason": "No rounded corners defined in brand book"},
    ]
    assert extras["iconography"] == {"set": "lucide", "stroke": 1.5}


def test_modeled_scalars_are_separated_from_extras() -> None:
    parsed = _parse_fixture("spec-canonical.md")

    assert parsed.spec_version == "alpha"
    assert parsed.title == "Daylight Prestige"
    assert (
        parsed.description
        == "A high-contrast editorial system for long-form product surfaces."
    )
    assert "name" not in parsed.front_matter_extras


def test_patching_one_token_changes_exactly_one_line() -> None:
    original = _read_fixture("team-authored.md")
    parsed = parse_design_md(original)

    patched = serialize_design_md(
        front_matter_raw=parsed.front_matter_raw,
        closing_fence=parsed.closing_fence,
        guide_markdown=parsed.guide_markdown,
        eol=parsed.eol,
        token_patches={"colors.primary": "#3AA6B9"},
    )

    original_lines = original.splitlines(keepends=True)
    patched_lines = patched.splitlines(keepends=True)
    changed = [
        (left, right)
        for left, right in zip(original_lines, patched_lines, strict=True)
        if left != right
    ]

    assert len(changed) == 1
    assert "#3AA6B9" in changed[0][1]
    assert "# 승인됨 2026-08-11" in changed[0][1]


def test_patching_preserves_quoted_style_of_the_patched_line() -> None:
    parsed = _parse_fixture("adversarial.md")

    patched = serialize_design_md(
        front_matter_raw=parsed.front_matter_raw,
        closing_fence=parsed.closing_fence,
        guide_markdown=parsed.guide_markdown,
        eol=parsed.eol,
        token_patches={"typography.body-md.fontWeight": "500"},
    )

    patched_line = next(
        line for line in patched.splitlines() if 'fontWeight: "500"' in line
    )
    assert "# quoted number" in patched_line


def test_patching_unknown_token_path_raises_clear_error() -> None:
    parsed = _parse_fixture("team-authored.md")

    with pytest.raises(UnknownTokenPathError):
        serialize_design_md(
            front_matter_raw=parsed.front_matter_raw,
            closing_fence=parsed.closing_fence,
            guide_markdown=parsed.guide_markdown,
            eol=parsed.eol,
            token_patches={"colors.nonexistent": "#000000"},
        )


@pytest.mark.parametrize(
    "token_path",
    ["colors", "colors.nope.primary", "name"],
    ids=["group-root", "missing-intermediate", "modeled-scalar-key"],
)
def test_patching_non_leaf_paths_raise(token_path: str) -> None:
    parsed = _parse_fixture("team-authored.md")

    with pytest.raises(UnknownTokenPathError):
        serialize_design_md(
            front_matter_raw=parsed.front_matter_raw,
            closing_fence=parsed.closing_fence,
            guide_markdown=parsed.guide_markdown,
            eol=parsed.eol,
            token_patches={token_path: "#000000"},
        )


def test_patching_bare_number_leaf_keeps_plain_style() -> None:
    original = _read_fixture("spec-canonical.md")
    parsed = parse_design_md(original)

    patched = serialize_design_md(
        front_matter_raw=parsed.front_matter_raw,
        closing_fence=parsed.closing_fence,
        guide_markdown=parsed.guide_markdown,
        eol=parsed.eol,
        token_patches={"typography.body-md.fontWeight": "500"},
    )

    original_lines = original.splitlines(keepends=True)
    patched_lines = patched.splitlines(keepends=True)
    assert len(original_lines) == len(patched_lines)
    changed = [
        (left, right)
        for left, right in zip(original_lines, patched_lines, strict=True)
        if left != right
    ]
    assert len(changed) == 1
    assert changed[0][1].strip() == "fontWeight: 500"


def test_patching_single_quoted_leaf_keeps_style() -> None:
    parsed = _parse_fixture("adversarial.md")

    patched = serialize_design_md(
        front_matter_raw=parsed.front_matter_raw,
        closing_fence=parsed.closing_fence,
        guide_markdown=parsed.guide_markdown,
        eol=parsed.eol,
        token_patches={"colors.tertiary": "#3AA6B9"},
    )

    patched_line = next(line for line in patched.splitlines() if "tertiary" in line)
    assert "'#3AA6B9'" in patched_line


def test_anchor_in_front_matter_is_rejected_with_reference_guidance() -> None:
    with pytest.raises(YamlAnchorError) as excinfo:
        _parse_fixture("anchors.md")

    assert "{colors.primary}" in str(excinfo.value)


def test_alias_pointing_across_groups_is_rejected() -> None:
    text = (
        "---\n"
        "typography:\n"
        "  font-family: &body Inter\n"
        "colors:\n"
        "  primary: '#111111'\n"
        "  text: *body\n"
        "---\n"
        "# Guide\n"
    )

    with pytest.raises(YamlAnchorError):
        parse_design_md(text)


def test_folded_scalar_and_mixed_quotes_survive_round_trip() -> None:
    original = _read_fixture("adversarial.md")
    parsed = parse_design_md(original)

    assert parsed.description == (
        "A dark operations console theme. Folded scalar, two source lines, "
        "one logical value."
    )
    assert _serialize(parsed) == original
