"""``row_affordance_answers``: one row's affordances, read off the row itself."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.affordances.row_affordance_answers import row_affordance_answers
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.present import present
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.selector_kind import SelectorKind
from tests.dispatch.utils import (
    BOOKS_CLOSED,
    BOOKS_OPEN,
    EDIT,
    NOT_ARCHIVED,
    OPEN,
    RENAME,
    NoteRows,
    Record,
    make_user,
    notes_of,
)
from tests.dispatch_app.models import Note
from tests.specs.utils import Foreign

ARCHIVED_ANSWER = {
    "available": False,
    "code": "note_archived",
    "reason": "An archived note cannot be renamed.",
}


def listing(selector: Any = notes_of, **fields: Any) -> SelectorSpec:
    fields.setdefault("affordances", {"rename": RENAME, "edit": EDIT})
    return SelectorSpec(kind=SelectorKind.LIST, selector=selector, permissions=OPEN, **fields)


def rows_of(spec: SelectorSpec, user: Any) -> list[Any]:
    # What dispatch hands a transport: the rows carrying the answers it wrote,
    # so the alias read here is the one dispatch actually produced.
    return list(dispatch(spec, principal=user, arguments={}).value)


@pytest.fixture
def ada() -> Any:
    return make_user("ada")


@pytest.fixture
def two_notes(ada: Any) -> tuple[Note, Note]:
    return (
        Note.objects.create(owner=ada, title="live"),
        Note.objects.create(owner=ada, title="archived", archived=True),
    )


@pytest.mark.django_db
class TestARowDispatchAnswered:
    def test_an_instance_row_answers_every_declared_name(self, ada: Any, two_notes: Any) -> None:
        spec = listing()
        live, archived = rows_of(spec, ada)

        assert row_affordance_answers(spec, live) == {
            "rename": {"available": True},
            "edit": {"available": True},
        }
        assert row_affordance_answers(spec, archived) == {
            "rename": ARCHIVED_ANSWER,
            "edit": {"available": True},
        }

    def test_a_mapping_row_answers_from_its_keys(self, ada: Any) -> None:
        callable_only = ServiceSpec(service=Record(), permissions=OPEN, affordances=[BOOKS_CLOSED])
        spec = listing(lambda: [{"id": 1}], affordances={"close": callable_only})
        (row,) = rows_of(spec, ada)

        assert isinstance(row, dict)
        assert row_affordance_answers(spec, row) == {
            "close": {
                "available": False,
                "code": "books_closed",
                "reason": "Renaming is paused while the books close.",
            }
        }

    def test_it_is_what_present_puts_on_the_presented_row(self, ada: Any, two_notes: Any) -> None:
        spec = listing(presenter=NoteRows())
        result = dispatch(spec, principal=ada, arguments={})
        rows = list(result.value)

        presented = present(spec, result)

        assert [row_affordance_answers(spec, row) for row in rows] == [
            item["affordances"] for item in presented
        ]
        # And the two rows differ, so agreement is not two identical answers.
        assert presented[0]["affordances"] != presented[1]["affordances"]

    def test_a_service_spec_is_read_through_its_output_selector(
        self, ada: Any, two_notes: Any
    ) -> None:
        live, archived = two_notes
        output = listing(
            lambda *, result: Note.objects.filter(pk__in=result), affordances={"rename": RENAME}
        )
        # Its own affordances are what it is checked against and are never
        # presented: only the output selector's mapping answers a row.
        spec = ServiceSpec(
            service=lambda: [live.pk, archived.pk],
            permissions=OPEN,
            affordances=[BOOKS_OPEN],
            output_selector_spec=output,
        )
        _, archived_row = dispatch(spec, principal=ada, arguments={}).value

        assert row_affordance_answers(spec, archived_row) == {"rename": ARCHIVED_ANSWER}

    def test_a_foreign_declaration_is_read_as_its_compiled_spec_is(
        self, ada: Any, two_notes: Any
    ) -> None:
        spec = listing()
        _, archived = rows_of(spec, ada)

        answers = row_affordance_answers(Foreign(spec), archived)

        assert answers == row_affordance_answers(spec, archived)
        assert answers["rename"] == ARCHIVED_ANSWER


class TestWalkOrder:
    """Both conditions are unmet on the archived row, so the order is what answers."""

    def answers(self, *order: Any) -> dict[str, Any]:
        both = ServiceSpec(service=Record(), permissions=OPEN, affordances=list(order))
        spec = listing(affordances={"rename": both})
        row = SimpleNamespace(
            affordance__rename__note_archived=False, affordance__rename__books_closed=False
        )
        return row_affordance_answers(spec, row)["rename"]

    def test_the_first_unmet_condition_reports_and_the_second_is_not_named(self) -> None:
        answer = self.answers(BOOKS_CLOSED, NOT_ARCHIVED)

        assert answer["code"] == "books_closed"
        assert "archived" not in answer["reason"]
        assert set(answer) == {"available", "code", "reason"}

    def test_reversing_the_declaration_reverses_the_answer(self) -> None:
        assert self.answers(NOT_ARCHIVED, BOOKS_CLOSED)["code"] == "note_archived"

    def test_a_met_condition_is_walked_past_to_the_first_unmet(self) -> None:
        both = ServiceSpec(
            service=Record(), permissions=OPEN, affordances=[NOT_ARCHIVED, BOOKS_CLOSED]
        )
        row = SimpleNamespace(
            affordance__rename__note_archived=True, affordance__rename__books_closed=False
        )

        assert row_affordance_answers(listing(affordances={"rename": both}), row)["rename"][
            "code"
        ] == ("books_closed")


class TestARowThatIsNotThere:
    def test_none_answers_unavailable_with_no_code_and_no_reason(self) -> None:
        row = SimpleNamespace(
            affordance__rename__note_archived=None, affordance__rename__books_closed=False
        )

        # Not ``False``: no condition's sentence is true of a row that no
        # longer exists, and the walk stops before the unmet second condition.
        assert row_affordance_answers(listing(affordances={"rename": RENAME}), row) == {
            "rename": {"available": False}
        }

    def test_an_unmet_condition_declared_before_it_still_reports_itself(self) -> None:
        both = ServiceSpec(
            service=Record(), permissions=OPEN, affordances=[BOOKS_CLOSED, NOT_ARCHIVED]
        )
        row = SimpleNamespace(
            affordance__rename__books_closed=False, affordance__rename__note_archived=None
        )

        answer = row_affordance_answers(listing(affordances={"rename": both}), row)["rename"]

        assert answer["code"] == "books_closed"


class TestARowThatCarriesNoAnswer:
    @pytest.mark.parametrize("row", [object(), {"id": 1}], ids=["instance", "mapping"])
    def test_it_is_refused_naming_the_missing_answer(self, row: Any) -> None:
        with pytest.raises(ImproperlyConfigured) as caught:
            row_affordance_answers(listing(affordances={"rename": RENAME}), row)

        assert str(caught.value).startswith(
            "The row carries no 'affordance__rename__note_archived' answer."
        )


class TestANameWithNoConditions:
    def test_it_reads_no_flag_so_any_row_is_available_for_it(self) -> None:
        # Nothing is asked of the row, so a row carrying no answers is fine; the
        # refusal above is for a name that does declare a condition.
        spec = listing(affordances={"edit": EDIT})

        assert row_affordance_answers(spec, object()) == {"edit": {"available": True}}


class TestAProjectBuiltFlag:
    @pytest.mark.parametrize("flag", [0, ""], ids=["zero", "empty-string"])
    def test_a_falsy_flag_that_is_not_false_is_unmet(self, flag: Any) -> None:
        # A mapping row built by the project may carry 0 where dispatch writes
        # False; an unmet condition is anything falsy, as the call reads it.
        row = {"affordance__rename__note_archived": flag}
        spec = listing(affordances={"rename": RENAME})

        assert row_affordance_answers(spec, row)["rename"] == ARCHIVED_ANSWER


class TestASpecThatPresentsNoAffordances:
    @pytest.mark.parametrize(
        "spec",
        [
            SelectorSpec(kind=SelectorKind.LIST, selector=notes_of, permissions=OPEN),
            ServiceSpec(service=Record(), permissions=OPEN, affordances=[BOOKS_CLOSED]),
            ServiceSpec(
                service=Record(),
                permissions=OPEN,
                affordances=[BOOKS_CLOSED],
                output_selector_spec=SelectorSpec(kind=SelectorKind.LIST, selector=notes_of),
            ),
        ],
        ids=["selector", "service-own-conditions-only", "output-selector-declaring-none"],
    )
    def test_it_is_refused_rather_than_answering_every_name_absent(self, spec: Any) -> None:
        with pytest.raises(ImproperlyConfigured) as caught:
            row_affordance_answers(spec, object())

        message = str(caught.value)
        assert "presents no affordances" in message
        assert "output_selector_spec" in message
        assert type(spec).__name__ in message

    def test_the_refusal_names_the_spec_s_callable(self) -> None:
        def archive_note() -> None: ...

        spec = ServiceSpec(service=archive_note, permissions=OPEN, affordances=[BOOKS_CLOSED])

        with pytest.raises(ImproperlyConfigured) as caught:
            row_affordance_answers(spec, object())

        assert "archive_note" in str(caught.value)

    def test_an_empty_mapping_is_a_declaration_and_answers_empty(self) -> None:
        # As ``present`` treats it: it adds an empty ``affordances`` object.
        assert row_affordance_answers(listing(affordances={}), object()) == {}
