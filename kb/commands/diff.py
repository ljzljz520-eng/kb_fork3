# -*- encoding: utf-8 -*-
# kb v0.2.0
# A knowledge base organizer
# Copyright © 2020, gnc.
# See /LICENSE for licensing information.

"""
kb diff command module

Shows a unified diff between two retained revisions of an artifact
(by default a revision against its parent, or the current revision
against its parent when no revision is specified).

:Copyright: © 2020, gnc.
:License: GPLv3 (see /LICENSE).
"""

import difflib
from typing import Dict, Optional, Tuple

import kb.db as db
import kb.initializer as initializer
import kb.history as recent
import kb.store as store


def diff(args: Dict[str, str], config: Dict[str, str]):
    """
    Diff revisions of an artifact.
    """
    initializer.init(config)

    conn = db.create_connection(config["PATH_KB_DB"])
    artifact = recent.resolve_artifact(conn, args, config, state="all")
    if not artifact:
        print("There is no artifact matching the provided selector")
        return

    old_rev, new_rev = select_revisions(conn, artifact.uuid, args)
    if old_rev is None or new_rev is None:
        print("Error: invalid revision selection")
        return

    old_data = store.read_blob(config["PATH_KB_BLOB"], old_rev.blob_hash)
    new_data = store.read_blob(config["PATH_KB_BLOB"], new_rev.blob_hash)

    if old_data == new_data:
        print("Revisions {old} and {new} have identical content".format(
            old=old_rev.revision_no, new=new_rev.revision_no))
        return

    if b"\x00" in old_data or b"\x00" in new_data:
        print("Binary content differs between revision {old} and "
              "revision {new}".format(
                  old=old_rev.revision_no, new=new_rev.revision_no))
        return

    old_lines = _normalize_lines(
        old_data.decode("utf-8", errors="replace").splitlines(True))
    new_lines = _normalize_lines(
        new_data.decode("utf-8", errors="replace").splitlines(True))

    difference = difflib.unified_diff(
        old_lines,
        new_lines,
        fromfile="{path}@rev{old}".format(
            path=artifact.path, old=old_rev.revision_no),
        tofile="{path}@rev{new}".format(
            path=artifact.path, new=new_rev.revision_no))

    output = "".join(difference)
    if output:
        print(output, end="")
        if not output.endswith("\n"):
            print()
    else:
        print("No differences")


def _normalize_lines(lines):
    """Ensure the final line is newline-terminated.

    difflib does not emit the standard "No newline at end of file"
    marker when the compared lines lack a terminator, so we add the
    terminator (and the marker) ourselves.
    """
    normalized = list(lines)
    if normalized and not normalized[-1].endswith("\n"):
        normalized[-1] = normalized[-1] + "\n"
        normalized.append("\\ No newline at end of file\n")
    return normalized


def select_revisions(conn, artifact_uuid: str,
                     args: Dict[str, str]) -> Tuple[Optional[object],
                                                    Optional[object]]:
    """
    Resolve the (old, new) revision pair according to -r/--revision
    and -R/--against semantics.

    * -r N -R M: revisions N and M
    * -r N     : revision N against its parent
    * neither  : current revision against its parent
    """
    latest = db.get_latest_revision(conn, artifact_uuid)
    if latest is None:
        return None, None

    if args.get("against") is not None:
        new_no = args["revision"] if args.get("revision") is not None \
            else latest.revision_no
        old_rev = db.get_revision(conn, artifact_uuid, int(args["against"]))
        new_rev = db.get_revision(conn, artifact_uuid, int(new_no))
        return old_rev, new_rev

    if args.get("revision") is not None:
        new_rev = db.get_revision(
            conn, artifact_uuid, int(args["revision"]))
    else:
        new_rev = latest

    if new_rev is None or new_rev.parent_id is None:
        print("Revision has no parent to diff against")
        return None, None
    old_rev = db.get_revision_by_id(conn, new_rev.parent_id)
    return old_rev, new_rev
