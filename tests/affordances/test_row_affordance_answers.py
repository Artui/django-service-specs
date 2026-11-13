from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.utils import translation

from django_service_specs.affordances.row_affordance_answers import row_affordance_answers
from django_service_specs.affordances.utils import rendered_affordances
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.present import present
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.affordance import Affordance
from django_service_specs.types.selector_kind import SelectorKind
from tests.affordances.utils import Card, empty_reason, language_reason
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
    # What dispatch hands a transport: the rows carrying the answers it wrote.
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
        # Its own affordances are what it is checked against and are never presented.
        spec = ServiceSpec(
            service=lambda: [live.pk, archived.pk],
            permissions=OPEN,
            affordances=[BOOKS_OPEN],
            output_selector_spec=output.derive(permissions=None),
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

        # Not ``False``: no condition's sentence is true of a row that no longer exists.
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
    @pytest.mark.parametrize(
        "row", [object(), {"id": 1}, None], ids=["instance", "mapping", "none-with-no-row-object"]
    )
    def test_it_is_refused_naming_the_missing_answer(self, row: Any) -> None:
        with pytest.raises(ImproperlyConfigured) as caught:
            row_affordance_answers(listing(affordances={"rename": RENAME}), row)

        assert str(caught.value).startswith(
            "The row carries no 'affordance__rename__note_archived' answer."
        )


class TestANameWithNoConditions:
    def test_it_reads_no_flag_so_any_row_is_available_for_it(self) -> None:
        # Nothing is asked of the row, so a row carrying no answers is fine.
        spec = listing(affordances={"edit": EDIT})

        assert row_affordance_answers(spec, object()) == {"edit": {"available": True}}


class TestAProjectBuiltFlag:
    @pytest.mark.parametrize("flag", [0, ""], ids=["zero", "empty-string"])
    def test_a_falsy_flag_that_is_not_false_is_unmet(self, flag: Any) -> None:
        # A mapping row built by the project may carry 0 where dispatch writes False.
        row = {"affordance__rename__note_archived": flag}
        spec = listing(affordances={"rename": RENAME})

        assert row_affordance_answers(spec, row)["rename"] == ARCHIVED_ANSWER


class TestASpecThatPresentsNoAffordances:
    @pytest.mark.parametrize(
        "spec",
        [
            SelectorSpec(kind=SelectorKind.LIST, selector=notes_of, permissions=OPEN),
            ServiceSpec(
                service=Record(),
                permissions=OPEN,
                affordances=[BOOKS_CLOSED],
                output_selector_spec=SelectorSpec(kind=SelectorKind.LIST, selector=notes_of),
            ),
            # Its own conditions are checked against and never presented.
            ServiceSpec(service=Record(), permissions=OPEN, affordances=[BOOKS_CLOSED]),
        ],
        ids=["selector", "output-selector-declaring-none", "no-output-selector"],
    )
    def test_a_spec_presenting_none_answers_empty(self, spec: Any) -> None:
        assert rendered_affordances(spec) is None
        assert row_affordance_answers(spec, object()) == {}

    def test_an_empty_mapping_answers_empty_too(self) -> None:
        spec = listing(affordances={})

        assert rendered_affordances(spec) == {}
        assert row_affordance_answers(spec, object()) == {}


class TestALazyReason:
    def spec_with(self, reason: Any) -> SelectorSpec:
        rename = ServiceSpec(
            service=print, affordances=[Affordance(code="c", reason=reason, when=lambda: False)]
        )
        return listing(affordances={"rename": rename})

    def test_the_answer_carries_it_as_text_in_the_language_active_at_the_call(self) -> None:
        with translation.override("fr"):
            answers = row_affordance_answers(
                self.spec_with(language_reason()), {"affordance__rename__c": False}
            )
        reason = answers["rename"]["reason"]
        assert (type(reason), reason) == (str, "fr")

    def test_one_that_resolves_empty_is_refused(self) -> None:
        spec = self.spec_with(empty_reason())
        with pytest.raises(ImproperlyConfigured, match="^Affordance.reason must be a non-empty"):
            row_affordance_answers(spec, {"affordance__rename__c": False})


@pytest.mark.django_db
class TestARowObject:
    def test_a_wrapper_row_answers_as_its_unwrapped_instance(
        self, ada: Any, two_notes: tuple[Note, Note]
    ) -> None:
        cards = [Card(note) for note in two_notes]
        spec = listing(lambda: cards, row_object="obj")

        rows = rows_of(spec, ada)

        assert [row_affordance_answers(spec, row) for row in rows] == [
            row_affordance_answers(listing(), note) for note in two_notes
        ]
        assert row_affordance_answers(spec, rows[1])["rename"] == ARCHIVED_ANSWER

    def test_present_puts_the_same_answers_on_each_presented_wrapper(
        self, ada: Any, two_notes: tuple[Note, Note]
    ) -> None:
        spec = listing(lambda: [Card(note) for note in two_notes], row_object="obj")
        spec = spec.derive(presenter=NoteRows())
        result = dispatch(spec, principal=ada, arguments={})

        presented = present(spec, result)

        assert [item["affordances"] for item in presented] == [
            row_affordance_answers(spec, row) for row in result.value
        ]
        assert presented[1]["title"] == "archived"

    def test_a_service_spec_reads_its_output_selector_s_row_object(
        self, ada: Any, two_notes: tuple[Note, Note]
    ) -> None:
        card = Card(two_notes[1])
        output = SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=lambda: card,
            affordances={"rename": RENAME},
            row_object="obj",
        )
        spec = ServiceSpec(service=print, permissions=OPEN, output_selector_spec=output)
        assert dispatch(output.derive(permissions=OPEN), principal=ada, arguments={}).value is card

        assert row_affordance_answers(spec, card)["rename"] == ARCHIVED_ANSWER

    def test_a_row_with_no_object_answers_unavailable_where_a_condition_is_declared(
        self, ada: Any
    ) -> None:
        spec = listing(lambda: [Card(None)], row_object="obj")

        (row,) = rows_of(spec, ada)

        assert row_affordance_answers(spec, row) == {
            "rename": {"available": False},
            "edit": {"available": True},
        }
