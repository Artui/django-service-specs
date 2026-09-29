"""pydantic is an extra: the package imports without it, and only this adapter needs it."""

from __future__ import annotations

import subprocess
import sys

# ``None`` in ``sys.modules`` makes any import of that name raise ImportError,
# so the child interpreter behaves as an environment without the extra. A
# fresh interpreter because this one has pydantic imported already.
_PROBE = """
import sys
sys.modules["pydantic"] = None
sys.modules["pydantic_core"] = None
import django_service_specs
print(len(django_service_specs.__all__))
try:
    import django_service_specs.adapters.pydantic
except ImportError:
    print("the adapter needs pydantic")
"""


def test_the_package_imports_without_pydantic_and_only_the_adapter_needs_it() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _PROBE], capture_output=True, text=True, check=True
    )
    exported, refused = result.stdout.split("\n")[:2]
    # The root, and every subpackage it re-exports, imported.
    assert int(exported) > 0
    # The blocker works: the one subpackage that imports pydantic could not.
    assert refused == "the adapter needs pydantic"
