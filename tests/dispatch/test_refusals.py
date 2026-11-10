from __future__ import annotations

import importlib
import pkgutil

import django_service_specs
from django_service_specs import (
    ActionUnavailable,
    AdditionalInputRequired,
    DispatchError,
    InvalidArguments,
    NotPermitted,
    PermissionCheckDenied,
    PrincipalUnavailable,
    ServiceConflict,
    ServiceError,
    ServiceNotFound,
    ServiceValidationError,
)
from django_service_specs.dispatch.refusals import REFUSALS


def _import_every_module() -> None:
    # The class tree holds only what has been imported.
    for info in pkgutil.walk_packages(
        django_service_specs.__path__, prefix=f"{django_service_specs.__name__}."
    ):
        importlib.import_module(info.name)


def _family(base: type[Exception]) -> set[type[Exception]]:
    found = {base}
    for sub in base.__subclasses__():
        found |= _family(sub)
    return found


def test_it_is_every_refusal_the_core_defines() -> None:
    # Read from the class tree, so a refusal a later release adds fails here until it is listed.
    _import_every_module()
    package = django_service_specs.__name__ + "."
    defined = {
        kind
        for kind in _family(DispatchError) | _family(ServiceError)
        if kind.__module__.startswith(package)
    }
    assert set(REFUSALS) == defined


def test_it_lists_each_once_family_by_family_and_each_base_first() -> None:
    assert (
        DispatchError,
        InvalidArguments,
        NotPermitted,
        PermissionCheckDenied,
        PrincipalUnavailable,
        ServiceError,
        ServiceNotFound,
        ServiceConflict,
        ActionUnavailable,
        AdditionalInputRequired,
        ServiceValidationError,
    ) == REFUSALS
