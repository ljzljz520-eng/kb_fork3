# -*- encoding: utf-8 -*-
# kb v0.2.0
# A knowledge base organizer
# Copyright © 2020, gnc.
# See /LICENSE for licensing information.

"""
kb add command module

:Copyright: © 2020, gnc.
:License: GPLv3 (see /LICENSE).
"""

import shlex
import sys
from pathlib import Path
from subprocess import call
from typing import Dict

import kb.db as db
import kb.initializer as initializer
import kb.filesystem as fs
import kb.store as store
from kb.entities.artifact import Artifact


def add(args: Dict[str, str], config: Dict[str, str]):
    """
    Adds a list of artifacts to the knowledge base of kb.

    The content is immediately stored as a hash-addressed blob and
    referenced by revision 1 of a brand new artifact UUID.
    """
    is_valid_add = args["file"] or args["title"]
    if not is_valid_add:
        print("Please, either specify a file or a title for the new artifact")
        sys.exit(1)

    initializer.init(config)

    conn = db.create_connection(config["PATH_KB_DB"])
    if args["file"]:
        for fname in args["file"]:
            if fs.is_directory(fname):
                continue
            add_file_to_kb(conn, args, config, fname)
    else:
        title = args["title"]
        category = args["category"] or "default"

        if args["body"] is not None:
            data = args["body"].replace("\\n", "\n").encode("utf-8")
        elif not sys.stdin.isatty():
            data = sys.stdin.buffer.read()
        else:
            data = edit_new_content(title, config)

        artifact_uuid = create_artifact_from_content(
            conn, config, title, category, data, args)
        if artifact_uuid:
            print("Artifact {category}/{title} added (uuid: {uuid})".format(
                category=category, title=title, uuid=artifact_uuid))


def edit_new_content(title: str, config: Dict[str, str]) -> bytes:
    """Open the editor on a temporary file and return its content."""
    suffix = Path(title).suffix
    tmp_path = fs.get_temp_filepath(suffix=suffix)
    try:
        shell_cmd = shlex.split(config["EDITOR"]) + [tmp_path]
        call(shell_cmd)
        try:
            with open(tmp_path, "rb") as art_file:
                return art_file.read()
        except FileNotFoundError:
            return b""
    finally:
        fs.remove_file(tmp_path)


def create_artifact_from_content(
        conn,
        config: Dict[str, str],
        title: str,
        category: str,
        data: bytes,
        args: Dict[str, str]) -> str:
    """Store content as a blob and create the artifact + revision 1."""
    # Reject duplicates before materializing any blob, so failed
    # additions never leave orphan files in the content store
    if db.is_artifact_existing(conn, title, category):
        print("Error: the specified artifact already exists in kb!")
        print("Run `kb update -h` to understand how to update an artifact")
        return None

    blob_hash = store.add_blob(config["PATH_KB_BLOB"], data)

    new_artifact = Artifact(
        uuid=None, title=title, category=category,
        current_hash=blob_hash,
        tags=args["tags"],
        status=args["status"], author=args["author"],
        template=args["template"])
    return db.create_artifact(
        conn, new_artifact, blob_hash, len(data))


def validate(args):
    """
    Validate arguments for the add command

    Returns:
    A boolean, True if the add command is valid
    """
    return bool(args["file"] or args["title"])


def add_file_to_kb(
        conn,
        args: Dict[str, str],
        config: Dict[str, str],
        fname: str
) -> None:
    """
    Adds a file to the kb knowledge base, importing its bytes into
    the content store.
    """
    title = args["title"] or fs.get_basename(fname)
    category = args["category"] or "default"
    template = args["template"] or "default"

    try:
        with open(fname, "rb") as handle:
            data = handle.read()
    except FileNotFoundError:
        print("Error: The specified file does not exist!")
        sys.exit(1)

    add_args = dict(args)
    add_args["template"] = template

    artifact_uuid = create_artifact_from_content(
        conn, config, title, category, data, add_args)
    if artifact_uuid:
        print("Artifact {category}/{title} added (uuid: {uuid})".format(
            category=category, title=title, uuid=artifact_uuid))
