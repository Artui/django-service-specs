from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from dataclasses import replace
from types import MappingProxyType
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db import connection
from django.db.models import QuerySet
from django.db.models.manager import BaseManager
from django.test.utils import CaptureQueriesContext
from typing_extensions import TypedDict

from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.dispatch_result import DispatchResult
from django_service_specs.dispatch.paginate_output import paginate_output
from django_service_specs.dispatch.present import present
from django_service_specs.dispatch.present_for_audience import present_for_audience
from django_service_specs.output.output import Output, OutputField
from django_service_specs.output.presentation_context import PresentationContext
from django_service_specs.output.presenter import Presenter
from django_service_specs.selectors.shape_queryset import shape_queryset
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.affordance import Affordance
from django_service_specs.types.selector_kind import SelectorKind
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
    TENANT_SEEDS,
    Contextual,
    NoteRows,
    Record,
    Titles,
    make_user,
    note_by_pk,
    notes_of,
)
from tests.dispatch_app.models import Note
from tests.specs.utils import Foreign

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


class Awaiting(Presenter):
    """A presenter whose plain ``def present`` hands back a coroutine, as a decorated async one does."""

    def __init__(self) -> None:
        self.answers: list[Any] = []

    def output(self) -> Output:
        return Output(())

    def present(self, value: Any) -> Any:
        async def presented() -> dict[str, Any]:
            return {}

        answer = presented()
        self.answers.append(answer)
        return answer


@pytest.mark.parametrize(
    ("kind", "value"), [(LIST, [Row("a")]), (RETRIEVE, Row("a"))], ids=["list", "instance"]
)
def test_a_presenter_answering_with_a_coroutine_is_refused(kind: SelectorKind, value: Any) -> None:
    presenter = Awaiting()
    result = DispatchResult("list" if kind is LIST else "instance", value)

    with pytest.raises(ImproperlyConfigured) as caught:
        present(selector_spec(kind, presenter), result)

    assert str(caught.value).startswith(
        "Awaiting.present answered with an awaitable (coroutine). A presenter is sync-only"
    )
    assert [inspect.getcoroutinestate(answer) for answer in presenter.answers] == [
        inspect.CORO_CLOSED
    ]


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
def test_a_list_selector_returning_a_manager_built_on_base_manager_presents_every_row() -> None:
    # ``BaseManager.from_queryset`` builds a manager that is not a ``Manager``,
    # and ``is_queryset`` counts it like one, so dispatch takes its ``.all()``
    # as well.
    ada = make_user("ada")
    Note.objects.create(owner=ada, title="One")
    Note.objects.create(owner=ada, title="Two")
    manager: Any = BaseManager.from_queryset(QuerySet)()
    manager.model = Note
    spec = SelectorSpec(kind=LIST, selector=lambda: manager, permissions=OPEN, presenter=Titles())

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


@pytest.mark.django_db
def test_a_target_lookup_s_answers_are_never_presented() -> None:
    # Answered, as djangorestframework-services' dispatch answers them, and read
    # by nothing: a service spec presents only its output selector's answers.
    ada = make_user("ada")
    note = Note.objects.create(owner=ada, title="Draft")
    spec = ServiceSpec(
        service=lambda *, instance: instance,
        permissions=OPEN,
        instance_selector_spec=SelectorSpec(
            kind=RETRIEVE, selector=note_by_pk, reads=PK, affordances={"rename": RENAME}
        ),
        presenter=Titles(),
    )

    result = dispatch(spec, principal=ada, arguments={"pk": note.pk})

    assert result.value.affordance__rename__note_archived is True
    assert present(spec, result) == {"title": "Draft"}


@pytest.mark.django_db
def test_rows_shaped_outside_dispatch_carry_no_answers_and_are_refused() -> None:
    ada = make_user("ada")
    Note.objects.create(owner=ada, title="Draft")
    spec = SelectorSpec(
        kind=LIST,
        selector=notes_of,
        permissions=OPEN,
        presenter=Titles(),
        affordances={"rename": RENAME},
    )
    rows = shape_queryset(Note.objects.all(), spec, {"user": ada}, source_label="a transport")

    with pytest.raises(ImproperlyConfigured, match="no 'affordance__rename__note_archived' answer"):
        present(spec, DispatchResult("list", rows))


