"""``bind_arguments`` - the shape check and the Validator, for a caller outside dispatch."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from django_service_specs.dispatch.utils import shape_check, validate_arguments
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.spec_source import SpecSource, kernel_spec
from django_service_specs.validation.unknown_arguments import UnknownArguments

if TYPE_CHECKING:
    from django_service_specs.specs.service_spec import ServiceSpec


def bind_arguments(
    spec: ServiceSpec | SelectorSpec | SpecSource,
    arguments: Mapping[str, Any],
    *,
    principal: Any,
    target: Any = None,
    unknown_arguments: UnknownArguments = UnknownArguments.REJECT,
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
       ``partial``, one its ``input_data`` provider is annotated to fill, and
       a read the ``kwargs`` provider of the spec declaring it is annotated
       to fill.
    2. For a [`ServiceSpec`][django_service_specs.specs.service_spec.ServiceSpec]
       with a Validator, ``validated()`` on only the arguments the Validator's
       own ``parameters()`` declare - never a selector's or the spec's
       ``reads`` - with ``ValidationContext(principal, target, partial)``.

    Returns the Validator's values. A service spec with no Validator returns
    ``{}``, because every argument it takes is a read and none is validated. A
    [`SelectorSpec`][django_service_specs.specs.selector_spec.SelectorSpec]
    has no Validator and returns the checked arguments, which are what its
    selector is called with.

    **It runs no provider.** The spec's ``input_data``, which dispatch merges
    over the caller's arguments before the Validator, is not called here: it
    reads the resolved target and the call's seeds, which this function is
    not handed. A spec declaring one is bound on the caller's arguments alone,
    so a field the provider is annotated to fill passes the shape check and
    is the Validator's to refuse: left out, or sent, since a value the caller
    sends for a field the server owns is checked and then dropped, as in
    dispatch. No ``kwargs`` provider is called either: a read one fills
    passes the shape check, and is absent from a selector spec's checked
    arguments whether or not the caller sent it.

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
            Validator runs on each row that passed the shape check, and a
            shape refusal and a Validator refusal on different rows come back
            as one tree keyed by row index.
    """
    spec = kernel_spec(spec)
    checked = shape_check(spec, spec.parameters(), arguments, unknown_arguments=unknown_arguments)
    if isinstance(spec, SelectorSpec):
        return checked
    # The step dispatch takes, the same function: the two cannot drift apart.
    validated = validate_arguments(
        spec, checked, principal=principal, target=target, server_input={}
    )
    return validated.values
