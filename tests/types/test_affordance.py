"""``Affordance``: a condition under which an operation can be done right now."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db.models import BooleanField, Exists, ExpressionWrapper, F, OuterRef, Q, Value

from django_service_specs.types.affordance import Affordance
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
    # A catch-all names nothing, so the declaration cannot refuse it; what it
    # is handed is filtered instead (tests/affordances/test_utils.py).
    def anything(**kwargs: Any) -> bool:
        return True

    assert Affordance(code="c", reason="r", when=anything).when is anything


def test_it_is_frozen() -> None:
    affordance = Affordance(code="c", reason="r", when=Q(archived=False))
    with pytest.raises(dataclasses.FrozenInstanceError):
        affordance.code = "d"  # type: ignore[misc]


class TestCodeAndReason:
    # The guard is ``not isinstance(value, str) or not value``: each of its two
    # halves is held by its own case here, for each of the two fields.
    @pytest.mark.parametrize("field_name", ["code", "reason"])
    def test_a_non_string_is_refused(self, field_name: str) -> None:
        values: dict[str, Any] = {"code": "c", "reason": "r", field_name: 7}
        with pytest.raises(ImproperlyConfigured) as refused:
            Affordance(**values, when=Q(archived=False))
        assert str(refused.value) == f"Affordance.{field_name} must be a non-empty string; got 7."

    @pytest.mark.parametrize("field_name", ["code", "reason"])
    def test_an_empty_string_is_refused(self, field_name: str) -> None:
        values: dict[str, Any] = {"code": "c", "reason": "r", field_name: ""}
        with pytest.raises(ImproperlyConfigured) as refused:
            Affordance(**values, when=Q(archived=False))
        assert str(refused.value) == f"Affordance.{field_name} must be a non-empty string; got ''."


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
        # Four, declared out of order, so an unsorted set cannot pass by luck of
        # the hash seed, as two names would half the time.
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
