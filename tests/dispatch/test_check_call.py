from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

from django_service_specs.authorization.not_permitted import NotPermitted
from django_service_specs.authorization.permission_check import PermissionCheck
from django_service_specs.authorization.principal_unavailable import PrincipalUnavailable
from django_service_specs.dispatch.bind_arguments import bind_arguments
from django_service_specs.dispatch.check_call import check_call
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.grant import Grant
from django_service_specs.parameters.invalid_arguments import InvalidArguments
from django_service_specs.parameters.parameters import Parameter, Parameters
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.selector_kind import SelectorKind
from django_service_specs.types.unknown_arguments import UnknownArguments
from tests.dispatch.utils import (
    OPEN,
    PK,
    TENANT_SEEDS,
    Arguing,
    Offered,
    Record,
    Refuse,
    Scoped,
    Titled,
    make_user,
)
from tests.dispatch_app.models import Note
from tests.specs.utils import Foreign

LIST = SelectorKind.LIST
pytestmark = pytest.mark.django_db


@pytest.fixture
def ada() -> Any:
    return make_user("ada")


def _deactivated(username: str) -> Any:
    user = make_user(username)
    user.is_active = False
    user.save(update_fields=["is_active"])
    return user


class _Asked(PermissionCheck):
    """Admits every principal and records each spec it was asked about."""

    def __init__(self, admit: bool = True) -> None:
        self.admit = admit
        self.asked: list[Any] = []

    def has_permission(self, principal: Any, spec: Any) -> bool:
        self.asked.append(spec)
        return self.admit


def _searching(*checks: PermissionCheck) -> SelectorSpec:
    return SelectorSpec(
        kind=LIST,
        selector=lambda *, search="": Note.objects.filter(title__icontains=search),
        permissions=checks or OPEN,
        reads=Parameters.of(Parameter("search", "string")),
    )


def _rows(*checks: PermissionCheck) -> ServiceSpec:
    return ServiceSpec(service=Record(), permissions=checks or OPEN, many=True, validator=Titled())


# --- the signature -----------------------------------------------------------------------


def test_its_keywords_are_dispatch_s_up_to_what_only_a_run_needs() -> None:
    def keywords(function: Callable[..., Any]) -> dict[str, Any]:
        return {
            name: (param.kind, param.default)
            for name, param in inspect.signature(function).parameters.items()
        }

    ran = keywords(dispatch)
    assert keywords(check_call) == {
        name: ran[name]
        for name in (
            "spec",
            "principal",
            "arguments",
            "grant",
            "pool_seeds",
            "unknown_arguments",
            "call_context",
        )
    }


# --- what it answers ----------------------------------------------------------------------


def test_it_returns_the_checked_arguments_and_the_grant_dispatch_honours(ada: Any) -> None:
    check = _Asked()
    spec = _searching(check)

    checked, grant = check_call(spec, principal=ada, arguments={"search": "a"})

    assert checked == {"search": "a"}
    assert grant.covers(spec, ada)
    dispatch(spec, principal=ada, arguments={"search": "a"}, grant=grant)
    assert check.asked == [spec]


def test_the_kernel_s_own_steps_run_no_query(ada: Any, django_assert_num_queries: Any) -> None:
    with django_assert_num_queries(0):
        check_call(_searching(), principal=ada, arguments={"search": "a"})


def test_a_deactivated_principal_is_refused_without_a_query(
    django_assert_num_queries: Any,
) -> None:
    check = _Asked()
    who = _deactivated("ada")

    with django_assert_num_queries(0), pytest.raises(PrincipalUnavailable):
        check_call(_searching(check), principal=who, arguments={"search": 3})

    assert check.asked == []


def test_a_foreign_declaration_is_checked_as_its_compiled_spec(ada: Any) -> None:
    compiled = _searching()
    source = Foreign(compiled)

    checked, grant = check_call(source, principal=ada, arguments={"search": "a"})

    assert checked == {"search": "a"}
    assert grant.covers(compiled, ada)


