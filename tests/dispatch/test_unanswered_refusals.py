"""Each finding names the input that produced it, and only that one.

Three findings can answer one map, so every test here is sized to raise
exactly one kind, asserts the whole tuple that came back, and asserts the
other kinds are absent: a bare base and a whole family missing both leave the
base unanswered, and only one of them is the bare-base trap.

No name this module's subject returns is imported, so each test runs against a
tree that returned sentences and fails at the field it reads rather than at
import.
"""

from __future__ import annotations

from typing import Any

import pytest

from django_service_specs import (
    ActionUnavailable,
    AdditionalInputRequired,
    DispatchError,
    InvalidArguments,
    NotPermitted,
    PrincipalUnavailable,
    ServiceConflict,
    ServiceError,
    ServiceNotFound,
    ServiceValidationError,
)
from django_service_specs.dispatch.refusals import REFUSALS
from django_service_specs.dispatch.unanswered_refusals import unanswered_refusals
from django_service_specs.parameters.check_arguments import check_arguments
from django_service_specs.parameters.parameters import Parameter, Parameters

# Each kind's value, for the negative assertions. A plain string compares
# equal to its ``RefusalFindingKind`` member, which ``str`` subclasses.
BARE = "bare_base"
SHADOWED = "shadowed_row"
UNANSWERED = "unanswered"

Fact = tuple[type[BaseException], str, type[BaseException] | None]


class _TransportRefusal(DispatchError):
    """A refusal a transport defines for itself, below the kernel's base."""


def _unanswered(kind: type[BaseException]) -> Fact:
    return (kind, UNANSWERED, None)


def _bare(kind: type[BaseException]) -> Fact:
    return (kind, BARE, None)


def _shadowed(row: type[BaseException], above: type[BaseException]) -> Fact:
    return (row, SHADOWED, above)


def _facts(found: tuple[Any, ...]) -> tuple[Fact, ...]:
    # Read through the finding's fields, so the comparison is with what a
    # transport filters by and never with the words.
    return tuple((finding.refusal, finding.kind, finding.shadowed_by) for finding in found)


def _rows(*kinds: type[BaseException]) -> tuple[tuple[type[BaseException], str], ...]:
    return tuple((kind, kind.__name__) for kind in kinds)


def _without(found: tuple[Any, ...], *kinds: str) -> bool:
    return not any(finding.kind in kinds for finding in found)


class TestAnOrderedMap:
    def test_a_map_answering_each_family_at_its_base_answers_everything(self) -> None:
        assert unanswered_refusals(_rows(DispatchError, ServiceError)) == ()

    def test_a_row_for_a_base_answers_every_refusal_under_it(self) -> None:
        rows = _rows(
            NotPermitted, PrincipalUnavailable, DispatchError, ServiceConflict, ServiceError
        )
        assert unanswered_refusals(rows) == ()

    def test_a_catch_all_row_answers_everything(self) -> None:
        assert unanswered_refusals(_rows(Exception)) == ()

    def test_a_family_with_no_row_is_each_refusal_in_it_unanswered(self) -> None:
        # Not the bare-base message for ServiceError or ServiceConflict: the
        # refusals under each are missing too, so the map does not look
        # complete. Holds the second conjunct of the bare-base guard.
        found = unanswered_refusals(_rows(DispatchError))
        assert _facts(found) == (
            _unanswered(ServiceError),
            _unanswered(ServiceNotFound),
            _unanswered(ServiceConflict),
            _unanswered(ActionUnavailable),
            _unanswered(AdditionalInputRequired),
            _unanswered(ServiceValidationError),
        )
        assert _without(found, BARE, SHADOWED)

    def test_a_table_and_the_callable_reading_it_find_the_same(self) -> None:
        # The table carries a row whose outcome is the unanswered value and no
        # row below its own base, so the only thing that can tell the two
        # shapes apart is whether the table reads that outcome. Holds the
        # ``!= unanswered`` comparison of the table form.
        rows: tuple[tuple[type[BaseException], object], ...] = (
            (NotPermitted, None),
            (DispatchError, "invalid"),
            (ServiceError, "refused"),
        )

        def answer(error: DispatchError | ServiceError) -> object:
            return next((outcome for kind, outcome in rows if isinstance(error, kind)), None)

        assert _facts(unanswered_refusals(rows)) == (_unanswered(NotPermitted),)
        assert unanswered_refusals(rows) == unanswered_refusals(answer)

    def test_the_first_matching_row_answers_even_when_it_answers_unanswered(self) -> None:
        # The base's row reads as no answer, and a subclass row below it with
        # a real outcome is never reached: first match wins, and the refusal
        # takes the base's outcome. Holds first-match against a reading that
        # takes any matching row's outcome.
        rows = (
            (DispatchError, "invalid"),
            (ServiceError, "unanswered"),
            (ServiceConflict, "conflict"),
        )
        found = unanswered_refusals(rows, unanswered="unanswered")
        assert _facts(found) == (
            _unanswered(ServiceError),
            _unanswered(ServiceNotFound),
            _unanswered(ServiceConflict),
            _unanswered(ActionUnavailable),
            _unanswered(AdditionalInputRequired),
            _unanswered(ServiceValidationError),
            _shadowed(ServiceConflict, ServiceError),
        )


