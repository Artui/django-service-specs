from __future__ import annotations

import dataclasses

import pytest

from django_service_specs import (
    DispatchError,
    NotPermitted,
    ServiceConflict,
    ServiceError,
    unanswered_refusals,
)
from django_service_specs.types.refusal_finding import RefusalFinding
from django_service_specs.types.refusal_finding_kind import RefusalFindingKind


def test_it_is_what_the_check_returns_and_compares_by_value() -> None:
    found = unanswered_refusals(((DispatchError, 1), (ServiceError, 2), (ServiceConflict, 3)))
    assert found == (
        RefusalFinding(ServiceConflict, RefusalFindingKind.SHADOWED_ROW, ServiceError),
    )
    assert type(found[0]) is RefusalFinding


def test_only_a_shadowed_row_names_the_row_above_it() -> None:
    found = unanswered_refusals(lambda error: None if type(error) is NotPermitted else 1)
    assert found == (RefusalFinding(NotPermitted, RefusalFindingKind.UNANSWERED),)
    assert found[0].shadowed_by is None


def test_it_is_frozen_and_hashable() -> None:
    finding = RefusalFinding(NotPermitted, RefusalFindingKind.UNANSWERED)
    with pytest.raises(dataclasses.FrozenInstanceError):
        finding.kind = RefusalFindingKind.BARE_BASE  # type: ignore[misc]
    assert {finding, RefusalFinding(NotPermitted, RefusalFindingKind.UNANSWERED)} == {finding}


def test_it_carries_its_three_fields_and_nothing_else() -> None:
    assert [field.name for field in dataclasses.fields(RefusalFinding)] == [
        "refusal",
        "kind",
        "shadowed_by",
    ]


@pytest.mark.parametrize(
    ("finding", "words"),
    [
        (
            RefusalFinding(NotPermitted, RefusalFindingKind.UNANSWERED),
            "nothing in the map answers NotPermitted",
        ),
        (
            RefusalFinding(DispatchError, RefusalFindingKind.BARE_BASE),
            "nothing in the map answers DispatchError itself, though it answers every refusal "
            "under it, and DispatchError may be raised bare",
        ),
        (
            RefusalFinding(ServiceConflict, RefusalFindingKind.SHADOWED_ROW, ServiceError),
            "the row for ServiceConflict never answers: the row for ServiceError above it "
            "answers every ServiceConflict first",
        ),
    ],
    ids=["unanswered", "bare_base", "shadowed_row"],
)
def test_str_is_the_finding_in_a_sentence(finding: RefusalFinding, words: str) -> None:
    assert str(finding) == words