def test_it_validates_nothing_where_bind_arguments_validates(ada: Any) -> None:
    # The complement: check_call authorizes and never runs the Validator;
    # bind_arguments runs the Validator and never authorizes.
    validator = Titled()
    spec = ServiceSpec(service=Record(), permissions=[Refuse()], validator=validator)

    with pytest.raises(NotPermitted):
        check_call(spec, principal=ada, arguments={"title": " T "})
    assert validator.calls == []
    assert bind_arguments(spec, {"title": " T "}, principal=ada) == {"title": "T"}


# --- the same refusal, at the same step, as dispatch -------------------------------------


_SEEDED = SelectorSpec(
    kind=LIST,
    selector=lambda **_: [],
    permissions=OPEN,
    reads=Parameters.of(Parameter("tenant", "string")),
)


@pytest.mark.parametrize(
    ("case", "refusal"),
    [
        (lambda ada: (_searching(), _deactivated("grace"), {}), PrincipalUnavailable),
        (lambda ada: (_SEEDED, ada, {"pool_seeds": TENANT_SEEDS}), ImproperlyConfigured),
        (lambda ada: (_searching(), ada, {"arguments": {"search": 3}}), InvalidArguments),
        (lambda ada: (_searching(Refuse()), ada, {}), NotPermitted),
        (
            lambda ada: (_searching(), ada, {"unknown_arguments": UnknownArguments.PASSTHROUGH}),
            ValueError,
        ),
    ],
    ids=["deactivated", "seed-occupied", "bad arguments", "not permitted", "passthrough"],
)
def test_it_refuses_what_dispatch_refuses_with_the_same_error(
    ada: Any, case: Callable[[Any], tuple[Any, Any, dict[str, Any]]], refusal: type[Exception]
) -> None:
    spec, principal, keywords = case(ada)
    call: dict[str, Any] = {"arguments": {}, **keywords}

    with pytest.raises(refusal) as by_dispatch:
        dispatch(spec, principal=principal, **call)
    with pytest.raises(refusal) as by_check_call:
        check_call(spec, principal=principal, **call)

    assert type(by_check_call.value) is type(by_dispatch.value)
    assert str(by_check_call.value) == str(by_dispatch.value)
    assert getattr(by_check_call.value, "detail", None) == getattr(
        by_dispatch.value, "detail", None
    )


def test_the_order_is_dispatch_s_arguments_are_checked_before_the_permission(ada: Any) -> None:
    # A shape refusal answers before a refusing check, on both.
    spec = _searching(Refuse())
    for call in (dispatch, check_call):
        with pytest.raises(InvalidArguments):
            call(spec, principal=ada, arguments={"search": 3})


def test_a_seed_occupied_parameter_is_refused_before_the_arguments(ada: Any) -> None:
    with pytest.raises(ImproperlyConfigured, match="which a registered pool seed occupies"):
        check_call(_SEEDED, principal=ada, arguments={"tenant": 3}, pool_seeds=TENANT_SEEDS)


# --- a many spec ----------------------------------------------------------------------------


def test_a_many_spec_s_rows_come_back_as_a_list_of_checked_rows(ada: Any) -> None:
    checked, _ = check_call(
        _rows(), principal=ada, arguments={"items": [{"title": "a"}, {"title": "b"}]}
    )
    assert checked == {"items": [{"title": "a"}, {"title": "b"}]}


def test_a_many_spec_s_refused_rows_are_raised_as_dispatch_raises_them(ada: Any) -> None:
    arguments = {"items": [{"title": "a"}, {"title": 3}, {"tenant": "x", "title": "c"}]}

    with pytest.raises(InvalidArguments) as by_dispatch:
        dispatch(_rows(), principal=ada, arguments=arguments)
    with pytest.raises(InvalidArguments) as by_check_call:
        check_call(_rows(), principal=ada, arguments=arguments)

    assert by_check_call.value.detail == by_dispatch.value.detail
    assert by_check_call.value.detail == {
        "items": {1: {"title": ["Expected a string."]}, 2: {"tenant": ["Unknown argument."]}}
    }


