# -*- encoding: utf-8 -*-
# kb v0.2.0
# A knowledge base organizer
# Copyright © 2020, gnc.
# See /LICENSE for licensing information.

"""
kb import command module

The archive is restored at the configured kb location (its parent
directory), so UUIDs, revisions and blob hashes carried by the
bundled database and content store are preserved unchanged. Legacy
archives whose root directory is called ``.kb`` are accepted too.

:Copyright: © 2020, gnc.
:License: GPLv3 (see /LICENSE).
"""

import tarfile
from pathlib import Path
from typing import Dict

import kb.filesystem as fs


def ingest(args: Dict[str, str], config: Dict[str, str]):
    """
    Import an entire kb knowledge base.

    Arguments:
    args:           - a dictionary containing the following fields:
                      file -> a string representing the path to the
                      archive to be imported
    config:         - a configuration dictionary containing at least
                      the following key:
                      PATH_KB           - the main path of KB
    """
    if args["file"].endswith(".tar.gz"):
        answer = input("You are about to import a whole knowledge base "
                       "are you sure you want to wipe your previous "
                       " kb data ? [YES/NO]")
        if answer.lower() == "yes":
            print("Previous kb knowledge base data wiped...")
            target = Path(config["PATH_KB"])
            target_parent = target.parent
            legacy_root = target_parent / ".kb"
            try:
                fs.remove_directory(str(target))
            except FileNotFoundError:
                pass
            try:
                fs.remove_directory(str(legacy_root))
            except FileNotFoundError:
                pass

            target_parent.mkdir(parents=True, exist_ok=True)
            with tarfile.open(args["file"], "r:gz") as archive:
                archive.extractall(target_parent)

            # Support legacy archives rooted at ".kb"
            if legacy_root.is_dir() and not target.exists():
                legacy_root.rename(target)

            print("kb archive {fname} imported at {path}".format(
                fname=args["file"], path=target))
    else:
        print("Please provide a file exported through kb with "
              "kb.tar.gz extension")
