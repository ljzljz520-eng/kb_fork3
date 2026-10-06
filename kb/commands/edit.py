# -*- encoding: utf-8 -*-
# kb v0.2.0
# A knowledge base organizer
# Copyright © 2020, gnc.
# See /LICENSE for licensing information.

"""
kb edit command module

Editing no longer overwrites content in place: the current blob is
materialized in a temporary file, the editor runs on it and, when
the content changes, a brand new revision referencing the new blob
is appended to the artifact's version chain.

:Copyright: © 2020, gnc.
:License: GPLv3 (see /LICENSE).
"""

import shlex
from pathlib import Path
from subprocess import call
from typing import Dict, Optional

import kb.db as db
import kb.initializer as initializer
import kb.history as history
import kb.filesystem as fs
import kb.store as store


def edit(args: Dict[str, str], config: Dict[str, str]):
    """
    Edit the content of an artifact, appending a new revision if the
    content changed.
    """
    initializer.init(config)

    conn = db.create_connection(config["PATH_KB_DB"])
    artifact = history.resolve_artifact(conn, args, config, state="alive")
    if not artifact:
        print("Error: no valid live artifact matched the selector")
        return

    edit_artifact(conn, artifact, config)


def edit_artifact(conn, artifact, config: Dict[str, str]) -> Optional[int]:
    """
    Edit the content of an already-resolved artifact.

    Returns:
    The new revision number if a revision was appended, None
    otherwise.
    """
    suffix = Path(artifact.title).suffix
    tmp_path = store.materialize(
        config["PATH_KB_BLOB"], artifact.current_hash, suffix=suffix)
    try:
        shell_cmd = shlex.split(config["EDITOR"]) + [tmp_path]
        call(shell_cmd)

        with open(tmp_path, "rb") as handle:
            data = handle.read()
    finally:
        fs.remove_file(tmp_path)

    blob_hash = store.hash_content(data)
    if blob_hash == artifact.current_hash:
        print("Content unchanged, no new revision created")
        return None

    blob_hash = store.add_blob(config["PATH_KB_BLOB"], data)
    revision = db.add_revision(
        conn, artifact.uuid, blob_hash, len(data))
    print("New revision {rev} stored for {path} (blob {sha})".format(
        rev=revision.revision_no, path=artifact.path,
        sha=blob_hash[:12]))
    return revision.revision_no
