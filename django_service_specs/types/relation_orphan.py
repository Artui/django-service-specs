from __future__ import annotations

from enum import Enum


class RelationOrphan(str, Enum):
    """How a relation disposes of a row it no longer holds."""

    AUTO = "auto"
    """Derive it from the link: unlink when it can hold ``NULL``, else delete.

    Mirroring ``on_delete=SET_NULL`` versus ``CASCADE``, which is the better
    default because it honours what the model already declares.
    """

    UNLINK = "unlink"
    """Always blank the row's link to the parent and leave the row standing.

    Refused when the link cannot hold ``NULL`` — there is nothing to blank, and
    deleting the row instead would be the opposite of what was asked.
    """

    DELETE = "delete"
    """Always delete the row, whether or not its link could have been blanked."""


__all__ = ["RelationOrphan"]
