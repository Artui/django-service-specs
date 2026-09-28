"""Construction checks shared by the two spec dataclasses."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from django.core.exceptions import ImproperlyConfigured

from django_service_specs.authorization.permission_check import PermissionCheck
from django_service_specs.output.presenter import Presenter
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.pool.reserved_pool_seeds import RESERVED_POOL_SEEDS


def check_callable(value: Any, *, label: str) -> None:
    if not callable(value):
        raise ImproperlyConfigured(f"{label} must be callable; got {type(value).__name__}.")


def check_permissions(
    permissions: Sequence[PermissionCheck] | None, *, label: str
) -> tuple[PermissionCheck, ...] | None:
    """Normalize to a tuple, refusing anything that is not a check *instance*.

    A class is the likely mistake - an HTTP framework declares permission
    classes - and a class passes ``callable()``, so it is refused by name here
    rather than failing at dispatch with an unbound-method error.
    """
    if permissions is None:
        return None
    if isinstance(permissions, str | bytes) or not isinstance(permissions, Sequence):
        raise ImproperlyConfigured(f"{label}.permissions must be a sequence of PermissionCheck.")
    checks = tuple(permissions)
    for check in checks:
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


def _describe(value: Any) -> str:
    return f"the class {value.__name__}" if isinstance(value, type) else type(value).__name__