@pytest.mark.django_db
class TestTheCallsContext:
    """A presenter reads the call it presents for: its principal, its target, its seeds."""

    def test_a_selector_spec_s_rows_are_each_presented_with_the_call_s_context(self) -> None:
        ada = make_user("ada")
        Note.objects.create(owner=ada, title="a")
        Note.objects.create(owner=ada, title="b")
        presenter = Contextual()
        spec = selector_spec(LIST, presenter=presenter)

        result = dispatch(spec, principal=ada, arguments={}, pool_seeds=TENANT_SEEDS)

        assert present(spec, result) == [{"title": "a"}, {"title": "b"}]
        first, second = presenter.contexts
        assert first is second
        assert (first.principal, first.target) == (ada, None)
        assert first.ambient["tenant"] == "tenant-of-ada"
        assert first.ambient["user"] is ada
        # The seeds alone: never an argument, a provider's key or the rows.
        assert set(first.ambient) == {"user", "progress", "tenant"}
        with pytest.raises(TypeError):
            first.ambient["tenant"] = "another"  # ty: ignore[invalid-assignment]

    def test_a_retrieve_s_context_holds_the_seeds_and_never_its_reads_provider_or_overlay(
        self,
    ) -> None:
        """A retrieve's pool holds a read, a ``kwargs`` provider's key and an
        ``extra_kwargs`` key beside the seeds; the context is handed the seeds
        alone, since the rest are the call's arguments, not its surroundings."""
        ada = make_user("ada")
        note = Note.objects.create(owner=ada, title="a")
        presenter = Contextual()

        class _Server(TypedDict):
            scope: str

        def server() -> _Server:
            return {"scope": "server"}

        def by_pk(*, pk: int, scope: str, audit: str) -> QuerySet[Note]:
            return Note.objects.filter(pk=pk)

        spec = SelectorSpec(
            kind=RETRIEVE,
            selector=by_pk,
            reads=PK,
            kwargs=server,
            permissions=OPEN,
            presenter=presenter,
        )
        result = dispatch(
            spec,
            principal=ada,
            arguments={"pk": note.pk},
            extra_kwargs={"audit": "overlay"},
            pool_seeds=TENANT_SEEDS,
        )

        assert present(spec, result) == {"title": "a"}
        [context] = presenter.contexts
        assert set(context.ambient) == {"user", "progress", "tenant"}

    def test_a_service_spec_s_context_carries_its_resolved_target(self) -> None:
        ada = make_user("ada")
        note = Note.objects.create(owner=ada, title="a")
        presenter = Contextual()
        spec = ServiceSpec(
            service=lambda *, instance: instance,
            permissions=OPEN,
            instance_selector_spec=SelectorSpec(kind=RETRIEVE, selector=note_by_pk, reads=PK),
            presenter=presenter,
        )

        result = dispatch(spec, principal=ada, arguments={"pk": note.pk}, pool_seeds=TENANT_SEEDS)

        assert present(spec, result) == {"title": "a"}
        [context] = presenter.contexts
        assert (context.principal, context.target) == (ada, note)
        assert context.ambient["tenant"] == "tenant-of-ada"

    def test_a_page_presented_for_an_audience_keeps_the_call_s_context(self) -> None:
        ada = make_user("ada")
        Note.objects.create(owner=ada, title="a")
        presenter = Contextual()
        spec = selector_spec(LIST, presenter=presenter)
        result = dispatch(spec, principal=ada, arguments={})

        page = paginate_output(result.value, limit=1)
        present_for_audience(spec, replace(result, value=page.items))

        [context] = presenter.contexts
        assert context.principal == ada

    def test_a_result_dispatch_did_not_build_is_presented_with_no_context(self) -> None:
        presenter = Contextual()
        present(selector_spec(presenter=presenter), DispatchResult("instance", Row("a")))
        assert presenter.contexts == [None]

    def test_the_context_takes_no_part_in_a_result_s_equality(self) -> None:
        ada = make_user("ada")
        note = Note.objects.create(owner=ada, title="a")
        spec = ServiceSpec(
            service=lambda *, instance: instance,
            permissions=OPEN,
            instance_selector_spec=SelectorSpec(kind=RETRIEVE, selector=note_by_pk, reads=PK),
        )
        result = dispatch(spec, principal=ada, arguments={"pk": note.pk})
        assert result == DispatchResult("instance", note, note, note, {})


