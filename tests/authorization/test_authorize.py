from __future__ import annotations

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.authorization.authorize import authorize
from django_service_specs.authorization.grant import Grant
from django_service_specs.authorization.not_permitted import NotPermitted
from django_service_specs.authorization.unrestricted import Unrestricted
from django_service_specs.specs.selector_kind import SelectorKind
from django_service_specs.specs.selector_spec import SelectorSpec
from tests.authorization.utils import Allow, Refuse, RefuseWithMessage


def _spec(permissions: list | None) -> SelectorSpec:
    return SelectorSpec(kind=SelectorKind.LIST, selector=list, permissions=permissions)


def test_a_covering_grant_is_returned_as_is() -> None:
    spec, principal = _spec([Unrestricted()]), object()
    grant = Grant(spec, principal)
    assert authorize(spec, principal, grant=grant) is grant


def test_a_non_covering_grant_raises_not_permitted() -> None:
    spec, principal = _spec([Unrestricted()]), object()
    other_grant = Grant(_spec([Unrestricted()]), principal)
    with pytest.raises(NotPermitted, match="does not cover"):
        authorize(spec, principal, grant=other_grant)


def test_no_grant_and_no_declared_permissions_raises_improperly_configured() -> None:
    spec, principal = _spec(None), object()
    with pytest.raises(ImproperlyConfigured, match="Unrestricted"):
        authorize(spec, principal)


def test_no_grant_and_a_passing_check_returns_a_fresh_grant() -> None:
    spec, principal = _spec([Unrestricted()]), object()
    grant = authorize(spec, principal)
    assert isinstance(grant, Grant)
    assert grant.covers(spec, principal)
    assert grant.target_checked is False


def test_a_refusal_raises_not_permitted_with_the_default_message() -> None:
    spec, principal = _spec([Refuse()]), object()
    with pytest.raises(NotPermitted) as excinfo:
        authorize(spec, principal)
    assert excinfo.value.message == NotPermitted.default_message


def test_a_refusal_raises_not_permitted_with_the_checks_own_message() -> None:
    spec, principal = _spec([RefuseWithMessage()]), object()
    with pytest.raises(NotPermitted, match="Staff only."):
        authorize(spec, principal)


def test_checks_run_in_order_and_stop_at_the_first_refusal() -> None:
    later = Allow()
    spec, principal = _spec([Refuse(), later]), object()
    with pytest.raises(NotPermitted):
        authorize(spec, principal)
    assert later.class_level_calls == 0


def test_every_check_runs_when_all_pass() -> None:
    first, second = Allow(), Allow()
    spec, principal = _spec([first, second]), object()
    authorize(spec, principal)
    assert first.class_level_calls == 1
    assert second.class_level_calls == 1
