"""Construction checks shared by the two spec dataclasses."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.authorization.permission_check import PermissionCheck
from django_service_specs.output.presenter import Presenter
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.pool.reserved_pool_seeds import RESERVED_POOL_SEEDS
from django_service_specs.services.is_async import is_async

# The methods dispatch reads a permission check's answer from.
_CHECK_METHODS = ("has_permission", "has_object_permission", "has_scope_permission")


def check_callable(value: Any, *, label: str, sync: bool = False) -> None:
    """Refuse a value that is not callable, and under ``sync`` one that is ``async def``.

    ``sync`` is for every seat dispatch calls from sync code and never awaits:
    the providers, the preconditions, a selector spec's ``extend_queryset`` and
    ``filter_set``, and each method of a permission check. Called there, an
    ``async def`` callable returns a coroutine nobody awaits, so a precondition
    that would have refused the call raises nothing and the call goes ahead, a
    permission check's answer is truthy and allows it, and a provider or a
    shaping callable hands dispatch a coroutine where its mapping, its sink or
    its queryset should be. An async generator function is refused with them:
    what it returns is never awaitable, never runs, and is truthy too. Refused
    when the spec is built, naming the seat and the callable, rather than
    found at the first call or never. The run itself - the service, or a
    selector spec's own selector - may be ``async def``, since dispatch
    bridges it and ``adispatch`` awaits it, so it is checked without ``sync``.
    """
    if not callable(value):
        raise ImproperlyConfigured(f"{label} must be callable; got {type(value).__name__}.")
    # One arc to coverage: test_the_run_may_still_be_async holds ``sync``,
    # test_a_sync_provider_and_precondition_are_accepted the second, and
    # test_an_async_generator_precondition_is_refused the third.
    if sync and (is_async(value) or inspect.isasyncgenfunction(value)):
        raise ImproperlyConfigured(
            f"{label} is {_name(value)}, an async callable. It is called from sync code "
            "and never awaited, on both entry points; declare it with def, since adispatch "
            "already runs it off the event loop."
        )


def check_providers(spec: Any, names: tuple[str, ...], *, label: str) -> None:
    """Refuse a provider field holding anything but a sync callable; ``None`` declares none."""
    for name in names:
        value = getattr(spec, name)
        if value is not None:
            check_callable(value, label=f"{label}.{name}", sync=True)


def check_preconditions(
    preconditions: Sequence[Callable[..., None]] | None, *, label: str
) -> tuple[Callable[..., None], ...] | None:
    """Normalize ``preconditions`` to a tuple in declaration order, refusing what is not one.

    ``Sequence`` alone refuses a bare callable, the likeliest mistake, as well
    as a set, whose order would decide which refusal a caller sees, and a
    generator, which the first call would exhaust. A string is a sequence of
    non-callables and is refused by name rather than per character. One arc
    to coverage: the ``"print"`` case of each spec's
    ``test_refuses_at_construction`` holds the first disjunct, its ``print``
    case the second.
    """
    if preconditions is None:
        return None
    if isinstance(preconditions, str | bytes) or not isinstance(preconditions, Sequence):
        raise ImproperlyConfigured(
            f"{label}.preconditions takes a sequence of callables; got "
            f"{type(preconditions).__name__}. Wrap a single one in a list: preconditions=[...]."
        )
    declared = tuple(preconditions)
    for index, precondition in enumerate(declared):
        check_callable(precondition, label=f"{label}.preconditions[{index}]", sync=True)
    return declared


def check_permissions(
    permissions: Sequence[PermissionCheck] | None, *, label: str
) -> tuple[PermissionCheck, ...] | None:
    """Normalize to a tuple, refusing anything that is not a check *instance*.

    A class is the likely mistake - an HTTP framework declares permission
    classes - and a class passes ``callable()``, so it is refused by name here
    rather than failing at dispatch with an unbound-method error.

    Each of the three methods is read for truth from sync code, so an
    ``async def`` one - whose answer is a truthy coroutine - is refused here,
    on the bound method, as any other sync-only seat is. One case per method
    in ``tests/specs/test_utils.py``'s ``TestAnAsyncPermissionCheckIsRefused``,
    since coverage cannot see a name dropped from ``_CHECK_METHODS``. What
    construction cannot see, a plain ``def`` handing back a coroutine, is
    refused where the answer is read, by ``authorization/utils.py``'s
    ``sync_answer``.
    """
    if permissions is None:
        return None
    if isinstance(permissions, str | bytes) or not isinstance(permissions, Sequence):
        raise ImproperlyConfigured(f"{label}.permissions must be a sequence of PermissionCheck.")
    checks = tuple(permissions)
    for index, check in enumerate(checks):
        if isinstance(check, type):
            raise ImproperlyConfigured(
                f"{label}.permissions holds the class {check.__name__}; pass an instance, "
                f"{check.__name__}()."
            )
        if not isinstance(check, PermissionCheck):
            raise ImproperlyConfigured(
                f"{label}.permissions holds {type(check).__name__}, which is not a "
                "PermissionCheck. Subclass PermissionCheck, or adapt it."
            )
        for method in _CHECK_METHODS:
            check_callable(
                getattr(check, method), label=f"{label}.permissions[{index}].{method}", sync=True
            )
    return checks


def check_presenter(presenter: Presenter | None, *, label: str) -> None:
    if presenter is not None and not isinstance(presenter, Presenter):
        raise ImproperlyConfigured(
            f"{label}.presenter is {_describe(presenter)}, which is not a Presenter instance."
        )


def check_metadata(metadata: Mapping[str, Any] | None, *, label: str) -> None:
    if metadata is not None and not isinstance(metadata, Mapping):
        raise ImproperlyConfigured(
            f"{label}.metadata must be a mapping; got {type(metadata).__name__}."
        )


def check_reserved(parameters: Parameters, *, label: str) -> Parameters:
    """Refuse a parameter named after a pool seed, and return the parameters."""
    taken = sorted(parameters.names() & RESERVED_POOL_SEEDS)
    if taken:
        raise ImproperlyConfigured(
            f"{label} declares the parameter(s) {taken}, which dispatch seeds itself. "
            "An argument must never outrank a seeded value; rename the parameter."
        )
    return parameters


def _name(value: Any) -> str:
    """A callable's own name, or its type's for an instance or a ``functools.partial``."""
    return getattr(value, "__qualname__", None) or type(value).__name__


def _describe(value: Any) -> str:
    return f"the class {value.__name__}" if isinstance(value, type) else type(value).__name__
