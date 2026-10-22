"""``bind_arguments`` - the shape check and the Validator, for a caller outside dispatch."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django_service_specs.dispatch.utils import shape_check, target_entry, validate_arguments
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource
from django_service_specs.types.unknown_arguments import UnknownArguments


def bind_arguments(
    spec: ServiceSpec | SelectorSpec | SpecSource,
    arguments: Mapping[str, Any],
    *,
    principal: Any,
    target: Any = None,
    unknown_arguments: UnknownArguments = UnknownArguments.REJECT,
    call_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Check ``arguments`` against the spec's parameters, then validate them.

    The bind a transport calls when it binds input itself rather than through
    ``dispatch`` - an MCP server answering a malformed call before it opens a
    transaction, a queue validating a task in the worker. It is the same two
    steps dispatch takes, so a transport that binds for itself cannot drift
    from the gate dispatch applies. ``spec`` may be a
    [`SpecSource`][django_service_specs.specs.spec_source.SpecSource], bound as
    the spec it compiles to:

    1. [`check_arguments`][django_service_specs.parameters.check_arguments.check_arguments]
       over ``spec.parameters()``, under ``unknown_arguments``: the closed
       argument set and the shape check, at every level, relaxing what
       dispatch relaxes: an absent Validator field when the service spec is
       ``partial``, one its ``input_data`` provider fills or may fill, and a
       read the ``kwargs`` provider of the spec declaring it fills or may
       fill - a typed provider's filled and declinable keys, and every
       parameter an untyped provider's values reach.
    2. For a [`ServiceSpec`][django_service_specs.specs.service_spec.ServiceSpec]
       with a Validator, ``validated()`` on only the arguments the Validator's
       own ``parameters()`` declare - never a selector's or the spec's
       ``reads`` - with ``ValidationContext(principal, target, partial)``,
       whose ``resolved`` names ``target`` as dispatch would: ``instance``
       for a spec with an instance selector, ``collection`` for one with a
       collection selector, nothing for a create, and whose ``call_context``
       is ``call_context``, the very dict passed, or a fresh one.

    Returns the Validator's values. A service spec with no Validator returns
    ``{}``, because every argument it takes is a read and none is validated. A
    [`SelectorSpec`][django_service_specs.specs.selector_spec.SelectorSpec]
    has no Validator and returns the checked arguments, which are what its
    selector is called with.

    **It runs no provider.** The spec's ``input_data``, which dispatch merges
    over the caller's arguments before the Validator, is not called here: it
    reads the resolved target and the call's seeds, which this function is
    not handed. A spec declaring one is bound on the caller's arguments alone,
    so a field the provider fills or may fill passes the shape check and is
    the Validator's to refuse: left out, or sent, since a value the caller
    sends for a field the server owns is checked and then dropped, as in
    dispatch. The presence check dispatch makes of such a field before the
    Validator, once the provider has answered, is not made here
    (test_a_field_input_data_fills_is_left_to_the_validator_which_runs_no_provider).
    No ``kwargs`` provider is called either: a read one fills or
    may fill passes the shape check absent, and the presence check dispatch
    makes once the provider has answered is not made here
    (test_bind_arguments_relaxes_a_may_fill_read). A read one is annotated to
    fill is absent from a selector spec's checked arguments whether or not
    the caller sent it.

    **It takes no** ``pool_seeds``, so it refuses no registered seed's name
    and splits none: a ``reflected`` read is checked as declared, so a
    required one is demanded of the caller here though a registered seed
    fills it on dispatch, which refuses the caller's value for it as an
    unknown argument under ``REJECT``
    (test_bind_arguments_still_demands_a_required_reflected_read), and a
    Validator field named like a registered seed is validated and returned
    among the values, as any field is. Which values a service's pool spreads
    is dispatch's question.

    **It does not resolve or authorize.** Dispatch runs class-level
    authorization, target resolution and object-level authorization *between*
    these two steps, so the Validator sees the resolved row and a refused
    principal learns nothing about which rows exist. A caller of this function
    owns both: it authorizes before binding, and passes the row it resolved as
    ``target``, or ``None`` for a create.

    It is the complement of
    [`check_call`][django_service_specs.dispatch.check_call.check_call]: this
    validates and does not authorize, and ``check_call`` authorizes and does
    not validate.

    Raises:
        InvalidArguments: from either step. The shape check's tree carries every
            problem at once, and a Validator is only reached with well-shaped
            arguments. A ``many`` spec is the one exception, row by row: the
            Validator's ``validated_many()`` is handed every row that passed
            the shape check, and a shape refusal and a Validator refusal on
            different rows come back as one tree keyed by row index.
    """
    spec = kernel_spec(spec)
    checked = shape_check(spec, spec.parameters(), arguments, unknown_arguments=unknown_arguments)
    if isinstance(spec, SelectorSpec):
        return checked
    validated = validate_arguments(
        spec,
        checked,
        principal=principal,
        target=target,
        server_input={},
        call_context={} if call_context is None else call_context,
        provider_answered=False,
        resolved=target_entry(spec, target),
    )
    return validated.values
