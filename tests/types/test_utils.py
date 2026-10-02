"""The helpers ``types/`` shares with the specs and the affordance phase."""

from __future__ import annotations

from django.db.models import Exists, F, OuterRef, Q

from django_service_specs.pool.reserved_pool_seeds import RESERVED_POOL_SEEDS
from django_service_specs.types.utils import (
    PER_CALL_POOL_NAMES,
    affordance_alias,
    is_row_condition,
)
from tests.dispatch_app.models import Note


def test_the_per_call_names_and_the_ambient_seeds_partition_the_reserved_names() -> None:
    # ``types/`` cannot import ``pool/``, so the per-call names are written out
    # rather than derived. This is what holds the two lists together: a name
    # reserved later has to be placed on one side or the other, deliberately.
    assert PER_CALL_POOL_NAMES <= RESERVED_POOL_SEEDS
    ambient = RESERVED_POOL_SEEDS - PER_CALL_POOL_NAMES
    assert ambient == {"user", "progress"}


def test_an_orm_expression_is_a_row_condition_and_a_callable_is_not() -> None:
    assert is_row_condition(Q(archived=False))
    assert is_row_condition(Exists(Note.objects.filter(pk=OuterRef("pk"))))
    assert is_row_condition(F("archived"))
    assert not is_row_condition(lambda: True)
    assert not is_row_condition(True)


def test_an_alias_cannot_shadow_a_model_field() -> None:
    # Django refuses ``__`` in a field name, so a double-underscored alias is
    # never one.
    assert affordance_alias("rename", "note_archived") == "affordance__rename__note_archived"
