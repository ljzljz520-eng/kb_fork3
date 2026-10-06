# -*- encoding: utf-8 -*-
# kb v0.2.0
# A knowledge base organizer
# Copyright © 2020, gnc.
# See /LICENSE for licensing information.

"""
kb undelete command module

Reverses a soft delete while the tombstone is still retained: the
artifact becomes live again with its full revision chain, and the
tombstone blob pins are released.

:Copyright: © 2020, gnc.
:License: GPLv3 (see /LICENSE).
"""

from typing import Dict

import kb.db as db
import kb.initializer as initializer
import kb.history as recent


def undelete(args: Dict[str, str], config: Dict[str, str]):
    """
    Undelete a tombstoned artifact (use 'kb list --deleted' to find
    the list IDs).
    """
    initializer.init(config)

    conn = db.create_connection(config["PATH_KB_DB"])
    artifact = recent.resolve_artifact(conn, args, config, state="deleted")
    if not artifact:
        print("There is no deleted artifact matching the provided "
              "selector within its retention period")
        return

    restored = db.undelete_artifact(conn, artifact.uuid)
    if restored:
        print("Artifact {path} restored (uuid: {uuid})".format(
            path=restored.path, uuid=restored.uuid))
