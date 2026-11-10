from __future__ import annotations

from enum import Enum


class UnguardedReason(str, Enum):
    """The declaration that leaves a spec open to every principal."""

    UNRESTRICTED = "unrestricted"
