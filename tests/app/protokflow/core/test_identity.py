"""Tests for deterministic path-based repository and worktree identity (KTD7)."""

from __future__ import annotations

import unicodedata
from pathlib import Path

from backend.app.protokflow.core import identity
from tests.fixtures.git import TemporaryGitRepository


def _common_dir(repo: TemporaryGitRepository) -> Path:
    return Path(
        repo.git_stdout("rev-parse", "--path-format=absolute", "--git-common-dir")
    )


def test_worktree_id_is_stable_across_symlink_paths(tmp_path: Path) -> None:
    """Symlinked access to the same root yields the same worktree_id (R25)."""
    real = tmp_path / "worktree"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    assert identity.worktree_id(link) == identity.worktree_id(real)


def test_sibling_worktrees_share_repository_identity(
    git_repo: TemporaryGitRepository,
) -> None:
    """Siblings differ per worktree but agree on the repository (R25)."""
    sibling = git_repo.add_worktree("sibling")
    assert identity.worktree_id(git_repo.root) != identity.worktree_id(sibling.root)
    assert identity.repository_id(_common_dir(git_repo)) == identity.repository_id(
        _common_dir(sibling)
    )


def test_case_folding_applies_only_when_case_insensitive(tmp_path: Path) -> None:
    """Case-fold on insensitive paths, preserve case on sensitive ones (KTD7)."""
    primary = tmp_path / "Worktree"
    secondary = tmp_path / "worktree"  # case-only spelling difference
    assert identity.worktree_id(primary, case_insensitive=True) == identity.worktree_id(
        secondary, case_insensitive=True
    )
    assert identity.worktree_id(
        primary, case_insensitive=False
    ) != identity.worktree_id(secondary, case_insensitive=False)


def test_auto_detection_matches_filesystem_behavior(tmp_path: Path) -> None:
    """Automatic case handling agrees with what the filesystem resolves."""
    directory = tmp_path / "ProbeDir"
    directory.mkdir()
    swapped = directory.with_name(directory.name.swapcase())
    insensitive = swapped.exists()  # possible only when the FS folds case
    same_id = identity.worktree_id(directory) == identity.worktree_id(swapped)
    assert same_id is insensitive


def test_unicode_normalization_unifies_equivalent_spellings(tmp_path: Path) -> None:
    """NFC normalization folds equivalent Unicode spellings together (KTD7)."""
    composed = tmp_path / unicodedata.normalize("NFC", "cafe-worktree-\u00e9")
    decomposed = tmp_path / unicodedata.normalize("NFD", "cafe-worktree-\u00e9")
    assert composed != decomposed  # the spellings genuinely differ before folding
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
