"""The shared phases, where a property is sharper stated on the phase than through dispatch."""

from __future__ import annotations

from typing import Any

import pytest
from django.core.exceptions import ObjectDoesNotExist

from django_service_specs.dispatch.dispatch_result import DispatchResult
from django_service_specs.dispatch.utils import (
    NOT_FOUND,
    call_pool,
    reraise_unless_retrieve,
    validate_arguments,
)
from django_service_specs.pool.null_progress import null_progress
from django_service_specs.pool.pool_seeds import DEFAULT_POOL_SEEDS
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from tests.dispatch.utils import OPEN, PK, Record, Titled

PRINCIPAL = object()
ROW = object()


def test_not_found_is_the_empty_not_found_result() -> None:
    assert DispatchResult(kind="not_found") == NOT_FOUND


def test_the_validator_sees_only_the_arguments_it_declares() -> None:
    validator = Titled()
    spec = ServiceSpec(
        service=Record(),
        permissions=OPEN,
        validator=validator,
        instance_selector_spec=SelectorSpec(
            kind=SelectorKind.RETRIEVE, selector=Record(), reads=PK
        ),
    )

    data = validate_arguments(spec, {"pk": 1, "title": " t "}, principal=PRINCIPAL, target=ROW)

    assert data == {"title": "t"}
    ((arguments, context),) = validator.calls
    assert arguments == {"title": " t "}
    assert context.principal is PRINCIPAL
    assert context.target is ROW


def test_a_spec_with_no_validator_validates_to_nothing() -> None:
    spec = ServiceSpec(service=Record(), permissions=OPEN)

    assert validate_arguments(spec, {"pk": 1}, principal=PRINCIPAL, target=ROW) == {}


@pytest.mark.parametrize("kind", [SelectorKind.RETRIEVE, SelectorKind.LIST])
def test_does_not_exist_is_a_missing_row_only_for_a_retrieve(kind: SelectorKind) -> None:
    spec = SelectorSpec(kind=kind, selector=Record())
    error = ObjectDoesNotExist("gone")

    if kind is SelectorKind.RETRIEVE:
        assert reraise_unless_retrieve(spec, error) is None
        return
    with pytest.raises(ObjectDoesNotExist) as caught:
        reraise_unless_retrieve(spec, error)
    assert caught.value is error


def test_seeds_resolve_before_the_call_s_own_entries_exist() -> None:
    seeds = DEFAULT_POOL_SEEDS.extend(seen=lambda **pool: sorted(pool))

    pool: dict[str, Any] = call_pool(PRINCIPAL, seeds, {"pk": 1, "data": {}})

    assert pool == {
        "user": PRINCIPAL,
        "progress": null_progress,
        "seen": ["progress", "user"],
        "pk": 1,
        "data": {},
    }
