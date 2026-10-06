# -*- encoding: utf-8 -*-
# kb v0.2.0
# A knowledge base organizer
# Copyright © 2020, gnc.
# See /LICENSE for licensing information.

"""
kb revision frozen dataclass

A revision is an immutable link in the version chain of an artifact.
It points to the hash-addressed blob holding the content and to its
parent revision. Revisions are never rewritten: restoring an old
revision always appends a *new* revision referencing the old blob.

:Copyright: © 2020, gnc.
:License: GPLv3 (see /LICENSE).
"""

import attr
from typing import Optional


@attr.s(auto_attribs=True, frozen=True, slots=True)
class Revision:
    id: Optional[int]
    artifact_uuid: str
    revision_no: int
    blob_hash: str
    parent_id: Optional[int] = None
    author: Optional[str] = None
    message: Optional[str] = None
    created_at: Optional[str] = None
