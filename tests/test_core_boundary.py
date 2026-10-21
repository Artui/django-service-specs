"""Core is what ``dispatch`` and ``registry`` load, and nothing else is in it.

The package is in three layers. Core is what every transport needs to run a
spec: the declaration, the registry and ``dispatch`` with authorization on,
which is the import closure of ``dispatch`` and ``registry``. Authorization is
in it rather than beside it because dispatch always authorizes, so it is
reached rather than named as a root. An opt-in module is a feature the
transports share and core never imports; an authoring library is code a
project writes against, such as a validator adapter. A transport only wires,
and ships in a distribution of its own, above all three.
Opt-in is a classification and not a switch: no setting turns a module on, so
the only thing that keeps one out of core is this file. It holds the
classification in one table, fails on a subpackage the table does not name,
and fails when the closure loads any module whose subpackage is not core. It
also holds that the closure reaches every subpackage classified as core, so a
core entry that stops being reached has to be classified again rather than
kept on its old layer by the table alone.

Measured by what loads rather than read from the import graph, because what
loads is the question, and it is larger than what the code names: importing
one leaf of a subpackage runs that subpackage's ``__init__``, which
re-exports its whole surface. So the closure comes from a fresh interpreter,
under a stand-in root that runs nothing, since the real root re-exports every
subpackage and would make the closure everything; Django is set up without
this app installed, so nothing reaches the real root first. What a bare
``import django_service_specs`` loads is not held here: the root is a table of
contents over every layer, on purpose.

What loads is what an import statement runs at import time, so the probe
cannot see an import inside a function body, which loads the module the first
time the function is called. The same table is therefore held against the
source as well: no module classified as core names a module of another layer
in any import, at any depth, a dynamic import by literal name included.
"""

from __future__ import annotations

import ast
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

# Every subpackage's layer, keyed by its path below the root, plus the one
# root module core reads. A module takes the layer of its nearest entry, so
# ``mutations/apply_input.py`` is an opt-in module with ``mutations/``, and the
# table names a nested subpackage only where it sits on a different layer from
# its parent.
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
    # The container's ``__init__``, which re-exports nothing and which
    # importing the filters adapter runs.
    "adapters": CORE,
    # The annotation reader the three validator adapters share, and nothing
    # in core reads it.
    "adapters.utils": AUTHORING,
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
}

# Packages whose children sit on different layers, so each child, a
# subpackage or a module, is named on its own and never inherits the
# container's entry: a new adapter is a validator a project picks or a
# dependency of core, and the table has to say which before it can land.
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
    # ``adapters.forms``. A child of a container the table does not name has
    # no layer rather than the container's, and neither has a module under no
    # entry: the gates report both rather than skip them.
    parts = module.split(".")[1:]
    if len(parts) > 1 and parts[0] in CONTAINERS and ".".join(parts[:2]) not in LAYERS:
        return None
    prefixes = (".".join(parts[:n]) for n in range(len(parts), 0, -1))
    return next((LAYERS[p] for p in prefixes if p in LAYERS), None)


def _modules() -> dict[str, Path]:
    # Every source file by its dotted path below the root, the root itself as
    # the empty path; a package is named by its directory, not its
    # ``__init__``.
    modules = {}
    for path in PACKAGE_ROOT.rglob("*.py"):
        parts = path.relative_to(PACKAGE_ROOT).with_suffix("").parts
        modules[".".join(parts[:-1] if parts[-1] == "__init__" else parts)] = path
    return modules


def _subpackages() -> frozenset[str]:
    # Read off the disk rather than ``sys.modules``, which holds only what
    # some import happened to load; and from every directory holding source,
    # so a namespace package with no ``__init__`` is one too.
    return frozenset(
        ".".join(path.parent.relative_to(PACKAGE_ROOT).parts)
        for path in PACKAGE_ROOT.rglob("*.py")
        if path.parent != PACKAGE_ROOT
    )


