"""Construction checks shared by the two spec dataclasses."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import Field
from typing import Any

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.output.presenter import Presenter
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.pool.call_seeds import CALL_SEEDS
from django_service_specs.pool.reserved_pool_seeds import RESERVED_POOL_SEEDS
from django_service_specs.types.utils import (
    CALL_SEEDS_NOTE,
    SHAPES,
    SHAPES_RENAME,
    check_callable,
)


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
    the name, never whether it is filled. The message ends with
    ``CALL_SEEDS_NOTE``, as dispatch's does on a mount registering no seed
    of the name. Not in ``check_reserved``, which also reads the assembled
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


def describe(value: Any) -> str:
    """A refusal's name for what was declared: ``the class X`` for a class, else its type's name."""
    return f"the class {value.__name__}" if isinstance(value, type) else type(value).__name__
