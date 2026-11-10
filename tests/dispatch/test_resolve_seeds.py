"""``resolve_seeds``: the seeds checks name, resolved once, for an ``authorize``-first call."""

from __future__ import annotations

from typing import Any

import pytest

from django_service_specs.authorization.not_permitted import NotPermitted
from django_service_specs.authorization.permission_check import PermissionCheck
from django_service_specs.authorization.principal_unavailable import PrincipalUnavailable
from django_service_specs.dispatch.authorize import authorize
from django_service_specs.dispatch.authorize_scope import authorize_scope
from django_service_specs.dispatch.check_call import check_call
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.resolve_seeds import resolve_seeds
from django_service_specs.dispatch.resolve_target import resolve_target
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.selector_kind import SelectorKind
from tests.dispatch.utils import (
    Deactivated,
    Record,
    SeedPerQuestion,
    Tenancy,
    Titled,
    make_user,
    recorded_seeds,
)
from tests.dispatch_app.models import Note
from tests.specs.utils import Foreign

pytestmark = pytest.mark.django_db


@pytest.fixture
def ada() -> Any:
    return make_user("ada")


def _listing(check: PermissionCheck) -> SelectorSpec:
    return SelectorSpec(kind=SelectorKind.LIST, selector=list, permissions=[check])


def test_it_resolves_what_check_call_resolves() -> None:
    """A seed per question, and ``locale``, which no check names and so stays unresolved."""
    pool_seeds, resolved = recorded_seeds()
    spec = _listing(SeedPerQuestion())
    checked = check_call(spec, principal="ada", arguments={}, pool_seeds=pool_seeds)
    resolved.clear()

    carrier = resolve_seeds(spec, principal="ada", pool_seeds=pool_seeds)

    assert dict(carrier.values) == {
        "club": "club of ada",
        "row_club": "row_club of ada",
        "scope_club": "scope_club of ada",
    }
    assert carrier.values.keys() == checked.seeds.values.keys()
    assert sorted(resolved) == ["club", "row_club", "scope_club"]


def test_a_deactivated_principal_resolves_no_seed() -> None:
    pool_seeds, resolved = recorded_seeds()
    with pytest.raises(PrincipalUnavailable):
        resolve_seeds(_listing(SeedPerQuestion()), principal=Deactivated(), pool_seeds=pool_seeds)
    assert resolved == []


def test_a_call_handed_no_context_gets_a_dict_readable_on_the_carrier() -> None:
    pool_seeds, _ = recorded_seeds()
    spec = _listing(SeedPerQuestion())
    context: dict[str, Any] = {}

    handed = resolve_seeds(spec, principal="ada", pool_seeds=pool_seeds, call_context=context)
    fresh = resolve_seeds(spec, principal="ada", pool_seeds=pool_seeds)

    assert handed.call_context is context
    assert isinstance(fresh.call_context, dict)
    assert fresh.call_context == {}
    # The dict it was bound to is the one that covers the call.
    grant = authorize(
        spec, "ada", seeds=fresh, pool_seeds=pool_seeds, call_context=fresh.call_context
    )
    assert grant.covers(spec, "ada")


def test_a_carrier_for_a_source_is_bound_to_the_source() -> None:
    pool_seeds, _ = recorded_seeds()
    source = Foreign(_listing(SeedPerQuestion()))
    carrier = resolve_seeds(source, principal="ada", pool_seeds=pool_seeds)
    assert carrier.spec is source
    assert carrier.values["club"] == "club of ada"


def test_a_spec_declaring_no_permissions_resolves_nothing() -> None:
    pool_seeds, resolved = recorded_seeds()
    spec = SelectorSpec(kind=SelectorKind.LIST, selector=list, permissions=None)
    assert dict(resolve_seeds(spec, principal="ada", pool_seeds=pool_seeds).values) == {}
    assert resolved == []


def test_authorize_without_the_carrier_s_context_is_refused() -> None:
    """The common mistake: a carrier minted with no ``call_context``, then handed on with none."""
    check = SeedPerQuestion()
    pool_seeds, _ = recorded_seeds()
    spec = _listing(check)
    carrier = resolve_seeds(spec, principal="ada", pool_seeds=pool_seeds)

    with pytest.raises(NotPermitted) as refused:
        authorize(spec, "ada", seeds=carrier, pool_seeds=pool_seeds)

    assert str(refused.value) == "The seeds do not cover this spec, principal and call context."
    assert check.handed == []


def test_one_resolution_from_resolve_seeds_to_dispatch(ada: Any) -> None:
    """Admitted, then the row found, then the run: one value of ``tenant`` throughout."""
    note = Note.objects.create(title="n", owner=ada)
    tenancy = Tenancy()
    spec, context = tenancy.spec(), {}

    carrier = resolve_seeds(
        spec, principal=ada, pool_seeds=tenancy.pool_seeds, call_context=context
    )
    grant = authorize(spec, ada, seeds=carrier, pool_seeds=tenancy.pool_seeds, call_context=context)
    found = resolve_target(
        spec,
        principal=ada,
        arguments={"pk": note.pk},
        grant=grant,
        pool_seeds=tenancy.pool_seeds,
        call_context=context,
        seeds=carrier,
    )
    target, checked = found
    dispatch(
        spec,
        principal=ada,
        arguments={"pk": note.pk},
        target=target,
        grant=checked,
        seeds=found.seeds,
        pool_seeds=tenancy.pool_seeds,
        call_context=context,
    )

    assert [stage for stage, _ in tenancy.seen] == [
        "has_permission",
        "instance_selector",
        "has_object_permission",
        "service",
    ]
    assert tenancy.one_value()


class _ScopeTenancy(PermissionCheck):
    """Names ``tenant`` at the class-level and the scope questions, recording what it is handed."""

    def __init__(self, seen: list[tuple[str, object]]) -> None:
        self.seen = seen

    def has_permission(self, principal: Any, spec: Any, *, tenant: object) -> bool:
        self.seen.append(("has_permission", tenant))
        return True

    def has_scope_permission(
        self, principal: Any, spec: Any, scope: Any, *, tenant: object
    ) -> bool:
        self.seen.append(("has_scope_permission", tenant))
        return True


def test_one_resolution_on_the_many_path(ada: Any) -> None:
    """Admitted, the scope checked ahead of the call, then the run: one value of ``tenant``."""
    tenancy = Tenancy()
    service = Record()
    spec = ServiceSpec(
        service=service, permissions=[_ScopeTenancy(tenancy.seen)], many=True, validator=Titled()
    )
    context: dict[str, Any] = {}

    carrier = resolve_seeds(
        spec, principal=ada, pool_seeds=tenancy.pool_seeds, call_context=context
    )
    grant = authorize(spec, ada, seeds=carrier, pool_seeds=tenancy.pool_seeds, call_context=context)
    authorize_scope(
        spec,
        ada,
        None,
        grant=grant,
        seeds=carrier,
        pool_seeds=tenancy.pool_seeds,
        call_context=context,
    )
    dispatch(
        spec,
        principal=ada,
        arguments={"items": [{"title": "a"}]},
        grant=grant,
        seeds=carrier,
        pool_seeds=tenancy.pool_seeds,
        call_context=context,
    )

    assert [stage for stage, _ in tenancy.seen] == [
        "has_permission",
        "has_scope_permission",
        "has_scope_permission",
    ]
    assert tenancy.one_value()
    assert service.calls[0]["tenant"] is tenancy.resolved[0]