class TestTheBareBaseTrap:
    def test_a_map_answering_every_dispatch_refusal_but_the_base_is_told_so(self) -> None:
        found = unanswered_refusals(
            _rows(InvalidArguments, NotPermitted, PrincipalUnavailable, ServiceError)
        )
        assert _facts(found) == (_bare(DispatchError),)
        assert _without(found, SHADOWED)

    def test_a_map_answering_every_service_refusal_but_the_base_is_told_so(self) -> None:
        rows = _rows(
            DispatchError,
            ServiceNotFound,
            ServiceConflict,
            AdditionalInputRequired,
            ServiceValidationError,
        )
        found = unanswered_refusals(rows)
        assert _facts(found) == (_bare(ServiceError),)
        assert _without(found, SHADOWED)

    def test_it_holds_at_a_base_below_the_top_of_its_family(self) -> None:
        # ServiceConflict is a base too: ActionUnavailable is under it. Its
        # own base is left plain, since ServiceConflict is missing beneath it.
        rows = _rows(
            DispatchError,
            ServiceNotFound,
            ActionUnavailable,
            AdditionalInputRequired,
            ServiceValidationError,
        )
        found = unanswered_refusals(rows)
        assert _facts(found) == (_unanswered(ServiceError), _bare(ServiceConflict))
        assert _without(found, SHADOWED)

    def test_a_refusal_with_nothing_under_it_is_never_called_a_base(self) -> None:
        # Holds the first conjunct of the bare-base guard: with nothing under
        # NotPermitted, "every refusal under it" is vacuously answered.
        found = unanswered_refusals(
            lambda error: None if type(error) is NotPermitted else "answered"
        )
        assert _facts(found) == (_unanswered(NotPermitted),)
        assert _without(found, BARE, SHADOWED)


class TestThePrecedenceTrap:
    def test_a_row_below_its_base_is_told_it_never_answers(self) -> None:
        found = unanswered_refusals(_rows(DispatchError, ServiceError, ServiceConflict))
        assert _facts(found) == (_shadowed(ServiceConflict, ServiceError),)
        assert _without(found, BARE, UNANSWERED)

    def test_the_row_named_is_the_first_one_that_catches_it(self) -> None:
        found = unanswered_refusals(
            _rows(DispatchError, ServiceError, ServiceConflict, ActionUnavailable)
        )
        assert _facts(found) == (
            _shadowed(ServiceConflict, ServiceError),
            _shadowed(ActionUnavailable, ServiceError),
        )

    def test_a_repeated_row_never_answers(self) -> None:
        found = unanswered_refusals(_rows(DispatchError, ServiceError, DispatchError))
        assert _facts(found) == (_shadowed(DispatchError, DispatchError),)

    def test_a_row_a_subclass_sits_above_is_not_reported(self) -> None:
        assert (
            unanswered_refusals(
                _rows(ActionUnavailable, ServiceConflict, ServiceError, DispatchError)
            )
            == ()
        )

    def test_a_transport_s_own_row_below_its_base_is_reported(self) -> None:
        # The check covers the kernel's refusals, but a row that can never be
        # reached is dead whoever's refusal it names.
        found = unanswered_refusals(_rows(DispatchError, _TransportRefusal, ServiceError))
        assert _facts(found) == (_shadowed(_TransportRefusal, DispatchError),)

    def test_both_traps_in_one_map_are_both_reported(self) -> None:
        rows = _rows(
            InvalidArguments, NotPermitted, PrincipalUnavailable, ServiceError, ServiceConflict
        )
        assert _facts(unanswered_refusals(rows)) == (
            _bare(DispatchError),
            _shadowed(ServiceConflict, ServiceError),
        )


