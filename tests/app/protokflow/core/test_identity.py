"""Tests for deterministic path-based repository and worktree identity generation."""

from __future__ import annotations

import unicodedata
from pathlib import Path

import pytest

from backend.app.protokflow.core import identity
from tests.fixtures.git import TemporaryGitRepository


def _common_dir(repo: TemporaryGitRepository) -> Path:
    return Path(
        repo.git_stdout("rev-parse", "--path-format=absolute", "--git-common-dir")
    )


def test_worktree_id_is_stable_across_symlink_paths(tmp_path: Path) -> None:
    """Accessing the same root via symlinks produces an identical worktree_id."""
    real = tmp_path / "worktree"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    assert identity.worktree_id(link) == identity.worktree_id(real)


def test_sibling_worktrees_share_repository_identity(
    git_repo: TemporaryGitRepository,
) -> None:
    """Linked sibling worktrees have distinct worktree IDs but share the same repository ID."""
    sibling = git_repo.add_worktree("sibling")
    assert identity.worktree_id(git_repo.root) != identity.worktree_id(sibling.root)
    assert identity.repository_id(_common_dir(git_repo)) == identity.repository_id(
        _common_dir(sibling)
    )


def test_case_folding_applies_only_when_case_insensitive(tmp_path: Path) -> None:
    """Folds case on case-insensitive filesystems while preserving case on sensitive ones."""
    primary = tmp_path / "Worktree"
    secondary = tmp_path / "worktree"  # Path differing only by casing
    assert identity.worktree_id(primary, case_insensitive=True) == identity.worktree_id(
        secondary, case_insensitive=True
    )
    assert identity.worktree_id(
        primary, case_insensitive=False
    ) != identity.worktree_id(secondary, case_insensitive=False)


def test_auto_detection_matches_filesystem_behavior(tmp_path: Path) -> None:
    """Automatic case sensitivity detection matches the underlying filesystem behavior."""
    directory = tmp_path / "ProbeDir"
    directory.mkdir()
    swapped = directory.with_name(directory.name.swapcase())
    insensitive = swapped.exists()  # True only on case-insensitive filesystems
    same_id = identity.worktree_id(directory) == identity.worktree_id(swapped)
    assert same_id is insensitive


def test_probe_does_not_mistake_symlink_alias_for_case_insensitivity(
    tmp_path: Path,
) -> None:
    """A pre-existing swapped-case symlink alias must not collapse the probe result."""
    directory = tmp_path / "Worktree"
    directory.mkdir()
    alias = tmp_path / "wORKTREE"
    try:
        alias.symlink_to(directory, target_is_directory=True)
    except FileExistsError:
        pytest.skip("host filesystem is case-insensitive")

    assert identity._is_case_insensitive(directory) is False


def test_probe_detects_folding_for_uncased_directory_names(tmp_path: Path) -> None:
    """A directory name without cased letters still gets a correct probe result."""
    ground_truth_probe = tmp_path / "case-probe"
    ground_truth_probe.touch()
    insensitive = True
    try:
        (tmp_path / "CASE-PROBE").touch(exist_ok=False)
        insensitive = False
    except FileExistsError:
        insensitive = True
    except OSError:
        insensitive = False
    finally:
        (tmp_path / "CASE-PROBE").unlink(missing_ok=True)
        ground_truth_probe.unlink(missing_ok=True)

    uncased = tmp_path / "2024"
    uncased.mkdir()

    assert identity._is_case_insensitive(uncased) is insensitive


def test_probe_result_is_cached_per_directory(tmp_path: Path) -> None:
    """Repeated probing of one directory answers from cache instead of new markers."""
    directory = tmp_path / "CachedTarget"
    directory.mkdir()
    before = identity._is_case_insensitive.cache_info()

    identity._is_case_insensitive(directory)
    identity._is_case_insensitive(directory)

    after = identity._is_case_insensitive.cache_info()
    assert after.hits == before.hits + 1


def test_probe_leaves_no_artifacts_behind(tmp_path: Path) -> None:
    """Probing a directory creates and removes its markers without a trace."""
    directory = tmp_path / "ProbeTarget"
    directory.mkdir()

    identity.normalize_path(directory)

    assert list(directory.iterdir()) == []


def test_unicode_normalization_unifies_equivalent_spellings(tmp_path: Path) -> None:
    """Unicode NFC normalization produces identical IDs for equivalent decomposed/composed forms."""
    composed = tmp_path / unicodedata.normalize("NFC", "cafe-worktree-\u00e9")
    decomposed = tmp_path / unicodedata.normalize("NFD", "cafe-worktree-\u00e9")
    assert (
        composed != decomposed
    )  # Spellings differ at the byte level before NFC normalization
    assert identity.worktree_id(
        composed, case_insensitive=False
    ) == identity.worktree_id(decomposed, case_insensitive=False)


def test_domains_separate_worktree_and_repository_ids(tmp_path: Path) -> None:
    """Distinct domain prefixes keep the two identifier spaces apart."""
    directory = tmp_path / "solo"
    directory.mkdir()
    assert identity.worktree_id(directory) != identity.repository_id(directory)


def test_ids_are_deterministic_lowercase_hex(tmp_path: Path) -> None:
    """Identifiers are stable SHA-256 digests rendered in lowercase hex."""
    directory = tmp_path / "stable"
    directory.mkdir()
    first = identity.worktree_id(directory)
    assert first == identity.worktree_id(directory)
    assert len(first) == 64
    assert first == first.lower()
    assert set(first) <= set("0123456789abcdef")
