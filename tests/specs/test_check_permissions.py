"""``check_permissions``: the one rule a ``permissions=`` declaration is held to."""

from __future__ import annotations

import re
from typing import Any

import pytest
from django.core.exceptions import ImproperlyConfigured

import django_service_specs
from django_service_specs.authorization.permission_check import PermissionCheck
from django_service_specs.authorization.unrestricted import Unrestricted
from django_service_specs.specs.check_permissions import check_permissions
from django_service_specs.specs.selector_spec import SelectorSpec
from django_service_specs.specs.service_spec import ServiceSpec
from django_service_specs.types.selector_kind import SelectorKind


def _service() -> None: ...


def _selector() -> list[Any]:
    return []


class _AsyncClassLevel(PermissionCheck):
    async def has_permission(self, principal: Any, spec: Any) -> bool:
        return False


class _AsyncObjectLevel(PermissionCheck):
    def has_permission(self, principal: Any, spec: Any) -> bool:
        return True

    async def has_object_permission(self, principal: Any, spec: Any, target: Any) -> bool:
        return False


class _AsyncScopeLevel(PermissionCheck):
    def has_permission(self, principal: Any, spec: Any) -> bool:
        return True

    async def has_scope_permission(self, principal: Any, spec: Any, scope: Any) -> bool:
        return False


class _AsyncGeneratorClassLevel(PermissionCheck):
    async def has_permission(self, principal: Any, spec: Any) -> Any:
        yield False


class TestAnAsyncPermissionCheckIsRefused:
    """A check method is read for truth from sync code; an ``async def`` one never refuses.

    One case per method, because the methods are named in one tuple and
    coverage cannot see a name dropped from it.
    """

    @pytest.mark.parametrize(
        ("check", "method"),
        [
            (_AsyncClassLevel(), "has_permission"),
            (_AsyncObjectLevel(), "has_object_permission"),
            (_AsyncScopeLevel(), "has_scope_permission"),
            (_AsyncGeneratorClassLevel(), "has_permission"),
        ],
    )
    def test_on_a_service_spec(self, check: PermissionCheck, method: str) -> None:
        named = f"ServiceSpec.permissions[1].{method} is {type(check).__name__}.{method}"
        with pytest.raises(ImproperlyConfigured, match=re.escape(named + ", an async callable")):
            ServiceSpec(service=_service, permissions=[Unrestricted(), check])

    def test_on_a_selector_spec(self) -> None:
        named = "SelectorSpec.permissions[0].has_object_permission is _AsyncObjectLevel"
        with pytest.raises(ImproperlyConfigured, match=re.escape(named)):
            SelectorSpec(
                kind=SelectorKind.RETRIEVE, selector=_selector, permissions=[_AsyncObjectLevel()]
            )


@pytest.mark.parametrize("empty", [[], ()], ids=["list", "tuple"])
@pytest.mark.parametrize(
    ("make", "label"),
    [
        (lambda permissions: ServiceSpec(service=_service, permissions=permissions), "ServiceSpec"),
        (
            lambda permissions: SelectorSpec(
                kind=SelectorKind.LIST, selector=_selector, permissions=permissions
            ),
            "SelectorSpec",
        ),
    ],
    ids=["service-spec", "selector-spec"],
)
def test_an_empty_permissions_sequence_is_refused(make: Any, label: str, empty: Any) -> None:
    # Every check passing is vacuously true of no checks, so an empty list
    # would let anyone run the operation; it is a list computed by accident
    # as often as a decision, and the decision has its own name.
    with pytest.raises(ImproperlyConfigured) as caught:
        make(empty)
    assert str(caught.value) == (
        f"{label}.permissions is empty, which would let anyone run it. Declare "
        "permissions=[Unrestricted()] to mean that."
    )


def test_it_is_the_root_s_own_function() -> None:
    assert django_service_specs.check_permissions is check_permissions


class TestAsAnyDeclarationOfChecks:
    """A transport holding checks on something other than a spec calls it with its own label."""

    def test_none_comes_back_as_none(self) -> None:
        assert check_permissions(None, label="Prompt") is None

    def test_a_list_comes_back_as_a_tuple_of_the_same_checks(self) -> None:
        first, second = Unrestricted(), Unrestricted()
        checked = check_permissions([first, second], label="Prompt")
        assert isinstance(checked, tuple)
        assert checked[0] is first
        assert checked[1] is second

    def test_an_empty_sequence_is_refused_under_the_label_handed(self) -> None:
        with pytest.raises(ImproperlyConfigured, match=r"^Prompt\.permissions is empty"):
            check_permissions([], label="Prompt")

    @pytest.mark.parametrize("not_a_sequence", ["Unrestricted", b"x", 3, {Unrestricted()}])
    def test_anything_but_a_sequence_is_refused(self, not_a_sequence: Any) -> None:
        with pytest.raises(
            ImproperlyConfigured,
            match=r"^Prompt\.permissions must be a sequence of PermissionCheck\.$",
        ):
            check_permissions(not_a_sequence, label="Prompt")

    def test_a_class_is_refused_by_name(self) -> None:
        with pytest.raises(
            ImproperlyConfigured, match=r"Prompt\.permissions holds the class Unrestricted"
        ):
            check_permissions([Unrestricted], label="Prompt")

    def test_a_value_that_is_not_a_check_is_refused_by_type(self) -> None:
        with pytest.raises(
            ImproperlyConfigured, match=r"Prompt\.permissions holds int, which is not"
        ):
            check_permissions([3], label="Prompt")

    def test_an_async_method_is_refused_under_the_label_and_index_handed(self) -> None:
        named = "Prompt.permissions[1].has_permission is _AsyncClassLevel.has_permission"
        with pytest.raises(ImproperlyConfigured, match=re.escape(named + ", an async callable")):
            check_permissions([Unrestricted(), _AsyncClassLevel()], label="Prompt")
