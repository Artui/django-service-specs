from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db.models import BooleanField, Exists, ExpressionWrapper, F, OuterRef, Q, Value
from django.utils.functional import lazy
from django.utils.translation import gettext_lazy

from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.affordance import Affordance
from django_service_specs.types.selector_kind import SelectorKind
from tests.dispatch_app.models import Note


def test_a_q_is_a_condition_on_the_row() -> None:
    affordance = Affordance(code="note_archived", reason="Archived.", when=Q(archived=False))
    assert affordance.code == "note_archived"
    assert affordance.reason == "Archived."
    assert affordance.when == Q(archived=False)


@pytest.mark.parametrize(
    "when",
    [
        Exists(Note.objects.filter(pk=OuterRef("pk"))),
        ExpressionWrapper(Q(archived=False), output_field=BooleanField()),
        Value(True, output_field=BooleanField()),
    ],
    ids=["exists", "wrapped-q", "boolean-value"],
)
def test_any_boolean_orm_expression_is_a_condition_on_the_row(when: Any) -> None:
    assert Affordance(code="c", reason="r", when=when).when is when


def test_a_callable_reading_only_seeds_is_a_condition_on_nothing_in_particular() -> None:
    def open_for_business(*, user: Any, progress: Any = None) -> bool:
        return True

    assert Affordance(code="c", reason="r", when=open_for_business).when is open_for_business


def test_a_callable_taking_kwargs_is_accepted_and_withheld_the_per_call_names_later() -> None:
    # A catch-all names nothing, so the declaration cannot refuse it.
    def anything(**kwargs: Any) -> bool:
        return True

    assert Affordance(code="c", reason="r", when=anything).when is anything


def test_it_is_frozen() -> None:
    affordance = Affordance(code="c", reason="r", when=Q(archived=False))
    with pytest.raises(dataclasses.FrozenInstanceError):
        affordance.code = "d"  # type: ignore[misc]


class TestCodeAndReason:
    # The guard is ``not isinstance(value, str) or not value``.
    @pytest.mark.parametrize("field_name", ["code", "reason"])
    @pytest.mark.parametrize(
        "value", [pytest.param(7, id="non-string"), pytest.param("", id="empty-string")]
    )
    def test_anything_but_a_non_empty_string_is_refused(self, field_name: str, value: Any) -> None:
        values: dict[str, Any] = {"code": "c", "reason": "r", field_name: value}
        with pytest.raises(ImproperlyConfigured) as refused:
            Affordance(**values, when=Q(archived=False))
        assert str(refused.value) == (
            f"Affordance.{field_name} must be a non-empty string; got {value!r}."
        )


class TestALazyReason:
    def test_a_gettext_lazy_reason_is_accepted_as_given(self) -> None:
        reason = gettext_lazy("A shipped order cannot be cancelled.")
        assert Affordance(code="c", reason=reason, when=Q(archived=False)).reason is reason

    def test_it_is_not_evaluated_by_the_declarations_that_hold_it(self) -> None:
        calls: list[str] = []

        def text() -> str:
            calls.append("resolved")
            return "Closed."

        affordance = Affordance(code="c", reason=lazy(text, str)(), when=Q(archived=False))
        service_spec = ServiceSpec(service=print, affordances=[affordance])
        SelectorSpec(kind=SelectorKind.LIST, selector=print, affordances={"x": service_spec})
        assert calls == []

    def test_a_lazy_code_is_refused(self) -> None:
        with pytest.raises(ImproperlyConfigured, match=r"^Affordance\.code must be a non-empty"):
            Affordance(code=gettext_lazy("c"), reason="r", when=Q(archived=False))

    @pytest.mark.parametrize("reason", [7, b"bytes", None], ids=["int", "bytes", "none"])
    def test_neither_text_nor_a_lazy_string_is_refused(self, reason: Any) -> None:
        with pytest.raises(ImproperlyConfigured, match=r"^Affordance\.reason must be a non-empty"):
            Affordance(code="c", reason=reason, when=Q(archived=False))


