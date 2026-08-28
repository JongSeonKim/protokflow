"""Tests for the database-neutral DESIGN.md source adapter."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.protokflow.core.discovery import DiscoveredDesignFile
from backend.app.protokflow.error.design_md import InvalidEncodingError
from backend.app.protokflow.storage import design_source
from backend.app.protokflow.storage.design_source import (
    SourceChange,
    SourceMetadata,
    observe_design_source,
    parse_design_file,
)


_DESIGN_MD = (
    "---\n"
    "name: Default\n"
    "colors:\n"
    "  primary: '#111111'\n"
    "  secondary: '#222222'\n"
    "---\n"
    "# Guide\n"
)


def _snapshot(root: Path):
    path = root / "DESIGN.md"
    path.write_bytes(_DESIGN_MD.encode())
    return parse_design_file(root, DiscoveredDesignFile(slug="default", path=path))


def test_matching_stat_is_unchanged_without_reading_source_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = _snapshot(tmp_path)

    def fail_read(*args: object, **kwargs: object) -> object:
        raise AssertionError("an unchanged source must not be read")

    monkeypatch.setattr(design_source, "read_source_bytes", fail_read)

    observation = observe_design_source(
        tmp_path,
        slug=snapshot.slug,
        source_path=snapshot.source_path,
        previous=SourceMetadata.from_snapshot(snapshot),
    )

    assert observation.change is SourceChange.UNCHANGED
    assert observation.metadata is None
    assert observation.snapshot is None


def test_touch_only_change_returns_new_metadata_without_reparsing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = _snapshot(tmp_path)
    path = tmp_path / snapshot.source_path
    os.utime(
        path,
        ns=(snapshot.source_mtime_ns, snapshot.source_mtime_ns + 2_000_000_000),
    )

    def fail_parse(*args: object, **kwargs: object) -> object:
        raise AssertionError("a touched source must not be reparsed")

    monkeypatch.setattr(design_source, "parse_design_content", fail_parse)

    observation = observe_design_source(
        tmp_path,
        slug=snapshot.slug,
        source_path=snapshot.source_path,
        previous=SourceMetadata.from_snapshot(snapshot),
    )

    assert observation.change is SourceChange.TOUCHED
    assert observation.metadata == SourceMetadata(
        source_digest=snapshot.source_digest,
        source_mtime_ns=(path.stat()).st_mtime_ns,
        source_size=len(_DESIGN_MD.encode()),
    )
    assert observation.snapshot is None


def test_same_size_content_change_reaches_digest_comparison_and_returns_snapshot(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot(tmp_path)
    path = tmp_path / snapshot.source_path
    changed = _DESIGN_MD.replace("#111111", "#333333")
    assert len(changed.encode()) == snapshot.source_size
    path.write_bytes(changed.encode())

    observation = observe_design_source(
        tmp_path,
        slug=snapshot.slug,
        source_path=snapshot.source_path,
        previous=SourceMetadata.from_snapshot(snapshot),
    )

    assert observation.change is SourceChange.CHANGED
    assert observation.metadata is None
    assert observation.snapshot is not None
    assert observation.snapshot.parsed.tokens[0].value == "#333333"
    assert observation.snapshot.source_digest != snapshot.source_digest
    assert SourceMetadata.from_snapshot(observation.snapshot) == SourceMetadata(
        source_digest=observation.snapshot.source_digest,
        source_mtime_ns=observation.snapshot.source_mtime_ns,
        source_size=observation.snapshot.source_size,
    )


def test_one_nanosecond_mtime_delta_reaches_digest_comparison() -> None:
    metadata = SourceMetadata(
        source_digest="digest", source_mtime_ns=1_000, source_size=10
    )
    stat = SimpleNamespace(st_mtime_ns=1_001, st_size=10)

    assert design_source.stat_matches(metadata, stat) is False


def test_stat_preserving_same_size_edit_remains_undetectable_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = _snapshot(tmp_path)
    path = tmp_path / snapshot.source_path
    changed = _DESIGN_MD.replace("#111111", "#333333")
    assert len(changed.encode()) == snapshot.source_size
    path.write_bytes(changed.encode())

    def fail_read(*args: object, **kwargs: object) -> object:
        raise AssertionError("the matching stat boundary must skip the digest read")

    monkeypatch.setattr(design_source, "read_source_bytes", fail_read)
    monkeypatch.setattr(
        design_source,
        "stat_source",
        lambda _: SimpleNamespace(
            st_mtime_ns=snapshot.source_mtime_ns,
            st_size=snapshot.source_size,
        ),
    )

    observation = observe_design_source(
        tmp_path,
        slug=snapshot.slug,
        source_path=snapshot.source_path,
        previous=SourceMetadata.from_snapshot(snapshot),
    )

    assert observation.change is SourceChange.UNCHANGED


def test_missing_source_is_neutral_missing_outcome(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    (tmp_path / snapshot.source_path).unlink()

    observation = observe_design_source(
        tmp_path,
        slug=snapshot.slug,
        source_path=snapshot.source_path,
        previous=SourceMetadata.from_snapshot(snapshot),
    )

    assert observation.change is SourceChange.MISSING
    assert observation.metadata is None
    assert observation.snapshot is None


def test_invalid_encoding_and_design_content_preserve_parse_errors(
    tmp_path: Path,
) -> None:
    invalid_encoding = tmp_path / "invalid-encoding.md"
    invalid_encoding.write_bytes(b"# Guide\n\xff\xfe\n")
    with pytest.raises(InvalidEncodingError):
        parse_design_file(
            tmp_path,
            DiscoveredDesignFile(slug="invalid-encoding", path=invalid_encoding),
        )

    invalid_design = tmp_path / "invalid-design.md"
    invalid_design.write_text("---\ncolors: [unterminated\n---\n", encoding="utf-8")
    with pytest.raises(ValueError):
        parse_design_file(
            tmp_path,
            DiscoveredDesignFile(slug="invalid-design", path=invalid_design),
        )
