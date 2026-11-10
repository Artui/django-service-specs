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
    """Refuse a ``ServerArguments`` that cannot mean what it says."""
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
    """Every key a typed provider of ``spec`` fills or may decline."""
    providers: list[Callable[..., Any] | None] = [spec.kwargs]
    if isinstance(spec, ServiceSpec):
        target = spec.target_selector_spec()
        providers += [spec.input_data, None if target is None else target.kwargs]
    found: set[str] = set()
    for provider in providers:
        keys = provider_keys(provider)
        if keys is not None:
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
    """Whether ``fn`` declares ``name`` with no default, so a call leaving it out is refused."""
    if fn is None:
        return False
    declared = inspect.signature(fn).parameters.get(name)
    return declared is not None and declared.default is inspect.Parameter.empty


def _call_hint(names: list[str], pool_seeds: PoolSeeds) -> str:
    """The note that a name no seed registers is the call's own, as dispatch's refusal adds it."""
    if set(names) <= pool_seeds.names:
        return ""
    return CALL_SEEDS_NOTE
