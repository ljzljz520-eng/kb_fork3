# -*- encoding: utf-8 -*-
# kb v0.2.0
# A knowledge base organizer
# Copyright © 2020, gnc.
# See /LICENSE for licensing information.

"""
kb export command module

A full export bundles the database and the content store, so
artifact UUIDs, revisions and blob hashes are preserved verbatim on
import (renames, imports or multi-device copies do not change
identity). The ``--only-data`` export materializes the current
content of live artifacts as a plain category/title directory tree.

:Copyright: © 2020, gnc.
:License: GPLv3 (see /LICENSE).
"""

import shutil
import tarfile
import tempfile
import time
from pathlib import Path
from typing import Dict

import kb.db as db
import kb.initializer as initializer
import kb.store as store


def export(args: Dict[str, str], config: Dict[str, str]):
    """
    Export the entire kb knowledge base.
    """
    initializer.init(config)

    fname = args["file"] or time.strftime("%d_%m_%Y-%H%M%S")
    archive_ext = ".kb.tar.gz"
    if not fname.endswith(archive_ext):
        fname = fname + archive_ext

    if args["only_data"]:
        staging = Path(tempfile.mkdtemp(prefix="kb-export-")) / "kb"
        materialize_data_tree(staging, config)
        try:
            with tarfile.open(fname, mode='w:gz') as archive:
                archive.add(str(staging), arcname="kb")
        finally:
            shutil.rmtree(staging.parent, ignore_errors=True)
    else:
        # The archive root is the base name of the kb path, so an
        # import restores it at the configured location verbatim
        with tarfile.open(fname, mode='w:gz') as archive:
            archive.add(
                config["PATH_KB"],
                arcname=Path(config["PATH_KB"]).name,
                recursive=True)


def materialize_data_tree(destination: Path, config: Dict[str, str]):
    """
    Write the current blob of every live artifact at its display
    path category/title under the provided destination directory.
    """
    conn = db.create_connection(config["PATH_KB_DB"])
    artifacts = db.get_artifacts_by_filter(conn, title="")
    for artifact in artifacts:
        target = Path(destination, artifact.category, artifact.title)
        target.parent.mkdir(parents=True, exist_ok=True)
        data = store.read_blob(
            config["PATH_KB_BLOB"], artifact.current_hash)
        with open(target, "wb") as handle:
            handle.write(data)
