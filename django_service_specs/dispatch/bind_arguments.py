"""``bind_arguments`` - the shape check and the Validator, for a caller outside dispatch."""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from django_service_specs.authorization.utils import refuse_deactivated
from django_service_specs.dispatch.utils import (
    seat_seed_named,
    seeded_base,
    shape_check,
    target_entry,
    validate_arguments,
)
from django_service_specs.pool.pool_seeds import PoolSeeds
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
    pool_seeds: PoolSeeds | None = None,
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

    **Given** ``pool_seeds``, **it binds as dispatch binds with them.** A
    ``reflected`` read a registered seed fills is no argument of the call, so
    it is not demanded of the caller
    (test_a_reflected_read_a_registered_seed_fills_is_not_demanded), and the
    caller's value for it is refused as an unknown argument under ``REJECT``
    and dropped under ``IGNORE``
    (test_the_caller_s_value_for_it_is_refused_under_reject_as_dispatch_refuses_it,
    test_the_caller_s_value_for_it_is_dropped_under_ignore). A parameter
    dispatch refuses for sharing a seed's name is refused here too, with
    ``ImproperlyConfigured``
    (test_an_unmarked_read_named_like_a_registered_seed_is_refused_only_with_the_seeds).
    The Validator's ``ambient`` is the pool dispatch hands it: ``user``,
    ``progress`` as the no-op reporter, since no call is running, and every
    registered seed, each resolved once for the principal against
    ``call_context``, so a ``FormValidator``'s ``form_kwargs`` naming a seed
    is handed it
    (test_a_form_kwargs_naming_a_registered_seed_is_handed_it). A Validator
    field named like a registered seed is validated and returned among the
    values, as any field is, and the seed keeps its own value in ``ambient``
    (test_a_validator_field_named_like_a_registered_seed_is_validated_and_returned).
    Every seed resolves on each bind of a spec with a Validator, as on
    dispatch, whether or not the Validator reads one, so a caller binding
    often, a page re-checking a form on each edit, pays each resolver per bind.
    A spec with no Validator resolves none, since nothing it binds reads one
    (test_a_service_spec_with_no_validator_resolves_no_seed).
    A deactivated principal is refused with ``PrincipalUnavailable`` first,
    as dispatch refuses one: before the seat refusal and the shape check, for
    every kind of spec and any registry, so no seed resolves for it
    (test_given_seeds_a_deactivated_principal_is_refused_first_as_dispatch_refuses_it,
    test_given_seeds_a_deactivated_principal_is_refused_before_the_seat_refusal,
    test_a_deactivated_principal_resolves_no_seed). Which values a service's
    pool spreads is dispatch's question.

    **Any registry is dispatch's, an empty one too**, so the call's
    ``request`` and ``view`` are seeds of the bind as of every pool dispatch
    builds: a ``reflected`` read of either name is filled rather than
    demanded (test_a_reflected_read_named_request_is_the_call_s_with_any_registry).
    **Without** ``pool_seeds`` it is the function it was before it took
    them: a ``reflected`` read is checked as declared, so a required one is
    demanded of the caller
    (test_bind_arguments_still_demands_a_required_reflected_read), no seed is
    resolved, no principal is refused for being deactivated, and the
    Validator's ``ambient`` is empty
    (test_the_validator_s_ambient_is_dispatch_s_with_any_registry).

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
    parameters = spec.parameters()
    if pool_seeds is not None:
        # First, as dispatch refuses one, so no resolver runs for it below.
        refuse_deactivated(principal)
        parameters = seat_seed_named(spec, parameters, parameters, pool_seeds)
    checked = shape_check(spec, parameters, arguments, unknown_arguments=unknown_arguments)
    if isinstance(spec, SelectorSpec):
        return checked
    # One dict for the seeds' resolvers and the Validator, so a resolver reading
    # ``request`` and the Validator see the same call
    # (test_a_seed_resolver_reads_the_dict_the_validator_is_handed).
    context = {} if call_context is None else call_context
    ambient: dict[str, Any] = {}
    # Two conjuncts: without the first a bind handed no seeds would have no
    # registry to resolve, and fail rather than bind with an empty ambient
    # (test_the_validator_s_ambient_is_dispatch_s_with_any_registry[none]); without
    # the second a spec with nothing to validate would run every resolver
    # (test_a_service_spec_with_no_validator_resolves_no_seed).
    if pool_seeds is not None and spec.validator is not None:
        ambient = seeded_base(
            principal, progress=None, pool_seeds=pool_seeds, early={}, call_context=context
        )
    validated = validate_arguments(
        spec,
        checked,
        principal=principal,
        target=target,
        server_input={},
        call_context=context,
        provider_answered=False,
        ambient=MappingProxyType(ambient),
        resolved=target_entry(spec, target),
    )
    return validated.values
