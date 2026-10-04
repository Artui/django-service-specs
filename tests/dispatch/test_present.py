from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db import connection
from django.test.utils import CaptureQueriesContext

from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.dispatch_result import DispatchResult
from django_service_specs.dispatch.present import present
from django_service_specs.output.output import Output
from django_service_specs.output.output_field import OutputField
from django_service_specs.output.presenter import Presenter
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.affordance import Affordance
from tests.dispatch.utils import (
    BOOKS_CLOSED,
    BOOKS_OPEN,
    EDIT,
    NOT_ARCHIVED,
    OPEN,
    PK,
    REFUSED_ARCHIVED,
    REFUSED_CLOSED,
    RENAME,
    NoteRows,
    Record,
    Titles,
    make_user,
    note_by_pk,
    notes_of,
)
from tests.dispatch_app.models import Note

LIST = SelectorKind.LIST
RETRIEVE = SelectorKind.RETRIEVE


class Row:
    def __init__(self, title: str) -> None:
        self.title = title


def selector_spec(kind: SelectorKind = RETRIEVE, presenter: Any = None) -> SelectorSpec:
    return SelectorSpec(kind=kind, selector=notes_of, permissions=OPEN, presenter=presenter)


def test_an_instance_goes_through_the_selector_spec_s_presenter() -> None:
    presenter = Titles()

    rendered = present(selector_spec(presenter=presenter), DispatchResult("instance", Row("a")))

    assert rendered == {"title": "a"}


def test_a_list_is_presented_item_by_item() -> None:
    presenter = Titles()
    rows = (Row("a"), Row("b"))

    rendered = present(selector_spec(LIST, presenter), DispatchResult("list", rows))

    assert rendered == [{"title": "a"}, {"title": "b"}]
    assert presenter.seen == list(rows)


def test_an_instance_with_no_presenter_is_returned_as_it_is() -> None:
    row = Row("a")

    assert present(selector_spec(), DispatchResult("instance", row)) is row


@pytest.mark.django_db
def test_a_list_with_no_presenter_is_evaluated_into_a_list() -> None:
    # A queryset handed back lazily would run its query wherever the caller
    # first iterates it, which for ``apresent``'s caller is the event loop.
    note = Note.objects.create(owner=make_user("ada"), title="a")

    rendered = present(selector_spec(LIST), DispatchResult("list", Note.objects.all()))

    assert rendered == [note]
    assert type(rendered) is list


def test_a_none_value_is_not_handed_to_the_presenter() -> None:
    presenter = Titles()

    assert present(selector_spec(presenter=presenter), DispatchResult("instance", None)) is None
    assert presenter.seen == []


def test_a_service_spec_presents_through_its_own_presenter() -> None:
    spec = ServiceSpec(service=Record(), permissions=OPEN, presenter=Titles())

    assert present(spec, DispatchResult("instance", Row("a"))) == {"title": "a"}


def test_a_service_spec_with_none_uses_its_output_selector_s() -> None:
    spec = ServiceSpec(
        service=Record(),
        permissions=OPEN,
        output_selector_spec=SelectorSpec(kind=LIST, selector=notes_of, presenter=Titles()),
    )

    assert present(spec, DispatchResult("list", [Row("a")])) == [{"title": "a"}]


def test_a_service_spec_with_no_presenter_anywhere_returns_its_value() -> None:
    spec = ServiceSpec(service=Record(), permissions=OPEN)

    assert present(spec, DispatchResult("instance", "done")) == "done"


@pytest.mark.parametrize("presenter", [None, Titles()], ids=["no presenter", "presenter"])
def test_not_found_has_nothing_to_present(presenter: Any) -> None:
    with pytest.raises(ValueError) as caught:
        present(selector_spec(presenter=presenter), DispatchResult("not_found"))

    assert str(caught.value) == (
        "A not-found result has nothing to present. Answer it as the transport's own "
        "not-found before presenting."
    )


# --- the answers each presented row carries ---------------------------------------


def listing(selector: Callable[..., Any] = notes_of, **fields: Any) -> SelectorSpec:
    fields.setdefault("presenter", NoteRows())
    fields.setdefault("affordances", {"rename": RENAME, "edit": EDIT})
    return SelectorSpec(kind=LIST, selector=selector, permissions=OPEN, **fields)


def served(spec: ServiceSpec | SelectorSpec, user: Any, **arguments: Any) -> Any:
    """What a transport sends: dispatched, presented, and through a JSON round trip."""
    return json.loads(
        json.dumps(present(spec, dispatch(spec, principal=user, arguments=arguments)))
    )


def vanishing(*affordances: Affordance) -> SelectorSpec:
    """A list whose first row is deleted after the selector returned it."""

    def then_delete(*, user: Any) -> list[Note]:
        rows = list(notes_of(user=user))
        Note.objects.filter(pk=rows[0].pk).delete()
        return rows

    rename = ServiceSpec(service=Record(), permissions=OPEN, affordances=list(affordances))
    return listing(then_delete, affordances={"rename": rename})


