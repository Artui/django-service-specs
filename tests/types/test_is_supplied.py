from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from django_service_specs.types.is_supplied import is_supplied
from django_service_specs.types.unset import UNSET

# Every ``assert_type`` here holds only if ``is_supplied`` narrows, and those in
# the ``else`` branches only if ``UnsetType`` is final, so that nothing but
# ``UNSET`` is left there. ``plain`` is the same predicate returning ``bool``,
# which is what ``value is not UNSET`` amounts to for a type checker: the line
# marked ``# drift`` is the one ty must report, so a narrowing that stopped
# working fails the test from both sides.
_SOURCE = """\
from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

from typing_extensions import assert_type

from django_service_specs import UNSET, UnsetType, is_supplied, supplied_fields

T = TypeVar("T")


def plain(value: T | UnsetType) -> bool:
    return value is not UNSET


@dataclass
class Patch:
    name: str | UnsetType = UNSET
    bio: str | None | UnsetType = UNSET


def read(name: str | UnsetType, bio: str | None | UnsetType, patch: Patch) -> None:
    if is_supplied(name):
        assert_type(name, str)
    if is_supplied(bio):
        assert_type(bio, str | None)
    else:
        assert_type(bio, UnsetType)
    if is_supplied(patch.bio):
        assert_type(patch.bio, str | None)
    else:
        assert_type(patch.bio, UnsetType)
    if plain(name):
        assert_type(name, str)  # drift


def fields_of(patch: Patch) -> None:
    supplied_fields(patch)
    supplied_fields({"name": UNSET})
    supplied_fields(3)  # drift
"""


def _reported_lines(tmp_path: Path, source: str) -> set[int]:
    """The lines ty reports an error on, checking ``source`` against this environment."""
    module = tmp_path / "narrowing.py"
    module.write_text(source)
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
    assert re.search(r"All checks passed|Found \d+ diagnostic", completed.stdout), (
        completed.stdout + completed.stderr
    )
    return {int(line) for line in re.findall(r"narrowing\.py:(\d+):\d+: error", completed.stdout)}


def test_it_narrows_a_supplied_value_to_its_type_and_a_bool_does_not(tmp_path: Path) -> None:
    marked = {number for number, line in enumerate(_SOURCE.splitlines(), 1) if "# drift" in line}

    assert _reported_lines(tmp_path, _SOURCE) == marked


def test_none_is_supplied_and_only_unset_is_not() -> None:
    assert is_supplied(None)
    assert is_supplied("")
    assert is_supplied(0)
    assert not is_supplied(UNSET)
