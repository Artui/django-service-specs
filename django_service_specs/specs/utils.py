"""Construction checks shared by the two spec dataclasses."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import Field
from typing import Any

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.authorization.permission_check import PermissionCheck
from django_service_specs.output.presenter import Presenter
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.pool.call_seeds import CALL_SEEDS
from django_service_specs.pool.reserved_pool_seeds import RESERVED_POOL_SEEDS
from django_service_specs.types.is_async import is_async
from django_service_specs.types.utils import CALL_SEEDS_NOTE, SHAPES, SHAPES_RENAME

# The methods dispatch reads a permission check's answer from.
_CHECK_METHODS = ("has_permission", "has_object_permission", "has_scope_permission")


def check_changes(declared: tuple[Field[Any], ...], changes: Iterable[str], *, label: str) -> None:
    """Refuse a ``derive`` change naming anything but a field an author declares.

    ``dataclasses.replace``, which builds the derived spec, already refuses a
    name that is no constructor keyword, but in words that name neither the
    spec nor ``derive``, and it accepts a private field without a word:
    ``SelectorSpec._filter_reads`` is the constructor's own record of what a
    filter set added, and one handed in from outside would take the author's
    reads out. One arc to coverage: the ``'_filter_reads'`` case of
    ``SelectorSpec``'s test_a_name_that_is_not_a_field_is_refused holds the
    second disjunct, its ``'parameters'`` case the first.
    """
    own = {declared_field.name for declared_field in declared}
    unknown = sorted(name for name in changes if name not in own or name.startswith("_"))
    if unknown:
        named = ", ".join(repr(name) for name in unknown)
        raise TypeError(f"{label}.derive() takes the spec's own fields, and not {named}.")


def check_callable(value: Any, *, label: str, sync: bool = False) -> None:
    """Refuse a value that is not callable, and under ``sync`` one that is ``async def``.

    ``sync`` is for every seat dispatch calls from sync code and never awaits:
    the providers, the preconditions, a selector spec's ``extend_queryset`` and
    ``filter_set``, each method of a permission check, a Validator's
    ``validate`` and ``validated``, and a Presenter's ``present``. Called there, an
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
            f"{label} is {callable_name(value)}, an async callable. It is called from sync code "
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

    An ``async def`` one is refused here. What construction cannot see, a
    plain ``def`` handing back a coroutine, is refused where the answer is
    read, by ``dispatch/utils.py``'s ``sync_result``.
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
    """Normalize to a tuple, refusing anything that is not a check *instance*, and an empty one.

    **An empty sequence is refused**, as ``None`` is refused at dispatch and
    at registration: every check passing is vacuously true of no checks, so
    ``permissions=[]`` would let anyone run the operation, and an empty list
    is as often computed by accident as decided. ``Unrestricted()`` is the
    decision, by name (test_an_empty_permissions_sequence_is_refused).

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
    if not checks:
        raise ImproperlyConfigured(
            f"{label}.permissions is empty, which would let anyone run it. Declare "
            "permissions=[Unrestricted()] to mean that."
        )
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
    """Refuse a presenter that is not a ``Presenter`` instance, or with an async ``present``, ``presented`` or ``presented_rows``.

    ``present`` is called from sync code on both entry points and never
    awaited, so an ``async def`` one would hand a transport a coroutine where
    the payload should be
    (``TestAnAsyncPresenterIsRefused`` in ``tests/specs/test_utils.py``).
    A plain ``def present`` handing back a coroutine is refused where its
    answer is read, by ``present``.
    """
    if presenter is None:
        return
    if not isinstance(presenter, Presenter):
        raise ImproperlyConfigured(
            f"{label}.presenter is {describe(presenter)}, which is not a Presenter instance."
        )
    # Each method by name, held by its own case in TestAnAsyncPresenterIsRefused:
    # test_on_a_service_spec, test_an_async_presented_is_refused_too and
    # test_an_async_presented_rows_is_refused_too.
    for method in ("present", "presented", "presented_rows"):
        check_callable(getattr(presenter, method), label=f"{label}.presenter.{method}", sync=True)


def check_metadata(metadata: Mapping[str, Any] | None, *, label: str) -> None:
    if metadata is not None and not isinstance(metadata, Mapping):
        raise ImproperlyConfigured(
            f"{label}.metadata must be a mapping; got {type(metadata).__name__}."
        )


def check_reserved(parameters: Parameters, *, label: str) -> Parameters:
    """Refuse a parameter named after a pool seed, and return the parameters."""
    taken = sorted(parameters.names() & RESERVED_POOL_SEEDS)
    if taken:
        # The rename only for ``shapes``, the name reserved after projects had
        # declared it: test_a_parameter_named_shapes_is_refused_with_the_rename
        # fails without it, and test_a_parameter_named_call_context_is_refused_without_the_shapes_rename
        # if every refusal carries it.
        hint = SHAPES_RENAME if SHAPES in taken else ""
        raise ImproperlyConfigured(
            f"{label} declares the parameter(s) {taken}, which dispatch seeds itself. "
            f"An argument must never outrank a seeded value; rename the parameter.{hint}"
        )
    return parameters


def check_call_seeds(parameters: Parameters, *, label: str, reflected_seated: bool) -> None:
    """Refuse a parameter named ``request`` or ``view`` that the call's seat does not fill.

    Dispatch hands both to every callable naming one, read off the call's
    context, on every mount, so a service spec's read nobody marked
    ``reflected``, its target selector's, or its shape, of either name, meets
    the call's value in one pool, and ``dispatch`` refuses the spec on every
    call whatever the caller sends, with or without a seed registered under
    the name. Refused here, when the spec is built, because nothing about
    the call can change the answer: the registered seeds change who fills
    the name, never whether it is filled. The message ends as dispatch's
    does, with ``CALL_SEEDS_NOTE``, so a consumer matching either matches
    both. Not in ``check_reserved``, which also reads the assembled
    parameters, where a top-level Validator field of either name stays the
    caller's (test_a_validator_field_named_request_takes_the_seat).

    Read for a ``ServiceSpec`` only, never on a ``SelectorSpec``'s own
    construction. A selector spec is built in two places its parameters are
    no call's: as an output selector, whose reads never reach the call's
    arguments and whose selector is handed the call's own value by name
    (test_an_output_selector_s_read_named_request_builds_and_runs), and
    for ``shape_queryset`` outside dispatch, where a FilterSet's filter of
    either name is a query parameter like any other
    (test_a_filter_named_view_builds_and_shapes). A selector spec dispatched
    on its own is refused by dispatch, as before, and by ``check_seeds``.

    ``reflected_seated`` is for a spec's reads: a ``reflected`` read is read
    off its callable's signature, so the call's seat fills it
    (test_a_reflected_read_named_either_is_the_call_s). A shape is no read
    any seat fills, so a reflected one is refused as an unmarked one is.
    One arc to coverage: the read cases of
    test_one_nobody_marked_is_refused_when_the_spec_is_built hold
    ``param.reflected``, and test_a_reflected_shape_is_still_refused holds
    ``reflected_seated``.
    """
    taken = sorted(
        param.name
        for param in parameters
        if param.name in CALL_SEEDS and not (reflected_seated and param.reflected)
    )
    if taken:
        # The mark is offered for a read alone, since it frees no shape:
        # test_the_hint_to_mark_it_is_offered_for_a_read, and the negative
        # assertion of test_a_reflected_shape_is_still_refused.
        hint = (
            " Mark a read reflected=True for its callable to be handed the call's own."
            if reflected_seated
            else ""
        )
        raise ImproperlyConfigured(
            f"{label} declares the parameter(s) {taken}, which dispatch hands every callable "
            "on every mount. An argument must never meet the call's value in one pool; "
            f"rename the parameter.{hint}{CALL_SEEDS_NOTE}"
        )


def callable_name(value: Any) -> str:
    """A callable's own name, or its type's for an instance or a ``functools.partial``."""
    return getattr(value, "__qualname__", None) or type(value).__name__


def describe(value: Any) -> str:
    """A refusal's name for what was declared: ``the class X`` for a class, else its type's name."""
    return f"the class {value.__name__}" if isinstance(value, type) else type(value).__name__