class TestWhen:
    def test_an_expression_that_is_not_boolean_is_refused(self) -> None:
        with pytest.raises(ImproperlyConfigured) as refused:
            Affordance(code="c", reason="r", when=F("title"))
        assert str(refused.value).startswith(
            "Affordance 'c': `when` is an ORM expression but not a boolean one (F(title))."
        )

    @pytest.mark.parametrize("when", [True, "archived=False", None])
    def test_neither_an_expression_nor_a_callable_is_refused(self, when: Any) -> None:
        with pytest.raises(ImproperlyConfigured) as refused:
            Affordance(code="c", reason="r", when=when)
        assert str(refused.value) == (
            "Affordance 'c': `when` must be an ORM boolean expression (a condition on the "
            "row) or a callable (a condition on nothing in particular); got "
            f"{type(when).__name__}."
        )

    def test_a_callable_reading_the_row_is_refused_towards_an_expression(self) -> None:
        def not_archived(*, instance: Note) -> bool:
            return not instance.archived

        with pytest.raises(ImproperlyConfigured) as refused:
            Affordance(code="c", reason="r", when=not_archived)
        message = str(refused.value)
        assert message.startswith("Affordance 'c': `when` is a callable that reads `instance`.")
        assert "a Q or an Exists" in message

    @pytest.mark.parametrize(
        ("name", "when"),
        [
            ("data", lambda *, user, data: True),
            ("collection", lambda *, user, collection: True),
            ("result", lambda *, user, result: True),
            ("queryset", lambda *, user, queryset: True),
        ],
        ids=lambda value: value if isinstance(value, str) else "",
    )
    def test_a_callable_reading_another_per_call_name_is_refused(
        self, name: str, when: Any
    ) -> None:
        with pytest.raises(ImproperlyConfigured) as refused:
            Affordance(code="c", reason="r", when=when)
        assert str(refused.value).startswith(
            f"Affordance 'c': `when` reads {name!r}, which exist only once a call is being made."
        )

    def test_every_per_call_name_a_callable_reads_is_named_in_order(self) -> None:
        # Four, declared out of order, so an unsorted set cannot pass by luck of the hash seed.
        def when(*, user: Any, result: Any, serializer: Any, data: Any, queryset: Any) -> bool:
            return True

        with pytest.raises(ImproperlyConfigured) as refused:
            Affordance(code="c", reason="r", when=when)
        assert str(refused.value).startswith(
            "Affordance 'c': `when` reads 'data', 'queryset', 'result', 'serializer',"
        )

    def test_instance_beside_another_per_call_name_answers_with_the_row_message(self) -> None:
        def when(*, data: Any, instance: Any) -> bool:
            return True

        with pytest.raises(ImproperlyConfigured) as refused:
            Affordance(code="c", reason="r", when=when)
        assert "reads `instance`" in str(refused.value)


async def _books_closed() -> bool:
    return False


async def _books_closed_lazily() -> Any:
    yield False


class _BooksClosed:
    """A callable object whose ``__call__`` is ``async def``: the function itself is not."""

    async def __call__(self) -> bool:
        return False


class TestAnAsyncCondition:
    """A condition is sync-only and is never awaited: an async one is refused when declared."""

    def test_an_async_def_is_refused(self) -> None:
        with pytest.raises(ImproperlyConfigured) as refused:
            Affordance(code="books_closed", reason="r", when=_books_closed)
        message = str(refused.value)
        assert message.startswith("Affordance 'books_closed': `when` is an async callable")
        assert "_books_closed" in message

    def test_an_object_whose_call_is_async_is_refused(self) -> None:
        with pytest.raises(ImproperlyConfigured) as refused:
            Affordance(code="books_closed", reason="r", when=_BooksClosed())
        assert str(refused.value).startswith(
            "Affordance 'books_closed': `when` is an async callable"
        )

    def test_an_async_generator_function_is_refused(self) -> None:
        # Not a coroutine function, and what it returns is not awaitable either.
        with pytest.raises(ImproperlyConfigured) as refused:
            Affordance(code="books_closed", reason="r", when=_books_closed_lazily)
        assert str(refused.value).startswith(
            "Affordance 'books_closed': `when` is an async callable"
        )

    @pytest.mark.parametrize(
        "when",
        [Q(archived=False), Exists(Note.objects.filter(pk=OuterRef("pk")))],
        ids=["q", "exists"],
    )
    def test_an_expression_is_still_a_condition_on_the_row(self, when: Any) -> None:
        # The row check returns before the async check is asked.
        assert Affordance(code="c", reason="r", when=when).when is when
