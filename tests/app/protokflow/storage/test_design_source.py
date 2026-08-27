"""Tests for the filesystem observation and parsing adapter.

These exercise ``design_source`` directly, with no database involved: the
module's contract is that it classifies a source file and never selects
query-versus-patch policy.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from stat import S_IMODE

import pytest

from backend.app.protokflow.core.discovery import DiscoveredDesignFile
from backend.app.protokflow.error.design_md import (
    FencedYamlBlockError,
    InvalidEncodingError,
)
from backend.app.protokflow.error.storage import (
    MissingSourceFileError,
    SourceWriteError,
    UnsupportedSourceLinkError,
)
from backend.app.protokflow.storage import design_source as design_source_module
from backend.app.protokflow.storage.design_source import (
    SourceChange,
    SourceMetadata,
    SourceObservation,
    observe_design_source,
    parse_design_content,
    parse_design_file,
    read_source_bytes,
    stat_matches,
    stat_source,
)

_DESIGN_MD = (
    "---\n"
    "name: Default\n"
    "description: A calm, high-contrast system.\n"
    "version: '1'\n"
    "colors:\n"
    "  primary: '#111111'\n"
    "  secondary: '#222222'\n"
    "---\n"
    "# Guide\n"
)


def _write(path: Path, text: str) -> None:
    """Write fixture text byte-exactly, without newline translation."""
    path.write_bytes(text.encode("utf-8"))


def _metadata_of(path: Path) -> SourceMetadata:
    """Return the metadata a sync of the current file bytes would persist."""
    content = path.read_bytes()
    stat = os.stat(path)
    return SourceMetadata(
        source_digest=hashlib.sha256(content).hexdigest(),
        source_mtime_ns=stat.st_mtime_ns,
        source_size=stat.st_size,
    )


def _observe(root: Path, previous: SourceMetadata) -> SourceObservation:
    return observe_design_source(
        root, slug="default", source_path="DESIGN.md", previous=previous
    )


def test_matching_stat_reports_unchanged_without_reading_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A matching ``(mtime_ns, size)`` short-circuits before any file read."""
    design_md_path = tmp_path / "DESIGN.md"
    _write(design_md_path, _DESIGN_MD)
    previous = _metadata_of(design_md_path)

    def fail_read(*args: object, **kwargs: object) -> None:
        raise AssertionError("an unchanged stat must not read the file")

    monkeypatch.setattr(design_source_module, "read_source_bytes", fail_read)

    observation = _observe(tmp_path, previous)

    assert observation.change is SourceChange.UNCHANGED
    assert observation.metadata is None
    assert observation.snapshot is None


def test_touch_only_change_reports_touched_with_fresh_metadata(
    tmp_path: Path,
) -> None:
    """Identical bytes under a new mtime are TOUCHED, carrying no snapshot."""
    design_md_path = tmp_path / "DESIGN.md"
    _write(design_md_path, _DESIGN_MD)
    previous = _metadata_of(design_md_path)
    assert previous.source_mtime_ns is not None
    bumped_ns = previous.source_mtime_ns + 1_000_000_000
    os.utime(design_md_path, ns=(bumped_ns, bumped_ns))

    observation = _observe(tmp_path, previous)

    assert observation.change is SourceChange.TOUCHED
    assert observation.snapshot is None
    assert observation.metadata is not None
    assert observation.metadata.source_digest == previous.source_digest
    assert observation.metadata.source_mtime_ns == bumped_ns
    assert observation.metadata.source_size == previous.source_size


def test_same_size_content_change_reaches_digest_comparison(tmp_path: Path) -> None:
    """A size-preserving edit is caught by the digest, not by the stat."""
    design_md_path = tmp_path / "DESIGN.md"
    _write(design_md_path, _DESIGN_MD)
    previous = _metadata_of(design_md_path)
    external = _DESIGN_MD.replace("#111111", "#999999")
    assert len(external) == len(_DESIGN_MD)
    _write(design_md_path, external)

    observation = _observe(tmp_path, previous)

    assert observation.change is SourceChange.CHANGED
    assert observation.snapshot is not None
    assert observation.snapshot.source_size == previous.source_size


