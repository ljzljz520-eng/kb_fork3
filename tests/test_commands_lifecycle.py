#!/usr/bin/env python
# -*- encoding: utf-8 -*-
# kb test suite
# Copyright © 2020, gnc.
# See /LICENSE for licensing information.

"""

End-to-end tests of the artifact lifecycle through the command
layer, including the three core guarantees:

* rename/category move preserves artifact identity;
* any retained revision can be restored and its blob verified;
* garbage collection only removes unreferenced blobs.

Also covers migration from a legacy v1 on-disk knowledge base.
"""

import hashlib
import sqlite3
import stat
from datetime import timedelta
from pathlib import Path

import pytest

import kb.db as db
import kb.initializer as initializer
import kb.store as store
from kb.commands import add as add_cmd
from kb.commands import delete as delete_cmd
from kb.commands import diff as diff_cmd
from kb.commands import edit as edit_cmd
from kb.commands import gc as gc_cmd
from kb.commands import grep as grep_cmd
from kb.commands import history as history_cmd
from kb.commands import restore as restore_cmd
from kb.commands import search as search_cmd
from kb.commands import undelete as undelete_cmd
from kb.commands import update as update_cmd
from kb.commands import view as view_cmd


def make_config(base: Path) -> dict:
    return {
        "PATH_KB": str(base),
        "PATH_KB_DB": str(base / "kb.db"),
        "PATH_KB_HIST": str(base / "recent.hist"),
        "PATH_KB_DATA": str(base / "data"),
        "PATH_KB_BLOB": str(base / "blob"),
        "PATH_KB_GIT": str(base / ".git"),
        "PATH_KB_CONFIG": str(base / "kb.conf.py"),
        "PATH_KB_TEMPLATES": str(base / "templates"),
        "PATH_KB_DEFAULT_TEMPLATE": str(base / "templates" / "default"),
        "DB_SCHEMA_VERSION": 2,
        "EDITOR": "true",
        "INITIAL_CATEGORIES": ["default"],
        "TOMBSTONE_RETENTION_DAYS": 30,
    }


def args(**overrides):
    base = {
        "file": [], "title": None, "category": None, "tags": None,
        "author": None, "status": None, "template": None,
        "body": None, "id": None, "nameid": None,
        "edit_content": False, "force": False, "no_color": True,
        "query": "", "verbose": False, "full_identifier": False,
        "deleted": False, "revision": None, "against": None,
        "verify": False, "full_hash": False, "dry_run": False,
        "regex": "", "case_insensitive": False, "matches": False,
        "editor": False,
    }
    base.update(overrides)
    return base


@pytest.fixture()
def config(tmp_path):
    cfg = make_config(tmp_path / "kbhome")
    initializer.init(cfg)
    return cfg


def _conn(cfg):
    return db.create_connection(cfg["PATH_KB_DB"])


