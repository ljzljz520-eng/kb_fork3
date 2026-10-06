#!/usr/bin/env python
# -*- encoding: utf-8 -*-
# kb test suite
# Copyright © 2020, gnc.
# See /LICENSE for licensing information.

"""
Tests for the content-addressed blob store and the reference
counted garbage collector.
"""

from datetime import timedelta

import pytest

import kb.db as db
import kb.store as store
from kb.entities.artifact import Artifact


CONTENT_A = b"hello world\n"
CONTENT_B = b"completely different bytes\n"


@pytest.fixture()
def backend(tmp_path):
    blob_root = tmp_path / "blob"
    blob_root.mkdir()
    db.create_kb_database(str(tmp_path / "kb.db"), 2)
    conn = db.create_connection(str(tmp_path / "kb.db"))
    return conn, str(blob_root)


def _add_artifact(conn, blob_root, content=CONTENT_A, title="a",
                  category="default"):
    digest = store.add_blob(str(blob_root), content)
    artifact = Artifact(
        uuid=None, title=title, category=category,
        current_hash=digest)
    artifact_uuid = db.create_artifact(
        conn, artifact, digest, len(content))
    return artifact_uuid, digest


def test_blob_is_hash_addressed_and_deduplicated(backend):
    _, blob_root = backend
    digest_a = store.hash_content(CONTENT_A)

    returned = store.add_blob(blob_root, CONTENT_A)
    assert returned == digest_a

    expected_path = store.blob_path(blob_root, digest_a)
    assert expected_path.is_file()
    # sharded in a two-char bucket
    assert expected_path.parent.name == digest_a[:2]

    # identical content is stored only once
    store.add_blob(blob_root, CONTENT_A)
    assert store.read_blob(blob_root, digest_a) == CONTENT_A


def test_blob_verification_detects_tampering(backend):
    _, blob_root = backend
    digest = store.add_blob(blob_root, CONTENT_A)
    assert store.verify_blob(blob_root, digest)

    path = store.blob_path(blob_root, digest)
    with open(path, "wb") as handle:
        handle.write(b"tampered content\n")
    assert not store.verify_blob(blob_root, digest)
    assert not store.verify_blob(blob_root, "a" * 64)


def test_materialize_roundtrip(backend):
    _, blob_root = backend
    digest = store.add_blob(blob_root, CONTENT_A)
    tmp = store.materialize(blob_root, digest, suffix=".md")
    try:
        assert tmp.endswith(".md")
        with open(tmp, "rb") as handle:
            assert handle.read() == CONTENT_A
    finally:
        import os
        os.unlink(tmp)


def test_gc_keeps_referenced_blobs(backend):
    conn, blob_root = backend
    uuid_a, hash_a = _add_artifact(conn, blob_root, CONTENT_A)
    uuid_b, hash_b = _add_artifact(
        conn, blob_root, CONTENT_B, title="b")

    report = store.garbage_collect(blob_root, conn)
    assert report["removed_count"] == 0
    assert store.blob_path(blob_root, hash_a).is_file()
    assert store.blob_path(blob_root, hash_b).is_file()

    references = store.get_blob_references(conn)
    assert references[hash_a] == 1
    assert references[hash_b] == 1


def test_gc_removes_only_unreferenced_blobs(backend):
    conn, blob_root = backend
    uuid_a, hash_a = _add_artifact(conn, blob_root, CONTENT_A)
    uuid_b, hash_b = _add_artifact(
        conn, blob_root, CONTENT_B, title="b")

    # purge one artifact completely (as GC would after tombstone
    # expiry): remove its revisions and artifact rows
    conn.execute("DELETE FROM revisions WHERE artifact_uuid = ?", [uuid_b])
    conn.execute("DELETE FROM tags WHERE artifact_uuid = ?", [uuid_b])
    conn.execute("DELETE FROM artifacts WHERE uuid = ?", [uuid_b])
    conn.commit()

    dry = store.garbage_collect(blob_root, conn, dry_run=True)
    assert dry["removed_blobs"] == [hash_b]
    # a dry run deletes nothing
    assert store.blob_path(blob_root, hash_b).is_file()

    report = store.garbage_collect(blob_root, conn)
    assert set(report["removed_blobs"]) == {hash_b}
    assert not store.blob_path(blob_root, hash_b).exists()
    # the referenced blob survives
    assert store.blob_path(blob_root, hash_a).is_file()
    cur = conn.cursor()
    cur.execute("SELECT hash FROM blobs")
    assert {row[0] for row in cur.fetchall()} == {hash_a}


