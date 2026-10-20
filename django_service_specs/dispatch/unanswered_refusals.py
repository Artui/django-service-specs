"""``unanswered_refusals`` - what a transport's refusal-to-outcome map leaves unanswered."""

from __future__ import annotations

from collections.abc import Callable, Sequence, Set

from django_service_specs.dispatch.refusals import REFUSALS
from django_service_specs.parameters.coded_message import CodedMessage
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.services.action_unavailable import ActionUnavailable
from django_service_specs.services.additional_input_required import AdditionalInputRequired
from django_service_specs.services.service_error import ServiceError
from django_service_specs.services.service_validation_error import ServiceValidationError
from django_service_specs.types.dispatch_error import DispatchError

_BUILDERS: dict[type[BaseException], Callable[[], DispatchError | ServiceError]] = {
    InvalidArguments: lambda: InvalidArguments(
        {"title": [CodedMessage("This field is required.", "required")]}
    ),
    ServiceValidationError: lambda: ServiceValidationError("This value is invalid."),
    ActionUnavailable: lambda: ActionUnavailable(code="unavailable"),
    AdditionalInputRequired: lambda: AdditionalInputRequired("One more value is needed."),
}
"""The refusals whose constructor needs an argument; every other one is built bare.

Each built as a dispatch or a service raises it, so a map reading what it
carries - a tree, a code, a detail - reads a real one. The tree is the one the
shape check raises for a required argument nobody sent, its message a
``CodedMessage`` carrying ``"required"``."""


def unanswered_refusals(
    answers: Callable[[DispatchError | ServiceError], object]
    | Sequence[tuple[type[BaseException], object]],
    *,
    unanswered: object = None,
) -> tuple[str, ...]:
    """What a transport's map from the kernel's refusals to its outcomes leaves unanswered.

    One sentence per finding, and none for a map that answers every one of
    [`REFUSALS`][django_service_specs.dispatch.refusals.REFUSALS], so a transport
    holds its map from its own test suite with
    ``assert unanswered_refusals(...) == ()`` and reads what is wrong in the
    failure. Each transport keeps its own vocabulary - an exit code, a status, a
    run state - and this checks only that the vocabulary is total.

    ``answers`` is the map in one of two shapes:

    - **An ordered table of ``(refusal class, outcome)`` rows**, read top to
      bottom by ``isinstance`` with the first match winning, which is how the
      kernel's own maps are written. A refusal is answered with the outcome
      of the first row whose class it is an instance of, so a row for a base
      answers every refusal under it, and a catch-all row of ``Exception``
      answers them all. A row whose outcome is ``unanswered`` answers
      nothing, and a refusal it catches first is unanswered whatever a later
      row says, as for the callable below. Pass the table itself.
    - **A callable**, given one instance of each refusal and answering with its
      outcome, for a map written as code. A refusal is unanswered when the
      callable returns ``unanswered`` (compared with ``==``, so a falsy
      outcome such as ``0`` is still an answer). Whatever it raises
      propagates: a map that cannot answer a refusal without raising is
      broken in a way this should not hide. A mapping looked up by the
      error's exact class passes ``lambda error: table.get(type(error))``,
      since reading it as ordered rows would let a base's key answer for a
      subclass the lookup never reaches.

    Three findings, each in its own words:

    - ``nothing in the map answers NotPermitted``: a refusal no row, or no
      call, answers.
    - ``nothing in the map answers DispatchError itself, though it answers
      every refusal under it, and DispatchError may be raised bare``: the map
      looks complete and is not. Either family base may be raised bare: the
      kernel raises neither itself, but a project's own code may, and
      ``ServiceConflict`` is a base too.
    - ``the row for ServiceConflict never answers: the row for ServiceError
      above it answers every ServiceConflict first``: the precedence trap of
      an ordered table, a subclass's row below its base's. Reported for every
      row, a transport's own refusal's included, since a row nothing reaches
      is dead whoever's refusal it names.

    The precedence trap is reported for a table only. A callable's order is
    code, and a branch for a subclass below its base's is a body that never
    runs, which the transport's own branch coverage reports; a table's order
    is data, which coverage reads as one expression.
    """
    if callable(answers):
        answered = {kind for kind in REFUSALS if answers(_BUILDERS.get(kind, kind)()) != unanswered}
        shadowed: list[str] = []
    else:
        # The first matching row's outcome, read as the ladder reads it. Held
        # in tests/dispatch/test_unanswered_refusals.py:
        # ``test_the_first_matching_row_answers_even_when_it_answers_unanswered``
        # fails if any matching row may answer instead of the first, and
        # ``test_a_table_and_the_callable_reading_it_find_the_same`` fails both
        # for that and if the outcome is not read at all.
        answered = {
            kind
            for kind in REFUSALS
            if next((outcome for row, outcome in answers if issubclass(kind, row)), unanswered)
            != unanswered
        }
        shadowed = _shadowed_rows([row for row, _ in answers])
    return (*(_unanswered(kind, answered) for kind in REFUSALS if kind not in answered), *shadowed)


def _unanswered(kind: type[BaseException], answered: Set[type[BaseException]]) -> str:
    """The sentence for ``kind``, which nothing answers."""
    under = [other for other in REFUSALS if other is not kind and issubclass(other, kind)]
    # Two conjuncts, each held in tests/dispatch/test_unanswered_refusals.py:
    # ``test_a_refusal_with_nothing_under_it_is_never_called_a_base`` fails
    # without the first (with nothing under it, "every refusal under it" is
    # vacuously answered), and
    # ``test_a_family_with_no_row_is_each_refusal_in_it_unanswered`` without
    # the second (a map missing a whole family does not look complete).
    if under and all(other in answered for other in under):
        return (
            f"nothing in the map answers {kind.__name__} itself, though it answers every "
            f"refusal under it, and {kind.__name__} may be raised bare"
        )
    return f"nothing in the map answers {kind.__name__}"


def _shadowed_rows(rows: list[type[BaseException]]) -> list[str]:
    """A sentence for each row an earlier row of its own base, or its own class, already answers."""
    found = []
    for index, row in enumerate(rows):
        above = next((earlier for earlier in rows[:index] if issubclass(row, earlier)), None)
        if above is not None:
            found.append(
                f"the row for {row.__name__} never answers: the row for {above.__name__} "
                f"above it answers every {row.__name__} first"
            )
    return found
