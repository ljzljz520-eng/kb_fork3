# -*- encoding: utf-8 -*-
# kb v0.2.0
# A knowledge base organizer
# Copyright © 2020, gnc.
# See /LICENSE for licensing information.

"""
kb database module

Schema v2 introduces:
* a stable UUID as artifact identity (title/category are only a
  mutable display mapping);
* immutable revisions referencing hash-addressed blobs and linked
  to their parent revision;
* tombstones with a retention period replacing hard deletes;
* a blob registry used for reference-counted garbage collection.

:Copyright: © 2020, gnc.
:License: GPLv3 (see /LICENSE).
"""

__all__ = ()

import sqlite3
import uuid as uuidlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from kb.entities.artifact import Artifact
from kb.entities.revision import Revision
import kb.store as store

DB_CREATE_QUERY = """CREATE TABLE IF NOT EXISTS artifacts (
                         uuid text PRIMARY KEY,
                         title text NOT NULL,
                         category text NOT NULL,
                         current_hash text,
                         current_revision integer,
                         tags text,
                         status text,
                         author text,
                         template text,
                         state text NOT NULL DEFAULT 'alive',
                         created_at text NOT NULL,
                         updated_at text NOT NULL);
                     CREATE TABLE IF NOT EXISTS revisions (
                         id integer PRIMARY KEY,
                         artifact_uuid text NOT NULL,
                         revision_no integer NOT NULL,
                         blob_hash text NOT NULL,
                         parent_id integer,
                         author text,
                         message text,
                         created_at text NOT NULL,
                         UNIQUE(artifact_uuid, revision_no));
                     CREATE TABLE IF NOT EXISTS blobs (
                         hash text PRIMARY KEY,
                         size integer NOT NULL,
                         created_at text NOT NULL);
                     CREATE TABLE IF NOT EXISTS tags (
                         artifact_uuid text NOT NULL,
                         tag text NOT NULL);
                     CREATE TABLE IF NOT EXISTS tombstones (
                         artifact_uuid text PRIMARY KEY,
                         deleted_at text NOT NULL,
                         purge_after text NOT NULL);
                     CREATE TABLE IF NOT EXISTS tombstone_blobs (
                         artifact_uuid text NOT NULL,
                         blob_hash text NOT NULL,
                         PRIMARY KEY(artifact_uuid, blob_hash));
                  """

_ARTIFACT_FIELDS = [
    "uuid", "title", "category", "current_hash", "tags", "status",
    "author", "template", "state", "created_at", "updated_at",
    "current_revision",
]

_REVISION_FIELDS = [
    "id", "artifact_uuid", "revision_no", "blob_hash", "parent_id",
    "author", "message", "created_at",
]

ARTIFACT_SELECT = """
                SELECT uuid, title, category, current_hash, tags,
                       status, author, template, state, created_at,
                       updated_at, current_revision
                FROM artifacts
                """

REVISION_SELECT = """
                  SELECT id, artifact_uuid, revision_no, blob_hash,
                         parent_id, author, message, created_at
                  FROM revisions
                  """


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return utc_now().isoformat()


def _row_to_artifact(row) -> Artifact:
    return Artifact(**dict(zip(_ARTIFACT_FIELDS, row)))


def _row_to_revision(row) -> Revision:
    return Revision(**dict(zip(_REVISION_FIELDS, row)))


def create_connection(db_file: str):
    """
    Create a database connection to the SQLite database
    specified by db_file

    Arguments:
    db_file         -  database file

    Returns:
    An sqlite3 connection object or None in case of error
    """
    conn = None
    try:
        conn = sqlite3.connect(db_file)
        return conn
    except Exception as err:
        print("Connection Failed: {error}".format(error=err))

    return conn