def test_a_refused_row_is_marked_as_raised_after_the_class_level_check(ada: Any) -> None:
    # The grant ``check_call`` earned still holds when it raises a row: step
    # four has passed. Dispatch's own refusal of the same row is unmarked, so
    # the mark is ``check_call``'s alone.
    arguments = {"items": [{"title": "a"}, {"title": 3}]}
    spec = _rows(_Asked())

    with pytest.raises(InvalidArguments) as by_check_call:
        check_call(spec, principal=ada, arguments=arguments)
    with pytest.raises(InvalidArguments) as by_dispatch:
        dispatch(spec, principal=ada, arguments=arguments)

    assert by_check_call.value.after_authorize is True
    assert by_dispatch.value.after_authorize is False


def test_a_failed_shape_is_not_marked_as_raised_after_the_class_level_check(ada: Any) -> None:
    # Held by name: a ``many`` spec whose list is no list, an argument the
    # call does not take, and a spec that is not ``many``. Each is raised
    # before step four, so no grant exists yet.
    asked = _Asked()
    for spec, arguments in (
        (_rows(asked), {"items": 3}),
        (_rows(asked), {"items": [], "tenant": "x"}),
        (_searching(asked), {"search": 3}),
    ):
        with pytest.raises(InvalidArguments) as caught:
            check_call(spec, principal=ada, arguments=arguments)
        assert caught.value.after_authorize is False
    assert asked.asked == []


def test_a_refused_principal_learns_nothing_about_the_rows_it_sent(ada: Any) -> None:
    with pytest.raises(NotPermitted):
        check_call(_rows(Refuse()), principal=ada, arguments={"items": [{"title": 3}]})


def test_a_grant_for_another_spec_is_refused_as_dispatch_refuses_it(ada: Any) -> None:
    spec = _searching()
    grant = Grant(_searching(), ada)
    for call in (dispatch, check_call):
        with pytest.raises(NotPermitted, match="does not cover this spec"):
            call(spec, principal=ada, arguments={}, grant=grant)


def test_a_pk_read_is_checked_as_declared(ada: Any) -> None:
    spec = SelectorSpec(
        kind=SelectorKind.RETRIEVE,
        selector=lambda *, pk: Note.objects.filter(pk=pk),
        permissions=OPEN,
        reads=PK,
    )
    with pytest.raises(InvalidArguments) as caught:
        check_call(spec, principal=ada, arguments={})
    assert caught.value.detail == {"pk": ["This field is required."]}


def test_a_scope_check_is_left_to_dispatch(ada: Any) -> None:
    # Nothing after the prelude runs: a create whose scope check refuses
    # passes here, and is refused when dispatch runs it.
    check = Scoped(refuse_scope=True)
    spec = ServiceSpec(service=Record(), permissions=[check])

    check_call(spec, principal=ada, arguments={})
    assert check.scopes == []
    with pytest.raises(NotPermitted, match="Not within your scope."):
        dispatch(spec, principal=ada, arguments={})


def test_a_check_declaring_arguments_is_handed_what_dispatch_hands_it(ada: Any) -> None:
    arguing = Arguing()
    check_call(_searching(arguing), principal=ada, arguments={"search": "x"})
    assert arguing.questions() == [("has_permission", {"search": "x"})]


def test_a_many_spec_s_check_is_handed_no_rows_as_under_dispatch(ada: Any) -> None:
    arguing = Arguing()
    check_call(_rows(arguing), principal=ada, arguments={"items": [{"title": "a"}]})
    assert arguing.questions() == [("has_permission", {})]


def test_its_checks_are_offered_the_call_context_passed_and_the_seeds_they_name() -> None:
    check = Offered()
    spec = SelectorSpec(kind=LIST, selector=list, permissions=[check])
    context: dict[str, Any] = {}
    ada = make_user("ada")
    check_call(spec, principal=ada, arguments={}, pool_seeds=TENANT_SEEDS, call_context=context)
    check_call(spec, principal=ada, arguments={}, pool_seeds=TENANT_SEEDS)
    (_, first, tenant), (_, second, _) = check.asked
    assert first is context
    assert tenant == "tenant-of-ada"
    assert second == {}
    assert second is not context
