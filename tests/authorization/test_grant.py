from __future__ import annotations

import copy
import pickle
from collections.abc import Callable

import pytest

from django_service_specs.authorization.grant import Grant
from django_service_specs.authorization.unrestricted import Unrestricted
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.spec_source import kernel_spec
from tests.specs.utils import Foreign


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


def test_a_grant_for_a_source_covers_the_source_and_the_spec_it_compiles_to() -> None:
    source, principal = Foreign(_spec()), object()
    grant = Grant(source, principal)

    assert grant.covers(source, principal)
    assert grant.covers(kernel_spec(source), principal)
    # Each held by name: another declaration compiles to another spec, and
    # the principal is still read by identity.
    assert not grant.covers(Foreign(_spec()), principal)
    assert not grant.covers(source, object())


def test_a_grant_for_a_compiled_spec_covers_the_source_it_was_compiled_from() -> None:
    source, principal = Foreign(_spec()), object()

    assert Grant(kernel_spec(source), principal).covers(source, principal)


def test_a_grant_keeps_the_object_it_was_given() -> None:
    # Compiled where it is read rather than when it is built, so the grant a
    # transport holds is the one it constructed, field for field.
    source = Foreign(_spec())

    assert Grant(source, object()).spec is source
