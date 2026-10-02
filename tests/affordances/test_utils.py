"""The helpers every reader of an affordance answers through."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any
from unittest import mock

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db import connection
from django.db.models import BooleanField, Count, Q, QuerySet, Value
from django.test.utils import CaptureQueriesContext

from django_service_specs.affordances.enforce_affordances import enforce_affordances
from django_service_specs.affordances.utils import (
    affordance_expression,
    ambient_pool,
    answer_operation_condition,
)
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.parameters.parameter import Parameter
from django_service_specs.parameters.parameters import Parameters
from django_service_specs.pool.base_pool import base_pool
from django_service_specs.pool.null_progress import null_progress
from django_service_specs.pool.reserved_pool_seeds import RESERVED_POOL_SEEDS
from django_service_specs.services.action_unavailable import ActionUnavailable
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.affordance import Affordance
from tests.dispatch.utils import (
    BOOKS_CLOSED,
    EDIT,
    OPEN,
    PK,
    RENAME,
    TENANT_SEEDS,
    make_user,
    note_by_pk,
    notes_of,
)
from tests.dispatch_app.models import LiveNote, Note
from tests.relations_app.models import Post


def call_pool(user: Any, **entries: Any) -> dict[str, Any]:
    """A pool shaped as dispatch shapes a service's: the seeds, then the call's own entries."""
    pool = base_pool(user=user, seeds=TENANT_SEEDS)
    pool.update(entries)
    return pool


class TestAmbientPool:
    # The filter is ``key in reserved and key not in PER_CALL_POOL_NAMES``. The
    # first test holds the first half and the second test the second: delete
    # either half and exactly that test fails.
    def test_a_spread_argument_is_not_ambient(self) -> None:
        pool = {"user": "ada", "title": "Final", "tenant": "t"}
        assert ambient_pool(pool, reserved=TENANT_SEEDS.reserved) == {"user": "ada", "tenant": "t"}

    def test_a_per_call_name_is_not_ambient_although_it_is_reserved(self) -> None:
        pool = {
            "user": "ada",
            "progress": "p",
            "data": {"title": "Final"},
            "instance": "row",
            "collection": "rows",
            "result": "returned",
            "queryset": "shaped",
        }
        assert ambient_pool(pool, reserved=RESERVED_POOL_SEEDS) == {"user": "ada", "progress": "p"}

    def test_a_drf_adapters_serializer_is_never_ambient(self) -> None:
        # djangorestframework-services hands these functions a pool holding the
        # bound input serializer, with ``serializer`` in its reserved set. It is
        # the call's input, so a condition never sees it there either.
        pool = {"user": "ada", "request": "r", "serializer": "bound"}
        reserved = RESERVED_POOL_SEEDS | {"request", "serializer"}
        assert ambient_pool(pool, reserved=reserved) == {"user": "ada", "request": "r"}

    def test_a_registered_seed_is_ambient_only_when_reserved_says_so(self) -> None:
        pool = {"user": "ada", "tenant": "t"}
        assert ambient_pool(pool, reserved=RESERVED_POOL_SEEDS) == {"user": "ada"}


@pytest.mark.django_db
class TestAnswerOperationCondition:
    def test_a_catch_all_condition_sees_the_seeds_and_nothing_per_call(self) -> None:
        ada = make_user("ada")
        seen: dict[str, Any] = {}

        def when(**kwargs: Any) -> bool:
            seen.update(kwargs)
            return True

        pool = call_pool(ada, title="Final", data={"title": "Final"}, instance="row")
        assert answer_operation_condition(when, pool, reserved=TENANT_SEEDS.reserved) is True
        assert seen == {"user": ada, "progress": null_progress, "tenant": "tenant-of-ada"}

    def test_a_condition_names_what_it_wants_from_the_seeds(self) -> None:
        ada = make_user("ada")
        pool = call_pool(ada)
        assert answer_operation_condition(
            lambda *, tenant: tenant == "tenant-of-ada", pool, reserved=TENANT_SEEDS.reserved
        )

    @pytest.mark.parametrize(("returned", "met"), [(None, False), (0, False), ("yes", True)])
    def test_the_answer_is_read_for_truth(self, returned: Any, met: bool) -> None:
        assert answer_operation_condition(lambda: returned, {}, reserved=RESERVED_POOL_SEEDS) is met


@pytest.mark.django_db
class TestAffordanceExpression:
    def test_it_answers_each_row_as_filter_would(self) -> None:
        ada = make_user("ada")
        live = Note.objects.create(owner=ada, title="Live")
        gone = Note.objects.create(owner=ada, title="Gone", archived=True)
        answers = dict(
            Note.objects.annotate(
                available=affordance_expression(Note, Q(archived=False))
            ).values_list("pk", "available")
        )
        assert answers == {live.pk: True, gone.pk: False}

    def test_a_multi_valued_relation_does_not_duplicate_the_rows(self) -> None:
        # Inline, a condition across ``owner__notes`` would join every sibling
        # note into the outer query; inside the subquery it joins nothing.
        ada = make_user("ada")
        for title in ("a", "b", "c"):
            Note.objects.create(owner=ada, title=title)
        rows = Note.objects.annotate(
            available=affordance_expression(Note, Q(owner__notes__title="b"))
        )
        assert sorted(rows.values_list("title", "available")) == [
            ("a", True),
            ("b", True),
            ("c", True),
        ]

    def test_a_null_is_not_true(self) -> None:
        ada = make_user("ada")
        note = Note.objects.create(owner=ada, title="Draft")
        unknown = Value(None, output_field=BooleanField())
        row = Note.objects.annotate(available=affordance_expression(Note, unknown)).get()
        assert row.pk == note.pk
        assert row.available is False


# --- the answers a selector spec's rows carry -------------------------------------

CODES = {"rename": ["note_archived", "books_closed"]}


def listing(selector: Callable[..., Any] = notes_of, **fields: Any) -> SelectorSpec:
    fields.setdefault("affordances", {"rename": RENAME, "edit": EDIT})
    return SelectorSpec(kind=SelectorKind.LIST, selector=selector, permissions=OPEN, **fields)


def rows_of(spec: SelectorSpec, user: Any, **kwargs: Any) -> Any:
    return dispatch(spec, principal=user, arguments=kwargs.pop("arguments", {}), **kwargs).value


def first_unmet(row: Any) -> str | None:
    """The code the row's answers say a rename would be refused with, if any."""
    for code in CODES["rename"]:
        if not getattr(row, f"affordance__rename__{code}"):
            return code
    return None


