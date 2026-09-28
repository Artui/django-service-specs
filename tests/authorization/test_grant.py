from __future__ import annotations

import copy
import pickle
from collections.abc import Callable

import pytest

from django_service_specs.authorization.grant import Grant
from django_service_specs.authorization.unrestricted import Unrestricted
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec


def _spec() -> SelectorSpec:
    return SelectorSpec(kind=SelectorKind.LIST, selector=list, permissions=[Unrestricted()])


def test_covers_exactly_one_spec_and_one_principal_by_identity() -> None:
    spec, principal = _spec(), object()
    grant = Grant(spec, principal)
    assert grant.target_checked is False
    assert grant.covers(spec, principal)
    assert not grant.covers(_spec(), principal)
    assert not grant.covers(spec, object())


@pytest.mark.parametrize("serialize", [pickle.dumps, copy.copy])
def test_refuses_to_be_serialized(serialize: Callable[[Grant], object]) -> None:
    grant = Grant(_spec(), object())
    with pytest.raises(TypeError, match="cannot be serialized"):
        serialize(grant)
