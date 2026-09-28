from __future__ import annotations

import pytest

from django_service_specs.authorization.authorize_target import authorize_target
from django_service_specs.authorization.grant import Grant
from django_service_specs.authorization.not_permitted import NotPermitted
from django_service_specs.authorization.unrestricted import Unrestricted
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from tests.authorization.utils import Allow, Refuse, RefuseWithMessage


def _spec(permissions: list | None) -> SelectorSpec:
    return SelectorSpec(kind=SelectorKind.RETRIEVE, selector=list, permissions=permissions)


def test_skips_the_checks_when_the_grant_already_checked_the_target() -> None:
    check = Allow()
    spec, principal, target = _spec([check]), object(), object()
    grant = Grant(spec, principal, target_checked=True)
    authorize_target(spec, principal, target, grant=grant)
    assert check.object_level_calls == 0


def test_no_permissions_declared_has_nothing_to_check() -> None:
    # authorize() already refused a spec whose permissions are None before any
    # target could be resolved, so this is reached only through a spec that
    # declared permissions=None for a nested selector, where authorize() never
    # looked at it at all. Nothing to check reads as pass, not refuse.
    spec, principal, target = _spec(None), object(), object()
    grant = Grant(spec, principal)
    authorize_target(spec, principal, target, grant=grant)


def test_a_passing_check_runs_and_raises_nothing() -> None:
    check = Allow()
    spec, principal, target = _spec([check]), object(), object()
    grant = Grant(spec, principal)
    authorize_target(spec, principal, target, grant=grant)
    assert check.object_level_calls == 1


def test_a_refusal_raises_not_permitted_with_the_default_message() -> None:
    spec, principal, target = _spec([Refuse()]), object(), object()
    grant = Grant(spec, principal)
    with pytest.raises(NotPermitted) as excinfo:
        authorize_target(spec, principal, target, grant=grant)
    assert excinfo.value.message == NotPermitted.default_message


def test_a_refusal_raises_not_permitted_with_the_checks_own_message() -> None:
    spec, principal, target = _spec([RefuseWithMessage()]), object(), object()
    grant = Grant(spec, principal)
    with pytest.raises(NotPermitted, match="Staff only."):
        authorize_target(spec, principal, target, grant=grant)


def test_checks_run_in_order_and_stop_at_the_first_refusal() -> None:
    later = Allow()
    spec, principal, target = _spec([Refuse(), later]), object(), object()
    grant = Grant(spec, principal)
    with pytest.raises(NotPermitted):
        authorize_target(spec, principal, target, grant=grant)
    assert later.object_level_calls == 0


def test_every_check_runs_when_all_pass() -> None:
    first, second = Allow(), Allow()
    spec, principal, target = _spec([first, second]), object(), object()
    grant = Grant(spec, principal)
    authorize_target(spec, principal, target, grant=grant)
    assert first.object_level_calls == 1
    assert second.object_level_calls == 1


def test_unrestricted_allows_at_the_object_level_too() -> None:
    spec, principal, target = _spec([Unrestricted()]), object(), object()
    grant = Grant(spec, principal)
    authorize_target(spec, principal, target, grant=grant)
