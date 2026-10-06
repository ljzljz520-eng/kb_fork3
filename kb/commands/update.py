# -*- encoding: utf-8 -*-
# kb v0.2.0
# A knowledge base organizer
# Copyright © 2020, gnc.
# See /LICENSE for licensing information.

"""
kb update command module

Updating the title or the category only changes the *display path
mapping*: the artifact UUID, its revision chain and its referenced
blobs are untouched, hence renames and category moves preserve the
artifact identity. Editing the body instead appends a new revision.

:Copyright: © 2020, gnc.
:License: GPLv3 (see /LICENSE).
"""

import shlex
from pathlib import Path
from subprocess import call
from typing import Dict

import kb.db as db
import kb.initializer as initializer
import kb.history as history
import kb.filesystem as fs
import kb.store as store


def update(args: Dict[str, str], config: Dict[str, str]):
    """
    Update artifact properties and/or content within kb.
    """
    initializer.init(config)

    conn = db.create_connection(config["PATH_KB_DB"])

    artifact = history.resolve_artifact(conn, args, config, state="alive")
    if not artifact:
        print("The artifact you are trying to update does not exist! "
              "Please insert a valid ID/title...")
        return

    # A rename or a category move is just a metadata update: the
    # UUID, current revision and blob hash never change.
    metadata_changed = any(
        args[key] is not None
        for key in ("title", "category", "tags", "author",
                    "status", "template"))

    if metadata_changed:
        updated = db.update_artifact_properties(
            conn,
            artifact.uuid,
            title=args["title"],
            category=args["category"],
            tags=args["tags"],
            author=args["author"],
            status=args["status"],
            template=args["template"])
        if updated is not None:
            artifact = updated
            print("Artifact display path is now {path} (uuid unchanged: "
                  "{uuid})".format(path=artifact.path, uuid=artifact.uuid))

    # Content edits append a new revision instead of overwriting
    if args["edit_content"] or args["body"] is not None:
        if args["body"] is not None:
            data = args["body"].replace("\\n", "\n").encode("utf-8")
            commit_new_content(conn, config, artifact, data)
        else:
            suffix = Path(artifact.title).suffix
            tmp_path = store.materialize(
                config["PATH_KB_BLOB"],
                artifact.current_hash,
                suffix=suffix)
            try:
                shell_cmd = shlex.split(config["EDITOR"]) + [tmp_path]
                call(shell_cmd)
                with open(tmp_path, "rb") as art_file:
                    data = art_file.read()
            finally:
                fs.remove_file(tmp_path)
            commit_new_content(conn, config, artifact, data)


def commit_new_content(conn, config, artifact, data: bytes) -> None:
    """Store new content as a blob and append a revision if changed."""
    blob_hash = store.hash_content(data)
    if blob_hash == artifact.current_hash:
        print("Content unchanged, no new revision created")
        return

    blob_hash = store.add_blob(config["PATH_KB_BLOB"], data)
    revision = db.add_revision(
        conn, artifact.uuid, blob_hash, len(data))
    print("New revision {rev} stored (blob {sha})".format(
        rev=revision.revision_no, sha=blob_hash[:12]))
