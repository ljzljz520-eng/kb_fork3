# -*- encoding: utf-8 -*-
# kb v0.2.0
# A knowledge base organizer
# Copyright © 2020, gnc.
# See /LICENSE for licensing information.

"""
kb gc (garbage collection) command module

Two phases:

1. tombstones past their retention deadline are purged, together
   with their revision rows;
2. blobs whose reference count is zero (no revision and no
   tombstone references them) are deleted from the content store
   and from the blob registry.

Blobs still referenced by any retained revision or any tombstone
can never be reclaimed.

:Copyright: © 2020, gnc.
:License: GPLv3 (see /LICENSE).
"""

from typing import Dict

import kb.db as db
import kb.initializer as initializer
import kb.store as store


def gc(args: Dict[str, str], config: Dict[str, str]):
    """
    Purge expired tombstones and garbage collect unreferenced
    blobs.
    """
    initializer.init(config)

    conn = db.create_connection(config["PATH_KB_DB"])
    dry_run = bool(args.get("dry_run"))
    now = db.utc_now()

    if dry_run:
        expired = [
            entry[0].uuid
            for entry in db.get_deleted_artifacts(conn)
            if entry[2] <= now.isoformat()
        ]
        # Simulate the state once the expired tombstones above
        # have been purged, so counts reflect what a real gc would do
        unreferenced = store.get_unreferenced_blobs(
            conn, purging_uuids=tuple(expired))
        print("Garbage collection dry-run: nothing will be deleted")
        print("  Expired tombstones that would be purged: "
              "{count}".format(count=len(expired)))
        for artifact_uuid in expired:
            print("    - {uuid}".format(uuid=artifact_uuid))
        reclaimed = sum(size or 0 for _, size in unreferenced)
        print("  Unreferenced blobs that would be removed: "
              "{count} ({bytes} bytes)".format(
                  count=len(unreferenced), bytes=reclaimed))
        for digest, _ in unreferenced:
            print("    - {sha}".format(sha=digest))
        return

    purged = db.purge_expired_tombstones(conn, now=now)
    print("Purged {count} expired tombstone(s)".format(count=len(purged)))
    for artifact_uuid in purged:
        print("    - {uuid}".format(uuid=artifact_uuid))

    report = store.garbage_collect(
        config["PATH_KB_BLOB"], conn, dry_run=False)
    print("Removed {count} unreferenced blob(s), reclaimed "
          "{bytes} bytes".format(
              count=report["removed_count"],
              bytes=report["reclaimed_bytes"]))
