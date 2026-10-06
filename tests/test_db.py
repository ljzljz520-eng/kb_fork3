#!/usr/bin/env python
# -*- encoding: utf-8 -*-
# kb test suite
# Copyright © 2020, gnc.
# See /LICENSE for licensing information.

"""
Tests for the schema v2 database layer: stable UUID identity,
hash-referencing revisions, display-only renames and tombstones.
"""

import sqlite3

import pytest

import kb.db as db
import kb.store as store
from kb.entities.artifact import Artifact


CONTENT_V1 = b"version one\n"
CONTENT_V2 = b"version two\n"


@pytest.fixture()
def backend(tmp_path):
    blob_root = str(tmp_path / "blob")
    db_path = str(tmp_path / "kb.db")
    db.create_kb_database(db_path, 2)
    conn = db.create_connection(db_path)
    conn.commit()
    return conn, blob_root


def _make_artifact(conn, blob_root, title="note", category="default",
                   content=CONTENT_V1, tags=None, **kwargs):
    blob_hash = store.add_blob(blob_root, content)
    artifact = Artifact(
        uuid=None, title=title, category=category,
        current_hash=blob_hash, tags=tags,
        author=kwargs.get("author"), status=kwargs.get("status"),
        template=kwargs.get("template"))
    artifact_uuid = db.create_artifact(
        conn, artifact, blob_hash, len(content))
    return artifact_uuid, blob_hash


def _list_tables(conn):
    cur = conn.cursor()
    cur.execute("""SELECT name FROM sqlite_master
                   WHERE type='table' ORDER BY name;""")
    return [row[0] for row in cur.fetchall()]


def test_create_kb_database_tables(backend):
    conn, _ = backend
    assert _list_tables(conn) == [
        "artifacts", "blobs", "revisions", "tags",
        "tombstone_blobs", "tombstones"]


def test_create_artifact_identity_and_revision_one(backend):
    conn, blob_root = backend
    artifact_uuid, blob_hash = _make_artifact(conn, blob_root)

    artifact = db.get_artifact_by_uuid(conn, artifact_uuid)
    assert artifact.uuid == artifact_uuid
    assert artifact.title == "note"
    assert artifact.state == "alive"
    assert artifact.current_hash == blob_hash

    revisions = db.get_revisions(conn, artifact_uuid)
    assert [rev.revision_no for rev in revisions] == [1]
    assert revisions[0].blob_hash == blob_hash
    assert revisions[0].parent_id is None

    cur = conn.cursor()
    cur.execute("SELECT hash FROM blobs")
    assert cur.fetchone()[0] == blob_hash


def test_duplicate_title_category_rejected(backend):
    conn, blob_root = backend
    uuid1, _ = _make_artifact(conn, blob_root, title="dup")
    uuid2, _ = _make_artifact(conn, blob_root, title="dup")
    assert uuid1 is not None
    assert uuid2 is None


def test_rename_preserves_identity_blob_and_revision(backend):
    conn, blob_root = backend
    artifact_uuid, blob_hash = _make_artifact(
        conn, blob_root, title="old", category="cat-a")
    original_revision = db.get_latest_revision(conn, artifact_uuid)

    updated = db.update_artifact_properties(
        conn, artifact_uuid, title="new", category="cat-b")

    assert updated.uuid == artifact_uuid
    assert updated.category == "cat-b"
    assert updated.title == "new"
    assert updated.current_hash == blob_hash
    assert updated.current_revision == original_revision.id
    assert db.get_revisions(conn, artifact_uuid) == [original_revision]


def test_rename_collision_rejected(backend):
    conn, blob_root = backend
    uuid1, _ = _make_artifact(conn, blob_root, title="a", category="c")
    _make_artifact(conn, blob_root, title="b", category="c")
    result = db.update_artifact_properties(
        conn, uuid1, title="b", category="c")
    assert result is None
    assert db.get_artifact_by_uuid(conn, uuid1).title == "a"


def test_revision_chain_and_restore(backend):
    conn, blob_root = backend
    artifact_uuid, hash_v1 = _make_artifact(
        conn, blob_root, content=CONTENT_V1)
    hash_v2 = store.add_blob(blob_root, CONTENT_V2)
    rev2 = db.add_revision(conn, artifact_uuid, hash_v2, len(CONTENT_V2))

    assert rev2.revision_no == 2
    assert rev2.blob_hash == hash_v2
    assert rev2.parent_id == 1

    revisions = db.get_revisions(conn, artifact_uuid)
    assert [r.blob_hash for r in revisions] == [hash_v1, hash_v2]

    # restore r1: appends a new child referencing the old blob
    rev3 = db.restore_revision(conn, artifact_uuid, 1)
    assert rev3.revision_no == 3
    assert rev3.blob_hash == hash_v1
    assert rev3.parent_id == rev2.id
    assert db.get_latest_revision(conn, artifact_uuid).blob_hash == hash_v1

    # restoring the current content is a no-op
    assert db.restore_revision(conn, artifact_uuid, 1) is None
    # restoring a missing revision fails
    assert db.restore_revision(conn, artifact_uuid, 99) is None