def test_shared_blob_survives_until_last_reference_drops(backend):
    """Two artifacts with identical content share one blob."""
    conn, blob_root = backend
    uuid_a, shared_hash = _add_artifact(
        conn, blob_root, CONTENT_A, title="a")
    uuid_b, same_hash = _add_artifact(
        conn, blob_root, CONTENT_A, title="b2")
    assert same_hash == shared_hash

    references = store.get_blob_references(conn)
    assert references[shared_hash] == 2

    # drop the first artifact: the blob must survive because the
    # second revision still references it
    conn.execute("DELETE FROM revisions WHERE artifact_uuid = ?", [uuid_a])
    conn.execute("DELETE FROM artifacts WHERE uuid = ?", [uuid_a])
    conn.commit()
    assert store.get_unreferenced_blobs(conn) == []
    assert store.blob_path(blob_root, shared_hash).is_file()

    # drop the second artifact as well: zero references => collected
    conn.execute("DELETE FROM revisions WHERE artifact_uuid = ?", [uuid_b])
    conn.execute("DELETE FROM artifacts WHERE uuid = ?", [uuid_b])
    conn.commit()
    unreferenced = store.get_unreferenced_blobs(conn)
    assert [digest for digest, _ in unreferenced] == [shared_hash]
    store.garbage_collect(blob_root, conn)
    assert not store.blob_path(blob_root, shared_hash).exists()


def test_tombstone_pins_prevent_gc(backend):
    conn, blob_root = backend
    uuid_a, hash_v1 = _add_artifact(conn, blob_root, CONTENT_A)
    hash_v2 = store.add_blob(blob_root, CONTENT_B)
    db.add_revision(conn, uuid_a, hash_v2, len(CONTENT_B))

    db.tombstone_artifact(conn, uuid_a, retention_days=30)

    # even the superseded revision's blob is protected by the
    # tombstone and nothing is collectable
    assert store.get_unreferenced_blobs(conn) == []
    references = store.get_blob_references(conn)
    assert references[hash_v1] == 2  # one revision + one tombstone pin
    assert references[hash_v2] == 2
    assert store.blob_path(blob_root, hash_v1).is_file()
    assert store.blob_path(blob_root, hash_v2).is_file()

    # simulate expiry: purge then collect => both blobs go
    db.purge_expired_tombstones(
        conn, now=db.utc_now() + timedelta(days=31))
    unreferenced = {digest for digest, _ in
                    store.get_unreferenced_blobs(conn)}
    assert unreferenced == {hash_v1, hash_v2}


def test_dry_run_simulation_keeps_blob_shared_with_live_artifact(backend):
    """purging_uuids must reproduce post-purge reference counts."""
    conn, blob_root = backend
    uuid_a, shared_hash = _add_artifact(
        conn, blob_root, CONTENT_A, title="a")
    uuid_b, same_hash = _add_artifact(
        conn, blob_root, CONTENT_A, title="b")
    uuid_c, exclusive_hash = _add_artifact(
        conn, blob_root, CONTENT_B, title="c", category="other")
    assert same_hash == shared_hash

    # nothing is unreferenced today
    assert store.get_unreferenced_blobs(conn) == []

    # simulate purging expired tombstones of a and c: c's private
    # blob becomes garbage, but the blob shared with live artifact b
    # must remain protected
    simulated = {digest for digest, _ in
                 store.get_unreferenced_blobs(conn, (uuid_a, uuid_c))}
    assert simulated == {exclusive_hash}
