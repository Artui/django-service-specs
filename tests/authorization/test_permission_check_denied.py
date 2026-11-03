"""``PermissionCheckDenied``: the mark on a declared check's denial, and on no other ``NotPermitted``."""

from __future__ import annotations

from typing import Any

import pytest

from django_service_specs.authorization.all_of import AllOf
from django_service_specs.authorization.any_of import AnyOf
from django_service_specs.authorization.none_of import NoneOf
from django_service_specs.authorization.not_permitted import NotPermitted
from django_service_specs.authorization.permission_check import PermissionCheck
from django_service_specs.authorization.permission_check_denied import PermissionCheckDenied
from django_service_specs.authorization.unrestricted import Unrestricted
from django_service_specs.dispatch.adispatch import adispatch
from django_service_specs.dispatch.authorize import authorize
from django_service_specs.dispatch.authorize_scope import authorize_scope
from django_service_specs.dispatch.authorize_target import authorize_target
from django_service_specs.dispatch.dispatch import dispatch
from django_service_specs.dispatch.grant import Grant
from django_service_specs.dispatch.resolve_seeds import resolve_seeds
from django_service_specs.specs.kernel_spec import kernel_spec
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.selector_kind import SelectorKind
from tests.specs.utils import Foreign


class _Denies(PermissionCheck):
    """Denies at every question, by answering ``False``."""

    def __init__(self, message: str | None = None) -> None:
        self.message = message

    def has_permission(self, principal: Any, spec: Any) -> bool:
        return False

    def has_object_permission(self, principal: Any, spec: Any, target: Any) -> bool:
        return False

    def has_scope_permission(self, principal: Any, spec: Any, scope: Any) -> bool:
        return False


class _RaisesItself(PermissionCheck):
    """Refuses by raising ``NotPermitted`` inside the check, at every question."""

    def has_permission(self, principal: Any, spec: Any) -> bool:
        raise NotPermitted("Raised by the check.")

    def has_object_permission(self, principal: Any, spec: Any, target: Any) -> bool:
        raise NotPermitted("Raised by the check.")

    def has_scope_permission(self, principal: Any, spec: Any, scope: Any) -> bool:
        raise NotPermitted("Raised by the check.")


class _Admits(PermissionCheck):
    def has_permission(self, principal: Any, spec: Any) -> bool:
        return True


class _AdmitsTheClass(_Denies):
    """Passes the class-level question, so the row and scope questions are reached."""

    def has_permission(self, principal: Any, spec: Any) -> bool:
        return True


def _spec(permissions: list[PermissionCheck], kind: SelectorKind = SelectorKind.LIST) -> Any:
    return SelectorSpec(kind=kind, selector=list, permissions=permissions)


def _denied(call: Any) -> NotPermitted:
    with pytest.raises(NotPermitted) as refused:
        call()
    return refused.value


class TestACheckSDenialIsMarked:
    """Each of the three questions a declared check answers ``False`` to raises the mark."""

    def test_the_class_level_denial_carries_the_check_and_the_spec(self) -> None:
        check = _Denies("Members only.")
        spec = _spec([Unrestricted(), check])
        denied = _denied(lambda: authorize(spec, object()))
        assert type(denied) is PermissionCheckDenied
        assert isinstance(denied, PermissionCheckDenied)
        assert denied.check is check
        assert denied.spec is spec
        assert denied.message == "Members only."

    def test_the_row_denial_carries_the_check_and_the_spec(self) -> None:
        check = _AdmitsTheClass("Not your row.")
        spec, principal = _spec([check], SelectorKind.RETRIEVE), object()
        grant = Grant(spec, principal)
        denied = _denied(lambda: authorize_target(spec, principal, object(), grant=grant))
        assert isinstance(denied, PermissionCheckDenied)
        assert denied.check is check
        assert denied.spec is spec
        assert denied.message == "Not your row."

    def test_the_scope_denial_carries_the_check_and_the_spec(self) -> None:
        check = _AdmitsTheClass("Not this scope.")
        spec, principal = _spec([check]), object()
        grant = Grant(spec, principal)
        denied = _denied(lambda: authorize_scope(spec, principal, [], grant=grant))
        assert isinstance(denied, PermissionCheckDenied)
        assert denied.check is check
        assert denied.spec is spec
        assert denied.message == "Not this scope."

    def test_a_check_with_no_message_says_the_default_wording(self) -> None:
        denied = _denied(lambda: authorize(_spec([_Denies()]), object()))
        assert isinstance(denied, PermissionCheckDenied)
        assert denied.message == NotPermitted.default_message

    @pytest.mark.parametrize("combinator", [AllOf, AnyOf, NoneOf])
    def test_a_combinator_s_denial_carries_the_combinator(self, combinator: Any) -> None:
        # ``NoneOf`` denies when its check passes, so it is handed one that does.
        inner = _Admits() if combinator is NoneOf else _Denies()
        check = combinator(inner)
        spec = _spec([check])
        denied = _denied(lambda: authorize(spec, object()))
        assert isinstance(denied, PermissionCheckDenied)
        assert denied.check is check
        assert denied.check is not inner

    @pytest.mark.parametrize("question", ["class", "row", "scope"])
    def test_a_source_s_denial_carries_the_spec_it_compiles_to(self, question: str) -> None:
        # The check is asked about the compiled spec, so that is the one it
        # names; a transport holding the source compares through kernel_spec.
        # Each question takes the source directly, as a transport may hand it.
        check = _Denies() if question == "class" else _AdmitsTheClass()
        source, principal = Foreign(_spec([check], SelectorKind.RETRIEVE)), object()
        grant = Grant(kernel_spec(source), principal)
        call = {
            "class": lambda: authorize(source, principal),
            "row": lambda: authorize_target(source, principal, object(), grant=grant),
            "scope": lambda: authorize_scope(source, principal, [], grant=grant),
        }[question]
        denied = _denied(call)
        assert isinstance(denied, PermissionCheckDenied)
        assert denied.check is check
        assert denied.spec is kernel_spec(source)
        assert denied.spec is not source