class Clashing(Presenter):
    def output(self) -> Output:
        return Output((OutputField("affordances", "string"),))

    def present(self, value: Any) -> Any:
        return {"affordances": "mine"}


class Scalar(Presenter):
    def output(self) -> Output:
        return Output((OutputField("title", "string"),))

    def present(self, value: Any) -> Any:
        return value.title


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
class TestAnswers:
    def test_each_presented_row_carries_its_answers(self, ada: Any, two_notes: Any) -> None:
        live, archived = two_notes

        assert served(listing(), ada) == [
            {
                "id": live.pk,
                "title": "live",
                "affordances": {"rename": {"available": True}, "edit": {"available": True}},
            },
            {
                "id": archived.pk,
                "title": "archived",
                "affordances": {"rename": REFUSED_ARCHIVED, "edit": {"available": True}},
            },
        ]

    def test_the_first_unmet_condition_in_declaration_order_is_the_one_reported(
        self, ada: Any, two_notes: Any
    ) -> None:
        both = ServiceSpec(
            service=Record(), permissions=OPEN, affordances=[BOOKS_CLOSED, NOT_ARCHIVED]
        )

        payload = served(listing(affordances={"rename": both}), ada)

        assert [row["affordances"]["rename"] for row in payload] == [REFUSED_CLOSED] * 2

    def test_a_single_row_presents_as_one_object(self, ada: Any, two_notes: Any) -> None:
        spec = SelectorSpec(
            kind=RETRIEVE,
            selector=note_by_pk,
            permissions=OPEN,
            reads=PK,
            presenter=NoteRows(),
            affordances={"rename": RENAME},
        )

        payload = served(spec, ada, pk=two_notes[1].pk)

        assert payload["affordances"] == {"rename": REFUSED_ARCHIVED}

    def test_nothing_carries_no_answers(self, ada: Any) -> None:
        spec = SelectorSpec(
            kind=RETRIEVE,
            selector=lambda: Note.objects.none(),
            permissions=OPEN,
            allow_none=True,
            presenter=NoteRows(),
            affordances={"rename": RENAME},
        )

        assert served(spec, ada) is None

    def test_a_service_spec_presents_its_output_selector_s_answers_not_its_own(
        self, ada: Any, two_notes: Any
    ) -> None:
        # A service spec's own ``affordances`` are what it is checked against;
        # only its output selector's are about the row it hands back.
        def output(**fields: Any) -> SelectorSpec:
            return SelectorSpec(
                kind=RETRIEVE,
                selector=lambda *, result: Note.objects.filter(pk=result),
                presenter=NoteRows(),
                **fields,
            )

        live = two_notes[0].pk
        checked_only = ServiceSpec(
            service=lambda: live,
            permissions=OPEN,
            affordances=[BOOKS_OPEN],
            output_selector_spec=output(),
        )
        rendering = ServiceSpec(
            service=lambda: live,
            permissions=OPEN,
            output_selector_spec=output(affordances={"rename": RENAME}),
        )

        assert "affordances" not in served(checked_only, ada)
        assert served(rendering, ada)["affordances"] == {"rename": {"available": True}}

    def test_a_service_spec_with_its_own_affordances_and_no_output_selector_is_untouched(
        self, ada: Any
    ) -> None:
        spec = ServiceSpec(service=lambda: {"ok": True}, permissions=OPEN, affordances=[BOOKS_OPEN])

        assert served(spec, ada) == {"ok": True}

    def test_instances_a_selector_returned_present_as_a_queryset_s_do(
        self, ada: Any, two_notes: Any
    ) -> None:
        from_list = listing(lambda *, user: list(notes_of(user=user)))

        assert served(from_list, ada) == served(listing(), ada)

    def test_mapping_rows_present_their_callable_answers(self, ada: Any) -> None:
        callable_only = ServiceSpec(service=Record(), permissions=OPEN, affordances=[BOOKS_OPEN])
        spec = listing(
            lambda: [{"id": 1, "title": "computed"}], affordances={"edit": callable_only}
        )

        assert served(spec, ada) == [
            {"id": 1, "title": "computed", "affordances": {"edit": {"available": True}}}
        ]

    def test_values_rows_carry_their_answers_as_keys(self, ada: Any, two_notes: Any) -> None:
        spec = listing(lambda: Note.objects.values())

        payload = served(spec, ada)

        assert [row["affordances"]["rename"]["available"] for row in payload] == [True, False]

    def test_presenting_the_answers_costs_no_query(self, ada: Any, two_notes: Any) -> None:
        spec = listing()
        rows = list(dispatch(spec, principal=ada, arguments={}).value)

        with CaptureQueriesContext(connection) as ctx:
            present(spec, DispatchResult("list", rows))

        assert ctx.captured_queries == []

    def test_rows_given_as_a_one_shot_iterable_are_walked_once(
        self, ada: Any, two_notes: Any
    ) -> None:
        spec = listing()
        rows = list(dispatch(spec, principal=ada, arguments={}).value)

        payload = present(spec, DispatchResult("list", iter(rows)))

        assert [row["affordances"]["rename"]["available"] for row in payload] == [True, False]

    def test_declaring_nothing_presents_exactly_what_the_presenter_did(
        self, ada: Any, two_notes: Any
    ) -> None:
        presenter = NoteRows()
        rows = list(notes_of(user=ada))

        assert served(listing(affordances=None), ada) == [presenter.present(row) for row in rows]

    @pytest.mark.parametrize(
        "result",
        [
            DispatchResult("list", []),
            DispatchResult("instance", Row("a")),
            DispatchResult("instance", None),
        ],
        ids=["list", "instance", "none"],
    )
    def test_no_presenter_is_refused_rather_than_dropping_the_answers(self, result: Any) -> None:
        # Refused whatever the value, ``None`` included: a spec declaring answers
        # with nothing to present them through is wrong for every call.
        spec = listing(presenter=None)

        with pytest.raises(ImproperlyConfigured) as caught:
            present(spec, result)

        assert str(caught.value) == (
            "affordances are projected into each presented object, and this spec declares "
            "no presenter to present one. Declare a presenter."
        )

    def test_an_output_field_named_affordances_is_refused(self, ada: Any, two_notes: Any) -> None:
        with pytest.raises(ImproperlyConfigured) as caught:
            served(listing(presenter=Clashing()), ada)

        assert str(caught.value) == (
            "The presented object already has an 'affordances' key, which the declared "
            "affordances would overwrite. Rename the output field."
        )

    def test_a_row_the_selector_did_not_answer_is_refused(self, ada: Any, two_notes: Any) -> None:
        with pytest.raises(ImproperlyConfigured) as caught:
            present(listing(), DispatchResult("list", list(notes_of(user=ada))))

        assert str(caught.value) == (
            "The presented row carries no 'affordance__rename__note_archived' answer. "
            "Affordance answers are computed by the selector spec that declares them; a value "
            "that did not come through that selector has none."
        )

    def test_a_non_object_item_is_refused(self, ada: Any, two_notes: Any) -> None:
        with pytest.raises(ImproperlyConfigured) as caught:
            served(listing(presenter=Scalar()), ada)

        assert str(caught.value) == (
            "affordances are projected into each presented object, and this spec's presenter "
            "returned str. Present each row as an object."
        )


