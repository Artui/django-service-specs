"""The refusal-coverage section's example, run, and each finding the page quotes."""

from __future__ import annotations

from django_service_specs import (
    ActionUnavailable,
    DispatchError,
    InvalidArguments,
    NotPermitted,
    PrincipalUnavailable,
    ServiceConflict,
    ServiceError,
    ServiceValidationError,
    unanswered_refusals,
)
from docs.examples import refusal_outcomes


def test_the_example_s_own_test_passes() -> None:
    refusal_outcomes.test_every_refusal_has_an_outcome()


def test_each_refusal_takes_its_nearest_listed_base_s_outcome() -> None:
    assert refusal_outcomes.outcome_for(InvalidArguments({})) == "invalid"
    assert refusal_outcomes.outcome_for(NotPermitted()) == "denied"
    assert refusal_outcomes.outcome_for(ActionUnavailable(code="archived")) == "conflict"
    assert refusal_outcomes.outcome_for(ServiceValidationError("Taken.")) == "refused"
    assert refusal_outcomes.outcome_for(RuntimeError("a bug")) == "failed"


def test_the_bare_base_finding_the_page_quotes() -> None:
    rows = tuple(row for row in refusal_outcomes.OUTCOMES if row[0] is not DispatchError)
    assert unanswered_refusals((*rows, (InvalidArguments, "invalid"))) == (
        "nothing in the map answers DispatchError itself, though it answers every refusal "
        "under it, and DispatchError may be raised bare",
    )


def test_the_precedence_finding_the_page_quotes() -> None:
    rows = (
        (NotPermitted, "denied"),
        (PrincipalUnavailable, "denied"),
        (DispatchError, "invalid"),
        (ServiceError, "refused"),
        (ServiceConflict, "conflict"),
    )
    assert unanswered_refusals(rows) == (
        "the row for ServiceConflict never answers: the row for ServiceError above it "
        "answers every ServiceConflict first",
    )