class TestEveryOtherRefusalIsNot:
    """A ``NotPermitted`` the kernel raises for another reason, or that is raised at it, stays bare."""

    def test_the_grant_refusal(self) -> None:
        spec, principal = _spec([Unrestricted()]), object()
        other = Grant(_spec([Unrestricted()]), principal)
        denied = _denied(lambda: authorize(spec, principal, grant=other))
        assert type(denied) is NotPermitted

    def test_the_seeds_carrier_refusal(self) -> None:
        spec = _spec([Unrestricted()])
        carrier = resolve_seeds(spec, principal="ada", call_context={})
        denied = _denied(lambda: authorize(spec, "bob", seeds=carrier, call_context={}))
        assert type(denied) is NotPermitted

    @pytest.mark.parametrize("question", ["class", "row", "scope"])
    def test_a_check_raising_it_itself(self, question: str) -> None:
        spec, principal = _spec([_RaisesItself()], SelectorKind.RETRIEVE), object()
        grant = Grant(spec, principal)
        call = {
            "class": lambda: authorize(spec, principal),
            "row": lambda: authorize_target(spec, principal, object(), grant=grant),
            "scope": lambda: authorize_scope(spec, principal, [], grant=grant),
        }[question]
        denied = _denied(call)
        assert type(denied) is NotPermitted
        assert denied.message == "Raised by the check."

    def test_a_service_s_own(self) -> None:
        def service() -> None:
            raise NotPermitted("Refused by the service.")

        spec = ServiceSpec(service=service, permissions=[Unrestricted()], atomic=False)
        denied = _denied(lambda: dispatch(spec, principal=object(), arguments={}))
        assert type(denied) is NotPermitted
        assert denied.message == "Refused by the service."


class TestThroughDispatch:
    """The mark survives dispatch, and names the spec whose check denied."""

    def test_dispatch_raises_it_for_its_own_spec(self) -> None:
        check = _Denies()
        spec = ServiceSpec(service=lambda: None, permissions=[check], atomic=False)
        denied = _denied(lambda: dispatch(spec, principal=object(), arguments={}))
        assert isinstance(denied, PermissionCheckDenied)
        assert denied.check is check
        assert denied.spec is spec

    async def test_adispatch_raises_it_for_its_own_spec(self) -> None:
        check = _Denies()

        async def service() -> None: ...

        spec = ServiceSpec(service=service, permissions=[check], atomic=False)
        with pytest.raises(NotPermitted) as refused:
            await adispatch(spec, principal=object(), arguments={})
        assert isinstance(refused.value, PermissionCheckDenied)
        assert refused.value.check is check
        assert refused.value.spec is spec

    def test_an_inner_dispatch_s_denial_names_the_inner_spec(self) -> None:
        # The outer call's check passed; a dispatch its service made was denied.
        # The class alone cannot tell the two apart, so the spec does.
        check = _Denies()
        inner = ServiceSpec(service=lambda: None, permissions=[check], atomic=False)

        def service() -> None:
            dispatch(inner, principal=object(), arguments={})

        outer = ServiceSpec(service=service, permissions=[Unrestricted()], atomic=False)
        denied = _denied(lambda: dispatch(outer, principal=object(), arguments={}))
        assert isinstance(denied, PermissionCheckDenied)
        assert denied.spec is inner
        assert denied.spec is not outer
        assert denied.check is check