def test_a_foreign_declaration_is_presented_through_its_compiled_spec() -> None:
    source = Foreign(selector_spec(presenter=Titles()))

    assert present(source, DispatchResult("instance", Row("a"))) == {"title": "a"}


class _ReadsTheCall(Presenter):
    """Renders each row with the shapes it is handed, and counts rows in the call's context."""

    def __init__(self) -> None:
        self.contexts: list[Any] = []

    def output(self) -> Output:
        return Output((OutputField("title", "string"),))

    def present(self, value: Any) -> Any:
        return {"title": value.title}

    def presented(self, value: Any, context: Any) -> Any:
        self.contexts.append(context)
        seen = context.call_context.setdefault("rows", 0) + 1
        context.call_context["rows"] = seen
        fields = context.shapes.get("fields", ["title"])
        return {name: getattr(value, name) for name in fields} | {"n": seen}


def test_every_row_of_one_result_shares_its_call_context_and_its_shapes() -> None:
    """One context per result, never a copy per row, so what one row's
    presenting writes to the call's context the next one reads."""
    call_context: dict[str, Any] = {}
    context = PresentationContext(
        "ada", call_context=call_context, shapes=MappingProxyType({"fields": ["title"]})
    )
    presenter = _ReadsTheCall()
    rows = (Row("a"), Row("b"))

    rendered = present(
        selector_spec(LIST, presenter), DispatchResult("list", rows, context=context)
    )

    assert rendered == [{"title": "a", "n": 1}, {"title": "b", "n": 2}]
    assert all(seen is context for seen in presenter.contexts)
    assert call_context == {"rows": 2}


class Batching(NoteRows):
    """Presents a list in one call: one lookup over its rows, then each row with its share.

    The lookup is each title's rank among the titles it was handed, which no
    single row can answer, so a presenter asked row by row could not give it.
    ``answer`` replaces what is handed back, for the refusals.
    """

    def __init__(self, answer: Callable[[list[Any]], Any] | None = None) -> None:
        self.calls: list[tuple[Any, PresentationContext | None]] = []
        self.answer = answer

    def presented_rows(self, values: Any, context: PresentationContext | None) -> Any:
        self.calls.append((values, context))
        rows = [self.present(value) for value in values]
        if self.answer is not None:
            return self.answer(rows)
        titles = sorted(row["title"] for row in rows)
        return [{**row, "rank": titles.index(row["title"])} for row in rows]


MAPPING_ROWS = ({"id": 1, "title": "a"}, {"id": 2, "title": "b"})


