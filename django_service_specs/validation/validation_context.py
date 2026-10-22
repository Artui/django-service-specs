"""``ValidationContext`` - what a Validator may know besides the arguments."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class ValidationContext:
    """The principal, the target, whether the call is partial, its seeds, and the call's context.

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

    ``call_context`` is the call's context: one plain ``dict`` the transport
    creates for its natural scope - a request, an agent run - and hands to
    dispatch, which every stage that declares it receives as the same object.
    A Validator reads it and writes to it directly, as a DRF serializer does
    its ``context``, and a later stage of the call reuses what it put there
    rather than computing it again. Unlike ``ambient`` it is the transport's
    and the stages' to change; the kernel writes nothing to it. A context
    built by hand gets an empty dict of its own, never one shared with
    another, so a Validator that writes to it needs no guard for a call that
    was handed none. It trails every other field, so no existing
    construction changes.
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
    # Out of equality and the hash for the reason ``ambient`` is, and because
    # it is the one field a stage changes: a context's identity cannot move
    # with what a stage writes. Held by
    # test_two_contexts_differing_in_call_context_alone_are_equal and
    # test_a_context_carrying_a_call_context_is_hashable. A factory rather
    # than a shared default, so no two contexts write to one dict
    # (test_each_context_built_by_hand_has_a_call_context_of_its_own).
    call_context: dict[str, Any] = field(default_factory=dict, compare=False)