def refusal(user: Any, row: Note) -> str | None:
    """The code ``enforce_affordances`` refuses a rename of ``row`` with, if any."""
    try:
        enforce_affordances(RENAME, base_pool(user=user), instance=row)
    except ActionUnavailable as exc:
        return exc.code
    return None


def run(spec: SelectorSpec, user: Any) -> tuple[list[Any], int, list[list[str]]]:
    """The rows, how many queries they cost, and the names of every ``annotate`` call."""
    real = QuerySet.annotate
    calls: list[list[str]] = []

    def spy(self: QuerySet[Any], *args: Any, **kwargs: Any) -> QuerySet[Any]:
        calls.append(sorted(kwargs))
        return real(self, *args, **kwargs)

    with mock.patch.object(QuerySet, "annotate", spy), CaptureQueriesContext(connection) as ctx:
        rows = list(rows_of(spec, user))
    return rows, len(ctx.captured_queries), calls


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
class TestRowsOfAQuerySet:
    def test_each_row_carries_one_boolean_per_condition(self, ada: Any, two_notes: Any) -> None:
        rows = rows_of(listing(), ada)

        assert [
            (row.affordance__rename__note_archived, row.affordance__rename__books_closed)
            for row in rows
        ] == [(True, True), (False, True)]

    def test_the_list_and_the_call_agree_about_every_row(self, ada: Any, two_notes: Any) -> None:
        rows = list(rows_of(listing(), ada))

        assert [first_unmet(row) for row in rows] == [refusal(ada, row) for row in rows]
        # And the answers differ, so agreement is not vacuous.
        assert [first_unmet(row) for row in rows] == [None, "note_archived"]

    def test_every_answer_rides_in_the_one_list_query_and_the_one_annotate_call(
        self, ada: Any, two_notes: Any
    ) -> None:
        rows, queries, calls = run(listing(annotations={"siblings": Count("owner__notes")}), ada)

        assert queries == 1
        assert calls == [
            sorted(
                [
                    "siblings",
                    "affordance__rename__note_archived",
                    "affordance__rename__books_closed",
                ]
            )
        ]
        # The declared aggregate is not inflated by a condition's relations.
        assert [row.siblings for row in rows] == [2, 2]

    def test_extend_queryset_sees_the_answers(self, ada: Any, two_notes: Any) -> None:
        # In the one ``annotate`` call the declared annotations make, so a
        # project's ``extend_queryset`` may filter on an answer.
        spec = listing(
            extend_queryset=lambda *, queryset: queryset.filter(
                affordance__rename__note_archived=True
            )
        )

        assert [row.title for row in rows_of(spec, ada)] == ["live"]

    def test_declaring_nothing_adds_nothing_to_the_query(self, ada: Any, two_notes: Any) -> None:
        rows, queries, calls = run(listing(affordances=None), ada)

        assert (queries, calls) == (1, [])
        assert not [name for name in vars(rows[0]) if name.startswith("affordance__")]

    def test_a_spec_with_no_affordances_of_its_own_adds_no_annotation(
        self, ada: Any, two_notes: Any
    ) -> None:
        _rows, queries, calls = run(listing(affordances={"edit": EDIT}), ada)

        assert (queries, calls) == (1, [])

    def test_a_callable_condition_is_answered_once_per_call_from_the_seeds_alone(
        self, ada: Any, two_notes: Any
    ) -> None:
        seen: list[dict[str, Any]] = []

        def books_open(**pool: Any) -> bool:
            seen.append(pool)
            return False

        closed = ServiceSpec(
            service=lambda: None,
            permissions=OPEN,
            affordances=[Affordance(code="books_closed", reason="Closed.", when=books_open)],
        )
        spec = listing(
            affordances={"rename": closed},
            reads=Parameters.of(Parameter("search", "string")),
        )

        # The selector reads an argument, so it sits in the selector's pool beside
        # the seeds, and must not reach the condition.
        rows = rows_of(spec, ada, arguments={"search": "x"})

        assert len(seen) == 1
        assert set(seen[0]) == {"user", "progress"}
        assert seen[0]["user"] == ada
        assert [row.affordance__rename__books_closed for row in rows] == [False, False]

    def test_a_callable_that_returns_nothing_is_unavailable(self, ada: Any, two_notes: Any) -> None:
        silent = ServiceSpec(
            service=lambda: None,
            permissions=OPEN,
            affordances=[Affordance(code="c", reason="r", when=lambda: None)],
        )

        rows = rows_of(listing(affordances={"x": silent}), ada)

        assert {row.affordance__x__c for row in rows} == {False}

    def test_a_registered_seed_reaches_a_condition_asked_for_every_row(
        self, ada: Any, two_notes: Any
    ) -> None:
        mine = ServiceSpec(
            service=lambda: None,
            permissions=OPEN,
            affordances=[
                Affordance(code="c", reason="r", when=lambda *, tenant: tenant == "tenant-of-ada")
            ],
        )

        rows = rows_of(listing(affordances={"x": mine}), ada, pool_seeds=TENANT_SEEDS)

        assert {row.affordance__x__c for row in rows} == {True}

    def test_a_retrieve_selector_carries_the_answer_on_its_one_row(
        self, ada: Any, two_notes: Any
    ) -> None:
        spec = SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=note_by_pk,
            permissions=OPEN,
            reads=PK,
            affordances={"rename": RENAME},
        )

        row = rows_of(spec, ada, arguments={"pk": two_notes[1].pk})

        assert first_unmet(row) == "note_archived"

    def test_a_service_spec_s_output_selector_carries_the_answer_on_the_written_row(
        self, ada: Any, two_notes: Any
    ) -> None:
        def archive(*, instance: Note) -> Note:
            instance.archived = True
            instance.save(update_fields=["archived"])
            return instance

        spec = ServiceSpec(
            service=archive,
            permissions=OPEN,
            instance_selector_spec=SelectorSpec(
                kind=SelectorKind.RETRIEVE, selector=note_by_pk, reads=PK
            ),
            output_selector_spec=SelectorSpec(
                kind=SelectorKind.RETRIEVE,
                selector=lambda *, result: Note.objects.filter(pk=result.pk),
                affordances={"rename": RENAME},
            ),
        )

        row = dispatch(spec, principal=ada, arguments={"pk": two_notes[0].pk}).value

        assert first_unmet(row) == "note_archived"


