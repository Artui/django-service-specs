from __future__ import annotations

from typing import Any


def is_deactivated(principal: Any) -> bool:
    """True for an authenticated principal whose ``is_active`` is false."""
    return bool(getattr(principal, "is_authenticated", True)) and not getattr(
        principal, "is_active", True
    )