def _imported(tree: ast.AST) -> frozenset[str]:
    # Every kernel module an import names, at every depth. ``from a import b``
    # counts as both ``a`` and ``a.b``, since ``b`` may be a submodule; an
    # attribute read as a module resolves to the module that holds it. A
    # dynamic import counts when its name is a literal: a computed one cannot
    # be read, and none is written in the package.
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif (
            isinstance(node, ast.Call)
            and _called(node.func) in {"import_module", "__import__"}
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            names.add(node.args[0].value)
    return frozenset(
        name
        for name in names
        if name == "django_service_specs" or name.startswith("django_service_specs.")
    )


def _called(func: ast.expr) -> str | None:
    # ``import_module(...)`` and ``importlib.import_module(...)`` alike.
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


@pytest.fixture(scope="module")
def closure() -> frozenset[str]:
    completed = subprocess.run(
        [sys.executable, "-c", _CLOSURE_PROBE], cwd=REPO_ROOT, capture_output=True, text=True
    )
    assert completed.returncode == 0, completed.stderr
    return frozenset(json.loads(completed.stdout))


def test_every_subpackage_is_classified() -> None:
    # A top-level subpackage, or a child of a container, that the table does
    # not name would take no layer, or the container's, and pass the gates
    # below unexamined.
    top = {package for package in _subpackages() if "." not in package}
    contained = {
        child
        for child in _subpackages() | _modules().keys()
        if child.rpartition(".")[0] in CONTAINERS
    }
    # A flat module is a child too, and ``adapters/utils.py`` is the one
    # standing case of it.
    assert "adapters.utils" in contained
    assert sorted((top | contained) - LAYERS.keys()) == []


def test_every_classification_names_something_real() -> None:
    # An entry for a subpackage that has left the kernel would keep a layer
    # nobody can import, and read as a placement still in force.
    assert sorted(LAYERS.keys() - _subpackages() - _modules().keys()) == []


def test_a_container_child_takes_no_layer_unless_named() -> None:
    # The container rule is what makes a new adapter be classified before it
    # lands; without it each of these would read as core.
    assert _layer("django_service_specs.adapters") == CORE
    assert _layer("django_service_specs.adapters.utils") == AUTHORING
    assert _layer("django_service_specs.adapters.forms.form_validator") == AUTHORING
    assert _layer("django_service_specs.adapters.attrs.validator") is None
    assert _layer("django_service_specs.adapters.attrs_validator") is None
    assert _layer("django_service_specs.tasks.run") is None


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


def test_no_core_module_imports_another_layer() -> None:
    # The probe sees import time only; this sees an import inside a function
    # body too, which would load an opt-in module into dispatch at call time
    # with the probe green. The root counts as another layer, since importing
    # it loads every one.
    reached = {}
    for dotted, path in _modules().items():
        module = f"django_service_specs.{dotted}" if dotted else "django_service_specs"
        if _layer(module) != CORE:
            continue
        outside = sorted(
            name for name in _imported(ast.parse(path.read_text())) if _layer(name) != CORE
        )
        if outside:
            reached[module] = outside
    assert reached == {}


def test_the_import_reader_sees_every_depth_and_spelling() -> None:
    source = (
        "import django_service_specs.relations.utils\n"
        "from django_service_specs.schema import thing\n"
        "import django_service_specs.validation as v\n"
        "from django_service_specs.registry import spec_registry as r\n"
        "import os\n"
        "def f():\n"
        "    from django_service_specs.mutations.create import create\n"
        "    import django_service_specs\n"
        "    importlib.import_module('django_service_specs.adapters.forms')\n"
        "    __import__('django_service_specs.adapters.pydantic')\n"
        "    import_module(name)\n"
        "    print('django_service_specs.output')\n"
    )
    assert _imported(ast.parse(source)) == {
        "django_service_specs",
        "django_service_specs.relations.utils",
        "django_service_specs.schema",
        "django_service_specs.schema.thing",
        "django_service_specs.validation",
        "django_service_specs.registry",
        "django_service_specs.registry.spec_registry",
        "django_service_specs.mutations.create",
        "django_service_specs.mutations.create.create",
        "django_service_specs.adapters.forms",
        "django_service_specs.adapters.pydantic",
    }
