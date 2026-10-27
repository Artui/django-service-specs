"""``check_server_arguments`` - whether a binding of server values can mean what it says."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.dispatch.provider_reached import provider_reached
from django_service_specs.dispatch.relax_partial import relax_partial
from django_service_specs.dispatch.utils import (
    checked_server_values,
    server_arguments_label,
    split_seed_named,
)
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS, PoolSeeds
from django_service_specs.pool.provider_keys import provider_keys
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.specs.spec_source import SpecSource
from django_service_specs.types.server_arguments import ServerArguments
from django_service_specs.types.unset import UNSET
from django_service_specs.types.utils import CALL_SEEDS_NOTE


def check_server_arguments(
    spec: ServiceSpec | SelectorSpec | SpecSource,
    server: ServerArguments,
    *,
    pool_seeds: PoolSeeds = DEFAULT_POOL_SEEDS,
) -> None:
    """Refuse a [`ServerArguments`][django_service_specs.types.server_arguments.ServerArguments] that cannot mean what it says for ``spec``.

    For a transport to call once, when it is built, with the ``pool_seeds`` it
    dispatches with, so a binding that would do nothing or break every call
    fails at startup rather than on the first call that reaches it. Pure and
    synchronous, and it runs no query. The checks run in this order, and the
    first that finds anything raises, naming the spec's kind and callable and
    every name it found, in order:

    1. **A name that is no top-level parameter of the spec**, read as
       django-spec-html's
       [`route_arguments`](https://artui.github.io/django-spec-html/reference/#django_spec_html.http.route_arguments.route_arguments)
       reads a route's kwargs: ``spec.parameters().names()``. So a field
       inside a ``many`` spec's rows cannot be bound; a read beside the list
       can. Held by test_every_undeclared_name_is_refused_in_order and
       test_a_field_inside_a_many_row_is_not_a_top_level_parameter.
    2. **A name both bound and withheld**, which asks for a value and for
       none. Held by test_a_name_both_bound_and_withheld_is_refused.
    3. **A name a registered seed occupies**, as dispatch reads one. Only a
       registered seed can reach here, since ``parameters()`` refuses the
       dispatcher's names as it assembles. Two refusals, in this order, each
       naming only its own:

       - a parameter dispatch refuses as a configuration error - a read
         nobody marked ``reflected``, a shape. Held by
         test_a_parameter_a_registered_seed_occupies_is_refused and
         test_an_unmarked_read_is_still_refused_as_dispatch_refuses_it;
       - a ``reflected`` read, which the seed fills on every call, so a
         binding or a withholding would do nothing. Held by
         test_binding_or_withholding_it_is_refused_as_doing_nothing.

       A top-level Validator field named like a registered seed is not
       refused: it is the caller's argument, so a bound value reaches the
       Validator and ``data`` while the seed keeps the service's parameter of
       its name (test_check_server_arguments_binds_such_a_field), and
       withholding it meets rule 5 as any field does.
    4. **A name a typed provider fills or may fill**: the spec's ``kwargs``
       and, on a service spec, its ``input_data`` and its target selector's
       ``kwargs``, the providers
       [`server_owned_keys`][django_service_specs.specs.server_owned_keys.server_owned_keys]
       walks. A key a provider fills is dropped from the caller's arguments
       and answered by the provider alone, so a binding would do nothing; one
       it may decline with ``UNSET`` is the provider's on every call where it
       answers, so a binding would hold only when the provider happens not
       to. Each half is held by its own test:
       test_a_name_a_typed_provider_fills_is_refused (the filled keys) and
       test_a_name_a_provider_may_decline_is_refused_too (the declinable ones),
       and each provider past the spec's own ``kwargs`` too:
       test_a_validator_field_input_data_fills_is_refused (``input_data``) and
       test_a_read_the_target_selector_s_provider_fills_is_refused (the
       target's ``kwargs``). A provider whose return names no keys may fill
       any name and so names none, as for ``server_owned_keys``.
    5. **A withheld name no call could then do without.** Withheld, the
       parameter is absent, so it is refused if the shape check demands it -
       required and declaring no default, read as dispatch relaxes a
       ``partial`` spec, whose Validator parameters it never demands - or, for
       a read, if the callable that receives it declares it with no default of
       its own: the selector of a selector spec or of a service spec's target,
       and the service for a service spec's ``reads``. Dispatch applies no
       declared default, so the callable's is the only one that answers, and
       a call without one is refused as missing, a client error no caller can
       fix. A Validator parameter is the shape check's alone. Each conjunct
       is held by its own test, named beside the guard. **A parameter an
       untyped provider's values reach is never refused here**: that
       provider may fill it on any call, so a call may do without the
       caller's value, and dispatch refuses one nobody filled where the
       provider's answer is merged
       (test_check_server_arguments_lets_a_read_an_untyped_provider_reaches_be_withheld,
       test_check_server_arguments_lets_a_field_an_untyped_input_data_reaches_be_withheld).
       A typed provider's keys, filled or declinable, were refused by rule 4.
    6. **A bound value its parameter refuses**, checked as the shape check
       checks it, so a server value in its Python form - a ``uuid.UUID``, a
       ``date``, a ``Decimal`` - for a parameter that takes the wire's string
       fails here rather than on every call. Held by
       test_a_bound_value_its_parameter_refuses_fails_at_construction.

    Raises:
        ImproperlyConfigured: the first check that finds anything.
    """
    spec = kernel_spec(spec)
    parameters = spec.parameters()
    names = server.names()
    label = server_arguments_label(spec)
    undeclared = sorted(names - parameters.names())
    if undeclared:
        raise ImproperlyConfigured(
            f"{label}: ServerArguments names {', '.join(undeclared)}, which the spec does not "
            f"declare. Each name is a top-level parameter of the {type(spec).__name__}: declare "
            "it, or leave it out."
        )
    both = sorted(server.values.keys() & server.withheld)
    if both:
        raise ImproperlyConfigured(
            f"{label}: ServerArguments has {', '.join(both)} both bound and withheld: a bound "
            "name takes the server's value and a withheld one takes none, so name each once."
        )
    seated, taken = split_seed_named(spec, parameters, pool_seeds)
    refused = sorted(names & taken)
    if refused:
        raise ImproperlyConfigured(
            f"{label}: ServerArguments names {', '.join(refused)}, which a registered pool seed "
            "occupies; dispatch refuses a spec declaring a parameter there, so rename the "
            f"parameter.{_call_hint(refused, pool_seeds)}"
        )
    filled = sorted(names & seated)
    if filled:
        raise ImproperlyConfigured(
            f"{label}: ServerArguments names {', '.join(filled)}, a reflected read which a "
            "registered pool seed fills on every call, so binding or withholding it would do "
            f"nothing. Leave the name to the seed.{_call_hint(filled, pool_seeds)}"
        )
    provided = sorted(names & _provider_names(spec))
    if provided:
        raise ImproperlyConfigured(
            f"{label}: ServerArguments names {', '.join(provided)}, which a provider is "
            "annotated to fill or may fill: its answer outranks every other on a call where it "
            "gives one, so the binding could not be relied on. Leave the name to the provider."
        )
    receivers = _read_receivers(spec)
    reached = provider_reached(spec)
    # One branch arc of five conditions, each held by its own test:
    # test_a_required_name_with_no_default_may_be_bound fails without
    # ``withheld``, test_an_optional_read_its_selector_defaults_may_be_withheld
    # without ``required``, test_a_required_read_with_both_defaults_may_be_withheld
    # without the declared default's, and
    # test_a_read_its_selector_declares_with_no_default_cannot_be_withheld
    # without the callable's; test_a_demanded_read_is_refused_though_its_selector_has_a_default
    # holds the shape check's half of the disjunction for a read, and
    # test_a_required_validator_field_may_be_withheld_from_a_partial_spec
    # fails if the declaration is read unrelaxed;
    # test_check_server_arguments_lets_a_read_an_untyped_provider_reaches_be_withheld
    # fails without ``reached``.
    unfillable = [
        parameter.name
        for parameter in relax_partial(spec, parameters)
        if parameter.name in server.withheld
        and parameter.name not in reached
        and (
            (parameter.required and parameter.default is UNSET)
            or _lacks_default(receivers.get(parameter.name), parameter.name)
        )
    ]
    if unfillable:
        raise ImproperlyConfigured(
            f"{label}: ServerArguments withholds {', '.join(sorted(unfillable))}, which no call "
            "could then do without: the shape check demands a required parameter with no "
            "declared default, and a callable declaring a read with no default of its own is "
            "refused it as missing. Bind a value instead, or give the parameter a default."
        )
    checked_server_values(spec, parameters, server.values)


def _provider_names(spec: ServiceSpec | SelectorSpec) -> frozenset[str]:
    """Every key a typed provider of ``spec`` fills or may decline, over the providers ``server_owned_keys`` walks."""
    providers: list[Callable[..., Any] | None] = [spec.kwargs]
    if isinstance(spec, ServiceSpec):
        target = spec.target_selector_spec()
        providers += [spec.input_data, None if target is None else target.kwargs]
    found: set[str] = set()
    for provider in providers:
        keys = provider_keys(provider)
        if keys is not None:
            # Two halves, each held by its own test (see the docstring).
            found |= keys.filled | keys.declinable
    return frozenset(found)


def _read_receivers(spec: ServiceSpec | SelectorSpec) -> dict[str, Callable[..., Any]]:
    """Each read's name, and the callable a call hands it to."""
    if isinstance(spec, SelectorSpec):
        return dict.fromkeys(spec.reads.names(), spec.selector)
    receivers = dict.fromkeys(spec.reads.names(), spec.service)
    target = spec.target_selector_spec()
    if target is not None:
        receivers.update(dict.fromkeys(target.reads.names(), target.selector))
    return receivers


def _lacks_default(fn: Callable[..., Any] | None, name: str) -> bool:
    """Whether ``fn`` declares ``name`` with no default, so a call leaving it out is refused.

    ``None`` for a Validator parameter, which no callable here receives by
    name. Two conjuncts: test_a_read_its_selector_does_not_declare_may_be_withheld
    fails without the first, and test_an_optional_read_its_selector_defaults_may_be_withheld
    without the second.
    """
    if fn is None:
        return False
    declared = inspect.signature(fn).parameters.get(name)
    return declared is not None and declared.default is inspect.Parameter.empty


def _call_hint(names: list[str], pool_seeds: PoolSeeds) -> str:
    """The note that a name no seed registers is the call's own, as dispatch's refusal adds it.

    The dispatcher's names never reach the two refusals above, so a name the
    mount does not register is ``request`` or ``view``
    (test_server_arguments_naming_either_say_it_is_the_call_s).
    """
    if set(names) <= pool_seeds.names:
        return ""
    return CALL_SEEDS_NOTE
