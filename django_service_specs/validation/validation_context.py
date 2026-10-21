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
    principal and a target is a whole call.

    ``ambient`` is the call's base pool as dispatch resolved it: ``user``,
    ``progress`` and every registered seed - an HTTP adapter's ``request``,
    a view it registers, a tenant - read-only at its top level. Its values
    are the call's own live objects - the principal itself, for one - so a
    Validator must not mutate them
    (test_the_validator_reads_the_registered_seeds_and_the_user holds both
    halves). A library whose validation
    reads what its caller registered, as a serializer reads its context's
    ``request``, finds it here rather than in an argument. It never holds an
    argument, a validated value or the target, which have seats of their
    own. Empty for a context built by hand, and in ``bind_arguments``, which
    is handed no seeds; it trails the others, so neither changes.

    ``resolved`` is the target under the pool name dispatch hands it to the
    service as, read-only: ``{"instance": row}`` for a spec with an instance
    selector - ``{"instance": None}`` when one that allows none finds no row
    - ``{"collection": rows}`` for one with a collection selector, and empty
    for a create. ``target`` is the same object with the role taken off, so a
    callable a Validator resolves through the pool, as ``FormValidator``'s
    ``form_kwargs`` is, names it as a selector or a service does. Dispatch
    fills it from the target it resolved, and ``bind_arguments`` from the
    ``target`` its caller passes and the spec's selectors, by the one rule
    both share. Empty for a context built by hand; it trails the rest, so no
    existing construction changes.
    """

    principal: Any
    target: Any = None
    partial: bool = False
    # Excluded from equality: two contexts of one call are one context whatever
    # the seeds resolved to, and a mapping proxy cannot be hashed. Held by
    # test_two_contexts_differing_in_ambient_alone_are_equal and
    # test_a_context_carrying_ambient_values_is_hashable.
    ambient: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}), compare=False)
    # Excluded from equality and the hash for the reason ``ambient`` is: held
    # by test_two_contexts_differing_in_resolved_alone_are_equal and
    # test_a_context_carrying_a_resolved_target_is_hashable.
    resolved: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}), compare=False)