def test_one_nanosecond_mtime_delta_reaches_digest_comparison(tmp_path: Path) -> None:
    """A 1ns delta is enough to leave UNCHANGED, where the filesystem stores it."""
    design_md_path = tmp_path / "DESIGN.md"
    _write(design_md_path, _DESIGN_MD)
    previous = _metadata_of(design_md_path)
    assert previous.source_mtime_ns is not None
    bumped_ns = previous.source_mtime_ns + 1
    os.utime(design_md_path, ns=(bumped_ns, bumped_ns))
    if os.stat(design_md_path).st_mtime_ns != bumped_ns:
        pytest.skip(
            "filesystem mtime granularity is coarser than 1ns "
            "(NTFS stores 100ns ticks), so the delta cannot be applied here"
        )

    observation = _observe(tmp_path, previous)

    assert observation.change is SourceChange.TOUCHED
    assert observation.metadata is not None
    assert observation.metadata.source_mtime_ns == bumped_ns


def test_changed_snapshot_describes_the_file_version_it_opened(
    tmp_path: Path,
) -> None:
    """Digest, size and mtime in a CHANGED snapshot come from one open handle."""
    design_md_path = tmp_path / "DESIGN.md"
    _write(design_md_path, _DESIGN_MD)
    previous = _metadata_of(design_md_path)
    external = _DESIGN_MD.replace("#222222", "#333333").replace(
        "# Guide\n", "# Guide\n\nMore.\n"
    )
    _write(design_md_path, external)

    observation = _observe(tmp_path, previous)

    assert observation.change is SourceChange.CHANGED
    assert observation.metadata is None
    snapshot = observation.snapshot
    assert snapshot is not None
    on_disk = design_md_path.read_bytes()
    assert snapshot.source_digest == hashlib.sha256(on_disk).hexdigest()
    assert snapshot.source_size == len(on_disk)
    assert snapshot.source_mtime_ns == os.stat(design_md_path).st_mtime_ns
    assert snapshot.slug == "default"
    assert snapshot.source_root == tmp_path.as_posix()
    assert snapshot.source_path == "DESIGN.md"
    assert {token.token_path: token.value for token in snapshot.parsed.tokens} == {
        "colors.primary": "#111111",
        "colors.secondary": "#333333",
    }


def test_absent_source_reports_missing(tmp_path: Path) -> None:
    """A source that is already gone is MISSING, not an error."""
    observation = _observe(
        tmp_path,
        SourceMetadata(source_digest="d", source_mtime_ns=1, source_size=1),
    )

    assert observation.change is SourceChange.MISSING
    assert observation.metadata is None
    assert observation.snapshot is None


def test_source_deleted_after_the_stat_reports_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A deletion inside the stat-to-read window stays inside the outcome enum."""
    design_md_path = tmp_path / "DESIGN.md"
    _write(design_md_path, _DESIGN_MD)
    previous = _metadata_of(design_md_path)
    external = _DESIGN_MD.replace("#111111", "#999999")
    _write(design_md_path, external)
    real_stat_source = design_source_module.stat_source

    def stat_then_delete(path: Path) -> os.stat_result | None:
        stat = real_stat_source(path)
        path.unlink()
        return stat

    monkeypatch.setattr(design_source_module, "stat_source", stat_then_delete)

    observation = _observe(tmp_path, previous)

    assert observation.change is SourceChange.MISSING


def test_invalid_utf8_source_preserves_the_encoding_error(tmp_path: Path) -> None:
    """Undecodable bytes raise the design-md encoding error, not a decode error."""
    design_md_path = tmp_path / "DESIGN.md"
    design_md_path.write_bytes(b"---\nname: \xff\xfe\n---\n")

    with pytest.raises(InvalidEncodingError, match="not valid UTF-8"):
        _observe(
            tmp_path,
            SourceMetadata(source_digest="d", source_mtime_ns=1, source_size=1),
        )


def test_invalid_design_md_source_preserves_the_parse_error(tmp_path: Path) -> None:
    """Malformed DESIGN.md content raises the parser's own error."""
    design_md_path = tmp_path / "DESIGN.md"
    _write(design_md_path, "```yaml\nname: Default\n```\n# Guide\n")

    with pytest.raises(FencedYamlBlockError):
        _observe(
            tmp_path,
            SourceMetadata(source_digest="d", source_mtime_ns=1, source_size=1),
        )


