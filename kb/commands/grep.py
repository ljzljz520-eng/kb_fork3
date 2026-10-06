# -*- encoding: utf-8 -*-
# kb v0.2.0
# A knowledge base organizer
# Copyright © 2020, gnc.
# See /LICENSE for licensing information.

"""
kb grep command module

:Copyright: © 2020, gnc.
:License: GPLv3 (see /LICENSE).
"""

import sys
from typing import Dict

import kb.db as db
import kb.initializer as initializer
import kb.printer.grep as printer
import kb.history as history
import kb.filesystem as fs
import kb.store as store


def grep(args: Dict[str, str], config: Dict[str, str]):
    """
    Grep through the live artifacts of the knowledge base.

    The search runs against the current blob of every live
    artifact; matches are mapped back to artifacts through the
    blob hash.
    """
    initializer.init(config)

    conn = db.create_connection(config["PATH_KB_DB"])

    rows = db.get_artifacts_by_filter(conn, title="")

    # Map each current blob path to its artifact (identical blobs
    # may be shared by several artifacts, hence a list per path)
    path_to_artifacts = {}
    for artifact in rows:
        blob_p = str(store.blob_path(
            config["PATH_KB_BLOB"], artifact.current_hash))
        path_to_artifacts.setdefault(blob_p, []).append(artifact)

    results = fs.grep_in_files(
        list(path_to_artifacts.keys()),
        args["regex"],
        args["case_insensitive"])

    color_mode = not args["no_color"]
    if args["matches"]:
        display_matches = []
        for file_path, line_no, matched_text in results:
            for artifact in path_to_artifacts.get(str(file_path), []):
                display_matches.append(
                    (artifact.path, line_no, matched_text))
        printer.print_grep_matches(display_matches, color_mode)
        sys.exit(0)

    # Aggregate hits per artifact UUID
    hits = {}
    for file_path, line_no, matched_text in results:
        for artifact in path_to_artifacts.get(str(file_path), []):
            hits[artifact.uuid] = hits.get(artifact.uuid, 0) + 1

    artifacts_by_uuid = {a.uuid: a for a in rows}
    grep_result = [artifacts_by_uuid[uuid] for uuid in hits]
    grep_result.sort(key=lambda art: hits[art.uuid], reverse=True)
    grep_hits = [hits[art.uuid] for art in grep_result]

    history.write(config["PATH_KB_HIST"], grep_result)

    if args["verbose"]:
        printer.print_grep_result_verbose(
            grep_result, grep_hits, color_mode)
    else:
        printer.print_grep_result(
            grep_result, grep_hits, color_mode)
