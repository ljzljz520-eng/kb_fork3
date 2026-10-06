# -*- encoding: utf-8 -*-
# kb v0.2.0
# A knowledge base organizer
# Copyright © 2020, gnc.
# See /LICENSE for licensing information.

"""
kb content-addressed blob store module

Artifact contents are never stored at their display path
(category/title): they live in a content-addressed store where the
file name is the SHA-256 hash of the bytes, sharded in 256 buckets
(``blob/<first two hex chars>/<full hash>``).

Properties:
* identical contents are automatically de-duplicated;
* a blob can be verified at any time by re-hashing the file;
* garbage collection deletes *exclusively* blobs that are not
  referenced by any revision nor by any tombstone.

:Copyright: © 2020, gnc.
:License: GPLv3 (see /LICENSE).
"""

__all__ = ()

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple

import kb.filesystem as fs

HASH_ALGORITHM = "sha256"


def hash_content(data: bytes) -> str:
    """Return the SHA-256 hex digest of the provided bytes."""
    return hashlib.sha256(data).hexdigest()


def hash_file(path: str, chunk_size: int = 1024 * 1024) -> str:
    """Return the SHA-256 hex digest of a file on disk."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def blob_relative_path(digest: str) -> Path:
    """Return the sharded relative path of a blob, e.g. ab/abcd1234..."""
    return Path(digest[:2], digest)


def blob_path(store_root: str, digest: str) -> Path:
    """Return the absolute on-disk path of a blob given its hash."""
    return Path(store_root, digest[:2], digest)


def add_blob(store_root: str, data: bytes) -> str:
    """Persist bytes in the content store.

    The write is idempotent and atomic: identical content maps to
    the same path and is never written twice.

    Arguments:
    store_root  - the root directory of the blob store
    data        - the bytes to store

    Returns:
    The SHA-256 hex digest of the stored content.
    """
    digest = hash_content(data)
    destination = blob_path(store_root, digest)
    if destination.exists():
        return digest

    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".kbblob-", dir=str(destination.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp_name, str(destination))
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return digest


def add_file(store_root: str, source_path: str) -> Tuple[str, int]:
    """Import a file from disk into the content store.

    Returns:
    A tuple (blob_hash, size_in_bytes).
    """
    with open(source_path, "rb") as handle:
        data = handle.read()
    digest = add_blob(store_root, data)
    return digest, len(data)


def has_blob(store_root: str, digest: str) -> bool:
    """Return True if the blob exists on disk."""
    return blob_path(store_root, digest).is_file()


def read_blob(store_root: str, digest: str) -> bytes:
    """Return the raw bytes of a blob."""
    with open(blob_path(store_root, digest), "rb") as handle:
        return handle.read()


def verify_blob(store_root: str, digest: str) -> bool:
    """Verify the integrity of a blob.

    Returns True only if the blob exists on disk and its content
    hashes back to the recorded digest.
    """
    path = blob_path(store_root, digest)
    if not path.is_file():
        return False
    return hash_file(str(path)) == digest


def materialize(
        store_root: str,
        digest: str,
        suffix: str = "") -> str:
    """Materialize a blob as a temporary regular file.

    This is needed to run interactive editors or external openers
    that need a normal file path.

    Arguments:
    store_root  - the root directory of the blob store
    digest      - the hash of the blob to materialize
    suffix      - an optional suffix for the temporary file,
                  useful to preserve syntax highlighting in editors

    Returns:
    The path of the temporary file.
    """
    tmp_path = fs.get_temp_filepath(suffix=suffix)
    data = read_blob(store_root, digest)
    with open(tmp_path, "wb") as handle:
        handle.write(data)
    return tmp_path


def get_blob_references(conn) -> Dict[str, int]:
    """Return the reference count of every registered blob.

    A blob is referenced once for every revision pointing to it
    plus once for every tombstone explicitly pinning it.
    """
    cur = conn.cursor()
    cur.execute("""
                SELECT b.hash,
                       (SELECT COUNT(*) FROM revisions r
                          WHERE r.blob_hash = b.hash)
                       +
                       (SELECT COUNT(*) FROM tombstone_blobs t
                          WHERE t.blob_hash = b.hash)
                       AS refcount
                FROM blobs b
                """)
    return {row[0]: row[1] for row in cur.fetchall()}


def get_unreferenced_blobs(
        conn,
        purging_uuids: Tuple[str, ...] = ()) -> List[Tuple[str, int]]:
    """Return (hash, size) tuples of blobs with zero references.

    A reference is a revision row or a tombstone_blobs row.

    When ``purging_uuids`` is supplied, references held by those
    artifacts are ignored: this lets a GC dry-run report which
    blobs would become unreferenced once the corresponding expired
    tombstones are purged.
    """
    cur = conn.cursor()
    if purging_uuids:
        placeholders = ",".join("?" for _ in purging_uuids)
        query = """
                SELECT b.hash, b.size
                FROM blobs b
                WHERE NOT EXISTS (
                    SELECT 1 FROM revisions r
                    WHERE r.blob_hash = b.hash
                      AND r.artifact_uuid NOT IN ({skip}))
                  AND NOT EXISTS (
                    SELECT 1 FROM tombstone_blobs t
                    WHERE t.blob_hash = b.hash
                      AND t.artifact_uuid NOT IN ({skip}))
                """.format(skip=placeholders)
        cur.execute(query, list(purging_uuids) + list(purging_uuids))
    else:
        cur.execute("""
                    SELECT b.hash, b.size
                    FROM blobs b
                    WHERE NOT EXISTS (
                        SELECT 1 FROM revisions r
                        WHERE r.blob_hash = b.hash)
                      AND NOT EXISTS (
                        SELECT 1 FROM tombstone_blobs t
                        WHERE t.blob_hash = b.hash)
                    """)
    return cur.fetchall()


def garbage_collect(
        store_root: str,
        conn,
        dry_run: bool = False) -> Dict[str, object]:
    """Delete blobs that are not referenced by any revision/tombstone.

    Only blobs recorded in the ``blobs`` registry with a reference
    count of zero are ever removed; referenced content is always
    preserved.

    Returns:
    A report dictionary with the list of removed blobs and the
    total number of reclaimed bytes.
    """
    unreferenced = get_unreferenced_blobs(conn)
    removed: List[str] = []
    reclaimed_bytes = 0

    for digest, size in unreferenced:
        if not dry_run:
            fs.remove_file(str(blob_path(store_root, digest)))
            cur = conn.cursor()
            cur.execute("DELETE FROM blobs WHERE hash = ?", [digest])
        removed.append(digest)
        reclaimed_bytes += size or 0

    if not dry_run:
        conn.commit()

    return {
        "removed_blobs": removed,
        "removed_count": len(removed),
        "reclaimed_bytes": reclaimed_bytes,
        "dry_run": dry_run,
    }
