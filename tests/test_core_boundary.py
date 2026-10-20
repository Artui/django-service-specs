"""A bare import of the package loads the core, and nothing a project has not asked for.

The core is ``dispatch``, ``registry`` and ``authorization``, with everything
they load. Authorization is in it rather than beside it because dispatch
always authorizes, and the registry because every transport registers specs.
The boundary is whatever those load today, which includes the filters
adapter and none of ``relations/``, since the column checks core reads live
in ``parameters/``; this test holds neither fact. What it holds is that nothing beyond them - the
writes, the schemas, the HTTP views, the management command, the other
validator adapters - loads unless a project asks for it.

Measured by what loads rather than read from the import graph, because what
loads is the question, and it is larger than what the code names: importing
one leaf of a subpackage runs that subpackage's ``__init__``, which
re-exports its whole surface. So each set comes from a fresh interpreter. The
closure is taken under a stand-in root that runs nothing, since the real root
re-exports every subpackage and would make the closure everything; Django is
set up without this app installed, so nothing reaches the real root first. The
bare import is taken with the test settings, as a project installing the app
loads it.

The boundary does not hold yet, because the root re-exports every subpackage,
so the test is an expected failure, strict: the day it holds, the marker has
to go. The probes are held by their own test rather than under the marker,
since an expected failure absorbs a broken probe as readily as a broken
boundary.
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

CORE = ("dispatch", "registry", "authorization")

# The root's own ``__version__``, which every import of the root reads. It is
# the root's rather than any subpackage's, and imports nothing.
ROOT_OWN = frozenset({"django_service_specs.version"})

# What a bare import loaded outside the core when the test was written, for
# the marker's reason. Nothing holds it: a module added outside the core moves
# the real count and leaves this one, so re-measure before leaning on it.
OUTSIDE_TODAY = 69

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
for core in {CORE!r}:
    importlib.import_module(f"django_service_specs.{{core}}")
print(json.dumps(sorted(m for m in sys.modules if m.startswith("django_service_specs."))))
"""

_BARE_PROBE = """
import json, sys
import django
django.setup()
import django_service_specs
print(json.dumps(sorted(m for m in sys.modules if m.startswith("django_service_specs."))))
"""


def _loaded(probe: str) -> frozenset[str]:
    completed = subprocess.run(
        [sys.executable, "-c", probe], cwd=REPO_ROOT, capture_output=True, text=True
    )
    # Raised rather than asserted, so a probe that cannot run is an error even
    # inside the expected failure below, which absorbs only an AssertionError.
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr)
    return frozenset(json.loads(completed.stdout))


@pytest.fixture(scope="module")
def closure() -> frozenset[str]:
    return _loaded(_CLOSURE_PROBE)


@pytest.fixture(scope="module")
def bare() -> frozenset[str]:
    return _loaded(_BARE_PROBE)


def test_the_probes_see_the_core_and_the_rest(
    closure: frozenset[str], bare: frozenset[str]
) -> None:
    # The negative control for the test below: a closure probe that loaded
    # everything, or nothing, or a bare probe that missed what it loaded,
    # would let the boundary pass or fail for a reason that is not the code.
    for core in (
        "django_service_specs.dispatch.dispatch",
        "django_service_specs.registry.spec_registry",
        "django_service_specs.authorization.resolve_principal",
    ):
        assert core in closure
    assert not any(
        m.startswith(("django_service_specs.http", "django_service_specs.commands"))
        for m in closure
    )
    assert closure <= bare
    assert "django_service_specs.http" in bare


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        f"A bare import loads {OUTSIDE_TODAY} modules outside the core, because the root "
        "re-exports every subpackage. Holding the boundary is the work this test waits on."
    ),
)
def test_a_bare_import_loads_only_the_core(closure: frozenset[str], bare: frozenset[str]) -> None:
    assert sorted(bare - closure - ROOT_OWN) == []
