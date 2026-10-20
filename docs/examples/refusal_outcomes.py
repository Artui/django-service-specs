"""A transport's own outcome for each refusal, and the test that holds the map total."""

from __future__ import annotations

# --8<-- [start:outcomes]
from django_service_specs import (
    AdditionalInputRequired,
    DispatchError,
    NotPermitted,
    PrincipalUnavailable,
    ServiceConflict,
    ServiceError,
    ServiceNotFound,
    unanswered_refusals,
)

OUTCOMES = (
    (NotPermitted, "denied"),
    (PrincipalUnavailable, "denied"),
    (DispatchError, "invalid"),
    (ServiceNotFound, "gone"),
    (ServiceConflict, "conflict"),
    (ServiceError, "refused"),
)
"""Read top to bottom, first match wins, so each subclass sits above its base."""


def outcome_for(error: BaseException) -> str:
    """The outcome a run that raised ``error`` ends in: ``failed`` for anything undeclared."""
    return next((outcome for kind, outcome in OUTCOMES if isinstance(error, kind)), "failed")


NO_QUESTIONS = ((AdditionalInputRequired, "failed"), *OUTCOMES)
"""For a queue with nobody to ask: a run that needs more input fails like a bug."""


# In the transport's own test suite:
def test_every_refusal_has_an_outcome() -> None:
    assert unanswered_refusals(OUTCOMES) == ()
    assert unanswered_refusals(outcome_for, unanswered="failed") == ()


def test_the_queue_leaves_one_refusal_unanswered_on_purpose() -> None:
    # Filtered by class, never by the finding's words.
    found = unanswered_refusals(NO_QUESTIONS, unanswered="failed")
    assert [finding for finding in found if finding.refusal is not AdditionalInputRequired] == []


# --8<-- [end:outcomes]
