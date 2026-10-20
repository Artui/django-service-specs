"""Each message names the input that produced it, and only that one.

Three findings can answer one map, so every test here is sized to raise
exactly one kind, asserts the whole tuple that came back, and asserts the
other kinds' wording is absent: a bare base and a whole family missing both
leave the base unanswered, and only one of them is the bare-base trap.
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
    UnsupportedMediaType,
)
from django_service_specs.commands.exit_code_for import _CODES, exit_code_for
from django_service_specs.dispatch.refusals import REFUSALS
from django_service_specs.dispatch.unanswered_refusals import unanswered_refusals
from django_service_specs.http.error_response import _STATUSES, error_response
from django_service_specs.types.exit_code import ExitCode

# Each kind's own words, for the negative assertions.
BARE = "may be raised bare"
SHADOWED = "never answers"
UNANSWERED = "nothing in the map answers"


def _unanswered(name: str) -> str:
    return f"nothing in the map answers {name}"


def _bare(name: str) -> str:
    return (
        f"nothing in the map answers {name} itself, though it answers every refusal "
        f"under it, and {name} may be raised bare"
    )


def _shadowed(row: str, above: str) -> str:
    return (
        f"the row for {row} never answers: the row for {above} above it answers every {row} first"
    )


def _rows(*kinds: type[BaseException]) -> tuple[tuple[type[BaseException], str], ...]:
    return tuple((kind, kind.__name__) for kind in kinds)


def _without(found: tuple[str, ...], *words: str) -> bool:
    return not any(word in message for message in found for word in words)


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
        assert found == (
            _unanswered("ServiceError"),
            _unanswered("ServiceNotFound"),
            _unanswered("ServiceConflict"),
            _unanswered("ActionUnavailable"),
            _unanswered("AdditionalInputRequired"),
            _unanswered("ServiceValidationError"),
        )
        assert _without(found, BARE, SHADOWED)


class TestTheBareBaseTrap:
    def test_a_map_answering_every_dispatch_refusal_but_the_base_is_told_so(self) -> None:
        found = unanswered_refusals(
            _rows(InvalidArguments, NotPermitted, PrincipalUnavailable, ServiceError)
        )
        assert found == (_bare("DispatchError"),)
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
        assert found == (_bare("ServiceError"),)
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
        assert found == (_unanswered("ServiceError"), _bare("ServiceConflict"))
        assert _without(found, SHADOWED)

    def test_a_refusal_with_nothing_under_it_is_never_called_a_base(self) -> None:
        # Holds the first conjunct of the bare-base guard: with nothing under
        # NotPermitted, "every refusal under it" is vacuously answered.
        found = unanswered_refusals(
            lambda error: None if type(error) is NotPermitted else "answered"
        )
        assert found == (_unanswered("NotPermitted"),)
        assert _without(found, BARE, SHADOWED)


class TestThePrecedenceTrap:
    def test_a_row_below_its_base_is_told_it_never_answers(self) -> None:
        found = unanswered_refusals(_rows(DispatchError, ServiceError, ServiceConflict))
        assert found == (_shadowed("ServiceConflict", "ServiceError"),)
        assert _without(found, BARE, UNANSWERED)

    def test_the_row_named_is_the_first_one_that_catches_it(self) -> None:
        found = unanswered_refusals(
            _rows(DispatchError, ServiceError, ServiceConflict, ActionUnavailable)
        )
        assert found == (
            _shadowed("ServiceConflict", "ServiceError"),
            _shadowed("ActionUnavailable", "ServiceError"),
        )

    def test_a_repeated_row_never_answers(self) -> None:
        found = unanswered_refusals(_rows(DispatchError, ServiceError, DispatchError))
        assert found == (_shadowed("DispatchError", "DispatchError"),)

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
        found = unanswered_refusals(_rows(DispatchError, UnsupportedMediaType, ServiceError))
        assert found == (_shadowed("UnsupportedMediaType", "DispatchError"),)

    def test_both_traps_in_one_map_are_both_reported(self) -> None:
        rows = _rows(
            InvalidArguments, NotPermitted, PrincipalUnavailable, ServiceError, ServiceConflict
        )
        assert unanswered_refusals(rows) == (
            _bare("DispatchError"),
            _shadowed("ServiceConflict", "ServiceError"),
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
        assert found == (_bare("ServiceError"),)

    def test_a_table_looked_up_by_exact_class_is_passed_as_a_callable(self) -> None:
        # Its keys read as ordered rows would let ServiceConflict answer for
        # ActionUnavailable, which ``table.get(type(error))`` never does.
        table = {kind: kind.__name__ for kind in REFUSALS if kind is not ActionUnavailable}
        assert _unanswered("ActionUnavailable") not in unanswered_refusals(tuple(table.items()))
        assert unanswered_refusals(lambda error: table.get(type(error))) == (
            _unanswered("ActionUnavailable"),
        )

    def test_only_the_unanswered_value_is_unanswered_not_any_falsy_one(self) -> None:
        assert unanswered_refusals(lambda error: 0) == ()
        assert unanswered_refusals(lambda error: None) == tuple(
            _unanswered(kind.__name__) for kind in REFUSALS
        )

    def test_what_the_callable_raises_propagates(self) -> None:
        def answer(error: DispatchError | ServiceError) -> Any:
            raise LookupError(type(error).__name__)

        with pytest.raises(LookupError, match="DispatchError"):
            unanswered_refusals(answer)

    def test_each_refusal_carries_what_a_real_map_reads(self) -> None:
        # error_response reads InvalidArguments' detail, ActionUnavailable's
        # code and AdditionalInputRequired's schema; it has no unanswered
        # value, so this proves the instances, not the map's coverage.
        assert unanswered_refusals(error_response) == ()


class TestTheKernelsOwnMaps:
    def test_the_exit_codes_answer_every_refusal(self) -> None:
        assert unanswered_refusals(_CODES) == ()
        assert unanswered_refusals(exit_code_for, unanswered=ExitCode.ERROR) == ()

    def test_the_http_statuses_answer_every_refusal(self) -> None:
        # The ladder only: error_response's four arms above it are code, and
        # its own tests' branch coverage holds their order.
        assert unanswered_refusals(_STATUSES) == ()
