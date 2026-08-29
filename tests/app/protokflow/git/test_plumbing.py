"""Tests for isolated-index commit creation and conditional reference plumbing."""

from __future__ import annotations

import pytest

from backend.app.protokflow.error.git import GitCommandError
from backend.app.protokflow.git import plumbing
from tests.fixtures.git import DESIGN_MD_CONTENT, TemporaryGitRepository


def _modified_design_md() -> str:
    return DESIGN_MD_CONTENT.replace("#3366ff", "#ff3366")


def test_create_blob_round_trips_content(git_repo: TemporaryGitRepository) -> None:
    """Creating a blob stores the exact binary content under the returned object ID."""
    content = b"alpha\nbeta"
    oid = plumbing.create_blob(git_repo.root, content)
    result = git_repo.run("cat-file", "blob", oid)
    assert result.stdout == content.decode()


def test_isolated_index_commit_includes_only_design_md_change(
    git_repo: TemporaryGitRepository,
) -> None:
    """Committing via an isolated index excludes existing staged changes and unstaged working tree edits."""
    git_repo.write_file("notes.txt", "staged work\n")
    git_repo.stage("notes.txt")
    modified = _modified_design_md()
    git_repo.write_file("DESIGN.md", modified)  # Unstaged working tree change

    parent = git_repo.head_oid()
    new_blob = plumbing.create_blob(git_repo.root, modified.encode())
    with plumbing.isolated_index(git_repo.root) as index:
        index.read_tree(parent)
        index.update_entry(mode="100644", oid=new_blob, path="DESIGN.md")
        tree = index.write_tree()
    commit = plumbing.create_commit(
        git_repo.root,
        tree=tree,
        parent=parent,
        message="export candidate",
    )

    new_entries = git_repo.tree_entries(tree)
    parent_entries = git_repo.tree_entries(parent)
    assert set(new_entries) == set(
        parent_entries
    )  # Staged notes.txt is excluded from the new commit tree
    assert new_entries["DESIGN.md"] == ("100644", new_blob)
    assert parent_entries["DESIGN.md"] != ("100644", new_blob)

    commit_text = git_repo.commit_object(commit)
    assert f"tree {tree}" in commit_text
    assert f"parent {parent}" in commit_text
    assert (
        git_repo.head_oid() == parent
    )  # HEAD reference remains untouched by commit-tree creation


def test_create_commit_resolves_configured_identity(
    git_repo: TemporaryGitRepository,
) -> None:
    """commit-tree receives the repository's configured identity as explicit env values."""
    commit = plumbing.create_commit(
        git_repo.root,
        tree=git_repo.head_tree(),
        parent=git_repo.head_oid(),
        message="identity: configured",
    )

    commit_text = git_repo.commit_object(commit)
    assert "author Protokflow Tests <tests@protokflow.invalid>" in commit_text
    assert "committer Protokflow Tests <tests@protokflow.invalid>" in commit_text


def test_create_commit_falls_back_to_runtime_identity_without_config(
    git_repo: TemporaryGitRepository,
) -> None:
    """An unconfigured repository still produces commits using the fixed runtime identity."""
    git_repo.run("config", "--local", "--unset", "user.name")
    git_repo.run("config", "--local", "--unset", "user.email")

    commit = plumbing.create_commit(
        git_repo.root,
        tree=git_repo.head_tree(),
        parent=git_repo.head_oid(),
        message="identity: runtime fallback",
    )

    commit_text = git_repo.commit_object(commit)
    assert "author Protokflow Runtime <runtime@protokflow.invalid>" in commit_text
    assert "committer Protokflow Runtime <runtime@protokflow.invalid>" in commit_text


def test_conditional_ref_update_accepts_matching_expected_oid(
    git_repo: TemporaryGitRepository,
) -> None:
    """Advancing a ref succeeds when the expected current OID matches."""
    base = git_repo.head_oid()
    target = plumbing.create_commit(
        git_repo.root,
        tree=git_repo.head_tree(),
        parent=base,
        message="advance",
    )
    result = plumbing.update_ref_conditionally(
        git_repo.root,
        ref="refs/heads/main",
        new_oid=target,
        expected_oid=base,
        reason="test: advance",
    )
    assert result.accepted is True
    assert result.cause is None
    assert result.current_oid == target
    assert git_repo.head_oid() == target


def test_conditional_ref_update_rejects_stale_expected_oid(
    git_repo: TemporaryGitRepository,
) -> None:
    """Advancing a ref is rejected with conflict details when the current OID has moved concurrently."""
    base = git_repo.head_oid()
    tree = git_repo.head_tree()
    target = plumbing.create_commit(
        git_repo.root, tree=tree, parent=base, message="target"
    )
    rival = plumbing.create_commit(
        git_repo.root, tree=tree, parent=base, message="rival"
    )
    git_repo.set_ref(
        "refs/heads/main", rival
    )  # Simulate a concurrent writer updating the branch

    result = plumbing.update_ref_conditionally(
        git_repo.root,
        ref="refs/heads/main",
        new_oid=target,
        expected_oid=base,
        reason="test: stale",
    )

    assert result.accepted is False
    assert result.current_oid == rival
    assert result.stderr
    assert isinstance(result.cause, GitCommandError)
    assert (
        git_repo.head_oid() == rival
    )  # Branch ref retains the concurrent update value


def test_update_index_entry_replaces_single_real_index_path(
    git_repo: TemporaryGitRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Updating a single entry modifies only the target path in the real index, ignoring environment overrides."""
    monkeypatch.setenv("GIT_INDEX_FILE", str(git_repo.root / "bogus-index"))
    before = git_repo.index_entries()

    modified = _modified_design_md()
    blob = plumbing.create_blob(git_repo.root, modified.encode())
    plumbing.update_index_entry(
        git_repo.root,
        mode="100644",
        oid=blob,
        path="DESIGN.md",
    )

    after = git_repo.index_entries()
    assert after["DESIGN.md"] == ("100644", blob)
    assert set(after) == set(before)
    for path, entry in before.items():
        if path != "DESIGN.md":
            assert after[path] == entry


def test_isolated_index_ignores_inherited_env_and_cleans_up(
    git_repo: TemporaryGitRepository,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Commands inside isolated_index use the temporary index file, which is deleted upon exit."""
    bogus = git_repo.root / "bogus-index"
    monkeypatch.setenv("GIT_INDEX_FILE", str(bogus))

    with plumbing.isolated_index(git_repo.root) as index:
        assert index.path != bogus
        assert index.path.exists()
        index.read_tree(git_repo.head_oid())
    assert not index.path.exists()
    assert not bogus.exists()  # Inherited GIT_INDEX_FILE path was never touched


def test_isolated_index_cleans_up_on_exception(
    git_repo: TemporaryGitRepository,
) -> None:
    """Temporary index file is guaranteed to be deleted even when an exception is raised within the context."""
    with pytest.raises(RuntimeError), plumbing.isolated_index(git_repo.root) as index:
        raise RuntimeError("boom")
    assert not index.path.exists()
