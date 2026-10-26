"""``PresentationContext`` - what a Presenter may know about the call besides the value."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any


@dataclass(frozen=True)
class PresentationContext:
    """The principal a call ran for, its target, its seeds, its context and its shapes.

    The output-side counterpart of
    [`ValidationContext`][django_service_specs.validation.validation_context.ValidationContext].
    Dispatch builds one per call and carries it on the
    [`DispatchResult`][django_service_specs.dispatch.dispatch_result.DispatchResult],
    and [`present`][django_service_specs.dispatch.present.present] hands it to
    [`Presenter.presented()`][django_service_specs.output.presenter.Presenter.presented]
    with every value it presents, so a library that renders under a context -
    a field defaulting to the current user, a link built from the request - can
    read the call it is rendering for.

    - ``principal`` is who the call ran for.
    - ``target`` is the row or the queryset a service spec resolved, ``None``
      for a create and for a selector spec, whose rows are the value itself.
    - ``ambient`` is the call's base pool, read-only at its top level:
      ``user``, ``progress`` and every registered seed, such as an HTTP
      adapter's ``request``. Its values are the call's own live objects, so a
      presenter must not mutate them
      (test_a_selector_spec_s_rows_are_each_presented_with_the_call_s_context
      holds both halves). Never an argument, a validated value or a
      provider's key.
    - ``call_context`` is the call's context, the one plain ``dict`` the
      transport created for its scope and every stage that declares it
      received, as on ``ValidationContext``: the Validator, the service and
      the presenter share one object, so a presenter - and a nested one
      handed the same context - reuses what an earlier stage put there. It is
      the presenter's to read and write; the kernel writes nothing to it. A
      context built by hand gets an empty dict of its own. Its
      ``"transport"`` key, where set, names the transport serving the call
      (``"agent"``, ``"http"``, ``"mcp"``): a family convention the kernel
      neither sets nor checks, so read it with ``.get``.
    - ``shapes`` is what the caller sent for the spec's declared ``shapes``,
      the arguments that shape the output - which fields, a query over the
      rows - by name, read-only. An argument the caller left out is absent
      rather than ``None``. Empty for a spec that declares none and for a
      context built by hand; no other argument is ever here.
    """

    principal: Any
    target: Any = None
    # Excluded from equality, as on ``ValidationContext``: a mapping proxy
    # cannot be hashed, and two contexts of one call are one context. Held by
    # test_two_contexts_differing_in_ambient_alone_are_equal and
    # test_a_context_carrying_ambient_values_is_hashable_where_its_target_is.
    ambient: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}), compare=False)
    # Both out of equality and the hash, as ``ambient`` is: a dict and the
    # lists a caller sends as a shape cannot be hashed, and the context is the
    # one field a stage changes. Held by
    # test_two_contexts_differing_in_call_context_or_shapes_alone_are_equal and
    # test_a_context_carrying_a_call_context_and_shapes_is_hashable. A factory
    # rather than a shared default, so no two contexts write to one dict
    # (test_each_context_built_by_hand_has_a_call_context_of_its_own).
    call_context: dict[str, Any] = field(default_factory=dict, compare=False)
    shapes: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}), compare=False)
