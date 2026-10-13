"""``ValidationContext`` - what a Validator may know besides the arguments."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ValidationContext:
    """The principal, the target the operation acts on, and whether the call is partial.

    ``target`` is here, rather than a constructor keyword the way DRF takes
    ``instance=``, because the kernel is what resolves it: target resolution
    runs **before** validation, so an update's uniqueness check can exclude the
    row being updated. It is the resolved row for a spec with an instance
    selector, the resolved queryset for one with a collection selector, and
    ``None`` for a create.

    ``partial`` is true for a call that may leave out any parameter, an update
    of only what it names: the shape check in front of the Validator has not
    refused an absent required one. A Validator then returns only the fields
    the caller sent, or refuses the call with ``ImproperlyConfigured`` if it
    cannot. It trails the other two with a default, so a context built from a
    principal and a target is a whole call, as it always was.
    """

    principal: Any
    target: Any = None
    partial: bool = False