def test_full_lifecycle_identity_restore_and_gc(config, capsys):
    # --- add initial content ---
    add_cmd.add(
        args(file=[], title="note", category="cheats",
             body="version one\n"),
        config)
    conn = _conn(config)
    artifact = db.get_uniq_artifact_by_filter(
        conn, title="note", category="cheats", is_strict=True)
    original_uuid = artifact.uuid
    hash_v1 = artifact.current_hash

    # content lives in the blob store, not at a display path
    assert store.blob_path(
        config["PATH_KB_BLOB"], hash_v1).is_file()
    assert not (Path(config["PATH_KB_DATA"]) / "cheats" / "note").exists()

    # --- rename + category move must preserve identity ---
    search_cmd.search(args(query=""), config)  # fills recent.hist
    update_cmd.update(
        args(id="0", title="note-renamed", category="guides"),
        config)

    conn = _conn(config)
    moved = db.get_artifact_by_uuid(conn, original_uuid)
    assert moved is not None
    assert moved.title == "note-renamed"
    assert moved.category == "guides"
    assert moved.uuid == original_uuid
    assert moved.current_hash == hash_v1
    # no new revision was introduced by a rename
    assert len(db.get_revisions(conn, original_uuid)) == 1

    # --- edit appends a new revision ---
    search_cmd.search(args(query=""), config)
    update_cmd.update(
        args(id="0", body="version two\n"), config)
    conn = _conn(config)
    revisions = db.get_revisions(conn, original_uuid)
    assert [r.revision_no for r in revisions] == [1, 2]
    assert revisions[1].parent_id == revisions[0].id
    hash_v2 = revisions[1].blob_hash

    # grep matches the current blob and maps back to display path
    grep_cmd.grep(args(regex="version two"), config)
    grep_out = capsys.readouterr().out
    assert "note-renamed" in grep_out and "guides" in grep_out

    # --- history reports the chain with verified hashes ---
    history_cmd.history(
        args(title="note-renamed", category="guides", verify=True),
        config)
    hist_out = capsys.readouterr().out
    assert "rev 1" in hist_out and "rev 2" in hist_out
    assert "parent 1" in hist_out
    assert "[verify: OK]" in hist_out

    # --- diff between revisions ---
    diff_cmd.diff(
        args(title="note-renamed", category="guides", revision=2),
        config)
    diff_out = capsys.readouterr().out
    assert "-version one" in diff_out
    assert "+version two" in diff_out

    # --- restore revision 1: hash verified, new child revision ---
    restore_cmd.restore(
        args(title="note-renamed", category="guides", revision=1),
        config)
    restore_out = capsys.readouterr().out
    assert "restored as new revision 3" in restore_out
    assert "hash verified" in restore_out

    conn = _conn(config)
    latest = db.get_latest_revision(conn, original_uuid)
    assert latest.revision_no == 3
    assert latest.blob_hash == hash_v1
    assert latest.parent_id == revisions[1].id

    # view renders the restored (r1) content
    view_cmd.view(
        args(title="note-renamed", category="guides"), config)
    assert "version one" in capsys.readouterr().out

    # --- delete: tombstone, content retained ---
    delete_cmd.delete(
        args(title="note-renamed", category="guides", force=True),
        config)
    delete_out = capsys.readouterr().out
    assert "moved to trash" in delete_out

    conn = _conn(config)
    assert db.get_artifact_by_uuid(conn, original_uuid).state == \
        "deleted"
    # blobs still on disk and pinned
    assert store.blob_path(config["PATH_KB_BLOB"], hash_v1).is_file()
    assert store.blob_path(config["PATH_KB_BLOB"], hash_v2).is_file()

    # gc with unexpired tombstone collects nothing
    gc_cmd.gc(args(dry_run=True), config)
    dry_out = capsys.readouterr().out
    assert "would be purged: 0" in dry_out
    assert "would be removed: 0" in dry_out

    # deleted listing + undelete
    search_cmd.search(args(query="", deleted=True), config)
    deleted_out = capsys.readouterr().out
    assert "note-renamed" in deleted_out
    search_cmd.search(args(query="", deleted=True), config)
    capsys.readouterr()
    undelete_cmd.undelete(
        args(title="note-renamed", category="guides"), config)
    conn = _conn(config)
    assert db.get_artifact_by_uuid(
        conn, original_uuid).state == "alive"
    # all revisions survived the delete/undelete round-trip
    assert len(db.get_revisions(conn, original_uuid)) == 3

    # --- delete again, expire, purge, collect ---
    delete_cmd.delete(
        args(title="note-renamed", category="guides", force=True),
        config)
    capsys.readouterr()
    conn = _conn(config)
    # move the purge deadline into the past
    past = (db.utc_now() - timedelta(days=1)).isoformat()
    conn.execute(
        "UPDATE tombstones SET purge_after = ? WHERE artifact_uuid = ?",
        [past, original_uuid])
    conn.commit()

    gc_cmd.gc(args(dry_run=False), config)
    gc_out = capsys.readouterr().out
    assert "Purged 1 expired tombstone(s)" in gc_out
    assert "Removed 2 unreferenced blob(s)" in gc_out
    assert not store.blob_path(
        config["PATH_KB_BLOB"], hash_v1).exists()
    assert not store.blob_path(
        config["PATH_KB_BLOB"], hash_v2).exists()


