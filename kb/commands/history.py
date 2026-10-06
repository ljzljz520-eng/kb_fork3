# -*- encoding: utf-8 -*-
# kb v0.2.0
# A knowledge base organizer
# Copyright © 2020, gnc.
# See /LICENSE for licensing information.

"""
kb history command module

Lists the immutable revision chain of an artifact: every revision
number, its parent revision, the referenced blob hash and the
creation timestamp. Blob hashes can optionally be verified against
the content store.

:Copyright: © 2020, gnc.
:License: GPLv3 (see /LICENSE).
"""

from typing import Dict

import kb.db as db
import kb.initializer as initializer
import kb.history as recent
import kb.store as store


def history(args: Dict[str, str], config: Dict[str, str]):
    """
    Show the revision history of an artifact.
    """
    initializer.init(config)

    conn = db.create_connection(config["PATH_KB_DB"])
    # History can be inspected both for live and deleted artifacts
    artifact = recent.resolve_artifact(conn, args, config, state="all")
    if not artifact:
        print("There is no artifact matching the provided selector")
        return

    revisions = db.get_revisions(conn, artifact.uuid)
    if not revisions:
        print("No revisions found for {path}".format(path=artifact.path))
        return

    id_to_no = {rev.id: rev.revision_no for rev in revisions}

    print("Revision history of {path} (uuid: {uuid})".format(
        path=artifact.path, uuid=artifact.uuid))
    for rev in revisions:
        parent = id_to_no.get(rev.parent_id) if rev.parent_id else None
        parent_str = str(parent) if parent is not None else "-"
        digest = rev.blob_hash if args.get("full_hash") else \
            rev.blob_hash[:12]

        integrity = ""
        if args.get("verify"):
            ok = store.verify_blob(config["PATH_KB_BLOB"], rev.blob_hash)
            integrity = "  [verify: OK]" if ok else \
                "  [verify: FAILED]"

        message = rev.message or ""
        print("  rev {no:<3d} {created}  blob {sha}  parent {parent}"
              "{integrity}  {message}".format(
                  no=rev.revision_no,
                  created=(rev.created_at or "")[:19],
                  sha=digest,
                  parent=parent_str,
                  integrity=integrity,
                  message=message))
