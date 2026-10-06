# -*- encoding: utf-8 -*-
# kb v0.2.0
# A knowledge base organizer
# Copyright © 2020, gnc.
# See /LICENSE for licensing information.

"""
kb artifact frozen dataclass

An artifact is identified by a stable UUID which never changes,
independently of renames or category moves. The title and the
category only represent a mutable *display path mapping*, they are
not part of the artifact identity.

:Copyright: © 2020, gnc.
:License: GPLv3 (see /LICENSE).
"""

import attr
from typing import Optional


@attr.s(auto_attribs=True, frozen=True, slots=True)
class Artifact:
    uuid: Optional[str]
    title: str
    category: str
    current_hash: Optional[str] = None
    tags: Optional[str] = None
    status: Optional[str] = None
    author: Optional[str] = None
    template: Optional[str] = None
    state: str = "alive"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    current_revision: Optional[int] = None

    @property
    def path(self) -> str:
        """The current display path of the artifact (category/title).

        This is purely a presentation helper, the real identity is
        the UUID and the real content lives in the blob store.
        """
        return "{category}/{title}".format(
            category=self.category, title=self.title)
