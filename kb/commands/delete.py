# -*- encoding: utf-8 -*-
# kb v0.2.0
# A knowledge base organizer
# Copyright © 2020, gnc.
# See /LICENSE for licensing information.

"""
kb delete command module

Deletion is soft: the artifact is marked as deleted and a tombstone
with a retention deadline is recorded. Every blob referenced by its
revisions is pinned by the tombstone, so nothing is reclaimed before
the retention period elapses. Use ``kb undelete`` to undo a delete
and ``kb gc`` to purge expired tombstones.

:Copyright: © 2020, gnc.
:License: GPLv3 (see /LICENSE).
"""

from typing import Dict

import kb.db as db
import kb.initializer as initializer
import kb.history as history


def delete(args: Dict[str, str], config: Dict[str, str]):
    """
    Delete a list of artifacts from the kb knowledge base.
    """
    initializer.init(config)
    conn = db.create_connection(config["PATH_KB_DB"])
    retention_days = int(config.get("TOMBSTONE_RETENTION_DAYS", 30))

    if args["id"]:
        for identifier in args["id"]:
            selector = {"id": identifier, "nameid": None,
                        "title": None, "category": None}
            artifact = history.resolve_artifact(
                conn, selector, config, state="alive")
            if not artifact:
                print("Error: Invalid artifact referenced")
                continue
            delete_artifact(conn, artifact, args["force"],
                            retention_days)
    else:
        artifact = history.resolve_artifact(
            conn, args, config, state="alive")
        if artifact:
            delete_artifact(conn, artifact, args["force"], retention_days)
        else:
            print(
                "There is no (unique) live artifact matching the selector")


def delete_artifact(conn, artifact, is_forced: bool,
                    retention_days: int) -> None:
    """Tombstone a resolved artifact after optional confirmation."""
    if not is_forced:
        confirm = ask_confirmation(artifact.title, artifact.category)
        if not confirm:
            print("No artifact was removed")
            return

    if db.tombstone_artifact(conn, artifact.uuid, retention_days):
        tombstone = db.get_tombstone(conn, artifact.uuid)
        print("Artifact {path} moved to trash (uuid: {uuid}), "
              "recoverable until {purge}".format(
                  path=artifact.path,
                  uuid=artifact.uuid,
                  purge=tombstone[1] if tombstone else "?"))
        print("Use 'kb undelete' to restore it before the retention "
              "period expires")
    else:
        print("Error: artifact could not be deleted (already deleted?)")


def ask_confirmation(title: str, category: str):
    """
    Ask confirmation for the deletion of an artifact

    Returns:
    A boolean that is true if the user really wants to remove
    an artifact, i.e., "y" or "yes" have been typed at the prompt
    """
    answer = input(
        "Are you sure you want to delete {category}/{title}? [y/n]".format(
            category=category, title=title))

    return answer.lower() in ["y", "yes"]
