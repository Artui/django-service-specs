"""The package root re-exports every subpackage's public surface, and only that."""

from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType

import django_service_specs


def _subpackages() -> list[ModuleType]:
    return [
        importlib.import_module(info.name)
        for info in pkgutil.walk_packages(
            django_service_specs.__path__, prefix=f"{django_service_specs.__name__}."
        )
        if info.ispkg
    ]


def test_every_subpackage_name_is_re_exported_at_the_root() -> None:
    # A subpackage's ``__all__`` is its public surface, and the root is where a
    # consumer reads the whole of it. A name added to a subpackage and not to
    # the root is public in one place and missing from the other, and nothing
    # else in the suite notices, because every test imports from leaf paths.
    missing = {
        f"{package.__name__}.{name}"
        for package in _subpackages()
        for name in package.__all__
        if name not in django_service_specs.__all__
    }
    assert not missing


def test_each_root_name_is_the_subpackage_s_own_object() -> None:
    # Identity rather than equality: a second definition of one name would
    # pass ``==`` for a class compared with itself nowhere, and an
    # ``isinstance`` against the other copy would fail in a consumer.
    for package in _subpackages():
        for name in package.__all__:
            assert getattr(django_service_specs, name) is getattr(package, name), name


def test_the_root_names_nothing_it_does_not_define() -> None:
    assert [
        name for name in django_service_specs.__all__ if not hasattr(django_service_specs, name)
    ] == []
