# -*- encoding: utf-8 -*-
# kb v0.2.0
# A knowledge base organizer
# Copyright © 2020, gnc.
# See /LICENSE for licensing information.

"""
kb restore command module

Restores any retained revision of a live artifact. Restoration
never rewrites history: a brand new revision referencing the old
blob is appended to the chain. The blob content is hash-verified
before being restored.

:Copyright: © 2020, gnc.
:License: GPLv3 (see /LICENSE).
"""

from typing import Dict

import kb.db as db
import kb.initializer as initializer
import kb.history as recent
import kb.store as store


def restore(args: Dict[str, str], config: Dict[str, str]):
    """
    Restore a retained revision of an artifact.
    """
    initializer.init(config)

    revision_no = args.get("revision")
    if revision_no is None:
        print("Please specify the revision to restore with -r/--revision")
        return

    conn = db.create_connection(config["PATH_KB_DB"])
    artifact = recent.resolve_artifact(conn, args, config, state="alive")
    if not artifact:
        print("There is no live artifact matching the provided selector")
        return

    target = db.get_revision(conn, artifact.uuid, int(revision_no))
    if not target:
        print("Error: revision {no} does not exist".format(
            no=revision_no))
        return

    if not store.verify_blob(config["PATH_KB_BLOB"], target.blob_hash):
        print("Error: blob {sha} for revision {no} failed hash "
              "verification, refusing to restore corrupt content".format(
                  sha=target.blob_hash, no=revision_no))
        return

    new_rev = db.restore_revision(conn, artifact.uuid, int(revision_no))
    if new_rev is None:
        print("Revision {no} content is already the current content, "
              "nothing to do".format(no=revision_no))
        return

    print("Revision {no} restored as new revision {new} of {path} "
          "(blob {sha}, hash verified)".format(
              no=revision_no, new=new_rev.revision_no,
              path=artifact.path, sha=target.blob_hash[:12]))