def create_table(conn, create_table_sql: str) -> None:
    """
    Create a table from the create_table_sql statement
    or show an error message in case of failure

    Arguments:
    conn              - Connection object
    create_table_sql  - A 'CREATE TABLE' statement
    """
    try:
        cursor = conn.cursor()
        cursor.executescript(create_table_sql)
    except Exception as err:
        print("Table Creation Failed: {error}".format(error=err))


def create_kb_database(kb_db_path: str, schema_version: int) -> None:
    """
    Create an empty sqlite database for kb
    at the specified path or return an error
    if the creation is not possible

    Arguments:
    kb_db_path      - the path where the kb database will be stored
    schema_version  - the schema version to stamp the database with
    """
    conn = create_connection(kb_db_path)

    if conn is not None:
        create_table(conn, DB_CREATE_QUERY)
        set_schema_version(conn, schema_version)
    else:
        print("Error! cannot create the database connection.")


# ---------------------------------------------------------------------------
# Artifact creation and content revisions
# ---------------------------------------------------------------------------

def _register_blob(
        conn,
        blob_hash: str,
        blob_size: int,
        created_at: Optional[str] = None) -> None:
    cur = conn.cursor()
    cur.execute(
        """INSERT OR IGNORE INTO blobs (hash, size, created_at)
           VALUES (?, ?, ?)""",
        [blob_hash, blob_size, created_at or _now_iso()])


def _replace_tags(conn, artifact_uuid: str, tags: Optional[str]) -> None:
    cur = conn.cursor()
    cur.execute("DELETE FROM tags WHERE artifact_uuid = ?", [artifact_uuid])
    if tags:
        for tag in set(tags.split(';')):
            if tag:
                cur.execute(
                    "INSERT INTO tags (artifact_uuid, tag) VALUES (?, ?)",
                    [artifact_uuid, tag])


def create_artifact(
        conn,
        artifact: Artifact,
        blob_hash: str,
        blob_size: int,
        message: Optional[str] = None) -> str:
    """
    Create a new artifact identified by a stable UUID and its first
    revision referencing the provided blob.

    Arguments:
    conn        - the sqlite connection object
    artifact    - an Artifact object (uuid may be None, it will be
                  assigned); the title/category pair must not already
                  exist among live artifacts
    blob_hash   - the hash of the initial content blob
    blob_size   - the size in bytes of the initial content blob
    message     - an optional revision message

    Returns:
    The UUID of the newly created artifact, or None if an artifact
    with the same title/category already exists.
    """
    if is_artifact_existing(conn, artifact.title, artifact.category):
        print("Error: the specified artifact already exists in kb!")
        print("Run `kb update -h` to understand how to update an artifact")
        return None

    artifact_uuid = artifact.uuid or str(uuidlib.uuid4())
    now = _now_iso()
    cur = conn.cursor()

    cur.execute(
        """INSERT INTO artifacts
           (uuid, title, category, current_hash, current_revision,
            tags, status, author, template, state, created_at, updated_at)
           VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, 'alive', ?, ?)""",
        [artifact_uuid, artifact.title, artifact.category, blob_hash,
         artifact.tags, artifact.status, artifact.author,
         artifact.template, now, now])

    _register_blob(conn, blob_hash, blob_size, now)

    cur.execute(
        """INSERT INTO revisions
           (artifact_uuid, revision_no, blob_hash, parent_id,
            author, message, created_at)
           VALUES (?, 1, ?, NULL, ?, ?, ?)""",
        [artifact_uuid, blob_hash, artifact.author, message, now])
    revision_id = cur.lastrowid

    cur.execute(
        "UPDATE artifacts SET current_revision = ? WHERE uuid = ?",
        [revision_id, artifact_uuid])

    _replace_tags(conn, artifact_uuid, artifact.tags)

    conn.commit()
    return artifact_uuid


