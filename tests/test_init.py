"""The package root re-exports every subpackage's public surface, and only that."""

from __future__ import annotations

import importlib
import json
import pkgutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import django_service_specs

# An adapter whose library is an optional extra rather than a dependency is
# public from its own subpackage alone. Re-exported at the root, it would import
# that library for every consumer, and fail for each one who never installed
# the extra. Each is keyed to the library it must not pull in.
OPTIONAL_LIBRARY_ADAPTERS = {"django_service_specs.adapters.pydantic": "pydantic"}

REPO_ROOT = Path(__file__).resolve().parents[1]


def _is_optional_library_adapter(name: str) -> bool:
    return any(
        name == adapter or name.startswith(f"{adapter}.") for adapter in OPTIONAL_LIBRARY_ADAPTERS
    )


def _subpackages() -> list[ModuleType]:
    return [
        importlib.import_module(info.name)
        for info in pkgutil.walk_packages(
            django_service_specs.__path__, prefix=f"{django_service_specs.__name__}."
        )
        if info.ispkg and not _is_optional_library_adapter(info.name)
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


def test_the_root_imports_no_optional_library_and_each_exempt_adapter_does() -> None:
    # A fresh interpreter, because this one imported every adapter while
    # walking the package. The second half is what makes the first mean
    # something: an exemption naming no adapter, or a probe that cannot see
    # the library, would otherwise pass as a root that stayed clean.
    probe = f"""
import importlib, json, sys
import django
django.setup()
import django_service_specs
adapters = {OPTIONAL_LIBRARY_ADAPTERS!r}
before = sorted(library for library in adapters.values() if library in sys.modules)
for adapter in adapters:
    importlib.import_module(adapter)
after = sorted(library for library in adapters.values() if library in sys.modules)
print(json.dumps([before, after]))
"""
    completed = subprocess.run(
        [sys.executable, "-c", probe], cwd=REPO_ROOT, capture_output=True, text=True
    )

    assert completed.returncode == 0, completed.stderr
    before, after = json.loads(completed.stdout)
    assert before == []
    assert after == sorted(OPTIONAL_LIBRARY_ADAPTERS.values())