def test_parse_design_content_is_database_free(tmp_path: Path) -> None:
    """Parsing takes bytes and a path only."""
    parsed = parse_design_content(tmp_path / "DESIGN.md", _DESIGN_MD.encode("utf-8"))

    assert parsed.title == "Default"
    assert [token.token_path for token in parsed.tokens] == [
        "colors.primary",
        "colors.secondary",
    ]


def test_parse_design_file_records_paths_relative_to_the_root(tmp_path: Path) -> None:
    """A snapshot stores the root absolutely and the source path relative to it."""
    design_dir = tmp_path / "design"
    design_dir.mkdir()
    source_path = design_dir / "admin.md"
    _write(source_path, _DESIGN_MD)

    snapshot = parse_design_file(
        tmp_path, DiscoveredDesignFile(slug="admin", path=source_path)
    )

    assert snapshot.slug == "admin"
    assert snapshot.source_root == tmp_path.as_posix()
    assert snapshot.source_path == "design/admin.md"
    assert (
        snapshot.source_digest == hashlib.sha256(source_path.read_bytes()).hexdigest()
    )


def test_read_source_bytes_names_the_slug_when_the_file_is_gone(
    tmp_path: Path,
) -> None:
    """The missing-source error identifies the design system it was read for."""
    with pytest.raises(MissingSourceFileError, match="design system 'admin'"):
        read_source_bytes(tmp_path / "DESIGN.md", slug="admin")


def test_read_source_bytes_treats_a_directory_as_a_missing_source(
    tmp_path: Path,
) -> None:
    """A source path resolving to a directory is a missing source, not an OSError."""
    (tmp_path / "DESIGN.md").mkdir()

    with pytest.raises(MissingSourceFileError):
        read_source_bytes(tmp_path / "DESIGN.md", slug="default")


def test_stat_source_returns_none_for_absent_and_unreachable_paths(
    tmp_path: Path,
) -> None:
    """Both a missing file and a non-directory parent stat as ``None``."""
    _write(tmp_path / "DESIGN.md", _DESIGN_MD)

    assert stat_source(tmp_path / "absent.md") is None
    assert stat_source(tmp_path / "DESIGN.md" / "nested.md") is None
    assert stat_source(tmp_path / "DESIGN.md") is not None


def test_stat_matches_requires_both_persisted_fields(tmp_path: Path) -> None:
    """A row missing either stat field can never match, so it is always re-read."""
    design_md_path = tmp_path / "DESIGN.md"
    _write(design_md_path, _DESIGN_MD)
    stat = os.stat(design_md_path)
    persisted = _metadata_of(design_md_path)

    assert stat_matches(persisted, stat) is True
    assert (
        stat_matches(
            SourceMetadata(
                source_digest=persisted.source_digest,
                source_mtime_ns=None,
                source_size=stat.st_size,
            ),
            stat,
        )
        is False
    )
    assert (
        stat_matches(
            SourceMetadata(
                source_digest=persisted.source_digest,
                source_mtime_ns=stat.st_mtime_ns,
                source_size=None,
            ),
            stat,
        )
        is False
    )


def test_atomic_write_preserves_non_default_file_mode(tmp_path: Path) -> None:
    """copymode carries the target's mode onto the 0o600 mkstemp temp before the swap."""
    target = tmp_path / "DESIGN.md"
    target.write_bytes(b"original\n")
    target.chmod(0o640)
    mode_before = S_IMODE(os.stat(target).st_mode)
    assert mode_before == 0o640  # distinct from mkstemp's default 0o600

    design_source_module.atomic_write_bytes(target, b"new content\n")

    assert target.read_bytes() == b"new content\n"
    assert S_IMODE(os.stat(target).st_mode) == 0o640


