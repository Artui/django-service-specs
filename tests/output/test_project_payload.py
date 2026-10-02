from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from django_service_specs.output.audience_projection import AudienceProjection
from django_service_specs.output.audience_projection_for_spec import audience_projection_for_spec
from django_service_specs.output.field_marking import FieldMarking
from django_service_specs.output.project_payload import project_payload
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from tests.dispatch.utils import OPEN, notes_of
from tests.output.utils import PROJECTED_ROW, ROW, InvoicePresenter

LABELS = {"PENDING_REVIEW": "Awaiting review"}


def invoice_projection() -> AudienceProjection:
    spec = SelectorSpec(
        kind=SelectorKind.LIST, selector=notes_of, permissions=OPEN, presenter=InvoicePresenter()
    )
    return audience_projection_for_spec(spec)


def test_drops_hidden_fields_and_speaks_labels_at_every_depth() -> None:
    assert project_payload(ROW, invoice_projection()) == PROJECTED_ROW


def test_leaves_the_payload_it_was_given_alone() -> None:
    payload = deepcopy(ROW)

    project_payload(payload, invoice_projection())

    assert payload == ROW


def test_projects_each_row_of_a_list() -> None:
    assert project_payload([ROW, ROW], invoice_projection()) == [PROJECTED_ROW, PROJECTED_ROW]


def test_leaves_the_payload_it_was_given_alone() -> None:
    row = dict(ROW)

    project_payload(row, invoice_projection())

    assert row == ROW


def test_a_handle_keeps_its_constant() -> None:
    """The second condition of the substitution: a handle is another tool's
    input, so its choices are never spoken."""
    projection = AudienceProjection(
        fields={"kind": FieldMarking.handle()}, choice_labels={"kind": LABELS}
    )

    assert project_payload({"kind": "PENDING_REVIEW"}, projection) == {"kind": "PENDING_REVIEW"}


def test_a_field_with_no_labels_is_passed_through() -> None:
    """The first condition of the substitution: only a field with labels has
    a display to substitute."""
    projection = AudienceProjection(choice_labels={"status": LABELS})

    assert project_payload({"status": "PENDING_REVIEW", "other": "PENDING_REVIEW"}, projection) == {
        "status": "Awaiting review",
        "other": "PENDING_REVIEW",
    }


def test_an_unknown_constant_passes_through() -> None:
    """A stale row naming a choice since removed is still reported."""
    projection = AudienceProjection(choice_labels={"status": LABELS})

    assert project_payload({"status": "VOID"}, projection) == {"status": "VOID"}


@pytest.mark.parametrize(
    "value",
    [["PENDING_REVIEW"], ("PENDING_REVIEW",), {"PENDING_REVIEW"}, frozenset({"PENDING_REVIEW"})],
    ids=["list", "tuple", "set", "frozenset"],
)
def test_each_member_of_a_collection_is_spoken(value: Any) -> None:
    """A collection of constants is substituted member by member: looked up
    whole, a list would be hashed and raise."""
    projection = AudienceProjection(choice_labels={"tags": LABELS})

    assert project_payload({"tags": value}, projection) == {"tags": ["Awaiting review"]}


def test_an_empty_projection_returns_the_payload_itself() -> None:
    payload = {"a": 1}

    assert project_payload(payload, AudienceProjection()) is payload


@pytest.mark.parametrize("payload", [None, "text", 3])
def test_a_payload_that_is_not_an_object_passes_through(payload: Any) -> None:
    projection = AudienceProjection(fields={"a": FieldMarking.hidden()})

    assert project_payload(payload, projection) == payload
