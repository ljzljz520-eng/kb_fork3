# -*- encoding: utf-8 -*-
# kb v0.1.8
# A knowledge base organizer
# Copyright © 2020, gnc.
# See /LICENSE for licensing information.

"""
kb search command module

:Copyright: © 2020, gnc.
:License: GPLv3 (see /LICENSE).
"""

from typing import Dict
import kb.db as db
import kb.initializer as initializer
import kb.printer.search as printer
import kb.history as history


def search(args: Dict[str, str], config: Dict[str, str]):
    """
    Search artifacts within the knowledge base of kb.

    Arguments:
    args:           - a dictionary containing the following fields:
                      query -> filter for the title field of the artifact
                      category -> filter for the category field of the artifact
                      tags -> filter for the tags field of the artifact
                      author -> filter for the author field of the artifact
                      status -> filter for the status field of the artifact
    config:         - a configuration dictionary containing at least
                      the following keys:
                      PATH_KB_DB        - the database path of KB
                      PATH_KB_DATA      - the data directory of KB
                      PATH_KB_HIST      - the history menu path of KB
                      EDITOR            - the editor program to call
    """
    # Check initialization
    initializer.init(config)

    tags_list = None
    if args["tags"] and args["tags"] != "":
        tags_list = args["tags"].split(';')

    conn = db.create_connection(config["PATH_KB_DB"])
    state = "deleted" if args.get("deleted") else "alive"

    if state == "deleted":
        deleted = db.get_deleted_artifacts(conn)
        if args["query"]:
            deleted = [entry for entry in deleted
                       if args["query"].lower() in entry[0].title.lower()]
        if args["category"]:
            deleted = [entry for entry in deleted
                       if args["category"].lower()
                       in entry[0].category.lower()]
        artifacts = sorted([entry[0] for entry in deleted],
                           key=lambda x: x.title)
        purge_by_uuid = {entry[0].uuid: entry[2] for entry in deleted}
    else:
        rows = db.get_artifacts_by_filter(
            conn,
            title=args["query"],
            category=args["category"],
            tags=tags_list,
            status=args["status"],
            author=args["author"],
            state="alive")
        artifacts = sorted(rows, key=lambda x: x.title)
        purge_by_uuid = {}

    # Write to history file
    history.write(config["PATH_KB_HIST"], artifacts)

    if state == "deleted":
        print("Deleted artifacts (use 'kb undelete' to restore):")
        for artifact in artifacts:
            print("  {path} (recoverable until {purge})".format(
                path=artifact.path, purge=purge_by_uuid[artifact.uuid]))
        return

    # Is full_identifier mode enabled?
    if args["full_identifier"]:
        printer.print_search_result_full_mode(artifacts)
        return

    # Print resulting list
    color_mode = not args["no_color"]
    if args["verbose"]:
        printer.print_search_result_verbose(artifacts, color_mode)
    else:
        printer.print_search_result(artifacts, color_mode)
