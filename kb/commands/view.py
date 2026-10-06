# -*- encoding: utf-8 -*-
# kb v0.2.0
# A knowledge base organizer
# Copyright © 2020, gnc.
# See /LICENSE for licensing information.

"""
kb view command module

:Copyright: © 2020, gnc.
:License: GPLv3 (see /LICENSE).
"""

import sys
import shlex
from pathlib import Path
from subprocess import call
from typing import Dict

import kb.db as db
import kb.filesystem as fs
import kb.history as history
import kb.initializer as initializer
import kb.opener as opener
import kb.viewer as viewer
import kb.store as store
from kb.config import get_markers
from kb.entities.artifact import Artifact


def view(args: Dict[str, str], config: Dict[str, str]):
    """
    View an artifact contained in the knowledge base of kb.
    """
    initializer.init(config)

    color_mode = not args["no_color"]
    conn = db.create_connection(config["PATH_KB_DB"])
    artifact = history.resolve_artifact(conn, args, config, state="alive")
    if not artifact:
        print("There is no artifact matching the provided selector")
        return

    view_artifact(artifact, config, args["editor"], color_mode)


def view_artifact(
        artifact: Artifact,
        config: Dict[str, str],
        open_editor: bool,
        color_mode: bool):
    """View a resolved artifact directly from its current blob."""
    blob_path = str(
        store.blob_path(config["PATH_KB_BLOB"], artifact.current_hash))

    if open_editor:
        tmpfname = store.materialize(
            config["PATH_KB_BLOB"],
            artifact.current_hash,
            suffix=Path(artifact.title).suffix)

        shell_cmd = shlex.split(config["EDITOR"]) + [tmpfname]
        call(shell_cmd)
        fs.remove_file(tmpfname)
        sys.exit(0)

    # The text/binary decision is made on the *display name*, since
    # a blob file has no extension. The content itself is identical.
    if fs.is_text_file(artifact.title):
        markers = get_template(artifact, config)
        viewer.view(blob_path, markers, color=color_mode)
    else:
        opener.open_non_text_file(blob_path)


def get_template(artifact: Artifact, config: Dict[str, str]) -> str:
    """"
    Get template for a specific artifact.

    Returns:
    A dictionary containing markers, where the key is a regex
    and the value is a string representing a color.
    """
    template = artifact.template or "default"
    if template == "default":
        markers = get_markers(config["PATH_KB_DEFAULT_TEMPLATE"])
    else:
        markers = get_markers(
            str(Path(*[config["PATH_KB_TEMPLATES"]] + template.split('/'))))
    return markers