def test_edit_command_appends_revision(config, tmp_path, capsys):
    add_cmd.add(args(title="editable", body="line one\n"), config)

    editor_script = tmp_path / "append_editor.sh"
    editor_script.write_text(
        '#!/bin/sh\necho "line two" >> "$1"\n')
    editor_script.chmod(
        editor_script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP |
        stat.S_IXOTH)
    config["EDITOR"] = str(editor_script)

    search_cmd.search(args(query=""), config)
    edit_cmd.edit(args(id="0"), config)
    out = capsys.readouterr().out
    assert "New revision 2" in out

    conn = _conn(config)
    artifact = db.get_uniq_artifact_by_filter(
        conn, title="editable", is_strict=True)
    assert store.read_blob(
        config["PATH_KB_BLOB"], artifact.current_hash) == \
        b"line one\nline two\n"

    # running the editor without changes does not create a revision
    config["EDITOR"] = "true"
    edit_cmd.edit(
        args(title="editable", category=None), config)
    assert "Content unchanged" in capsys.readouterr().out
    conn = _conn(config)
    assert len(db.get_revisions(conn, artifact.uuid)) == 2


def test_v1_to_v2_migration(tmp_path):
    base = tmp_path / "oldkb"
    base.mkdir()
    data_dir = base / "data" / "cheats"
    data_dir.mkdir(parents=True)
    legacy_content = b"legacy body\n"
    (data_dir / "oldnote").write_bytes(legacy_content)

    db_path = base / "kb.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""CREATE TABLE artifacts (
        id integer PRIMARY KEY, title text NOT NULL,
        category text NOT NULL, path text NOT NULL, tags text,
        status text, author text, template text);
    CREATE TABLE tags (
        artifact_id integer, tag text,
        FOREIGN KEY(artifact_id) REFERENCES artifacts(id));
    """)
    conn.execute(
        """INSERT INTO artifacts
           (id, title, category, path, tags, status, author, template)
           VALUES (1, 'oldnote', 'cheats', 'cheats/oldnote', 'x;y',
                   'draft', 'alice', NULL)""")
    conn.execute("INSERT INTO tags (artifact_id, tag) VALUES (1, 'x')")
    conn.execute("INSERT INTO tags (artifact_id, tag) VALUES (1, 'y')")
    # a genuine v1 database is stamped with schema version 1
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()

    cfg = make_config(base)
    # init detects the v1 schema and migrates in place
    initializer.init(cfg)
    assert db.is_schema_updated_to_version(
        db.create_connection(cfg["PATH_KB_DB"]), 2)

    conn = db.create_connection(cfg["PATH_KB_DB"])
    artifact = db.get_uniq_artifact_by_filter(
        conn, title="oldnote", category="cheats", is_strict=True)
    assert artifact is not None
    assert artifact.uuid  # stable identity assigned
    expected_hash = hashlib.sha256(legacy_content).hexdigest()
    assert artifact.current_hash == expected_hash

    # content imported into the blob store and hash-verifiable
    assert store.verify_blob(cfg["PATH_KB_BLOB"], expected_hash)
    assert store.read_blob(
        cfg["PATH_KB_BLOB"], expected_hash) == legacy_content

    revisions = db.get_revisions(conn, artifact.uuid)
    assert len(revisions) == 1
    assert revisions[0].revision_no == 1

    # tags re-keyed to the new UUID
    tagged = db.get_artifacts_by_tags(conn, tags=["x"], is_strict=True)
    assert [art.uuid for art in tagged] == [artifact.uuid]
