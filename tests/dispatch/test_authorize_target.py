from __future__ import annotations

import inspect

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.authorization.not_permitted import NotPermitted
from django_service_specs.authorization.unrestricted import Unrestricted
from django_service_specs.dispatch.authorize_target import authorize_target
from django_service_specs.dispatch.grant import Grant
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.types.selector_kind import SelectorKind
from tests.authorization.utils import Allow, AnswersWith, Refuse, RefuseWithMessage, refuses
from tests.dispatch.utils import Arguing
from tests.specs.utils import Foreign


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


def test_a_check_answering_with_a_coroutine_is_refused_rather_than_read_as_a_pass() -> None:
    # Sync-only like the class-level check: an unawaited answer is truthy.
    answer = refuses()
    spec, principal = _spec([AnswersWith(answer)]), object()
    with pytest.raises(ImproperlyConfigured, match="answered with an awaitable") as caught:
        authorize_target(spec, principal, object(), grant=Grant(spec, principal))
    assert "AnswersWith.has_object_permission" in str(caught.value)
    assert inspect.getcoroutinestate(answer) == inspect.CORO_CLOSED


def test_a_source_s_object_checks_are_the_spec_it_compiles_to_s() -> None:
    source, principal = Foreign(_spec([RefuseWithMessage()])), object()

    with pytest.raises(NotPermitted, match="Staff only."):
        authorize_target(source, principal, object(), grant=Grant(source, principal))


def test_a_source_s_grant_that_checked_the_target_skips_the_checks() -> None:
    check = Allow()
    source, principal = Foreign(_spec([check])), object()

    authorize_target(
        source, principal, object(), grant=Grant(source, principal, target_checked=True)
    )

    assert check.object_level_calls == 0


def test_a_check_declaring_arguments_is_handed_them_as_given_and_none_without() -> None:
    arguing, legacy = Arguing(), Allow()
    spec, principal, arguments = _spec([arguing, legacy]), object(), {"pk": 1}
    authorize_target(spec, principal, object(), grant=Grant(spec, principal), arguments=arguments)
    authorize_target(spec, principal, object(), grant=Grant(spec, principal))
    assert arguing.asked == [("has_object_permission", arguments), ("has_object_permission", None)]