@pytest.mark.django_db
class TestPresentedRows:
    def test_a_page_is_presented_in_one_call_and_each_row_keeps_its_answers(
        self, ada: Any, two_notes: Any
    ) -> None:
        live, archived = two_notes
        Note.objects.create(owner=ada, title="past the page")
        presenter = Batching()
        spec = listing(presenter=presenter)
        result = dispatch(spec, principal=ada, arguments={})

        page = paginate_output(result.value, limit=2)
        payload = present(spec, replace(result, value=page.items))

        [(rows, context)] = presenter.calls
        assert list(rows) == [live, archived]
        assert context is result.context
        # The ranks are the batch's answer and the affordances each row's own:
        # "archived" ranks first among the page's titles and is the row that
        # may not be renamed, so a payload walked against the wrong rows fails.
        assert json.loads(json.dumps(payload)) == [
            {
                "id": live.pk,
                "title": "live",
                "rank": 1,
                "affordances": {"rename": {"available": True}, "edit": {"available": True}},
            },
            {
                "id": archived.pk,
                "title": "archived",
                "rank": 0,
                "affordances": {"rename": REFUSED_ARCHIVED, "edit": {"available": True}},
            },
        ]

    def test_the_rows_are_handed_over_as_a_tuple(self) -> None:
        """A tuple, so an override cannot reorder the rows the answers are walked from."""
        presenter = Batching()

        present(selector_spec(LIST, presenter), DispatchResult("list", iter(MAPPING_ROWS)))

        [(rows, _)] = presenter.calls
        assert rows == MAPPING_ROWS

    def test_a_page_presented_for_an_audience_is_presented_in_one_call(self, ada: Any) -> None:
        for title in ("a", "b", "c"):
            Note.objects.create(owner=ada, title=title)
        presenter = Batching()
        spec = selector_spec(LIST, presenter)
        result = dispatch(spec, principal=ada, arguments={})

        page = paginate_output(result.value, limit=2)
        payload = present_for_audience(spec, replace(result, value=page.items))

        [(rows, _)] = presenter.calls
        assert [row.title for row in rows] == ["a", "b"]
        assert [row["rank"] for row in payload] == [0, 1]

    @pytest.mark.parametrize(
        ("answer", "count"),
        [(lambda rows: rows[:1], 1), (lambda rows: [*rows, rows[0]], 3)],
        ids=["short", "long"],
    )
    def test_an_answer_with_a_row_too_few_or_too_many_is_refused(
        self, answer: Callable[[list[Any]], Any], count: int
    ) -> None:
        """No affordances declared, so nothing downstream would notice the mismatch."""
        spec = selector_spec(LIST, Batching(answer))

        with pytest.raises(ImproperlyConfigured) as caught:
            present(spec, DispatchResult("list", MAPPING_ROWS))

        assert str(caught.value).startswith(
            f"Batching.presented_rows answered with a list of {count} for 2 rows."
        )

    def test_a_mismatch_is_refused_before_the_answers_are_walked_against_it(
        self, ada: Any, two_notes: Any
    ) -> None:
        spec = listing(presenter=Batching(lambda rows: rows[:1]))
        result = dispatch(spec, principal=ada, arguments={})

        with pytest.raises(ImproperlyConfigured) as caught:
            present(spec, result)

        # The refusal is this one, not with_affordances' strict zip, which
        # would answer a mismatch too, as a ValueError.
        assert str(caught.value).startswith(
            "Batching.presented_rows answered with a list of 1 for 2 rows."
        )
        assert "zip()" not in str(caught.value)

    @pytest.mark.parametrize(
        ("answer", "kind"),
        [
            (tuple, "tuple"),
            (lambda rows: (row for row in rows), "generator"),
            (lambda rows: dict(enumerate(rows)), "dict"),
        ],
        ids=["tuple", "generator", "dict"],
    )
    def test_an_answer_that_is_not_a_list_is_refused(
        self, answer: Callable[[list[Any]], Any], kind: str
    ) -> None:
        spec = selector_spec(LIST, Batching(answer))

        with pytest.raises(ImproperlyConfigured) as caught:
            present(spec, DispatchResult("list", MAPPING_ROWS))

        assert str(caught.value).startswith(
            f"Batching.presented_rows answered with {kind!r} where a list is expected."
        )

    def test_an_answer_still_to_be_awaited_is_refused(self) -> None:
        answers: list[Any] = []

        def awaiting(rows: list[Any]) -> Any:
            async def presented() -> list[Any]:
                return rows

            answers.append(presented())
            return answers[-1]

        spec = selector_spec(LIST, Batching(awaiting))

        with pytest.raises(ImproperlyConfigured) as caught:
            present(spec, DispatchResult("list", MAPPING_ROWS))

        assert str(caught.value).startswith(
            "Batching.presented_rows answered with an awaitable (coroutine). A presenter is"
        )
        assert [inspect.getcoroutinestate(answer) for answer in answers] == [inspect.CORO_CLOSED]

    def test_an_instance_is_still_presented_alone(self) -> None:
        presenter = Batching()

        rendered = present(
            selector_spec(presenter=presenter), DispatchResult("instance", MAPPING_ROWS[0])
        )

        assert rendered == {"id": 1, "title": "a"}
        assert presenter.calls == []
