from __future__ import annotations

import copy

from django_service_specs.types.unset import UNSET, UnsetType


def test_unset_is_a_falsy_singleton_that_survives_copying() -> None:
    assert UnsetType() is UNSET
    assert not UNSET
    assert repr(UNSET) == "UNSET"
    assert copy.copy(UNSET) is UNSET
    assert copy.deepcopy({"a": UNSET})["a"] is UNSET


def test_unset_is_not_none() -> None:
    # The trap every consumer of the sentinel has to know: a check written as
    # ``default is not None`` treats an undeclared default as a declared one.
    assert UNSET is not None
