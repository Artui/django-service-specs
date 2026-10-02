"""The helpers every reader of an affordance answers through."""

from __future__ import annotations

from typing import Any

import pytest
from django.db.models import BooleanField, Q, Value

from django_service_specs.affordances.utils import (
    affordance_expression,
    ambient_pool,
    answer_operation_condition,
)
from django_service_specs.pool.base_pool import base_pool
from django_service_specs.pool.reserved_pool_seeds import RESERVED_POOL_SEEDS
from tests.dispatch.utils import TENANT_SEEDS, make_user
from tests.dispatch_app.models import Note


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
        assert seen == {"user": ada, "tenant": "tenant-of-ada"}

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