def test_add_revision_same_content_is_callers_responsibility(backend):
    conn, blob_root = backend
    artifact_uuid, _ = _make_artifact(conn, blob_root, content=CONTENT_V1)
    # the store de-duplicates identical bytes to the same hash
    same_hash = store.add_blob(blob_root, CONTENT_V1)
    rev = db.add_revision(conn, artifact_uuid, same_hash, len(CONTENT_V1))
    assert rev is not None
    assert rev.blob_hash == same_hash


def test_tag_filtering(backend):
    conn, blob_root = backend
    _make_artifact(conn, blob_root, title="a", tags="pt;smb")
    _make_artifact(conn, blob_root, title="b", tags="pt")
    _make_artifact(conn, blob_root, title="c", tags="web")

    rows = db.get_artifacts_by_tags(conn, tags=["pt"], is_strict=True)
    assert {art.title for art in rows} == {"a", "b"}

    rows = db.get_artifacts_by_filter(
        conn, tags=["smb"], is_strict=True)
    assert {art.title for art in rows} == {"a"}


def test_tombstone_lifecycle_and_purge(backend):
    conn, blob_root = backend
    artifact_uuid, hash_v1 = _make_artifact(
        conn, blob_root, content=CONTENT_V1)
    hash_v2 = store.add_blob(blob_root, CONTENT_V2)
    db.add_revision(conn, artifact_uuid, hash_v2, len(CONTENT_V2))

    assert db.tombstone_artifact(conn, artifact_uuid, retention_days=30)
    assert db.tombstone_artifact(conn, artifact_uuid, retention_days=30) \
        is False

    deleted = db.get_artifact_by_uuid(conn, artifact_uuid)
    assert deleted.state == "deleted"
    assert db.is_artifact_existing(conn, "note", "default") is False

    tombstone = db.get_tombstone(conn, artifact_uuid)
    assert tombstone is not None

    # both blobs are pinned by the tombstone
    cur = conn.cursor()
    cur.execute(
        "SELECT blob_hash FROM tombstone_blobs WHERE artifact_uuid = ?",
        [artifact_uuid])
    pinned = {row[0] for row in cur.fetchall()}
    assert pinned == {hash_v1, hash_v2}

    # live filters exclude deleted artifacts
    assert db.get_artifacts_by_title(conn, "note", is_strict=True) == []
    deleted_rows = db.get_artifacts_by_title(
        conn, "note", is_strict=True, state="deleted")
    assert len(deleted_rows) == 1

    # nothing expires yet
    assert db.purge_expired_tombstones(conn) == []
    assert db.get_artifact_by_uuid(conn, artifact_uuid) is not None

    # undelete works while the tombstone is retained
    restored = db.undelete_artifact(conn, artifact_uuid)
    assert restored.state == "alive"
    assert db.get_tombstone(conn, artifact_uuid) is None
    cur.execute(
        "SELECT COUNT(*) FROM tombstone_blobs WHERE artifact_uuid = ?",
        [artifact_uuid])
    assert cur.fetchone()[0] == 0


def test_purge_expired_tombstone(backend):
    conn, blob_root = backend
    artifact_uuid, _ = _make_artifact(conn, blob_root)

    # negative retention => already expired
    assert db.tombstone_artifact(conn, artifact_uuid, retention_days=-1)
    purged = db.purge_expired_tombstones(conn)
    assert purged == [artifact_uuid]

    assert db.get_artifact_by_uuid(conn, artifact_uuid) is None
    assert db.get_revisions(conn, artifact_uuid) == []
    assert db.get_tombstone(conn, artifact_uuid) is None


def test_undelete_unknown_artifact(backend):
    conn, _ = backend
    assert db.undelete_artifact(conn, "missing") is None


def test_schema_management(backend, tmp_path):
    conn, _ = backend
    assert db.get_schema_version(conn) == 2
    assert db.is_schema_updated_to_version(conn, 2)
    assert not db.is_schema_updated_to_version(conn, 1)


def test_v0_to_v1_migration(tmp_path):
    db_path = str(tmp_path / "old.db")
    conn = sqlite3.connect(db_path)
    conn.executescript("""CREATE TABLE artifacts (
        id integer PRIMARY KEY, title text NOT NULL,
        category text NOT NULL, path text NOT NULL, tags text,
        status text, author text);
    """)
    conn.commit()
    db.migrate_v0_to_v1(conn)
    assert db.get_schema_version(conn) == 1
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(artifacts)")
    assert "template" in [row[1] for row in cur.fetchall()]
