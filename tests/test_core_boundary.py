"""Core is what ``dispatch`` and ``registry`` load, and nothing else is in it.

The package is in three layers. Core is what every transport needs to run a
spec: the declaration, the registry and ``dispatch`` with authorization on,
which is the import closure of ``dispatch`` and ``registry``. Authorization is
in it rather than beside it because dispatch always authorizes, so it is
reached rather than named as a root. An opt-in module is a feature the
transports share and core never imports; an authoring library is code a
project writes against, such as a validator adapter; a transport only wires.
Opt-in is a classification and not a switch: no setting turns a module on, so
the only thing that keeps one out of core is this test. It holds the
classification in one table, fails on a subpackage the table does not name,
and fails when the closure loads any module whose subpackage is not core. The
table runs both ways: a subpackage classified as core that the closure does
not reach is classified wrongly, since core is the closure by definition.

Measured by what loads rather than read from the import graph, because what
loads is the question, and it is larger than what the code names: importing
one leaf of a subpackage runs that subpackage's ``__init__``, which
re-exports its whole surface. So the closure comes from a fresh interpreter,
under a stand-in root that runs nothing, since the real root re-exports every
subpackage and would make the closure everything; Django is set up without
this app installed, so nothing reaches the real root first. What a bare
``import django_service_specs`` loads is not held here: the root is a table of
contents over every layer, on purpose.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import django_service_specs

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = Path(django_service_specs.__file__).resolve().parent

ROOTS = ("dispatch", "registry")

CORE = "core"
OPT_IN = "opt-in module"
AUTHORING = "authoring library"
TRANSPORT = "transport"

# Every subpackage's layer, keyed by its path below the root, plus the one
# root module core reads. A module takes the layer of its nearest entry, so
# ``commands/argv/`` is a transport with ``commands/``, and the table names a
# nested subpackage only where it sits on a different layer from its parent.
LAYERS: dict[str, str] = {
    "affordances": CORE,
    "authorization": CORE,
    "dispatch": CORE,
    "output": CORE,
    "parameters": CORE,
    "pool": CORE,
    "registry": CORE,
    "selectors": CORE,
    "services": CORE,
    "settings": CORE,
    "specs": CORE,
    "types": CORE,
    "validation": CORE,
    # The container's own modules: an ``__init__`` that re-exports nothing,
    # which importing the filters adapter runs, and ``utils.py``, the
    # annotation reader the three authoring libraries share. It imports only
    # ``types/``, so a core module reading it brings no authoring library in.
    "adapters": CORE,
    # Core because a selector declares its filters through it, in
    # ``specs/selector_spec.py`` and ``selectors/utils.py``; django-filter
    # stays an extra, read only inside the function that needs it.
    "adapters.filters": CORE,
    "adapters.dataclass": AUTHORING,
    "adapters.forms": AUTHORING,
    "adapters.pydantic": AUTHORING,
    "mutations": OPT_IN,
    "relations": OPT_IN,
    "schema": OPT_IN,
    "http": TRANSPORT,
    "commands": TRANSPORT,
}

# Packages whose subpackages sit on different layers, so each child is named
# on its own rather than inheriting the container's entry: a new adapter is a
# validator a project picks or a dependency of core, and the table has to say
# which before it can land.
CONTAINERS = frozenset({"adapters"})

_CLOSURE_PROBE = f"""
import importlib, importlib.util, json, sys
import django
from django.conf import settings
settings.configure(
    INSTALLED_APPS=["django.contrib.contenttypes", "django.contrib.auth"],
    DATABASES={{"default": {{"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}}},
)
django.setup()
root = importlib.util.spec_from_file_location(
    "django_service_specs",
    {str(PACKAGE_ROOT / "__init__.py")!r},
    submodule_search_locations=[{str(PACKAGE_ROOT)!r}],
)
sys.modules["django_service_specs"] = importlib.util.module_from_spec(root)
for core in {ROOTS!r}:
    importlib.import_module(f"django_service_specs.{{core}}")
print(json.dumps(sorted(m for m in sys.modules if m.startswith("django_service_specs."))))
"""


def _layer(module: str) -> str | None:
    # The nearest entry wins, so ``adapters.forms.form_validator`` is read as
    # ``adapters.forms`` and never falls through to the container. A module
    # under no entry has no layer, which the gate reports rather than skips.
    parts = module.split(".")[1:]
    prefixes = (".".join(parts[:n]) for n in range(len(parts), 0, -1))
    return next((LAYERS[p] for p in prefixes if p in LAYERS), None)


def _subpackages() -> frozenset[str]:
    # Read off the disk rather than ``sys.modules``, which holds only what
    # some import happened to load.
    return frozenset(
        ".".join(init.parent.relative_to(PACKAGE_ROOT).parts)
        for init in PACKAGE_ROOT.rglob("__init__.py")
        if init.parent != PACKAGE_ROOT
    )


@pytest.fixture(scope="module")
def closure() -> frozenset[str]:
    completed = subprocess.run(
        [sys.executable, "-c", _CLOSURE_PROBE], cwd=REPO_ROOT, capture_output=True, text=True
    )
    assert completed.returncode == 0, completed.stderr
    return frozenset(json.loads(completed.stdout))


def test_every_subpackage_is_classified() -> None:
    # A top-level subpackage, or a child of a container, that the table does
    # not name would take no layer, or the container's, and pass the gate
    # below unexamined.
    named = {
        package
        for package in _subpackages()
        if "." not in package or package.rpartition(".")[0] in CONTAINERS
    }
    assert sorted(named - LAYERS.keys()) == []


def test_every_classification_names_something_real() -> None:
    # An entry for a subpackage that has left the kernel would keep a layer
    # nobody can import, and read as a placement still in force.
    modules = {path.stem for path in PACKAGE_ROOT.glob("*.py")}
    assert sorted(LAYERS.keys() - _subpackages() - modules) == []


def test_the_probe_sees_the_core(closure: frozenset[str]) -> None:
    # The negative control for the gate: a probe that loaded nothing, or only
    # the roots, would let it pass for a reason that is not the code. Every
    # subpackage classified as core has to be reached, so the closure is the
    # whole of core rather than a corner of it.
    for leaf in (
        "django_service_specs.dispatch.dispatch",
        "django_service_specs.registry.spec_registry",
        "django_service_specs.authorization.resolve_principal",
    ):
        assert leaf in closure
    core = {name for name, layer in LAYERS.items() if layer == CORE}
    reached = {name for name in core if f"django_service_specs.{name}" in closure}
    assert sorted(core - reached) == []


def test_core_loads_nothing_classified_otherwise(closure: frozenset[str]) -> None:
    # Allowed by layer rather than refused by a list, so a module the table
    # cannot place fails here as surely as one it places outside core.
    outside = {module: _layer(module) for module in closure if _layer(module) != CORE}
    assert outside == {}