@pytest.mark.django_db
class TestRowsASelectorReturnsDirectly:
    """A selector returning instances or mappings rather than a ``QuerySet``."""

    def queries(self, spec: SelectorSpec, user: Any) -> tuple[list[Any], int]:
        with CaptureQueriesContext(connection) as ctx:
            rows = list(rows_of(spec, user))
        return rows, len(ctx.captured_queries)

    def test_declaring_nothing_leaves_a_returned_list_as_it_was(self, ada: Any) -> None:
        # Not walked, copied or refused: rows that are neither instances nor
        # mappings are refused only where there are answers to carry.
        rows = [object(), object()]

        assert rows_of(listing(lambda: rows, affordances=None), ada) is rows

    def test_a_list_agrees_with_the_queryset_about_every_row(
        self, ada: Any, two_notes: Any
    ) -> None:
        from_list = rows_of(listing(lambda *, user: list(notes_of(user=user))), ada)
        from_queryset = rows_of(listing(), ada)

        assert [first_unmet(row) for row in from_list] == [None, "note_archived"]
        assert [first_unmet(row) for row in from_list] == [
            first_unmet(row) for row in from_queryset
        ]

    def test_a_list_of_instances_costs_one_query_whatever_the_row_count(self, ada: Any) -> None:
        for title in ("a", "b", "c", "d"):
            Note.objects.create(owner=ada, title=title)
        selector = lambda *, user: list(notes_of(user=user))  # noqa: E731

        _rows, baseline = self.queries(listing(selector, affordances=None), ada)
        rows, queries = self.queries(listing(selector), ada)

        assert queries == baseline + 1
        assert {first_unmet(row) for row in rows} == {None}

    def test_an_empty_list_spends_no_query(self, ada: Any) -> None:
        rows, queries = self.queries(listing(lambda: []), ada)

        assert (rows, queries) == ([], 0)

    def test_only_callable_conditions_spend_no_row_query(self, ada: Any, two_notes: Any) -> None:
        selector = lambda *, user: list(notes_of(user=user))  # noqa: E731
        callable_only = ServiceSpec(
            service=lambda: None, permissions=OPEN, affordances=[BOOKS_CLOSED]
        )

        _rows, baseline = self.queries(listing(selector, affordances=None), ada)
        rows, queries = self.queries(listing(selector, affordances={"a": callable_only}), ada)

        assert queries == baseline
        assert {row.affordance__a__books_closed for row in rows} == {False}

    def test_one_query_per_model_class_each_answered_against_its_own_table(self, ada: Any) -> None:
        # Pks collide across the two tables, so answering one class's rows
        # against the other's table would read the wrong titles.
        note = Note.objects.create(owner=ada, title="draft")
        other_note = Note.objects.create(owner=ada, title="not a draft")
        post = Post.objects.create(title="not a draft")
        other_post = Post.objects.create(title="draft")
        assert {note.pk, other_note.pk} == {post.pk, other_post.pk}
        titled = ServiceSpec(
            service=lambda: None,
            permissions=OPEN,
            affordances=[Affordance(code="not_draft", reason="r", when=Q(title="draft"))],
        )

        def mixed() -> list[Any]:
            return [
                Note.objects.get(pk=note.pk),
                Note.objects.get(pk=other_note.pk),
                Post.objects.get(pk=post.pk),
                Post.objects.get(pk=other_post.pk),
            ]

        _rows, baseline = self.queries(listing(mixed, affordances=None), ada)
        rows, queries = self.queries(listing(mixed, affordances={"edit": titled}), ada)

        assert queries == baseline + 2
        assert [row.affordance__edit__not_draft for row in rows] == [True, False, False, True]

    def test_a_generator_is_walked_once_and_the_list_flows_on(
        self, ada: Any, two_notes: Any
    ) -> None:
        def lazily(*, user: Any) -> Iterator[Note]:
            yield from notes_of(user=user)

        rows = rows_of(listing(lazily), ada)

        assert isinstance(rows, list)
        assert [first_unmet(row) for row in rows] == [None, "note_archived"]

    def test_a_row_deleted_after_the_selector_ran_has_no_row_answer(
        self, ada: Any, two_notes: Any
    ) -> None:
        # ``None``, not ``False``: a ``False`` names a condition the row fails,
        # and a row that no longer exists fails none of them.
        def then_delete(*, user: Any) -> list[Note]:
            rows = list(notes_of(user=user))
            Note.objects.filter(pk=rows[0].pk).delete()
            return rows

        gone, archived = rows_of(listing(then_delete), ada)

        assert gone.affordance__rename__note_archived is None
        # A callable condition is not about the row, and still answers.
        assert gone.affordance__rename__books_closed is True
        # The row that still exists is answered as before.
        assert first_unmet(archived) == "note_archived"

    def test_a_default_manager_that_hides_the_rows_does_not_decide(self, ada: Any) -> None:
        Note.objects.create(owner=ada, title="hidden", archived=True)
        always = ServiceSpec(
            service=lambda: None,
            permissions=OPEN,
            affordances=[Affordance(code="c", reason="r", when=Q(pk__isnull=False))],
        )
        selector = lambda: list(LiveNote._base_manager.all())  # noqa: E731

        rows = rows_of(listing(selector, affordances={"a": always}), ada)

        assert [row.affordance__a__c for row in rows] == [True]

    def test_an_instance_with_no_primary_key_is_refused_by_name(self, ada: Any) -> None:
        spec = listing(lambda: [Note(title="never saved")])

        with pytest.raises(ImproperlyConfigured) as caught:
            rows_of(spec, ada)

        assert str(caught.value) == (
            "SelectorSpec.selector returned <Note: Note object (None)>, which has no primary "
            "key, and a condition on the row is answered by finding the row. Return saved "
            "instances."
        )

    def test_an_instance_with_no_primary_key_is_fine_with_only_callable_conditions(
        self, ada: Any
    ) -> None:
        callable_only = ServiceSpec(
            service=lambda: None, permissions=OPEN, affordances=[BOOKS_CLOSED]
        )

        (row,) = rows_of(
            listing(lambda: [Note(title="never saved")], affordances={"a": callable_only}), ada
        )

        assert row.affordance__a__books_closed is False

    def test_a_retrieve_selector_returning_an_instance_carries_its_answers(
        self, ada: Any, two_notes: Any
    ) -> None:
        spec = SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=lambda *, pk: Note.objects.get(pk=pk),
            permissions=OPEN,
            reads=PK,
            affordances={"rename": RENAME},
        )

        row = rows_of(spec, ada, arguments={"pk": two_notes[1].pk})

        assert isinstance(row, Note)
        assert first_unmet(row) == "note_archived"

    def test_a_retrieve_selector_returning_nothing_passes_nothing_through(self, ada: Any) -> None:
        spec = SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=lambda: None,
            permissions=OPEN,
            allow_none=True,
            affordances={"rename": RENAME},
        )

        assert rows_of(spec, ada) is None

    def test_a_retrieve_selector_returning_a_mapping_gets_a_new_one(self, ada: Any) -> None:
        row = {"id": 1, "title": "computed"}
        callable_only = ServiceSpec(
            service=lambda: None, permissions=OPEN, affordances=[BOOKS_CLOSED]
        )
        spec = SelectorSpec(
            kind=SelectorKind.RETRIEVE,
            selector=lambda: row,
            permissions=OPEN,
            affordances={"a": callable_only},
        )

        answered = rows_of(spec, ada)

        assert answered == {"id": 1, "title": "computed", "affordance__a__books_closed": False}
        assert row == {"id": 1, "title": "computed"}

    def test_mapping_rows_get_new_mappings_with_the_callable_answers(self, ada: Any) -> None:
        callable_only = ServiceSpec(
            service=lambda: None, permissions=OPEN, affordances=[BOOKS_CLOSED]
        )

        rows = rows_of(
            listing(lambda: [{"id": 1}, {"id": 2}], affordances={"a": callable_only}), ada
        )

        assert rows == [
            {"id": 1, "affordance__a__books_closed": False},
            {"id": 2, "affordance__a__books_closed": False},
        ]

    def test_a_condition_on_the_row_beside_mapping_rows_is_refused_with_the_way_out(
        self, ada: Any
    ) -> None:
        with pytest.raises(ImproperlyConfigured) as caught:
            rows_of(listing(lambda: [{"id": 1}]), ada)

        assert str(caught.value) == (
            "SelectorSpec.selector returned mapping rows, and the affordances declare a "
            "condition on the row: a mapping has no model and no primary key to evaluate one "
            "against. Return model instances or a QuerySet, or keep only callable conditions."
        )

    def test_instance_and_mapping_rows_are_each_answered(self, ada: Any, two_notes: Any) -> None:
        callable_only = ServiceSpec(
            service=lambda: None, permissions=OPEN, affordances=[BOOKS_CLOSED]
        )
        live = two_notes[0]

        rows = rows_of(listing(lambda: [live, {"id": 9}], affordances={"a": callable_only}), ada)

        assert rows[0] is live
        assert live.affordance__a__books_closed is False
        assert rows[1] == {"id": 9, "affordance__a__books_closed": False}

    @pytest.mark.parametrize("row", ["a string", 3, object()], ids=["str", "int", "object"])
    def test_a_row_that_is_neither_an_instance_nor_a_mapping_is_refused(
        self, ada: Any, row: Any
    ) -> None:
        with pytest.raises(ImproperlyConfigured) as caught:
            rows_of(listing(lambda: [row]), ada)

        assert str(caught.value) == (
            f"SelectorSpec.selector returned a row of type {type(row).__name__}. Affordance "
            "answers are carried by model instances and mappings; return one of those, or a "
            "QuerySet."
        )

    @pytest.mark.parametrize(
        "result", [{"id": 1}, "rows", b"rows", 3], ids=["mapping", "str", "bytes", "int"]
    )
    def test_a_list_result_that_is_not_an_iterable_of_rows_is_refused(
        self, ada: Any, result: Any
    ) -> None:
        with pytest.raises(ImproperlyConfigured) as caught:
            rows_of(listing(lambda: result), ada)

        assert str(caught.value) == (
            "affordances are declared on a LIST spec but SelectorSpec.selector returned "
            f"{type(result).__name__}, which is neither a QuerySet nor an iterable of rows."
        )
