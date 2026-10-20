"""A transport's own outcome for each refusal, and the test that holds the map total."""

from __future__ import annotations

# --8<-- [start:outcomes]
from django_service_specs import (
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


# In the transport's own test suite:
def test_every_refusal_has_an_outcome() -> None:
    assert unanswered_refusals(OUTCOMES) == ()
    assert unanswered_refusals(outcome_for, unanswered="failed") == ()


# --8<-- [end:outcomes]