@pytest.mark.django_db
class TestARowThatVanished:
    """A row deleted between the selector returning it and its answers being asked."""

    def test_it_is_unavailable_with_no_code_and_no_reason(self, ada: Any, two_notes: Any) -> None:
        # No condition's sentence is true of a row that no longer exists. The
        # row that still exists is answered exactly as before.
        payload = served(vanishing(NOT_ARCHIVED, BOOKS_OPEN), ada)

        assert payload[0]["affordances"] == {"rename": {"available": False}}
        assert payload[1]["affordances"] == {"rename": REFUSED_ARCHIVED}

    def test_it_stops_at_its_first_row_condition(self, ada: Any, two_notes: Any) -> None:
        # An unmet callable declared after the row condition: the walk stops at
        # the missing row, so the later callable's sentence is not reported.
        payload = served(vanishing(NOT_ARCHIVED, BOOKS_CLOSED), ada)

        assert payload[0]["affordances"] == {"rename": {"available": False}}

    def test_it_still_reports_an_unmet_callable_declared_first(
        self, ada: Any, two_notes: Any
    ) -> None:
        # A callable condition is not about the row: declared first and unmet,
        # it is the genuine first refusal, true whether or not the row exists.
        payload = served(vanishing(BOOKS_CLOSED, NOT_ARCHIVED), ada)

        assert [row["affordances"] for row in payload] == [{"rename": REFUSED_CLOSED}] * 2


@pytest.mark.django_db
def test_a_list_selector_returning_a_manager_presents_every_row() -> None:
    # ``Note.objects`` is a selector's shortest spelling of "every row", and a
    # Manager is neither iterable nor sliceable: dispatch takes ``.all()`` of it.
    ada = make_user("ada")
    Note.objects.create(owner=ada, title="One")
    Note.objects.create(owner=ada, title="Two")
    spec = SelectorSpec(
        kind=LIST, selector=lambda: Note.objects, permissions=OPEN, presenter=Titles()
    )

    rendered = present(spec, dispatch(spec, principal=ada, arguments={}))

    assert sorted(row["title"] for row in rendered) == ["One", "Two"]


@pytest.mark.django_db
def test_a_list_selector_returning_a_manager_answers_its_rows_affordances() -> None:
    ada = make_user("ada")
    Note.objects.create(owner=ada, title="One", archived=True)
    spec = SelectorSpec(
        kind=LIST,
        selector=lambda: Note.objects,
        permissions=OPEN,
        presenter=Titles(),
        affordances={"rename": RENAME},
    )

    (row,) = present(spec, dispatch(spec, principal=ada, arguments={}))

    assert row["title"] == "One"
    assert row["affordances"]["rename"]["available"] is False