class TestACallable:
    def test_it_is_called_once_with_each_refusal_of_exactly_its_class(self) -> None:
        seen: list[type[BaseException]] = []

        def answer(error: DispatchError | ServiceError) -> str:
            seen.append(type(error))
            return "answered"

        assert unanswered_refusals(answer) == ()
        assert seen == list(REFUSALS)

    def test_a_callable_answering_every_subclass_but_the_base_is_told_so(self) -> None:
        found = unanswered_refusals(
            lambda error: "failed" if type(error) is ServiceError else "refused",
            unanswered="failed",
        )
        assert _facts(found) == (_bare(ServiceError),)

    def test_a_table_looked_up_by_exact_class_is_passed_as_a_callable(self) -> None:
        # Its keys read as ordered rows would let ServiceConflict answer for
        # ActionUnavailable, which ``table.get(type(error))`` never does.
        table = {kind: kind.__name__ for kind in REFUSALS if kind is not ActionUnavailable}
        assert _unanswered(ActionUnavailable) not in _facts(
            unanswered_refusals(tuple(table.items()))
        )
        assert _facts(unanswered_refusals(lambda error: table.get(type(error)))) == (
            _unanswered(ActionUnavailable),
        )

    def test_only_the_unanswered_value_is_unanswered_not_any_falsy_one(self) -> None:
        assert unanswered_refusals(lambda error: 0) == ()
        assert _facts(unanswered_refusals(lambda error: None)) == tuple(
            _unanswered(kind) for kind in REFUSALS
        )

    def test_what_the_callable_raises_propagates(self) -> None:
        def answer(error: DispatchError | ServiceError) -> Any:
            raise LookupError(type(error).__name__)

        with pytest.raises(LookupError, match="DispatchError"):
            unanswered_refusals(answer)

    def test_each_refusal_carries_what_a_real_map_reads(self) -> None:
        # An HTTP map reads every refusal's message, InvalidArguments' and
        # ServiceValidationError's detail, ActionUnavailable's code and
        # AdditionalInputRequired's schema; reading one an instance lacks
        # raises here. It has no unanswered value, so this proves the
        # instances, not the map's coverage.
        def answer(error: DispatchError | ServiceError) -> Any:
            if isinstance(error, (InvalidArguments, ServiceValidationError)):
                return error.detail
            if isinstance(error, ActionUnavailable):
                return {"detail": error.message, "code": error.code}
            if isinstance(error, AdditionalInputRequired):
                return {"detail": error.message, "schema": error.schema}
            return {"detail": error.message}

        assert unanswered_refusals(answer) == ()

    def test_invalid_arguments_carries_the_tree_the_shape_check_raises(self) -> None:
        # Compared message by message rather than by tree: a CodedMessage
        # equals its plain words, so tree equality passes with no code at all.
        seen: list[InvalidArguments] = []

        def answer(error: DispatchError | ServiceError) -> str:
            if isinstance(error, InvalidArguments):
                seen.append(error)
            return "answered"

        unanswered_refusals(answer)
        with pytest.raises(InvalidArguments) as raised:
            check_arguments(Parameters.of(Parameter("title", "string", required=True)), {})
        (built,) = seen
        assert built.detail.keys() == raised.value.detail.keys()
        for key, messages in built.detail.items():
            real = raised.value.detail[key]
            assert [(type(m), m, getattr(m, "code", None)) for m in messages] == [
                (type(m), m, getattr(m, "code", None)) for m in real
            ]
        assert built.detail["title"][0].code == "required"


def test_a_table_given_as_a_generator_is_read_as_the_same_table() -> None:
    rows = ((DispatchError, 1), (ServiceError, 2), (ServiceConflict, 3))
    assert unanswered_refusals(row for row in rows) == unanswered_refusals(rows)
