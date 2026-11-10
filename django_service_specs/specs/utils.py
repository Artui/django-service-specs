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
    """Refuse a ``derive`` change naming anything but a field an author declares."""
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
    """Normalize ``preconditions`` to a tuple in declaration order, refusing what is not one."""
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
    """Refuse a presenter that is not a ``Presenter``, or whose methods are async."""
    if presenter is None:
        return
    if not isinstance(presenter, Presenter):
        raise ImproperlyConfigured(
            f"{label}.presenter is {describe(presenter)}, which is not a Presenter instance."
        )
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
        hint = SHAPES_RENAME if SHAPES in taken else ""
        raise ImproperlyConfigured(
            f"{label} declares the parameter(s) {taken}, which dispatch seeds itself. "
            f"An argument must never outrank a seeded value; rename the parameter.{hint}"
        )
    return parameters


def check_call_seeds(parameters: Parameters, *, label: str, reflected_seated: bool) -> None:
    """Refuse a parameter named ``request`` or ``view`` that the call's seat does not fill."""
    taken = sorted(
        param.name
        for param in parameters
        if param.name in CALL_SEEDS and not (reflected_seated and param.reflected)
    )
    if taken:
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
