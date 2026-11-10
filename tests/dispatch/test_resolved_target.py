from __future__ import annotations

import copy
import pickle
from collections.abc import Callable
from typing import Any

import pytest

from django_service_specs.dispatch.dispatch_result import DispatchResult
from django_service_specs.dispatch.grant import Grant
from django_service_specs.dispatch.resolve_target import resolve_target
from tests.dispatch.utils import Tenancy, make_user
from tests.dispatch_app.models import Note
from tests.specs.utils import Foreign

pytestmark = pytest.mark.django_db


def test_resolve_target_still_unpacks_to_two() -> None:
    ada, tenancy = make_user("ada"), Tenancy()
    note = Note.objects.create(title="n", owner=ada)
    spec, context = tenancy.spec(), {}

    found = resolve_target(
        spec,
        principal=ada,
        arguments={"pk": note.pk},
        pool_seeds=tenancy.pool_seeds,
        call_context=context,
    )
    assert not isinstance(found, DispatchResult)
    target, grant = found

    assert isinstance(found, tuple)
    assert len(found) == 2
    assert target == note
    assert found[0] is target
    assert isinstance(grant, Grant)
    assert grant.target_checked is True
    assert found[1] is grant
    assert found.seeds.covers(spec, ada, context, tenancy.pool_seeds)
    assert dict(found.seeds.values) == {"tenant": tenancy.resolved[0]}
    assert tenancy.one_value()


def test_its_seeds_keep_the_declaration_they_were_handed() -> None:
    """The transport's own object, as a grant keeps it; compared compiled, so it covers both."""
    ada, tenancy = make_user("ada"), Tenancy()
    note = Note.objects.create(title="n", owner=ada)
    source, context = Foreign(tenancy.spec()), {}

    found = resolve_target(
        source,
        principal=ada,
        arguments={"pk": note.pk},
        pool_seeds=tenancy.pool_seeds,
        call_context=context,
    )

    assert not isinstance(found, DispatchResult)
    assert found.seeds.spec is source
    assert found.seeds.covers(source, ada, context, tenancy.pool_seeds)
    assert found.seeds.covers(source.compiled, ada, context, tenancy.pool_seeds)


def test_a_missing_row_carries_no_seeds() -> None:
    """Dispatch's own answer, as before: there is no call to hand them on to."""
    ada, tenancy = make_user("ada"), Tenancy()

    found = resolve_target(
        tenancy.spec(), principal=ada, arguments={"pk": 999}, pool_seeds=tenancy.pool_seeds
    )

    assert isinstance(found, DispatchResult)
    assert found.kind == "not_found"


@pytest.mark.parametrize("serialize", [pickle.dumps, copy.copy, copy.deepcopy])
def test_it_cannot_be_pickled_for_the_seeds_it_carries(
    serialize: Callable[[Any], object],
) -> None:
    ada, tenancy = make_user("ada"), Tenancy()
    note = Note.objects.create(title="n", owner=ada)
    found: Any = resolve_target(
        tenancy.spec(), principal=ada, arguments={"pk": note.pk}, pool_seeds=tenancy.pool_seeds
    )
    assert found.seeds is found.seeds

    with pytest.raises(TypeError, match="cannot be serialized"):
        serialize(found)