def test_atomic_write_unlinks_temp_when_copymode_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A copymode failure after the temp is written must unlink it and preserve the target."""
    target = tmp_path / "DESIGN.md"
    target.write_bytes(b"original\n")

    def failing_copymode(*args: object, **kwargs: object) -> None:
        raise OSError("simulated copymode failure")

    monkeypatch.setattr(design_source_module.shutil, "copymode", failing_copymode)

    with pytest.raises(SourceWriteError, match="simulated copymode failure"):
        design_source_module.atomic_write_bytes(target, b"new content\n")

    assert target.read_bytes() == b"original\n"
    assert list(tmp_path.iterdir()) == [target]


def test_atomic_write_unlinks_temp_when_handle_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A write failure into the temp file must unlink it and never touch the target."""
    target = tmp_path / "DESIGN.md"
    target.write_bytes(b"original\n")

    real_fdopen = os.fdopen

    def fdopen_with_failing_write(fd: int, mode: str = "wb") -> object:
        # atomic_write_bytes always opens the temp descriptor "wb"; wrap that
        # real handle so only its write() fails while flush/fileno/close stay real.
        handle = real_fdopen(fd, "wb")

        class _FailingWriteHandle:
            def __enter__(self) -> _FailingWriteHandle:
                handle.__enter__()
                return self

            def __exit__(self, *exc: object) -> None:
                handle.close()

            def write(self, _data: object) -> int:
                raise OSError("simulated write failure")

            def flush(self) -> None:
                handle.flush()

            def fileno(self) -> int:
                return handle.fileno()

        return _FailingWriteHandle()

    monkeypatch.setattr(design_source_module.os, "fdopen", fdopen_with_failing_write)

    with pytest.raises(SourceWriteError, match="simulated write failure"):
        design_source_module.atomic_write_bytes(target, b"new content\n")

    assert target.read_bytes() == b"original\n"
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.skipif(
    hasattr(os, "getuid") and os.getuid() == 0,
    reason="root bypasses directory permission bits",
)
def test_atomic_write_wraps_permission_error_on_unwritable_parent(
    tmp_path: Path,
) -> None:
    """mkstemp cannot create the temp in a read-only directory; wrapped with cause."""
    design_dir = tmp_path / "locked"
    design_dir.mkdir()
    target = design_dir / "DESIGN.md"
    target.write_bytes(b"original\n")
    design_dir.chmod(0o500)
    try:
        with pytest.raises(SourceWriteError) as excinfo:
            design_source_module.atomic_write_bytes(target, b"new content\n")
    finally:
        design_dir.chmod(0o700)

    assert isinstance(excinfo.value.__cause__, PermissionError)
    assert target.read_bytes() == b"original\n"


def test_atomic_write_rejects_symlink_source(tmp_path: Path) -> None:
    """Symlink sources are rejected to prevent replacing the link with a regular file."""
    real_target = tmp_path / "real.md"
    real_target.write_bytes(b"original\n")
    link = tmp_path / "DESIGN.md"
    link.symlink_to(real_target)

    with pytest.raises(UnsupportedSourceLinkError):
        design_source_module.atomic_write_bytes(link, b"new content\n")

    assert link.is_symlink()
    assert real_target.read_bytes() == b"original\n"
    assert sorted(tmp_path.iterdir()) == sorted([real_target, link])


def test_atomic_write_rejects_hard_linked_source(tmp_path: Path) -> None:
    """Hard-linked sources are rejected to prevent breaking link aliases."""
    target = tmp_path / "DESIGN.md"
    target.write_bytes(b"original\n")
    alias = tmp_path / "alias.md"
    os.link(target, alias)

    with pytest.raises(UnsupportedSourceLinkError):
        design_source_module.atomic_write_bytes(target, b"new content\n")

    assert target.read_bytes() == b"original\n"
    assert alias.read_bytes() == b"original\n"
    assert os.stat(target).st_ino == os.stat(alias).st_ino
