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
    PrincipalUnavailable,
    ServiceConflict,
    ServiceError,
    ServiceNotFound,
    ServiceValidationError,
)
from django_service_specs.dispatch.refusals import REFUSALS


def _import_every_module() -> None:
    # The class tree holds only what has been imported, and importing the root
    # loads every module an ``__init__`` lists and nothing else: a refusal in a
    # module none lists, or under the pydantic adapter the root never imports,
    # would be missing from the tree and so from the comparison. Walking every
    # module makes the answer the package's rather than the collection order's.
    # Every module imports in each environment the suite runs in: the dev group
    # installs both extras' libraries, and no module needs a setting the test
    # settings lack.
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
    # Read from the class tree, so a refusal a later release adds fails here
    # until it is listed. ``http/`` is a transport, and its own refusal is its
    # own to map; the tree is filtered by module so a test's subclass is not
    # read as the package's.
    _import_every_module()
    package = django_service_specs.__name__ + "."
    defined = {
        kind
        for kind in _family(DispatchError) | _family(ServiceError)
        if kind.__module__.startswith(package) and not kind.__module__.startswith(package + "http.")
    }
    assert set(REFUSALS) == defined


def test_it_lists_each_once_family_by_family_and_each_base_first() -> None:
    assert (
        DispatchError,
        InvalidArguments,
        NotPermitted,
        PrincipalUnavailable,
        ServiceError,
        ServiceNotFound,
        ServiceConflict,
        ActionUnavailable,
        AdditionalInputRequired,
        ServiceValidationError,
    ) == REFUSALS
