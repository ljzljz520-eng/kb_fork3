# -*- encoding: utf-8 -*-
# kb v0.2.0
# A knowledge base organizer
# Copyright © 2020, gnc.
# See /LICENSE for licensing information.

"""
kb recent-results history module

The "history" file only maps the ephemeral list IDs shown by
``kb list``/``kb grep`` to the *stable UUID* of the corresponding
artifact. It has nothing to do with the artifact revision history
(which is stored in the database, see ``kb.commands.history``).

:Copyright: © 2020, gnc.
:License: GPLv3 (see /LICENSE).
"""

from typing import List, Optional
from kb.entities.artifact import Artifact
import kb.db as db


def get_artifact_uuid(hist_file_path: str, list_id) -> Optional[str]:
    """
    Get the artifact UUID related to an artifact based on the list
    ID (the ID shown by kb list).

    Arguments:
    hist_file_path      - the path to the history file
                          ($HOME/.local/share/kb/recent.hist by
                          default)
    list_id             - the ID shown by kb list

    Returns:
    The UUID corresponding to the artifact or None for an invalid
    list ID.
    """
    target = str(list_id)
    try:
        with open(hist_file_path, 'r') as hfile:
            for line in hfile:
                items = line.rstrip("\n").split(",", 1)
                if len(items) == 2 and items[0] == target:
                    return items[1]
    except FileNotFoundError:
        return None
    return None


def write(hist_file_path: str, search_result: List) -> None:
    """
    Write the kb history file with the results of a search/list
    operation, mapping each view ID to an artifact UUID.
    """
    with open(hist_file_path, "w") as hfile:
        hfile.write('view_id,artifact_uuid\n')
        for view_id, result in enumerate(search_result):
            hfile.write("{},{}\n".format(view_id, result.uuid))


def get_artifact(conn, hist_file_path: str, list_id) -> Optional[Artifact]:
    """
    Get an artifact based on the list ID (the ID shown by kb list).

    Returns:
    The artifact corresponding to list_id shown by kb list,
    None for a non-valid list ID.
    """
    artifact_uuid = get_artifact_uuid(hist_file_path, list_id)
    if artifact_uuid is None:
        return None
    return db.get_artifact_by_uuid(conn, artifact_uuid)


def resolve_artifact(
        conn,
        args: dict,
        config: dict,
        state: str = "alive") -> Optional[Artifact]:
    """
    Resolve an artifact from the usual command selectors:

    * ``-i/--id`` or an all-digits ``nameid``: the list ID recorded
      in the recent results history;
    * ``-t/--title`` (plus optional ``-c/--category``) or a textual
      ``nameid``: unique title/category lookup.

    Arguments:
    state   - "alive" (default) to resolve only live artifacts,
              "deleted" for tombstoned ones, "all" for both
    """
    artifact = None
    identifier = args.get("id") or args.get("nameid")

    if identifier is not None and str(identifier).isdigit():
        artifact = get_artifact(
            conn, config["PATH_KB_HIST"], identifier)
    else:
        title = args.get("title")
        if title is None and identifier is not None and not \
                str(identifier).isdigit():
            title = identifier
        if title is not None:
            artifact = db.get_uniq_artifact_by_filter(
                conn,
                title=title,
                category=args.get("category"),
                is_strict=True,
                state=state)

    if artifact and state != "all" and artifact.state != state:
        return None
    return artifact
