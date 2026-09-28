"""``ValidationContext`` - what a Validator may know besides the arguments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ValidationContext:
    """The principal, and the target the operation acts on.

    ``target`` is here, rather than a constructor keyword the way DRF takes
    ``instance=``, because the kernel is what resolves it: target resolution
    runs **before** validation, so an update's uniqueness check can exclude the
    row being updated. It is the resolved row for a spec with an instance
    selector, the resolved queryset for one with a collection selector, and
    ``None`` for a create.
    """

    principal: Any
    target: Any = None
