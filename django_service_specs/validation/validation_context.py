"""``ValidationContext`` - what a Validator may know besides the arguments."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class ValidationContext:
    """The principal, the target the operation acts on, whether the call is partial, and its seeds.

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

    ``ambient`` is the call's base pool as dispatch resolved it: ``user``,
    ``progress`` and every registered seed - an HTTP adapter's ``request``,
    a view it registers, a tenant - read-only. A library whose validation
    reads what its caller registered, as a serializer reads its context's
    ``request``, finds it here rather than in an argument. It never holds an
    argument, a validated value or the target, which have seats of their
    own. Empty for a context built by hand, and in ``bind_arguments``, which
    is handed no seeds; it trails the others, so neither changes.
    """

    principal: Any
    target: Any = None
    partial: bool = False
    # Excluded from equality: two contexts of one call are one context whatever
    # the seeds resolved to, and a mapping proxy cannot be hashed. Held by
    # test_two_contexts_differing_in_ambient_alone_are_equal and
    # test_a_context_carrying_ambient_values_is_hashable.
    ambient: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}), compare=False)
