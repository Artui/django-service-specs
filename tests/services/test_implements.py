"""``implements``: unchanged at run time, and a type checker reports drift at the decorator.

The static half is the claim the decorator exists for, so it is run rather than
assumed: ty, which the dev group installs, checks a module of conforming and
drifting callables written out for the test, and must report exactly the
decorator lines marked as drift. ty's own scope is the package, so nothing else
would ever check these.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from django_service_specs.services.create_service import CreateService
from django_service_specs.services.implements import implements

_PREAMBLE = """\
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from typing_extensions import NotRequired, TypedDict, Unpack

from django_service_specs import (
    CreateService,
    DeleteService,
    ListSelector,
    NoInput,
    RetrieveSelector,
    UpdateService,
    implements,
)


class In:
    title: str


class Row:
    pk: int


class Other:
    name: str


class Tenant(TypedDict):
    tenant: NotRequired[str]

"""

_CONFORMING = """
@implements(CreateService[In, Row])
def create(*, data: In, **extras: Any) -> Row:
    raise NotImplementedError


@implements(CreateService[In, Row])
def create_with_typed_extras(*, data: In, **extras: Unpack[Tenant]) -> Row:
    raise NotImplementedError


@implements(UpdateService[In, Row, Row])
def update(*, instance: Row, data: In, **extras: Any) -> Row:
    raise NotImplementedError


@implements(DeleteService[NoInput, Row, None])
def delete(*, instance: Row, **extras: Any) -> None: ...


@implements(DeleteService[In, Row, None])
def delete_with_input(*, instance: Row, data: In | None = None, **extras: Any) -> None: ...


@implements(ListSelector[Row])
def rows(**extras: Any) -> Iterable[Row]:
    raise NotImplementedError


@implements(RetrieveSelector[Row])
def row(**extras: Any) -> Row | None: ...
"""

# Each ``# drift`` line is where ty must report, and nowhere else. A service
# requiring a typed extra is drift too, but the oldest ty the dev group admits
# does not report it, so it is not asserted here.
_DRIFTING = """
@implements(CreateService[In, Row])  # drift
def create_misnamed(*, payload: In, **extras: Any) -> Row:
    raise NotImplementedError


@implements(CreateService[In, Row])  # drift
def create_wrong_return(*, data: In, **extras: Any) -> Other:
    raise NotImplementedError


@implements(CreateService[In, Row])  # drift
def create_without_extras(*, data: In) -> Row:
    raise NotImplementedError


@implements(UpdateService[In, Row, Row])  # drift
def update_another_type(*, instance: Other, data: In, **extras: Any) -> Row:
    raise NotImplementedError


@implements(DeleteService[NoInput, Row, None])  # drift
def delete_another_type(*, instance: Other, **extras: Any) -> None: ...


@implements(DeleteService[In, Row, None])  # drift
def delete_requiring_input(*, instance: Row, data: In, **extras: Any) -> None: ...


@implements(ListSelector[Row])  # drift
def rows_of_another_type(**extras: Any) -> Iterable[Other]:
    raise NotImplementedError


@implements(RetrieveSelector[Row])  # drift
def row_of_another_type(**extras: Any) -> Other | None: ...
"""


def _reported_lines(tmp_path: Path, source: str) -> set[int]:
    """The lines ty reports an error on, checking ``source`` against this environment."""
    module = tmp_path / "conformance.py"
    module.write_text(source)
    # Outside the project, so no ``[tool.ty]`` scope applies, and against this
    # interpreter's environment, so the package resolves as a consumer sees it.
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "ty",
            "check",
            "--python",
            sys.prefix,
            "--output-format",
            "concise",
            str(module),
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        check=False,
    )
    # ty ran and checked the module, or no diagnostics would read as conforming.
    assert re.search(r"All checks passed|Found \d+ diagnostic", completed.stdout), (
        completed.stdout + completed.stderr
    )
    return {int(line) for line in re.findall(r"conformance\.py:(\d+):\d+: error", completed.stdout)}


def _marked_lines(source: str) -> set[int]:
    return {number for number, line in enumerate(source.splitlines(), 1) if "# drift" in line}


def test_it_returns_the_callable_unchanged() -> None:
    def create_note(*, data: Mapping[str, Any], **extras: Any) -> str:
        return data["title"]

    decorated = implements(CreateService[Mapping[str, Any], str])(create_note)

    assert decorated is create_note
    assert decorated(data={"title": "Minutes"}, user=None) == "Minutes"


def test_a_conforming_callable_is_not_reported(tmp_path: Path) -> None:
    assert _reported_lines(tmp_path, _PREAMBLE + _CONFORMING) == set()


def test_every_drift_is_reported_at_its_decorator(tmp_path: Path) -> None:
    source = _PREAMBLE + _DRIFTING

    assert _reported_lines(tmp_path, source) == _marked_lines(source)