def add_revision(
        conn,
        artifact_uuid: str,
        blob_hash: str,
        blob_size: int,
        message: Optional[str] = None,
        author: Optional[str] = None) -> Optional[Revision]:
    """
    Append a new revision to the version chain of an artifact.

    The new revision references the provided blob and has as parent
    the current revision of the artifact.

    Returns:
    The newly created Revision, or None if the artifact does not
    exist or is currently deleted.
    """
    artifact = get_artifact_by_uuid(conn, artifact_uuid)
    if not artifact or artifact.state != "alive":
        return None

    now = _now_iso()
    next_rev_no = (artifact.current_revision and
                   get_revision_by_id(
                       conn, artifact.current_revision).revision_no + 1) or 1
    cur = conn.cursor()

    _register_blob(conn, blob_hash, blob_size, now)

    cur.execute(
        """INSERT INTO revisions
           (artifact_uuid, revision_no, blob_hash, parent_id,
            author, message, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [artifact_uuid, next_rev_no, blob_hash,
         artifact.current_revision, author, message, now])
    new_id = cur.lastrowid

    cur.execute(
        """UPDATE artifacts
           SET current_hash = ?, current_revision = ?, updated_at = ?
           WHERE uuid = ?""",
        [blob_hash, new_id, now, artifact_uuid])

    conn.commit()
    return get_revision_by_id(conn, new_id)


def restore_revision(
        conn,
        artifact_uuid: str,
        revision_no: int,
        message: Optional[str] = None) -> Optional[Revision]:
    """
    Restore an old revision by appending a new revision referencing
    the same blob. The version chain is never rewritten.

    Returns:
    The new Revision, or None when the target does not exist, the
    artifact is deleted, or the target blob is already the current
    content (nothing to do).
    """
    artifact = get_artifact_by_uuid(conn, artifact_uuid)
    if not artifact or artifact.state != "alive":
        return None

    target = get_revision(conn, artifact_uuid, revision_no)
    if not target:
        return None

    current = get_latest_revision(conn, artifact_uuid)
    if current and target.blob_hash == current.blob_hash:
        return None

    cur = conn.cursor()
    cur.execute("SELECT size FROM blobs WHERE hash = ?", [target.blob_hash])
    row = cur.fetchone()
    blob_size = row[0] if row else 0

    return add_revision(
        conn,
        artifact_uuid,
        target.blob_hash,
        blob_size,
        message=message or "restore revision {n}".format(n=revision_no))


# ---------------------------------------------------------------------------
# Artifact queries
# ---------------------------------------------------------------------------

def is_artifact_existing(conn, title: str, category: str) -> bool:
    """
    Check if a live artifact with the provided title and category
    already exists.
    """
    cur = conn.cursor()
    cur.execute(
        """SELECT title, category FROM artifacts
           WHERE title = ? AND category = ? AND state = 'alive'""",
        [title, category])
    return cur.fetchone() is not None


def get_artifact_by_uuid(
        conn,
        artifact_uuid: str,
        include_deleted: bool = True) -> Optional[Artifact]:
    """Get an artifact by its stable UUID."""
    cur = conn.cursor()
    if include_deleted:
        cur.execute(ARTIFACT_SELECT + " WHERE uuid = ?", [artifact_uuid])
    else:
        cur.execute(
            ARTIFACT_SELECT + " WHERE uuid = ? AND state = 'alive'",
            [artifact_uuid])
    row = cur.fetchone()
    if row:
        return _row_to_artifact(row)
    return None


def _state_clause(state: str) -> str:
    if state == "all":
        return ""
    if state == "deleted":
        return " AND state = 'deleted'"
    return " AND state = 'alive'"


def get_artifacts_by_title(
        conn,
        query_string: str = "",
        is_strict: bool = False,
        state: str = "alive") -> List[Artifact]:
    """Return artifacts matching the title (all of them if empty)."""
    if not is_strict:
        query_string = "%" + query_string + "%"
    cur = conn.cursor()
    cur.execute(
        ARTIFACT_SELECT + " WHERE title LIKE ? COLLATE NOCASE"
        + _state_clause(state),
        [query_string])
    return [_row_to_artifact(row) for row in cur.fetchall()]


def get_artifacts_by_status(
        conn,
        query_string: str = "",
        is_strict: bool = False,
        state: str = "alive") -> List[Artifact]:
    """Return artifacts matching the status."""
    if not is_strict:
        query_string = "%" + query_string + "%"
    cur = conn.cursor()
    cur.execute(
        ARTIFACT_SELECT + " WHERE status LIKE ? COLLATE NOCASE"
        + _state_clause(state),
        [query_string])
    return [_row_to_artifact(row) for row in cur.fetchall()]


def get_artifacts_by_author(
        conn,
        query_string: str = "",
        is_strict: bool = False,
        state: str = "alive") -> List[Artifact]:
    """Return artifacts matching the author."""
    if not is_strict:
        query_string = "%" + query_string + "%"
    cur = conn.cursor()
    cur.execute(
        ARTIFACT_SELECT + " WHERE author LIKE ? COLLATE NOCASE"
        + _state_clause(state),
        [query_string])
    return [_row_to_artifact(row) for row in cur.fetchall()]


def get_artifacts_by_category(
        conn,
        query_string: str = "",
        is_strict: bool = False,
        state: str = "alive") -> List[Artifact]:
    """Return artifacts matching the category."""
    if not is_strict:
        query_string = "%" + query_string + "%"
    cur = conn.cursor()
    cur.execute(
        ARTIFACT_SELECT + " WHERE category LIKE ? COLLATE NOCASE"
        + _state_clause(state),
        [query_string])
    return [_row_to_artifact(row) for row in cur.fetchall()]


def get_artifacts_by_tags(
        conn,
        tags: Optional[List[str]] = None,
        is_strict: bool = False,
        state: str = "alive") -> List[Artifact]:
    """Return artifacts matching the provided tags."""
    if tags is None:
        tags = []
    if not is_strict:
        tags = ["%" + tag + "%" for tag in tags]

    cur = conn.cursor()
    for tag in tags:
        cur.execute(
            ARTIFACT_SELECT +
            """ INNER JOIN tags ON tags.artifact_uuid = artifacts.uuid
                WHERE tag LIKE ? COLLATE NOCASE""" + _state_clause(state),
            [tag])

    artifacts = [_row_to_artifact(row[:len(_ARTIFACT_FIELDS)])
                 for row in cur.fetchall()]
    return artifacts


def get_artifacts_by_filter(
        conn,
        title: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        author: Optional[str] = None,
        status: Optional[str] = None,
        is_strict: bool = False,
        state: str = "alive") -> Optional[List[Artifact]]:
    """
    Return live artifacts matching the intersection of the provided
    filters. Returns None when no filter at all is supplied.
    """
    artifact_id_list = list()

    if title is not None:
        artifact_id_list.append({art.uuid for art in get_artifacts_by_title(
            conn, query_string=title, is_strict=is_strict, state=state)})
    if category is not None:
        artifact_id_list.append({art.uuid for art in get_artifacts_by_category(
            conn, query_string=category, is_strict=is_strict, state=state)})
    if tags:
        artifact_id_list.append({art.uuid for art in get_artifacts_by_tags(
            conn, tags=tags, is_strict=is_strict, state=state)})
    if author:
        artifact_id_list.append({art.uuid for art in get_artifacts_by_author(
            conn, query_string=author, is_strict=is_strict, state=state)})
    if status:
        artifact_id_list.append({art.uuid for art in get_artifacts_by_status(
            conn, query_string=status, is_strict=is_strict, state=state)})

    if len(artifact_id_list) == 0:
        return None

    resulting_set = artifact_id_list.pop()
    for art_ids in artifact_id_list:
        resulting_set.intersection_update(art_ids)

    return [get_artifact_by_uuid(conn, result_id)
            for result_id in resulting_set]


def get_uniq_artifact_by_filter(
        conn,
        title: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        author: Optional[str] = None,
        status: Optional[str] = None,
        is_strict: bool = False,
        state: str = "alive") -> Optional[Artifact]:
    """Return the unique artifact matching the filter, None otherwise."""
    artifacts = get_artifacts_by_filter(
        conn, title=title, category=category, tags=tags, author=author,
        status=status, is_strict=is_strict, state=state)
    if artifacts and len(artifacts) == 1:
        return artifacts.pop()
    return None


def update_artifact_properties(
        conn,
        artifact_uuid: str,
        title: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[str] = None,
        status: Optional[str] = None,
        author: Optional[str] = None,
        template: Optional[str] = None) -> Optional[Artifact]:
    """
    Update the mutable display metadata of an artifact.

    This only changes the display path mapping (title/category) and
    the other metadata: the UUID, current revision and referenced
    blob are untouched, so renames and category moves preserve the
    artifact identity.

    A tags value of "" (empty string) clears the tags.
    """
    artifact = get_artifact_by_uuid(conn, artifact_uuid)
    if not artifact:
        return None

    new_title = title if title is not None else artifact.title
    new_category = category if category is not None else artifact.category

    if (new_title != artifact.title or new_category != artifact.category) and \
            is_artifact_existing(conn, new_title, new_category):
        print("Error: an artifact with this title/category already exists!")
        return None

    new_values = {
        "title": new_title,
        "category": new_category,
        "tags": tags if tags is not None else artifact.tags,
        "status": status if status is not None else artifact.status,
        "author": author if author is not None else artifact.author,
        "template": template if template is not None else artifact.template,
    }

    cur = conn.cursor()
    cur.execute(
        """UPDATE artifacts
           SET title = ?, category = ?, tags = ?, status = ?,
               author = ?, template = ?, updated_at = ?
           WHERE uuid = ?""",
        [new_values["title"], new_values["category"], new_values["tags"],
         new_values["status"], new_values["author"],
         new_values["template"], _now_iso(), artifact_uuid])

    _replace_tags(conn, artifact_uuid, new_values["tags"])
    conn.commit()

    return get_artifact_by_uuid(conn, artifact_uuid)


# ---------------------------------------------------------------------------
# Revision queries
# ---------------------------------------------------------------------------

def get_revision_by_id(conn, revision_id: int) -> Optional[Revision]:
    """Get a revision by its row id."""
    cur = conn.cursor()
    cur.execute(REVISION_SELECT + " WHERE id = ?", [revision_id])
    row = cur.fetchone()
    if row:
        return _row_to_revision(row)
    return None


def get_revision(
        conn,
        artifact_uuid: str,
        revision_no: int) -> Optional[Revision]:
    """Get a specific revision number of an artifact."""
    cur = conn.cursor()
    cur.execute(
        REVISION_SELECT +
        " WHERE artifact_uuid = ? AND revision_no = ?",
        [artifact_uuid, revision_no])
    row = cur.fetchone()
    if row:
        return _row_to_revision(row)
    return None


def get_latest_revision(conn, artifact_uuid: str) -> Optional[Revision]:
    """Get the current (highest) revision of an artifact."""
    cur = conn.cursor()
    cur.execute(
        REVISION_SELECT +
        """ WHERE artifact_uuid = ?
            ORDER BY revision_no DESC LIMIT 1""",
        [artifact_uuid])
    row = cur.fetchone()
    if row:
        return _row_to_revision(row)
    return None


def get_revisions(conn, artifact_uuid: str) -> List[Revision]:
    """Return all revisions of an artifact ordered by revision number."""
    cur = conn.cursor()
    cur.execute(
        REVISION_SELECT +
        " WHERE artifact_uuid = ? ORDER BY revision_no ASC",
        [artifact_uuid])
    return [_row_to_revision(row) for row in cur.fetchall()]


def get_revision_parent(
        conn,
        revision: Revision) -> Optional[Revision]:
    """Return the parent revision of the provided revision, if any."""
    if revision.parent_id is None:
        return None
    return get_revision_by_id(conn, revision.parent_id)


# ---------------------------------------------------------------------------
# Tombstones (soft delete with retention)
# ---------------------------------------------------------------------------

def tombstone_artifact(
        conn,
        artifact_uuid: str,
        retention_days: int,
        now: Optional[datetime] = None) -> bool:
    """
    Soft-delete an artifact: mark it as deleted and create a
    tombstone carrying a purge deadline. Every blob referenced by
    any retained revision of the artifact is additionally pinned by
    the tombstone so that garbage collection cannot reclaim it
    before the retention period elapses.

    Returns:
    True on success, False if the artifact does not exist or is
    already deleted.
    """
    artifact = get_artifact_by_uuid(conn, artifact_uuid)
    if not artifact or artifact.state == "deleted":
        return False

    moment = now or utc_now()
    deleted_at = moment.isoformat()
    purge_after = (moment + timedelta(days=retention_days)).isoformat()

    cur = conn.cursor()
    cur.execute(
        "UPDATE artifacts SET state = 'deleted', updated_at = ? WHERE uuid = ?",
        [deleted_at, artifact_uuid])
    cur.execute(
        """INSERT INTO tombstones (artifact_uuid, deleted_at, purge_after)
           VALUES (?, ?, ?)""",
        [artifact_uuid, deleted_at, purge_after])
    cur.execute(
        """INSERT OR IGNORE INTO tombstone_blobs (artifact_uuid, blob_hash)
           SELECT ?, blob_hash
           FROM (SELECT DISTINCT blob_hash FROM revisions
                 WHERE artifact_uuid = ?)""",
        [artifact_uuid, artifact_uuid])
    conn.commit()
    return True


def get_tombstone(
        conn,
        artifact_uuid: str) -> Optional[Tuple[str, str]]:
    """Return (deleted_at, purge_after) for a deleted artifact."""
    cur = conn.cursor()
    cur.execute(
        """SELECT deleted_at, purge_after FROM tombstones
           WHERE artifact_uuid = ?""",
        [artifact_uuid])
    row = cur.fetchone()
    return tuple(row) if row else None


def get_deleted_artifacts(conn) -> List[Tuple[Artifact, str, str]]:
    """Return deleted artifacts as (artifact, deleted_at, purge_after)."""
    cur = conn.cursor()
    cur.execute(
        """SELECT a.uuid, a.title, a.category, a.current_hash, a.tags,
                  a.status, a.author, a.template, a.state, a.created_at,
                  a.updated_at, a.current_revision,
                  t.deleted_at, t.purge_after
           FROM artifacts a INNER JOIN tombstones t
             ON t.artifact_uuid = a.uuid
           ORDER BY t.purge_after ASC""")
    results = []
    for row in cur.fetchall():
        results.append(
            (_row_to_artifact(row[:len(_ARTIFACT_FIELDS)]),
             row[-2], row[-1]))
    return results


def undelete_artifact(conn, artifact_uuid: str) -> Optional[Artifact]:
    """
    Reverse a soft delete while the tombstone is still retained:
    the artifact becomes live again and the tombstone (including its
    blob pins) is removed. All revisions are preserved.
    """
    artifact = get_artifact_by_uuid(conn, artifact_uuid)
    if not artifact or artifact.state != "deleted":
        return None

    cur = conn.cursor()
    cur.execute(
        "UPDATE artifacts SET state = 'alive', updated_at = ? WHERE uuid = ?",
        [_now_iso(), artifact_uuid])
    cur.execute(
        "DELETE FROM tombstone_blobs WHERE artifact_uuid = ?",
        [artifact_uuid])
    cur.execute(
        "DELETE FROM tombstones WHERE artifact_uuid = ?",
        [artifact_uuid])
    conn.commit()
    return get_artifact_by_uuid(conn, artifact_uuid)


def purge_expired_tombstones(
        conn,
        now: Optional[datetime] = None) -> List[str]:
    """
    Permanently remove artifacts whose tombstones expired.

    Revisions, tags, tombstone rows and the artifact row are all
    deleted in a single transaction. The blob files themselves are
    NOT removed here: they are reclaimed afterwards by the garbage
    collector only if no remaining revision/tombstone references
    them.

    Returns:
    The list of purged artifact UUIDs.
    """
    moment = (now or utc_now()).isoformat()
    cur = conn.cursor()
    cur.execute(
        "SELECT artifact_uuid FROM tombstones WHERE purge_after <= ?",
        [moment])
    expired = [row[0] for row in cur.fetchall()]

    for artifact_uuid in expired:
        cur.execute(
            "DELETE FROM revisions WHERE artifact_uuid = ?",
            [artifact_uuid])
        cur.execute(
            "DELETE FROM tags WHERE artifact_uuid = ?", [artifact_uuid])
        cur.execute(
            "DELETE FROM tombstone_blobs WHERE artifact_uuid = ?",
            [artifact_uuid])
        cur.execute(
            "DELETE FROM tombstones WHERE artifact_uuid = ?",
            [artifact_uuid])
        cur.execute(
            "DELETE FROM artifacts WHERE uuid = ?", [artifact_uuid])

    conn.commit()
    return expired


# ---------------------------------------------------------------------------
# Schema version management and migrations
# ---------------------------------------------------------------------------

def get_schema_version(conn) -> int:
    """Return the schema version used by the database."""
    cur = conn.cursor()
    cur.execute("PRAGMA user_version;")
    return cur.fetchone()[0]


def set_schema_version(conn, version: int) -> None:
    """Stamp the database with the provided schema version."""
    cur = conn.cursor()
    cur.execute("PRAGMA user_version = {v:d}".format(v=version))
    conn.commit()


def is_schema_updated_to_version(conn, version: int) -> bool:
    """Return True if the DB schema matches the provided version."""
    return get_schema_version(conn) == version


def migrate_v0_to_v1(conn):
    """
    Migrates the database schema from v0 to v1.

    Arguments:
    conn            - the database connection object
    """
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(artifacts)")
    columns = [row[1] for row in cur.fetchall()]
    if "template" not in columns:
        cur.execute("ALTER TABLE artifacts ADD COLUMN template text")
        conn.commit()
    set_schema_version(conn, 1)


def migrate_v1_to_v2(conn, config) -> None:
    """
    Migrate the legacy v1 schema (autoincrement id + files living at
    their category/title path) to the v2 schema (stable UUID,
    hash-addressed blobs and revisions).

    Every legacy artifact gets a fresh UUID, its on-disk content is
    imported into the blob store and revision 1 is created. Legacy
    tags are re-keyed from the old integer id to the new UUID.

    Arguments:
    conn    - the database connection object
    config  - the kb configuration, needing PATH_KB_BLOB and
              PATH_KB_DATA
    """
    blob_root = config["PATH_KB_BLOB"]
    data_root = Path(config["PATH_KB_DATA"])
    now = _now_iso()
    cur = conn.cursor()

    cur.executescript("""
        CREATE TABLE IF NOT EXISTS artifacts_v2 (
            uuid text PRIMARY KEY,
            title text NOT NULL,
            category text NOT NULL,
            current_hash text,
            current_revision integer,
            tags text,
            status text,
            author text,
            template text,
            state text NOT NULL DEFAULT 'alive',
            created_at text NOT NULL,
            updated_at text NOT NULL);
        CREATE TABLE IF NOT EXISTS revisions_v2 (
            id integer PRIMARY KEY,
            artifact_uuid text NOT NULL,
            revision_no integer NOT NULL,
            blob_hash text NOT NULL,
            parent_id integer,
            author text,
            message text,
            created_at text NOT NULL,
            UNIQUE(artifact_uuid, revision_no));
        CREATE TABLE IF NOT EXISTS blobs (
            hash text PRIMARY KEY,
            size integer NOT NULL,
            created_at text NOT NULL);
        CREATE TABLE IF NOT EXISTS tags_v2 (
            artifact_uuid text NOT NULL,
            tag text NOT NULL);
        CREATE TABLE IF NOT EXISTS tombstones (
            artifact_uuid text PRIMARY KEY,
            deleted_at text NOT NULL,
            purge_after text NOT NULL);
        CREATE TABLE IF NOT EXISTS tombstone_blobs (
            artifact_uuid text NOT NULL,
            blob_hash text NOT NULL,
            PRIMARY KEY(artifact_uuid, blob_hash));
    """)

    cur.execute(
        """SELECT id, title, category, path, tags, status, author, template
           FROM artifacts""")
    legacy_artifacts = cur.fetchall()

    id_to_uuid: Dict[int, str] = {}
    for old_id, title, category, old_path, tags, status, author, \
            template in legacy_artifacts:
        artifact_uuid = str(uuidlib.uuid4())
        id_to_uuid[old_id] = artifact_uuid

        content = b""
        candidates = []
        if old_path:
            candidates.append(data_root / old_path)
        candidates.append(data_root / category / title)
        for candidate in candidates:
            if candidate.is_file():
                with open(candidate, "rb") as handle:
                    content = handle.read()
                break

        blob_hash = store.add_blob(blob_root, content)
        blob_size = len(content)

        cur.execute(
            """INSERT INTO artifacts_v2
               (uuid, title, category, current_hash, current_revision,
                tags, status, author, template, state, created_at, updated_at)
               VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, 'alive', ?, ?)""",
            [artifact_uuid, title, category, blob_hash, tags, status,
             author, template, now, now])
        cur.execute(
            """INSERT OR IGNORE INTO blobs (hash, size, created_at)
               VALUES (?, ?, ?)""",
            [blob_hash, blob_size, now])

    # Re-key tags from the legacy integer id to the new UUID; unknown
    # old ids are simply dropped
    try:
        cur.execute("SELECT artifact_id, tag FROM tags")
        for old_artifact_id, tag in cur.fetchall():
            new_uuid = id_to_uuid.get(old_artifact_id)
            if new_uuid and tag:
                cur.execute(
                    "INSERT INTO tags_v2 (artifact_uuid, tag) VALUES (?, ?)",
                    [new_uuid, tag])
    except sqlite3.OperationalError:
        pass

    # Every migrated artifact starts a fresh version chain at
    # revision 1, then repoint current_revision to the new row id
    for old_id in id_to_uuid:
        artifact_uuid = id_to_uuid[old_id]
        cur.execute(
            "SELECT current_hash, author FROM artifacts_v2 WHERE uuid = ?",
            [artifact_uuid])
        blob_hash, author = cur.fetchone()
        cur.execute(
            """INSERT INTO revisions_v2
               (artifact_uuid, revision_no, blob_hash, parent_id,
                author, message, created_at)
               VALUES (?, 1, ?, NULL, ?, 'imported from v1', ?)""",
            [artifact_uuid, blob_hash, author, now])
        rev_pk = cur.lastrowid
        cur.execute(
            "UPDATE artifacts_v2 SET current_revision = ? WHERE uuid = ?",
            [rev_pk, artifact_uuid])

    cur.executescript("""
        DROP TABLE artifacts;
        DROP TABLE tags;
        ALTER TABLE artifacts_v2 RENAME TO artifacts;
        ALTER TABLE tags_v2 RENAME TO tags;
        ALTER TABLE revisions_v2 RENAME TO revisions;
    """)

    conn.commit()
    set_schema_version(conn, 2)
