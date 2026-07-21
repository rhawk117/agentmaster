"""Tests for content-addressed SHA-256 artifact storage (SPEC.md §16.1, §23 MT13)."""

import pytest

from ledger.artifact_store import ArtifactStore, content_address


def test_identical_content_produces_the_same_digest():
    assert content_address(b'hello') == content_address(b'hello')


def test_different_content_produces_a_different_digest():
    assert content_address(b'hello') != content_address(b'world')


def test_put_writes_content_readable_back_by_its_digest(tmp_path):
    store = ArtifactStore(tmp_path)

    write = store.put(b'evidence payload')

    assert store.read(write.sha256) == b'evidence payload'


def test_put_deduplicates_identical_content(tmp_path):
    store = ArtifactStore(tmp_path)

    first = store.put(b'same bytes')
    second = store.put(b'same bytes')

    assert first.sha256 == second.sha256
    assert first.deduplicated is False
    assert second.deduplicated is True


def test_put_of_different_content_stores_at_different_paths(tmp_path):
    store = ArtifactStore(tmp_path)

    first = store.put(b'alpha')
    second = store.put(b'beta')

    assert first.relative_path != second.relative_path


def test_a_write_crash_leaves_no_partial_artifact(tmp_path, monkeypatch):
    store = ArtifactStore(tmp_path)

    def _boom(_fd):
        raise OSError('simulated crash mid-write')

    monkeypatch.setattr('os.fsync', _boom)

    with pytest.raises(OSError, match='simulated crash mid-write'):
        store.put(b'never fully written')

    digest = content_address(b'never fully written')
    assert not store.path_for(digest).exists()
    leftover = list((tmp_path / 'sha256').iterdir())
    assert leftover == []
