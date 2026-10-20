"""The package root re-exports every subpackage's public surface, and only that."""

from __future__ import annotations

import importlib
import importlib.util
import json
import pkgutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

import django_service_specs

# An adapter whose library is an optional extra rather than a dependency is
# public from its own subpackage alone. Re-exported at the root, it would import
# that library for every consumer, and fail for each one who never installed
# the extra. Each is keyed to the library it must not pull in.
OPTIONAL_LIBRARY_ADAPTERS = {"django_service_specs.adapters.pydantic": "pydantic"}

# An adapter that is exported from the root, yet reads its optional library
# only inside the function that needs it. The library is still not the root's
# to load, so it is held by the same probe: neither the root nor importing the
# adapter's module may pull it in. Keyed to the library, as above.
LAZY_LIBRARY_ADAPTERS = {"django_service_specs.adapters.filters": "django_filters"}

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
import pytest

import django_service_specs
adapters = {OPTIONAL_LIBRARY_ADAPTERS!r}
lazy = {LAZY_LIBRARY_ADAPTERS!r}
loaded_lazy = lambda: sorted(library for library in lazy.values() if library in sys.modules)
before_lazy = loaded_lazy()
before = sorted(library for library in adapters.values() if library in sys.modules)
for adapter in adapters:
    importlib.import_module(adapter)
after = sorted(library for library in adapters.values() if library in sys.modules)
for adapter in lazy:
    importlib.import_module(adapter)
print(json.dumps([before, after, before_lazy, loaded_lazy()]))
"""
    completed = subprocess.run(
        [sys.executable, "-c", probe], cwd=REPO_ROOT, capture_output=True, text=True
    )

    assert completed.returncode == 0, completed.stderr
    before, after, lazy_before, lazy_after = json.loads(completed.stdout)
    assert before == []
    assert after == sorted(OPTIONAL_LIBRARY_ADAPTERS.values())
    # The lazy adapter's library stays unloaded, on the root and on its module:
    # a top-level import of it would make the root need an optional extra.
    assert lazy_before == []
    assert lazy_after == []


def test_the_form_page_view_is_not_served_from_this_package() -> None:
    # A page a person reads belongs to a package that owns presentation, and
    # this one is the plumbing under it: the view that rendered a spec's form
    # as a page is not importable from here, at the root or at its old path.
    assert importlib.util.find_spec("django_service_specs.http.spec_form_view") is None
    assert not hasattr(django_service_specs, "SpecFormView")
    assert "SpecFormView" not in django_service_specs.__all__


# A name a separate distribution imports is public at the root, and it is the
# one object the kernel's own readers call: a second copy at the root would
# let a transport's rule drift from the kernel's. Each name is paired with
# every module inside the kernel that reads it, so moving a reader onto a copy
# of its own fails here.
SHARED_WITH_THE_KERNEL = {
    "relax_partial": (
        "django_service_specs.commands.spec_command",
        "django_service_specs.dispatch.check_server_arguments",
        "django_service_specs.dispatch.utils",
        "django_service_specs.schema.spec_input_schema",
    ),
    "refusal_messages": (
        "django_service_specs.commands.spec_command",
        "django_service_specs.http.add_argument_errors",
    ),
    "NON_FIELD_KEYS": (
        "django_service_specs.http.add_argument_errors",
        "django_service_specs.parameters.refusal_messages",
    ),
    "expected_type": (
        "django_service_specs.adapters.dataclass.dataclass_validator",
        "django_service_specs.http.request_arguments",
        "django_service_specs.parameters.check_arguments",
    ),
    "max_length_in_force": (
        "django_service_specs.http.request_arguments",
        "django_service_specs.parameters.utils",
        "django_service_specs.schema.parameters_schema",
    ),
    # The inactive-account rule is one predicate on purpose: dispatch, the
    # principal an identifier names and the HTTP entry points refuse the same
    # principals.
    "is_deactivated": (
        "django_service_specs.authorization.resolve_principal",
        "django_service_specs.dispatch.utils",
        "django_service_specs.http.request_principal",
    ),
    "clean_held_to_their_columns": (
        "django_service_specs.adapters.forms.form_validator",
        "django_service_specs.http.add_argument_errors",
    ),
}


@pytest.mark.parametrize(
    ("name", "reader"),
    [(name, reader) for name, readers in SHARED_WITH_THE_KERNEL.items() for reader in readers],
)
def test_a_name_the_kernel_shares_is_the_root_s_own_object(name: str, reader: str) -> None:
    assert name in django_service_specs.__all__
    assert getattr(django_service_specs, name, None) is getattr(
        importlib.import_module(reader), name
    )
